"""Factorised evaluation harness for InternScenes scene graphs.

Compares a *predicted* scene graph against a *reference* scene graph and
reports the factorised metrics defined in ``PLAN.md``:

* **nodes**    -- mAP, 3D IoU, per-category Macro-F1
* **relations**-- exact Triplet P / R / F1, mRecall@K
* **spatial**  -- Macro-F1 over the spatial predicates
* **hierarchy** -- parent-edge F1
* **affordance**-- AP / IoU of the affordance sets per node
* **calibration** -- ECE / Brier for VLM confidence tiers
* **efficiency**-- bytes / #edges / #nodes (for the Pareto report)

When no human Gold reference exists (v1), the *reference* can be the
deterministic graph and the *predicted* a graph augmented with the VLM
functional/affordance layer, so the harness measures the VLM's contribution.
A ``pareto()`` helper reports the accuracy-vs-efficiency frontier across a set
of configurations.
"""
from __future__ import annotations

import json
import math
from typing import Any

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _nodes(graph: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {n["id"]: n for n in graph.get("nodes", [])}


def _edges(graph: dict[str, Any]) -> list[dict[str, Any]]:
    return graph.get("edges", [])


def _bbox(n: dict[str, Any]) -> tuple[tuple[float, float, float],
                                      tuple[float, float, float]] | None:
    g = n.get("geometry") or {}
    mn = g.get("bbox_min_m")
    mx = g.get("bbox_max_m")
    if mn and mx:
        return tuple(mn), tuple(mx)
    return None


def _iou3d(a: dict[str, Any], b: dict[str, Any]) -> float:
    ba, bb = _bbox(a), _bbox(b)
    if ba is None or bb is None:
        return 0.0
    (amin, amax), (bmin, bmax) = ba, bb
    inter = max(0.0, min(amax[0], bmax[0]) - max(amin[0], bmin[0])) * \
            max(0.0, min(amax[1], bmax[1]) - max(amin[1], bmin[1])) * \
            max(0.0, min(amax[2], bmax[2]) - max(amin[2], bmin[2]))
    va = max(1e-9, (amax[0] - amin[0]) * (amax[1] - amin[1]) * (amax[2] - amin[2]))
    vb = max(1e-9, (bmax[0] - bmin[0]) * (bmax[1] - bmin[1]) * (bmax[2] - bmin[2]))
    union = va + vb - inter
    return inter / union if union > 0 else 0.0


def _affordances(n: dict[str, Any]) -> set[str]:
    a = n.get("affordances")
    if a is None:
        a = (n.get("attributes") or {}).get("affordances", [])
    return set(a or [])


def _f1(p: float, r: float) -> float:
    return 2 * p * r / (p + r) if (p + r) > 0 else 0.0


# ---------------------------------------------------------------------------
# node metrics
# ---------------------------------------------------------------------------
def node_metrics(ref: dict[str, Any], pred: dict[str, Any]) -> dict[str, Any]:
    rnodes = _nodes(ref)
    pnodes = _nodes(pred)
    # mAP: fraction of predicted nodes that exist in the reference (precision@recall)
    matched = [pid for pid in pnodes if pid in rnodes]
    ap = len(matched) / len(pnodes) if pnodes else 1.0
    # 3D IoU: average over matched nodes
    ious = [_iou3d(rnodes[pid], pnodes[pid]) for pid in matched]
    mean_iou = sum(ious) / len(ious) if ious else 0.0
    # per-category Macro-F1
    cats: set[str] = set()
    for n in rnodes.values():
        cats.add(n.get("category", "object"))
    for n in pnodes.values():
        cats.add(n.get("category", "object"))
    f1s: list[float] = []
    for c in sorted(cats):
        rc = sum(1 for n in rnodes.values() if n.get("category") == c)
        pc = sum(1 for n in pnodes.values() if n.get("category") == c)
        tp = sum(1 for pid in pnodes
                 if pnodes[pid].get("category") == c and pid in rnodes
                 and rnodes[pid].get("category") == c)
        p = tp / pc if pc else 0.0
        r = tp / rc if rc else 0.0
        f1s.append(_f1(p, r))
    macro_f1 = sum(f1s) / len(f1s) if f1s else 0.0
    return {
        "mAP": round(ap, 4),
        "mean_3d_IoU": round(mean_iou, 4),
        "macro_F1": round(macro_f1, 4),
        "num_matched": len(matched),
        "num_predicted": len(pnodes),
        "num_reference": len(rnodes),
    }


# ---------------------------------------------------------------------------
# relation metrics
# ---------------------------------------------------------------------------
def _triplets(edges: list[dict[str, Any]]) -> set[tuple[str, str, str]]:
    return {(e["source"], e.get("predicate", ""), e["target"]) for e in edges}


def relation_metrics(ref: dict[str, Any], pred: dict[str, Any],
                     predicates: set[str] | None = None) -> dict[str, Any]:
    rtr = _triplets(_edges(ref))
    ptr = _triplets(_edges(pred))
    if predicates is not None:
        rtr = {t for t in rtr if t[1] in predicates}
        ptr = {t for t in ptr if t[1] in predicates}
    tp = len(rtr & ptr)
    p = tp / len(ptr) if ptr else 0.0
    r = tp / len(rtr) if rtr else 0.0
    return {
        "precision": round(p, 4),
        "recall": round(r, 4),
        "F1": round(_f1(p, r), 4),
        "num_tp": tp,
        "num_predicted": len(ptr),
        "num_reference": len(rtr),
    }


SPATIAL = {"near", "far", "above", "below", "left", "right", "front", "behind",
           "touching", "distance", "inside"}
HIERARCHY = {"contains", "in_room", "part_of", "has_part", "parent_of"}


def mrecall_at_k(ref: dict[str, Any], pred: dict[str, Any], k: int = 8) -> float:
    """For each reference node, the fraction of its reference neighbours that
    appear among the predicted neighbours within the top-K edges."""
    rnodes = _nodes(ref)
    if not rnodes:
        return 1.0
    # build adjacency from edges (undirected for neighbour sets)
    def adj(g: dict[str, Any]) -> dict[str, set[str]]:
        a: dict[str, set[str]] = {}
        for e in _edges(g):
            s, t = e["source"], e["target"]
            a.setdefault(s, set()).add(t)
            a.setdefault(t, set()).add(s)
        return a
    ra, pa = adj(ref), adj(pred)
    recalls: list[float] = []
    for nid, rneigh in ra.items():
        if not rneigh:
            continue
        pset = pa.get(nid, set())
        hit = len(rneigh & pset)
        recalls.append(hit / len(rneigh))
    return sum(recalls) / len(recalls) if recalls else 0.0


# ---------------------------------------------------------------------------
# affordance metrics
# ---------------------------------------------------------------------------
def affordance_metrics(ref: dict[str, Any], pred: dict[str, Any]) -> dict[str, Any]:
    rnodes = _nodes(ref)
    pnodes = _nodes(pred)
    ious: list[float] = []
    aps: list[float] = []
    for pid in pnodes:
        pa = _affordances(pnodes[pid])
        if not pa:
            continue
        ra = _affordances(rnodes.get(pid, {}))
        ious.append(len(pa & ra) / len(pa | ra) if (pa | ra) else 1.0)
        aps.append(len(pa & ra) / len(pa) if pa else 1.0)
    return {
        "mean_IoU": round(sum(ious) / len(ious), 4) if ious else 0.0,
        "mean_AP": round(sum(aps) / len(aps), 4) if aps else 0.0,
        "num_nodes": len(pnodes),
    }


# ---------------------------------------------------------------------------
# VLM calibration
# ---------------------------------------------------------------------------
def calibration(ece_pairs: list[tuple[float, bool]]) -> dict[str, Any]:
    """ECE / Brier from (confidence, correct) pairs.

    ``ece_pairs`` is a list of ``(confidence, is_correct)`` for a set of
    predicted edges/nodes with VLM-derived confidence.
    """
    if not ece_pairs:
        return {"ECE": 0.0, "Brier": 0.0, "n": 0}
    n = len(ece_pairs)
    brier = sum((c - (1.0 if ok else 0.0)) ** 2 for c, ok in ece_pairs) / n
    # ECE with 10 equal-width bins
    n_bins = 10
    ece = 0.0
    for i in range(n_bins):
        lo, hi = i / n_bins, (i + 1) / n_bins
        bucket = [p for p in ece_pairs if (lo <= p[0] < hi) or (i == n_bins - 1 and p[0] == 1.0)]
        if not bucket:
            continue
        conf = sum(c for c, _ in bucket) / len(bucket)
        acc = sum(1.0 if ok else 0.0 for _, ok in bucket) / len(bucket)
        ece += (len(bucket) / n) * abs(acc - conf)
    return {"ECE": round(ece, 4), "Brier": round(brier, 4), "n": n}


# ---------------------------------------------------------------------------
# efficiency + pareto
# ---------------------------------------------------------------------------
def efficiency(graph: dict[str, Any]) -> dict[str, Any]:
    raw = json.dumps(graph)
    return {
        "bytes": len(raw.encode("utf-8")),
        "num_nodes": len(_nodes(graph)),
        "num_edges": len(_edges(graph)),
    }


def evaluate(reference: dict[str, Any], predicted: dict[str, Any]) -> dict[str, Any]:
    """Full factorised evaluation of ``predicted`` against ``reference``."""
    reference_triplets = _triplets(_edges(reference))
    vlm_calibration = []
    for edge in _edges(predicted):
        if edge.get("tier") != "vlm":
            continue
        confidence = edge.get("confidence")
        if confidence is None:
            continue
        triplet = (
            edge.get("source", ""),
            edge.get("predicate", ""),
            edge.get("target", ""),
        )
        vlm_calibration.append((float(confidence), triplet in reference_triplets))
    m = {
        "nodes": node_metrics(reference, predicted),
        "relations": relation_metrics(reference, predicted),
        "spatial": relation_metrics(reference, predicted, SPATIAL),
        "hierarchy": relation_metrics(reference, predicted, HIERARCHY),
        "affordance": affordance_metrics(reference, predicted),
        "calibration": calibration(vlm_calibration),
        "mRecall@8": round(mrecall_at_k(reference, predicted, 8), 4),
        "efficiency": efficiency(predicted),
    }
    return m


def pareto(entries: list[tuple[str, dict[str, Any]]]) -> dict[str, Any]:
    """Report the accuracy-vs-efficiency Pareto frontier.

    Each entry is ``(name, metrics_dict)``.  Accuracy is the mean of the
    reported F1 scores; efficiency cost is the sum of bytes + edges.  The
    frontier keeps entries that are not dominated on (accuracy up, cost down).
    """
    points: list[tuple[str, float, float]] = []
    for name, m in entries:
        acc = (m.get("relations", {}).get("F1", 0.0)
               + m.get("nodes", {}).get("macro_F1", 0.0)
               + m.get("spatial", {}).get("F1", 0.0)) / 3.0
        cost = m.get("efficiency", {}).get("bytes", 0)
        cost += m.get("efficiency", {}).get("num_edges", 0) * 8  # weight edges
        points.append((name, acc, cost))
    frontier: list[str] = []
    for name, acc, cost in points:
        is_dominated = False
        for other in points:
            if other[0] == name:
                continue
            if other[1] >= acc and other[2] <= cost and (other[1] > acc or other[2] < cost):
                is_dominated = True
                break
        if not is_dominated:
            frontier.append(name)
    return {
        "frontier": frontier,
        "points": {p[0]: {"accuracy": p[1], "cost": p[2]} for p in points},
        "num_entries": len(points),
    }


def self_report(graph: dict[str, Any]) -> dict[str, Any]:
    """Self-consistency report of a single graph (no external reference)."""
    from . import vlm_annotate as v
    rep = v.consistency_check(graph)
    eff = efficiency(graph)
    return {
        "consistent": rep["ok"],
        "issues": rep["num_issues"],
        "num_nodes": rep["num_nodes"],
        "num_edges": rep["num_edges"],
        "efficiency": eff,
        "by_family": (graph.get("stats") or {}).get("num_by_family", {}),
        "by_level": (graph.get("stats") or {}).get("num_by_level", {}),
    }


if __name__ == "__main__":  # pragma: no cover
    import argparse

    ap = argparse.ArgumentParser(description="Evaluate a scene graph")
    ap.add_argument("predicted", help="predicted scene_graph.json")
    ap.add_argument("--reference", help="reference scene_graph.json")
    ap.add_argument("--self", action="store_true", help="self-consistency only")
    args = ap.parse_args()
    pred = json.load(open(args.predicted, encoding="utf-8"))
    if args.self or args.reference is None:
        print(json.dumps(self_report(pred), indent=2))
    else:
        ref = json.load(open(args.reference, encoding="utf-8"))
        print(json.dumps(evaluate(ref, pred), indent=2))

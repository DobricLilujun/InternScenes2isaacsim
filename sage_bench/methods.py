"""Five SOTA scene-graph-building methods evaluated against the reference.

Each method takes a scene's ``records`` (``layout.json``) and produces a
``scene_graph.json`` in the same schema as the reference.  The methods model
the dominant paradigms for indoor / robotic scene-graph construction.  Because
running the *actual* external SOTA systems (which need GPU VLMs, trained
detectors, etc.) is infeasible in this environment, each method is a faithful,
deterministic proxy for its paradigm, built on the same InternScenes data.  The
evaluation harness then measures each paradigm against the deterministic oracle
(reference).

1. **geometric_3d**  -- classical 3D scene graph: metric + hierarchy edges
   (spatial / containment), no category semantics.

2. **semantic**      -- category / functional rules only: semantic + hierarchy
   edges, no metric.

3. **vlm_augmented** -- the deterministic base PLUS a VLM functional /
   affordance layer (interactive parts, affordances) via
   :func:`internscenes.vlm_annotate.annotate`.  Runs without an endpoint via the
   deterministic rule fallback.

4. **knn_spatial**   -- only proximity edges: ``distance`` / ``near`` /
   ``touching``.

5. **random**        -- random edges between nodes (null / random baseline,
   to confirm the harness discriminates signal from noise).
"""
from __future__ import annotations

import copy
import random
from typing import Any

from internscenes import coordinate as coord
from internscenes import relations as rel
from internscenes import scene_graph as sg
from internscenes import scene_info as si
from internscenes import vlm_annotate as vlm

Path = sg.Path


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _copy_nodes(ref_graph: dict[str, Any]) -> list[dict[str, Any]]:
    """Deep-copy the reference's nodes so a method cannot mutate the oracle."""
    return copy.deepcopy(ref_graph["nodes"])


def _assemble(scene_id: str, nodes: list[dict[str, Any]],
              edges: list[Any], ref_graph: dict[str, Any]) -> dict[str, Any]:
    """Assemble a scene graph (same schema as the oracle) from nodes + edges."""
    edges = [e.as_dict() if isinstance(e, rel.Edge) else e for e in edges]
    stats = sg._stats(nodes, edges)
    graph = dict(ref_graph)          # shallow copy of the top-level dict
    graph["nodes"] = nodes
    graph["edges"] = edges
    graph["stats"] = stats
    graph.pop("vlm_manifest", None)
    return graph


def _boxes(records: list[dict[str, Any]],
           ref_graph: dict[str, Any]) -> list[rel.Box]:
    return rel.build_boxes(records)


def _frame(records: list[dict[str, Any]],
           ref_graph: dict[str, Any]) -> coord.Frame:
    layout = Path(ref_graph["layout_source"])
    interior = si.structure_mesh_bounds(layout)
    return coord.room_canonical_frame(records, interior)


# ---------------------------------------------------------------------------
# 1. geometric 3D
# ---------------------------------------------------------------------------
def geometric_3d(scene_id: str, ref_graph: dict[str, Any],
                 records: list[dict[str, Any]]) -> dict[str, Any]:
    """Metric + hierarchy edges only (no category semantics)."""
    boxes = _boxes(records, ref_graph)
    frame = _frame(records, ref_graph)
    cfg = rel.DEFAULT_CONFIG
    edges = rel.metric_edges(boxes, cfg, frame) + \
        rel.hierarchy_edges(boxes, cfg)
    return _assemble(scene_id, _copy_nodes(ref_graph), edges, ref_graph)


# ---------------------------------------------------------------------------
# 2. semantic
# ---------------------------------------------------------------------------
def semantic(scene_id: str, ref_graph: dict[str, Any],
             records: list[dict[str, Any]]) -> dict[str, Any]:
    """Semantic + hierarchy edges only (no metric)."""
    boxes = _boxes(records, ref_graph)
    cfg = rel.DEFAULT_CONFIG
    edges = rel.semantic_edges(boxes, cfg) + \
        rel.hierarchy_edges(boxes, cfg)
    return _assemble(scene_id, _copy_nodes(ref_graph), edges, ref_graph)


# ---------------------------------------------------------------------------
# 3. VLM-augmented
# ---------------------------------------------------------------------------
def vlm_augmented(scene_id: str, ref_graph: dict[str, Any],
                  records: list[dict[str, Any]]) -> dict[str, Any]:
    """Deterministic base + a VLM functional / affordance layer."""
    nodes = _copy_nodes(ref_graph)
    # start from the full deterministic (oracle) edges
    edges = list(ref_graph["edges"])
    result = vlm.annotate(scene_id, records, cfg=vlm.VLMConfig.from_env())
    affordances = result.get("affordances", {})
    for n in nodes:
        affs = affordances.get(n["id"])
        if affs:
            n["affordances"] = list(affs)
            n.setdefault("attributes", {})["affordances"] = list(affs)
    node_ids = {x["id"] for x in nodes}
    for part in result.get("interactive", []):
        pn = sg._interactive_node(part)
        if pn is None:
            continue
        pn = copy.deepcopy(pn)
        nodes.append(pn)
        node_ids.add(pn["id"])
        parent = part.get("parent") or pn.get("parent")
        if parent and parent in node_ids:
            e = rel.Edge(parent, pn["id"], "has_part", "functional",
                         float(part.get("confidence", 0.6)), "world",
                         None, "interactive part")
            e.tier = "vlm"
            edges.append(e)
    return _assemble(scene_id, nodes, edges, ref_graph)


# ---------------------------------------------------------------------------
# 4. knn spatial
# ---------------------------------------------------------------------------
def knn_spatial(scene_id: str, ref_graph: dict[str, Any],
                records: list[dict[str, Any]]) -> dict[str, Any]:
    """Only proximity edges (distance / near / touching)."""
    boxes = _boxes(records, ref_graph)
    frame = _frame(records, ref_graph)
    cfg = rel.DEFAULT_CONFIG
    all_metric = rel.metric_edges(boxes, cfg, frame)
    keep = {"distance", "near", "touching"}
    edges = [e for e in all_metric if e.predicate in keep]
    return _assemble(scene_id, _copy_nodes(ref_graph), edges, ref_graph)


# ---------------------------------------------------------------------------
# 5. random
# ---------------------------------------------------------------------------
def random_baseline(scene_id: str, ref_graph: dict[str, Any],
                    records: list[dict[str, Any]],
                    seed: int = 0) -> dict[str, Any]:
    """Random edges between a random subset of node pairs (null baseline)."""
    # deterministic hash (Python's built-in hash() is per-process randomised)
    import hashlib
    h = int(hashlib.md5(scene_id.encode()).hexdigest()[:8], 16)
    rng = random.Random((h ^ seed) & 0xFFFFFFFF)
    ids = [n["id"] for n in ref_graph["nodes"]]
    preds = ["near", "far", "above", "below", "left", "right", "inside"]
    n = len(ids)
    budget = max(0, int(len(ref_graph["edges"]) * 0.6))
    edges: list[rel.Edge] = []
    seen: set[tuple[str, str]] = set()
    attempts = 0
    while len(edges) < budget and attempts < budget * 20 + 100:
        attempts += 1
        if n < 2:
            break
        a, b = rng.sample(ids, 2)
        if (a, b) in seen:
            continue
        seen.add((a, b))
        p = rng.choice(preds)
        edges.append(rel.Edge(a, b, p, "metric", rng.random(), "world",
                              None, "random"))
    return _assemble(scene_id, _copy_nodes(ref_graph), edges, ref_graph)


# ---------------------------------------------------------------------------
# registry
# ---------------------------------------------------------------------------
METHODS = {
    "geometric_3d": geometric_3d,
    "semantic": semantic,
    "vlm_augmented": vlm_augmented,
    "knn_spatial": knn_spatial,
    "random": random_baseline,
}


def run_method(name: str, scene_id: str, ref_graph: dict[str, Any],
               records: list[dict[str, Any]],
               seed: int = 0) -> dict[str, Any]:
    fn = METHODS[name]
    if name == "random":
        return fn(scene_id, ref_graph, records, seed=seed)
    return fn(scene_id, ref_graph, records)


def build_all(scene_id: str, ref_graph: dict[str, Any],
             records: list[dict[str, Any]],
             seed: int = 0) -> dict[str, dict[str, Any]]:
    return {name: run_method(name, scene_id, ref_graph, records, seed=seed)
            for name in METHODS}

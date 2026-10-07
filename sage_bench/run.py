"""Run the SAGE-Bench evaluation: 5 SOTA methods vs. the reference.

For each scene in the dataset:
  1. load the reference (gold) scene graph,
  2. run every method to get a predicted graph,
  3. evaluate the prediction against the reference
     (:func:`internscenes.evaluate_graph.evaluate`),
then aggregate per-scene metrics into a per-method leaderboard and an
accuracy-vs-efficiency Pareto frontier.
"""
from __future__ import annotations

import json
import pathlib
import statistics
from typing import Any

from internscenes import evaluate_graph as ev
from internscenes import scene_info as si
from internscenes import scene_graph as sg

from . import methods as M

ROOT = pathlib.Path(__file__).resolve().parent
DATASET_DIR = ROOT / "dataset"
RESULTS_DIR = ROOT / "results"

# metrics we aggregate (higher = better unless noted)
_AGG = [
    ("nodes", "macro_F1"),
    ("nodes", "mean_3d_IoU"),
    ("relations", "precision"),
    ("relations", "recall"),
    ("relations", "F1"),
    ("spatial", "F1"),
    ("hierarchy", "F1"),
    ("affordance", "mean_IoU"),
    ("mRecall@8", None),
]


def _flatten(m: dict[str, Any], section: str, key: str | None) -> float:
    v = m.get(section, {})
    if key is None:
        return float(v) if isinstance(v, (int, float)) else 0.0
    return float(v.get(key, 0.0))


def _load_records(scene_id: str) -> list[dict[str, Any]]:
    layout = DATASET_DIR.parent.parent / "data" / "Layout_info" / scene_id / "layout.json"
    return si.load_layout(layout)


def _per_scene(scene_id: str, ref_path: str) -> dict[str, Any]:
    ref = json.load(open(ref_path, encoding="utf-8"))
    records = _load_records(scene_id)
    out: dict[str, Any] = {"scene_id": scene_id, "by_method": {}}
    for name, fn in M.METHODS.items():
        try:
            pred = fn(scene_id, ref, records) if name != "random" \
                else fn(scene_id, ref, records, seed=0)
        except Exception as e:  # noqa: BLE001
            out["by_method"][name] = {"error": f"{type(e).__name__}: {e}"}
            continue
        m = ev.evaluate(ref, pred)
        out["by_method"][name] = m
    return out


def aggregate(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate per-scene metrics into per-method averages."""
    table: dict[str, dict[str, float]] = {}
    for r in results:
        for name, m in r["by_method"].items():
            if "error" in m:
                continue
            row = table.setdefault(name, {})
            for section, key in _AGG:
                row[section + ("." + key if key else "")] = \
                    row.get(section + ("." + key if key else ""), 0.0) \
                    + _flatten(m, section, key)
            row["_n"] = row.get("_n", 0) + 1
    # average
    for name, row in table.items():
        n = row.pop("_n", 1) or 1
        for k in list(row):
            row[k] = round(row[k] / n, 4)
    return table


def _leaderboard(table: dict[str, dict[str, float]]) -> list[dict[str, Any]]:
    rows = []
    for name, m in table.items():
        rows.append({
            "method": name,
            "relations_F1": m.get("relations.F1", 0.0),
            "relations_precision": m.get("relations.precision", 0.0),
            "relations_recall": m.get("relations.recall", 0.0),
            "nodes_macro_F1": m.get("nodes.macro_F1", 0.0),
            "nodes_mean_3d_IoU": m.get("nodes.mean_3d_IoU", 0.0),
            "spatial_F1": m.get("spatial.F1", 0.0),
            "hierarchy_F1": m.get("hierarchy.F1", 0.0),
            "affordance_IoU": m.get("affordance.mean_IoU", 0.0),
            "mRecall@8": m.get("mRecall@8", 0.0),
        })
    # rank by relations F1
    rows.sort(key=lambda x: x["relations_F1"], reverse=True)
    for i, r in enumerate(rows, 1):
        r["rank"] = i
    return rows


def main() -> None:
    manifest_path = DATASET_DIR / "manifest.json"
    if not manifest_path.exists():
        print("dataset not built; run: python -m sage_bench.dataset")
        raise SystemExit(1)
    manifest = json.load(manifest_path.open(encoding="utf-8"))
    if isinstance(manifest, dict):
        manifest = manifest.get("refs", manifest.get("scenes", []))

    print(f"== SAGE-Bench: {len(manifest)} scenes x {len(M.METHODS)} methods ==")
    results: list[dict[str, Any]] = []
    for rec in manifest:
        r = _per_scene(rec["scene_id"], rec["ref_path"])
        results.append(r)
        nm = r["by_method"]
        print(f"\n{rec['scene_id']} "
              f"({rec['num_objects']} objs, {rec['num_nodes']} ref nodes)")
        for name, m in nm.items():
            if "error" in m:
                print(f"    {name:14s}: ERROR {m['error']}")
                continue
            print(f"    {name:14s}: relF1={m['relations']['F1']:.3f} "
                  f"P={m['relations']['precision']:.3f} "
                  f"R={m['relations']['recall']:.3f} "
                  f"mRec@8={m['mRecall@8']:.3f}")

    table = aggregate(results)
    board = _leaderboard(table)
    # pareto frontier (accuracy vs efficiency)
    entries = [(name, results[0]["by_method"][name]) for name in M.METHODS
               if name in results[0].get("by_method", {})
               and "error" not in results[0]["by_method"][name]]

    report = {
        "dataset": str(DATASET_DIR),
        "num_scenes": len(manifest),
        "methods": list(M.METHODS),
        "leaderboard": board,
        "per_scene": results,
    }
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    (RESULTS_DIR / "leaderboard.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8")
    _write_markdown(report, RESULTS_DIR / "leaderboard.md")
    print("\n== LEADERBOARD (rank by relations F1) ==")
    for r in board:
        print(f"  #{r['rank']} {r['method']:14s} "
              f"relF1={r['relations_F1']:.3f} "
              f"mRec@8={r['mRecall@8']:.3f} "
              f"nodeF1={r['nodes_macro_F1']:.3f}")
    print(f"\nwrote {RESULTS_DIR}/leaderboard.md + leaderboard.json")


def _write_markdown(report: dict[str, Any], path: pathlib.Path) -> None:
    num_datasets = len({x["scene_id"].split("/", 1)[0]
                       for x in report["per_scene"]})
    lines = ["# SAGE-Bench — scene-graph method evaluation",
             "",
             f"**{report['num_scenes']} scenes** across {num_datasets} datasets, "
             f"**{len(report['methods'])} methods** vs. a deterministic oracle reference.",
             "",
             "| rank | method | rel. F1 | rel. P | rel. R | node F1 | 3D-IoU | spatial F1 | mRecall@8 |",
             "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for r in report["leaderboard"]:
        lines.append(
            f"| {r['rank']} | {r['method']} | {r['relations_F1']:.3f} | "
            f"{r['relations_precision']:.3f} | {r['relations_recall']:.3f} | "
            f"{r['nodes_macro_F1']:.3f} | {r['nodes_mean_3d_IoU']:.3f} | "
            f"{r['spatial_F1']:.3f} | {r['mRecall@8']:.3f} |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()

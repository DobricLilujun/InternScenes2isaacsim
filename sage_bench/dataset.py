"""Small scene-graph dataset for SAGE-Bench.

Selects a diverse, reproducible subset of InternScenes scenes across the four
source datasets (ScanNet, 3RScan, ARKitScenes, Matterport3D) and builds the
*reference* scene graph for each using the deterministic oracle
(:func:`internscenes.scene_graph.build_scene_graph`).

The reference is the "gold" graph every method is evaluated against.  It is the
best graph we can produce deterministically from ``layout.json`` (deterministic
metric + hierarchy + semantic edges), so it is a strong, reproducible baseline
rather than hand annotation.
"""
from __future__ import annotations

import glob
import json
import pathlib
from typing import Any

from internscenes import scene_graph as sg

ROOT = pathlib.Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "Layout_info"

# ---------------------------------------------------------------------------
# scene discovery
# ---------------------------------------------------------------------------
def _discover() -> dict[str, list[tuple[str, int]]]:
    """Return {dataset: [(scene_id, num_objects), ...]} across all datasets."""
    out: dict[str, list[tuple[str, int]]] = {}
    for f in glob.glob(str(DATA / "**" / "layout.json"), recursive=True):
        p = pathlib.Path(f)
        rel = p.relative_to(DATA)
        ds = rel.parts[0]
        scene_id = str(rel).replace("layout.json", "").rstrip("/")
        try:
            d = json.load(p.open(encoding="utf-8"))
            n = len(d) if isinstance(d, list) else 0
        except Exception:
            n = 0
        out.setdefault(ds, []).append((scene_id, n))
    for ds in out:
        out[ds].sort(key=lambda x: x[1])
    return out


def select_subset(discovered: dict[str, list[tuple[str, int]]],
                  per_dataset: int = 3, *,
                  want_sizes: tuple[int, ...] = (1, 3, 5)) -> list[str]:
    """Pick a diverse subset: ``per_dataset`` scenes from each dataset,
    chosen to span the object-count range (small / medium / large)."""
    chosen: list[str] = []
    for ds in sorted(discovered):
        scenes = discovered[ds]
        if not scenes:
            continue
        n = len(scenes)
        # spread indices across the sorted-by-size list
        picks = []
        for i in want_sizes:
            idx = i * (n - 1) // (len(want_sizes) - 1) if len(want_sizes) > 1 else n // 2
            picks.append(scenes[min(idx, n - 1)])
        # de-dupe
        seen = set()
        for sid, _ in picks:
            if sid not in seen:
                seen.add(sid)
                chosen.append(sid)
        # top up to per_dataset if we lost some to de-dup
        while len([c for c in chosen if c.startswith(ds + "/")]) < per_dataset and len(seen) < n:
            cand = scenes[len(seen)]
            if cand[0] not in seen:
                seen.add(cand[0])
                chosen.append(cand[0])
    return chosen


# ---------------------------------------------------------------------------
# reference (gold) graph
# ---------------------------------------------------------------------------
def reference_graph(scene_id: str) -> dict[str, Any]:
    """Build the reference (deterministic oracle) scene graph for a scene."""
    layout = DATA / scene_id / "layout.json"
    return sg.build_scene_graph(scene_id, layout)


def build_dataset(scenes: list[str],
                  out_dir: pathlib.Path) -> list[dict[str, Any]]:
    """Build reference graphs for ``scenes`` and persist them.

    Returns a list of ``{scene_id, num_objects, ref_path}`` records and writes
    one ``scene_graph.json`` per scene under ``out_dir``.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest: list[dict[str, Any]] = []
    for scene_id in scenes:
        try:
            g = reference_graph(scene_id)
        except Exception as e:  # noqa: BLE001
            print(f"  ! {scene_id}: skipped ({type(e).__name__}: {e})")
            continue
        p = out_dir / f"{scene_id.replace('/', '_')}.json"
        sg.write_scene_graph(g, p)
        manifest.append({
            "scene_id": scene_id,
            "dataset": scene_id.split("/", 1)[0],
            "num_objects": g["num_objects"],
            "num_nodes": g["stats"]["num_nodes"],
            "num_edges": g["stats"]["num_edges"],
            "ref_path": str(p),
        })
        print(f"  {scene_id}: {g['stats']['num_nodes']} nodes, "
              f"{g['stats']['num_edges']} edges")
    return manifest


if __name__ == "__main__":  # pragma: no cover
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-dataset", type=int, default=3)
    ap.add_argument("--out", default=str(ROOT / "sage_bench" / "dataset"))
    args = ap.parse_args()
    disc = _discover()
    scenes = select_subset(disc, per_dataset=args.per_dataset)
    print(f"selected {len(scenes)} scenes:")
    for s in scenes:
        print(f"  - {s}")
    out_dir = pathlib.Path(args.out)
    manifest = build_dataset(scenes, out_dir)
    (out_dir / "manifest.json").write_text(
        json.dumps({"scenes": scenes, "refs": manifest}, indent=2),
        encoding="utf-8")
    print(f"\nwrote {len(manifest)} reference graphs -> {args.out}")

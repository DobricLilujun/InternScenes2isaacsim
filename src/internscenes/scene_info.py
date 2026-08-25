"""Scene information extraction for InternScenes scenes.

Reads a scene's ``layout.json`` (the per-object layout produced by InternScenes)
and produces a compact, JSON-serialisable description of the scene:

* room dimensions (bounding box of all objects, in metres);
* the object list, with each object's category, source asset, world position,
  size (length/width/height) and rotation;
* a Unitree Go2 placement (collision-aware) so the downstream pipeline knows
  where a robot could stand;
* category frequency counts.

This module is deliberately free of heavy dependencies (only the standard
library plus ``numpy``) so it can be imported from the notebook, the CLI
wrappers in ``scripts/`` and the batch orchestrator alike.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import numpy as np

try:  # optional: reuse the collision-aware placement used by the topdown view
    from . import place_go2  # type: ignore  (relative import, package context)
except Exception:  # pragma: no cover - allow standalone import
    import sys
    # ``place_go2`` lives in the project's ``scripts/`` package; add it to the path.
    _HERE = Path(__file__).resolve().parent
    _PROJECT_ROOT = _HERE.parent.parent  # .../src/internscenes -> project root
    sys.path.insert(0, str(_PROJECT_ROOT / "scripts"))
    import place_go2  # type: ignore

logger = logging.getLogger(__name__)

# Canonical InternScenes category (dataset) names, in display order.
DATASETS: tuple[str, ...] = ("scannet", "3rscan", "arkitscenes", "matterport3d")

# ``layout.json`` entry shape: bbox = [cx, cy, cz, dx, dy, dz, rot_x, rot_y, rot_z]
# where (dx, dy, dz) are the *full* extents of the object's bounding box and the
# last three entries are Euler rotation angles (radians).
_BBOX_SIZE = 9


def load_layout(layout_path: str | Path) -> list[dict[str, Any]]:
    """Load and validate a ``layout.json`` file.

    Parameters
    ----------
    layout_path:
        Path to the ``layout.json`` for a scene.

    Returns
    -------
    list of object records (each a dict with at least ``category`` and ``bbox``).
    """
    layout_path = Path(layout_path)
    if not layout_path.exists():
        raise FileNotFoundError(f"layout.json not found: {layout_path}")
    try:
        with layout_path.open(encoding="utf-8") as fh:
            data = json.load(fh)
    except json.JSONDecodeError as exc:  # pragma: no cover - defensive
        raise ValueError(f"malformed JSON in {layout_path}") from exc
    if not isinstance(data, list):
        raise ValueError(f"expected a JSON list of objects in {layout_path}")
    return data


def _as_array(value: Any) -> np.ndarray | None:
    """Best-effort conversion of a bbox entry to a length-9 float array."""
    try:
        arr = np.asarray(value, dtype=float)
    except (TypeError, ValueError):
        return None
    if arr.ndim != 1 or len(arr) < 6:
        return None
    return arr


def room_dimensions(objs: list[dict[str, Any]]) -> dict[str, float]:
    """Return the room bounding box in metres derived from object extents.

    Each object's centre is offset by half its extent along each axis; the union
    of all those boxes yields the room's min/max coordinates and (width, depth,
    height).
    """
    xs: list[float] = []
    ys: list[float] = []
    zs: list[float] = []
    for obj in objs:
        b = _as_array(obj.get("bbox"))
        if b is None:
            continue
        cx, cy, cz, dx, dy, dz = b[0], b[1], b[2], b[3], b[4], b[5]
        xs += [cx - dx / 2, cx + dx / 2]
        ys += [cy - dy / 2, cy + dy / 2]
        zs += [cz - dz / 2, cz + dz / 2]
    if not xs:
        return {"min_x": 0.0, "min_y": 0.0, "min_z": 0.0,
                "max_x": 0.0, "max_y": 0.0, "max_z": 0.0,
                "width": 0.0, "depth": 0.0, "height": 0.0}
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    min_z, max_z = min(zs), max(zs)
    return {
        "min_x": round(float(min_x), 3), "min_y": round(float(min_y), 3), "min_z": round(float(min_z), 3),
        "max_x": round(float(max_x), 3), "max_y": round(float(max_y), 3), "max_z": round(float(max_z), 3),
        "width": round(float(max_x - min_x), 3),
        "depth": round(float(max_y - min_y), 3),
        "height": round(float(max_z - min_z), 3),
    }


def object_properties(obj: dict[str, Any]) -> dict[str, Any]:
    """Return a normalised, JSON-safe record of a single object.

    Exposes position, size (length/width/height) and rotation so the record is
    human- and machine-readable without requiring the raw ``bbox`` layout.
    """
    b = _as_array(obj.get("bbox"))
    if b is None:
        return {
            "id": obj.get("id"),
            "category": obj.get("category"),
            "model_uid": obj.get("model_uid", ""),
            "valid": False,
        }
    rec: dict[str, Any] = {
        "id": obj.get("id"),
        "category": obj.get("category"),
        "model_uid": obj.get("model_uid", ""),
        "valid": True,
        "position_m": {
            "x": round(float(b[0]), 4),
            "y": round(float(b[1]), 4),
            "z": round(float(b[2]), 4),
        },
        "size_m": {
            "length": round(float(b[3]), 4),
            "width": round(float(b[4]), 4),
            "height": round(float(b[5]), 4),
        },
    }
    if len(b) >= 9:
        rec["rotation_rad"] = {
            "x": round(float(b[6]), 4),
            "y": round(float(b[7]), 4),
            "z": round(float(b[8]), 4),
        }
    return rec


def category_counts(objs: list[dict[str, Any]]) -> dict[str, int]:
    """Return a {category: count} frequency table over the scene's objects."""
    counts: dict[str, int] = {}
    for obj in objs:
        cat = str(obj.get("category", "unknown"))
        counts[cat] = counts.get(cat, 0) + 1
    # most common first, ties broken alphabetically for stability
    return dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))


def go2_placement(objs: list[dict[str, Any]]) -> dict[str, Any]:
    """Return the collision-aware Go2 placement (best + nearest clearance)."""
    try:
        candidates = place_go2.best_placement(objs)
    except Exception as exc:  # pragma: no cover - placement is best-effort
        logger.warning("go2 placement failed: %s", exc)
        return {"valid": False, "reason": str(exc)}
    if not candidates:
        return {"valid": False, "reason": "no collision-free placement found"}
    clearance, gx, gy = candidates[0]
    return {
        "valid": True,
        "position_m": {"x": round(float(gx), 3), "y": round(float(gy), 3)},
        "clearance_m": round(float(clearance), 3),
    }


def build_scene_info(
    scene_id: str,
    layout_path: str | Path,
    renders: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Build the full scene-information dictionary for one scene.

    Parameters
    ----------
    scene_id:
        Logical scene identifier, e.g. ``"scannet/scene0001_00"``.
    layout_path:
        Path to that scene's ``layout.json``.
    renders:
        Optional mapping of output name -> absolute file path (e.g. the Blender
        perspective render and the top-down PNG), added for convenience.
    """
    objs = load_layout(layout_path)
    valid_objs = [o for o in objs if _as_array(o.get("bbox")) is not None]
    info: dict[str, Any] = {
        "scene_id": scene_id,
        "dataset": scene_id.split("/", 1)[0] if "/" in scene_id else "unknown",
        "layout_source": str(layout_path),
        "num_objects": len(objs),
        "num_valid_objects": len(valid_objs),
        "room_dimensions_m": room_dimensions(objs),
        "category_counts": category_counts(objs),
        "go2_placement": go2_placement(objs),
        "objects": [object_properties(o) for o in objs],
    }
    if renders:
        info["renders"] = {k: str(v) for k, v in renders.items()}
    return info


def write_scene_info(info: dict[str, Any], out_path: str | Path) -> None:
    """Write ``info`` to ``out_path`` as pretty-printed JSON, creating parents."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as fh:
        json.dump(info, fh, ensure_ascii=False, indent=2)
    logger.info("wrote scene info -> %s", out_path)


if __name__ == "__main__":  # pragma: no cover - manual smoke test
    import argparse

    logging.basicConfig(level=logging.INFO)
    ap = argparse.ArgumentParser(description="Export scene info JSON")
    ap.add_argument("scene", help="scene id, e.g. scannet/scene0001_00")
    ap.add_argument("--layout", help="layout.json path (default from data dir)")
    ap.add_argument("--out", help="output JSON path")
    args = ap.parse_args()
    here = Path(__file__).resolve().parent
    root = here.parent.parent
    layout = args.layout or str(root / "data" / "Layout_info" / args.scene / "layout.json")
    out = args.out or str(root / "output" / "info" / f"{args.scene.replace('/', '_')}.json")
    result = build_scene_info(args.scene, layout)
    write_scene_info(result, out)
    print(f"scene: {args.scene}  objects: {result['num_objects']}  "
          f"room: {result['room_dimensions_m']}")
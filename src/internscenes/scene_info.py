"""Scene information extraction for InternScenes scenes.

Reads a scene's ``layout.json`` (the per-object layout produced by InternScenes)
and produces a compact, JSON-serialisable description of the scene:

* room dimensions (bounding box of all objects, in metres);
* real interior room bounds derived from ``StructureMesh/*.glb`` when available;
* the object list, with each object's category, source asset, world position,
  size (length/width/height) and rotation;
* a Unitree Go2 placement (collision-aware) so the downstream pipeline knows
  where a robot could stand;
* category frequency counts.

This module tries to stay light on dependencies (only the standard library plus
``numpy``).  Reading the actual structural mesh bounds requires ``trimesh``; if
it is unavailable the code falls back to the layout-derived bounding box.
"""

from __future__ import annotations

import functools
import json
import logging
from pathlib import Path
from typing import Any

import numpy as np

try:
    import trimesh
except Exception:  # pragma: no cover - optional heavy dependency
    trimesh = None  # type: ignore

try:  # optional: reuse the collision-aware placement used by the topdown view
    from . import place_go2  # type: ignore  (relative import, package context)
except Exception:  # pragma: no cover - allow standalone import
    import sys
    # ``place_go2`` lives in the project's ``scripts/`` package; add it to the path.
    _HERE = Path(__file__).resolve().parent
    _PROJECT_ROOT = _HERE.parent.parent  # .../src/internscenes -> project root
    sys.path.insert(0, str(_PROJECT_ROOT / "scripts"))
    import place_go2  # type: ignore

try:
    from .compose import AssetMeshLoader  # type: ignore
except Exception:  # pragma: no cover - allow standalone import
    import sys
    _HERE = Path(__file__).resolve().parent
    _PROJECT_ROOT = _HERE.parent.parent
    sys.path.insert(0, str(_PROJECT_ROOT / "src"))
    from internscenes.compose import AssetMeshLoader  # type: ignore

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


def _average_image_color(img) -> tuple[float, float, float] | None:
    """Return the mean RGB of a PIL image, premultiplied by alpha if present."""
    try:
        from PIL import Image
    except Exception:
        return None
    if not isinstance(img, Image.Image):
        return None
    try:
        if img.mode == "P":
            img = img.convert("RGBA")
        small = img.resize((64, 64))
        arr = np.asarray(small, dtype=float) / 255.0
        if arr.ndim == 2:
            m = float(arr.mean())
            return (m, m, m)
        if arr.shape[-1] == 4:
            rgb = arr[..., :3]
            alpha = arr[..., 3:4]
            if alpha.sum() > 0:
                mean = (rgb * alpha).sum(axis=(0, 1)) / alpha.sum()
            else:
                mean = rgb.mean(axis=(0, 1))
        else:
            mean = arr[..., :3].mean(axis=(0, 1))
        if hasattr(mean, "__len__") and len(mean) == 1:
            mean = np.repeat(mean, 3)
        return tuple(round(float(x), 3) for x in mean[:3])
    except Exception:
        return None


def _material_color(material: Any) -> tuple[tuple[float, float, float], str] | None:
    """Extract a single RGB color from a trimesh PBR material."""
    if material is None:
        return None
    tex = getattr(material, "baseColorTexture", None)
    if tex is not None:
        rgb = _average_image_color(tex)
        if rgb is not None:
            return rgb, "baseColorTexture"
    factor = getattr(material, "baseColorFactor", None)
    if factor is not None:
        try:
            arr = np.asarray(factor, dtype=float).flatten()
            # trimesh sometimes stores factors as 0-255 integers.
            if arr.size >= 3:
                if arr[:3].max() > 1.0:
                    arr = arr / 255.0
                rgb = tuple(float(x) for x in arr[:3])
                return rgb, "baseColorFactor"
        except Exception:
            pass
    return None


@functools.lru_cache(maxsize=4096)
def _extract_object_color(uid: str) -> dict[str, Any] | None:
    """Load an object GLB and extract its representative base color."""
    if not uid or trimesh is None:
        return None
    try:
        loader = AssetMeshLoader()
        path = loader.resolve_mesh_path(uid)
        if path is None:
            return None
        mesh = trimesh.load(str(path))
    except Exception:
        return None

    colors: list[tuple[tuple[float, float, float], str]] = []
    if isinstance(mesh, trimesh.Scene):
        for geom in mesh.geometry.values():
            mat = getattr(getattr(geom, "visual", None), "material", None)
            c = _material_color(mat)
            if c is not None:
                colors.append(c)
    else:
        mat = getattr(getattr(mesh, "visual", None), "material", None)
        c = _material_color(mat)
        if c is not None:
            colors.append(c)

    if not colors:
        return None
    rgbs = [c[0] for c in colors if isinstance(c[0], (list, tuple, np.ndarray)) and len(c[0]) == 3]
    if not rgbs:
        return None
    rgb = tuple(round(float(x), 3) for x in np.mean(rgbs, axis=0))
    return {
        "r": rgb[0], "g": rgb[1], "b": rgb[2],
        "source": colors[0][1],
    }


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


def _mesh_bounds(path: Path) -> np.ndarray | None:
    """Return (2,3) axis-aligned bounds of a GLB mesh in the project frame.

    trimesh loads GLB files in their native frame (usually Y-up).  The project
    standard (matches ``layout.json`` and the USD stage) is Z-up, so we apply
    the inverse of the -90 deg X-axis rotation used in :mod:`compose` to bring
    the mesh into the unified frame.  The mapping is (x, y, z) -> (x, -z, y).

    We transform the vertices first and re-compute the axis-aligned bounds, so
    that the min/max order is preserved after the axis swap.
    """
    if trimesh is None or not path.exists():
        return None
    try:
        mesh = trimesh.load(str(path), force="mesh")
        if isinstance(mesh, trimesh.Scene):
            mesh = mesh.dump(concatenate=True)
        # GLB (Y-up) -> project (Z-up): (x, y, z) -> (x, -z, y)
        verts = np.asarray(mesh.vertices, dtype=float).copy()
        verts = np.column_stack([verts[:, 0], -verts[:, 2], verts[:, 1]])
        return np.array([verts.min(axis=0), verts.max(axis=0)], dtype=float)
    except Exception as exc:
        logger.debug("could not load mesh bounds from %s: %s", path, exc)
        return None


def structure_mesh_bounds(layout_path: str | Path) -> dict[str, Any] | None:
    """Compute real interior room bounds from ``StructureMesh/*.glb``.

    The floor mesh is the most reliable proxy for the walkable interior footprint;
    walls/ceilings are included when available so the caller can sanity-check the
    height.  The returned dict has the same shape as ``room_dimensions`` plus a
    ``source`` field indicating which files contributed.
    """
    layout_path = Path(layout_path)
    struct_dir = layout_path.parent / "StructureMesh"
    if not struct_dir.is_dir():
        return None

    floor_bounds = _mesh_bounds(struct_dir / "floor.glb")
    wall_bounds = _mesh_bounds(struct_dir / "wall.glb")
    ceiling_bounds = _mesh_bounds(struct_dir / "ceiling.glb")

    if floor_bounds is None:
        # Without a floor we cannot trust the footprint; fall back to layout bbox.
        return None

    min_x, min_y, min_z = floor_bounds[0]
    max_x, max_y, max_z = floor_bounds[1]

    # Height: use ceiling when available, otherwise wall top, otherwise floor Z.
    if ceiling_bounds is not None:
        max_z = max(max_z, ceiling_bounds[1, 2])
    if wall_bounds is not None:
        max_z = max(max_z, wall_bounds[1, 2])
        min_z = min(min_z, wall_bounds[0, 2])

    sources = ["floor"]
    if wall_bounds is not None:
        sources.append("wall")
    if ceiling_bounds is not None:
        sources.append("ceiling")

    return {
        "min_x": round(float(min_x), 3),
        "min_y": round(float(min_y), 3),
        "min_z": round(float(min_z), 3),
        "max_x": round(float(max_x), 3),
        "max_y": round(float(max_y), 3),
        "max_z": round(float(max_z), 3),
        "width": round(float(max_x - min_x), 3),
        "depth": round(float(max_y - min_y), 3),
        "height": round(float(max_z - min_z), 3),
        "source": "/".join(sources),
    }


def object_properties(obj: dict[str, Any]) -> dict[str, Any]:
    """Return a normalised, JSON-safe record of a single object.

    Exposes position, size (length/width/height), rotation and a
    representative base colour so the record is human- and machine-readable
    without requiring the raw ``bbox`` layout.
    """
    b = _as_array(obj.get("bbox"))
    uid = obj.get("model_uid", "")
    if b is None:
        rec: dict[str, Any] = {
            "id": obj.get("id"),
            "category": obj.get("category"),
            "model_uid": uid,
            "valid": False,
        }
        color = _extract_object_color(uid)
        if color is not None:
            rec["color"] = color
        return rec

    rec = {
        "id": obj.get("id"),
        "category": obj.get("category"),
        "model_uid": uid,
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
    color = _extract_object_color(uid)
    if color is not None:
        rec["color"] = color
    return rec


def category_counts(objs: list[dict[str, Any]]) -> dict[str, int]:
    """Return a {category: count} frequency table over the scene's objects."""
    counts: dict[str, int] = {}
    for obj in objs:
        cat = str(obj.get("category", "unknown"))
        counts[cat] = counts.get(cat, 0) + 1
    # most common first, ties broken alphabetically for stability
    return dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))


def go2_placement(objs: list[dict[str, Any]], layout_path: str | Path | None = None) -> dict[str, Any]:
    """Return the collision-aware Go2 placement (best + safety clearance).

    When ``layout_path`` is provided, the placement search is restricted to the
    interior polygon derived from ``StructureMesh/wall.glb`` (or the
    ``floor.glb`` bbox when the wall mesh is unavailable).

    The returned ``clearance_m`` is ``min(wall_gap, obstacle_gap)``: it rewards
    positions that are simultaneously far from walls and far from obstacles.
    """
    interior = structure_mesh_bounds(layout_path) if layout_path else None
    polygon = place_go2.interior_polygon(layout_path) if layout_path else None
    try:
        candidates = place_go2.best_placement(
            objs, interior_bounds=interior, polygon=polygon,
        )
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
    poly = place_go2.interior_polygon(layout_path)
    info: dict[str, Any] = {
        "scene_id": scene_id,
        "dataset": scene_id.split("/", 1)[0] if "/" in scene_id else "unknown",
        "layout_source": str(layout_path),
        "num_objects": len(objs),
        "num_valid_objects": len(valid_objs),
        "room_dimensions_m": room_dimensions(objs),
        "room_interior_bounds_m": structure_mesh_bounds(layout_path),
        "room_interior_polygon_xy_m": (
            [[round(float(x), 4), round(float(y), 4)] for x, y in poly]
            if poly is not None else None
        ),
        "category_counts": category_counts(objs),
        "go2_placement": go2_placement(objs, layout_path),
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
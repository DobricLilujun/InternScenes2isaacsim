"""Placement algorithm for a Unitree Go2 robot in an InternScenes scene.

Goal: find a floor location where the Go2 can stand without colliding with any
object and with enough clearance from walls.

Input : layout.json of a scene -> list of {id, category, model_uid, bbox}
        bbox = [cx, cy, cz, dx, dy, dz, rot_x, rot_y, rot_z]  (meters)

Method (collision-aware, floor-level):
  1. Room XY extent from all objects (centers +/- half-extents).
  2. Each object -> circle of radius max(dx,dy)/2 (+ clearance margin).
  3. Go2 -> circle of radius ~0.25 m (0.46 x 0.30 bbox).
  4. Grid-sample candidate points INSIDE the room footprint.
  5. Keep candidates whose Go2-circle does not intersect any obstacle circle.
  6. Score by clearance (distance to nearest obstacle).
  7. Return best candidate + nearest-obstacle distance + a few alternates.

Go2 dims (meters): 0.46 x 0.30 x 0.30.
"""

from __future__ import annotations

import json
import logging
import math
from pathlib import Path
from typing import Any

import numpy as np

try:
    from scipy.spatial import ConvexHull  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    ConvexHull = None  # type: ignore

try:
    from shapely.geometry import Polygon as SPoly, Point as SPoint  # type: ignore
    from shapely.ops import unary_union  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    SPoly = None  # type: ignore
    SPoint = None  # type: ignore
    unary_union = None  # type: ignore

try:
    from matplotlib.path import Path as MplPath  # for fast point-in-polygon
except Exception:  # pragma: no cover
    MplPath = None  # type: ignore

logger = logging.getLogger(__name__)

CLEARANCE_MARGIN = 0.12  # extra clearance beyond object bbox (m)
GO2_R = 0.25            # Go2 footprint radius (m) ~ half of 0.50 diag

# A parsed object record: a tuple of (centre_x, centre_y, radius, category).
Obstacle = tuple[float, float, float, str]


def _point_in_polygon(x: float, y: float, polygon: np.ndarray | None) -> bool:
    """Return True if (x, y) is inside the polygon with a GO2_R wall buffer.

    A ``None`` polygon means "no polygon constraint" -> always inside.
    Uses ``shapely`` when available (supports concave polygons and proper
    negative buffer); otherwise falls back to matplotlib ``Path`` for convex
    polygons, then ray casting as a last resort.
    """
    if polygon is None or len(polygon) < 3:
        return True
    if SPoly is not None and SPoint is not None:
        try:
            poly = SPoly(polygon)
            # Negative buffer shrinks the walkable area by GO2_R so the robot
            # centre stays clear of the walls.
            buffered = poly.buffer(-GO2_R)
            if buffered.is_empty:
                return False
            return buffered.contains(SPoint(x, y))
        except Exception:
            pass
    if MplPath is not None:
        return MplPath(polygon).contains_point((x, y), radius=-GO2_R)
    # Fallback: ray casting without buffer.
    inside = False
    n = len(polygon)
    j = n - 1
    for i in range(n):
        xi, yi = polygon[i]
        xj, yj = polygon[j]
        if ((yi > y) != (yj > y)) and (
            x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-12) + xi
        ):
            inside = not inside
        j = i
    return inside


def _wall_footprint_polygon(mesh_path: Path) -> np.ndarray | None:
    """Extract the room exterior polygon from a wall GLB.

    The wall mesh is a thin shell. Its triangles projected onto the XY plane
    form a ring whose exterior boundary is the inner surface of the walls, i.e.
    the walkable room outline (possibly concave).

    Returns an ``(N, 2)`` array of CCW vertices, or ``None`` on failure.
    """
    if SPoly is None or unary_union is None:
        return None
    try:
        import trimesh  # local import: this module is otherwise light-weight
    except Exception:
        return None
    try:
        mesh = trimesh.load(str(mesh_path), force="mesh")
        if isinstance(mesh, trimesh.Scene):
            mesh = mesh.dump(concatenate=True)
        verts = np.asarray(mesh.vertices, dtype=float).copy()
        # GLB (Y-up) -> project (Z-up): (x, y, z) -> (x, -z, y)
        verts = np.column_stack([verts[:, 0], -verts[:, 2], verts[:, 1]])
        faces = np.asarray(mesh.faces, dtype=int)
        polys = []
        for tri in faces:
            pts = verts[tri, :2]
            try:
                polys.append(SPoly(pts))
            except Exception:
                pass
        if not polys:
            return None
        union = unary_union(polys)
        if union.is_empty or not hasattr(union, "exterior"):
            return None
        coords = np.asarray(union.exterior.coords, dtype=float)[:-1]  # close ring
        # Ensure CCW winding for matplotlib / shapely consistency.
        if _signed_area(coords) < 0:
            coords = coords[::-1]
        return coords
    except Exception as exc:
        logger.debug("could not extract wall footprint from %s: %s", mesh_path, exc)
        return None


def _signed_area(poly: np.ndarray) -> float:
    """Return 2x the signed area of a simple polygon (shoelace formula)."""
    if len(poly) < 3:
        return 0.0
    x0, y0 = poly[:, 0], poly[:, 1]
    x1, y1 = np.roll(x0, -1), np.roll(y0, -1)
    return float(np.sum(x0 * y1 - x1 * y0))


def _convex_hull_polygon(xy: np.ndarray) -> np.ndarray | None:
    """Return the CCW convex hull of 2D points, or None if not possible."""
    if ConvexHull is None or len(xy) < 3:
        return None
    try:
        hull = ConvexHull(xy)
        poly = xy[hull.vertices]
        if _signed_area(poly) < 0:
            poly = poly[::-1]
        return poly
    except Exception:
        return None


def interior_polygon(layout_path: str | Path) -> np.ndarray | None:
    """Compute the interior walkable polygon (XY outline) from ``wall.glb``.

    Returns an ``(N, 2)`` array of vertices ordered counter-clockwise, or
    ``None`` if the file is missing/unreadable.

    The preferred path uses ``shapely`` to extract the possibly-concave
    exterior boundary of the wall footprint.  If shapely is unavailable or the
    wall mesh cannot be interpreted, a convex hull of the wall vertices is
    returned as a conservative fallback.
    """
    p = Path(layout_path)
    wall = p.parent / "StructureMesh" / "wall.glb"
    if not wall.exists():
        return None

    # 1) Try shapely-based concave footprint extraction.
    footprint = _wall_footprint_polygon(wall)
    if footprint is not None and len(footprint) >= 3:
        return footprint

    # 2) Fallback: convex hull of unique wall vertices.
    try:
        import trimesh  # local import
        mesh = trimesh.load(str(wall), force="mesh")
        if isinstance(mesh, trimesh.Scene):
            mesh = mesh.dump(concatenate=True)
        verts = np.asarray(mesh.vertices, dtype=float).copy()
        verts = np.column_stack([verts[:, 0], -verts[:, 2], verts[:, 1]])
        xy = np.unique(np.round(verts[:, :2], 4), axis=0)
    except Exception as exc:
        logger.debug("could not load wall polygon from %s: %s", wall, exc)
        return None
    if len(xy) < 3:
        return None
    return _convex_hull_polygon(xy) or xy


def load_layout(p: str | Path) -> list[dict]:
    """Load and return the objects list from a layout.json file."""
    p = Path(p)
    if not p.exists():
        raise FileNotFoundError(f"layout.json not found: {p}")
    with p.open(encoding="utf-8") as fh:
        return json.load(fh)


def _bbox(o: dict) -> list[float] | None:
    """Return a usable bbox list for an object, or None if invalid/absent."""
    b = o.get("bbox")
    if b is None:
        return None
    try:
        return [float(x) for x in b]
    except (TypeError, ValueError):
        logger.debug("skipping object with invalid bbox: %r", o.get("id"))
        return None


def room_bounds(objs: list[dict],
                interior_bounds: dict[str, Any] | None = None) -> tuple[float, float, float, float]:
    """Return (min_x, max_x, min_y, max_y) of the walkable room footprint.

    If ``interior_bounds`` is supplied (e.g. from ``StructureMesh/floor.glb``),
    use that rectangle directly; otherwise fall back to the union of object
    extents from the layout file.  The footprint is shrunk inward by ``GO2_R``
    so the robot centre always stays clear of the walls.
    """
    if interior_bounds is not None:
        bx0 = float(interior_bounds["min_x"]) + GO2_R
        bx1 = float(interior_bounds["max_x"]) - GO2_R
        by0 = float(interior_bounds["min_y"]) + GO2_R
        by1 = float(interior_bounds["max_y"]) - GO2_R
        # If the room is too tight to shrink on both sides, fall through to the
        # layout-based fallback below.
        if bx1 - bx0 > 0 and by1 - by0 > 0:
            return (bx0, bx1, by0, by1)
    xs: list[float] = []
    ys: list[float] = []
    for o in objs:
        b = _bbox(o)
        if b is None:
            continue
        cx, cy, dx, dy = b[0], b[1], b[3], b[4]
        xs += [cx - dx / 2, cx + dx / 2]
        ys += [cy - dy / 2, cy + dy / 2]
    if not xs:
        return (-1.0, 1.0, -1.0, 1.0)
    return (min(xs), max(xs), min(ys), max(ys))


def obstacle_circles(objs: list[dict], margin: float = CLEARANCE_MARGIN) -> list[Obstacle]:
    """Turn each object into a collision circle (cx, cy, radius, category)."""
    out: list[Obstacle] = []
    for o in objs:
        b = _bbox(o)
        if b is None:
            continue
        cx, cy, dx, dy = b[0], b[1], b[3], b[4]
        r = max(dx, dy) / 2 + margin
        out.append((cx, cy, r, o.get("category", "")))
    return out


def collides(cx: float, cy: float, obs: list[Obstacle]) -> bool:
    """True if the Go2 circle at (cx, cy) intersects any obstacle circle."""
    for ox, oy, r, _ in obs:
        if math.hypot(cx - ox, cy - oy) < GO2_R + r:
            return True
    return False


def nearest_clearance(cx: float, cy: float, obs: list[Obstacle]) -> float:
    """Smallest gap (m) between the Go2 at (cx, cy) and any obstacle."""
    return min((math.hypot(cx - ox, cy - oy) - r for ox, oy, r, _ in obs),
               default=999.0)


def _wall_clearance(cx: float, cy: float, polygon: np.ndarray | None) -> float:
    """Smallest gap (m) between the Go2 centre and the room walls.

    Returns a large value when no polygon is available.
    """
    if polygon is None or len(polygon) < 3:
        return 999.0
    if SPoly is not None and SPoint is not None:
        try:
            boundary = SPoly(polygon).boundary
            dist = boundary.distance(SPoint(cx, cy))
            # The polygon boundary is the inner wall surface; subtract GO2_R
            # so the clearance represents free space between robot edge and wall.
            return max(0.0, dist - GO2_R)
        except Exception:
            pass
    return 999.0


def best_placement(objs: list[dict], n_grid: int = 80,
                   margin: float = CLEARANCE_MARGIN,
                   interior_bounds: dict[str, Any] | None = None,
                   polygon: np.ndarray | None = None) -> list[tuple[float, float, float]]:
    """Return collision-free placements sorted by descending clearance.

    Each entry is (clearance, x, y); an empty list means no valid placement.

    The score of a candidate is ``min(wall_clearance, obstacle_clearance)``,
    so the chosen position is simultaneously far from walls and far from
    obstacles.  When ``polygon`` is supplied (e.g. from
    ``StructureMesh/wall.glb``'s exterior footprint), the candidate grid is
    clipped to that polygon and a GO2_R margin so the robot centre stays clear
    of the walls.  The polygon may be concave.
    """
    obs = obstacle_circles(objs, margin=margin)
    if polygon is not None and len(polygon) >= 3:
        bx0, bx1, by0, by1 = polygon[:, 0].min(), polygon[:, 0].max(), polygon[:, 1].min(), polygon[:, 1].max()
    else:
        bx0, bx1, by0, by1 = room_bounds(objs, interior_bounds=interior_bounds)
    # Increase density for small/irregular rooms so concave corners still
    # yield reasonable candidate coverage.
    span = max(bx1 - bx0, by1 - by0, 1e-6)
    n_grid = max(40, min(n_grid, int(120 * span / 10.0)))
    cand: list[tuple[float, float, float]] = []
    for i in range(n_grid + 1):
        for j in range(n_grid + 1):
            cx = bx0 + (bx1 - bx0) * i / n_grid
            cy = by0 + (by1 - by0) * j / n_grid
            if not _point_in_polygon(cx, cy, polygon):
                continue
            if collides(cx, cy, obs):
                continue
            obstacle_gap = nearest_clearance(cx, cy, obs)
            wall_gap = _wall_clearance(cx, cy, polygon)
            score = min(obstacle_gap, wall_gap)
            cand.append((score, cx, cy))
    cand.sort(key=lambda t: t[0], reverse=True)
    return cand


def place_go2(layout_path: str | Path, top_n: int = 5) -> list[tuple[float, float, float]]:
    """Compute and print the best Go2 placements for a scene's layout.json."""
    objs = load_layout(layout_path)
    cand = best_placement(objs)
    print(f"scene: {layout_path}")
    print(f"objects: {len(objs)}, valid candidates: {len(cand)}")
    for nearest, cx, cy in cand[:top_n]:
        print(f"  pos=({cx:6.2f},{cy:6.2f})  clearance_to_nearest={nearest:5.2f}m")
    return cand


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Find Go2 placement for a scene layout")
    ap.add_argument("layout", help="path to layout.json")
    ap.add_argument("--top-n", type=int, default=5, help="print top N placements")
    args = ap.parse_args()
    place_go2(args.layout, top_n=args.top_n)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Reference-frame standard for the InternScenes scene-graph dataset.

The scene graph needs *relative* predicates (left / right / front / behind /
above / below) to be unambiguous.  Because InternScenes scenes are static (no
moving camera), a relative predicate must always be tied to an **explicit
reference frame** stored on the edge.  This module defines that standard.

Two frames are supported (see ``docs/SCENE_GRAPH.md``):

* ``room_canonical`` (the default) -- gravity-aligned: up = +Z, and the
  horizontal "forward" axis is the principal axis of the room (the direction of
  maximum variance of the object centroids in the XY plane, with a deterministic
  sign convention).  left / right / front / behind are defined relative to this
  forward axis.
* ``object_intrinsic`` -- the local frame of a single object, derived from its
  Euler rotation, used for object-relative predicates (e.g. "the handle is on
  the front of the cabinet").

Gravity-aligned predicates (above / below, near / far, distance, inside) do not
need a horizontal frame and therefore carry ``reference_frame = "world"``.

A frame is represented by an orthonormal 3x3 rotation matrix ``R`` whose columns
are ``[right, forward, up]`` expressed in the world (gravity-aligned) frame, plus
an origin.  ``world_to_frame`` = ``R^T @ (p - origin)`` and
``frame_to_world`` = ``R @ p' + origin``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence

import numpy as np

# The default (gravity-aligned) frame identifier.
WORLD = "world"
ROOM_CANONICAL = "room_canonical"
OBJECT_INTRINSIC = "object_intrinsic"


def _as_points(records: Sequence[dict[str, Any]]) -> np.ndarray:
    """Return an (N, 3) array of object centres from a list of records.

    Accepts either raw ``layout.json`` entries (``bbox[9]``) or normalised
    ``object_properties`` records (``position_m``).  Invalid records are skipped.
    """
    pts: list[list[float]] = []
    for r in records:
        b = r.get("bbox")
        if isinstance(b, (list, tuple)) and len(b) >= 6:
            pts.append([float(b[0]), float(b[1]), float(b[2])])
            continue
        pos = r.get("position_m")
        if isinstance(pos, dict):
            pts.append([float(pos.get("x", 0.0)), float(pos.get("y", 0.0)),
                        float(pos.get("z", 0.0))])
    return np.asarray(pts, dtype=float) if pts else np.zeros((0, 3))


def _unit(v: np.ndarray) -> np.ndarray:
    n = float(np.linalg.norm(v))
    return v / n if n > 1e-9 else np.zeros_like(v)


@dataclass
class Frame:
    """An orthonormal reference frame with an origin."""

    name: str
    origin: np.ndarray = field(default_factory=lambda: np.zeros(3))
    # columns: [right, forward, up] in world coordinates
    matrix: np.ndarray = field(default_factory=lambda: np.eye(3))
    method: str = ""
    source: str = ""

    def world_to_frame(self, p: np.ndarray) -> np.ndarray:
        """Map a world point (or (N,3) array) into the local frame."""
        p = np.asarray(p, dtype=float)
        single = p.ndim == 1
        if single:
            p = p[None, :]
        out = (p - self.origin) @ self.matrix
        return out[0] if single else out

    def to_world(self, p: np.ndarray) -> np.ndarray:
        p = np.asarray(p, dtype=float)
        single = p.ndim == 1
        if single:
            p = p[None, :]
        out = p @ self.matrix.T + self.origin
        return out[0] if single else out

    def forward(self) -> np.ndarray:
        return self.matrix[:, 1]

    def up(self) -> np.ndarray:
        return self.matrix[:, 2]

    def right(self) -> np.ndarray:
        return self.matrix[:, 0]

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "origin": [round(float(x), 4) for x in self.origin],
            "forward": [round(float(x), 4) for x in self.matrix[:, 1]],
            "right": [round(float(x), 4) for x in self.matrix[:, 0]],
            "up": [round(float(x), 4) for x in self.matrix[:, 2]],
            "matrix": [[round(float(x), 4) for x in row] for row in self.matrix],
            "method": self.method,
            "source": self.source,
        }


# ---------------------------------------------------------------------------
# world frame
# ---------------------------------------------------------------------------
def world_frame() -> Frame:
    """The gravity-aligned world frame (Z up), origin at the world origin."""
    return Frame(name=WORLD, origin=np.zeros(3), matrix=np.eye(3),
                 method="gravity-aligned", source="world")


# ---------------------------------------------------------------------------
# room-canonical frame
# ---------------------------------------------------------------------------
def room_canonical_frame(
    records: Sequence[dict[str, Any]],
    interior_bounds: dict[str, Any] | None = None,
    default_forward: tuple[float, float] | None = None,
) -> Frame:
    """Build the room-canonical frame for a scene.

    up = +Z (gravity).  The horizontal "forward" axis is the principal axis of
    the room, taken as the principal component (largest variance) of the object
    centroids in the XY plane.  A deterministic sign convention fixes the
    otherwise-ambiguous eigenvector sign: forward.x > 0, else forward.y > 0,
    else the fallback ``default_forward`` (the longer room axis), else +X.
    """
    pts = _as_points(records)
    origin = np.zeros(3)
    if pts.shape[0] >= 2:
        origin = pts.mean(axis=0)
    xy = pts[:, :2]

    forward = None
    method = "PCA(principal axis of object centroids, XY)"
    if xy.shape[0] >= 3:
        centered = xy - xy.mean(axis=0)
        cov = centered.T @ centered
        # symmetric eigendecomposition; eigenvalues in descending order
        vals, vecs = np.linalg.eigh(cov)
        order = np.argsort(vals)[::-1]
        principal = vecs[order[0]]
        # deterministic sign: prefer +X, then +Y
        if principal[0] < 0:
            principal = -principal
        elif abs(principal[0]) < 1e-9 and principal[1] < 0:
            principal = -principal
        forward = _unit(np.array([principal[0], principal[1], 0.0]))
        if np.linalg.norm(forward) < 1e-9:
            forward = None
    else:
        method = "insufficient objects; fallback axis"

    if forward is None or np.linalg.norm(forward) < 1e-9:
        # Fallback 1: the longer horizontal room dimension (from interior bounds).
        fwd = None
        if interior_bounds is not None:
            w = abs(float(interior_bounds.get("width", 0.0)))
            d = abs(float(interior_bounds.get("depth", 0.0)))
            if w > 1e-6 or d > 1e-6:
                fwd = np.array([d, w, 0.0])  # x ~ depth span, y ~ width span
                if np.linalg.norm(fwd) > 1e-9:
                    forward = _unit(fwd)
                    method = "fallback(longer room axis)"
        if forward is None:
            # Fallback 2: an explicit default, else +X.
            if default_forward is not None:
                forward = _unit(np.array([default_forward[0], default_forward[1], 0.0]))
            if forward is None or np.linalg.norm(forward) < 1e-9:
                forward = np.array([1.0, 0.0, 0.0])
            method = "fallback(+X)"

    up = np.array([0.0, 0.0, 1.0])
    right = _unit(np.cross(forward, up))
    # Guarantee right-handed [right, forward, up]: right x forward == up.
    if np.dot(np.cross(right, forward), up) < 0:
        right = -right
    matrix = np.column_stack([right, forward, up])
    return Frame(
        name=ROOM_CANONICAL,
        origin=origin,
        matrix=matrix,
        method=method,
        source="room_canonical",
    )


# ---------------------------------------------------------------------------
# object-intrinsic frame
# ---------------------------------------------------------------------------
def _euler_to_matrix(rot_x: float, rot_y: float, rot_z: float) -> np.ndarray:
    """Extrinsic XYZ Euler rotation -> 3x3 matrix (matches trimesh/compose)."""
    rx, ry, rz = float(rot_x), float(rot_y), float(rot_z)
    cx, sx = np.cos(rx), np.sin(rx)
    cy, sy = np.cos(ry), np.sin(ry)
    cz, sz = np.cos(rz), np.sin(rz)
    Rx = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]])
    Ry = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
    Rz = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]])
    return Rz @ Ry @ Rx


def object_intrinsic_frame(record: dict[str, Any], base: str = "world") -> Frame:
    """Build the object-intrinsic frame for a single object record.

    The object's local axes are its rotation applied to the world axes; forward
    is the object's local +X, up is its local +Z.  Used for object-relative
    predicates (e.g. "the handle is on the front of the door").
    """
    rot = record.get("rotation_rad")
    if isinstance(rot, dict):
        rx, ry, rz = rot.get("x", 0.0), rot.get("y", 0.0), rot.get("z", 0.0)
    else:
        b = record.get("bbox")
        if isinstance(b, (list, tuple)) and len(b) >= 9:
            rx, ry, rz = float(b[6]), float(b[7]), float(b[8])
        else:
            rx, ry, rz = 0.0, 0.0, 0.0
    m = _euler_to_matrix(rx, ry, rz)
    # The Frame class treats matrix columns as [right, forward, up].
    # The object's local axes in world coords are the columns of ``m``:
    # m[:,0] = local +X (forward), m[:,1] = local +Y (right), m[:,2] = local +Z (up).
    # Reorder so that column 1 (forward) is the object's local +X.
    matrix = np.column_stack([m[:, 1], m[:, 0], m[:, 2]])
    pos = record.get("position_m")
    if isinstance(pos, dict):
        origin = np.array([float(pos.get("x", 0.0)), float(pos.get("y", 0.0)),
                          float(pos.get("z", 0.0))])
    else:
        b = record.get("bbox")
        if isinstance(b, (list, tuple)) and len(b) >= 3:
            origin = np.array([float(b[0]), float(b[1]), float(b[2])])
        else:
            origin = np.zeros(3)
    return Frame(name=OBJECT_INTRINSIC, origin=origin, matrix=matrix,
                 method="object Euler rotation", source=base)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def resolve_frame(
    reference_frame: str | Frame | None,
    records: Sequence[dict[str, Any]],
    interior_bounds: dict[str, Any] | None = None,
    record: dict[str, Any] | None = None,
) -> Frame:
    """Resolve a frame specifier into a :class:`Frame`.

    ``reference_frame`` may be a :class:`Frame`, the name ``"world"``,
    ``"room_canonical"``, ``"object_intrinsic"``, or ``None`` (-> room_canonical).
    """
    if isinstance(reference_frame, Frame):
        return reference_frame
    name = reference_frame or ROOM_CANONICAL
    if name == WORLD or name is None and reference_frame is None:
        return world_frame()
    if name == ROOM_CANONICAL:
        return room_canonical_frame(records, interior_bounds)
    if name == OBJECT_INTRINSIC:
        if record is None:
            return world_frame()
        return object_intrinsic_frame(record)
    return world_frame()


def relative_horizontal(
    a: dict[str, Any],
    b: dict[str, Any],
    frame: Frame,
) -> str:
    """Classify the horizontal relationship of ``b`` relative to ``a``.

    Returns one of ``"front" / "behind" / "left" / "right"`` using the given
    frame's forward/right axes.  The vector ``b - a`` is projected into the
    frame; whichever horizontal component (forward vs right) dominates wins, with
    sign giving front/behind (or left/right).
    """
    pa = _record_point(a)
    pb = _record_point(b)
    v = frame.world_to_frame(pb - pa)  # local coordinates
    fwd, rgt = float(v[1]), float(v[0])
    if abs(fwd) >= abs(rgt):
        return "front" if fwd > 0 else "behind"
    return "left" if rgt > 0 else "right"


def vertical_relation(a: dict[str, Any], b: dict[str, Any],
                      eps: float = 0.02) -> str:
    """Return ``"above" / "below" / "level"`` for ``a`` relative to ``b``.

    Compares the vertical extents of the two objects (gravity-aligned).
    """
    az0, az1 = _z_extent(a)
    bz0, bz1 = _z_extent(b)
    if az0 > bz1 - eps:
        return "above"
    if az1 < bz0 + eps:
        return "below"
    return "level"


def _record_point(r: dict[str, Any]) -> np.ndarray:
    if isinstance(r.get("bbox"), (list, tuple)) and len(r["bbox"]) >= 3:
        return np.array([float(r["bbox"][0]), float(r["bbox"][1]), float(r["bbox"][2])])
    pos = r.get("position_m")
    if isinstance(pos, dict):
        return np.array([float(pos.get("x", 0.0)), float(pos.get("y", 0.0)),
                         float(pos.get("z", 0.0))])
    return np.zeros(3)


def _z_extent(r: dict[str, Any]) -> tuple[float, float]:
    b = r.get("bbox")
    if isinstance(b, (list, tuple)) and len(b) >= 6:
        cz, dz = float(b[2]), float(b[5])
        return cz - dz / 2.0, cz + dz / 2.0
    pos = r.get("position_m")
    size = r.get("size_m")
    if isinstance(pos, dict) and isinstance(size, dict):
        cz = float(pos.get("z", 0.0))
        dz = float(size.get("height", 0.0))
        return cz - dz / 2.0, cz + dz / 2.0
    return (0.0, 0.0)


if __name__ == "__main__":  # pragma: no cover - smoke test
    import json

    here = _here = __file__
    data = json.load(open(__import__("pathlib").Path(__file__).resolve().parents[2]
                          / "data" / "Layout_info" / "scannet" / "scene0313_00"
                          / "layout.json"))
    frame = room_canonical_frame(data)
    print("room-canonical frame:", frame.as_dict())
    if len(data) >= 2:
        print("b rel a:", relative_horizontal(data[0], data[1], frame))
        print("a vs b vertical:", vertical_relation(data[0], data[1]))

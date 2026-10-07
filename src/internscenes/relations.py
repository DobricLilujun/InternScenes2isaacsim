"""Deterministic + rule-based relation derivation for the InternScenes graph.

Turns a scene's object records into typed edges across three families that do
NOT require a VLM:

* **metric / spatial** (deterministic, gravity-aligned): above / below,
  near / far, distance, inside, touching.
* **hierarchical** (deterministic): contains / part_of / in_room (object in the
  room footprint/polygon).
* **semantic** (heuristic rules over category + geometry): on_top_of, support,
  attached_to, same_material.

Functional / affordance / interactive edges are produced by
:mod:`internscenes.vlm_annotate` (with a rule-based fallback when no VLM
endpoint is configured) and merged in by :mod:`internscenes.scene_graph`.

All geometry uses axis-aligned bounding boxes (AABB) of each object for
determinism and speed.  ``dx, dy, dz`` in ``layout.json`` are the *full*
extents, so the AABB half-extents are ``(dx/2, dy/2, dz/2)``.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Sequence

import numpy as np

from . import coordinate as coord

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# configuration
# ---------------------------------------------------------------------------
@dataclass
class RelationConfig:
    """Thresholds and caps for relation derivation (metres unless noted)."""

    near_dist: float = 1.5          # centre-to-centre distance for "near"
    far_dist: float = 4.0           # centre-to-centre distance for "far"
    touch_eps: float = 0.05         # gap <= this counts as "touching"
    overlap_eps: float = 0.02       # vertical gap for on_top_of / support
    containment_margin: float = 0.05  # margin allowed for "inside"
    color_tol: float = 0.18         # RGB distance for "same_material"
    # caps to keep the edge count bounded for large scenes
    max_distance_edges: int = 400
    max_edges_per_predicate: int = 600
    max_candidates: int = 6000      # hard cap on (a,b) pairs considered

    # category families for the heuristic semantic rules
    support_categories: frozenset = frozenset({
        "table", "desk", "counter", "shelf", "cabinet", "bench",
        "nightstand", "dresser", "console", "sink", "bathtub", "toilet",
        "stove", "oven", "coffeetable", "coffee_table", "wardrobe",
    })
    supportable_categories: frozenset = frozenset({
        "book", "vase", "cup", "mug", "plate", "bowl", "bottle", "can",
        "lamp", "plant", "television", "monitor", "phone", "remote",
        "speaker", "clock", "toy", "food", "box", "chair",
    })
    attachable_categories: frozenset = frozenset({
        "handle", "knob", "lock", "switch", "button", "latch", "hinge",
    })
    wall_mounted_categories: frozenset = frozenset({
        "picture", "window", "doorframe", "mirror", "painting",
    })


DEFAULT_CONFIG = RelationConfig()


# ---------------------------------------------------------------------------
# edge record
# ---------------------------------------------------------------------------
@dataclass
class Edge:
    """A single typed relation between two nodes."""

    source: str                       # node id
    target: str                       # node id
    predicate: str                    # e.g. "above", "on_top_of", "contains"
    family: str                       # metric | hierarchy | semantic | functional
    confidence: float                 # 0..1 (tier signal)
    reference_frame: str = "world"    # world | room_canonical | object_intrinsic
    value: float | None = None        # numeric predicate value (e.g. distance)
    note: str = ""                    # derivation note
    tier: str = ""                    # deterministic | heuristic | vlm | gold

    def as_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "source": self.source,
            "target": self.target,
            "predicate": self.predicate,
            "family": self.family,
            "confidence": round(float(self.confidence), 3),
            "reference_frame": self.reference_frame,
        }
        if self.value is not None:
            if isinstance(self.value, (int, float)):
                d["value"] = round(float(self.value), 4)
            else:
                d["value"] = str(self.value)
        if self.note:
            d["note"] = self.note
        d["tier"] = self.tier or _tier_for(self.family)
        return d


# Confidence tier (provenance) for each edge family (see PLAN.md).
_TIER_BY_FAMILY = {
    "metric": "deterministic",
    "hierarchy": "deterministic",
    "semantic": "heuristic",
    "functional": "vlm",
}


def _tier_for(family: str) -> str:
    """Map an edge family to its confidence tier / provenance."""
    return _TIER_BY_FAMILY.get(family, "deterministic")


# ---------------------------------------------------------------------------
# geometry helpers
# ---------------------------------------------------------------------------
@dataclass
class Box:
    """Axis-aligned bounding box for one object."""

    id: str
    min: np.ndarray   # (3,)
    max: np.ndarray   # (3,)
    center: np.ndarray
    size: np.ndarray  # (3,) full extents
    category: str
    color: tuple[float, float, float] | None
    model_uid: str

    @property
    def z_min(self) -> float:
        return float(self.min[2])

    @property
    def z_max(self) -> float:
        return float(self.max[2])


def _category_norm(cat: Any) -> str:
    c = str(cat or "object").lower()
    return c.replace(" ", "_")


def build_boxes(records: Sequence[dict[str, Any]]) -> list[Box]:
    """Convert object records into :class:`Box` objects (skipping invalid).

    Node ids use the record's ``_idx`` tag when present (so a scene graph's
    node ids and its edge endpoints agree), otherwise the enumeration index.
    """
    boxes: list[Box] = []
    for idx, r in enumerate(records):
        nidx = r.get("_idx", idx)
        b = r.get("bbox")
        color = r.get("color")
        rgb = None
        if isinstance(color, dict):
            rgb = (float(color.get("r", 0.0)), float(color.get("g", 0.0)),
                   float(color.get("b", 0.0)))
        if isinstance(b, (list, tuple)) and len(b) >= 6:
            cx, cy, cz, dx, dy, dz = (float(b[0]), float(b[1]), float(b[2]),
                                      float(b[3]), float(b[4]), float(b[5]))
            if dx <= 0 or dy <= 0 or dz <= 0:
                continue
            center = np.array([cx, cy, cz])
            half = np.array([dx / 2.0, dy / 2.0, dz / 2.0])
            box = Box(
                id=f"obj_{nidx}",
                min=center - half, max=center + half, center=center,
                size=np.array([dx, dy, dz]),
                category=_category_norm(r.get("category")),
                color=rgb, model_uid=str(r.get("model_uid", "")),
            )
            boxes.append(box)
        else:
            pos = r.get("position_m")
            size = r.get("size_m")
            if isinstance(pos, dict) and isinstance(size, dict):
                l = float(size.get("length", 0.0))
                w = float(size.get("width", 0.0))
                h = float(size.get("height", 0.0))
                if l <= 0 or w <= 0 or h <= 0:
                    continue
                center = np.array([float(pos.get("x", 0.0)), float(pos.get("y", 0.0)),
                                   float(pos.get("z", 0.0))])
                half = np.array([l / 2.0, w / 2.0, h / 2.0])
                box = Box(
                    id=f"obj_{nidx}",
                    min=center - half, max=center + half, center=center,
                    size=np.array([l, w, h]),
                    category=_category_norm(r.get("category")),
                    color=rgb, model_uid=str(r.get("model_uid", "")),
                )
                boxes.append(box)
    return boxes


def _gap(a: Box, b: Box) -> float:
    """Signed gap between two AABBs: <=0 means overlapping (negative = overlap)."""
    d = 0.0
    for i in range(3):
        if a.max[i] < b.min[i]:
            d += b.min[i] - a.max[i]
        elif b.max[i] < a.min[i]:
            d += a.min[i] - b.max[i]
    return d


def _center_dist(a: Box, b: Box) -> float:
    return float(np.linalg.norm(a.center - b.center))


def _overlap_in_axes(a: Box, b: Box) -> int:
    """Number of axes where the two boxes overlap (0..3)."""
    n = 0
    for i in range(3):
        lo = max(a.min[i], b.min[i])
        hi = min(a.max[i], b.max[i])
        if hi > lo:
            n += 1
    return n


def _area(box: Box) -> float:
    s = box.size
    return float(s[0] * s[1])


# ---------------------------------------------------------------------------
# metric / spatial
# ---------------------------------------------------------------------------
def metric_edges(boxes: list[Box], cfg: RelationConfig,
                 frame: coord.Frame | None = None) -> list[Edge]:
    """Derive above/below, near/far, distance, inside, touching, and
    left/right/front/behind (relative) edges between all object pairs."""
    edges: list[Edge] = []
    n = len(boxes)
    if frame is None:
        frame = coord.room_canonical_frame(boxes)  # type: ignore[arg-type]

    # distance edges: keep the K nearest neighbours of each object
    dist_edges: list[Edge] = []
    for i in range(n):
        d = [(_center_dist(boxes[i], boxes[j]), j) for j in range(n) if j != i]
        d.sort()
        for dist, j in d[:8]:
            dist_edges.append(Edge(
                boxes[i].id, boxes[j].id, "distance", "metric", 1.0,
                "world", round(dist, 3), "centre-to-centre",
            ))
    dist_edges.sort(key=lambda e: (e.source, e.value or 0))
    for e in dist_edges[:cfg.max_distance_edges]:
        edges.append(e)

    # all other pairwise predicates
    for i in range(n):
        for j in range(i + 1, n):
            a, b = boxes[i], boxes[j]
            dist = _center_dist(a, b)
            gap = _gap(a, b)

            # near / far
            if dist < cfg.near_dist:
                edges.append(Edge(a.id, b.id, "near", "metric", 0.9, "world",
                                  round(dist, 3)))
            elif dist > cfg.far_dist:
                edges.append(Edge(a.id, b.id, "far", "metric", 0.7, "world",
                                  round(dist, 3)))

            # touching (small gap, at least two overlapping axes)
            if gap <= cfg.touch_eps and _overlap_in_axes(a, b) >= 2:
                edges.append(Edge(a.id, b.id, "touching", "metric", 0.85, "world",
                                  round(gap, 3)))

            # inside (AABB containment, with margin)
            if _is_inside(a, b, cfg.containment_margin):
                edges.append(Edge(a.id, b.id, "inside", "metric", 0.95, "world",
                                  None, "AABB containment"))
            elif _is_inside(b, a, cfg.containment_margin):
                edges.append(Edge(b.id, a.id, "inside", "metric", 0.95, "world",
                                  None, "AABB containment"))

            # above / below (gravity-aligned)
            if a.z_min > b.z_max + cfg.overlap_eps:
                edges.append(Edge(a.id, b.id, "above", "metric", 1.0, "world"))
            elif b.z_min > a.z_max + cfg.overlap_eps:
                edges.append(Edge(b.id, a.id, "above", "metric", 1.0, "world"))

            # relative horizontal (reference-frame dependent)
            rel = _relative_horizontal(a, b, frame)
            edges.append(Edge(a.id, b.id, rel, "metric", 0.8, frame.name))

    return _cap(edges, "metric", cfg)


def _is_inside(a: Box, b: Box, margin: float) -> bool:
    """True if box ``a`` is contained within box ``b`` (all axes, with margin)."""
    for i in range(3):
        if a.min[i] < b.min[i] - margin or a.max[i] > b.max[i] + margin:
            return False
    return True


def _relative_horizontal(a: Box, b: Box, frame: coord.Frame) -> str:
    """Classify the horizontal relationship of ``b`` relative to ``a`` using ``frame``."""
    v = frame.world_to_frame(b.center - a.center)
    fwd, rgt = float(v[1]), float(v[0])
    if abs(fwd) >= abs(rgt):
        return "front" if fwd > 0 else "behind"
    return "left" if rgt > 0 else "right"


# ---------------------------------------------------------------------------
# hierarchy
# ---------------------------------------------------------------------------
def hierarchy_edges(boxes: list[Box], cfg: RelationConfig,
                    room_id: str = "room",
                    interior_bounds: dict[str, Any] | None = None,
                    polygon: list[list[float]] | None = None) -> list[Edge]:
    """Derive contains / in_room edges between the room node and each object.

    An object is "in the room" when its centre lies inside the room footprint
    (the interior polygon if available, else the interior-bounds AABB).
    """
    edges: list[Edge] = []
    for box in boxes:
        in_room = _point_in_room(box.center, interior_bounds, polygon)
        if in_room:
            edges.append(Edge(room_id, box.id, "contains", "hierarchy", 0.98,
                             "world", "object centre in room footprint"))
            edges.append(Edge(box.id, room_id, "in_room", "hierarchy", 0.98,
                             "world"))
    return _cap(edges, "hierarchy", cfg)


def _point_in_room(center: np.ndarray,
                   interior_bounds: dict[str, Any] | None,
                   polygon: list[list[float]] | None) -> bool:
    if polygon is not None and len(polygon) >= 3:
        try:
            from shapely.geometry import Point  # type: ignore
            from shapely.geometry.polygon import Polygon  # type: ignore
            poly = Polygon(polygon)
            if poly.is_valid:
                return bool(poly.contains(Point(float(center[0]), float(center[1]))))
        except Exception:
            pass
    if interior_bounds is not None:
        try:
            x = float(center[0]); y = float(center[1]); z = float(center[2])
            return (float(interior_bounds["min_x"]) <= x <= float(interior_bounds["max_x"])
                    and float(interior_bounds["min_y"]) <= y <= float(interior_bounds["max_y"])
                    and float(interior_bounds["min_z"]) <= z <= float(interior_bounds["max_z"]))
        except Exception:
            pass
    return True  # if no room geometry, assume contained


# ---------------------------------------------------------------------------
# semantic (heuristic)
# ---------------------------------------------------------------------------
def semantic_edges(boxes: list[Box], cfg: RelationConfig) -> list[Edge]:
    """Derive on_top_of / support / attached_to / same_material edges."""
    edges: list[Edge] = []
    n = len(boxes)
    for i in range(n):
        for j in range(i + 1, n):
            a, b = boxes[i], boxes[j]
            # on_top_of: a above b with horizontal overlap and small vertical gap
            if _on_top_of(a, b, cfg.overlap_eps):
                edges.append(Edge(a.id, b.id, "on_top_of", "semantic", 0.7,
                                  "world", "above + horizontal overlap"))
                if _support(a, b, cfg):
                    edges.append(Edge(a.id, b.id, "support", "semantic", 0.6,
                                      "world", "supportable-on-support"))
            elif _on_top_of(b, a, cfg.overlap_eps):
                edges.append(Edge(b.id, a.id, "on_top_of", "semantic", 0.7,
                                  "world", "above + horizontal overlap"))
                if _support(b, a, cfg):
                    edges.append(Edge(b.id, a.id, "support", "semantic", 0.6,
                                      "world", "supportable-on-support"))

            # attached_to: touching + smaller + attachable category
            if _gap(a, b) <= cfg.touch_eps and _area(a) < _area(b) * 0.5:
                if a.category in cfg.attachable_categories or b.category in cfg.attachable_categories:
                    small, large = (a, b) if _area(a) < _area(b) else (b, a)
                    edges.append(Edge(small.id, large.id, "attached_to", "semantic",
                                      0.6, "world", "touching + smaller"))

            # same_material: colour within tolerance or shared model_uid
            if _same_material(a, b, cfg):
                edges.append(Edge(a.id, b.id, "same_material", "semantic", 0.7,
                                  "world", "color/model_uid"))
    return _cap(edges, "semantic", cfg)


def _on_top_of(a: Box, b: Box, eps: float) -> bool:
    """True if ``a`` rests on top of ``b`` (a above b, horizontal overlap)."""
    if a.z_min < b.z_max + eps:
        return False
    # horizontal (XY) overlap required
    for axis in (0, 1):
        lo = max(a.min[axis], b.min[axis])
        hi = min(a.max[axis], b.max[axis])
        if hi <= lo:
            return False
    return True


def _support(a: Box, b: Box, cfg: RelationConfig) -> bool:
    return a.category in cfg.supportable_categories and b.category in cfg.support_categories


def _same_material(a: Box, b: Box, cfg: RelationConfig) -> bool:
    if a.color is not None and b.color is not None:
        d = math_sqrt((a.color[0] - b.color[0]) ** 2
                       + (a.color[1] - b.color[1]) ** 2
                       + (a.color[2] - b.color[2]) ** 2)
        if d <= cfg.color_tol:
            return True
    if a.model_uid and a.model_uid == b.model_uid:
        return True
    return False


def math_sqrt(x: float) -> float:
    import math
    return math.sqrt(x)


# ---------------------------------------------------------------------------
# top-level
# ---------------------------------------------------------------------------
def derive_edges(
    records: Sequence[dict[str, Any]],
    frame: coord.Frame | None = None,
    cfg: RelationConfig | None = None,
    room_id: str = "room",
    interior_bounds: dict[str, Any] | None = None,
    polygon: list[list[float]] | None = None,
    include_relative: bool = True,
) -> list[Edge]:
    """Derive all non-VLM edges (metric + hierarchy + semantic) for a scene."""
    cfg = cfg or DEFAULT_CONFIG
    boxes = build_boxes(records)
    if frame is None:
        frame = coord.room_canonical_frame(records, interior_bounds)  # type: ignore[arg-type]
    edges: list[Edge] = []
    edges += metric_edges(boxes, cfg, frame if include_relative else coord.world_frame())
    edges += hierarchy_edges(boxes, cfg, room_id=room_id,
                             interior_bounds=interior_bounds, polygon=polygon)
    edges += semantic_edges(boxes, cfg)
    return edges


def _cap(edges: list[Edge], family: str, cfg: RelationConfig) -> list[Edge]:
    """Cap the number of edges per family to keep the graph bounded."""
    if len(edges) <= cfg.max_edges_per_predicate:
        return edges
    logger.info("capping %d %s edges to %d", len(edges), family,
                cfg.max_edges_per_predicate)
    return edges[:cfg.max_edges_per_predicate]


if __name__ == "__main__":  # pragma: no cover
    import json
    import pathlib

    here = pathlib.Path(__file__).resolve().parents[2]
    data = json.load(open(here / "data" / "Layout_info" / "scannet"
                          / "scene0313_00" / "layout.json"))
    recs = [dict(r) for r in data]
    from . import scene_info as _si
    interior = _si.structure_mesh_bounds(here / "data" / "Layout_info" / "scannet"
                                        / "scene0313_00" / "layout.json")
    frame = coord.room_canonical_frame(recs, interior)
    edges = derive_edges(recs, frame, interior_bounds=interior)
    by_pred: dict[str, int] = {}
    for e in edges:
        by_pred[e.predicate] = by_pred.get(e.predicate, 0) + 1
    print("edges:", len(edges), "by predicate:", by_pred)

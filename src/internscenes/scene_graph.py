"""Scene-graph builder for InternScenes.

Assembles a scene graph from a scene's ``layout.json`` (and, optionally, a
VLM-annotation result), producing a JSON-serialisable ``scene_graph.json``
following the degradable canonical schema::

    Scene -> Room/Place -> Object/Agent -> Part/Interactive element

The graph has:

* **nodes** -- objects, the room, structure (floor/wall/ceiling), the Go2
  agent, and (optionally, VLM-derived) interactive parts;
* **edges** -- typed relations grouped by family (metric / hierarchy /
  semantic / functional), each with an explicit ``reference_frame`` and a
  ``confidence`` tier signal;
* **frame** -- the room-canonical reference frame used for relative predicates;
* **stats** -- counts and a confidence-tier summary.

Deterministic + semantic edges come from :mod:`internscenes.relations`.
Functional / affordance / interactive edges come from
:mod:`internscenes.vlm_annotate` (with a rule-based fallback when no VLM
endpoint is configured).
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from . import coordinate as coord
from . import relations as rel
from . import scene_info as si

logger = logging.getLogger(__name__)

SCHEMA_VERSION = "1.0"


# ---------------------------------------------------------------------------
# node construction
# ---------------------------------------------------------------------------
def _object_node(record: dict[str, Any]) -> dict[str, Any] | None:
    """Build an object node from a normalised object record.

    ``record`` may be a raw ``layout.json`` entry (``bbox[9]``) or a
    normalised :func:`scene_info.object_properties` record.
    """
    box = rel.build_boxes([record])
    if not box:
        # still emit a node for invalid/placeholder objects so counts match
        # num_objects, but mark it invalid
        b = record.get("bbox")
        valid = b is not None and isinstance(b, (list, tuple)) and len(b) >= 6
        return {
            "id": f"obj_{record.get('_idx', 0)}",
            "level": "object",
            "category": str(record.get("category", "object")).lower().replace(" ", "_"),
            "model_uid": str(record.get("model_uid", "")),
            "valid": bool(valid),
            "geometry": None,
            "attributes": {},
            "confidence": 1.0 if valid else 0.0,
            "source": "deterministic",
        }
    b = box[0]
    color = b.color
    node = {
        "id": b.id,
        "level": "object",
        "category": b.category,
        "model_uid": b.model_uid,
        "valid": True,
        "geometry": {
            "center_m": [round(float(x), 4) for x in b.center],
            "size_m": [round(float(x), 4) for x in b.size],
            "bbox_min_m": [round(float(x), 4) for x in b.min],
            "bbox_max_m": [round(float(x), 4) for x in b.max],
        },
        "attributes": {},
        "confidence": 1.0,
        "source": "deterministic",
    }
    if color is not None:
        node["color"] = {"r": color[0], "g": color[1], "b": color[2]}
    return node


def _room_node(interior: dict[str, Any] | None) -> dict[str, Any]:
    geom = None
    if interior is not None:
        geom = {
            "min_m": [interior["min_x"], interior["min_y"], interior["min_z"]],
            "max_m": [interior["max_x"], interior["max_y"], interior["max_z"]],
            "width_m": interior.get("width"),
            "depth_m": interior.get("depth"),
            "height_m": interior.get("height"),
        }
    return {
        "id": "room",
        "level": "room",
        "category": "room",
        "geometry": geom,
        "attributes": {},
        "confidence": 0.98,
        "source": "structure_mesh" if interior is not None else "layout",
    }


def _structure_nodes(interior: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Floor/wall/ceiling structure nodes (from the interior bounds)."""
    if interior is None:
        return []
    nodes: list[dict[str, Any]] = []
    for part in ("floor", "wall", "ceiling"):
        nodes.append({
            "id": f"structure_{part}",
            "level": "structure",
            "category": part,
            "geometry": {"source": interior.get("source")},
            "attributes": {},
            "confidence": 0.9,
            "source": "structure_mesh",
        })
    return nodes


def _agent_node(go2: dict[str, Any]) -> dict[str, Any] | None:
    if not go2 or not go2.get("valid"):
        return None
    pos = go2.get("position_m", {})
    return {
        "id": "agent_go2",
        "level": "agent",
        "category": "go2",
        "geometry": {"center_m": [pos.get("x", 0.0), pos.get("y", 0.0), 0.0]},
        "attributes": {"clearance_m": go2.get("clearance_m")},
        "confidence": 0.9,
        "source": "placement",
    }


# ---------------------------------------------------------------------------
# graph assembly
# ---------------------------------------------------------------------------
def build_scene_graph(
    scene_id: str,
    layout_path: str | Path,
    *,
    vlm_result: dict[str, Any] | None = None,
    cfg: rel.RelationConfig | None = None,
    render_views: dict[str, str] | None = None,
    include_relative: bool = True,
) -> dict[str, Any]:
    """Build a scene graph for ``scene_id`` from its ``layout.json``.

    Parameters
    ----------
    scene_id:
        Logical scene id, e.g. ``"scannet/scene0313_00"``.
    layout_path:
        Path to the scene's ``layout.json``.
    vlm_result:
        Optional dict from :func:`internscenes.vlm_annotate.annotate`
        (``{"relations": [...], "interactive": [...], "manifest": {...}}``).
    cfg:
        Relation thresholds/caps.
    render_views:
        Optional mapping of view name -> path (multi-view render output).
    include_relative:
        If False, skip left/right/front/behind (use world frame only).
    """
    cfg = cfg or rel.DEFAULT_CONFIG
    layout_path = Path(layout_path)
    records = si.load_layout(layout_path)

    # tag records with an index so node ids are stable even if 'id' is missing
    for i, r in enumerate(records):
        r = dict(r)
        r["_idx"] = i
        records[i] = r

    # interior geometry + room polygon
    interior = si.structure_mesh_bounds(layout_path)
    try:
        polygon = si.place_go2.interior_polygon(layout_path)
    except Exception:
        polygon = None
    if polygon is not None and len(polygon) >= 3:
        polygon = [[round(float(x), 4), round(float(y), 4)] for x, y in polygon]

    # nodes
    nodes: list[dict[str, Any]] = [_room_node(interior)]
    nodes += _structure_nodes(interior)
    object_nodes = []
    for r in records:
        n = _object_node(r)
        if n is not None:
            object_nodes.append(n)
            nodes.append(n)
    agent = _agent_node(si.go2_placement(records, layout_path))
    if agent is not None:
        nodes.append(agent)

    # reference frame
    frame = coord.room_canonical_frame(records, interior)

    # deterministic + semantic edges
    edges = rel.derive_edges(
        records,
        frame=frame,
        cfg=cfg,
        interior_bounds=interior,
        polygon=polygon,
        include_relative=include_relative,
    )

    # VLM functional / interactive layer
    vlm_manifest = None
    if vlm_result is not None:
        # affordances are node attributes (unary)
        affordances = vlm_result.get("affordances", {})
        for n in nodes:
            affs = affordances.get(n["id"])
            if affs:
                n["affordances"] = list(affs)
                n["attributes"]["affordances"] = list(affs)
        # interactive part nodes + has_part (functional) edges
        for part in vlm_result.get("interactive", []):
            pn = _interactive_node(part)
            if pn is not None:
                nodes.append(pn)
                parent = part.get("parent") or pn.get("parent")
                if parent and parent in {x["id"] for x in nodes if x.get("level") != "part"}:
                    edges.append(rel.Edge(
                        parent, pn["id"], "has_part", "functional",
                        float(part.get("confidence", 0.6)), "world",
                        None, "interactive part",
                    ))
        vlm_manifest = vlm_result.get("manifest")

    stats = _stats(nodes, edges)
    graph = {
        "schema_version": SCHEMA_VERSION,
        "scene_id": scene_id,
        "dataset": scene_id.split("/", 1)[0] if "/" in scene_id else "unknown",
        "layout_source": str(layout_path),
        "frame": frame.as_dict(),
        "num_objects": len(records),
        "nodes": nodes,
        "edges": [e.as_dict() if isinstance(e, rel.Edge) else e for e in edges],
        "stats": stats,
    }
    if render_views:
        graph["renders"] = {k: str(v) for k, v in render_views.items()}
    if vlm_manifest is not None:
        graph["vlm_manifest"] = vlm_manifest
    return graph


def _edge_from_vlm(e: dict[str, Any]) -> rel.Edge:
    return rel.Edge(
        source=e.get("source", ""),
        target=e.get("target", ""),
        predicate=e.get("predicate", "used_for"),
        family=e.get("family", "functional"),
        confidence=float(e.get("confidence", 0.6)),
        reference_frame=e.get("reference_frame", "world"),
        value=e.get("value"),
        note=e.get("note", "vlm"),
    )


def _interactive_node(part: dict[str, Any]) -> dict[str, Any] | None:
    pid = part.get("id")
    if not pid:
        return None
    return {
        "id": pid,
        "level": "part",
        "category": str(part.get("category", "interactive")).lower().replace(" ", "_"),
        "geometry": part.get("geometry"),
        "attributes": part.get("attributes", {}),
        "affordances": part.get("affordances", []),
        "parent": part.get("parent"),
        "confidence": float(part.get("confidence", 0.6)),
        "source": "vlm",
    }


def _stats(nodes: list[dict[str, Any]], edges: list[rel.Edge]) -> dict[str, Any]:
    by_family: dict[str, int] = {}
    by_predicate: dict[str, int] = {}
    for e in edges:
        f = e.family if isinstance(e, rel.Edge) else e.get("family", "functional")
        p = e.predicate if isinstance(e, rel.Edge) else e.get("predicate", "")
        by_family[f] = by_family.get(f, 0) + 1
        by_predicate[p] = by_predicate.get(p, 0) + 1
    edge_tiers: dict[str, int] = {}
    for e in edges:
        t = _tier_for(e) if isinstance(e, rel.Edge) else e.get("tier", "")
        edge_tiers[t] = edge_tiers.get(t, 0) + 1
    # confidence tiers from source
    tiers: dict[str, int] = {}
    for n in nodes:
        tiers[n.get("source", "deterministic")] = tiers.get(n.get("source", "deterministic"), 0) + 1
    return {
        "num_nodes": len(nodes),
        "num_edges": len(edges),
        "num_by_level": _count_level(nodes),
        "num_by_family": by_family,
        "num_by_predicate": by_predicate,
        "confidence_tiers": tiers,
        "edge_tiers": edge_tiers,
    }


def _tier_for(e: rel.Edge) -> str:
    """Confidence tier / provenance for an edge object."""
    return getattr(e, "tier", "") or rel._tier_for(e.family)


def _count_level(nodes: list[dict[str, Any]]) -> dict[str, int]:
    c: dict[str, int] = {}
    for n in nodes:
        lvl = n.get("level", "object")
        c[lvl] = c.get(lvl, 0) + 1
    return c


def write_scene_graph(graph: dict[str, Any], out_path: str | Path) -> Path:
    """Write ``graph`` to ``out_path`` as pretty JSON (creating parents)."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as fh:
        json.dump(graph, fh, ensure_ascii=False, indent=2)
    logger.info("wrote scene graph -> %s", out_path)
    return out_path


if __name__ == "__main__":  # pragma: no cover
    import argparse

    logging.basicConfig(level=logging.INFO)
    ap = argparse.ArgumentParser(description="Build a scene graph JSON")
    ap.add_argument("scene", help="scene id, e.g. scannet/scene0313_00")
    ap.add_argument("--layout", help="layout.json path")
    ap.add_argument("--out", help="output path")
    args = ap.parse_args()
    root = Path(__file__).resolve().parents[2]
    layout = args.layout or str(root / "data" / "Layout_info" / args.scene / "layout.json")
    out = args.out or str(root / "output" / "graph" / f"{args.scene.replace('/', '_')}.json")
    g = build_scene_graph(args.scene, layout)
    write_scene_graph(g, out)
    print(f"{args.scene}: {g['stats']['num_nodes']} nodes, "
          f"{g['stats']['num_edges']} edges -> {out}")

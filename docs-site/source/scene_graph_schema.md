---
title: Scene-Graph Schema
description: The degradable canonical scene-graph schema
---

# Scene-Graph Schema

A SAGE-Bench scene graph is a JSON document describing a single scene. It
follows a **degradable canonical schema**:

```text
Scene  →  Room/Place  →  Object/Agent  →  Part / Interactive element
```

The graph degrades gracefully — if a layer is unavailable (e.g. no VLM
endpoint), the next tier of edges is simply absent rather than the build
failing.

## Top-level document

A built graph (`scene_graph.json`) has this shape:

| Field | Type | Meaning |
| --- | --- | --- |
| `schema_version` | str | Schema version, currently `"1.0"` |
| `scene_id` | str | Logical id, e.g. `scannet/scene0313_00` |
| `dataset` | str | Source dataset (`scannet`, `3rscan`, …) |
| `layout_source` | str | Path to the source `layout.json` |
| `frame` | object | The room-canonical reference frame |
| `num_objects` | int | Number of object records |
| `nodes` | list | Node records (below) |
| `edges` | list | Edge records (below) |
| `stats` | object | Counts + confidence-tier summary |
| `vlm_manifest` | object? | Present only when `--vlm` was used |

## Node record

| Field | Type | Meaning |
| --- | --- | --- |
| `id` | str | Stable id: `room`, `structure_<part>`, `obj_<idx>`, `agent_go2`, `part_<…>` |
| `level` | str | `room` / `structure` / `object` / `agent` / `part` |
| `category` | str | Category (e.g. `chair`, `door`) |
| `geometry` | object | `min_m`, `max_m`, `width_m`, `depth_m`, `height_m` (metres) |
| `attributes` | object | Extra metadata (colour, model uid, …) |
| `affordances` | list? | VLM-derived affordances (functional tier) |
| `confidence` | float | 0–1 confidence tier signal |
| `source` | str | Derivation source (`layout`, `structure_mesh`, `vlm`, …) |

Node ids are stable: objects use `obj_<index>` (index in the object list, not
the layout id) so ids are always unique even when a layout record lacks an
`id`.

## Edge record

| Field | Type | Meaning |
| --- | --- | --- |
| `source` / `target` | str | Endpoint node ids |
| `predicate` | str | The relation (e.g. `distance`, `contains`, `support`) |
| `family` | str | `metric` / `hierarchy` / `semantic` / `functional` |
| `confidence` | float | 0–1 confidence |
| `reference_frame` | str | `world` / `room_canonical` / `object_intrinsic` |
| `value` | float? | Numeric value for quantitative predicates (distance, …) |
| `note` | str? | Derivation note |
| `tier` | str | `deterministic` / `heuristic` / `vlm` (provenance) |

> **Quantitative vs qualitative.** Quantitative predicates
> (`distance`, `near`, `far`, `touching`) carry a numeric `value`. Qualitative
> ones (`inside`, `above`, `below`, `left`, `right`, `front`, `behind`) carry
> a `reference_frame` instead of a value.

## Stats

The `stats` object summarises the graph:

| Field | Meaning |
| --- | --- |
| `num_nodes` / `num_edges` | Counts |
| `num_by_level` | Node count per level |
| `num_by_family` | Edge count per family |
| `num_by_predicate` | Edge count per predicate |
| `confidence_tiers` | Edge count per confidence tier |
| `edge_tiers` | Edge count per provenance tier |

## Example

A single edge from a real graph:

```json
{
  "source": "obj_0",
  "target": "obj_14",
  "predicate": "distance",
  "family": "metric",
  "confidence": 1.0,
  "reference_frame": "world",
  "value": 1.211,
  "note": "centre-to-centre",
  "tier": "deterministic"
}
```

## Building a graph

```python
from internscenes import scene_graph

graph = scene_graph.build_scene_graph(
    scene_id="scannet/scene0313_00",
    layout_path="data/Layout_info/scannet/scene0313_00/layout.json",
    vlm_result=None,          # pass a vlm_annotate result for the VLM layer
)
scene_graph.write_scene_graph(graph, "output/graph/scene_graph.json")
```

See [Relations &amp; Edge Families](/relations.html) for the full edge
catalogue and [Reference Frames](/reference_frames.html) for the coordinate
standard.

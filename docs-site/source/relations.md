---
title: Relations & Edge Families
description: The typed edge families, predicates and confidence tiers
---

# Relations &amp; Edge Families

Every edge in a SAGE-Bench graph has a **family**, a **predicate**, and a
**confidence tier** (its provenance). The families are derived by
`internscenes.relations` (deterministic + heuristic) and by
`internscenes.vlm_annotate` (functional / interactive).

## Families

| Family | Predicates | Derivation | Tier |
| --- | --- | --- | --- |
| **Metric / spatial** | `distance`, `near`, `far`, `above`, `below`, `inside`, `touching`, `left`, `right`, `front`, `behind` | from `bbox` (gravity-aligned AABB) | **deterministic** |
| **Hierarchy** | `contains`, `part_of`, `in_room` | object ∈ room footprint / StructureMesh | **deterministic** |
| **Semantic** | `support`, `attached_to`, `on_top_of`, `same_material` | rules over category + geometry | **heuristic** |
| **Functional / affordance** | `opens_via`, `used_for`, `pressable`, `openable`, `graspable` | VLM on rendered views (fallback: rules) | **vlm** |
| **Interactive element** | interactive-part nodes + functional edges | VLM on rendered views (fallback: rules) | **vlm** |
| **Temporal** | — | static scenes → not applicable | — |

The tier is recorded on every edge so a consumer can filter by provenance:

```python
graph = scene_graph.build_scene_graph(scene_id, layout_path)
det = [e for e in graph["edges"] if e["tier"] == "deterministic"]
vlm = [e for e in graph["edges"] if e["tier"] == "vlm"]
```

## How edges are derived

All geometric relations use **axis-aligned bounding boxes** (AABB), which are
deterministic and fast. `dx / dy / dz` in `layout.json` are full extents;
half-extents are `(dx/2, dy/2, dz/2)`.

### Metric / spatial

- **distance** — centre-to-centre distance of the **K nearest neighbours**
  per object (`K = 8`), capped at `max_distance_edges = 400` to avoid
  O(n²) blow-up on large scenes.
- **near / far** — centre distance below `near_dist` / above `far_dist`.
- **touching** — small gap `≤ touch_eps` with overlap in ≥ 2 axes.
- **inside** — AABB containment with a margin.
- **above / below** — gravity-aligned vertical (world frame).
- **left / right / front / behind** — relative horizontal, **defined by the
  room-canonical frame** (see [Reference Frames](/reference_frames.html)).

### Hierarchy

- **in_room** — object centre inside the room footprint / interior polygon.
- **contains / part_of** — one box contains another.

### Semantic (rules)

| Predicate | Rule |
| --- | --- |
| `support` | a supportable object sits on a support category (table / shelf / …) |
| `attached_to` | an attachable object is near a wall / support |
| `on_top_of` | a small vertical gap with a large horizontal overlap |
| `same_material` | same normalised category family |

The category families (`support_categories`, `supportable_categories`,
`attachable_categories`, `wall_mounted_categories`) are configured in
`RelationConfig`.

## Consistency invariants

The deterministic edges satisfy cheap, high-value invariants, checked by
`internscenes.vlm_annotate.consistency_check`:

- `above(a, b) ⇔ below(b, a)` (inverse)
- `inside(a, b) ⇔ ¬disconnected(a, b)`
- symmetric `touching` / `near`
- no containment cycles
- room–object geometric containment

## Configure the thresholds

```python
from internscenes import relations as rel

cfg = rel.RelationConfig(
    near_dist=1.0,
    far_dist=4.0,
    touch_eps=0.05,
    containment_margin=0.2,
    max_distance_edges=400,
    max_edges_per_predicate=600,
)
```

See [Reference Frames](/reference_frames.html) for how `left / right /
front / behind` are defined and [Evaluation Metrics](/evaluation.html) for
how relations are scored.

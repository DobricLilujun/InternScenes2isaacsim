---
title: Reference Frames
description: The coordinate standard for relative spatial predicates
---

# Reference Frames

Relative spatial predicates (`left / right / front / behind`) only make sense
once a **reference frame** is fixed. SAGE-Bench stores the frame **explicitly
on every edge** so a consumer never has to guess. Gravity-safe predicates
(`above / below`, `near / far`, `distance`, `inside`) carry no horizontal
frame.

The module is `internscenes.coordinate`.

## Three frames

| Frame | Up | Forward | Used for |
| --- | --- | --- | --- |
| **world** | +Z (gravity-aligned) | — | `above/below`, `near/far`, `distance`, `inside`, `touching` |
| **room_canonical** | +Z | principal axis of the room (PCA of object centroids, XY) | `left/right/front/behind` |
| **object_intrinsic** | object local +Z | object local +X | object-relative (e.g. "handle on the front of the door") |

A frame is an orthonormal 3×3 matrix **R** whose columns are
`[right, forward, up]` in world coordinates:

```python
world_to_frame  = R.T @ (p - origin)
frame_to_world  = R @ p' + origin
```

The room-canonical frame is **right-handed** (det = 1.0) and the forward sign
is **deterministic**: `forward.x > 0`, else `forward.y > 0` — so the same scene
always yields the same "front".

## Build a frame

```python
from internscenes import coordinate as coord

# room-canonical: up = +Z, forward = room principal axis
frame = coord.room_canonical_frame(object_records)

# object-intrinsic: forward = the object's local +X
obj_frame = coord.object_intrinsic_frame(record, base="world")

# resolve a frame by name
frame = coord.resolve_frame("room_canonical", object_records)
```

## Relative predicates

`left / right / front / behind` classify **b** relative to **a** in the
room-canonical frame:

```python
pred = coord.relative_horizontal(a, b, frame)
# -> "front" | "behind" | "left" | "right"
```

The rule: transform `b - a` into the frame, take `forward` and `right`
components, and pick the larger in magnitude:

```python
v = frame.world_to_frame(b.center - a.center)
fwd, rgt = v[1], v[0]
if abs(fwd) >= abs(rgt):
    return "front" if fwd > 0 else "behind"
return "left" if rgt > 0 else "right"
```

Vertical relations use the world frame directly:

```python
rel = coord.vertical_relation(a, b)   # "above" | "below" | None
```

## Example

Every relative edge records its frame, e.g.:

```json
{
  "source": "obj_0",
  "target": "obj_1",
  "predicate": "front",
  "family": "metric",
  "reference_frame": "room_canonical",
  "tier": "deterministic"
}
```

A gravity-safe edge (no horizontal frame) records `world`:

```json
{ "predicate": "distance", "reference_frame": "world", "value": 1.211 }
```

## Why explicit frames

InternScenes layouts come from four datasets with heterogeneous conventions.
By pinning **up = +Z** and **forward = the room principal axis**, SAGE-Bench
makes `front / behind` reproducible across scenes and datasets — and by storing
the frame on the edge, a downstream task (navigation, VLM grounding, retrieval)
can always reconstruct the meaning of a relation.

See [Relations &amp; Edge Families](/relations.html) for the full predicate
catalogue and [Python API](/python_api.html) for `coordinate` usage.

# Scene Graph Dataset for InternScenes — Development Plan (v0.2, decisions locked)

> Scope: builds a scene-graph dataset **only on the current, already-present
> InternScenes data** (ScanNet, 3RScan, ARKitScenes, Matterport3D; 2847 scenes,
> 87,733 objects, 258 categories). CVPR framing and the new external datasets in
> the source brief are **ignored**.

## Decisions locked from the user
1. **Deliverable = (b)**: scene-graph **dataset + evaluation harness** (no
   baselines/ablations in v1).
2. **Edge families in v1**: geometric + hierarchical (deterministic) **plus**
   semantic (rules) **plus** functional/interactive (VLM-derived).
3. **Annotation track**: camera + **multi-view rendering** → rule-based candidate
   generation → **VLM annotation (Qwen3.8-27B-NVFP4 via Inferact)** →
   consistency check.
4. **Interactive-element / affordance layer**: included in v1, derived via the
   VLM track; **human verification added after v1**.
5. **Reference frame**: a documented standard per predicate (see §Reference Frame).
6. **Scale**: v1 = a **subset (~200 scenes)**, pilot 20–30 first.
7. **Integration**: new `internscenes graph <scene>` command + pipeline stage.

## Context

**Current project.** `InternScenes2isaacsim` turns InternScenes indoor layouts
into USD scenes (Isaac Sim) + perspective / top-down images + per-scene metadata
(`scene.json`) + object-finding navigation questions.

**What we actually have today** (per scene):
- `layout.json`: objects, each `{id, category, model_uid, bbox[9]}` where
  `bbox = (cx, cy, cz, dx, dy, dz, rot_x, rot_y, rot_z)`.
- `StructureMesh/{floor,wall,ceiling}.glb`: real room geometry → containment /
  interior footprint.
- `scene.json`: room dims, interior bounds + polygon, category counts, Go2
  (robot) placement, per-object `position_m / size_m / rotation_rad / color`.
- `render.py`: **single** perspective view (camera inside room, walls/ceiling
  hidden, eye level, EEVEE/CYCLES, 1920×1080).
- **No edges / relations / hierarchy exist yet.**

**Why here.** InternScenes already holds the two ingredients a scene graph needs
— grounded object **nodes** (geometry + category + color) and room **structure**
geometry — and can render interior **views**. Missing pieces: the **edge layer**,
**multi-view capture**, and a **VLM annotation + evaluation** pipeline.

## Approach

A **degradable canonical schema** + **typed edge families** with explicit
confidence tiers, a **standard reference frame**, a **multi-view render → VLM
annotation** track, and a **factorized evaluation harness**.

### Canonical schema (degradable)
```
Scene  →  Room/Place  →  Object/Agent  →  Part / Interactive element
```
- **Nodes**: `object` (layout.json), `structure` (floor/wall/ceiling),
  `room/place` (from StructureMesh), `agent` (Go2), `part/interactive`
  (VLM-derived).
- **Node attributes**: `id, level, geometry(bbox/box), category, aliases,
  color, attributes, affordances, confidence, source`.
- **Projections** `P_flat / P_room / P_full`.

### Typed edge families (v1) + confidence tier
| Family | Predicates | Derivation | Tier |
|---|---|---|---|
| **Hierarchical** | contains / part-of / in-room | object ∈ StructureMesh footprint | **deterministic** |
| **Metric/spatial** | above/below, near/far, distance, inside, touching | from `bbox` (gravity-aligned) | **deterministic** |
| **Semantic** | support / attached-to / on-top-of / same-material | rules over category + geometry | **heuristic** |
| **Functional / affordance** | opens-via / used-for / pressable / openable / graspable | **VLM (Qwen) on rendered views** | **VLM** |
| **Interactive element** | interactive-part nodes + functional edges | **VLM (Qwen) on rendered views** | **VLM** |
| **Temporal** | — | static scenes → **n/a** | — |

Confidence tiers → provenance: **deterministic / heuristic / VLM / (Gold post-v1)**.

### Reference frame standard (decision #5)
- **World frame**: gravity-aligned, Z-up (existing project standard).
- **Primary: room-canonical frame** — up = +Z; horizontal "forward" = principal
  axis of the room (PCA of the StructureMesh footprint / longest room axis).
  left / right / front / behind are defined relative to this forward axis.
- **Object-intrinsic frame** — for object-relative predicates (e.g. "handle is
  on the front of the cabinet").
- Every relative predicate stores `reference_frame ∈ {room_canonical,
  object_intrinsic}` **explicitly**. Gravity-safe predicates (above/below,
  near/far, distance, inside) carry no horizontal frame.
- Standard written into `docs/SCENE_GRAPH.md` and confirmed before rollout.

### Annotation track (decision #3, #4)
```
compose scene GLB
  → multi-view render (orbit camera N views + top-down)      [NEW capability]
  → candidate generation (geometry + rules)                  [reuse scene_info/path_planner]
  → VLM annotation (Qwen3.8-27B-NVFP4 via Inferact)          [NEW module]
        inputs: rendered views + scene.json object list + candidates
        outputs: relation labels + interactive elements + affordances + confidence
  → consistency checker (inverse/symmetry/containment)
  → [post-v1] human verification → Gold set
```
- **Multi-view render** (extend `render.py` / new `render_multi.py`): orbit the
  camera around the room centre at eye level + a top-down view; ~8–12 images/scene
  (count configurable).
- **VLM module** (`vlm_annotate.py`): thin configurable backend
  (`endpoint`, `model_id=Qwen3.8-27B-NVFP4`, `prompt_template`, `temperature`,
  cost/token logging) — records a **foundation-model manifest** per run for
  reproducibility (matches the brief's foundation-model policy).
- **Consistency checks** (cheap, high value): `above(a,b)⇔below(b,a)`,
  `inside(a,b)⇔¬disconnected(a,b)`, symmetric `touching/near`, no containment
  cycles, room-object geometric containment.

### Evaluation harness (factorized, not single Recall@K)
- **Node**: mAP / 3D IoU / Macro-F1 (category).
- **Relation**: Triplet P/R/F1, mRecall@K (long-tail aware).
- **Spatial**: Macro-F1 + geometric-consistency.
- **Hierarchy**: parent-edge F1 / level-wise F1.
- **Affordance / interactive**: AP / IoU.
- **Calibration** (VLM): ECE / Brier.
- **Efficiency**: latency / memory / graph bytes / #edges.
- Report a **Pareto** (quality vs edges / latency), not one number.

## Files to modify
- **NEW** `src/internscenes/scene_graph.py` — schema + graph builder + `scene_graph.json` writer
- **NEW** `src/internscenes/relations.py` — geometric + containment + semantic-rule edges
- **NEW** `src/internscenes/coordinate.py` — room-canonical / object-intrinsic reference frame
- **NEW** `src/internscenes/render_multi.py` — multi-view orbit rendering (or extend `render.py`)
- **NEW** `src/internscenes/vlm_annotate.py` — Qwen/Inferact annotation backend + manifest
- **NEW** `src/internscenes/evaluate_graph.py` — factorized metrics
- **EDIT** `src/internscenes/cli.py` — add `graph` subcommand
- **EDIT** `src/internscenes/pipeline.py` — add `stage_graph`, `stage_render_multi`, `assemble_normalized`
- **EDIT** `src/internscenes/render.py` — multi-view support (shared camera/lighting)
- **EDIT** `src/internscenes/scene_info.py` — expose structured node records
- **NEW** `tests/test_relations.py`, `tests/test_scene_graph.py`, `tests/test_coordinate.py`
- **NEW** `docs/SCENE_GRAPH.md` (schema + edge families + reference frame + VLM protocol)

## Reuse (existing code)
- `scene_info.py`: `object_properties`, `room_dimensions`, `structure_mesh_bounds`,
  `place_go2.interior_polygon`, `build_scene_info`
- `path_planner.py`: `_footprint_rect`, `_build_obstacles`, `_circle_rect_intersect`,
  distance/intersection logic
- `compose.py`: `AssetMeshLoader` (mesh/rotation), `_extract_object_color`
- `render.py` / `_render_in_blender.py`: camera placement, lighting, Blender bootstrap
- `questions.py`: candidate/target selection patterns

## Steps
- [ ] Step 1: Finalize `docs/SCENE_GRAPH.md` (nodes, edge families, **reference frame**, VLM protocol, confidence tiers)
- [ ] Step 2: `coordinate.py` — room-canonical + object-intrinsic frames
- [ ] Step 3: `relations.py` — geometric + containment + semantic-rule edges
- [ ] Step 4: `render_multi.py` — multi-view orbit + top-down capture
- [ ] Step 5: `vlm_annotate.py` — Qwen/Inferact backend + manifest + consistency checker
- [ ] Step 6: `scene_graph.py` — assemble nodes + edges + interactive layer → `scene_graph.json`
- [ ] Step 7: CLI `graph` command + pipeline stage + `assemble_normalized`
- [ ] Step 8: `evaluate_graph.py` — factorized metrics + Pareto
- [ ] Step 9: Pilot 20–30 scenes → expand to ~200; (post-v1) human Gold verification
- [ ] Step 10: Tests + docs

## Verification
- `python -m unittest discover -s tests -v`
- Pilot: `internscenes graph --scene scannet/scene0330_00` (renders views →
  VLM-annotates → writes `scene_graph.json`)
- Checks: node count = valid objects + structure + (VLM) interactive; all
  edges pass inverse/symmetry/containment consistency; every relative predicate
  has a `reference_frame`; VLM manifest records model/endpoint/prompt/cost.
- `evaluate_graph.py` on the pilot subset returns node/relation/hierarchy/
  affordance/calibration scores + a Pareto plot.

## Open items to confirm during execution (not blocking the plan)
- Exact **Inferact / Qwen3.8-27B-NVFP4 serving endpoint** (the module is a thin
  configurable wrapper; endpoint + model id + prompt template are config).
- Final **reference-frame standard** wording in `SCENE_GRAPH.md` (proposed:
  room-canonical primary + object-intrinsic).
- **Multi-view count** (proposed 8–12 views/scene).
- **v1 subset** composition (proposed: 1–2 datasets, ~200 scenes, pilot 20–30).

# Scene Graph Dataset — Schema, Reference Frame, VLM Protocol & Evaluation

> **Scope (v1):** a scene-graph *dataset + evaluation harness* built **only** on
> the already-present InternScenes data (ScanNet, 3RScan, ARKitScenes,
> Matterport3D; 2847 scenes, 87,733 objects, 258 categories). No new external
> datasets and no CVPR-specific framing are involved.
>
> **Confidence tiers** → provenance: `deterministic` / `heuristic` / `vlm` /
> `gold` (gold is a post-v1 human-verification layer).

---

## 1. Canonical schema (degradable)

```
Scene  →  Room/Place  →  Object / Agent  →  Part / Interactive element
```

Each scene is emitted as a single `scene_graph.json` with:

```
{
  "schema_version": "1.0",
  "scene_id":   "scannet/scene0313_00",
  "frame":      { …reference-frame… },
  "nodes":  [ … ],
  "edges":  [ … ],
  "renders":  { "view_0": "…/…/scene0313_00__view_0.png", … },
  "vlm_manifest": { … },          # present when a VLM layer was applied
  "stats":  { num_nodes, num_edges, num_by_level, num_by_family,
              num_by_predicate, confidence_tiers, edge_tiers }
}
```

**Node attributes** (schema 1.0):
`id, level, category, model_uid, valid, geometry, color, attributes,
affordances, confidence, source, tier`.

- `level` ∈ `{room, structure, object, agent, part}`
- `geometry` = `{center_m, size_m, bbox_min_m, bbox_max_m}` (metres, gravity-aligned)
- `confidence` ∈ [0, 1]
- `source` / `tier` = provenance (e.g. `deterministic`, `structure_mesh`, `vlm`)

**Projections** (downstream consumers may request a reduced view):
`P_flat` (object-only, no hierarchy), `P_room` (room + structure + objects),
`P_full` (everything including VLM parts/affordances). The builder always writes
`P_full`; a projection is just a filtered view of the same `nodes`/`edges`.

---

## 2. Typed edge families (v1)

| Family | Predicates | Derivation | Confidence tier |
|---|---|---|---|
| **Hierarchical** | `contains` / `in_room` | object ∈ StructureMesh footprint | **deterministic** |
| **Metric / spatial** | `above`/`below`, `near`/`far`, `distance`, `inside`, `touching`, `front`/`behind`/`left`/`right` | from `bbox` (gravity-aligned / room-canonical) | **deterministic** |
| **Semantic** | `on_top_of`, `support`, `attached_to`, `same_material` | rules over category + geometry | **heuristic** |
| **Functional / affordance** | `opens_via`, `used_for`, `pressable`, `openable`, `graspable` | **VLM (Qwen) on rendered views** | **vlm** |
| **Interactive element** | `has_part` + part nodes | **VLM (Qwen) on rendered views** | **vlm** |
| **Temporal** | — | static scenes → **n/a** | — |

Every edge stores:
`source, target, predicate, family, confidence, reference_frame, value?, note?, tier`.

The `tier` field (deterministic / heuristic / vlm / gold) is the provenance
signal; the numeric `confidence` is the tier's calibrated value
(deterministic edges → 1.0 / high; heuristic → ~0.6–0.7; VLM → reported value).

### Determinism / caps
- Distance edges are KNN per object (K=8) to avoid O(n²); capped at
  `max_distance_edges`.
- `near`/`far`/`above`/`touching`/`inside` use fixed thresholds
  (`near_dist`, `far_dist`, `touch_eps`, `overlap_eps`) in `RelationConfig`.
- Above/below are never mutually generated (an edge is added only when the
  vertical order is unambiguous).

---

## 3. Reference-frame standard (decision #5)

Because InternScenes scenes are **static** (no moving camera), every *relative*
predicate must be tied to an explicit reference frame stored on the edge.
`gravity-safe` predicates (`above`/`below`, `near`/`far`, `distance`, `inside`)
carry **no** horizontal frame (`reference_frame = "world"`).

| Frame | `up` | `forward` (horizontal) | `right` | Use |
|---|---|---|---|---|
| **world** | +Z (gravity) | — | — | gravity-safe predicates only |
| **room_canonical** (primary) | +Z | **principal axis of the room** (PCA of object centroids in XY, deterministic sign) | `up × forward` | `front`/`behind`/`left`/`right` |
| **object_intrinsic** | object local +Z | object local +X | object local +Y | object-relative predicates (e.g. "handle is on the front of the cabinet") |

A frame is an orthonormal 3×3 rotation matrix **R** whose columns are
`[right, forward, up]` in world coordinates, plus an origin:
- `world_to_frame(p) = Rᵀ · (p − origin)`
- `frame_to_world(p') = R · p' + origin`

**room_canonical** is built from the PCA of the object centroids in the XY
plane: `forward` = the principal eigenvector with a deterministic sign
(`forward.x > 0`, else `forward.y > 0`), falling back to the longer room axis
and then +X. `up` = +Z; `right` = `up × forward`.

**object_intrinsic** is the object's Euler rotation (from `bbox[6:9]`).

Every relative predicate stores `reference_frame ∈ {room_canonical,
object_intrinsic}` **explicitly**; the builder records the frame it used.

---

## 4. Annotation track (decisions #3, #4)

```
compose scene GLB
  → multi-view render (orbit N views + top-down)         [render_multi.py]
  → candidate generation (geometry + rules)             [scene_info / relations / vlm_annotate]
  → VLM annotation (Qwen3.8-27B-NVFP4 via Inferact)     [vlm_annotate.py]
        inputs : rendered views + scene.json object list + candidates
        outputs: relation labels + interactive elements + affordances + confidence
  → consistency checker (inverse / symmetry / containment / cycle)  [vlm_annotate.consistency_check]
  → [post-v1] human verification → Gold set
```

### 4.1 Multi-view render (`render_multi.py`)
- Orbits the camera around the room centre at eye level for **N** evenly spaced
  views (default 8, range ~8–12, configurable) plus one **top-down** view.
- Reuses `render.py` / `_render_in_blender.py` camera placement, lighting, and
  the Blender bootstrap. Renders the composed GLB **once** and captures all
  views in a single Blender session for efficiency.
- Output: `output/render/<scene>__view_k.png` + `output/render/<scene>__topdown.png`.

### 4.2 VLM backend (`vlm_annotate.py`)
A thin, **configurable** wrapper around a Qwen-class foundation model served via
Inferact. Configuration (`VLMConfig`, from env / JSON):

| Field | Default | Meaning |
|---|---|---|
| `endpoint` | `""` (→ deterministic fallback) | Inferact / Qwen serving URL |
| `model_id` | `Qwen3.8-27B-NVFP4` | served model id |
| `prompt_template` | `DEFAULT_PROMPT` | prompt template |
| `temperature` | `0.0` | sampling temperature |
| `timeout`, `max_tokens` | — | request limits |

- **Deterministic fallback**: when no endpoint is configured, the module emits
  rule-based affordances / interactive parts (category → affordance tables) so
  the graph is always well-formed and the pipeline is runnable without a server.
- **Local render inputs**: local PNG/JPEG paths are encoded as `data:` URLs
  before sending them to an OpenAI-compatible endpoint; HTTP(S) and existing
  `data:` URLs are passed through. The pipeline uses the eight orbit renders
  and top-down render, with local files checked before making a VLM request.
- **Foundation-model manifest**: every run records a manifest
  (`mode, backend, endpoint, model_id, temperature, prompt_template, n_calls,
  n_images, n_objects, n_affordances, n_interactive, config_fingerprint,
  scene_id`) for reproducibility (matches the project's foundation-model policy).
  The manifest is embedded in `scene_graph.json` as `vlm_manifest`.
- **Cost / token logging**: `n_calls` / `n_images` / token counters are tracked
  in the manifest (a real endpoint populates them; the fallback reports 0).

The VLM contract consumed by the graph builder:
```
{
  "affordances": { node_id: [ "opens", "graspable", … ] },
  "interactive": [ { id, parent, category, affordances, confidence, … } ],
  "manifest": { … }
}
```
Affordances are attached as **node attributes**; interactive parts become
**part nodes** with `has_part` (functional) edges from their parent object.

### 4.3 Consistency checker (`vlm_annotate.consistency_check`)
Cheap, high-value checks on a built graph:
- every edge endpoint references an existing node id (no dangling edges);
- no self-loops (`source == target`);
- every edge carries a valid `reference_frame`;
- `above(a,b)` ⇔ not `above(b,a)` (mutual-inconsistency guard);
- confidence values in [0, 1];
- no duplicate `(source, target, predicate)` triplets (covers symmetric
  `touching` / `near` and cycle-free containment, since `contains` is
  room→object only).

A failing consistency check is a **warning** (the graph is still written) so
problems are surfaced without blocking the batch.

---

## 5. Evaluation harness (`evaluate_graph.py`)

Factorised (not a single Recall@K). Each sub-metric is reported independently
and combined into a **Pareto** frontier (quality vs edges / latency).

| Sub-metric | Scores |
|---|---|
| **Node** | mAP, mean 3D IoU, per-category Macro-F1 |
| **Relation** | Triplet Precision / Recall / F1, **mRecall@K** (long-tail aware) |
| **Spatial** | Macro-F1 + geometric-consistency |
| **Hierarchy** | parent-edge F1 / level-wise F1 |
| **Affordance / interactive** | AP / IoU |
| **Calibration (VLM)** | ECE / Brier |
| **Efficiency** | graph bytes, #nodes, #edges (latency / memory recorded when timed) |

`evaluate(reference, prediction)` compares a predicted graph to a reference
and reports ECE/Brier calibration over predicted edges whose provenance tier
is `vlm` (against exact reference triplets).
`self_report(graph)` runs the consistency gate. `pareto([...])` returns the
Pareto-optimal frontier (max quality, min edges / latency).

---

## 6. CLI & pipeline integration

```bash
# build a scene graph (deterministic + optional VLM layer)
internscenes graph <scene>                 # → output/graph/<scene>.json
internscenes graph <scene> --vlm          # apply VLM annotation (fallback if no endpoint)
internscenes graph <scene> --self         # self-consistency report
internscenes graph <scene> --reference R.json   # factorised evaluation vs reference

# full pipeline now includes a graph stage (+ multi-view render for VLM)
internscenes run --scene <scene> --vlm
internscenes run -n 30 --seed 0 --vlm     # pilot subset
```

Pipeline stages (`pipeline.run_scene`): `compose → render → topdown → info →
graph → normalize → questions`. Multi-view rendering runs only with `--vlm`;
it can be explicitly skipped with `--skip-render-multi` only when no configured
VLM endpoint needs image inputs. The graph is copied into the normalized scene
folder after it is built.
`assemble_normalized` copies `scene_graph.json` into `output/normalized/<scene>/`.
Skip flags: `--skip-graph`, `--skip-render-multi`; VLM: `--vlm`.

---

## 7. v1 scale & rollout

- **Pilot**: 20–30 scenes (1–2 datasets, scenes with StructureMesh and a
  reasonable object count, e.g. `scannet/scene0313_00`).
- **Expand**: ~200 scenes.
- **Post-v1**: human verification → **Gold** tier.

## 8. Open items (non-blocking)
- Exact **Inferact / Qwen3.8-27B-NVFP4 serving endpoint** (the module is a thin
  configurable wrapper; endpoint + model id + prompt template are config).
- **Multi-view count** (proposed 8–12 views/scene).
- **v1 subset** composition (proposed 1–2 datasets, ~200 scenes, pilot 20–30).

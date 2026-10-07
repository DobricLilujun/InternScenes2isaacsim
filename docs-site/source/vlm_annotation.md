---
title: VLM Annotation
description: The vision-language annotation track, backend and reproducibility manifest
---

# VLM Annotation

The functional / affordance / interactive layer of a scene graph is derived by
a **vision-language model (VLM)** looking at rendered views of the scene. The
module is `internscenes.vlm_annotate`. It is a **thin, configurable backend**
with a **deterministic fallback**, so the pipeline never blocks on a missing
endpoint.

## The annotation track

```text
compose scene GLB
  → multi-view render (orbit N views + top-down)      render_multi
  → candidate generation (geometry + rules)           scene_info / path_planner
  → VLM annotation (Qwen3.8-27B-NVFP4 via Inferact)   vlm_annotate
        inputs:  rendered views + scene.json object list + candidates
        outputs: relation labels + interactive elements + affordances + confidence
  → consistency checker (inverse / symmetry / containment)
  → [post-v1] human verification → Gold set
```

## Configure the backend

The backend is fully configurable via `VLMConfig`:

| Field | Default | Meaning |
| --- | --- | --- |
| `endpoint` | `None` | base URL of an OpenAI-compatible chat API |
| `model_id` | `Qwen3.8-27B-NVFP4` | model id |
| `prompt_template` | built-in | the prompt with `{category}` |
| `temperature` | `0.2` | sampling temperature |
| `fallback` | `True` | fall back to deterministic rules if the endpoint is unset / fails |

Configure from the environment, JSON, or directly:

```python
from internscenes import vlm_annotate

cfg = vlm_annotate.VLMConfig.from_env()     # reads INTERNSCENES_VLM_* env vars
# or:
cfg = vlm_annotate.VLMConfig.from_json("vlm.json")
# or:
cfg = vlm_annotate.VLMConfig(
    endpoint="https://inferact.example.com/v1",
    model_id="Qwen3.8-27B-NVFP4",
    temperature=0.2,
)
```

The CLI passes `--vlm` to use the configured backend (with deterministic
fallback when no endpoint is set).

## Annotate

```python
result = vlm_annotate.annotate(
    scene_id="scannet/scene0313_00",
    records=object_records,
    cfg=cfg,
    views={"view_0": "output/render/…/view_0.png", "topdown": "…/topdown.png"},
)
# result = {"relations": [...], "interactive": [...], "manifest": {...}}
```

## The reproducibility manifest

Every run records a **foundation-model manifest** for reproducibility
(matching the foundation-model policy). It is attached to the graph as
`vlm_manifest`:

| Field | Meaning |
| --- | --- |
| `mode` | `vlm` or `deterministic_fallback` |
| `backend` | backend name (`none` when no endpoint) |
| `endpoint` | the endpoint used (`null` if fallback) |
| `model_id` | the model id |
| `temperature` | sampling temperature |
| `prompt_template` | the exact prompt template |
| `n_calls` | number of VLM calls |
| `n_images` | number of images sent |
| `n_objects` / `n_affordances` / `n_interactive` | counts |

## Deterministic fallback

When no endpoint is configured (or a call fails), the backend falls back to
category-based rules so the graph is still complete:

```python
vlm_annotate.deterministic_affordances("door")       # -> ["open", "close", ...]
vlm_annotate.deterministic_interactive("door", "obj_3")  # -> [{"name": "handle", ...}]
```

These fallback affordances are tagged `tier = "vlm"` so a consumer can
distinguish them from deterministic edges.

## Consistency checker

`consistency_check(graph)` validates the graph and returns a report:

```python
rep = vlm_annotate.consistency_check(graph)
# {"ok": True, "num_issues": 0, "issues": [...]}
```

The checks (see [Relations](/relations.html)) are cheap and high-value:
inverse (`above ⇔ below`), symmetry (`touching`, `near`), containment and
cycle-freedom.

## Next

- [Multi-View Rendering](/rendering.html) — the capture stage that feeds the VLM.
- [Evaluation Metrics](/evaluation.html) — how VLM output is scored &amp; calibrated.

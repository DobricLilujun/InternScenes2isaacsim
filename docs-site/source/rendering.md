---
title: Multi-View Rendering
description: Multi-view orbit and top-down capture for the VLM annotation track
---

# Multi-View Rendering

`internscenes.render_multi` captures a ring of **orbit** cameras around the
room centre at eye level plus one **top-down** view, in a single Blender
session (the glTF is imported once and reused for every camera). The captures
feed the [VLM annotation](/vlm_annotation.html) track.

## What it produces

For a scene, `render_multi` writes:

```text
<scene_id>__view_0.png
<scene_id>__view_1.png
...
<scene_id>__view_{n-1}.png
<scene_id>__topdown.png
```

The default is **8 orbit views + 1 top-down** (count configurable). The
`scene_id` is flattened for filenames (`scannet/scene0013_00` →
`scannet_scene0013_00`), so files land directly in the render directory with
no nesting.

## How it works

```python
def render_multi(glb_path, out_dir=None, engine="auto",
                 n_views=8, height=1.6, resolution=(1920, 1080),
                 scene_id=None) -> list[str]:
    ...
```

- **import once** — the composed GLB is imported a single time.
- **hide structure** — floor / wall / ceiling hidden so the interior is visible
  (same as `render.py`).
- **lighting** — a sun + world background (same as `render.py`).
- **orbit** — cameras placed evenly around the room centre at eye height.
- **top-down** — one camera above the room looking down.
- **engine** — `auto` (Eevee → Cycles) or `CYCLES`.

## Bootstrapped inside Blender

Like `render.py`, the module **must run inside Blender's Python** (it imports
`bpy`). It is bootstrapped by `internscenes._render_in_blender`, which
re-executes the module inside Blender's interpreter via the project venv.

The pipeline invokes it by setting `INTERN_RENDER_FILE=render_multi.py` and
running the Blender bootstrap — the same mechanism as the single perspective
render:

```text
blender --background --python _render_in_blender.py -- \
    --glb <glb> --out <render_dir> --engine=EEVEE \
    --views=8 --height=1.6 --scene <scene_id>
```

The bootstrap reads `INTERN_RENDER_FILE` (default `render.py`) so one script
serves both the single and multi-view renders.

## Run via the pipeline

```sh
# full pipeline includes render_multi
internscenes run --scene scannet/scene0313_00 --resume

# skip the multi-view stage
internscenes run --scene scannet/scene0313_00 --skip-render-multi
```

Or call the stage directly:

```python
from internscenes import pipeline
ok = pipeline.stage_render_multi("scannet/scene0313_00", n_views=4)
```

## Requirements

- A **composed GLB** for the scene (run `internscenes run … --resume` or
  compose first).
- **Blender** on `PATH` (or set `BLENDER=/path/to/blender`).

If the composed GLB is missing, the stage degrades to a warning and the graph
stage falls back to deterministic affordances — the pipeline does not block.

## Next

- [VLM Annotation](/vlm_annotation.html) — consumes these captures.
- [CLI Reference](/cli.html) — every flag for the pipeline.

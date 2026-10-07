---
title: CLI Reference
description: Every SAGE-Bench command and flag
---

# CLI Reference

The `internscenes` console command exposes the pipeline and the scene-graph
tools.

## Commands

| Command | Purpose |
| --- | --- |
| `run` | run the full pipeline |
| `render` | render a perspective PNG (Blender) |
| `topdown` | render a 2D top-down projection |
| `info` | export scene metadata JSON |
| `graph` | build a scene-graph JSON (deterministic + optional VLM) |
| `batch` | run the legacy batch pipeline |
| `questions` | generate object-finding navigation questions |
| `plan-questions` | plan A* paths and render path top-downs |

## `run` — full pipeline

```sh
# reproducible sampling (2 scenes / dataset)
internscenes run -n 2 --seed 200

# one scene
internscenes run --scene scannet/scene0313_00

# reuse verified output + VLM layer
internscenes run --scene scannet/scene0313_00 --resume --vlm

# no Blender rendering
internscenes run --scene scannet/scene0313_00 --skip-render

# no graph / multi-view stage
internscenes run --scene scannet/scene0313_00 --skip-graph --skip-render-multi
```

| Flag | Meaning |
| --- | --- |
| `--scene` | specific scene id(s); repeatable |
| `-n` | scenes per dataset |
| `--seed` | RNG seed for sampling |
| `--resume` | reuse verified existing output |
| `--vlm` | apply the VLM annotation layer |
| `--disable-auto-fill` | use local assets only |
| `--skip-render` / `--skip-render-multi` / `--skip-graph` / `--skip-topdown` / `--skip-questions` | skip a stage |
| `--plan-questions` | also plan paths + render path top-downs |
| `--min-room-extent` | skip scenes below a floor dimension (m) |

## `graph` — scene graph

```sh
# deterministic
internscenes graph scannet/scene0313_00 --out output/graph

# VLM layer (deterministic fallback if no endpoint)
internscenes graph scannet/scene0313_00 --vlm --out output/graph

# self-consistency report
internscenes graph scannet/scene0313_00 --self

# evaluate against a reference
internscenes graph scannet/scene0313_00 --reference output/graph/ref.json
```

| Argument / flag | Meaning |
| --- | --- |
| `scene` (positional) | scene id, e.g. `scannet/scene0313_00` |
| `--out` | output path (a file or a directory) |
| `--vlm` | apply the VLM annotation layer |
| `--reference` | reference `scene_graph.json` for factorised evaluation |
| `--self` | report only self-consistency (no reference) |

> `--out` may be a **file** or a **directory**; a bare directory gets the
> `<flat>_vlm.json` name appended as appropriate.

## `render` / `topdown`

```sh
internscenes render --glb output/composed/.../glb_scene.glb --out output/render --engine EEVEE
internscenes topdown --scene scannet/scene0313_00
```

## Environment variables

| Variable | Meaning |
| --- | --- |
| `INTERN_DATA_DIR` | path to `data/` (default `data`) |
| `BLENDER` | path to the Blender binary (else detected on `PATH`) |
| `INTERN_VLM_ENDPOINT` | VLM base URL (OpenAI-compatible) |
| `INTERN_VLM_MODEL_ID` | VLM model id (default `Qwen3.8-27B-NVFP4`) |
| `INTERN_VLM_TEMPERATURE` | sampling temperature |

## Next

- [Quickstart](/quickstart.html) — the common workflow.
- [Installation](/installation.html) — setup.

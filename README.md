# InternScenes to Isaac Sim

Turn [InternScenes](https://github.com/InternRobotics/InternScenes) indoor layouts
into USD scenes for Isaac Sim / Omniverse, with perspective images, top-down
images, scene metadata, and object-finding navigation questions.

**Missing object models are downloaded automatically.** Use
`--disable-auto-fill` when you want to use local assets only.

---

## SAGE-Bench — Scene-graph Assessment & Generation Evaluation

This repository also contains **SAGE-Bench**: a scene-graph benchmark that turns
the InternScenes layouts into typed, confidence-tiered scene graphs (nodes,
spatial / hierarchical / semantic / functional edges), a documented
reference-frame standard, a VLM annotation track, and a factorised evaluation
harness — built on the 2,847 scenes, 87,733 objects and 258 categories already
present in InternScenes.

🌐 **Documentation &amp; online docs:** https://dobriclilujun.github.io/SAGE-Bench

```sh
# build a scene graph for one scene (deterministic, then VLM-augmented)
internscenes graph scannet/scene0313_00 --out output/graph
internscenes graph scannet/scene0313_00 --vlm --out output/graph

# evaluate a prediction against a reference (factorised metrics)
internscenes graph scannet/scene0313_00 --reference output/graph/ref.json

# programmatic
python -c "from internscenes import scene_graph, evaluate_graph; \"\"

The SAGE-Bench modules (`scene_graph`, `relations`, `coordinate`,
`vlm_annotate`, `evaluate_graph`, `render_multi`) are exposed as lazy imports
under `internscenes` and are **testable without Blender or asset composition** —
they run from `layout.json` and structure-mesh data only. See the
[documentation](https://dobriclilujun.github.io/SAGE-Bench) and
`docs/SCENE_GRAPH.md` for the full schema, edge families, reference frames and
VLM protocol.

---

## Setup

Requires Python 3.11+, InternScenes layout data, and Blender for perspective
rendering. Blender 4.5+ is recommended; Blender 4.0.2 has also been tested on
two scenes with EEVEE.

```bash
cd InternScenes2isaacsim
uv venv --python 3.11 .venv311
source .venv311/bin/activate
uv pip install -e .
```

Without `uv`, use `python3.11 -m venv .venv311`, activate it, then run
`pip install -e .`.

Prepare layouts and asset-library metadata using the
[upstream data guide](https://github.com/InternRobotics/InternScenes/blob/main/data/README.md):

```text
data/
  Layout_info/<scene>/layout.json
  Layout_info/<scene>/StructureMesh/
  asset_library/uid_2_angle.json
  asset_library/uid_2_origin_cate.json
  asset_library/<model files>
```

Auto-fill downloads missing object GLBs, not layouts, structure meshes, or the
asset-library metadata files. Blender is detected on `PATH`; if needed, set
`export BLENDER=/path/to/blender`. Isaac Sim is optional: conversion uses it
when installed, otherwise the USD fallback backend.

## Run

Run these commands from the project root with the virtual environment active:

```bash
# Two scenes per dataset, reproducible sampling (8 scenes across 4 datasets)
internscenes run -n 2 --seed 200

# One scene
internscenes run --scene scannet/scene0330_00

# No downloads; missing models still make the run fail
internscenes run -n 2 --seed 200 --disable-auto-fill

# Reuse verified existing output
internscenes run --scene scannet/scene0330_00 --resume

# No Blender rendering
internscenes run --scene scannet/scene0330_00 --skip-render

# Generate navigation paths and action sequences too
internscenes run --scene scannet/scene0330_00 --plan-questions
```

The pipeline checks model references, downloads only missing files, verifies
them, then composes and processes each scene. Partial scenes are not reported
as complete. A failed download or incomplete run returns a nonzero exit code.

### Important: Objaverse

The upstream `objaverse/` library is published as roughly **100 GB of split
archives**, not individual GLBs. Auto-fill cannot download those models one
by one. Prepare that library separately if your scenes reference it.
The pipeline reports unresolved models instead of silently skipping them,
and does not automatically download the large archives.

## Output

Each scene is collected under `output/normalized/<scene_id_with_underscores>/`:

```text
scene.usd
textures/
scene.json
perspective.png       # unless --skip-render
topdown.png           # unless --skip-topdown
questions.jsonl       # unless --skip-questions
questions/            # with --plan-questions
```

Check `output/batch/manifest.json` for run status and
`output/batch/download.log` for download results. Per-scene asset reports are
under `output/info/*_missing.json`; complete compositions report zero missing.

## Python API

```python
from internscenes import pipeline

# Same default asset policy as the CLI.
result = pipeline.run_scene("scannet/scene0330_00")
if result["status"] != "complete":
    raise RuntimeError(f"Scene failed: {result}")

# Disable downloads explicitly.
result = pipeline.run_scene("scannet/scene0330_00", auto_fill=False)
```

See [USAGE.md](USAGE.md) for options, individual stages, configuration, and
troubleshooting. Run regression tests with:

```bash
python -m unittest discover -s tests -v
```

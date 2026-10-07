---
title: Installation
description: How to install SAGE-Bench and its dependencies
---

# Installation

SAGE-Bench is a Python package. It needs Python **3.11+** and the InternScenes
layout data. Perspective / multi-view rendering additionally needs **Blender**.

## 1. Create a virtual environment

```sh
cd InternScenes2isaacsim
uv venv --python 3.11 .venv311
source .venv311/bin/activate
```

Without `uv`:

```sh
python3.11 -m venv .venv311
source .venv311/bin/activate
```

## 2. Install the library

```sh
# editable install (recommended for development)
uv pip install -e .            # or: pip install -e .
```

This registers the `internscenes` console command and installs the core
dependencies (`trimesh`, `open3d`, `numpy`, `matplotlib`, `huggingface-hub`,
`usd-exchange`, `shapely`).

### Optional extras

```sh
# running the render module *inside* Blender
pip install -e ".[studio]"     # bpy>=4.2

# Isaac Sim USD conversion backend
pip install -e ".[isaac]"

# notebook + test tooling
pip install -e ".[dev]"
```

## 3. Point at your data

SAGE-Bench reads layouts from `data/`. By default it looks for
`data/Layout_info/…`; override with the `INTERN_DATA_DIR` environment variable:

```sh
export INTERN_DATA_DIR=/path/to/data
```

Expected layout:

```text
data/
  Layout_info/<dataset>/<scene>/layout.json
  Layout_info/<dataset>/<scene>/StructureMesh/   # floor / wall / ceiling
  asset_library/uid_2_angle.json
  asset_library/uid_2_origin_cate.json
  asset_library/<model files>
```

> **Objaverse note.** The upstream `objaverse/` library is ~100 GB of split
> archives, not individual GLBs. Auto-fill cannot download those models one by
> one — prepare that library separately if your scenes reference it.

## 4. Verify the install

```sh
# the console command is available
internscenes --help

# the package imports
python -c "import internscenes; print(internscenes.__name__)"

# regression tests
python -m unittest discover -s tests -v
```

## 5. Blender (for rendering stages)

Blender is detected on `PATH`. If it is not, set the path explicitly:

```sh
export BLENDER=/path/to/blender
```

Blender **4.5+** is recommended; **4.0.2** has also been tested on two scenes
with EEVEE. Rendering is only needed for the perspective / multi-view stages —
the scene-graph, relation and evaluation stages run without Blender.

## Next

- [Quickstart](/quickstart.html) — build your first scene graph in 60 seconds.
- [Python API](/python_api.html) — programmatic use.
- [CLI Reference](/cli.html) — every command and flag.

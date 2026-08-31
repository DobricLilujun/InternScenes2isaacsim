# InternScenes → Isaac Sim

Convert **InternScenes** 3D indoor scenes into **USD** (the asset format used by
NVIDIA Isaac Sim / Omniverse), render **perspective** (Blender/EEVEE) and
**2D top-down** views as visual proof, and export **per-scene metadata**
(room dimensions, object list with positions/sizes/rotations, and a
collision-aware robot placement) as JSON.

The pipeline runs fully on a single machine — no remote server required.

```
data/Layout_info/<scene>/layout.json
        │  compose (trimesh)
        ▼
output/composed/<scene>/glb_scene.glb
        │  ┌──────────────────────────────────────────────────────────────────┐
        │  │  glb_to_usd  →  output/normalized/<ds>_<id>/scene.usd           │   (auto: Isaac Sim → usd-exchange fallback)
        │  │  glb_render  →  output/render/<scene>/perspective.png           │   (Blender EEVEE, camera inside the room)
        │  └──────────────────────────────────────────────────────────────────┘
        │  ┌──────────────────────────────────────────────────────────────┐
        │  │  topdown_projection → output/topdown/<scene>_topdown.png     │   (2D ground-plane projection)
        │  │  scene_info       → output/info/<scene>.json                │   (dimensions, objects, Go2 placement)
        │  └──────────────────────────────────────────────────────────────┘
```

## Features

- **GLB → USD** with **auto backend** selection (`internscenes.glb_to_usd`):
  - **Primary** — Isaac Sim's `omni.kit.asset_converter`
    (`internscenes.glb_to_usd_isaac`), matching the
    [official InternScenes Real2Sim release](https://github.com/InternRobotics/InternScenes).
    Produces the full `OmniPBR.mdl` material graph the InternScenes
    `trajectory_tools` renderer expects, with glTF PBR extensions
    (`KHR_materials_variants`, multi-UV, glTF mesh compression).
  - **Fallback** — `usd-exchange` / `pxr` (`internscenes.glb_to_usd_fallback`):
    full PBR `UsdPreviewSurface` materials with metallic / roughness / opacity,
    `UsdShade.MaterialBindingAPI` bindings, exported texture PNGs, vertex
    normals, UVs (`primvars:st`), and `primvars:class` for instance
    segmentation.
  - Default output is the **normalized** per-scene folder
    (`output/normalized/<dataset>_<id>/scene.usd` + `textures/`), so the
    USD is the pipeline's primary artefact.
  - **Per-object representative colour** extraction from the source GLB
    PBR materials, stored in `scene.json`.
  - **Navigation-question generation**: produce object-finding tasks of
    the form "Find the red chair" with target positions, Go2 start pose,
    and distance, written as JSONL.
- **Blender headless rendering** (EEVEE) with a camera placed *inside* the room.
- **2D top-down projection** with a collision-aware Unitree **Go2** robot marker,
  nearest-obstacle clearance, and metre-scale grid.
- **Scene metadata export** (JSON): room dimensions (m), per-object category/position/
  size/rotation, category frequency, and the Go2 placement.
- **Batch orchestration** (`internscenes run` / `internscenes batch`): sample *N*
  random scenes per category, run compose → render → top-down → info for each,
  resumable and logged.
- **Type annotations, logging, and exception handling** throughout the codebase.

## Project layout

```
InternScenes2isaacsim/
├── src/internscenes/          # installable Python package
│   ├── compose.py             # SceneComposer: layout.json + asset library -> glb_scene.glb
│   ├── scene_info.py          # per-scene metadata extraction (JSON)
│   ├── sampler.py             # deterministic per-category random sampling
│   ├── pipeline.py            # full pipeline Python API
│   ├── cli.py                 # unified CLI (`run` + legacy commands)
│   ├── glb_to_usd.py          # GLB -> USD dispatcher (auto backend, normalized output)
│   ├── glb_to_usd_isaac.py    # Primary backend — Isaac Sim's omni.kit.asset_converter
│   ├── glb_to_usd_fallback.py # Fallback backend — usd-exchange / pxr
│   ├── render.py              # GLB -> perspective PNG (Blender, run via `blender --python`)
│   ├── _render_in_blender.py  # Blender bootstrap (runs render.py inside Blender's Python)
│   ├── topdown.py             # layout.json -> 2D top-down PNG
│   ├── place_go2.py           # collision-aware Go2 placement (shared by topdown)
│   ├── download.py            # download per-object GLBs (`--auto` fills only what's missing)
│   └── __init__.py            # public API (lazy submodules for Blender compatibility)
├── data/
│   ├── Layout_info/        # per-scene layout.json (one folder per scene)
│   └── asset_library/      # per-object GLB assets (22k+)
├── output/                 # composed/ render/ topdown/ info/ batch/ normalized/
└── pipeline_commands_test.ipynb  # end-to-end walkthrough notebook
```

## Installation

Requires **Python ≥ 3.11** and **Blender ≥ 4.5** (the project was developed with
Python 3.11 and Blender 5.1.2). [uv](https://docs.astral.sh/uv/) is recommended.

```bash
# 1. virtual environment
uv venv --python 3.11 .venv311
source .venv311/bin/activate            # or use .venv311/bin/python directly

# 2. dependencies
uv pip install --python .venv311/bin/python \
    trimesh open3d numpy matplotlib huggingface-hub usd-exchange shapely

# 3. (optional) install the package itself for the CLI
pip install -e .
```

> **Blender** is *not* a Python dependency. Provide its path via the `BLENDER`
> environment variable (see [Configuration](#configuration)).

### Data

InternScenes data (the `layout.json` files and the per-object GLB `asset_library`)
is downloaded from the Hugging Face repository **`InternRobotics/InternScenes`** and
placed under `data/`. The 5 example scenes in the notebook ship composed GLBs in
`output/composed/`.

## Usage

All commands below assume the project root is the working directory and the
`.venv311` virtual environment is active.

### Quick start with the unified CLI

```bash
# install the package
pip install -e .

# one specific scene -> output/normalized/scannet_scene0001_00/
internscenes run --scene scannet/scene0001_00

# random batch: 10 scenes per dataset, with auto-fill
internscenes run -n 10 --seed 0 --auto-fill
```

### Single scene (programmatic)

```bash
# 1. compose the GLB from layout.json + the asset library
.venv311/bin/python -c "from internscenes import compose; \
  compose.SceneComposer().compose_one_scene('scannet/scene0001_00')"

# 2. GLB -> USD (auto backend: Isaac Sim if installed, else usd-exchange).
#    Output lands in the normalized per-scene folder by default.
.venv311/bin/python -c "from internscenes.glb_to_usd import build_usd; \
  build_usd('output/composed/scannet/scene0001_00/glb_scene.glb')"
# -> output/normalized/scannet_scene0001_00/scene.usd
#    output/normalized/scannet_scene0001_00/textures/*.png

# 3. GLB -> perspective PNG (Blender, headless)
internscenes render scannet/scene0001_00 --engine EEVEE

# 4. 2D top-down projection
internscenes topdown scannet/scene0001_00

# 5. per-scene metadata (dimensions, objects, Go2 placement)
internscenes info scannet/scene0001_00

# 6. assemble the per-scene normalized folder (USD + textures + scene.json + PNGs)
.venv311/bin/python -c "from internscenes import pipeline; \
  pipeline.assemble_normalized('scannet/scene0001_00')"
```

### Batch with the unified CLI

```bash
# N random scenes per dataset
internscenes run -n 50 --seed 0

# limit to specific datasets
internscenes run -n 20 --datasets scannet 3rscan --seed 0

# auto-fill missing assets (recommended when the asset library is incomplete)
internscenes run -n 50 --seed 0 --auto-fill

# resume an interrupted run
internscenes run -n 50 --seed 0 --resume
```

### Batch

Render **N** random scenes per category (compose → render → top-down → info),
writing artifacts into `output/`:

```bash
internscenes run -n 50 --seed 0
# resume a previously interrupted run (skips stages whose output already exists)
internscenes run -n 50 --seed 0 --resume
# **auto-fill missing assets** — pre-compose every scene once, collect the
# missing UIDs into output/info/*_missing.json, download *only* those, then
# re-compose for real.  Avoids downloading the whole 22k-asset library.
internscenes run -n 50 --seed 0 --auto-fill
```

You can also run the auto-filler on demand:

```bash
# dry-run: print which UIDs would be downloaded
.venv311/bin/python -m internscenes.download --auto --scene scannet/scene0001_00 --dry-run
# actually download
.venv311/bin/python -m internscenes.download --auto --scene scannet/scene0001_00
```

Outputs: `output/composed/…/glb_scene.glb`, `output/render/…/perspective.png`,
`output/topdown/…_topdown.png`, and `output/info/….json`; a run manifest is written
to `output/batch/manifest.json`.  The USD + textures are produced (or picked up
from a previous run) by the normalization step at the end, in
`output/normalized/<ds>_<id>/`.

### CLI commands

```bash
# unified run (recommended)
internscenes run -n 50 --seed 0
internscenes run --scene scannet/scene0001_00
internscenes run -n 10 --datasets scannet --seed 0 --auto-fill

# legacy single-stage commands
internscenes render scannet/scene0001_00 --engine EEVEE
internscenes topdown scannet/scene0001_00
internscenes info   scannet/scene0001_00 --out output/info/scannet_scene0001_00.json
internscenes questions --scene scannet/scene0001_00 -n 5 --seed 0
internscenes batch  -n 50 --seed 0
```

### Notebook

`pipeline_commands_test.ipynb` walks the pipeline end to end, executing each stage
and verifying the output file. Render and export *every* sampled scene with
`internscenes.run`.

## Configuration

| Setting | Where | Default | Purpose |
|---|---|---|---|
| `BLENDER` | env var | `/home/ubadmin/tools/blender/blender-5.1.2-linux-x64/blender` | Blender binary used by `internscenes render` |
| `INTERN_DATA_DIR` | env var | `<root>/data` | Root for `Layout_info/` and `asset_library/` |
| `INTERN_OUTPUT_DIR` | env var | `<root>/output` | Output root (`composed/`, `render/`, `usd/`, `info/`, …) |
| `-n` | `internscenes run` / `batch` | `50` | Scenes sampled per category |
| `--seed` | `internscenes run` / `batch` | `0` | RNG seed (reproducible sampling) |
| `--resume` | `internscenes run` / `batch` | off | Skip stages whose output file already exists |
| `--auto-fill` | `internscenes run` / `batch` | off | Pre-pass: compose once, collect missing UIDs, download only those, then re-compose |
| `--engine` | `internscenes render` | `EEVEE` | Render engine (`EEVEE` or `CYCLES`) |

Paths are resolved relative to the project root by default; override with the
environment variables above to point at an alternate data/output location.

## Python API

The same pipeline is available programmatically:

```python
from internscenes import pipeline

# one scene
pipeline.run_scene("scannet/scene0001_00")

# resolve and run a batch
scenes = pipeline.resolve_scenes(n=10, seed=0, datasets=["scannet"])
for sid in scenes:
    pipeline.run_scene(sid)

# just assemble the normalized folder from existing artefacts
pipeline.assemble_normalized("scannet/scene0001_00")
```

## Outputs

| Path | Meaning |
|---|---|
| `output/composed/<scene>/glb_scene.glb` | composed scene GLB (shared input) |
| `output/normalized/<dataset>_<id>/scene.usd` | USD stage (auto backend: Isaac Sim if available, else usd-exchange) |
| `output/normalized/<dataset>_<id>/textures/` | extracted PBR textures (next to the USD) |
| `output/render/<scene>/perspective.png` | Blender perspective render |
| `output/topdown/<scene>_topdown.png` | 2D top-down projection |
| `output/info/<scene>.json` | per-scene metadata |
| `output/batch/manifest.json` | batch run status (per scene) |
| `output/scene_inventory.json` | full list of all scene IDs |

## Scene metadata format (`output/info/<scene>.json`)

```json
{
  "scene_id": "scannet/scene0001_00",
  "dataset": "scannet",
  "num_objects": 23,
  "num_valid_objects": 23,
  "room_dimensions_m": { "width": 7.4, "depth": 9.0, "height": 2.5, "min_x": -3.8, "max_x": 3.6, "…": "…" },
  "category_counts": { "chair": 5, "table": 2, "…": "…" },
  "go2_placement": { "valid": true, "position_m": { "x": -3.8, "y": 4.6 }, "clearance_m": 1.4 },
  "objects": [
    { "id": 0, "category": "chair", "model_uid": "gr100/…",
      "position_m": { "x": 0.79, "y": 0.80, "z": 0.48 },
      "size_m": { "length": 0.69, "width": 2.22, "height": 0.97 },
      "rotation_rad": { "x": -1.6, "y": 0.0, "z": 0.0 },
      "color": { "r": 0.31, "g": 0.24, "b": 0.19, "source": "baseColorTexture" },
      "valid": true }
  ]
}
```

## Troubleshooting

- **`MISSING` in the environment check** — install the missing dependency or set the
  relevant path (`BLENDER`, `INTERN_DATA_DIR`, `INTERN_OUTPUT_DIR`).
- **Blender render produces no PNG** — ensure `--glb` points at an existing composed
  GLB and that `$BLENDER` is a valid binary.
- **`compose` reports missing assets** — the asset for a `model_uid` is absent from
  `data/asset_library/`; it is skipped (see the compose log).
- **Re-run a batch cheaply** — use `--resume` so completed stages are skipped.
- **`compose` reports many missing assets** — re-run the batch with `--auto-fill` (or
  run `python -m internscenes.download --auto`) to pull only the missing UIDs from
  HuggingFace.  The per-scene report is at `output/info/<ds>_<id>_missing.json`.

## License

MIT. Scene data is from the InternScenes project (see its license); individual
asset GLBs follow the licenses of their source datasets.
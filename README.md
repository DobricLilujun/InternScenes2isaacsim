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
        │  ┌───────────────────────────────┐
        │  │  glb_to_usd  →  *.usd          │   (geometry + transforms + base-color material)
        │  │  glb_render  →  perspective.png│   (Blender EEVEE, camera inside the room)
        │  └───────────────────────────────┘
        │  ┌──────────────────────────────────────────────┐
        │  │  topdown_projection → <scene>_topdown.png    │   (2D ground-plane projection)
        │  │  scene_info       → <scene>.json             │   (dimensions, objects, Go2 placement)
        │  └──────────────────────────────────────────────┘
```

## Features

- **GLB → USD** conversion via OpenUSD (`usd-exchange` / `pxr`), preserving per-instance
  world transforms and a base-colour material.
- **Blender headless rendering** (EEVEE) with a camera placed *inside* the room.
- **2D top-down projection** with a collision-aware Unitree **Go2** robot marker,
  nearest-obstacle clearance, and metre-scale grid.
- **Scene metadata export** (JSON): room dimensions (m), per-object category/position/
  size/rotation, category frequency, and the Go2 placement.
- **Batch orchestration** (`scripts/batch_pipeline.py`): sample *N* random scenes per
  category, run compose → render → top-down → info for each, resumable and logged.
- **Type annotations, logging, and exception handling** throughout the codebase.

## Project layout

```
InternScenes2isaacsim/
├── src/internscenes/
│   ├── compose.py          # SceneComposer: layout.json + asset library -> glb_scene.glb
│   ├── scene_info.py       # per-scene metadata extraction (JSON)
│   ├── sampler.py          # deterministic per-category random sampling
│   └── cli.py              # small CLI front-ends (render / topdown / info / batch)
├── scripts/
│   ├── glb_to_usd.py       # GLB -> USD (OpenUSD/pxr)
│   ├── glb_render.py       # GLB -> perspective PNG (Blender, run via `blender --python`)
│   ├── topdown_projection.py  # layout.json -> 2D top-down PNG
│   ├── place_go2.py        # collision-aware Go2 placement (shared by topdown)
│   ├── download_perobject.py  # download per-object GLBs for chosen scenes
│   ├── usd_all.sh / render_all.sh   # batch helpers for the 5 example scenes
│   └── batch_pipeline.py   # full batch pipeline (sample -> compose -> render -> topdown -> info)
├── data/
│   ├── Layout_info/        # per-scene layout.json (one folder per scene)
│   └── asset_library/      # per-object GLB assets (22k+)
├── output/                 # composed/ render/ topdown/ usd/ info/ batch/
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
    trimesh open3d numpy matplotlib huggingface-hub usd-exchange

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

### Single scene

```bash
# compose the GLB from layout.json + the asset library
.venv311/bin/python -c "import sys; sys.path.insert(0,'src/internscenes'); \
  import compose; compose.SceneComposer().compose_one_scene('scannet/scene0001_00')"

# GLB -> USD
.venv311/bin/python scripts/glb_to_usd.py \
  --glb output/composed/scannet/scene0001_00/glb_scene.glb \
  --out output/usd/scannet/scene0001_00/scene.usd

# GLB -> perspective PNG (Blender, headless)
$BLENDER --background --python scripts/glb_render.py -- \
  --glb output/composed/scannet/scene0001_00/glb_scene.glb \
  --out output/render/scannet/scene0001_00 --engine=EEVEE

# 2D top-down projection
.venv311/bin/python scripts/topdown_projection.py scannet/scene0001_00

# per-scene metadata (dimensions, objects, Go2 placement)
.venv311/bin/python -c "import sys; sys.path.insert(0,'src/internscenes'); \
  import scene_info; \
  scene_info.write_scene_info(\
    scene_info.build_scene_info('scannet/scene0001_00', \
      'data/Layout_info/scannet/scene0001_00/layout.json'), \
    'output/info/scannet_scene0001_00.json')"
```

### Batch (random sample per category)

Render **N** random scenes per category (compose → render → top-down → info),
writing artifacts into `output/`:

```bash
.venv311/bin/python scripts/batch_pipeline.py -n 50 --seed 0
# resume a previously interrupted run (skips stages whose output already exists)
.venv311/bin/python scripts/batch_pipeline.py -n 50 --seed 0 --resume
```

Outputs: `output/composed/…/glb_scene.glb`, `output/render/…/perspective.png`,
`output/topdown/…_topdown.png`, and `output/info/….json`; a run manifest is written
to `output/batch/manifest.json`.

### CLI front-ends

```bash
internscenes render scannet/scene0001_00 --engine EEVEE
internscenes topdown scannet/scene0001_00
internscenes info   scannet/scene0001_00 --out output/info/scannet_scene0001_00.json
internscenes batch  -n 50 --seed 0
```

### Notebook

`pipeline_commands_test.ipynb` walks the pipeline end to end, executing each stage
and verifying the output file. Render and export *every* sampled scene with
`scripts/batch_pipeline.py`.

## Configuration

| Setting | Where | Default | Purpose |
|---|---|---|---|
| `BLENDER` | env var | `/home/ubadmin/tools/blender/blender-5.1.2-linux-x64/blender` | Blender binary used by `glb_render.py` and `batch_pipeline.py` |
| `VENV_PY` | env var | `.venv311/bin/python` | Python interpreter for `batch_pipeline.py` |
| `INTERN_DATA_DIR` | env var | `<root>/data` | Root for `Layout_info/` and `asset_library/` |
| `INTERN_OUTPUT_DIR` | env var | `<root>/output` | Output root (`composed/`, `render/`, `usd/`, `info/`, …) |
| `-n` | `batch_pipeline.py` | `50` | Scenes sampled per category |
| `--seed` | `batch_pipeline.py` | `0` | RNG seed (reproducible sampling) |
| `--resume` | `batch_pipeline.py` | off | Skip stages whose output file already exists |
| `--engine` | `glb_render.py` | `auto` (EEVEE) | Render engine (`EEVEE` or `CYCLES`) |

Paths are resolved relative to the project root by default; override with the
environment variables above to point at an alternate data/output location.

## Outputs

| Path | Meaning |
|---|---|
| `output/composed/<scene>/glb_scene.glb` | composed scene GLB (shared input) |
| `output/usd/<scene>/scene.usd` | USD stage (geometry + transforms + material) |
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
      "valid": true }
  ]
}
```

## Troubleshooting

- **`MISSING` in the environment check** — install the missing dependency or set the
  relevant path (`BLENDER`, `VENV_PY`).
- **Blender render produces no PNG** — ensure `--glb` points at an existing composed
  GLB and that `$BLENDER` is a valid binary.
- **`compose` reports missing assets** — the asset for a `model_uid` is absent from
  `data/asset_library/`; it is skipped (see the compose log).
- **Re-run a batch cheaply** — use `--resume` so completed stages are skipped.

## License

MIT. Scene data is from the InternScenes project (see its license); individual
asset GLBs follow the licenses of their source datasets.
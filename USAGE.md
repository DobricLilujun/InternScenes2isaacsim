# InternScenes → Isaac Sim — Usage Guide

This guide explains how to use the **InternScenes2isaacsim** pipeline. It converts
InternScenes 3D indoor scenes (ScanNet / ARKitScenes / Matterport3D / 3RScan) into
**USD** assets for NVIDIA Isaac Sim / Omniverse, renders **perspective** (Blender/EEVEE)
and **2D top-down** views as visual proof, and exports **per-scene metadata**
(room dimensions, object list, collision-aware robot placement) as JSON.

The whole pipeline runs on a single machine — no remote server is required.

---

## 1. Pipeline overview

```
data/Layout_info/<scene>/layout.json
        │  compose (trimesh + asset_library)
        ▼
output/composed/<scene>/glb_scene.glb          ← composed scene GLB (shared input)
        │
        ├─ glb_to_usd      ──► output/usd/<scene>/scene.usd          (USD, geometry+transforms+material)
        │
        ├─ glb_render      ──► output/render/<scene>/perspective.png  (Blender EEVEE, camera in the room)
        │
        ├─ topdown_projection ─► output/topdown/<scene>_topdown.png  (2D ground-plane projection + Go2)
        │
        └─ scene_info      ──► output/info/<scene>.json              (dimensions, objects, Go2 placement)

normalize_output  ──► output/normalized/<dataset>_<id>/   (one self-contained folder per scene:
                   scene.usd + scene.json + perspective.png + topdown.png)
```

### Effective code (kept)

| Location | Role |
|---|---|
| `src/internscenes/compose.py` | `SceneComposer`: `layout.json` + asset library → `glb_scene.glb` |
| `src/internscenes/scene_info.py` | per-scene metadata extraction (dimensions, objects, Go2 placement) → JSON |
| `src/internscenes/sampler.py` | deterministic per-category random sampling |
| `src/internscenes/cli.py` | small CLI front-ends (`render` / `topdown` / `info` / `batch`) |
| `scripts/glb_to_usd.py` | **GLB → USD** (OpenUSD / `usd-exchange`). Content is authored under a `/World` root; up-axis left as `Y` (Y-up) so the Isaac Sim adapter can rotate to Z-up at load time. |
| `scripts/glb_render.py` | **GLB → perspective PNG** (Blender, run via `blender --python`) |
| `scripts/topdown_projection.py` | `layout.json` → 2D top-down PNG (imports `place_go2`) |
| `scripts/place_go2.py` | collision-aware Unitree **Go2** placement (shared by `topdown_projection`) |
| `scripts/normalize_output.py` | assemble one self-contained folder per scene (4 artefacts); converts the USD on the fly via `glb_to_usd.build_usd` |
| `scripts/download_perobject.py` | download per-object GLBs for chosen scenes |
| `scripts/batch_pipeline.py` | full batch orchestration (sample → compose → render → top-down → info), resumable |
| `scripts/usd_all.sh` / `render_all.sh` | batch helpers for the 5 example scenes |

---

## 2. Installation

Requires **Python ≥ 3.11** and **Blender ≥ 4.5** (developed with Python 3.11 and
Blender 5.1.2). [`uv`](https://docs.astral.sh/uv/) is recommended.

```bash
# 1. virtual environment
uv venv --python 3.11 .venv311
source .venv311/bin/activate            # or call .venv311/bin/python directly

# 2. dependencies
uv pip install --python .venv311/bin/python \
    trimesh open3d numpy matplotlib huggingface-hub usd-exchange

# 3. (optional) install the package itself so the `internscenes` CLI is available
pip install -e .
```

> **Blender** is *not* a Python dependency. Provide its path via the `BLENDER`
> environment variable (see [Configuration](#5-configuration)).

### Data

InternScenes data (`layout.json` files + per-object GLB `asset_library`) is downloaded
from the Hugging Face repo **`InternRobotics/InternScenes`** and placed under `data/`.

- `data/Layout_info/<scene>/layout.json` — one folder per scene
- `data/asset_library/` — per-object GLB assets

---

## 3. Usage

All commands below assume the **project root** is the working directory and the
`.venv311` virtual environment is active.

### 3.1 Compose a scene GLB

Build the composed GLB from `layout.json` + the asset library:

```bash
.venv311/bin/python -c "import sys; sys.path.insert(0,'src/internscenes'); \
  import compose; compose.SceneComposer().compose_one_scene('scannet/scene0001_00')"
# -> output/composed/scannet/scene0001_00/glb_scene.glb
```

### 3.2 GLB → USD

```bash
.venv311/bin/python scripts/glb_to_usd.py \
  --glb output/composed/scannet/scene0001_00/glb_scene.glb \
  --out output/usd/scannet/scene0001_00/scene.usd
# -> output/usd/scannet/scene0001_00/scene.usd
```

The USD is authored with all geometry under a `/World` root (e.g. `/World/Objects/…`)
and an **up-axis of `Y`** (the InternScenes/GLB convention). This keeps the conversion
faithful to the source; the Isaac Sim adapter rotates it to Z-up at load time, so there
is no double-rotation.

### 3.3 GLB → perspective PNG (Blender)

```bash
$BLENDER --background --python scripts/glb_render.py -- \
  --glb output/composed/scannet/scene0001_00/glb_scene.glb \
  --out output/render/scannet/scene0001_00 \
  --engine=EEVEE
# -> output/render/scannet/scene0001_00/perspective.png
```

`--engine` may be `EEVEE` (default) or `CYCLES`.

### 3.4 2D top-down projection

```bash
.venv311/bin/python scripts/topdown_projection.py scannet/scene0001_00
# -> output/topdown/scannet_scene0001_00_topdown.png
```

This uses a collision-aware **Go2** robot marker (via `place_go2.py`), nearest-obstacle
clearance, and a metre-scale grid.

### 3.5 Per-scene metadata (JSON)

```bash
.venv311/bin/python -c "import sys; sys.path.insert(0,'src/internscenes'); \
  import scene_info; \
  scene_info.write_scene_info( \
    scene_info.build_scene_info('scannet/scene0001_00', \
      'data/Layout_info/scannet/scene0001_00/layout.json'), \
    'output/info/scannet_scene0001_00.json')"
# -> output/info/scannet_scene0001_00.json
```

### 3.6 Normalized per-scene folder

Assemble **one self-contained folder per scene** (USD + scene.json + perspective.png +
topdown.png). This is the recommended entry point for a single scene:

```bash
# one scene (quick check)
.venv311/bin/python scripts/normalize_output.py --sample scannet/scene0001_00

# the 200-scene batch sample manifest
.venv311/bin/python scripts/normalize_output.py

# explicit scene list, one id per line
.venv311/bin/python scripts/normalize_output.py --list my_scenes.txt

# only the first N scenes
.venv311/bin/python scripts/normalize_output.py -n 5
```

Output layout:

```
output/normalized/<dataset>_<id>/
    scene.usd          # USD (geometry, NO Go2) — built by glb_to_usd on the fly if missing
    scene.json         # full scene info + computed Go2 placement
    perspective.png    # Blender perspective render
    topdown.png        # 2D top-down render
```

> **Important:** `normalize_output.py` will *copy* an existing USD if one is present
> (`output/usd/<scene>/scene.usd`). If you changed `glb_to_usd.py` and want the USD to
> reflect the change, **delete the stale USD first** so the script re-converts it via the
> current pipeline.

### 3.7 Batch (random sample per category)

Render **N** random scenes per category (compose → render → top-down → info), writing
artefacts into `output/`:

```bash
.venv311/bin/python scripts/batch_pipeline.py -n 50 --seed 0
# resume a previously interrupted run (skips stages whose output already exists)
.venv311/bin/python scripts/batch_pipeline.py -n 50 --seed 0 --resume
```

Other options:

```bash
--blender <path>      # Blender binary (default: $BLENDER or the bundled 5.1.2 path)
--venv-python <path>  # Python interpreter (default: $VENV_PY or .venv311/bin/python)
--datasets <csv>      # comma-separated datasets to include (default: all in sampler.DATASETS)
--manifest <path>     # run manifest path (default: output/batch/manifest.json)
--log <path>          # log path (default: output/batch/batch.log)
```

Outputs: `output/composed/…/glb_scene.glb`, `output/render/…/perspective.png`,
`output/topdown/…_topdown.png`, `output/info/….json`; a run manifest is written to
`output/batch/manifest.json`.

### 3.8 CLI front-ends

If you installed the package (`pip install -e .`), the `internscenes` command is
available:

```bash
internscenes render scannet/scene0001_00 --engine EEVEE
internscenes topdown scannet/scene0001_00
internscenes info   scannet/scene0001_00 --out output/info/scannet_scene0001_00.json
internscenes batch  -n 50 --seed 0
```

### 3.9 Batch helpers for the 5 example scenes

```bash
bash scripts/usd_all.sh      # convert the 5 composed GLBs to USD
bash scripts/render_all.sh   # render the 5 composed GLBs to perspective PNGs
```

---

## 4. Outputs

| Path | Meaning |
|---|---|
| `output/composed/<scene>/glb_scene.glb` | composed scene GLB (shared input) |
| `output/usd/<scene>/scene.usd` | USD stage (geometry + transforms + material), content under `/World` |
| `output/render/<scene>/perspective.png` | Blender perspective render |
| `output/topdown/<scene>_topdown.png` | 2D top-down projection |
| `output/info/<scene>.json` | per-scene metadata |
| `output/normalized/<dataset>_<id>/` | self-contained per-scene folder (from `normalize_output.py`) |
| `output/batch/manifest.json` | batch run status (per scene) |
| `output/scene_inventory.json` | full list of all scene IDs |

### Scene metadata format (`output/info/<scene>.json`)

```json
{
  "scene_id": "scannet/scene0001_00",
  "dataset": "scannet",
  "num_objects": 23,
  "num_valid_objects": 23,
  "room_dimensions_m": { "width": 7.4, "depth": 9.0, "height": 2.5, "min_x": -3.8, "max_x": 3.6 },
  "category_counts": { "chair": 5, "table": 2 },
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

---

## 5. Configuration

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

---

## 6. Troubleshooting

- **`MISSING` in the environment check** — install the missing dependency or set the
  relevant path (`BLENDER`, `VENV_PY`).
- **Blender render produces no PNG** — ensure `--glb` points at an existing composed
  GLB and that `$BLENDER` is a valid binary.
- **`compose` reports missing assets** — the asset for a `model_uid` is absent from
  `data/asset_library/`; it is skipped (see the compose log).
- **Re-run a batch cheaply** — use `--resume` so completed stages are skipped.
- **`normalize_output` keeps an old USD** — the script copies an existing USD instead of
  re-converting; delete `output/usd/<scene>/scene.usd` first to force a fresh conversion
  with the current `glb_to_usd.py`.
- **USD looks empty in Isaac Sim** — the scene USD must contain geometry under `/World`
  (or `/Objects`). `glb_to_usd.py` now authors everything under `/World` with an up-axis
  of `Y`; the Isaac Sim adapter rotates it to Z-up at load time.

## 7. License

MIT. Scene data is from the InternScenes project (see its license); individual asset
GLBs follow the licenses of their source datasets.
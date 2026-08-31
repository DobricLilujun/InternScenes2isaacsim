# InternScenes → Isaac Sim — Usage Guide

This guide explains how to use the **InternScenes2isaacsim** pipeline. It converts
InternScenes 3D indoor scenes (ScanNet / ARKitScenes / Matterport3D / 3RScan) into
**USD** assets for NVIDIA Isaac Sim / Omniverse, renders **perspective** (Blender/EEVEE)
and **2D top-down** views as visual proof, and exports **per-scene metadata**
(room dimensions, object list, collision-aware robot placement) as JSON.

The project is packaged as an **installable Python library** with a unified CLI:

```bash
pip install -e .
internscenes run -n 10 --seed 0 --auto-fill
internscenes run --scene scannet/scene0001_00
```

> **Note:** the old `scripts/` folder has been removed.  All reusable logic now
> lives in `src/internscenes/`.  Use the `internscenes` CLI or import from the
> `internscenes` package directly.

The whole pipeline runs on a single machine — no remote server is required.

---

## 1. Pipeline overview

```
data/Layout_info/<scene>/layout.json
        │  compose (trimesh + asset_library)
        ▼
output/composed/<scene>/glb_scene.glb          ← composed scene GLB (shared input)
        │
        ├─ glb_to_usd      ──► output/normalized/<ds>_<id>/scene.usd   (auto: Isaac Sim, else usd-exchange)
        │                     output/normalized/<ds>_<id>/textures/    (extracted PBR textures)
        │
        ├─ glb_render      ──► output/render/<scene>/perspective.png  (Blender EEVEE, camera in the room)
        │
        ├─ topdown_projection ─► output/topdown/<scene>_topdown.png  (2D top-plane projection + Go2)
        │
        └─ scene_info      ──► output/info/<scene>.json              (dimensions, objects, Go2 placement)

normalize_output  ──► output/normalized/<dataset>_<id>/   (one self-contained folder per scene:
                   scene.usd + textures/ + scene.json + perspective.png + topdown.png)
```

### Effective code (kept)

| Location | Role |
|---|---|
| `src/internscenes/compose.py` | `SceneComposer`: `layout.json` + asset library → `glb_scene.glb` |
| `src/internscenes/scene_info.py` | per-scene metadata extraction (dimensions, objects, Go2 placement) → JSON |
| `src/internscenes/sampler.py` | deterministic per-category random sampling |
| `src/internscenes/pipeline.py` | **Python API** wrapping compose/render/topdown/info/normalize |
| `src/internscenes/cli.py` | **unified CLI** (`run` / `render` / `topdown` / `info` / `batch`) |
| `src/internscenes/glb_to_usd.py` | **GLB → USD dispatcher** (auto backend, normalized output). Uses Isaac Sim's `omni.kit.asset_converter` (matches the official [InternScenes Real2Sim](https://github.com/InternRobotics/InternScenes) release) when `isaacsim` is importable; otherwise falls back to the `usd-exchange` path.  Default output lands in `output/normalized/<ds>_<id>/scene.usd`. |
| `src/internscenes/glb_to_usd_isaac.py` | **Primary backend** — Isaac Sim's `omni.kit.asset_converter` + the official `set_usd_prim_orientation` Z-up fix. Used by `glb_to_usd`; also importable directly. |
| `src/internscenes/glb_to_usd_fallback.py` | **Fallback backend** — `usd-exchange` / `pxr` GLB → USD (full PBR `UsdPreviewSurface` materials, exported textures, vertex normals, UV primvars, Isaac-Sim-correct stage metadata). |
| `src/internscenes/render.py` | **GLB → perspective PNG** (Blender, run via `internscenes render`) |
| `src/internscenes/_render_in_blender.py` | Blender bootstrap script: runs `internscenes.render` inside Blender's Python interpreter |
| `src/internscenes/topdown.py` | `layout.json` → 2D top-down PNG (imports `place_go2`) |
| `src/internscenes/place_go2.py` | collision-aware Unitree **Go2** placement (shared by `topdown`) |
| `src/internscenes/download.py` | download per-object GLBs for chosen scenes (`--auto` downloads only what's missing) |
| `src/internscenes/__init__.py` | public package API (lazy submodules so Blender's Python can load only `render`) |

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
    trimesh open3d numpy matplotlib huggingface-hub usd-exchange shapely

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

### 3.2 GLB → USD (auto backend, normalized output)

```bash
# Default: writes into the normalized per-scene folder.
.venv311/bin/python -c "from internscenes.glb_to_usd import build_usd; \
  build_usd('output/composed/scannet/scene0001_00/glb_scene.glb')"
# -> output/normalized/scannet_scene0001_00/scene.usd
#    output/normalized/scannet_scene0001_00/textures/*.png  (extracted PBR textures)

# Explicit output path (legacy `output/usd/<scene>/scene.usd` form is also supported).
.venv311/bin/python -c "from internscenes.glb_to_usd import build_usd; \
  build_usd('output/composed/scannet/scene0001_00/glb_scene.glb', 'path/to/scene.usd')"
```

`internscenes.glb_to_usd` is a thin **dispatcher**: it auto-picks the
highest-fidelity backend available and writes to the **normalized**
output layout by default.

* **Backend 1 — Isaac Sim** (`internscenes.glb_to_usd_isaac`, used when
  `isaacsim` is importable).  This is the same path the official
  InternScenes Real2Sim release takes
  (`InternScenes/InternScenes_Real2Sim/glb2usd.py` + the
  `set_usd_prim_orientation` Z-up fix in
  `real2sim_utils/usd_tools.py`).  The resulting USD contains the
  full `OmniPBR.mdl` material graph the InternScenes
  `trajectory_tools` renderer expects, with glTF PBR extensions
  (`KHR_materials_variants`, multi-UV, glTF mesh compression) all
  handled by Omniverse's asset converter.
* **Backend 2 — `usd-exchange` / `pxr`** (`internscenes.glb_to_usd_fallback`).
  Used when Isaac Sim is not installed.  Produces a real PBR USD
  (`UsdPreviewSurface` materials with `metallic` / `roughness` /
  `opacity`, exported texture PNGs, vertex normals, UVs, and
  `primvars:class` for instance segmentation).  Isaac-Sim-correct
  stage metadata (`Z` up, `metersPerUnit = 1`, `defaultPrim = /World`).

Override the backend with `--backend isaac` or `--backend usd-exchange`
if you need to force a specific path.

> The dispatcher is the same one used internally by
> `pipeline.assemble_normalized()` and `internscenes run`, so the
> USD never gets converted twice.

### 3.3 GLB → perspective PNG (Blender)

```bash
# using the CLI (recommended)
internscenes render scannet/scene0001_00 --engine EEVEE

# or run the Blender bootstrap directly
$BLENDER --background --python src/internscenes/_render_in_blender.py -- \
  --glb output/composed/scannet/scene0001_00/glb_scene.glb \
  --out output/render/scannet/scene0001_00 \
  --engine=EEVEE
# -> output/render/scannet/scene0001_00/perspective.png
```

`--engine` may be `EEVEE` (default) or `CYCLES`.

### 3.4 2D top-down projection

```bash
internscenes topdown scannet/scene0001_00
# -> output/topdown/scannet_scene0001_00_topdown.png
```

This uses a collision-aware **Go2** robot marker (via `internscenes.place_go2`), nearest-obstacle
clearance, and a metre-scale grid.

### 3.5 Per-scene metadata (JSON)

```bash
internscenes info scannet/scene0001_00
# -> output/info/scannet_scene0001_00.json
```

### 3.6 Navigation question generation (JSONL)

Generate up to 5 object-finding questions per scene for evaluating a navigation
robot.  Questions prefer medium-to-long distances from the Go2 start pose and
favour objects whose representative colour is known.

```bash
# one scene
internscenes questions --scene scannet/scene0001_00 -n 5 --seed 0
# -> output/normalized/scannet_scene0001_00/questions.jsonl
# -> output/questions/all.jsonl   (merged across all processed scenes)

# or use the standalone script
python scripts/generate_questions.py --scene scannet/scene0001_00 -n 5 --seed 0
```

Each line in the JSONL contains the English question, target category and
colour, target object metadata, the Go2 start position, and the straight-line
distance to the target.

### 3.7 Normalized per-scene folder

Assemble **one self-contained folder per scene** (USD + textures + scene.json + perspective.png +
topdown.png). This is the recommended entry point for a single scene:

```bash
# one scene (quick check)
internscenes run --scene scannet/scene0001_00

# from Python
.venv311/bin/python -c "from internscenes import pipeline; \
  pipeline.assemble_normalized('scannet/scene0001_00')"
```

Output layout:

```
output/normalized/<dataset>_<id>/
    scene.usd          # USD (geometry, NO Go2) — auto-built by glb_to_usd if missing
    textures/          # extracted PBR textures (next to the USD)
    scene.json         # full scene info + computed Go2 placement
    questions.jsonl    # generated object-finding navigation tasks (produced separately)
    perspective.png    # Blender perspective render
    topdown.png        # 2D top-down render
```

> **Important:** `assemble_normalized()` calls the same `glb_to_usd`
> dispatcher as the direct CLI.  If you change the converter backend
> or any converter option, **delete the stale USD** at
> `output/normalized/<ds>_<id>/scene.usd` first so the script
> re-converts it via the current pipeline.

### 3.8 Unified CLI (recommended)

After `pip install -e .`, the `internscenes` command is the recommended entry
point. It always produces the **normalized** per-scene folder as the final
output and supports both batch/random sampling and explicit scene IDs.

```bash
# batch: N random scenes per dataset
internscenes run -n 50 --seed 0

# batch with auto-fill (download only missing per-object GLBs)
internscenes run -n 10 --seed 0 --auto-fill

# specific scene
internscenes run --scene scannet/scene0001_00

# several specific scenes
internscenes run --scene scannet/scene0001_00 --scene scannet/scene0002_00

# limit random sampling to certain datasets
internscenes run -n 10 --datasets scannet --seed 0

# only keep larger rooms (smaller floor dimension >= 5 m)
internscenes run -n 10 --seed 0 --min-room-extent 5.0
```

Options:

| Option | Meaning |
|---|---|
| `-n N` | random sample: N scenes per dataset |
| `--seed S` | RNG seed for reproducible sampling |
| `--datasets A B` | only sample from these datasets |
| `--scene ID` | explicit scene id(s); repeatable; overrides random sampling |
| `--resume` | skip stages whose output file already exists |
| `--auto-fill` | pre-pass: collect missing UIDs, download only those, re-compose |
| `--auto-fill-once` | collect + download, but do not re-compose |
| `--skip-render` | skip Blender perspective render |
| `--skip-topdown` | skip 2D top-down projection |
| `--min-room-extent M` | skip rooms whose smaller floor dimension is < M metres |
| `--manifest PATH` | batch manifest (default: `output/batch/manifest.json`) |
| `--log PATH` | batch log (default: `output/batch/batch.log`) |

The final normalized folder is written to
`output/normalized/<dataset>_<id>/` and contains:

```
scene.usd          # USD (geometry, NO Go2) — auto-built by glb_to_usd
textures/          # extracted PBR textures (next to the USD)
scene.json         # full scene info + Go2 placement
questions.jsonl    # generated object-finding navigation tasks
perspective.png    # Blender perspective render
topdown.png        # 2D top-down render
```

Single-stage commands:

```bash
internscenes render scannet/scene0001_00 --engine EEVEE
internscenes topdown scannet/scene0001_00
internscenes info   scannet/scene0001_00 --out output/info/scannet_scene0001_00.json
internscenes questions --scene scannet/scene0001_00 -n 5 --seed 0
internscenes batch  -n 50 --seed 0
```

### 3.9 Batch (random sample per category)

```bash
internscenes run -n 50 --seed 0
# resume a previously interrupted run (skips stages whose output already exists)
internscenes run -n 50 --seed 0 --resume
# **auto-fill missing assets** — pre-compose every scene once, collect the
# missing UIDs into output/info/*_missing.json, download *only* those, then
# re-compose for real.  Avoids downloading the whole 22k-asset library.
internscenes run -n 50 --seed 0 --auto-fill
```

Other options:

```bash
--datasets <list>     # space-separated datasets to include (default: all in sampler.DATASETS)
--manifest <path>     # run manifest path (default: output/batch/manifest.json)
--log <path>          # log path (default: output/batch/batch.log)
--auto-fill           # pre-pass: download only the per-object GLBs that are
                      # actually missing for the chosen scenes (recommended
                      # when the asset library is incomplete).
--auto-fill-once      # same as --auto-fill but skip the post-download
                      # re-compose; inspect the assets first.
```

### Auto-fill on demand

You can also run the auto-filler directly without the rest of the batch pipeline:

```bash
# 1. Compose a scene once (writes output/info/<ds>_<id>_missing.json).
.venv311/bin/python -c "from internscenes import compose; \
  compose.SceneComposer().compose_one_scene('scannet/scene0001_00', \
  verbose_missing=False)"

# 2. Download only the UIDs that are not already on disk.
.venv311/bin/python -m internscenes.download --auto --scene scannet/scene0001_00

# 3. Re-compose (now 0 missing assets).
.venv311/bin/python -c "from internscenes import compose; \
  compose.SceneComposer().compose_one_scene('scannet/scene0001_00', \
  verbose_missing=False)"

# Dry-run: print what would be downloaded without actually downloading.
.venv311/bin/python -m internscenes.download --auto --scene scannet/scene0001_00 --dry-run
```

Outputs: `output/composed/…/glb_scene.glb`, `output/render/…/perspective.png`,
`output/topdown/…_topdown.png`, `output/info/….json`; a run manifest is written to
`output/batch/manifest.json`.

### 3.10 Batch helpers for the 5 example scenes

```bash
# example shell loop over the 5 composed example scenes
for scene in scannet/scene0001_00 scannet/scene0002_00 arkitscenes/Training_47895301 \
             matterport3d/VFuaQ6m2Qom_region28 3rscan/0cac75ab-8d6f-2d13-8fea-b1eb7e9bf6e7; do
    internscenes run --scene "$scene"
done
```

---

## 4. Outputs

| Path | Meaning |
|---|---|
| `output/composed/<scene>/glb_scene.glb` | composed scene GLB (shared input) |
| `output/normalized/<dataset>_<id>/scene.usd` | USD stage (auto backend: Isaac Sim if available, else usd-exchange) |
| `output/normalized/<dataset>_<id>/textures/` | extracted PBR textures (next to the USD) |
| `output/render/<scene>/perspective.png` | Blender perspective render |
| `output/topdown/<scene>_topdown.png` | 2D top-down projection |
| `output/info/<scene>.json` | per-scene metadata |
| `output/normalized/<dataset>_<id>/` | self-contained per-scene folder (from `pipeline.assemble_normalized()`) |
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
      "color": { "r": 0.31, "g": 0.24, "b": 0.19, "source": "baseColorTexture" },
      "valid": true }
  ]
}
```

---

## 5. Configuration

| Setting | Where | Default | Purpose |
|---|---|---|---|
| `BLENDER` | env var | `/home/ubadmin/tools/blender/blender-5.1.2-linux-x64/blender` | Blender binary used by `internscenes render` |
| `INTERN_DATA_DIR` | env var | `<root>/data` | Root for `Layout_info/` and `asset_library/` |
| `INTERN_OUTPUT_DIR` | env var | `<root>/output` | Output root (`composed/`, `render/`, `usd/`, `info/`, …) |
| `-n` | `internscenes run` / `batch` | `50` | Scenes sampled per category |
| `--seed` | `internscenes run` / `batch` | `0` | RNG seed (reproducible sampling) |
| `--resume` | `internscenes run` / `batch` | off | Skip stages whose output file already exists |
| `--engine` | `internscenes render` | `EEVEE` | Render engine (`EEVEE` or `CYCLES`) |

Paths are resolved relative to the project root by default; override with the
environment variables above to point at an alternate data/output location.

---

## 6. Troubleshooting

- **`MISSING` in the environment check** — install the missing dependency or set the
  relevant path (`BLENDER`, `INTERN_DATA_DIR`, `INTERN_OUTPUT_DIR`).
- **Blender render produces no PNG** — ensure the composed GLB exists and that
  `$BLENDER` is a valid binary.
- **`compose` reports missing assets** — the asset for a `model_uid` is absent from
  `data/asset_library/`; it is skipped (see the compose log).  Re-run the
  batch with `--auto-fill` (or run `python -m internscenes.download --auto`) to
  download only the missing UIDs from HuggingFace.  The full per-scene
  missing-assets report lives at `output/info/<ds>_<id>_missing.json`.
- **Re-run a batch cheaply** — use `--resume` so completed stages are skipped.
- **`assemble_normalized` keeps an old USD** — the function reuses an existing USD in
  `output/normalized/<ds>_<id>/scene.usd` if present.  Delete that file to force
  a fresh conversion with the current `internscenes.glb_to_usd` backend.
- **USD looks empty in Isaac Sim** — the dispatcher writes everything under
  `/World` (the stage default prim) and applies the official InternScenes
  Z-up fix, so the stage is ready to load directly.  Open the USD with
  `/World` as the default prim and `Z` as the up-axis.

## 7. License

MIT. Scene data is from the InternScenes project (see its license); individual asset
GLBs follow the licenses of their source datasets.
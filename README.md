# InternScenes -> USD (Isaac Sim asset format) pipeline

Convert InternScenes 3D scenes to USD and render perspective views proving the
materials render correctly.  Built on this machine (no remote server).

## Pipeline

```
Layout_info/*.json  ──compose──►  *.glb  ──USD──►  *.usd      (geometry+transforms+material)
                              └──render──►  perspective.png    (visual proof, EEVEE)
```

## Layout

- `src/internscenes/compose.py`     — SceneComposer (ported from InternScenes, paths configurable)
- `scripts/download_perobject.py`   — download per-object GLBs for chosen scenes
- `scripts/glb_render.py`           — GLB -> perspective PNG via Blender (EEVEE, camera inside room)
- `scripts/glb_to_usd.py`           — GLB -> USD via OpenUSD (usd-exchange / pxr)
- `scripts/render_all.sh`           — render all 5 scenes
- `scripts/usd_all.sh`              — convert all 5 scenes to USD

## 5 scenes (one per dataset, diverse types)

| scene | dataset | type | objects |
|---|---|---|---|
| scene0000_00 | ScanNet | open-plan living/bedroom/kitchen | 117 |
| scene0001_00 | ScanNet | living room | 23 |
| 095821fb-... | 3RScan | residential lounge / home office | 9 |
| Training/43896449 | ARKitScenes | office / waiting area | 21 |
| B6ByNegPMKs/region51 | Matterport3D | office / workspace | 57 |

## Environment

- Python 3.11 venv `.venv311` (trimesh, open3d, huggingface_hub, usd-exchange)
- Blender 5.1.2 (renders) + 4.5.1 (reference) at `~/tools/blender/`
- USD via OpenUSD (`usd-exchange` / `pxr`), OpenUSD 26.x API

## Run

```bash
uv venv --python 3.11 .venv311
uv pip install --python .venv311/bin/python trimesh open3d huggingface_hub usd-exchange
# download data (see README for HF repo InternRobotics/InternScenes)
python -c "import sys;sys.path.insert(0,'src/internscenes');import compose;compose.SceneComposer().compose_one_scene('scannet/scene0001_00')"
blender --background --python scripts/glb_render.py -- --glb=output/composed/scannet/scene0001_00/glb_scene.glb --out=output/render/scannet/scene0001_00
python scripts/glb_to_usd.py --glb=output/composed/scannet/scene0001_00/glb_scene.glb --out=output/usd/scannet/scene0001_00/scene.usd
```
#!/usr/bin/env bash
# Place Go2 in a scene + render (combined: compute placement, export env, render in Blender).
set -e
PROJ=/home/ubadmin/projects/InternScenes2isaacsim
BLENDER=/home/ubadmin/tools/blender/blender-5.1.2-linux-x64/blender
scene_id="$1"

# 1) compute placement (stdlib only)
python3 - "$PROJ" "$scene_id" <<'PY'
import sys, os
sys.path.insert(0, sys.argv[1] + "/scripts")
import place_go2 as pg
proj, scene_id = sys.argv[1], sys.argv[2]
layout = f"{proj}/data/Layout_info/{scene_id}/layout.json"
cand = pg.best_placement(pg.load_layout(layout))
if not cand:
    print("no placement"); sys.exit(1)
nearest, px, py = cand[0]
print(f"placement ({px:.3f},{py:.3f}) clearance={nearest:.2f}m valid={len(cand)}")
os.environ["GO2X"] = f"{px:.4f}"
os.environ["GO2Y"] = f"{py:.4f}"
os.environ["SCENE_ID"] = scene_id
# re-exec blender with env in same shell
PY

# 2) render in Blender with the computed env
# re-run placement to get env into this shell
eval "$(python3 - "$PROJ" "$scene_id" <<'PY'
import sys, os
sys.path.insert(0, sys.argv[1] + "/scripts")
import place_go2 as pg
proj, scene_id = sys.argv[1], sys.argv[2]
cand = pg.best_placement(pg.load_layout(f"{proj}/data/Layout_info/{scene_id}/layout.json"))
if not cand: sys.exit(1)
nearest, px, py = cand[0]
print(f'export GO2X={px:.4f}')
print(f'export GO2Y={py:.4f}')
print(f'export SCENE_ID={scene_id}')
print(f'export GO2_CLEARANCE={nearest:.2f}')
print(f'export GO2_VALID={len(cand)}')
PY
)"

echo "GO2X=$GO2X GO2Y=$GO2Y SCENE_ID=$SCENE_ID"
timeout 300 "$BLENDER" --background --python "$PROJ/scripts/go2_render.py" 2>&1 | tail -6
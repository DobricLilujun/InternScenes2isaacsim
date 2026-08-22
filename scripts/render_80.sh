#!/usr/bin/env bash
# Render all 80 composed scenes to perspective PNGs (numbered 01-20 per category).
set -e
PROJ=/home/ubadmin/projects/InternScenes2isaacsim
BLENDER=/home/ubadmin/tools/blender/blender-5.1.2-linux-x64/blender
cd "$PROJ"

# render a given composed glb -> numbered png
render() {
  local glb="$1" out="$2"
  if [ ! -f "$glb" ]; then
    echo "  SKIP (no glb) $out"; return 0
  fi
  timeout 300 "$BLENDER" --background --python scripts/glb_render.py -- \
    --glb "$glb" --out "$out" --engine=EEVEE 2>&1 | tail -3
}

# category -> base composed dir
for d in scannet 3rscan arkitscenes matterport3d; do
  echo "===== $d ====="
  python3 -c "
import json
c=json.load(open('scripts/chosen_80.json'))
for s in c['$d']: print(s.split('/')[-1])
" 2>/dev/null || true
done

echo "render script prepared"
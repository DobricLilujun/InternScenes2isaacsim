#!/usr/bin/env bash
# Render all 5 composed scenes to perspective PNGs via Blender (EEVEE).
set -e
PROJ=/home/ubadmin/projects/InternScenes2isaacsim
BLENDER=/home/ubadmin/tools/blender/blender-5.1.2-linux-x64/blender
cd "$PROJ"

declare -a SCENES=(
  "scannet/scene0001_00"
  "3rscan/095821fb-e2c2-2de1-94df-20f2cb423bcb"
  "arkitscenes/Training/43896449"
  "matterport3d/B6ByNegPMKs/region51"
  "scannet/scene0000_00"
)

for scene in "${SCENES[@]}"; do
  glb="output/composed/$scene/glb_scene.glb"
  out="output/render/$scene"
  echo "=== rendering $scene ==="
  timeout 300 "$BLENDER" --background --python scripts/glb_render.py -- \
    --glb="$glb" --out="$out" --engine=EEVEE 2>&1 | grep -E "render saved|rendering|DONE|Error" || true
  if [ -f "$out/perspective.png" ]; then
    echo "OK: $out/perspective.png ($(du -h "$out/perspective.png" | cut -f1))"
  else
    echo "MISSING: $out/perspective.png"
  fi
done
echo "ALL_RENDER_DONE"
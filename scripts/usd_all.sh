#!/usr/bin/env bash
# Convert all 5 composed GLB scenes to USD via OpenUSD (usd-exchange / pxr).
set -e
PROJ=/home/ubadmin/projects/InternScenes2isaacsim
cd "$PROJ"

declare -a SCENES=(
  "3rscan/095821fb-e2c2-2de1-94df-20f2cb423bcb"
  "arkitscenes/Training/43896449"
  "scannet/scene0001_00"
  "scannet/scene0000_00"
  "matterport3d/B6ByNegPMKs/region51"
)

for scene in "${SCENES[@]}"; do
  glb="output/composed/$scene/glb_scene.glb"
  usd="output/usd/$scene/scene.usd"
  echo "=== USD $scene ==="
  .venv311/bin/python scripts/glb_to_usd.py --glb="$glb" --out="$usd" 2>&1 | tail -2 || echo "FAIL $scene"
done
echo "ALL_USD_DONE"
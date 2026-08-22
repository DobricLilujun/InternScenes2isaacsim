#!/usr/bin/env bash
# Re-render all already-placed Go2 scenes with the improved renderer (walls hidden, bright).
set -e
PROJ=/home/ubadmin/projects/InternScenes2isaacsim
cd "$PROJ"
# gather all scenes that have a layout + are composed
for layout in data/Layout_info/*/*/layout.json; do
  scene=$(echo "$layout" | sed -E 's#data/Layout_info/##; s#/layout.json##')
  # skip the original 5 already in chosen_80 set? no — just re-render any that have a go2 render
  if [ -f "output/go2_placed/${scene//\//_}_go2.png" ]; then
    echo "=== re-render $scene ==="
    bash scripts/place_and_render.sh "$scene" 2>&1 | tail -1
  fi
done
echo "RERENDER_ALL_DONE"
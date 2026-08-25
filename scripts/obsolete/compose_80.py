import sys, time, json
sys.path.insert(0, "/home/ubadmin/projects/InternScenes2isaacsim/src/internscenes")
import compose
from pathlib import Path

PROJ = Path("/home/ubadmin/projects/InternScenes2isaacsim")
LAYOUT = PROJ / "data" / "Layout_info"
chosen = json.loads((PROJ / "scripts" / "chosen_80.json").read_text())
composer = compose.SceneComposer()

results = []
t0 = time.time()
for d, scenes in chosen.items():
    for i, scene_abs in enumerate(scenes):
        # scene name relative to LAYOUT_DIR, e.g. scannet/scene0325_00
        rel = str(Path(scene_abs).resolve().relative_to(LAYOUT))
        try:
            glb, missing = composer.compose_one_scene(rel)
            sz = Path(glb).stat().st_size / 1e9
            results.append((rel, "OK", sz, len(missing)))
            print(f"[{d} {i+1:02d}] OK {rel} size={sz:.2f}GB missing={len(missing)}", flush=True)
        except Exception as e:
            results.append((rel, "ERR", 0, str(e)))
            print(f"[{d} {i+1:02d}] ERR {rel}: {e}", flush=True)

print(f"\nDONE in {time.time()-t0:.0f}s")
ok = sum(1 for r in results if r[1] == "OK")
print(f"composed {ok}/{len(results)}")
Path(PROJ / "scripts" / "compose_results.json").write_text(json.dumps(results, indent=2))
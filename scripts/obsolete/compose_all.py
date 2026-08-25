import sys, time
sys.path.insert(0, "/home/ubadmin/projects/InternScenes2isaacsim/src/internscenes")
import compose

SCENES = [
    "3rscan/095821fb-e2c2-2de1-94df-20f2cb423bcb",
    "arkitscenes/Training/43896449",
    "scannet/scene0001_00",
    "matterport3d/B6ByNegPMKs/region51",
    "scannet/scene0000_00",
]

for scene in SCENES:
    t0 = time.time()
    try:
        glb, missing = compose.SceneComposer().compose_one_scene(scene)
        import os
        sz = os.path.getsize(glb) / 1e9
        print(f"COMPOSE_OK {scene} size={sz:.2f}GB missing={len(missing)} elapsed={time.time()-t0:.0f}s")
    except Exception as e:
        import traceback
        print(f"COMPOSE_FAIL {scene}: {type(e).__name__}: {e}")
        traceback.print_exc()
print("ALL_COMPOSE_DONE")
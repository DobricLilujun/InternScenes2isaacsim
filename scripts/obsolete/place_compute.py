import sys, os
sys.path.insert(0, "/home/ubadmin/projects/InternScenes2isaacsim/scripts")
import place_go2 as pg

scene_id = sys.argv[1]              # e.g. scannet/scene0001_00
layout = f"/home/ubadmin/projects/InternScenes2isaacsim/data/Layout_info/{scene_id}/layout.json"
cand = pg.best_placement(pg.load_layout(layout))
if not cand:
    print("no placement"); sys.exit(1)
nearest, px, py = cand[0]
print(f"placement ({px:.3f},{py:.3f}) clearance={nearest:.2f}m valid={len(cand)}")
os.environ["GO2X"] = f"{px:.4f}"
os.environ["GO2Y"] = f"{py:.4f}"
os.environ["SCENE_ID"] = scene_id
os.environ["GO2_CLEARANCE"] = f"{nearest:.2f}"
os.environ["GO2_VALID"] = str(len(cand))
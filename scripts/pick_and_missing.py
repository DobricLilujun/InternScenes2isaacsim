import os, json, random
from pathlib import Path

PROJ = "/home/ubadmin/projects/InternScenes2isaacsim"
base = Path(PROJ) / "data" / "Layout_info"
al = Path(PROJ) / "data" / "asset_library"
random.seed(1234)

def get_scenes(dataset):
    p = base / dataset
    scenes = []
    for root, dirs, files in os.walk(p):
        if "layout.json" in files:
            scenes.append(root)
    return scenes

datasets = ["scannet", "3rscan", "arkitscenes", "matterport3d"]
chosen = {}
for d in datasets:
    s = get_scenes(d)
    random.shuffle(s)
    chosen[d] = s[:20]

need = set()
for d, scenes in chosen.items():
    for scene_path in scenes:
        p = Path(scene_path) / "layout.json"
        if not p.exists():
            continue
        for o in json.loads(p.read_text()):
            u = o.get("model_uid", "")
            if not u:
                continue
            lib = u.split("/")[0]
            if lib in ("partnet_mobility", "objaverse", "objaverse_old"):
                continue
            need.add(u)

already = sum(1 for u in need if (al / (u + ".glb")).exists())
missing = [u for u in need if not (al / (u + ".glb")).exists()]
print("total per-object uids needed across 80 scenes:", len(need))
print("already on disk:", already)
print("missing (need download):", len(missing))
print("sample missing:", missing[:5])

with open(Path(PROJ) / "scripts" / "chosen_80.json", "w") as f:
    json.dump({d: [str(s) for s in v] for d, v in chosen.items()}, f)
print("saved chosen_80.json")
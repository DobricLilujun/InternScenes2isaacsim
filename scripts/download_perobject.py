import time, json
from pathlib import Path
from huggingface_hub import snapshot_download

scenes = [
    "scannet/scene0000_00",
    "3rscan/095821fb-e2c2-2de1-94df-20f2cb423bcb",
    "arkitscenes/Training/43896449",
    "matterport3d/B6ByNegPMKs/region51",
    "scannet/scene0001_00",
]
base = Path("data/Layout_info")
all_uids = set()
for scene in scenes:
    p = base / scene / "layout.json"
    if not p.exists():
        print(f"WARN: no layout for {scene}")
        continue
    for o in json.loads(p.read_text()):
        u = o.get("model_uid", "")
        if not u:
            continue
        lib = u.split("/")[0]
        if lib not in ("partnet_mobility", "objaverse", "objaverse_old"):
            all_uids.add(u)

patterns = [f"asset_library/{u}.glb" for u in all_uids]
print(f"downloading {len(patterns)} per-object GLBs...")
t0 = time.time()
snapshot_download("InternRobotics/InternScenes", repo_type="dataset",
                  allow_patterns=patterns, local_dir="data")
print(f"PER-OBJECT GLBs DONE in {time.time() - t0:.0f}s")
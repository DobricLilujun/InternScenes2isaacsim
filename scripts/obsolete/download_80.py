import time, json
from pathlib import Path
from huggingface_hub import snapshot_download

PROJ = Path("/home/ubadmin/projects/InternScenes2isaacsim")
chosen = json.loads((PROJ / "scripts" / "chosen_80.json").read_text())
al = PROJ / "data" / "asset_library"
base = PROJ / "data" / "Layout_info"

need = set()
for d, scenes in chosen.items():
    for scene in scenes:
        p = Path(scene) / "layout.json"
        if not p.exists():
            continue
        for o in json.loads(p.read_text()):
            u = o.get("model_uid", "")
            if not u:
                continue
            lib = u.split("/")[0]
            if lib in ("partnet_mobility", "objaverse", "objaverse_old"):
                continue
            if not (al / (u + ".glb")).exists():
                need.add(u)

patterns = [f"asset_library/{u}.glb" for u in need]
print(f"downloading {len(patterns)} missing per-object GLBs...")
t0 = time.time()
snapshot_download("InternRobotics/InternScenes", repo_type="dataset",
                  allow_patterns=patterns, local_dir=str(PROJ / "data"))
print(f"PER-OBJECT GLBs DONE in {time.time()-t0:.0f}s")
# verify
still = [u for u in need if not (al / (u + ".glb")).exists()]
print("still missing after download:", len(still), still[:3])
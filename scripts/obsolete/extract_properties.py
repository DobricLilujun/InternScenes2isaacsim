import json, os
from pathlib import Path
import numpy as np

PROJ = Path("/home/ubadmin/projects/InternScenes2isaacsim")
LAYOUT = PROJ / "data" / "Layout_info"
chosen = json.loads((PROJ / "scripts" / "chosen_80.json").read_text())

# --- Task 1: extract per-object properties from layout + GLB color ---
def extract_color(glb_path, n_obj):
    """Return a dict mapping (mesh order) -> mean RGB color (0-255)."""
    try:
        import trimesh
        scene = trimesh.load(glb_path)
    except Exception as e:
        return {}
    colors = {}
    try:
        geoms = list(scene.geometry.values())
    except Exception:
        geoms = []
    # try to read material base color
    for i, g in enumerate(geoms):
        col = None
        try:
            mat = getattr(g, "visual", None)
            if mat is not None and getattr(mat, "material", None) is not None:
                m = mat.material
                c = getattr(m, "base_color", None)
                if c is not None:
                    col = [int(x) for x in c[:3]]
        except Exception:
            pass
        if col is None:
            col = [128, 128, 128]
        colors[i] = col
    return colors

rows = []
for d, scenes in chosen.items():
    for i, scene_abs in enumerate(scenes, start=1):
        rel = str(Path(scene_abs).resolve().relative_to(LAYOUT))
        layout_p = Path(scene_abs) / "layout.json"
        if not layout_p.exists():
            continue
        layout = json.loads(layout_p.read_text())
        for o in layout:
            bbox = o.get("bbox", [])
            x, y, z = bbox[0], bbox[1], bbox[2]
            dx, dy, dz = bbox[3], bbox[4], bbox[5]
            rx, ry, rz = bbox[6], bbox[7], bbox[8]
            rows.append({
                "dataset": d, "scene": rel, "id": o.get("id"),
                "category": o.get("category"), "model_uid": o.get("model_uid", ""),
                "source": o.get("model_uid", "").split("/")[0],
                "x": round(x, 3), "y": round(y, 3), "z": round(z, 3),
                "dx": round(dx, 3), "dy": round(dy, 3), "dz": round(dz, 3),
                "rot_x": round(rx, 2), "rot_y": round(ry, 2), "rot_z": round(rz, 2),
            })

# write CSV
import csv
csv_p = PROJ / "output" / "object_properties.csv"
csv_p.parent.mkdir(parents=True, exist_ok=True)
with open(csv_p, "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=["dataset","scene","id","category","model_uid","source","x","y","z","dx","dy","dz","rot_x","rot_y","rot_z"])
    w.writeheader()
    for r in rows:
        w.writerow(r)
print(f"Extracted {len(rows)} object rows -> {csv_p}")

# category distribution
from collections import Counter
print("\n=== category counts (top 20) ===")
for c, n in Counter(r["category"] for r in rows).most_common(20):
    print(f"  {c}: {n}")
print("\n=== source (asset library) counts ===")
for c, n in Counter(r["source"] for r in rows).most_common(10):
    print(f"  {c}: {n}")
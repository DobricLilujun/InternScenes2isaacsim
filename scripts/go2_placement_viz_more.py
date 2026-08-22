import json, sys
sys.path.insert(0, "/home/ubadmin/projects/InternScenes2isaacsim/scripts")
import place_go2 as pg
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle, Circle
from pathlib import Path

PROJ = Path("/home/ubadmin/projects/InternScenes2isaacsim")
picks = json.loads((PROJ / "scripts" / "chosen_more20.json").read_text())
out = PROJ / "output/go2_placed"

for scene in picks:
    layout = PROJ / "data/Layout_info" / scene / "layout.json"
    if not layout.exists():
        print("skip (no layout):", scene); continue
    objs = pg.load_layout(str(layout))
    obs = pg.obstacle_circles(objs)
    cand = pg.best_placement(objs)
    if not cand:
        print("no placement:", scene); continue
    nearest, px, py = cand[0]
    # draw
    fig, ax = plt.subplots(figsize=(7, 7))
    for o in objs:
        b = o.get("bbox")
        if b is None:
            continue
        cx, cy, dx, dy = b[0], b[1], b[3], b[4]
        ax.add_patch(Rectangle((cx - dx / 2, cy - dy / 2), dx, dy,
                               fill=True, color="#888", alpha=0.5,
                               ec="#555", lw=0.4))
    # Go2 footprint
    ax.add_patch(Circle((px, py), pg.GO2_R, color="red", alpha=0.9))
    # clearance ring
    ax.add_patch(Circle((px, py), pg.GO2_R + nearest, fill=False,
                        color="red", ls="--", lw=1.2))
    ax.set_title(f"{scene}  —  Go2 placement\n"
                 f"valid spots: {len(cand)}  |  clearance: {nearest:.2f}m",
                 fontsize=10)
    xs = [b[0] for o in objs if o.get("bbox") for b in [o["bbox"]]]
    ys = [b[1] for o in objs if o.get("bbox") for b in [o["bbox"]]]
    ax.set_xlim(min(xs) - 0.5, max(xs) + 0.5)
    ax.set_ylim(min(ys) - 0.5, max(ys) + 0.5)
    ax.set_aspect("equal"); ax.grid(True, alpha=0.2)
    fp = out / (scene.replace("/", "_") + "_placement.png")
    plt.savefig(fp, dpi=110, bbox_inches="tight")
    plt.close()
    print("placement diagram:", scene, f"({px:.2f},{py:.2f}) clr={nearest:.2f}")
print("DONE")
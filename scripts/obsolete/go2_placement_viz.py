"""Top-down placement diagram: clearly shows the collision-aware Go2 placement.
For each scene: draw all objects (grey), the chosen Go2 spot (red), the
clearance circle (dashed), and the nearest object. Much clearer than a 3D
render for demonstrating the placement algorithm.
"""
import sys, json, math
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mp

sys.path.insert(0, "/home/ubadmin/projects/InternScenes2isaacsim/scripts")
import place_go2 as pg

PROJ = Path("/home/ubadmin/projects/InternScenes2isaacsim")
scenes = [
    ("ScanNet", "scannet/scene0001_00"),
    ("ScanNet", "scannet/scene0000_00"),
    ("3RScan", "3rscan/095821fb-e2c2-2de1-94df-20f2cb423bcb"),
    ("ARKitScenes", "arkitscenes/Training/43896449"),
    ("Matterport3D", "matterport3d/B6ByNegPMKs/region51"),
]
GO2_R = pg.GO2_R

for label, sid in scenes:
    layout = PROJ / "data" / "Layout_info" / sid / "layout.json"
    objs = pg.load_layout(layout)
    obs = pg.obstacle_circles(objs)
    cand = pg.best_placement(objs)
    if not cand:
        continue
    nearest, px, py = cand[0]
    fig, ax = plt.subplots(figsize=(9, 8))
    ax.set_aspect("equal")
    # objects (grey boxes, oriented)
    for o in objs:
        b = o.get("bbox")
        if b is None:
            continue
        cx, cy, dx, dy = b[0], b[1], b[3], b[4]
        ax.add_patch(mp.Rectangle((cx - dx/2, cy - dy/2), dx, dy,
                     facecolor="lightgray", edgecolor="gray", alpha=0.5))
    # clearance circle
    ax.add_patch(mp.Circle((px, py), nearest, fill=False,
                 edgecolor="red", lw=1.5, ls="--"))
    # Go2 footprint
    ax.add_patch(mp.Circle((px, py), GO2_R, color="red", alpha=0.9, zorder=5))
    ax.add_patch(mp.Rectangle((px - GO2_R, py - GO2_R*0.6),
                 GO2_R*2, GO2_R*1.2, color="red", alpha=0.9, zorder=6))
    # label
    ax.annotate(f"Go2  ({px:.1f},{py:.1f})\nclearance {nearest:.2f}m",
                (px, py), xytext=(px + 0.4, py + 0.4),
                color="red", fontsize=9, fontweight="bold")
    ax.set_title(f"{label} {sid}  —  Go2 placement\n"
                 f"valid spots: {len(cand)}  |  best clearance: {nearest:.2f}m",
                 fontsize=11)
    # explicit axis limits covering the whole room
    bx0, bx1, by0, by1 = pg.room_bounds(objs)
    pad = 0.5
    ax.set_xlim(bx0 - pad, bx1 + pad)
    ax.set_ylim(by0 - pad, by1 + pad)
    ax.set_xlabel("X (m)"); ax.set_ylabel("Y (m)")
    ax.grid(True, alpha=0.3)
    out = PROJ / "output" / "go2_placed" / f"{sid.replace('/','_')}_placement.png"
    fig.savefig(out, dpi=130)
    plt.close(fig)
    print(f"{label} {sid}: placed at ({px:.2f},{py:.2f}) "
          f"clearance={nearest:.2f}m -> {out.name}")
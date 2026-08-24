#!/usr/bin/env python3
"""3D -> 2D top-down projection of an InternScenes scene with a live Go2 marker.

For each scene we project the 3D world onto the XY (top-down) plane:
  - every object's 3D bounding box -> its rotated rectangle footprint (XY)
  - the Go2 is placed by the collision-aware algorithm (scripts/place_go2.py)
  - the Go2 is drawn as a marker with a heading + a live position trace

This is the "3D to 2D projection" view the user asked for, alongside the
Isaac ego (A) and third-person (B) renders.
"""
import os, json, math, argparse
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle, FancyArrow
from matplotlib.transforms import Affine2D
import sys

sys.path.insert(0, os.path.dirname(__file__))
import place_go2 as pg

# Go2 heading (yaw, radians) for a few scenes (arbitrary but plausible)
GO2_YAW = {"default": -math.pi / 2}


def footprint_rect(b):
    """Return (cx, cy, w, h, yaw) for the XY footprint of a 3D bbox.
    b = [cx, cy, cz, dx, dy, dz, rot_x, rot_y, rot_z]; dx,dy are full extents."""
    if isinstance(b, dict):
        b = [b.get("cx", 0), b.get("cy", 0), b.get("cz", 0),
             b.get("dx", 0), b.get("dy", 0), b.get("dz", 0),
             b.get("rot_x", 0), b.get("rot_y", 0), b.get("rot_z", 0)]
    cx, cy, dx, dy = b[0], b[1], b[3], b[4]
    return cx, cy, dx, dy, b[8]


def draw_scene(scene_name, layout_path, out_path, go2_trace=None, go2_yaw=-math.pi/2):
    objs = json.load(open(layout_path))
    objs = [o for o in objs if o.get("bbox")]
    obs = pg.obstacle_circles(objs)

    cand = pg.best_placement(objs)
    if not cand:
        print(f"{scene_name}: no valid placement, skipping")
        return None

    # best placement = largest clearance
    clearance, gx, gy = cand[0]

    # room bounds
    bx0, bx1, by0, by1 = pg.room_bounds(objs)
    pad = 0.6
    bx0, bx1, by0, by1 = bx0 - pad, bx1 + pad, by0 - pad, by1 + pad

    fig, ax = plt.subplots(figsize=(7, 7))
    ax.set_xlim(bx0, bx1)
    ax.set_ylim(by0, by1)
    ax.set_aspect("equal")

    # obstacle footprints (rotated rectangles)
    for o in objs:
        b = o.get("bbox")
        if b is None:
            continue
        cx, cy, w, h, yaw = footprint_rect(b)
        # rotate the rectangle by yaw about its center
        t = Affine2D().translate(cx, cy).rotate(yaw).translate(-cx, -cy)
        rect = Rectangle((cx - w / 2, cy - h / 2), w, h,
                         transform=ax.transData,
                         facecolor="#d94f4f", edgecolor="#a03030",
                         alpha=0.35, lw=0.6)
        # apply rotation
        import matplotlib.transforms as mt
        rect.set_transform(t + ax.transData)
        ax.add_patch(rect)

    # Go2 live position trace (optional: previous positions as faint dots)
    if go2_trace:
        for (px, py) in go2_trace:
            ax.plot(px, py, "o", color="#2a7f2a", alpha=0.35, markersize=4)

    # Go2 marker (circle + heading arrow)
    ax.add_patch(plt.Circle((gx, gy), pg.GO2_R, color="#1f6fb2",
                  alpha=0.85, zorder=5, label="Go2"))
    ax.annotate("", xy=(gx + 0.35 * math.cos(go2_yaw), gy + 0.35 * math.sin(go2_yaw)),
                xytext=(gx, gy),
                arrowprops=dict(arrowstyle="->", color="#0d3b6b", lw=2.5),
                zorder=6)
    ax.plot(gx, gy, "+", color="white", markersize=10, markeredgewidth=2, zorder=7)

    # title + legend
    ax.set_title(f"{scene_name}  —  3D→2D top-down projection\n"
                 f"Go2 @ ({gx:.2f}, {gy:.2f})  clearance={clearance:.2f}m  "
                 f"obstacles={len(objs)}", fontsize=11)
    ax.grid(True, alpha=0.25)
    ax.set_xlabel("X (m)")
    ax.set_ylabel("Y (m)")
    # legend
    ax.plot([], [], "o", color="#1f6fb2", label="Go2 (live)")
    ax.add_patch(Rectangle((0, 0), 1, 1, facecolor="#d94f4f", alpha=0.35,
                  edgecolor="#a03030", label="obstacle footprint"))
    ax.legend(loc="upper left", fontsize=8, framealpha=0.9)
    plt.tight_layout()
    plt.savefig(out_path, dpi=120)
    plt.close()
    return (gx, gy, clearance)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("scene", help="scene name (e.g. scannet/scene0100_01)")
    ap.add_argument("--layout", help="layout.json path")
    ap.add_argument("--out", help="output png")
    ap.add_argument("--yaw", type=float, default=-math.pi / 2, help="Go2 heading (rad)")
    args = ap.parse_args()

    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(here)
    layout = args.layout or os.path.join(root, "data", "Layout_info",
                                         args.scene, "layout.json")
    if not os.path.exists(layout):
        print("no layout.json at", layout)
        sys.exit(1)
    out = args.out or os.path.join(root, "output", "topdown",
                                   args.scene.replace("/", "_") + "_topdown.png")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    res = draw_scene(args.scene, layout, out, go2_yaw=args.yaw)
    if res:
        print(f"{args.scene}: Go2=({res[0]:.2f},{res[1]:.2f}) clearance={res[2]:.2f}m -> {out}")


if __name__ == "__main__":
    main()
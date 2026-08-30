"""3D -> 2D top-down projection of an InternScenes scene with a live Go2 marker.

For each scene we project the 3D world onto the XY (top-down) plane:
  - every object's 3D bounding box -> its rotated rectangle footprint (XY)
  - the Go2 is placed by the collision-aware algorithm (:mod:`place_go2`)
  - the Go2 is drawn as a marker with a heading + a live position trace
  - the room's wall footprint (XY hull of ``StructureMesh/wall.glb``) is
    drawn as a translucent fill so the user can see the walkable region
    and not just the layout-derived bounding box.

Public entry point: :func:`draw_scene`.
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import os
from pathlib import Path

import numpy as np

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle, Polygon
from matplotlib.transforms import Affine2D

from . import place_go2 as pg

logger = logging.getLogger(__name__)

GO2_YAW = {"default": -math.pi / 2}


def _footprint_rect(b):
    """Return (cx, cy, w, h, yaw) for the XY footprint of a 3D bbox.
    b = [cx, cy, cz, dx, dy, dz, rot_x, rot_y, rot_z]; dx,dy are full extents."""
    if isinstance(b, dict):
        b = [b.get("cx", 0), b.get("cy", 0), b.get("cz", 0),
             b.get("dx", 0), b.get("dy", 0), b.get("dz", 0),
             b.get("rot_x", 0), b.get("rot_y", 0), b.get("rot_z", 0)]
    cx, cy, dx, dy = b[0], b[1], b[3], b[4]
    return cx, cy, dx, dy, b[8]


def draw_scene(scene_name: str, layout_path: str, out_path: str,
               go2_trace: list | None = None, go2_yaw: float = -math.pi / 2) -> tuple | None:
    """Render the top-down projection of a scene to ``out_path``.

    Returns the (gx, gy, clearance) of the Go2 placement, or ``None`` if the
    scene could not be drawn. When no collision-free placement exists the scene
    is still drawn (obstacle footprints + grid) with a "no valid placement"
    note so the caller always gets an image.
    """
    with open(layout_path, encoding="utf-8") as fh:
        objs = json.load(fh)
    objs = [o for o in objs if o.get("bbox")]
    obs = pg.obstacle_circles(objs)

    polygon = pg.interior_polygon(layout_path)
    cand = pg.best_placement(objs, polygon=polygon)
    if cand:
        # best placement = largest clearance
        clearance, gx, gy = cand[0]
    else:
        # no collision-free placement: still draw the scene, mark it clearly
        logger.warning("%s: no valid placement, drawing without Go2 marker", scene_name)
        clearance, gx, gy = 0.0, 0.0, 0.0

    # room bounds (use polygon extents when available so the figure is tight)
    if polygon is not None and len(polygon) >= 3:
        bx0, bx1 = float(polygon[:, 0].min()), float(polygon[:, 0].max())
        by0, by1 = float(polygon[:, 1].min()), float(polygon[:, 1].max())
    else:
        bx0, bx1, by0, by1 = pg.room_bounds(objs)
    pad = 0.6
    bx0, bx1, by0, by1 = bx0 - pad, bx1 + pad, by0 - pad, by1 + pad

    fig, ax = plt.subplots(figsize=(7, 7))
    ax.set_xlim(bx0, bx1)
    ax.set_ylim(by0, by1)
    ax.set_aspect("equal")

    # walkable interior polygon (XY hull of wall.glb) as a translucent fill
    if polygon is not None and len(polygon) >= 3:
        ax.add_patch(Polygon(polygon, closed=True, facecolor="#7fbf7f",
                             edgecolor="#2a7f2a", alpha=0.18, lw=1.2,
                             label="walkable interior"))

    # Go2 live position trace (optional: previous positions as faint dots)
    if go2_trace:
        for (px, py) in go2_trace:
            ax.plot(px, py, "o", color="#2a7f2a", alpha=0.35, markersize=4)

    # obstacle footprints (rotated rectangles)
    for o in objs:
        b = o.get("bbox")
        if b is None:
            continue
        cx, cy, w, h, yaw = _footprint_rect(b)
        t = Affine2D().translate(cx, cy).rotate(yaw).translate(-cx, -cy)
        rect = Rectangle((cx - w / 2, cy - h / 2), w, h,
                         facecolor="#d94f4f", edgecolor="#a03030",
                         alpha=0.35, lw=0.6)
        rect.set_transform(t + ax.transData)
        ax.add_patch(rect)

    # Go2 live position trace (optional: previous positions as faint dots)
    if go2_trace:
        for (px, py) in go2_trace:
            ax.plot(px, py, "o", color="#2a7f2a", alpha=0.35, markersize=4)

    # Go2 marker (circle + heading arrow) — only when a valid placement exists
    if cand:
        ax.add_patch(plt.Circle((gx, gy), pg.GO2_R, color="#1f6fb2",
                      alpha=0.85, zorder=5, label="Go2"))
        ax.annotate("", xy=(gx + 0.35 * math.cos(go2_yaw), gy + 0.35 * math.sin(go2_yaw)),
                    xytext=(gx, gy),
                    arrowprops=dict(arrowstyle="->", color="#0d3b6b", lw=2.5),
                    zorder=6)
        ax.plot(gx, gy, "+", color="white", markersize=10, markeredgewidth=2, zorder=7)

    # title + legend
    if cand:
        sub = (f"Go2 @ ({gx:.2f}, {gy:.2f})  clearance={clearance:.2f}m  "
               f"obstacles={len(objs)}")
    else:
        sub = f"no valid Go2 placement  obstacles={len(objs)}"
    ax.set_title(f"{scene_name}  —  3D\u21922D top-down projection\n{sub}", fontsize=11)
    ax.grid(True, alpha=0.25)
    ax.set_xlabel("X (m)")
    ax.set_ylabel("Y (m)")
    # legend
    if cand:
        ax.plot([], [], "o", color="#1f6fb2", label="Go2 (live)")
    ax.add_patch(Rectangle((0, 0), 1, 1, facecolor="#d94f4f", alpha=0.35,
                  edgecolor="#a03030", label="obstacle footprint"))
    ax.legend(loc="upper left", fontsize=8, framealpha=0.9)
    plt.tight_layout()
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    plt.savefig(out_path, dpi=120)
    plt.close()
    return (gx, gy, clearance)


def main() -> int:
    ap = argparse.ArgumentParser(description="Render a top-down projection")
    ap.add_argument("scene", help="scene name (e.g. scannet/scene0100_01)")
    ap.add_argument("--layout", help="layout.json path")
    ap.add_argument("--out", help="output png")
    ap.add_argument("--yaw", type=float, default=-math.pi / 2, help="Go2 heading (rad)")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    here = Path(__file__).resolve().parent
    root = here.parents[1]
    layout = args.layout or str(root / "data" / "Layout_info" /
                                args.scene / "layout.json")
    if not os.path.exists(layout):
        logger.error("no layout.json at %s", layout)
        return 1
    out = args.out or str(root / "output" / "topdown" /
                          args.scene.replace("/", "_") + "_topdown.png")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    try:
        res = draw_scene(args.scene, layout, out, go2_yaw=args.yaw)
    except Exception as exc:
        logger.error("topdown failed for %s: %s", args.scene, exc)
        return 1
    if res:
        gx, gy, clr = res
        print(f"{args.scene}: Go2=({gx:.2f},{gy:.2f}) clearance={clr:.2f}m -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

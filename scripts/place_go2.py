"""
Placement algorithm for a Unitree Go2 robot in an InternScenes scene.

Goal: find a floor location where the Go2 can stand without colliding with any
object and with enough clearance from walls.

Input : layout.json of a scene -> list of {id, category, model_uid, bbox}
        bbox = [cx, cy, cz, dx, dy, dz, rot_x, rot_y, rot_z]  (meters)

Method (collision-aware, floor-level):
  1. Room XY extent from all objects (centers +/- half-extents).
  2. Each object -> circle of radius max(dx,dy)/2 (+ clearance margin).
  3. Go2 -> circle of radius ~0.25 m (0.46 x 0.30 bbox).
  4. Grid-sample candidate points INSIDE the room footprint.
  5. Keep candidates whose Go2-circle does not intersect any obstacle circle.
  6. Score by clearance (distance to nearest obstacle).
  7. Return best candidate + nearest-obstacle distance + a few alternates.

Go2 dims (meters): 0.46 x 0.30 x 0.30.
"""

import json, math
from pathlib import Path


CLEARANCE_MARGIN = 0.12  # extra clearance beyond object bbox (m)
GO2_R = 0.25            # Go2 footprint radius (m) ~ half of 0.50 diag


def load_layout(p):
    with open(p) as f:
        return json.load(f)


def room_bounds(objs):
    xs, ys = [], []
    for o in objs:
        b = o.get("bbox")
        if b is None:
            continue
        cx, cy, dx, dy = b[0], b[1], b[3], b[4]
        xs += [cx - dx / 2, cx + dx / 2]
        ys += [cy - dy / 2, cy + dy / 2]
    if not xs:
        return (-1, 1, -1, 1)
    return (min(xs), max(xs), min(ys), max(ys))


def obstacle_circles(objs, margin=CLEARANCE_MARGIN):
    out = []
    for o in objs:
        b = o.get("bbox")
        if b is None:
            continue
        cx, cy, dx, dy = b[0], b[1], b[3], b[4]
        r = max(dx, dy) / 2 + margin
        out.append((cx, cy, r, o.get("category")))
    return out


def collides(cx, cy, obs):
    for (ox, oy, r, _) in obs:
        if math.hypot(cx - ox, cy - oy) < GO2_R + r:
            return True
    return False


def nearest_clearance(cx, cy, obs):
    return min((math.hypot(cx - ox, cy - oy) - r for (ox, oy, r, _) in obs),
               default=999.0)


def best_placement(objs, n_grid=80, margin=CLEARANCE_MARGIN):
    obs = obstacle_circles(objs, margin=margin)
    bx0, bx1, by0, by1 = room_bounds(objs)
    cand = []
    for i in range(n_grid + 1):
        for j in range(n_grid + 1):
            cx = bx0 + (bx1 - bx0) * i / n_grid
            cy = by0 + (by1 - by0) * j / n_grid
            if not (bx0 <= cx <= bx1 and by0 <= cy <= by1):
                continue
            if collides(cx, cy, obs):
                continue
            nearest = nearest_clearance(cx, cy, obs)
            cand.append((nearest, cx, cy))
    cand.sort(key=lambda t: t[0], reverse=True)
    return cand


def place_go2(layout_path, top_n=5):
    objs = load_layout(layout_path)
    cand = best_placement(objs)
    print(f"scene: {layout_path}")
    print(f"objects: {len(objs)}, valid candidates: {len(cand)}")
    for nearest, cx, cy in cand[:top_n]:
        print(f"  pos=({cx:6.2f},{cy:6.2f})  clearance_to_nearest={nearest:5.2f}m")
    return cand


if __name__ == "__main__":
    import sys
    p = sys.argv[1] if len(sys.argv) > 1 else \
        "/home/ubadmin/projects/InternScenes2isaacsim/data/Layout_info/scannet/scene0000_00/layout.json"
    place_go2(p)
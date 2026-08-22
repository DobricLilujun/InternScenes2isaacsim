"""Build a recognizable Unitree Go2 robot-dog model (GLB).
Cleaner proportions, clearly splayed 4 legs, body, head. Units: meters.
Bright red body so it is unmistakable in-scene. Feet reach z=0.
"""
import os
import numpy as np
import trimesh

# ---- dimensions (meters) ----
BODY_L, BODY_W, BODY_H = 0.44, 0.30, 0.22
LEG_CS = 0.08
HEAD_L, HEAD_W, HEAD_H = 0.16, 0.22, 0.14
FOOT_X, FOOT_Y = 0.30, 0.26     # feet splayed well beyond the body
BODY_TOP = 0.52                  # top of the body (legs drop from here)
BODY_Z = BODY_TOP - BODY_H / 2

# leg tops (hip) a bit below the body; legs drop to the floor
HIP_Z = BODY_Z - BODY_H / 2 + 0.02


def col(r, g, b):
    return [r, g, b, 255]


def box(length, width, height, center, color):
    m = trimesh.creation.box((length, width, height))
    m.apply_translation(center)
    m.visual.face_colors = np.tile(np.array(color, dtype=np.uint8),
                                   (len(m.faces), 1))
    return m


parts = []
# body (bright red)
parts.append(box(BODY_L, BODY_W, BODY_H, (0, 0, BODY_Z), col(220, 30, 30)))
# head (front, +x) - dark
hx = BODY_L / 2 + HEAD_L / 2
parts.append(box(HEAD_L, HEAD_W, HEAD_H, (hx, 0, BODY_Z + 0.02), col(40, 40, 45)))
# two camera eyes (white)
for dy in (+0.05, -0.05):
    parts.append(box(0.02, 0.03, 0.03,
                     (hx + HEAD_L / 2, dy, BODY_Z + 0.04), col(245, 245, 245)))

# 4 legs: from hip down to the floor, at splayed foot positions
for sx in (+1, -1):        # front(+x) / back(-x)
    for sy in (+1, -1):    # left(+y) / right(-y)
        fx, fy = sx * FOOT_X, sy * FOOT_Y
        leg_h = HIP_Z       # height from floor (0) to hip
        # thigh (upper, thicker)
        parts.append(box(LEG_CS*1.3, LEG_CS*1.3, leg_h*0.55,
                         (fx*0.85, fy*0.85, leg_h*0.72), col(110, 110, 115)))
        # shin (lower, thinner)
        parts.append(box(LEG_CS, LEG_CS, leg_h*0.5,
                         (fx*1.0, fy*1.0, leg_h*0.25), col(110, 110, 115)))
        # foot pad
        parts.append(box(0.10, 0.07, 0.03, (fx, fy, 0.015), col(25, 25, 25)))

scene = trimesh.util.concatenate(parts)
out = "/home/ubadmin/projects/InternScenes2isaacsim/assets/go2_built.glb"
scene.export(out, file_type="glb")
print("exported:", out, "size:", os.path.getsize(out), "parts:", len(parts))
print("bounds:", np.round(scene.bounds[0],2), "->", np.round(scene.bounds[1],2))
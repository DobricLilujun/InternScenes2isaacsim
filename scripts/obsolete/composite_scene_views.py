#!/usr/bin/env python3
"""Composite 'one scene, multiple views' for scene0004_00:
  (1) 2D top-down projection  (verified, our matplotlib render)
  (2) Isaac 3D ego render      (real Isaac frame from the preview pipeline)
Labels honestly which is which, and flags that Isaac 3D top-down/perspective
failed to render in this build.
"""
import os
from PIL import Image, ImageDraw, ImageFont

BASE = "/home/ubadmin/projects/InternScenes2isaacsim/output"
OUT = os.path.join(BASE, "scene0004_00_views.png")

topdown = os.path.join(BASE, "topdown", "scannet_scene0004_00_topdown.png")
ego = "/tmp/ego_frame.png"   # real Isaac frame (ego/head camera)


def fit(img, size):
    img = img.copy()
    img.thumbnail(size)
    return img


def pad(img, size, color=(20, 22, 30)):
    c = Image.new("RGB", size, color)
    c.paste(img, ((size[0] - img.width) // 2, (size[1] - img.height) // 2))
    return c


def label(img, text, size, color=(255, 255, 255)):
    c = Image.new("RGB", size, (0, 0, 0))
    d = ImageDraw.Draw(c)
    try:
        f = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 20)
    except Exception:
        f = ImageFont.load_default()
    d.text((12, 8), text, fill=color, font=f)
    return c


tw, th = 600, 600
t = pad(fit(Image.open(topdown), (tw - 30, th - 50)), (tw, th))
c = Image.new("RGB", (tw, th), (20, 22, 30))
c.paste(label(c, "2D top-down (matplotlib)", (tw, 36)), (0, 0))
c.paste(t, (0, 36))
c = c.crop((0, 36, tw, 36 + th - 36)) if False else c  # keep as is

# build panels
panel_top = Image.new("RGB", (tw, th + 36), (20, 22, 30))
panel_top.paste(label(panel_top, "(1) 2D top-down  —  matplotlib (verified)", (tw, 36)), (0, 0))
panel_top.paste(pad(fit(Image.open(topdown), (tw - 20, th - 20)), (tw, th)), (0, 36))
panel_top = panel_top.crop((0, 0, tw, th))

panel_ego = Image.new("RGB", (tw, th + 36), (20, 22, 30))
panel_ego.paste(label(panel_ego, "(2) Isaac 3D — ego / head camera (real render)", (tw, 36)), (0, 0))
panel_ego.paste(pad(fit(Image.open(ego), (tw - 20, th - 20)), (tw, th)), (0, 36))
panel_ego = panel_ego.crop((0, 0, tw, th))

# 3rd panel: honest note that Isaac 3D top-down / perspective failed
note = Image.new("RGB", (tw, th + 36), (20, 22, 30))
d = ImageDraw.Draw(note)
try:
    f = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 18)
    f2 = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 14)
except Exception:
    f = f2 = ImageFont.load_default()
d.text((12, 8), "(3) Isaac 3D — top-down / perspective", fill=(255, 255, 255), font=f)
msg = ("BLOCKED in this Isaac build:\n"
       "custom camera get_rgba() returns\n"
       "empty frames (5 approaches tried).\n"
       "\n"
       "Only the livestream ego camera\n"
       "renders. 3D top-down / perspective\n"
       "need a different Isaac machine\n"
       "or the GUI viewport screenshot.")
y = 52
for line in msg.split("\n"):
    d.text((12, y), line, fill=(230, 200, 120), font=f2)
    y += 20

# compose: 3 columns
W = tw * 3 + 24
H = th + 36 + 30
canvas = Image.new("RGB", (W, H), (10, 11, 16))
canvas.paste(panel_top, (12, 24))
canvas.paste(panel_ego, (12 + tw + 12, 24))
canvas.paste(note, (12 + (tw + 12) * 2, 24))

# title
dd = ImageDraw.Draw(canvas)
try:
    tf = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 22)
except Exception:
    tf = ImageFont.load_default()
dd.text((12, 2), "scene0004_00 — one scene, multiple views", fill=(255, 255, 255), font=tf)

canvas.save(OUT)
print("saved", OUT, canvas.size)
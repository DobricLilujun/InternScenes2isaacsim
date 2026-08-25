#!/usr/bin/env python3
"""Build a larger, diverse montage of the available 2D top-downs."""
import os
from PIL import Image, ImageDraw, ImageFont

BASE = "/home/ubadmin/projects/InternScenes2isaacsim"
TD = os.path.join(BASE, "output", "topdown")
files = sorted(f for f in os.listdir(TD) if f.endswith(".png"))
n = len(files)
step = n // 64
samp = files[::step][:64]
print(f"available={n}, sampled={len(samp)}")

try:
    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 11)
except Exception:
    font = ImageFont.load_default()

cols, rows = 8, 8
tw, th = 300, 300
label_h = 18
canvas_w = cols * tw
canvas_h = rows * (th + label_h)
canvas = Image.new("RGB", (canvas_w, canvas_h), (25, 25, 30))
d = ImageDraw.Draw(canvas)

for i, f in enumerate(samp):
    im = Image.open(os.path.join(TD, f))
    im = im.convert("RGB").resize((tw, th))
    r, c = divmod(i, cols)
    x, y = c * tw, r * (th + label_h)
    canvas.paste(im, (x, y + label_h))
    name = f.replace("_topdown.png", "")
    d.text((x + 4, y + 3), name, fill=(230, 230, 230), font=font)

out = os.path.join(BASE, "output", "topdown_montage_large.png")
canvas.save(out)
print("saved", out, canvas.size)
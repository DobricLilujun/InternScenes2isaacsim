#!/usr/bin/env python3
"""Build a montage of N 2D top-down projections (the verified working view)."""
import os
from PIL import Image, ImageDraw, ImageFont

BASE = "/home/ubadmin/projects/InternScenes2isaacsim"
OUT = os.path.join(BASE, "output", "topdown_montage_batch.png")

files = sorted(
    os.path.join(BASE, "output/topdown", f) for f in os.listdir(os.path.join(BASE, "output/topdown"))
    if f.endswith(".png")
)
# pick a diverse sample (every ~8th) up to 24
step = max(1, len(files) // 24)
sel = files[::step][:24]
print("montage from", len(sel), "of", len(files), "topdowns")

cols, rows = 4, 6
cell = 300
pad = 6
canvas_w = cols * (cell + pad) + pad
canvas_h = rows * (cell + pad) + pad + 26
canvas = Image.new("RGB", (canvas_w, canvas_h), (12, 13, 18))
d = ImageDraw.Draw(canvas)
try:
    tf = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 18)
    lf = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 11)
except Exception:
    tf = lf = ImageFont.load_default()
d.text((10, 4), "2D top-down projections  (Go2 marker + obstacle footprints)  —  sample of %d scenes" % len(sel),
       fill=(255, 255, 255), font=tf)
for i, f in enumerate(sel):
    r, c = divmod(i, cols)
    try:
        im = Image.open(f).convert("RGB")
        im.thumbnail((cell - 8, cell - 8))
        x = c * (cell + pad) + pad
        y = r * (cell + pad) + pad + 26
        canvas.paste(im, (x + (cell - 8 - im.width) // 2, y + (cell - 8 - im.height) // 2))
        name = os.path.basename(f).replace("_topdown.png", "")
        d.text((x + 2, y - 1), name[:30], fill=(160, 180, 210), font=lf)
    except Exception:
        pass
canvas.save(OUT)
print("SAVED", OUT, os.path.getsize(OUT))
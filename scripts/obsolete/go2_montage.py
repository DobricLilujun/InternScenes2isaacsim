import json
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

PROJ = Path("/home/ubadmin/projects/InternScenes2isaacsim")
picks = json.loads((PROJ / "scripts" / "chosen_more20.json").read_text())
out = PROJ / "output/go2_placed"

CELL = 512
COLS = 5
ROWS = (len(picks) + COLS - 1) // COLS
gap = 6
img = Image.new("RGB", (COLS * CELL + (COLS + 1) * gap,
                        ROWS * CELL + (ROWS + 1) * gap), (22, 22, 26))
d = ImageDraw.Draw(img)
try:
    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 26)
except Exception:
    font = ImageFont.load_default()

def loadp(scene):
    for ext in ("_go2.png", "_placement.png"):
        p = out / (scene.replace("/", "_") + ext)
        if p.exists():
            return p
    return None

for i, scene in enumerate(picks):
    r, c = divmod(i, COLS)
    x = c * CELL + (c + 1) * gap
    y = r * CELL + (r + 1) * gap
    p = loadp(scene)
    if p:
        im = Image.open(p).convert("RGB").resize((CELL, CELL))
        img.paste(im, (x, y))
    d.text((x + 6, y + 6), f"{i+1:02d}", fill=(255, 255, 60), font=font)
    d.text((x + 6, y + CELL - 34), scene.replace("/", "_")[:30],
           fill=(255, 255, 255), font=font)

mont = out / "go2_more20_montage.png"
img.save(mont)
print("montage:", mont, img.size, "cells:", len(picks))
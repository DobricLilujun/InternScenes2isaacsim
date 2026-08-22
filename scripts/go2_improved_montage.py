import glob
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

out = Path("/home/ubadmin/projects/InternScenes2isaacsim/output/go2_placed")
renders = sorted(glob.glob(str(out / "*_go2.png")))
picks = renders[::2][:20]
CELL = 512
COLS = 5
ROWS = (len(picks) + COLS - 1) // COLS
gap = 6
img = Image.new("RGB", (COLS * CELL + (COLS + 1) * gap,
                        ROWS * CELL + (ROWS + 1) * gap), (22, 22, 26))
d = ImageDraw.Draw(img)
try:
    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 22)
except Exception:
    font = ImageFont.load_default()
for i, p in enumerate(picks):
    r, c = divmod(i, COLS)
    x = c * CELL + (c + 1) * gap
    y = r * CELL + (r + 1) * gap
    im = Image.open(p).convert("RGB").resize((CELL, CELL))
    img.paste(im, (x, y))
    d.text((x + 6, y + 6), f"{i+1:02d}", fill=(255, 255, 60), font=font)
mont = out / "go2_improved_montage.png"
img.save(mont)
print("montage cells:", len(picks), img.size)
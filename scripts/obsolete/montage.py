import json
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

PROJ = Path("/home/ubadmin/projects/InternScenes2isaacsim")
chosen = json.loads((PROJ / "scripts" / "chosen_80.json").read_text())
RENDER = PROJ / "output" / "render_80"
OUT = PROJ / "output" / "montage"
OUT.mkdir(parents=True, exist_ok=True)

LABEL = {"scannet": "ScanNet", "3rscan": "3RScan",
         "arkitscenes": "ARKitScenes", "matterport3d": "Matterport3D"}
COLS, ROWS = 5, 4          # 20 images
THUMB = 384                # thumb width
CELLH = int(THUMB * 9 / 16)
PAD = 10
NUM = 22                   # number label height
TITLE = 46

try:
    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 26)
    tfont = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 30)
except Exception:
    font = ImageFont.load_default()
    tfont = font

def draw_number(im, num, name):
    # number band at bottom
    w, h = im.size
    band = Image.new("RGB", (w, NUM), (20, 20, 28))
    d = ImageDraw.Draw(band)
    d.text((10, (NUM - 22) // 2 - 2), f"#{num}  {name}", fill=(255, 255, 255), font=font)
    # draw label text
    return Image.new("RGB", im.size, (20, 20, 28)), band

for d, scenes in chosen.items():
    cells = []
    for i, scene_abs in enumerate(scenes, start=1):
        p = RENDER / f"{LABEL[d]}_{i:02d}.png"
        if not p.exists():
            cells.append(None)
            continue
        im = Image.open(p).convert("RGB")
        im = im.resize((THUMB, CELLH), 1)  # LANCZOS (1)
        # number band
        band = Image.new("RGB", (THUMB, NUM), (15, 15, 22))
        bd = ImageDraw.Draw(band)
        sd = Path(scene_abs).name
        bd.text((8, (NUM - 22) // 2 - 1), f"#{i:02d}  {sd}", fill=(255, 255, 255), font=font)
        cell = Image.new("RGB", (THUMB, CELLH + NUM), (15, 15, 22))
        cell.paste(im, (0, 0))
        cell.paste(band, (0, CELLH))
        cells.append(cell)

    # grid
    gw = COLS * (THUMB + PAD) + PAD
    gh = ROWS * (CELLH + NUM + PAD) + PAD + TITLE
    sheet = Image.new("RGB", (gw, gh), (25, 25, 34))
    sd = ImageDraw.Draw(sheet)
    title = f"{LABEL[d]}  —  20 random scenes (showing diversity)"
    sd.text((PAD, 12), title, fill=(255, 255, 255), font=tfont)
    y0 = TITLE
    for i, cell in enumerate(cells):
        r = i // COLS
        c = i % COLS
        x = PAD + c * (THUMB + PAD)
        y = y0 + r * (CELLH + NUM + PAD)
        if cell is None:
            ph = Image.new("RGB", (THUMB, CELLH + NUM), (45, 45, 60))
            pd = ImageDraw.Draw(ph)
            pd.text((10, CELLH + 2), f"#{i+1:02d} (missing)", fill=(180, 180, 200), font=font)
            sheet.paste(ph, (x, y))
        else:
            sheet.paste(cell, (x, y))
    outp = OUT / f"{LABEL[d]}_montage.png"
    sheet.save(outp)
    print(f"{LABEL[d]} montage: {outp} ({sheet.size[0]}x{sheet.size[1]}), {sum(1 for c in cells if c)}/20 cells")

print("MONTAGE DONE")
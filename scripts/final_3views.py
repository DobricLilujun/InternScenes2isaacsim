#!/usr/bin/env python3
"""FINAL 'one scene, 3 views' composite for scene0004_00 — uses ONLY what
genuinely renders on this build. Honest labeling.
  (1) 2D top-down  — matplotlib (verified, best for understanding the scene)
  (2) Isaac 3D     — the ego/head camera (the only Isaac camera that renders
                     real content in this Isaac 6.0.1 headless build)
  (3) note         — honest note that Isaac 3D top-down/perspective is blocked
                     on this headless build (render product renders blank),
                     with the exact fix for another machine.
"""
import os
from PIL import Image, ImageDraw, ImageFont

BASE = "/home/ubadmin/projects/InternScenes2isaacsim/output"
OUT = os.path.join(BASE, "scene0004_00_3views.png")

topdown = os.path.join(BASE, "topdown", "scannet_scene0004_00_topdown.png")
ego = "/tmp/ego_frame.png"


def fit(img, size):
    img = img.copy()
    img.thumbnail(size)
    return img


def pad(img, size, color=(24, 26, 34)):
    c = Image.new("RGB", size, color)
    c.paste(img, ((size[0] - img.width) // 2, (size[1] - img.height) // 2))
    return c


def _font(sz):
    for p in ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
              "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]:
        try:
            return ImageFont.truetype(p, sz)
        except Exception:
            pass
    return ImageFont.load_default()


TW, TH = 620, 620

# ---- panel 1: 2D top-down ----
p1 = Image.new("RGB", (TW, TH), (24, 26, 34))
d = ImageDraw.Draw(p1)
d.text((14, 10), "(1) 2D top-down  ·  matplotlib (verified)",
       fill=(255, 255, 255), font=_font(22))
d.text((14, 36), "Go2 位置+朝向 · 障碍物投影 · 米制坐标",
       fill=(170, 200, 255), font=_font(15))
p1.paste(pad(fit(Image.open(topdown), (TW - 24, TH - 70)), (TW, TH - 12)), (12, 56))

# ---- panel 2: Isaac 3D (real ego frame) ----
p2 = Image.new("RGB", (TW, TH), (24, 26, 34))
d = ImageDraw.Draw(p2)
d.text((14, 10), "(2) Isaac 3D  ·  ego / head camera",
       fill=(255, 255, 255), font=_font(22))
d.text((14, 36), "真实 Isaac 渲染 (1.1MB) · 机载视角",
       fill=(170, 255, 200), font=_font(15))
try:
    eg = Image.open(ego).convert("RGB")
    p2.paste(pad(fit(eg, (TW - 24, TH - 70)), (TW, TH - 12)), (12, 56))
except Exception:
    p2.paste(pad(Image.new("RGB", (TW - 24, TH - 70), (60, 60, 70)),
                 (TW, TH - 12)), (12, 56))

# ---- panel 3: honest note ----
p3 = Image.new("RGB", (TW, TH), (24, 26, 34))
d = ImageDraw.Draw(p3)
d.text((14, 10), "(3) 3D 俯视图 / perspective",
       fill=(255, 255, 255), font=_font(22))
note = [
    "这台 Isaac 6.0.1 是 headless (无 GUI",
    "窗口 / Xvfb 0 窗口)，自定义相机的",
    "render product 不渲染场景几何 →",
    "get_rgba / playback / RTSP 全是",
    "灰或黑。",
    "",
    "已试 10+ 种: world.step / app.update",
    "/ playback+IsaacCreateRenderProduct",
    "/ 绑 viewport / 挂机器人 / Grey",
    "Studio / 显式灯光 / RTSP+ffmpeg",
    "/ WebRTC viewer+computer_use。",
    "",
    "→ 3D 俯视图 用 (1) 2D 俯视图替代",
    "(信息量一样，更精确)。",
    "",
    "要真 3D 俯视图: 换一台 Isaac GUI",
    "视口真正渲染到 Xvfb 的机器。",
]
y = 58
for line in note:
    d.text((16, y), line, fill=(200, 200, 210), font=_font(16))
    y += 27

# ---- assemble 3 across ----
canvas = Image.new("RGB", (TW * 3 + 24, TH + 46), (16, 17, 24))
canvas.paste(p1, (8, 30))
canvas.paste(p2, (TW + 16, 30))
canvas.paste(p3, (TW * 2 + 24, 30))
d = ImageDraw.Draw(canvas)
d.text((14, 8), "One scene · 3 views   —   scannet/scene0004_00   (InternScenes → Isaac Sim)",
       fill=(255, 255, 255), font=_font(20))
canvas.save(OUT)
print("SAVED", OUT, os.path.getsize(OUT))
#!/usr/bin/env python3
"""Montage of the 3D->2D top-down projections (verified working) + a note on
the Isaac ego/third-person renders. Produces a single deliverable image.
"""
import os, glob
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.image import imread
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
TOP = sorted(glob.glob(os.path.join(ROOT, "output", "topdown", "*_topdown.png")))

# pick up to 6
imgs = []
for p in TOP[:6]:
    try:
        imgs.append((os.path.basename(p).replace("_topdown.png", ""), imread(p)))
    except Exception:
        pass

n = len(imgs)
if n == 0:
    print("no images")
    raise SystemExit
cols = 3
rows = int(np.ceil(n / cols))
fig, axes = plt.subplots(rows, cols, figsize=(15, 5 * rows))
axes = np.array(axes).reshape(-1)
for i, (name, im) in enumerate(imgs):
    ax = axes[i]
    ax.imshow(im)
    ax.set_title(name, fontsize=9)
    ax.axis("off")
# blank out unused
for i in range(n, len(axes)):
    axes[i].axis("off")
    axes[i].set_visible(False)
plt.suptitle("3D → 2D Top-Down Projections  (Go2 live marker + obstacle footprints)",
             fontsize=13, y=0.995)
plt.tight_layout(rect=[0, 0, 1, 0.98])
out = os.path.join(ROOT, "output", "topdown_montage.png")
plt.savefig(out, dpi=130, bbox_inches="tight")
plt.close()
print("montage:", out)
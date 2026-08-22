import json, os, time, subprocess, shutil
from pathlib import Path

PROJ = Path("/home/ubadmin/projects/InternScenes2isaacsim")
BLENDER = "/home/ubadmin/tools/blender/blender-5.1.2-linux-x64/blender"
RENDER_PY = PROJ / "scripts" / "glb_render.py"
chosen = json.loads((PROJ / "scripts" / "chosen_80.json").read_text())
OUT_ROOT = PROJ / "output" / "render_80"
OUT_ROOT.mkdir(parents=True, exist_ok=True)

# map dataset -> pretty category label
LABEL = {"scannet": "ScanNet", "3rscan": "3RScan",
         "arkitscenes": "ARKitScenes", "matterport3d": "Matterport3D"}

t0 = time.time()
made = 0
for d, scenes in chosen.items():
    for i, scene_abs in enumerate(scenes, start=1):
        rel = str(Path(scene_abs).resolve().relative_to(PROJ / "data" / "Layout_info"))
        glb = PROJ / "output" / "composed" / rel / "glb_scene.glb"
        num = "%02d" % i
        if not glb.exists():
            print(f"[{LABEL[d]} {num}] SKIP no glb: {rel}", flush=True)
            continue
        workdir = OUT_ROOT / f"{d}_{num}_work"
        workdir.mkdir(exist_ok=True)
        cmd = [BLENDER, "--background", "--python", str(RENDER_PY), "--",
               "--glb", str(glb), "--out", str(workdir), "--engine=EEVEE"]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=360)
            src = workdir / "perspective.png"
            if src.exists():
                dest = OUT_ROOT / f"{LABEL[d]}_{num}.png"
                shutil.copy(str(src), str(dest))
                made += 1
                sz = src.stat().st_size / 1e6
                print(f"[{LABEL[d]} {num}] OK {rel} -> {dest.name} ({sz:.1f}MB)", flush=True)
            else:
                print(f"[{LABEL[d]} {num}] NO PNG for {rel} (rc={r.returncode})", flush=True)
        except subprocess.TimeoutExpired:
            print(f"[{LABEL[d]} {num}] TIMEOUT {rel}", flush=True)
        except Exception as e:
            print(f"[{LABEL[d]} {num}] ERR {rel}: {e}", flush=True)

print(f"\nDONE in {time.time()-t0:.0f}s, rendered {made}/80")
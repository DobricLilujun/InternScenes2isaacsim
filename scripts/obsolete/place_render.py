import sys, os, math
import bpy
import mathutils

# ---- args ----
args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
scene_glb = go2 = out = "auto"
i = 0
while i < len(args):
    a = args[i]
    if a == "--scene" and i + 1 < len(args):
        i += 1; scene_glb = args[i]
    elif a.startswith("--scene="):
        scene_glb = a.split("=", 1)[1]
    elif a == "--go2" and i + 1 < len(args):
        i += 1; go2 = args[i]
    elif a.startswith("--go2="):
        go2 = a.split("=", 1)[1]
    elif a == "--out" and i + 1 < len(args):
        i += 1; out = args[i]
    elif a.startswith("--out="):
        out = a.split("=", 1)[1]
    i += 1

proj = "/home/ubadmin/projects/InternScenes2isaacsim"

# ---- placement from layout ----
sys.path.insert(0, proj + "/scripts")
import place_go2 as pg
# scene id = path between "composed/" and "glb_scene.glb"
norm = scene_glb.replace("\\", "/")
if "/composed/" in norm:
    scene_id = norm.split("/composed/")[1].split("/glb_scene.glb")[0]
elif "composed" in norm.split("/"):
    scene_id = norm.split("composed/")[1].split("/glb_scene.glb")[0]
else:
    scene_id = ""
layout = os.path.join(proj, "data", "Layout_info", scene_id, "layout.json")
print("scene_id:", scene_id, "layout:", layout, "exists:", os.path.exists(layout))
if not os.path.exists(layout):
    print("layout missing:", layout); sys.exit(1)
cand = pg.best_placement(pg.load_layout(layout))
if not cand:
    print("no valid placement"); sys.exit(2)
nearest, px, py = cand[0]
print(f"Go2 placement: ({px:.2f}, {py:.2f})  clearance={nearest:.2f}m  "
      f"({len(cand)} valid spots)")

# ---- import scene, remember its objects ----
bpy.ops.import_scene.gltf(filepath=scene_glb)
scene_objs = set(o.name for o in bpy.data.objects if o.type == "MESH")

# ---- import Go2 (new objects only) ----
bpy.ops.import_scene.gltf(filepath=go2)
go2_objs = [o for o in bpy.data.objects if o.type == "MESH" and o.name not in scene_objs]
print("go2 objects:", len(go2_objs))
# translate go2 to (px, py, 0)
for o in go2_objs:
    o.location.x += px
    o.location.y += py
    o.location.z += 0.0
bpy.context.view_layer.update()

# ---- scene bounds for camera ----
xs, ys, zs = [], [], []
for o in bpy.data.objects:
    if o.type != "MESH":
        continue
    for c in o.bound_box:
        w = o.matrix_world @ mathutils.Vector(c)
        xs.append(w.x); ys.append(w.y); zs.append(w.z)
cx = (min(xs)+max(xs))/2; cy = (min(ys)+max(ys))/2; cz = (min(zs)+max(zs))/2
sz = max(max(xs)-min(xs), max(ys)-min(ys))

# ---- ground ----
try:
    bpy.ops.mesh.primitive_plane_add(size=sz*5, location=(cx, cy, 0))
except Exception as e:
    print("ground err", e)

# ---- camera 3/4 view centered on the Go2 ----
bpy.ops.object.camera_add()
cam = bpy.context.active_object
try:
    cam.data.lens = 45
except Exception:
    pass
bpy.context.scene.camera = cam
d = mathutils.Vector((px, py, 0.4)) - (
    (cx + sz*0.9, cy - sz*0.9, cz + sz*0.4))
cam.location = (cx + sz*0.9, cy - sz*0.9, cz + sz*0.4)
cam.rotation_euler = d.to_track_quat('-Z', 'Y').to_euler()

bpy.ops.object.light_add(type='SUN')
sun = bpy.context.active_object
try:
    sun.data.energy = 3.0
    sun.rotation_euler = (math.radians(50), 0, math.radians(120))
except Exception:
    pass

sc = bpy.context.scene
try:
    sc.render.engine = "BLENDER_EEVEE"
except Exception:
    pass
sc.render.resolution_x = 1280
sc.render.resolution_y = 960
os.makedirs(out, exist_ok=True)
fp = os.path.join(out, "go2_placed.png")
sc.render.filepath = fp
try:
    bpy.ops.render.render(write_still=True)
    print("saved:", fp)
except Exception as e:
    print("render ERR:", e)
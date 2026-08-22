import os
import math
import bpy
import mathutils

scene_id = os.environ["SCENE_ID"]
px = float(os.environ["GO2X"])
py = float(os.environ["GO2Y"])
proj = "/home/ubadmin/projects/InternScenes2isaacsim"
scene_glb = f"{proj}/output/composed/{scene_id}/glb_scene.glb"
go2_glb = f"{proj}/assets/go2_built.glb"

# import scene
bpy.ops.import_scene.gltf(filepath=scene_glb)
scene_objs = set(o.name for o in bpy.data.objects if o.type == "MESH")
# import go2
bpy.ops.import_scene.gltf(filepath=go2_glb)
go2_objs = [o for o in bpy.data.objects if o.type == "MESH" and o.name not in scene_objs]
print("go2 objects:", len(go2_objs))
for o in go2_objs:
    o.location.x += px
    o.location.y += py
    o.location.z += 0.0
bpy.context.view_layer.update()

# scene bounds for camera
xs, ys, zs = [], [], []
for o in bpy.data.objects:
    if o.type != "MESH":
        continue
    for c in o.bound_box:
        w = o.matrix_world @ mathutils.Vector(c)
        xs.append(w.x); ys.append(w.y); zs.append(w.z)
cx = (min(xs)+max(xs))/2; cy = (min(ys)+max(ys))/2; cz = (min(zs)+max(zs))/2
sz = max(max(xs)-min(xs), max(ys)-min(ys))

# ground
try:
    bpy.ops.mesh.primitive_plane_add(size=sz*5, location=(cx, cy, 0))
except Exception as e:
    print("ground err", e)

# camera 3/4 view looking at the Go2, standing on the OPEN side (away from the
# nearest furniture) so the robot has a clean background.
bpy.ops.object.camera_add()
cam = bpy.context.active_object
try:
    cam.data.lens = 55
except Exception:
    pass
bpy.context.scene.camera = cam

# find nearest scene object to the Go2 (to stand opposite it)
go2_names = set(o.name for o in go2_objs)
nx = ny = None
best_d = 1e9
for o in bpy.data.objects:
    if o.type != "MESH" or o.name in go2_names:
        continue
    wx = o.location.x; wy = o.location.y
    d2 = (wx - px) ** 2 + (wy - py) ** 2
    if d2 < best_d:
        best_d = d2
        nx, ny = wx, wy
if nx is not None and best_d > 1e-6:
    dx, dy = px - nx, py - ny           # direction from nearest obj -> go2
    m = math.hypot(dx, dy)
    ux, uy = dx / m, dy / m            # open side = go2 + (away from obj)
else:
    ux, uy = 0.7, -0.7
cam.location = (px + ux * 2.0, py + uy * 2.0, 1.5)
look = mathutils.Vector((px, py, 0.30))
d = look - cam.location
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
out = f"{proj}/output/go2_placed"
os.makedirs(out, exist_ok=True)
fp = os.path.join(out, f"{scene_id.replace('/','_')}_go2.png")
sc.render.filepath = fp
try:
    bpy.ops.render.render(write_still=True)
    print("saved:", fp)
except Exception as e:
    print("render ERR:", e)
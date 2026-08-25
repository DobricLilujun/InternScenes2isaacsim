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

# ---- import scene ----
bpy.ops.import_scene.gltf(filepath=scene_glb)
scene_objs = set(o.name for o in bpy.data.objects if o.type == "MESH")
# ---- import go2 (after, so new objects are the Go2) ----
bpy.ops.import_scene.gltf(filepath=go2_glb)
go2_objs = [o for o in bpy.data.objects if o.type == "MESH" and o.name not in scene_objs]
print("go2 objects:", len(go2_objs))
for o in go2_objs:
    o.location.x += px
    o.location.y += py
    o.location.z += 0.0
bpy.context.view_layer.update()

# ---- hide walls / ceiling / floor by SIZE (structure is >3m; furniture <2m) ----
def hide_structure():
    for obj in bpy.data.objects:
        if obj.type != "MESH":
            continue
        # bounding size in world space
        sx = sy = sz = 0.0
        try:
            mn = [1e9, 1e9, 1e9]
            mx = [-1e9, -1e9, -1e9]
            for c in obj.bound_box:
                w = obj.matrix_world @ mathutils.Vector(c)
                for i in range(3):
                    if w[i] < mn[i]:
                        mn[i] = w[i]
                    if w[i] > mx[i]:
                        mx[i] = w[i]
            sx, sy, sz = mx[0] - mn[0], mx[1] - mn[1], mx[2] - mn[2]
        except Exception:
            continue
        # large flat (wall/ceiling/floor) or any huge object -> hide
        if max(sx, sy, sz) > 3.0:
            obj.hide_render = True
            obj.hide_viewport = True
hide_structure()

# ---- add a ground plane under the Go2 (scene floor was hidden) ----
try:
    bpy.ops.mesh.primitive_plane_add(size=8.0, location=(px, py, 0.0))
    g = bpy.context.active_object
    g.name = "Go2Ground"
except Exception as e:
    print("ground err", e)

# ---- bright world background (the key to visible renders) ----
try:
    sc = bpy.context.scene
    world = sc.world or bpy.data.worlds.new("World")
    sc.world = world
    world.use_nodes = True
    bg = world.node_tree.nodes.get("Background")
    if bg:
        bg.inputs[0].default_value = (0.85, 0.86, 0.90, 1)
        bg.inputs[1].default_value = 1.2
except Exception as e:
    print("world err", e)

# ---- sun light ----
try:
    sun = bpy.data.lights.new("Sun", 'SUN')
    sun.energy = 2.5
    sun.angle = math.radians(50)
    sun.color = (1.0, 0.97, 0.92)
    sun_obj = bpy.data.objects.new("Sun", sun)
    bpy.context.collection.objects.link(sun_obj)
    sun_obj.location = (px + 5, py - 5, 15)
    sun_obj.rotation_euler = (math.radians(45), math.radians(10), math.radians(30))
except Exception as e:
    print("sun err", e)

# ---- camera: frame the Go2 on its OPEN side, wide lens, close ----
bpy.ops.object.camera_add()
cam = bpy.context.active_object
try:
    cam.data.lens = 35
    cam.data.clip_end = 500
except Exception:
    pass
bpy.context.scene.camera = cam

# stand on the open side (opposite nearest scene object)
go2_names = set(o.name for o in go2_objs)
nx = ny = None
best_d = 1e9
for o in bpy.data.objects:
    if o.type != "MESH" or o.name in go2_names or o.name == "Go2Ground":
        continue
    wx = o.location.x; wy = o.location.y
    d2 = (wx - px) ** 2 + (wy - py) ** 2
    if d2 < best_d:
        best_d = d2
        nx, ny = wx, wy
if nx is not None and best_d > 1e-6:
    dx, dy = px - nx, py - ny
    m = math.hypot(dx, dy)
    ux, uy = dx / m, dy / m
else:
    ux, uy = 0.7, -0.7
cam.location = (px + ux * 1.7, py + uy * 1.7, 1.0)
look = mathutils.Vector((px, py, 0.35))
d = look - cam.location
cam.rotation_euler = d.to_track_quat('-Z', 'Y').to_euler()

# ---- render ----
sc = bpy.context.scene
for eng in ("BLENDER_EEVEE_NEXT", "BLENDER_EEVEE"):
    try:
        sc.render.engine = eng
        break
    except Exception:
        continue
sc.render.resolution_x = 1280
sc.render.resolution_y = 960
out = f"{proj}/output/go2_placed"
os.makedirs(out, exist_ok=True)
fp = os.path.join(out, f"{scene_id.replace('/', '_')}_go2.png")
sc.render.filepath = fp
try:
    bpy.ops.render.render(write_still=True)
    print("saved:", fp)
except Exception as e:
    print("render ERR:", e)
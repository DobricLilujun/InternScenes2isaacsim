import sys, os, math
import bpy
import mathutils

args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
glb = out = "auto"
i = 0
while i < len(args):
    a = args[i]
    if a == "--glb" and i + 1 < len(args):
        i += 1; glb = args[i]
    elif a.startswith("--glb="):
        glb = a.split("=", 1)[1]
    if a == "--out" and i + 1 < len(args):
        i += 1; out = args[i]
    elif a.startswith("--out="):
        out = a.split("=", 1)[1]
    i += 1

bpy.ops.import_scene.gltf(filepath=glb)
bpy.context.view_layer.update()
for o in list(bpy.data.objects):
    if o.type in ('CAMERA', 'LIGHT'):
        bpy.data.objects.remove(o, do_unlink=True)

xs, ys, zs = [], [], []
for o in bpy.data.objects:
    if o.type != 'MESH':
        continue
    for c in o.bound_box:
        w = o.matrix_world @ mathutils.Vector(c)
        xs.append(w.x); ys.append(w.y); zs.append(w.z)
cx, cy, cz = sum(xs)/len(xs), sum(ys)/len(ys), sum(zs)/len(zs)
sz = max(max(xs)-min(xs), max(ys)-min(ys), max(zs)-min(zs)) if xs else 1.0
print("center:", (round(cx,3),round(cy,3),round(cz,3)), "size:", round(sz,3))

try:
    bpy.ops.mesh.primitive_plane_add(size=sz*8, location=(cx, cy, min(zs)))
    bpy.context.active_object.name = "Ground"
except Exception as e:
    print("ground err", e)

def render_view(name, loc, lens):
    bpy.ops.object.camera_add()
    cam = bpy.context.active_object
    try:
        cam.data.lens = lens
    except Exception:
        pass
    bpy.context.scene.camera = cam
    cam.location = loc
    d = mathutils.Vector((cx, cy, cz)) - cam.location
    cam.rotation_euler = d.to_track_quat('-Z', 'Y').to_euler()
    bpy.ops.object.light_add(type='SUN')
    sun = bpy.context.active_object
    try:
        sun.data.energy = 4.0
        sun.rotation_euler = (math.radians(55), 0, math.radians(120))
    except Exception:
        pass
    scene = bpy.context.scene
    try:
        scene.render.engine = "BLENDER_EEVEE"
    except Exception:
        pass
    scene.render.resolution_x = 1280
    scene.render.resolution_y = 960
    os.makedirs(out, exist_ok=True)
    fp = os.path.join(out, name)
    scene.render.filepath = fp
    try:
        bpy.ops.render.render(write_still=True)
    except Exception as e:
        print("render ERR:", e)
    print(name, "exists:", os.path.exists(fp))

# 3/4 view (front-right, low)
render_view("go2_34.png",
           (cx + sz*1.5, cy - sz*1.5, cz + sz*0.6), 50)
# top-down
render_view("go2_top.png",
           (cx + 0.01, cy, cz + sz*4.5), 50)
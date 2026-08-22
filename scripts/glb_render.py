#!/usr/bin/env python3
"""Render a composed InternScenes GLB to a perspective PNG in Blender (headless).

Places the camera INSIDE the room (walls/ceiling hidden so the interior is
visible), at eye level, looking across the furniture.  Materials/textures are
preserved on glTF import, so the render is the visual proof that the composed
scene renders correctly.

Usage (run via Blender):
    blender --background --python glb_render.py -- --glb <scene.glb> --out <dir>
"""
import sys, os, math
import bpy
import mathutils


def parse_args():
    args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    glb = out = engine = "auto"
    i = 0
    while i < len(args):
        a = args[i]
        if a.startswith("--glb="):
            glb = a.split("=", 1)[1]
        elif a == "--glb":
            i += 1
            if i < len(args):
                glb = args[i]
        elif a.startswith("--out="):
            out = a.split("=", 1)[1]
        elif a == "--out":
            i += 1
            if i < len(args):
                out = args[i]
        elif a.startswith("--engine="):
            engine = a.split("=", 1)[1]
        elif a == "--engine":
            i += 1
            if i < len(args):
                engine = args[i]
        i += 1
    return glb, out, engine


def import_glb(glb_path):
    bpy.ops.import_scene.gltf(filepath=glb_path)
    for ob in list(bpy.data.objects):
        if ob.name in ("Cube",):
            bpy.data.objects.remove(ob)
    bpy.context.view_layer.update()


def hide_structure():
    for obj in bpy.data.objects:
        if obj.type != 'MESH':
            continue
        nm = obj.name.lower()
        if any(kw in nm for kw in ("floor", "wall", "ceiling")):
            obj.hide_render = True
            obj.hide_viewport = True


def compute_bounds():
    mn = mathutils.Vector((1e9, 1e9, 1e9))
    mx = mathutils.Vector((-1e9, -1e9, -1e9))
    for obj in bpy.data.objects:
        if obj.type != 'MESH' or not obj.data or len(obj.data.vertices) == 0:
            continue
        if obj.hide_render:
            continue
        for bb in obj.bound_box:
            bp = mathutils.Vector((bb[0], bb[1], bb[2]))
            wp = obj.matrix_world @ bp
            for i in range(3):
                if wp[i] < mn[i]:
                    mn[i] = wp[i]
                if wp[i] > mx[i]:
                    mx[i] = wp[i]
    return mn, mx


def place_camera():
    mn, mx = compute_bounds()
    center = (mn + mx) / 2.0
    span = mx - mn
    eye_z = mn.z + 1.5
    cam_x = mn.x + span.x * 0.15
    cam_y = mn.y + span.y * 0.15
    cam_loc = mathutils.Vector((cam_x, cam_y, eye_z))
    look = mathutils.Vector((center.x + span.x * 0.1,
                             center.y + span.y * 0.1,
                             center.z - 0.3))
    cam_data = bpy.data.cameras.new("Camera")
    cam_data.type = "PERSP"
    cam_data.lens = 16.0
    cam_data.clip_start = 0.01
    cam_data.clip_end = span.length * 10 + 100.0
    cam = bpy.data.objects.new("Camera", cam_data)
    bpy.context.collection.objects.link(cam)
    cam.location = cam_loc
    cam.rotation_euler = (look - cam_loc).to_track_quat('-Z', 'Y').to_euler()
    bpy.context.scene.camera = cam


def add_lighting():
    mn, mx = compute_bounds()
    center = (mn + mx) / 2.0
    try:
        sun = bpy.data.lights.new("Sun", 'SUN')
        sun.energy = 2.5
        sun.angle = math.radians(50)
        sun.color = (1.0, 0.97, 0.92)
        sun_obj = bpy.data.objects.new("Sun", sun)
        bpy.context.collection.objects.link(sun_obj)
        sun_obj.location = center + mathutils.Vector((5, -5, 15))
        sun_obj.rotation_euler = (math.radians(45), math.radians(10), math.radians(30))
    except Exception:
        pass
    try:
        scene = bpy.context.scene
        world = scene.world or bpy.data.worlds.new("World")
        scene.world = world
        bg = world.node_tree.nodes.get("Background")
        if bg:
            bg.inputs[0].default_value = (0.7, 0.72, 0.78, 1)
            bg.inputs[1].default_value = 1.2
    except Exception:
        pass


def render(out_dir, engine):
    scene = bpy.context.scene
    if "CYCLES" in engine.upper():
        scene.render.engine = "CYCLES"
        scene.cycles.samples = 96
        try:
            scene.cycles.device = "GPU"
            bpy.context.preferences.addons["cycles"].preferences.compute_device_type = "CUDA"
            for d in bpy.context.preferences.addons["cycles"].preferences.devices:
                d.use = True
        except Exception:
            pass
    else:
        for eng in ("BLENDER_EEVEE_NEXT", "BLENDER_EEVEE"):
            try:
                scene.render.engine = eng
                break
            except Exception:
                continue
    scene.render.resolution_x = 1920
    scene.render.resolution_y = 1080
    scene.render.filepath = os.path.join(out_dir, "perspective.png")
    scene.render.image_settings.file_format = "PNG"
    os.makedirs(out_dir, exist_ok=True)
    print("rendering with engine =", scene.render.engine)
    bpy.ops.render.render(write_still=True)
    print("render saved:", scene.render.filepath)


def main():
    glb, out, engine = parse_args()
    if not glb or glb in ("", "auto"):
        print("ERROR: --glb= required")
        sys.exit(1)
    out_dir = out or os.path.dirname(glb)
    import_glb(glb)
    hide_structure()
    place_camera()
    add_lighting()
    render(out_dir, engine)
    print("DONE")


if __name__ == "__main__":
    main()
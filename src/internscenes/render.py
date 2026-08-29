"""Render a composed InternScenes GLB to a perspective PNG in Blender (headless).

Places the camera INSIDE the room (walls/ceiling hidden so the interior is
visible), at eye level, looking across the furniture.  Materials/textures are
preserved on glTF import, so the render is the visual proof that the composed
scene renders correctly.

This module **must run inside the Blender Python process** because it imports
``bpy``.  The package exposes a ``-m`` CLI for use in environments where
``bpy`` is importable (for example a Blender-adjacent venv).  For the normal
Isaac Sim / project venv, the pipeline calls Blender with
:mod:`internscenes._render_in_blender`, which re-executes this module using the
project venv Python inside Blender's process.

Public entry point: :func:`render_scene(glb_path, out_dir, engine)`.
"""
from __future__ import annotations

import argparse
import logging
import math
import os
import sys
from pathlib import Path

logger = logging.getLogger(__name__)


def _import_glb(glb_path: str):
    import bpy
    bpy.ops.import_scene.gltf(filepath=glb_path)
    for ob in list(bpy.data.objects):
        if ob.name in ("Cube",):
            bpy.data.objects.remove(ob)
    bpy.context.view_layer.update()


def _hide_structure():
    import bpy
    for obj in bpy.data.objects:
        if obj.type != "MESH":
            continue
        nm = obj.name.lower()
        if any(kw in nm for kw in ("floor", "wall", "ceiling")):
            obj.hide_render = True
            obj.hide_viewport = True


def _compute_bounds():
    import bpy
    import mathutils
    mn = mathutils.Vector((1e9, 1e9, 1e9))
    mx = mathutils.Vector((-1e9, -1e9, -1e9))
    for obj in bpy.data.objects:
        if obj.type != "MESH" or not obj.data or len(obj.data.vertices) == 0:
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


def _place_camera():
    import bpy
    import mathutils
    mn, mx = _compute_bounds()
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
    cam.rotation_euler = (look - cam_loc).to_track_quat("-Z", "Y").to_euler()
    bpy.context.scene.camera = cam


def _add_lighting():
    import bpy
    import mathutils
    mn, mx = _compute_bounds()
    center = (mn + mx) / 2.0
    try:
        sun = bpy.data.lights.new("Sun", "SUN")
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


def _render(out_dir: str, engine: str):
    import bpy
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
    logger.info("rendering with engine = %s", scene.render.engine)
    bpy.ops.render.render(write_still=True)
    logger.info("render saved: %s", scene.render.filepath)


def render_scene(glb_path: str, out_dir: str | None = None, engine: str = "auto") -> str:
    """Render ``glb_path`` to ``<out_dir>/perspective.png``.

    This is the public entry point.  It must be called from a Blender Python
    process (i.e. when ``bpy`` is importable).  ``engine`` can be
    ``"CYCLES"`` or ``"auto"`` (tries Eevee then Cycles).
    """
    import bpy
    out_dir = out_dir or os.path.dirname(glb_path)
    out_dir = os.path.abspath(out_dir)
    _import_glb(glb_path)
    _hide_structure()
    _place_camera()
    _add_lighting()
    _render(out_dir, engine)
    return os.path.join(out_dir, "perspective.png")


def _cli_parse(argv: list[str] | None = None):
    """Parse Blender CLI arguments, skipping Blender's own prefix."""
    if argv is None:
        argv = sys.argv
    # Drop everything up to and including the script name or Blender binary.
    # Typical forms:
    #   blender --python <script> -- --glb ...
    #   python -m internscenes.render --glb ...
    if "--" in argv:
        args = argv[argv.index("--") + 1:]
    else:
        # strip leading entries until we see a known option
        keys = ("--glb", "--out", "--engine")
        start = 0
        for idx, a in enumerate(argv):
            if a.startswith("--") and any(a.startswith(k) for k in keys):
                start = idx
                break
        args = argv[start:]
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


def main() -> int:
    glb, out, engine = _cli_parse()
    if not glb or glb in ("", "auto"):
        logger.error("--glb= required")
        return 1
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    render_scene(glb, out or None, engine)
    logger.info("DONE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

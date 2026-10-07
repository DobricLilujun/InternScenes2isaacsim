"""Multi-view (orbit + top-down) capture for VLM annotation.

Mirrors :mod:`internscenes.render` but renders a ring of *orbit* cameras around
the room centre at eye level (default 8) plus one *top-down* view, all in a
single Blender session (the glTF is imported once and re-used for every camera).

Like :mod:`internscenes.render`, this module **must run inside the Blender
Python process** (it imports ``bpy``).  It is bootstrapped by
:mod:`internscenes._render_in_blender` (which re-executes it via the project
venv Python inside Blender's interpreter).  The pipeline's
``stage_render_multi`` invokes Blender with ``--python _render_in_blender.py``
and ``INTERN_RENDER_FILE=render_multi.py``.

Public entry point: :func:`render_multi(glb_path, out_dir, engine, n_views)`.
"""
from __future__ import annotations

import argparse
import logging
import math
import os
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_VIEWS = 8
DEFAULT_HEIGHT = 1.6
DEFAULT_RESOLUTION = (1920, 1080)


# ---------------------------------------------------------------------------
# geometry (mirrors render.py so a single glb import serves every camera)
# ---------------------------------------------------------------------------
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
        sun_obj.rotation_euler = (math.radians(45), math.radians(10),
                                  math.radians(30))
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


def orbit_cameras(center, mn, mx, n, height):
    """Evenly spaced orbit positions (X,Y) around ``center`` at eye height."""
    span = mx - mn
    radius = max(span.x, span.y) * 0.5 * 1.25 + 1.0
    eye_z = min(height, mx.z - 0.2) if mx.z > height else height
    cams = []
    for k in range(n):
        theta = 2.0 * math.pi * k / n
        x = center.x + radius * math.cos(theta)
        y = center.y + radius * math.sin(theta)
        cams.append((x, y, eye_z))
    # one top-down view
    cams.append((center.x, center.y, mx.z + 5.0))
    return cams


def _place_camera(center, pos, fov_deg):
    import bpy
    import mathutils
    mn, mx = _compute_bounds()
    span = mx - mn
    cam_loc = mathutils.Vector((pos[0], pos[1], pos[2]))
    look = mathutils.Vector((center.x, center.y, center.z - 0.2))
    cam_data = bpy.data.cameras.new("Cam")
    cam_data.type = "PERSP"
    cam_data.lens = 50.0 * (2.0 / math.tan(math.radians(fov_deg)))
    cam_data.clip_start = 0.01
    cam_data.clip_end = span.length * 10 + 100.0
    cam = bpy.data.objects.new("Cam", cam_data)
    bpy.context.collection.objects.link(cam)
    cam.location = cam_loc
    cam.rotation_euler = (look - cam_loc).to_track_quat("-Z", "Y").to_euler()
    return cam


def _configure_engine(engine: str):
    import bpy
    scene = bpy.context.scene
    if "CYCLES" in str(engine).upper():
        scene.render.engine = "CYCLES"
        scene.cycles.samples = 64
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


# ---------------------------------------------------------------------------
# public entry
# ---------------------------------------------------------------------------
def render_multi(
    glb_path: str,
    out_dir: str | None = None,
    engine: str = "auto",
    n_views: int = DEFAULT_VIEWS,
    height: float = DEFAULT_HEIGHT,
    resolution: tuple[int, int] = DEFAULT_RESOLUTION,
    scene_id: str | None = None,
) -> list[str]:
    """Render ``n_views`` orbit views + 1 top-down into ``out_dir``.

    Must be called from a Blender Python process (``bpy`` importable).
    Returns the list of written image paths.  ``scene_id`` controls the
    output filenames (``<scene_id>__view_k.png`` / ``<scene_id>__topdown.png``);
    it defaults to the output directory name when not given.
    """
    import bpy
    out_dir = out_dir or os.path.dirname(glb_path)
    out_dir = os.path.abspath(out_dir)
    os.makedirs(out_dir, exist_ok=True)
    scene_id = scene_id or _scene_id_from_out(out_dir)
    flat = str(scene_id).replace("/", "_")

    _import_glb(glb_path)
    _hide_structure()
    _add_lighting()
    _configure_engine(engine)

    mn, mx = _compute_bounds()
    center = (mn + mx) / 2.0
    positions = orbit_cameras(center, mn, mx, n_views, height)

    scene = bpy.context.scene
    scene.render.resolution_x = resolution[0]
    scene.render.resolution_y = resolution[1]
    scene.render.image_settings.file_format = "PNG"

    written: list[str] = []
    for k, pos in enumerate(positions):
        is_top = k == len(positions) - 1
        name = f"{flat}__topdown.png" if is_top \
            else f"{flat}__view_{k}.png"
        out_path = os.path.join(out_dir, name)
        cam = _place_camera(center, pos, fov_deg=70.0)
        scene.camera = cam
        scene.render.filepath = out_path
        logger.info("rendering view %d -> %s", k, out_path)
        bpy.ops.render.render(write_still=True)
        written.append(out_path)
    return written


def _scene_id_from_out(out_dir: str) -> str:
    return Path(out_dir).name or "scene"


def _cli_parse(argv: list[str] | None = None):
    """Parse Blender CLI arguments, skipping Blender's own prefix."""
    if argv is None:
        argv = sys.argv
    if "--" in argv:
        args = argv[argv.index("--") + 1:]
    else:
        keys = ("--glb", "--out", "--engine", "--views", "--height")
        start = 0
        for idx, a in enumerate(argv):
            if a.startswith("--") and any(a.startswith(k) for k in keys):
                start = idx
                break
        args = argv[start:]

    def _get(flag):
        for i, a in enumerate(args):
            if a == flag:
                return args[i + 1] if i + 1 < len(args) else ""
            if a.startswith(flag + "="):
                return a.split("=", 1)[1]
        return ""

    glb = _get("--glb") or "auto"
    out = _get("--out") or ""
    engine = _get("--engine") or "auto"
    views = int(_get("--views") or DEFAULT_VIEWS)
    height = float(_get("--height") or DEFAULT_HEIGHT)
    scene = _get("--scene") or ""
    return glb, out, engine, views, height, scene


def main() -> int:
    glb, out, engine, views, height, scene = _cli_parse()
    if not glb or glb in ("", "auto"):
        logger.error("--glb= required")
        return 1
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    try:
        written = render_multi(glb, out or None, engine, views, height,
                               scene_id=(scene or None))
    except Exception as exc:  # noqa: BLE001
        logger.exception("multi-view render failed: %s", exc)
        return 1
    logger.info("multi-view render complete: %d views", len(written))
    logger.info("DONE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

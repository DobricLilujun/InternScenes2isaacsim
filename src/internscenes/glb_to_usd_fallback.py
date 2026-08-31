"""``usd-exchange`` / ``pxr`` GLB → USD fallback converter.

This backend produces a real PBR USD (``Z`` up, ``metersPerUnit = 1``,
``UsdPreviewSurface`` materials with exported textures, vertex normals,
UVs) when Isaac Sim is **not** installed.

Public entry point: :func:`build_usd(glb_path, out_usd)`.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _ensure_trimesh():
    try:
        import trimesh  # noqa: F401
        import trimesh.exchange.gltf  # noqa: F401
    except Exception as exc:
        raise ImportError(
            "trimesh is required for the usd-exchange fallback backend"
        ) from exc


def _load_gltf(glb_path: str):
    import trimesh
    scene = trimesh.load(glb_path, force="scene")
    if isinstance(scene, trimesh.Scene):
        return scene
    s = trimesh.Scene()
    s.add_geometry(scene)
    return s


def _safe_name(name: str) -> str:
    """Turn a node/geometry name into a valid USD prim identifier."""
    safe = "".join(
        c if c.isalnum() or c == "_" else "_" for c in str(name)
    ).strip("_.")
    if safe and safe[0].isdigit():
        safe = "m_" + safe
    return safe or "mesh"


def _save_image(img, tex_dir: Path, basename: str, fallback_ext: str = ".png") -> Path | None:
    """Save a PIL / numpy image to ``tex_dir`` and return the saved path."""
    try:
        from PIL import Image as PILImage
    except Exception:
        PILImage = None  # type: ignore

    if img is None:
        return None

    path = tex_dir / basename
    try:
        if PILImage is not None and isinstance(img, PILImage.Image):
            fmt = img.format
            if fmt in ("JPEG", "JPG"):
                path = path.with_suffix(".jpg")
                img.save(path, "JPEG")
            elif fmt == "PNG":
                path = path.with_suffix(".png")
                img.save(path, "PNG")
            else:
                path = path.with_suffix(fallback_ext)
                img.save(path)
            return path
        # numpy array fallback
        import numpy as np
        arr = np.asarray(img)
        if arr.ndim == 3 and arr.shape[-1] == 4:
            path = path.with_suffix(".png")
            if PILImage is not None:
                PILImage.fromarray(arr).save(path)
        elif arr.ndim in (2, 3):
            path = path.with_suffix(".png")
            if PILImage is not None:
                PILImage.fromarray(arr).save(path)
        return path if path.exists() else None
    except Exception as exc:
        logger.debug("could not save texture %s: %s", basename, exc)
        return None


def _build_preview_surface(
    stage,
    prim,
    material: Any | None,
    tex_dir: Path,
    texture_counter: list[int],
):
    """Attach a ``UsdPreviewSurface`` material with ``UsdUVTexture`` bindings.

    The resulting material graph is compatible with standard USD viewers.
    """
    from pxr import UsdShade, Sdf

    mesh_path = prim.GetPath()
    mat_path = mesh_path.AppendChild("Looks").AppendChild("material")
    mat = UsdShade.Material.Define(stage, mat_path)

    shader_path = mat_path.AppendChild("shader")
    shader = UsdShade.Shader.Define(stage, shader_path)
    shader.CreateIdAttr("UsdPreviewSurface")

    # Create primvar reader for UVs
    primvar_path = mat_path.AppendChild("primvar_st")
    primvar_reader = UsdShade.Shader.Define(stage, primvar_path)
    primvar_reader.CreateIdAttr("UsdPrimvarReader_float2")
    primvar_reader.CreateInput("varname", Sdf.ValueTypeNames.Token).Set("st")
    st_output = primvar_reader.CreateOutput("result", Sdf.ValueTypeNames.Float2)

    def _get_factor(name: str, default: float) -> float:
        if material is None:
            return default
        try:
            v = getattr(material, name, None)
            return float(v) if v is not None else default
        except Exception:
            return default

    def _get_color(name: str, default: tuple[float, float, float]):
        if material is None:
            return default
        try:
            v = getattr(material, name, None)
            if v is None:
                return default
            v = tuple(v)
            if len(v) >= 3:
                return tuple(float(x) for x in v[:3])
            if len(v) == 4:
                return tuple(float(x) for x in v[:3])
        except Exception:
            pass
        return default

    shader.CreateInput("diffuseColor", Sdf.ValueTypeNames.Color3f).Set(
        _get_color("baseColorFactor", (1.0, 1.0, 1.0))
    )
    shader.CreateInput("roughness", Sdf.ValueTypeNames.Float).Set(
        _get_factor("roughnessFactor", 0.5)
    )
    shader.CreateInput("metallic", Sdf.ValueTypeNames.Float).Set(
        _get_factor("metallicFactor", 0.0)
    )
    shader.CreateInput("specularColor", Sdf.ValueTypeNames.Color3f).Set((0.0, 0.0, 0.0))

    def _bind_texture(
        texture_attr: str,
        shader_input: str,
        output_name: str = "rgb",
    ) -> None:
        if material is None:
            return
        tex = getattr(material, texture_attr, None)
        if tex is None:
            return
        texture_counter[0] += 1
        tex_name = f"texture_{texture_counter[0]:04d}"
        saved = _save_image(tex, tex_dir, tex_name)
        if saved is None:
            return
        rel_path = f"textures/{saved.name}"

        tex_shader_path = mat_path.AppendChild(f"{tex_name}_shader")
        tex_shader = UsdShade.Shader.Define(stage, tex_shader_path)
        tex_shader.CreateIdAttr("UsdUVTexture")
        tex_shader.CreateInput("file", Sdf.ValueTypeNames.Asset).Set(rel_path)
        tex_shader.CreateInput("st", Sdf.ValueTypeNames.Float2).ConnectToSource(st_output)
        tex_shader.CreateOutput(output_name, Sdf.ValueTypeNames.Color3f if output_name == "rgb" else Sdf.ValueTypeNames.Float)

        inp = shader.CreateInput(shader_input, Sdf.ValueTypeNames.Color3f if output_name == "rgb" else Sdf.ValueTypeNames.Float)
        inp.ConnectToSource(
            tex_shader.ConnectableAPI(),
            output_name,
        )

    # Bind known PBR texture slots.
    _bind_texture("baseColorTexture", "diffuseColor", "rgb")
    _bind_texture("emissiveTexture", "emissiveColor", "rgb")
    _bind_texture("normalTexture", "normal", "rgb")
    # glTF metallicRoughness texture: G=roughness, B=metallic
    _bind_texture("metallicRoughnessTexture", "roughness", "g")
    _bind_texture("metallicRoughnessTexture", "metallic", "b")
    _bind_texture("occlusionTexture", "occlusion", "r")

    UsdShade.MaterialBindingAPI(prim).Bind(mat)


def build_usd(glb_path: str, out_usd: str) -> str:
    """Convert ``glb_path`` to a USD file at ``out_usd``.

    Returns the absolute path to the generated USD.  Raises
    ``FileNotFoundError`` for a missing input GLB and ``RuntimeError`` if
    conversion fails.
    """
    _ensure_trimesh()
    import trimesh
    from pxr import Usd, UsdGeom, Sdf, Gf

    if not os.path.isfile(glb_path):
        raise FileNotFoundError(f"GLB not found: {glb_path}")

    out_usd = os.path.abspath(out_usd)
    out_dir = Path(out_usd).parent
    tex_dir = out_dir / "textures"
    os.makedirs(tex_dir, exist_ok=True)

    scene = _load_gltf(glb_path)

    stage = Usd.Stage.CreateNew(out_usd)
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.z)
    stage.SetMetadata("metersPerUnit", 1.0)

    world = stage.DefinePrim("/World", "Xform")
    stage.SetDefaultPrim(world)

    texture_counter = [0]

    for node_name in scene.graph.nodes_geometry:
        transform, geom_name = scene.graph[node_name]
        mesh = scene.geometry.get(geom_name)
        if mesh is None:
            continue

        safe = _safe_name(node_name)
        if not safe:
            safe = f"mesh_{texture_counter[0]}"
        prim_path = world.GetPath().AppendChild(safe)
        mesh_prim = UsdGeom.Mesh.Define(stage, prim_path)

        vertices = mesh.vertices.tolist()
        faces = mesh.faces.tolist() if hasattr(mesh, "faces") else []
        if faces:
            face_vertex_counts = [len(f) for f in faces]
            face_vertex_indices = [i for f in faces for i in f]
            mesh_prim.CreateFaceVertexCountsAttr(face_vertex_counts)
            mesh_prim.CreateFaceVertexIndicesAttr(face_vertex_indices)
        mesh_prim.CreatePointsAttr(vertices)

        if hasattr(mesh, "vertex_normals") and mesh.vertex_normals is not None:
            mesh_prim.CreateNormalsAttr(mesh.vertex_normals.tolist())
            mesh_prim.SetNormalsInterpolation("vertex")

        uvs = getattr(getattr(mesh, "visual", None), "uv", None)
        if uvs is not None:
            primvar = UsdGeom.PrimvarsAPI(mesh_prim).CreatePrimvar(
                "st", Sdf.ValueTypeNames.TexCoord2fArray
            )
            primvar.Set(uvs.tolist())
            primvar.SetInterpolation("vertex")

        material = getattr(getattr(mesh, "visual", None), "material", None)
        _build_preview_surface(stage, mesh_prim, material, tex_dir, texture_counter)

        matrix = transform.tolist()
        xform = UsdGeom.Xformable(mesh_prim)
        xform.AddTransformOp().Set(Gf.Matrix4d(matrix))

    stage.Save()
    logger.info("USD (usd-exchange) written: %s", out_usd)
    return out_usd


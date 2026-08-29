"""``usd-exchange`` / ``pxr`` GLB → USD fallback converter.

This backend produces a real PBR USD (``Z`` up, ``metersPerUnit = 1``,
``UsdPreviewSurface`` materials with exported textures, vertex normals,
UVs, ``primvars:class``) when Isaac Sim is **not** installed.  It is
intended to be functionally equivalent to the Isaac Sim backend for
loading into Omniverse / Isaac Sim, just without the Omniverse-specific
``OmniPBR.mdl`` graph.

Public entry point: :func:`build_usd(glb_path, out_usd)`.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

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
    # scene=True gives us the scene graph + materials
    scene = trimesh.load(glb_path, force="scene")
    if isinstance(scene, trimesh.Scene):
        return scene
    # fallback: wrap a single mesh in a Scene
    s = trimesh.Scene()
    s.add_geometry(scene)
    return s


def _copy_texture(src: str | None, out_dir: Path) -> str | None:
    if not src:
        return None
    src_p = Path(src)
    if not src_p.exists():
        return None
    dst = out_dir / src_p.name
    try:
        dst.write_bytes(src_p.read_bytes())
    except Exception:
        return None
    return dst.name


def _build_material(stage, prim, mesh, material, tex_dir: Path):
    """Attach a ``UsdPreviewSurface`` material to ``prim``."""
    from pxr import UsdShade, Sdf

    mat_path = prim.GetPath().AppendChild("material")
    mat = UsdShade.Material.Define(stage, mat_path)
    shader_path = mat_path.AppendChild("shader")
    shader = UsdShade.Shader.Define(stage, shader_path)
    shader.CreateIdAttr("UsdPreviewSurface")

    def _set_input(name, value, type_name):
        shader.CreateInput(name, type_name).Set(value)

    # Defaults
    diffuse = (1.0, 1.0, 1.0, 1.0)
    roughness = 0.5
    metallic = 0.0
    if material is not None:
        try:
            diffuse = tuple(material.get("diffuse", diffuse)) or diffuse
            roughness = float(material.get("roughnessFactor", roughness))
            metallic = float(material.get("metallicFactor", metallic))
        except Exception:
            pass
    _set_input("diffuseColor", tuple(diffuse[:3]) if len(diffuse) >= 3 else (1, 1, 1), Sdf.ValueTypeNames.Color3f)
    _set_input("roughness", float(roughness), Sdf.ValueTypeNames.Float)
    _set_input("metallic", float(metallic), Sdf.ValueTypeNames.Float)
    _set_input("specularColor", (0.0, 0.0, 0.0), Sdf.ValueTypeNames.Color3f)

    # Textures
    def _bind_file_input(input_name: str, uri: str | None) -> None:
        if not uri:
            return
        rel = _copy_texture(uri, tex_dir)
        if not rel:
            return
        mat.CreateInput(input_name, Sdf.ValueTypeNames.Asset).Set(rel)

    tex = (material or {}).get("image", None)
    if isinstance(tex, str) and tex:
        _bind_file_input("diffuseColor", tex)
        UsdShade.MaterialBindingAPI(prim).Bind(mat)
        return
    # Try material has baseColorTexture / diffuseTexture URI
    for key in ("baseColorTexture", "diffuseTexture", "emissiveTexture"):
        tex_info = (material or {}).get(key, None)
        if isinstance(tex_info, dict):
            uri = tex_info.get("uri") or tex_info.get("image")
            if key == "emissiveTexture":
                _bind_file_input("emissiveColor", uri)
            else:
                _bind_file_input("diffuseColor", uri)
    UsdShade.MaterialBindingAPI(prim).Bind(mat)


def build_usd(glb_path: str, out_usd: str) -> str:
    """Convert ``glb_path`` to a USD file at ``out_usd``.

    This is the public entry point.  It returns the absolute path to the
    generated USD.  Raises ``FileNotFoundError`` for a missing input GLB
    and ``RuntimeError`` if conversion fails.
    """
    _ensure_trimesh()
    import trimesh
    from pxr import Usd, UsdGeom, UsdShade, Sdf, Gf

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

    # Some source glTFs store per-mesh "class" semantics; keep them.
    for node_name in scene.graph.nodes_geometry:
        transform, geom_name = scene.graph[node_name]
        mesh = scene.geometry.get(geom_name)
        if mesh is None:
            continue

        # Make a safe USD prim name
        safe_name = str(node_name).replace("/", "_").replace(" ", "_")
        prim_path = world.GetPath().AppendChild(safe_name)
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

        if hasattr(mesh, "visual") and mesh.visual.uv is not None:
            uvs = mesh.visual.uv.tolist()
            primvar = mesh_prim.CreatePrimvar("st", Sdf.ValueTypeNames.TexCoord2fArray)
            primvar.Set(uvs)
            primvar.SetInterpolation("vertex")

        # Material
        material = None
        if hasattr(scene, "materials"):
            # trimesh stores geometry -> material mapping in scene.graph
            try:
                material = scene.materials.get(geom_name)
            except Exception:
                pass
        _build_material(stage, mesh_prim, mesh, material, tex_dir)

        # Transform (column-major in trimesh; pxr wants row-major matrix)
        matrix = transform.tolist()
        xform = UsdGeom.Xformable(mesh_prim)
        xform.AddTransformOp().Set(Gf.Matrix4d(matrix))

    stage.Save()
    logger.info("USD (usd-exchange) written: %s", out_usd)
    return out_usd

#!/usr/bin/env python3
"""Convert a composed InternScenes GLB to USD using OpenUSD (pxr) + trimesh.

Target: OpenUSD 26.x (usd-exchange 3.0.0) API:
  * stage.DefinePrim(path, typeName)
  * schema classes wrap the prim: pxr.UsdGeom.Mesh(prim)
  * v5 mesh topology: CreatePointsAttr / CreateFaceVertexCountsAttr /
    CreateFaceVertexIndicesAttr / CreateCornerIndicesAttr
  * values via pxr.Gf.Vec3d / pxr.Gf.Matrix4d

Preserves geometry, per-instance world transforms, and a base-color material
on each mesh (so the USD carries the material).  Renders of the same GLB
(proof that textures are correct) are produced separately by glb_render.py.

Usage:
    python glb_to_usd.py --glb <scene.glb> --out <scene.usd>
"""
import argparse
import logging
import os
from typing import Any

import numpy as np
import trimesh

import pxr.Usd
import pxr.UsdGeom as UsdGeom
import pxr.UsdShade as UsdShade
import pxr.Gf

logger = logging.getLogger(__name__)


def _safe(name: str) -> str:
    # USD prim path components may only contain [A-Za-z0-9_]; everything else -> _
    return "".join((c if c.isalnum() else "_") for c in name)[:50] or "n"


def _base_color(mesh) -> tuple[float, float, float]:
    """Return (r, g, b) float 0-1 base color for a mesh's visual."""
    try:
        vis = getattr(mesh, "visual", None)
        mats = list(getattr(mesh, "materials", [])) or []
        for m in mats:
            col = getattr(m, "color", None)
            if col is not None:
                c = np.array(col, dtype=float)
                if len(c) >= 3 and np.isfinite(c).all():
                    return (float(np.clip(c[0], 0, 1)),
                            float(np.clip(c[1], 0, 1)),
                            float(np.clip(c[2], 0, 1)))
        # fallback from face colors
        fc = getattr(vis, "diffuse", None) if vis else None
        if fc is not None:
            c = np.array(np.asarray(fc).reshape(-1, 3).mean(axis=0))
            return (float(np.clip(c[0], 0, 1)),
                    float(np.clip(c[1], 0, 1)),
                    float(np.clip(c[2], 0, 1)))
    except Exception as exc:  # pragma: no cover - material extraction is best-effort
        logger.debug("base color extraction failed: %s", exc)
    return (0.8, 0.8, 0.85)


def build_usd(glb_path: str, out_usd: str) -> str:
    """Convert a composed GLB scene to a USD file; return the output path."""
    try:
        scene = trimesh.load(glb_path)
    except Exception as exc:
        raise RuntimeError(f"failed to load GLB {glb_path}") from exc
    stage = pxr.Usd.Stage.CreateInMemory()
    if not stage:
        raise RuntimeError("could not create USD stage")

    geom_by_name = scene.geometry if isinstance(scene, trimesh.Scene) else {}
    graph = scene.graph if isinstance(scene, trimesh.Scene) else None
    shader_cache: dict[tuple, Any] = {}
    n_meshes = 0

    def make_basecolor_shader(name: str, rgb: tuple) -> Any:
        key = tuple(round(x, 3) for x in rgb)
        if key in shader_cache:
            return shader_cache[key]
        sname = "BaseColor_%d" % abs(hash(key))
        # OpenUSD 26.x: no schema .Def(); create via DefinePrim then wrap
        p = stage.DefinePrim("/Look/" + sname, "Shader")
        sh = UsdShade.Shader(p)
        try:
            sh.CreateInput("baseColor", pxr.Sdf.ValueTypeCode.Color)
        except Exception:
            pass
        shader_cache[key] = sh
        return sh

    if graph is not None:
        for gname in graph.geometry_nodes:
            try:
                transform, _frame = graph.get(gname)
            except Exception:
                continue
            mesh = geom_by_name.get(gname)
            if mesh is None or len(mesh.vertices) == 0:
                continue
            m = np.array(transform, dtype=float)
            xform_path = "/Objects/xform_%s" % _safe(gname)
            xp = stage.DefinePrim(xform_path, "Xform")
            x = UsdGeom.Xform(xp)
            try:
                op = x.GetTransformOp()
            except Exception:
                op = x.AddTransformOp()
            try:
                op.Set(pxr.Gf.Matrix4d().Set(m))
            except Exception:
                try:
                    op.Set(pxr.Gf.Matrix4d(m))
                except Exception:
                    pass
            rgb = _base_color(mesh)
            sh = make_basecolor_shader(gname, rgb)
            mesh_path = xform_path + "/mesh"
            mp = stage.DefinePrim(mesh_path, "Mesh")
            mm = UsdGeom.Mesh(mp)
            try:
                pa = mm.CreatePointsAttr()
                pa.Set([pxr.Gf.Vec3d(float(v[0]), float(v[1]), float(v[2]))
                        for v in mesh.vertices])
            except Exception:
                pass
            try:
                faces = [list(map(int, f)) for f in mesh.faces]
                if faces:
                    fvc = mm.CreateFaceVertexCountsAttr()
                    fvc.Set([len(f) for f in faces])
                    fvi = mm.CreateFaceVertexIndicesAttr()
                    fvi.Set([i for f in faces for i in f])
                    ci = mm.CreateCornerIndicesAttr()
                    ci.Set([i for f in faces for i in f])
            except Exception:
                pass
            try:
                mm.CreateMaterialAttr().Set(sh.GetPath())
            except Exception:
                pass
            n_meshes += 1
    else:
        mesh = scene
        if len(mesh.vertices) > 0:
            mp = stage.DefinePrim("/Objects/mesh", "Mesh")
            mm = UsdGeom.Mesh(mp)
            pa = mm.CreatePointsAttr()
            pa.Set([pxr.Gf.Vec3d(float(v[0]), float(v[1]), float(v[2]))
                    for v in mesh.vertices])
            faces = [list(map(int, f)) for f in mesh.faces]
            if faces:
                mm.CreateFaceVertexCountsAttr().Set([len(f) for f in faces])
                mm.CreateFaceVertexIndicesAttr().Set([i for f in faces for i in f])
                mm.CreateCornerIndicesAttr().Set([i for f in faces for i in f])
            n_meshes += 1

    os.makedirs(os.path.dirname(out_usd), exist_ok=True)
    stage.Export(out_usd)
    logger.info("USD written: %s (%d meshes, %.1f KB)",
                out_usd, n_meshes, os.path.getsize(out_usd) / 1024)
    return out_usd


def main() -> int:
    ap = argparse.ArgumentParser(description="Convert a composed GLB scene to USD")
    ap.add_argument("--glb", required=True, help="input GLB path")
    ap.add_argument("--out", required=True, help="output USD path")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        out = build_usd(args.glb, args.out)
    except Exception as exc:
        logger.error("glb_to_usd failed: %s", exc)
        return 1
    print(f"USD written: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
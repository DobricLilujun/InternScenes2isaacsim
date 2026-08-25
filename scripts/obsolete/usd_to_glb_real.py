"""Convert the real Unitree Go2 USD (Isaac Sim asset) to GLB.
Uses OpenUSD UsdTransformable.GetLocalTransform() (composes all xform ops),
reads Mesh geometry. OpenUSD is Y-up; trimesh/Blender is Z-up -> rotate.
"""
import numpy as np
import pxr.Usd, pxr.UsdGeom
import trimesh

USD = "/tmp/unitree_model/Go2/usd/configuration/go2_description_base.usd"
OUT = "/home/ubadmin/projects/InternScenes2isaacsim/assets/go2_usd.glb"

stage = pxr.Usd.Stage.Open(USD)
t = 0.0  # default time code (this build has no UsdTime)

parts = []
n_mesh = 0
for prim in stage.Traverse():
    if prim.GetTypeName() != "Mesh":
        continue
    mesh = pxr.UsdGeom.Mesh(prim)
    if not mesh:
        continue
    # geometry
    try:
        pts = mesh.GetPointsAttr().Get(t)
        fvc = mesh.GetFaceVertexCountsAttr().Get(t)
        fvi = mesh.GetFaceVertexIndicesAttr().Get(t)
        if pts is None or fvc is None or fvi is None:
            continue
        points = np.array([[p[0], p[1], p[2]] for p in pts], dtype=np.float64)
        faces = []
        idx = 0
        for c in fvc:
            faces.append(fvi[idx:idx + c])
            idx += c
        faces = np.array(faces)
        if points.size == 0 or faces.size == 0:
            continue
    except Exception as e:
        print("geom err", prim.GetPath().pathString, e)
        continue
    # world transform (GetLocalTransformation = mesh-local -> world, Y-up)
    xf = pxr.UsdGeom.Xformable(prim)
    m = xf.GetLocalTransformation(t)
    M = np.array([[m[x][y] for y in range(4)] for x in range(4)],
                 dtype=np.float64)
    wp = points @ M[:3, :3].T + M[:3, 3]
    pc = wp.mean(axis=0)
    part = trimesh.Trimesh(vertices=wp, faces=faces, process=False)
    parts.append(part)
    n_mesh += 1
    print(f"  {prim.GetPath().pathString[:44]:44} "
          f"v={len(pts):6} c=({pc[0]:+.2f},{pc[1]:+.2f},{pc[2]:+.2f})")

if not parts:
    print("NO GEOMETRY")
    raise SystemExit(1)
scene = trimesh.util.concatenate(parts)
# OpenUSD Y-up -> trimesh/Blender Z-up (rotate -90 about X)
Rz = np.array([[1, 0, 0], [0, 0, -1], [0, 1, 0]], dtype=np.float64)
scene.vertices = scene.vertices @ Rz.T
scene.export(OUT, file_type="glb")
bb = scene.bounds
print(f"\nexported {OUT}")
print(f"parts: {n_mesh}  vertices: {len(scene.vertices)}")
print(f"bounds: {bb}")
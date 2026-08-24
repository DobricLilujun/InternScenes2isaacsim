"""Convert Go2 USD to GLB using RAW mesh points only (no transform).
The points may already be in an assembled pose. Tests the model shape.
"""
import numpy as np
import pxr.Usd, pxr.UsdGeom
import trimesh

USD = "/tmp/unitree_model/Go2/usd/configuration/go2_description_base.usd"
OUT = "/home/ubadmin/projects/InternScenes2isaacsim/assets/go2_raw.glb"

stage = pxr.Usd.Stage.Open(USD)
t = 0.0
parts = []
for prim in stage.Traverse():
    if prim.GetTypeName() != "Mesh":
        continue
    mesh = pxr.UsdGeom.Mesh(prim)
    if not mesh:
        continue
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
    except Exception:
        continue
    part = trimesh.Trimesh(vertices=points, faces=faces, process=False)
    parts.append(part)
    pc = points.mean(axis=0)
    print(f"  {prim.GetPath().pathString[:44]:44} v={len(pts):6} "
          f"rawcenter=({pc[0]:+.2f},{pc[1]:+.2f},{pc[2]:+.2f})")

scene = trimesh.util.concatenate(parts)
# Y-up -> Z-up
Rz = np.array([[1, 0, 0], [0, 0, -1], [0, 1, 0]], dtype=np.float64)
scene.vertices = scene.vertices @ Rz.T
scene.export(OUT, file_type="glb")
bb = scene.bounds
print(f"\nexported {OUT}")
print(f"parts: {len(parts)}  verts: {len(scene.vertices)}")
print(f"bounds: {bb}")
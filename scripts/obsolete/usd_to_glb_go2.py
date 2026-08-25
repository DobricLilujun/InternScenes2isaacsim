import numpy as np, os
import pxr.Usd, pxr.UsdGeom
import trimesh

USD = "/tmp/unitree_model/Go2/usd/configuration/go2_description_base.usd"
stage = pxr.Usd.Stage.Open(USD)
meshes = [p for p in stage.Traverse() if p.GetTypeName() == "Mesh"]
print("meshes:", len(meshes))


def read_xform_op(prim):
    try:
        if prim is None or not prim.IsValid() or not prim.IsDefined():
            return None
        if prim.GetTypeName() != "Xform":
            return None
        xf = pxr.UsdGeom.Xform(prim)
        if xf is None or not xf.IsDefined():
            return None
        op = xf.GetTransformOp()
        if op is None:
            return None
        t = op.Get()
        if t is None:
            return None
        arr = np.array(t, dtype=float)
        return arr if arr.shape == (4, 4) else None
    except Exception:
        return None


def world_transform(prim):
    m = np.eye(4)
    local = read_xform_op(prim)
    if local is not None:
        m = local
    p = prim
    for _ in range(64):
        try:
            parent = p.GetParent()
        except Exception:
            break
        if parent is None:
            break
        if not parent.IsValid() or not parent.IsDefined():
            break
        t = read_xform_op(parent)
        if t is not None:
            m = t @ m
        p = parent
    return m


scene = trimesh.Scene()
n_ok = 0
for i, p in enumerate(meshes):
    try:
        m = pxr.UsdGeom.Mesh(p)
        pts = m.GetPointsAttr().Get()
        fv = m.GetFaceVertexIndicesAttr().Get()
        if not pts or not fv:
            continue
        pts = np.array(pts, dtype=float)
        fv = np.array(fv, dtype=np.int64)
        faces = None
        try:
            fvc = m.GetFaceVertexCountsAttr().Get()
            if fvc:
                fl = []
                start = 0
                for c in fvc:
                    face = fv[start:start + c]
                    if len(face) == 3:
                        fl.append(face)
                    start += c
                if fl:
                    faces = np.array(fl, dtype=np.int64)
        except Exception:
            pass
        if faces is None or len(faces) == 0:
            faces = fv.reshape(-1, 3)
        W = world_transform(p)
        mesh = trimesh.Trimesh(vertices=pts, faces=faces, process=False)
        scene.add_geometry(mesh, geom_name=f"mesh{i}", transform=W)
        n_ok += 1
    except Exception as e:
        print(f"  [{i}] err: {e}")

print("added", n_ok, "meshes")
out = "/home/ubadmin/projects/InternScenes2isaacsim/assets/go2.glb"
os.makedirs(os.path.dirname(out), exist_ok=True)
try:
    scene.export(out)
    print("exported:", out, "size:", os.path.getsize(out))
except Exception as e:
    print("export err:", e)
"""InternScenes scene composer (ported locally; paths configurable).

Adapted from InternScenes/InternScenes/InternScenes_Real2Sim/compose_scenes.py.
The original hard-coded `BASE_DIR = Path(__file__).parents[2]` and expected the
InternScenes checkout layout; here everything is resolved from this project
root so the pipeline runs standalone on this machine.
"""
import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import trimesh
from trimesh.transformations import rotation_matrix

# --- paths (relative to project root: <root>/src/internscenes/compose.py) ---
ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.environ.get("INTERN_DATA_DIR", ROOT / "data"))
ASSET_LIBRARY = DATA_DIR / "asset_library"
LAYOUT_DIR = DATA_DIR / "Layout_info"
OUTPUT_ROOT = Path(os.environ.get("INTERN_OUTPUT_DIR", ROOT / "output"))
COMPOSED_DIR = OUTPUT_ROOT / "composed"


class AssetMeshLoader:
    def __init__(self):
        self.asset_dir = ASSET_LIBRARY
        self.obja_uid_2_rotation = json.load(open(ASSET_LIBRARY / "uid_2_angle.json"))
        self.pm_uid_2_origin_cate = json.load(open(ASSET_LIBRARY / "uid_2_origin_cate.json"))

    def get_mesh_path(self, uid):
        if uid.startswith("objaverse/") or uid.startswith("objaverse_old/"):
            return str(ASSET_LIBRARY / f"{uid}.glb")
        if uid.startswith("partnet_mobility"):
            return str(ASSET_LIBRARY / uid / "whole.glb")
        for lib in ("3D-FUTURE-model", "hssd-models", "gen_assets", "gr100"):
            if uid.startswith(lib):
                return str(ASSET_LIBRARY / f"{uid}.glb")
        raise ValueError(f"Invalid uid: {uid}")

    def resolve_mesh_path(self, uid):
        """Return the on-disk path for ``uid``, or None if not found.

        Tries the canonical path first, then common layout variants
        (e.g. ``data/asset_library/<lib>/<lib>/<uid>.glb`` for asset
        libraries that were extracted from a multi-part tar with a
        top-level directory of the same name).
        """
        try:
            primary = Path(self.get_mesh_path(uid))
            if primary.exists():
                return primary
        except ValueError:
            return None
        # Fallback: <lib>/<lib>/<uid>.glb (matches the objaverse tar extract)
        first = uid.split("/", 1)[0]
        for nested in (
            ASSET_LIBRARY / first / first / f"{Path(uid).name}.glb",
        ):
            if nested.exists():
                return nested
        return None

    def load_init_mesh(self, uid, use_texture=False):
        path = self.resolve_mesh_path(uid)
        if path is None:
            raise FileNotFoundError(self.get_mesh_path(uid))
        return trimesh.load(path, force="mesh") if not use_texture else trimesh.load(path)

    def load_init_rotation(self, uid):
        if uid.startswith("objaverse/"):
            rot = self.obja_uid_2_rotation[uid.split("objaverse/")[-1]] / 180.0 * np.pi
            return rotation_matrix(rot, [0, 0, 1]) @ rotation_matrix(0.5 * np.pi, [0, 0, 1]) \
                @ rotation_matrix(0.5 * np.pi, [1, 0, 0])
        if uid.startswith("objaverse_old/"):
            return rotation_matrix(0.5 * np.pi, [0, 0, 1]) @ rotation_matrix(0.5 * np.pi, [1, 0, 0])
        if uid.startswith("partnet_mobility"):
            transform = rotation_matrix(np.pi, [0, 0, 1]) @ rotation_matrix(0.5 * np.pi, [1, 0, 0])
            if self.pm_uid_2_origin_cate.get(uid) in ("Pen", "Remote", "Phone"):
                r1 = rotation_matrix(np.pi, [0, 0, 1])
                r2 = rotation_matrix(np.pi / 2, [0, 1, 0])
                transform = r2 @ r1 @ transform
            return transform
        for lib in ("3D-FUTURE-model", "hssd-models", "gen_assets", "gr100"):
            if uid.startswith(lib):
                return rotation_matrix(0.5 * np.pi, [0, 0, 1]) @ rotation_matrix(0.5 * np.pi, [1, 0, 0])
        raise ValueError(f"Invalid uid: {uid}")

    def load_canonical_mesh(self, uid, use_texture=False):
        mesh = self.load_init_mesh(uid, use_texture)
        transform = self.load_init_rotation(uid)
        centroid = mesh.bounding_box.centroid
        mesh.apply_translation(-centroid)
        mesh.apply_transform(transform)
        return mesh


class SceneComposer:
    def __init__(self, asset_mesh_loader=None):
        self.asset_mesh_loader = asset_mesh_loader or AssetMeshLoader()
        self.composed_dir = COMPOSED_DIR

    def get_scale_transform_from_rules(self, mesh_size, instance_info, bbox_key="bbox"):
        cat = instance_info["category"]
        target_size = np.array(instance_info[bbox_key][3:6])
        if cat not in ("carpet", "clothes"):
            scale = target_size / mesh_size
            return np.diag([scale[0], scale[1], scale[2], 1])
        if cat == "carpet":
            scale_factors = target_size / mesh_size
            if target_size[2] / target_size[0] > 150 or target_size[2] / target_size[1] > 150:
                if target_size[2] / target_size[0] > target_size[2] / target_size[1]:
                    rot = rotation_matrix(0.5 * np.pi, [0, 1, 0])
                    target_size = np.array([target_size[2], target_size[0], target_size[1]])
                    scale_factors = target_size / mesh_size
                    m = np.diag([scale_factors[0], scale_factors[1], scale_factors[2] / 100.0, 1])
                    return m @ rot
                else:
                    rot = rotation_matrix(0.5 * np.pi, [1, 0, 0])
                    target_size = np.array([target_size[0], target_size[2], target_size[1]])
                    scale_factors = target_size / mesh_size
                    m = np.diag([scale_factors[0], scale_factors[1], scale_factors[2] / 100.0, 1])
                    return m @ rot
            return np.diag([scale_factors[0], scale_factors[1], scale_factors[2] / 100.0, 1])
        if cat == "clothes":
            scale = target_size / mesh_size
            s = min(scale)
            return np.diag([s, s, s, 1])
        return np.diag([1, 1, 1, 1])

    def compose_scene_from_instance_infos(self, infos, output_glb, use_texture,
                                         bbox_key="bbox",
                                         missing_report_path=None,
                                         verbose_missing=True):
        scene = trimesh.scene.Scene()
        lock = threading.Lock()
        missing = []

        def process_instance(index):
            instance = infos[index]
            uid = instance["model_uid"]
            if uid == "":
                return
            try:
                mesh = self.asset_mesh_loader.load_canonical_mesh(uid, use_texture)
            except FileNotFoundError as e:
                if verbose_missing:
                    print(f"  MISSING asset {uid}: {e}")
                with lock:
                    missing.append({"uid": uid, "path": str(e)})
                return
            geometry_name = instance["category"] + "@" + uid
            transform = np.eye(4)
            box = instance[bbox_key]
            scale = self.get_scale_transform_from_rules(mesh.bounding_box.extents, instance, bbox_key)
            transform = scale @ transform
            euler = np.array(box[6:9])
            rot = trimesh.transformations.euler_matrix(euler[0], euler[1], euler[2], axes="rzxy")
            transform = rot @ transform
            transform[:3, 3] = np.array(box[0:3])
            transform = trimesh.transformations.rotation_matrix(-np.pi / 2, [1, 0, 0]) @ transform
            name = str(index) + "_" + geometry_name
            with lock:
                scene.graph.update(frame_to=name, matrix=transform)
                if isinstance(mesh, trimesh.Scene):
                    for gname, part in mesh.geometry.items():
                        nodes = mesh.graph.geometry_nodes.get(gname, [])
                        for i, node in enumerate(nodes):
                            internal, _ = mesh.graph.get(node)
                            scene.add_geometry(part, geom_name=f"{name}_{gname}_{i}",
                                              transform=internal, parent_node_name=name)
                else:
                    scene.add_geometry(mesh, geom_name=name + "_geom", parent_node_name=name)

        with ThreadPoolExecutor(max_workers=8) as ex:
            futs = [ex.submit(process_instance, i) for i in range(len(infos))]
            for f in futs:
                try:
                    f.result()
                except Exception as e:
                    print(f"  error: {e}")

        if not use_texture:
            from trimesh.visual.texture import TextureVisuals
            for g in scene.geometry.values():
                g.visual = TextureVisuals()
        if output_glb:
            Path(output_glb).parent.mkdir(parents=True, exist_ok=True)
            trimesh.exchange.export.export_mesh(scene, output_glb)
        return scene, missing

    def compose_one_scene(self, scene_name, use_texture=True,
                          add_floor=True, add_wall=True, add_ceiling=True,
                          write_missing_report=True, verbose_missing=True):
        layout = LAYOUT_DIR / scene_name / "layout.json"
        out_glb = COMPOSED_DIR / scene_name / "glb_scene.glb"
        infos = json.load(open(layout))
        # Decide where the missing-assets report lives.  Mirror the
        # scene_info convention: ``<dataset>_<id>_missing.json`` under
        # ``output/info/`` so the auto-fill downloader can read it.
        slug = scene_name.replace("/", "_")
        missing_report = OUTPUT_ROOT / "info" / f"{slug}_missing.json"
        scene, missing = self.compose_scene_from_instance_infos(
            infos, None, use_texture, "bbox",
            missing_report_path=str(missing_report),
            verbose_missing=verbose_missing,
        )
        for part in (("floor", add_floor), ("wall", add_wall), ("ceiling", add_ceiling)):
            try:
                p = LAYOUT_DIR / scene_name / "StructureMesh" / f"{part[0]}.glb"
                if p.exists():
                    scene.add_geometry(trimesh.load(p), geom_name=f"{part[0]}")
                else:
                    print(f"  no {part[0]}.glb for {scene_name}")
            except Exception as e:
                print(f"  error adding {part[0]}: {e}")
        Path(out_glb).parent.mkdir(parents=True, exist_ok=True)
        trimesh.exchange.export.export_mesh(scene, out_glb)
        if write_missing_report and missing:
            missing_report.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "scene_id": scene_name,
                "num_missing": len(missing),
                "missing": missing,
            }
            with missing_report.open("w", encoding="utf-8") as fh:
                json.dump(payload, fh, ensure_ascii=False, indent=2)
        print(f"Composed {scene_name} -> {out_glb} (missing assets: {len(missing)})")
        return out_glb, missing


if __name__ == "__main__":
    import sys
    sn = sys.argv[1] if len(sys.argv) > 1 else "scannet/scene0000_00"
    glb, miss = SceneComposer().compose_one_scene(sn)
    print("OK", glb, "missing", miss)
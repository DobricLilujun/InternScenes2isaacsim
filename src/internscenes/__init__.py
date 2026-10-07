"""InternScenes2isaacsim: compose, render and convert InternScenes layouts to Isaac Sim USD.

Public API surface (intended for notebooks and external callers):

    from internscenes import pipeline

    # Run the whole pipeline for one scene:
    status = pipeline.run_scene("scannet/scene0001_00")

    # Or run individual stages:
    pipeline.stage_compose(scene_id)
    pipeline.stage_render(scene_id)
    pipeline.stage_topdown(scene_id)
    pipeline.stage_info(scene_id)
    pipeline.stage_usd(scene_id)
    pipeline.assemble_normalized(scene_id)

    # Utilities:
    pipeline.resolve_scenes(n=10, seed=0, datasets=["scannet"])
    pipeline.scene_inventory()
"""
from __future__ import annotations

# Keep lazy imports for the public modules so that ``import internscenes`` in
# Blender's Python (which lacks optional dependencies such as trimesh and
# omni.*) does not fail when only ``internscenes.render`` is needed.
from . import cli, pipeline

__all__ = [
    "cli",
    "pipeline",
]

# Helper so callers can still do ``from internscenes import compose`` etc.
# without eagerly importing everything at package load time.
_submodules = [
    "compose",
    "download",
    "glb_to_usd",
    "place_go2",
    "render",
    "render_multi",
    "sampler",
    "scene_info",
    "topdown",
    # SAGE-Bench scene-graph modules
    "coordinate",
    "relations",
    "scene_graph",
    "vlm_annotate",
    "evaluate_graph",
]


def __getattr__(name: str):
    if name in _submodules:
        import importlib
        mod = importlib.import_module(f"internscenes.{name}")
        globals()[name] = mod
        return mod
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

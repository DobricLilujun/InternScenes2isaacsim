"""High-fidelity GLB → USD converter using Isaac Sim's ``omni.kit.asset_converter``.

This is the **primary** backend of the InternScenes → Isaac Sim pipeline
(``glb_to_usd`` calls into it when Isaac Sim is importable).  It mirrors
the official InternScenes Real2Sim release
(``InternScenes/InternScenes_Real2Sim/glb2usd.py``): the resulting USD
contains the full ``OmniPBR.mdl`` material graph the InternScenes
``trajectory_tools`` renderer expects, with glTF PBR extensions,
multi-UV (``KHR_materials_variants``), and mesh compression handled by
Omniverse's asset converter.

The dispatcher (``glb_to_usd.build_usd``) is the public entry point;
this module is intentionally importable so the dispatcher can avoid
launching ``SimulationApp`` when Isaac Sim is not installed.

Public entry point: :func:`convert(in_file, out_file, load_materials=True)`.
"""
from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger(__name__)


async def convert(in_file: str, out_file: str, load_materials: bool = True) -> bool:
    """Convert one GLB to USD via ``omni.kit.asset_converter``.

    Requires ``isaacsim`` and ``omni.kit.asset_converter`` to be importable,
    and a ``SimulationApp`` instance to be running in the same process.
    The caller (the ``glb_to_usd`` dispatcher) owns the ``SimulationApp``
    lifecycle.

    Returns True only when the USD is actually written to ``out_file`` AND
    the converter task reports success.  Returns False (and logs) when the
    source GLB is missing, the converter reports an error status, or the
    output file is not produced.
    """
    import os
    if not os.path.isfile(in_file):
        logger.error("convert: source GLB does not exist: %s", in_file)
        return False

    import omni.kit.asset_converter  # noqa: F401  (Isaac Sim)

    def progress_callback(progress, total_steps):  # noqa: ARG001
        pass

    ctx = omni.kit.asset_converter.AssetConverterContext()
    ctx.ignore_materials = not load_materials
    ctx.use_meter_as_world_unit = True
    instance = omni.kit.asset_converter.get_instance()
    task = instance.create_converter_task(
        in_file, out_file, progress_callback, ctx
    )
    while True:
        success = await task.wait_until_finished()
        if not success:
            await asyncio.sleep(0.1)
        else:
            # ``task.wait_until_finished()`` returns True even when the
            # underlying conversion status is an error.  Treat as success
            # only when the output USD actually exists and is non-empty.
            return bool(success) and os.path.isfile(out_file) and os.path.getsize(out_file) > 0


def set_usd_prim_orientation(usd_path: str, prim_path: str = "/World",
                             euler_xyz_deg=(90.0, 0.0, 0.0)) -> None:
    """Rotate ``prim_path`` so the stage is Z-up (matches the official
    InternScenes Real2Sim release's ``real2sim_utils.usd_tools.set_usd_prim_orientation``).
    """
    from pxr import Usd, UsdGeom, Gf  # Isaac Sim ships pxr
    try:
        from scipy.spatial.transform import Rotation as R
    except Exception:  # pragma: no cover
        R = None

    stage = Usd.Stage.Open(usd_path)
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.z)
    prim = stage.GetPrimAtPath(prim_path)
    if not prim.IsValid():
        stage.Save()
        return
    for attr in prim.GetAttributes():
        name = attr.GetName()
        if "orient" in name:
            if R is None:
                continue
            quat = R.from_euler("xyz", list(euler_xyz_deg), degrees=True).as_quat()
            # scipy: xyzw -> USD Gf.Quatf: real-first (w, x, y, z)
            attr.Set(Gf.Quatf(float(quat[3]), float(quat[0]),
                              float(quat[1]), float(quat[2])))
    stage.Save()


def convert_and_orient(in_file: str, out_file: str, load_materials: bool = True) -> bool:
    """Run :func:`convert` then apply the official Z-up orientation fix."""
    ok = asyncio.get_event_loop().run_until_complete(
        convert(in_file, out_file, load_materials=load_materials)
    )
    if ok:
        try:
            set_usd_prim_orientation(out_file)
        except Exception as exc:  # pragma: no cover
            logger.warning("set_usd_prim_orientation failed: %s", exc)
    return ok

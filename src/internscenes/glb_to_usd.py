"""Convert a composed InternScenes GLB to USD (auto backend selection).

This is the *front door* for the InternScenes → Isaac Sim USD conversion.  It
is a thin dispatcher that:

1. Uses the **Isaac Sim** backend (``omni.kit.asset_converter``) by default —
   the same path the official InternScenes Real2Sim release takes
   (``InternScenes/InternScenes_Real2Sim/glb2usd.py``).  This is the
   highest-fidelity conversion available: it understands the full glTF PBR
   extension set, multi-UV (``KHR_materials_variants``), glTF mesh
   compression, etc., and emits the ``OmniPBR.mdl`` graph the
   ``trajectory_tools`` renderer expects.
2. Falls back to the **``usd-exchange`` / ``pxr``** backend
   (``glb_to_usd_fallback.py``) when Isaac Sim is not installed.
   This backend also produces a real PBR USD (``Z`` up,
   ``metersPerUnit = 1``, ``UsdPreviewSurface`` materials with exported
   textures, vertex normals, UVs, ``primvars:class``).

The default output location follows the **normalized** layout:
``output/normalized/<dataset>_<id>/scene.usd``.  Use ``--out`` to override.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

# Where the converter writes by default (the normalized per-scene layout).
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DEFAULT_NORMALIZED = ROOT / "output" / "normalized"

# A single SimulationApp instance per process; closed at script exit.
_kit = None  # type: ignore[var-annotated]


# ---------------------------------------------------------------------------
# Backend selection
# ---------------------------------------------------------------------------
def _isaac_available() -> bool:
    """True when an Isaac Sim Python environment is importable."""
    try:
        from isaacsim import SimulationApp  # noqa: F401
        return True
    except Exception:
        return False


def _normalized_path_for(glb_path: str) -> Path:
    """Map a composed GLB to the canonical normalized output path.

    Example: ``output/composed/scannet/scene0001_00/glb_scene.glb``
             -> ``output/normalized/scannet_scene0001_00/scene.usd``.
    """
    p = Path(glb_path).resolve()
    try:
        rel = p.relative_to(ROOT / "output" / "composed")
    except ValueError:
        return DEFAULT_NORMALIZED / p.stem / "scene.usd"
    parts = rel.parts[:-1]  # drop the trailing "glb_scene.glb"
    if not parts:
        return DEFAULT_NORMALIZED / p.stem / "scene.usd"
    if len(parts) >= 2:
        slug = "_".join(parts[:2]) + (
            "_" + "_".join(parts[2:]) if len(parts) > 2 else ""
        )
    else:
        slug = parts[0]
    return DEFAULT_NORMALIZED / slug / "scene.usd"


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------
def build_usd_isaac(glb_path: str, out_usd: str) -> str:
    """High-fidelity GLB → USD via Isaac Sim's ``omni.kit.asset_converter``."""
    global _kit
    if not os.path.isfile(glb_path):
        raise FileNotFoundError(f"GLB not found: {glb_path}")

    from .glb_to_usd_isaac import convert_and_orient  # type: ignore
    from isaacsim import SimulationApp  # noqa: F401

    out_usd = os.path.abspath(out_usd)
    os.makedirs(os.path.dirname(out_usd), exist_ok=True)

    if _kit is None:
        _kit = SimulationApp()
    ok = convert_and_orient(glb_path, out_usd, load_materials=True)
    if not ok or not os.path.isfile(out_usd) or os.path.getsize(out_usd) == 0:
        # Best-effort cleanup of any zero-byte file the converter may have left.
        try:
            if os.path.isfile(out_usd) and os.path.getsize(out_usd) == 0:
                os.remove(out_usd)
        except OSError:  # pragma: no cover
            pass
        raise RuntimeError(f"omni.kit.asset_converter failed for {glb_path}")
    logger.info("USD (isaacsim) written: %s", out_usd)
    return out_usd


def build_usd_fallback(glb_path: str, out_usd: str) -> str:
    """``usd-exchange`` / ``pxr`` GLB → USD path (no Isaac Sim required)."""
    from .glb_to_usd_fallback import build_usd as _impl  # type: ignore
    return _impl(glb_path, out_usd)


def build_usd(glb_path: str, out_usd: str | None = None) -> str:
    """Convert a composed GLB scene to a USD file; return the output path.

    This is the *only* function the rest of the pipeline calls.  It picks
    the Isaac Sim path when available, otherwise the ``usd-exchange``
    fallback.  When ``out_usd`` is None, it lands in the normalized
    output layout (``output/normalized/<ds>_<id>/scene.usd``).

    Raises
    ------
    FileNotFoundError
        if ``glb_path`` does not exist (we check up front so the
        Isaac Sim backend doesn't silently create an empty directory).
    """
    if not os.path.isfile(glb_path):
        raise FileNotFoundError(f"GLB not found: {glb_path}")

    if out_usd is None:
        out_usd = str(_normalized_path_for(glb_path))
    out_usd = os.path.abspath(out_usd)

    if _isaac_available():
        try:
            return build_usd_isaac(glb_path, out_usd)
        except Exception as exc:  # pragma: no cover - keep going
            logger.warning(
                "Isaac Sim backend failed (%s); falling back to usd-exchange", exc
            )
    return build_usd_fallback(glb_path, out_usd)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(
        description="Convert a composed GLB scene to USD "
                    "(default: isaacsim if available, else usd-exchange)"
    )
    ap.add_argument("--glb", required=True, help="input GLB path")
    ap.add_argument(
        "--out",
        default=None,
        help="output USD path (default: output/normalized/<ds>_<id>/scene.usd)",
    )
    ap.add_argument(
        "--backend",
        choices=("auto", "isaac", "usd-exchange"),
        default="auto",
        help="force a backend (default: auto = isaac if installed)",
    )
    args = ap.parse_args()
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )

    out = args.out or str(_normalized_path_for(args.glb))
    try:
        if args.backend == "isaac":
            if not _isaac_available():
                logger.error("isaacsim is not installed in this environment")
                return 2
            out_path = build_usd_isaac(args.glb, out)
        elif args.backend == "usd-exchange":
            out_path = build_usd_fallback(args.glb, out)
        else:
            out_path = build_usd(args.glb, out)
    except Exception as exc:
        logger.error("glb_to_usd failed: %s", exc)
        return 1
    print(f"USD written: {out_path}")
    if _kit is not None:
        try:
            _kit.close()
        except Exception:  # pragma: no cover
            pass
        globals()["_kit"] = None
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

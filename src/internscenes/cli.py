#!/usr/bin/env python3
"""Command-line front-ends for the InternScenes -> Isaac Sim pipeline.

Thin wrappers around the batch stages so each operation can be run individually
from a shell:

    internscenes render <scene> [--engine EEVEE|CYCLES]
    internscenes topdown <scene>
    internscenes info   <scene> [--out PATH]
    internscenes batch  [-n 50] [--seed 0] [--resume]

Installed as the ``internscenes`` console script (see pyproject.toml).
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]        # project root
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src" / "internscenes"))

import batch_pipeline as batch  # noqa: E402

logger = logging.getLogger("internscenes")


def _paths(scene_id: str) -> dict:
    return batch._paths(scene_id)


def _blender() -> str:
    return os.environ.get("BLENDER",
                          "/home/ubadmin/tools/blender/blender-5.1.2-linux-x64/blender")


def _venv_python() -> str:
    return os.environ.get("VENV_PY", str(ROOT / ".venv311" / "bin" / "python"))


def cmd_render(scene_id: str, engine: str = "EEVEE") -> int:
    """Compose (if needed) and render the perspective PNG for one scene."""
    paths = _paths(scene_id)
    logger.info("render: %s", scene_id)
    if not paths["composed"].exists():
        logger.info("composed GLB missing -> composing first")
        if not batch.stage_compose(scene_id, paths):
            logger.error("compose failed")
            return 1
    return 0 if batch.stage_render(scene_id, paths, _blender()) else 1


def cmd_topdown(scene_id: str) -> int:
    """Produce the 2D top-down projection for one scene."""
    paths = _paths(scene_id)
    logger.info("topdown: %s", scene_id)
    return 0 if batch.stage_topdown(scene_id, paths, _venv_python()) else 1


def cmd_info(scene_id: str, out: str | None = None) -> int:
    """Export the scene metadata JSON for one scene."""
    paths = _paths(scene_id)
    if out:
        paths["info"] = Path(out)
    logger.info("info: %s", scene_id)
    return 0 if batch.stage_info(scene_id, paths) else 1


def cmd_batch(n: int, seed: int, resume: bool, datasets: str) -> int:
    """Run the full batch pipeline."""
    # batch_pipeline.main reads its own argv; build it from the CLI args
    import sys as _sys
    _sys.argv = [
        "batch_pipeline.py", "-n", str(n), "--seed", str(seed),
    ]
    if resume:
        _sys.argv.append("--resume")
    if datasets:
        _sys.argv += ["--datasets", datasets]
    return batch.main()


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="internscenes",
                                 description="InternScenes -> Isaac Sim pipeline")
    ap.add_argument("--verbose", "-v", action="store_true")
    sub = ap.add_subparsers(dest="command", required=True)

    p = sub.add_parser("render", help="render a perspective PNG (Blender)")
    p.add_argument("scene")
    p.add_argument("--engine", default="EEVEE")
    p.set_defaults(func=cmd_render)

    p = sub.add_parser("topdown", help="render a 2D top-down projection")
    p.add_argument("scene")
    p.set_defaults(func=cmd_topdown)

    p = sub.add_parser("info", help="export scene metadata JSON")
    p.add_argument("scene")
    p.add_argument("--out")
    p.set_defaults(func=cmd_info)

    p = sub.add_parser("batch", help="run the full batch pipeline")
    p.add_argument("-n", type=int, default=50)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--resume", action="store_true")
    p.add_argument("--datasets", default="")
    p.set_defaults(func=cmd_batch)

    return ap


def main() -> int:
    args = build_parser().parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    return args.func(**{k: v for k, v in vars(args).items() if k != "command"})


if __name__ == "__main__":
    raise SystemExit(main())
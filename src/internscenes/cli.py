#!/usr/bin/env python3
"""Unified CLI for the InternScenes -> Isaac Sim pipeline.

After ``pip install -e .`` the command ``internscenes`` is available:

    # random batch: N scenes per dataset
    internscenes run -n 50 --seed 0 --auto-fill

    # specific scene(s)
    internscenes run --scene scannet/scene0001_00
    internscenes run --scene scannet/scene0001_00 --scene scannet/scene0002_00

    # dataset filter + random sample
    internscenes run -n 10 --datasets scannet --seed 0

Legacy single-stage commands remain available:

    internscenes render <scene> [--engine EEVEE|CYCLES]
    internscenes topdown <scene>
    internscenes info   <scene> [--out PATH]
    internscenes batch  [-n 50] [--seed 0] [--resume]
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path

from . import pipeline
from . import questions as _questions

logger = logging.getLogger("internscenes")


def cmd_run(
    n: int,
    seed: int,
    datasets: list[str] | None,
    scene_ids: list[str] | None,
    resume: bool,
    auto_fill: bool,
    auto_fill_once: bool,
    skip_render: bool,
    skip_topdown: bool,
    manifest: str,
    log: str,
    min_room_extent_m: float = 0.0,
) -> int:
    """Run the full pipeline (compose → render → topdown → info → normalize)."""
    manifest_path = Path(manifest)
    log_path = Path(log)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.FileHandler(log_path), logging.StreamHandler()],
    )

    # resolve scene list
    if scene_ids:
        scenes = pipeline.resolve_scenes(
            scene_ids=scene_ids, min_room_extent_m=min_room_extent_m
        )
        picked: dict[str, list[str]] = {}
        for sid in scenes:
            ds = sid.split("/", 1)[0]
            picked.setdefault(ds, []).append(sid)
    else:
        scenes = pipeline.resolve_scenes(
            n=n or 50,
            seed=seed,
            datasets=datasets,
            min_room_extent_m=min_room_extent_m,
        )
        picked: dict[str, list[str]] = {}
        for sid in scenes:
            ds = sid.split("/", 1)[0]
            picked.setdefault(ds, []).append(sid)
        pipeline._sampler.save_sample(
            picked, pipeline.OUTPUT / "batch" / "sample_manifest.json"
        )

    total = len(scenes)
    logger.info(
        "run start: %d scene(s) (n=%s, seed=%d, min_room_extent_m=%.2f)",
        total, n or "N/A", seed, min_room_extent_m,
    )

    # optional auto-fill pass
    if auto_fill or auto_fill_once:
        logger.info("=== auto-fill pre-pass: %d scene(s) ===", len(scenes))
        for sid in scenes:
            pipeline.stage_compose(sid, write_missing_report=True, verbose_missing=False)
        pipeline.auto_fill_assets(scenes)
        if auto_fill:
            for sid in scenes:
                p = pipeline.paths_for(sid)["composed"]
                if p.exists():
                    try:
                        p.unlink()
                    except OSError:
                        pass
            logger.info("auto-fill: cleared placeholder composed GLBs")
        else:
            logger.info("auto-fill-once: leaving placeholder composed GLBs in place")

    t_start = time.time()
    results: list[dict] = []
    n_ok = 0
    for i, sid in enumerate(scenes, 1):
        logger.info("=== %s [%d/%d] ===", sid, i, total)
        st = pipeline.run_scene(
            sid,
            resume=resume,
            skip_render=skip_render,
            skip_topdown=skip_topdown,
        )
        results.append(st)
        if st["status"] == "complete":
            n_ok += 1
        pipeline.flush_manifest(manifest_path, results, picked, t_start)
        logger.info("progress: %d/%d scenes, %d complete", len(results), total, n_ok)

    elapsed = time.time() - t_start
    logger.info("RUN DONE in %.1f min: %d/%d complete", elapsed / 60, n_ok, total)
    print(json.dumps({
        "total": total,
        "complete": n_ok,
        "elapsed_min": round(elapsed / 60, 1),
        "manifest": str(manifest_path),
    }))
    return 0


# ---------------------------------------------------------------------------
# legacy single-stage wrappers
# ---------------------------------------------------------------------------
def _paths(scene_id: str) -> dict:
    return pipeline.paths_for(scene_id)


def cmd_render(scene: str, engine: str = "EEVEE") -> int:
    """Compose (if needed) and render the perspective PNG for one scene."""
    p = _paths(scene)
    logger.info("render: %s", scene)
    if not p["composed"].exists():
        logger.info("composed GLB missing -> composing first")
        if not pipeline.stage_compose(scene):
            logger.error("compose failed")
            return 1
    return 0 if pipeline.stage_render(scene) else 1


def cmd_topdown(scene: str) -> int:
    """Produce the 2D top-down projection for one scene."""
    logger.info("topdown: %s", scene)
    return 0 if pipeline.stage_topdown(scene) else 1


def cmd_info(scene: str, out: str | None = None) -> int:
    """Export the scene metadata JSON for one scene."""
    logger.info("info: %s", scene)
    if not pipeline.stage_info(scene):
        return 1
    if out:
        src = _paths(scene)["info"]
        dst = Path(out)
        if src.exists() and src.resolve() != dst.resolve():
            dst.parent.mkdir(parents=True, exist_ok=True)
            import shutil
            shutil.copy2(src, dst)
    return 0


def cmd_batch(
    n: int, seed: int, resume: bool, datasets: str,
    min_room_extent_m: float = 0.0,
) -> int:
    """Run the legacy batch pipeline (compose → render → topdown → info)."""
    return cmd_run(
        n=n,
        seed=seed,
        datasets=datasets.split(",") if datasets else None,
        scene_ids=None,
        resume=resume,
        auto_fill=False,
        auto_fill_once=False,
        skip_render=False,
        skip_topdown=False,
        manifest=str(pipeline.OUTPUT / "batch" / "manifest.json"),
        log=str(pipeline.OUTPUT / "batch" / "batch.log"),
        min_room_extent_m=min_room_extent_m,
    )


def cmd_questions(
    scene_ids: list[str] | None,
    n: int,
    seed: int,
    datasets: list[str] | None,
    out_dir: str | None,
    min_room_extent_m: float = 0.0,
) -> int:
    """Generate object-finding questions for one or more scenes."""
    if scene_ids:
        scenes = pipeline.resolve_scenes(
            scene_ids=scene_ids, min_room_extent_m=min_room_extent_m
        )
    else:
        scenes = pipeline.resolve_scenes(
            n=n or 50, seed=seed, datasets=datasets, min_room_extent_m=min_room_extent_m
        )
    if not scenes:
        logger.error("no scenes matched the criteria")
        return 1
    _questions.generate_for_scenes(
        scenes, out_dir=out_dir, n=n, seed=seed
    )
    return 0


# ---------------------------------------------------------------------------
# parser
# ---------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="internscenes",
        description="InternScenes -> Isaac Sim pipeline (installable library)",
    )
    ap.add_argument("--verbose", "-v", action="store_true")
    sub = ap.add_subparsers(dest="command", required=True)

    # unified run command
    p = sub.add_parser("run", help="run the full pipeline")
    p.add_argument("-n", type=int, default=50,
                   help="scenes per dataset for random batch (default: 50)")
    p.add_argument("--seed", type=int, default=0, help="RNG seed")
    p.add_argument("--datasets", nargs="+",
                   help="limit random sampling to these datasets")
    p.add_argument("--scene", action="append", dest="scene_ids",
                   help="specific scene id(s); repeatable (e.g. scannet/scene0001_00)")
    p.add_argument("--resume", action="store_true",
                   help="skip stages whose output file already exists")
    p.add_argument("--auto-fill", action="store_true",
                   help="pre-pass: collect missing UIDs, download only those, re-compose")
    p.add_argument("--auto-fill-once", action="store_true",
                   help="collect + download missing UIDs, but do not re-compose")
    p.add_argument("--skip-render", action="store_true")
    p.add_argument("--skip-topdown", action="store_true")
    p.add_argument("--min-room-extent", dest="min_room_extent_m", type=float, default=0.0,
                   help="skip scenes whose smaller floor dimension (width/depth in m) is below this value")
    p.add_argument("--manifest", default=str(pipeline.OUTPUT / "batch" / "manifest.json"))
    p.add_argument("--log", default=str(pipeline.OUTPUT / "batch" / "batch.log"))
    p.set_defaults(func=cmd_run)

    # legacy commands
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

    p = sub.add_parser("batch", help="run the legacy batch pipeline")
    p.add_argument("-n", type=int, default=50)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--resume", action="store_true")
    p.add_argument("--datasets", default="")
    p.add_argument("--min-room-extent", dest="min_room_extent_m", type=float, default=0.0,
                   help="skip scenes whose smaller floor dimension (width/depth in m) is below this value")
    p.set_defaults(func=cmd_batch)

    p = sub.add_parser(
        "questions",
        help="generate object-finding questions for navigation evaluation",
    )
    p.add_argument("-n", type=int, default=5,
                   help="questions per scene (default: 5)")
    p.add_argument("--seed", type=int, default=0, help="RNG seed")
    p.add_argument("--datasets", nargs="+",
                   help="limit random sampling to these datasets")
    p.add_argument("--scene", action="append", dest="scene_ids",
                   help="specific scene id(s); repeatable")
    p.add_argument("--out-dir", default=str(pipeline.OUTPUT / "questions"),
                   help="directory for the merged all.jsonl (per-scene files go into each normalized folder)")
    p.add_argument("--min-room-extent", dest="min_room_extent_m", type=float, default=0.0,
                   help="skip scenes whose smaller floor dimension (width/depth in m) is below this value")
    p.set_defaults(func=cmd_questions)

    return ap


def main() -> int:
    args = build_parser().parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    kwargs = {k: v for k, v in vars(args).items()
              if k not in ("command", "func", "verbose")}
    return args.func(**kwargs)


if __name__ == "__main__":
    raise SystemExit(main())
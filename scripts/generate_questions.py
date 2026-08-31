#!/usr/bin/env python3
"""Standalone script to generate navigation questions for InternScenes scenes.

Reads each scene's ``scene.json`` from
``output/normalized/<dataset>_<id>/scene.json``, selects medium-to-far target
objects from the Go2 start pose, and writes ``questions.jsonl`` into the same
normalized folder.  A merged ``all.jsonl`` is also written to ``--out-dir``.

Examples
--------

    # one specific scene
    python scripts/generate_questions.py --scene scannet/scene0001_00

    # 10 random ScanNet scenes, 5 questions each
    python scripts/generate_questions.py -n 10 --seed 0 --datasets scannet

    # explicit scene list
    python scripts/generate_questions.py \
        --scene scannet/scene0001_00 \
        --scene arkitscenes/Training/41125543
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

# Allow running before the package is installed.
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from internscenes import pipeline
from internscenes import questions as _questions

logger = logging.getLogger("generate_questions")


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Generate navigation questions for InternScenes scenes"
    )
    ap.add_argument(
        "-n", type=int, default=5, help="questions per scene (default: 5)"
    )
    ap.add_argument("--seed", type=int, default=0, help="RNG seed")
    ap.add_argument(
        "--datasets", nargs="+",
        help="limit random sampling to these datasets"
    )
    ap.add_argument(
        "--scene", action="append", dest="scene_ids",
        help="specific scene id(s); repeatable"
    )
    ap.add_argument(
        "--min-room-extent", dest="min_room_extent_m", type=float, default=0.0,
        help="skip scenes whose smaller floor dimension (width/depth in m) is below this value",
    )
    ap.add_argument(
        "--out-dir", default=str(pipeline.OUTPUT / "questions"),
        help="directory for the merged all.jsonl (per-scene files go into each normalized folder)",
    )
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    if args.scene_ids:
        scenes = pipeline.resolve_scenes(
            scene_ids=args.scene_ids, min_room_extent_m=args.min_room_extent_m
        )
    else:
        scenes = pipeline.resolve_scenes(
            n=args.n or 5,
            seed=args.seed,
            datasets=args.datasets,
            min_room_extent_m=args.min_room_extent_m,
        )
    if not scenes:
        logger.error("no scenes matched the criteria")
        return 1

    _questions.generate_for_scenes(
        scenes, out_dir=args.out_dir, n=args.n, seed=args.seed
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

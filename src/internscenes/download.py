"""Download the per-object GLBs referenced by InternScenes layouts.

The original InternScenes asset library is ~22k GLBs; downloading the whole
thing is wasteful when you only care about a handful of scenes.  This module
supports three modes:

1. **Auto-fill** (default) — reads every ``output/info/*_missing.json``
   (or a sample manifest) and downloads *only* the UIDs that are not
   already present under ``data/asset_library/``.  This is the path the
   pipeline uses when ``--auto-fill`` is set.
2. **Explicit list** — pass ``scene_ids`` to download every unique UID
   referenced by those scenes' layouts.
3. **uid_2_angle-driven** — original behaviour: download a fixed list of
   scenes (kept for backwards compatibility).

Public entry point: :func:`download_missing(scene_ids, auto, sample, ...)`.
"""
from __future__ import annotations

import json
import logging
import os
import time
from collections import defaultdict
from pathlib import Path

from huggingface_hub import snapshot_download

logger = logging.getLogger(__name__)

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DATA = Path(os.environ.get("INTERN_DATA_DIR", ROOT / "data"))
ASSET_LIBRARY = DATA / "asset_library"
LAYOUT_DIR = DATA / "Layout_info"
OUTPUT = Path(os.environ.get("INTERN_OUTPUT_DIR", ROOT / "output"))
INFO = OUTPUT / "info"

# UIDs that compose.py will try to load as ``<uid>.glb`` directly; the
# remainder come from inside a sub-folder (``partnet_mobility/<id>/whole.glb``).
# HuggingFace's pattern matcher works on allow_patterns glob, so we build
# the per-UID patterns explicitly.
DIRECT_LOAD_PREFIXES = ("objaverse", "objaverse_old", "3D-FUTURE-model",
                        "hssd-models", "gr100", "gen_assets")


def _layout_uids(scene_id: str) -> set[str]:
    """Return every model_uid referenced by ``scene_id``'s layout.json."""
    p = LAYOUT_DIR / scene_id / "layout.json"
    if not p.exists():
        return set()
    return {o["model_uid"] for o in json.loads(p.read_text())
            if o.get("model_uid")}


def _missing_report_uids(scene_ids: list[str] | None = None) -> dict[str, set[str]]:
    """Read every ``output/info/<scene>_missing.json`` and group UIDs by source.

    ``scene_ids`` — restrict to a subset of scenes (None = all).  Returns a
    ``{source_prefix: {uid, ...}, ...}`` mapping so the downloader can ask
    HuggingFace for only the prefixes that are actually needed.
    """
    found: dict[str, set[str]] = defaultdict(set)
    if not INFO.exists():
        return found
    for r in sorted(INFO.glob("*_missing.json")):
        if "_missing" not in r.stem:
            continue
        try:
            data = json.loads(r.read_text())
        except Exception:
            continue
        sid = data.get("scene_id")
        if scene_ids and sid not in scene_ids:
            continue
        for m in data.get("missing", []):
            uid = m.get("uid")
            if not uid:
                continue
            found[uid.split("/", 1)[0]].add(uid)
    return found


def _collect_uids(scene_ids: list[str] | None) -> dict[str, set[str]]:
    """Build a ``{source: {uid, ...}}`` map for the given scenes."""
    found: dict[str, set[str]] = defaultdict(set)
    scenes = scene_ids or [
        "scannet/scene0000_00",
        "3rscan/095821fb-e2c2-2de1-94df-20f2cb423bcb",
        "arkitscenes/Training/43896449",
        "matterport3d/B6ByNegPMKs/region51",
        "scannet/scene0001_00",
    ]
    for s in scenes:
        for u in _layout_uids(s):
            found[u.split("/", 1)[0]].add(u)
    return found


def _exists_on_disk(uid: str, src: str) -> bool:
    """Return True if any of the canonical or nested variants of ``uid`` exist."""
    if src == "partnet_mobility":
        return (ASSET_LIBRARY / uid / "whole.glb").exists()
    primary = ASSET_LIBRARY / f"{uid}.glb"
    if primary.exists():
        return True
    # Nested variant: ``<lib>/<lib>/<uid>.glb`` (some tar extracts).
    first = uid.split("/", 1)[0]
    nested = ASSET_LIBRARY / first / first / f"{Path(uid).name}.glb"
    return nested.exists()


def _filter_existing(by_source: dict[str, set[str]]) -> dict[str, set[str]]:
    """Drop UIDs that are already on disk under ``data/asset_library/``."""
    out: dict[str, set[str]] = {}
    for src, uids in by_source.items():
        keep: set[str] = set()
        for uid in uids:
            if not _exists_on_disk(uid, src):
                keep.add(uid)
        if keep:
            out[src] = keep
    return out


def _build_hf_patterns(by_source: dict[str, set[str]]) -> list[str]:
    """Convert ``{src: {uid, ...}}`` to a flat list of HuggingFace globs."""
    pats: list[str] = []
    for src, uids in by_source.items():
        for uid in sorted(uids):
            if src == "partnet_mobility":
                pats.append(f"asset_library/{uid}/whole.glb")
            else:
                pats.append(f"asset_library/{uid}.glb")
    return pats


def download_missing(
    scene_ids: list[str] | None = None,
    *,
    auto: bool = False,
    sample: str | Path | None = None,
    no_filter_existing: bool = False,
    dry_run: bool = False,
    log: str | Path = "output/batch/download.log",
) -> int:
    """Download only the missing per-object GLBs for the selected scenes.

    Parameters
    ----------
    scene_ids
        Scene ids to scope the download to.
    auto
        Scan ``output/info/*_missing.json`` instead of reading layouts directly.
    sample
        Path to a sample manifest JSON produced by the batch runner.
    no_filter_existing
        Download even UIDs that are already on disk.
    dry_run
        Print what would be downloaded without downloading.
    log
        Path to write the download log.

    Returns
    -------
    0 on success, 1 on error.
    """
    log_path = Path(log)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logger.handlers.clear()
    logger.setLevel(logging.INFO)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    file_handler = logging.FileHandler(log_path)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    logger.addHandler(logging.StreamHandler())

    scenes = list(scene_ids) if scene_ids else None
    if sample:
        try:
            data = json.loads(Path(sample).read_text())
            scenes = []
            for ids in data.get("sample", {}).values():
                scenes.extend(ids)
        except Exception as exc:
            logger.error("could not read --sample %s: %s", sample, exc)
            return 1

    if auto:
        by_source = _missing_report_uids(scenes)
        logger.info("auto-fill: %d scene(s) scanned, %d source(s) with missing UIDs",
                    len(scenes) if scenes else "all", len(by_source))
    else:
        by_source = _collect_uids(scenes)
        logger.info("explicit mode: %d scene(s), %d source(s)",
                    len(scenes) if scenes else 5, len(by_source))

    if not by_source:
        logger.info("nothing to download — all referenced UIDs are present")
        return 0

    if not no_filter_existing:
        before = sum(len(v) for v in by_source.values())
        by_source = _filter_existing(by_source)
        after = sum(len(v) for v in by_source.values())
        logger.info("filter-existing: %d → %d UIDs to download", before, after)
        if not by_source:
            logger.info("all UIDs already on disk; nothing to do")
            return 0

    patterns = _build_hf_patterns(by_source)
    total = len(patterns)
    by_src_counts = {k: len(v) for k, v in by_source.items()}
    logger.info("downloading %d files: %s", total, by_src_counts)

    if dry_run:
        for p in patterns:
            print(p)
        return 0

    t0 = time.time()
    snapshot_download(
        "InternRobotics/InternScenes",
        repo_type="dataset",
        allow_patterns=patterns,
        local_dir=str(DATA),
    )
    elapsed = time.time() - t0
    logger.info("DONE in %.0fs: %d files", elapsed, total)
    return 0


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(
        description="Download per-object InternScenes GLBs (auto-fill mode preferred)",
    )
    ap.add_argument(
        "--auto", action="store_true",
        help="scan output/info/*_missing.json and download only what's missing",
    )
    ap.add_argument(
        "--scene", action="append", default=[],
        help="scene id(s) to scope the download to (repeatable)",
    )
    ap.add_argument(
        "--sample",
        help="path to a sample_manifest.json (e.g. output/batch/sample_manifest.json)",
    )
    ap.add_argument(
        "--no-filter-existing", action="store_true",
        help="download even UIDs that already exist on disk",
    )
    ap.add_argument(
        "--dry-run", action="store_true",
        help="print what would be downloaded without actually downloading",
    )
    ap.add_argument(
        "--log", default="output/batch/download.log",
        help="log file path (default: output/batch/download.log)",
    )
    args = ap.parse_args()
    return download_missing(
        scene_ids=args.scene or None,
        auto=args.auto,
        sample=args.sample,
        no_filter_existing=args.no_filter_existing,
        dry_run=args.dry_run,
        log=args.log,
    )


if __name__ == "__main__":
    import sys
    raise SystemExit(main())

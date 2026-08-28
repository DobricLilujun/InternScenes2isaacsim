#!/usr/bin/env python3
"""Normalise InternScenes per-scene output into a single, regular folder per scene.

For every scene (taken from the batch sample manifest, or a scene list), this
collects the four existing pipeline artefacts and lays them out in one
self-contained directory whose name is "<dataset>_<scene_id>":

    output/normalized/<dataset>_<id>/
        topdown.png          # 2D top-down render
        perspective.png      # Blender perspective render
        scene.usd            # USD (built from the composed GLB, WITHOUT Go2)
        scene.json          # full scene info + the computed Go2 placement

The four artefacts already exist in the separate output trees
(composed / usd / render / topdown / info); this script only assembles them,
and (for any scene missing a USD) converts the composed GLB on the fly.
The Go2 placement is NOT added to the scene geometry here (the requirement is a
USD *without* Go2); it is only reported inside scene.json so a later step can
drop a Go2 asset in.

Usage:
    python normalize_output.py                 # normalise the 200-scene sample
    python normalize_output.py --n 1 --seed 0  # just one scene (quick check)
    python normalize_output.py --list my.txt   # explicit scene list (one per line)
"""
from __future__ import annotations

import argparse
import json
import logging
import shutil
import sys
from pathlib import Path
from typing import Any

# --- project root (this file lives in <root>/scripts) ---
HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "src"))

from internscenes import scene_info  # noqa: E402  (project module)

try:
    import place_go2  # scripts/  (for the go2 placement, if scene_info import fails)
except Exception:  # pragma: no cover
    place_go2 = None

logger = logging.getLogger("normalize_output")

# --- output layout ---
OUTPUT = ROOT / "output"
NORMALIZED = OUTPUT / "normalized"
COMPOSED = OUTPUT / "composed"
USD = OUTPUT / "usd"
RENDER = OUTPUT / "render"
TOPDOWN = OUTPUT / "topdown"
INFO = OUTPUT / "info"


def slug(scene_id: str) -> str:
    """<dataset>_<id> with '/' collapsed to '_' (e.g. 3rscan_02b33... )."""
    return scene_id.replace("/", "_")


def resolve_artifacts(scene_id: str) -> dict[str, Path | None]:
    """Return the on-disk paths of the four artefacts for a scene, if present."""
    ds = scene_id.split("/", 1)[0]
    rest = scene_id.split("/", 1)[1] if "/" in scene_id else scene_id
    usd_rel = scene_id  # USD tree mirrors the full scene_id
    return {
        "topdown": TOPDOWN / f"{slug(scene_id)}_topdown.png",
        "perspective": RENDER / usd_rel / "perspective.png",
        "usd": USD / usd_rel / "scene.usd",
        "glb": COMPOSED / usd_rel / "glb_scene.glb",
        "info": INFO / f"{slug(scene_id)}.json",
    }


def ensure_usd(scene_id: str, usd_path: Path, glb_path: Path | None) -> Path | None:
    """Ensure a USD exists; convert the composed GLB (no Go2) if it is missing."""
    if usd_path.exists():
        return usd_path
    if glb_path is None or not glb_path.exists():
        logger.warning("no GLB and no USD for %s; USD will be missing", scene_id)
        return None
    try:
        import glb_to_usd
        glb_to_usd.build_usd(str(glb_path), str(usd_path))
        return usd_path
    except Exception as exc:  # pragma: no cover
        logger.warning("USD conversion failed for %s: %s", scene_id, exc)
        return None


def build_scene_json(scene_id: str) -> dict[str, Any]:
    """(Re)compute the full scene info incl. the collision-aware Go2 placement."""
    layout = ROOT / "data" / "Layout_info" / scene_id / "layout.json"
    if not layout.exists():
        logger.warning("layout.json missing for %s", scene_id)
        return {}
    try:
        return scene_info.build_scene_info(scene_id, layout)
    except Exception as exc:  # pragma: no cover
        logger.warning("scene_info build failed for %s: %s", scene_id, exc)
        return {}


def normalize_scene(scene_id: str, out_root: Path, rebuild_json: bool = True) -> dict[str, str]:
    """Assemble one scene's folder; return the {artefact: dest_path} that succeeded."""
    paths = resolve_artifacts(scene_id)
    dest_dir = out_root / slug(scene_id)
    dest_dir.mkdir(parents=True, exist_ok=True)
    got: dict[str, str] = {}

    def copy(src: Path | None, dest_name: str, key: str) -> None:
        if src is not None and src.exists():
            dst = dest_dir / dest_name
            shutil.copy2(src, dst)
            got[key] = str(dst)
        else:
            logger.info("  [missing] %s for %s", dest_name, scene_id)

    copy(paths["topdown"], "topdown.png", "topdown")
    copy(paths["perspective"], "perspective.png", "perspective")

    usd = ensure_usd(scene_id, paths["usd"], paths["glb"])
    if usd is not None and usd.exists():
        shutil.copy2(usd, dest_dir / "scene.usd")
        got["usd"] = str(dest_dir / "scene.usd")
    else:
        logger.info("  [missing] scene.usd for %s", scene_id)

    # scene.json: prefer a freshly computed one (guarantees go2 placement),
    # fall back to the existing info file.
    if rebuild_json:
        info = build_scene_json(scene_id)
        if info:
            dst = dest_dir / "scene.json"
            with dst.open("w", encoding="utf-8") as fh:
                json.dump(info, fh, ensure_ascii=False, indent=2)
            got["scene.json"] = str(dst)
        elif paths["info"] is not None and paths["info"].exists():
            shutil.copy2(paths["info"], dest_dir / "scene.json")
            got["scene.json"] = str(dest_dir / "scene.json")
        else:
            logger.info("  [missing] scene.json for %s", scene_id)
    else:
        copy(paths["info"], "scene.json", "scene.json")

    return got


def load_scenes(args: argparse.Namespace) -> list[str]:
    if args.list:
        return [s.strip() for s in Path(args.list).read_text().splitlines() if s.strip()]
    if args.sample:
        return [s for s in args.sample]
    # default: the 200-scene batch sample manifest
    manifest = OUTPUT / "batch" / "manifest.json"
    if manifest.exists():
        data = json.load(manifest.open())
        scenes: list[str] = []
        for ds, ids in data.get("sample", {}).items():
            scenes.extend(ids)
        if scenes:
            return scenes
    logger.error("no scene source; pass --sample/--list or create a batch manifest")
    return []


def main() -> int:
    ap = argparse.ArgumentParser(description="Normalise per-scene output into one folder each")
    ap.add_argument("--out", default=str(NORMALIZED), help="normalised output root")
    ap.add_argument("--sample", nargs="+", help="explicit scene ids (e.g. scannet/scene0001_00)")
    ap.add_argument("--list", help="file with one scene id per line")
    ap.add_argument("--n", type=int, default=0, help="normalise only the first N scenes")
    ap.add_argument("--seed", type=int, default=0, help="seed (reserved for future sampling)")
    ap.add_argument("--no-rebuild-json", action="store_true",
                    help="reuse existing info JSON instead of recomputing")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    scenes = load_scenes(args)
    if args.n > 0:
        scenes = scenes[: args.n]
    out_root = Path(args.out)
    out_root.mkdir(parents=True, exist_ok=True)

    logger.info("normalising %d scene(s) -> %s", len(scenes), out_root)
    summary = {"done": 0, "missing": []}
    for i, scene_id in enumerate(scenes, 1):
        got = normalize_scene(scene_id, out_root, rebuild_json=not args.no_rebuild_json)
        n = len(got)
        logger.info("[%d/%d] %s -> %s (%d/4 artefacts)", i, len(scenes),
                    scene_id, slug(scene_id), n)
        if n == 0:
            summary["done"] += 0
        else:
            summary["done"] += 1
        if n < 4:
            summary["missing"].append((scene_id, sorted(set(["topdown", "perspective",
                                                            "usd", "scene.json"]) - set(got))))
    logger.info("done: %d/%d fully complete", summary["done"], len(scenes))
    for scene_id, miss in summary["missing"]:
        logger.info("incomplete %s: missing %s", scene_id, miss)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
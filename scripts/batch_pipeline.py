#!/usr/bin/env python3
"""Batch pipeline for InternScenes scenes.

For every scene in a per-category random sample this orchestrator runs the full
pipeline and writes the artifacts back into the project's ``output/`` tree:

    compose  layout.json  ->  output/composed/<scene>/glb_scene.glb
    render   glb          ->  output/render/<scene>/perspective.png   (Blender EEVEE)
    topdown  layout.json  ->  output/topdown/<scene>_topdown.png
    info     layout.json  ->  output/info/<scene>.json

Each stage is independent and *resumable*: if the run is interrupted, re-running
with ``--resume`` skips stages whose output file already exists.  A JSON
manifest of the final status of every scene is written to ``output/batch/``.

Run from the project root, inside the Python 3.11 virtual environment:

    .venv311/bin/python scripts/batch_pipeline.py --n 50 --seed 0
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

# --- project layout -------------------------------------------------------
HERE = Path(__file__).resolve().parent          # .../scripts
ROOT = HERE.parent                               # project root
SRC = ROOT / "src" / "internscenes"
sys.path.insert(0, str(HERE))           # for place_go2 (imported by topdown)
sys.path.insert(0, str(SRC))           # for compose / scene_info / sampler

import compose as compose_mod  # noqa: E402
import sampler  # noqa: E402
import scene_info  # noqa: E402

logger = logging.getLogger("batch")


# ---------------------------------------------------------------------------
# path helpers
# ---------------------------------------------------------------------------
def rel_scene(*parts: str) -> str:
    """Join path parts with '/' so the result is stable on every OS."""
    return "/".join(p.strip("/") for p in parts)


def _paths(scene_id: str) -> dict[str, Path]:
    """Return the canonical output paths for a scene."""
    composed = ROOT / "output" / "composed" / scene_id / "glb_scene.glb"
    render_dir = ROOT / "output" / "render" / scene_id
    perspective = render_dir / "perspective.png"
    flat = scene_id.replace("/", "_")
    topdown = ROOT / "output" / "topdown" / f"{flat}_topdown.png"
    info = ROOT / "output" / "info" / f"{flat}.json"
    return {
        "layout": ROOT / "data" / "Layout_info" / scene_id / "layout.json",
        "composed": composed,
        "render_dir": render_dir,
        "perspective": perspective,
        "topdown": topdown,
        "info": info,
    }


# ---------------------------------------------------------------------------
# individual stages
# ---------------------------------------------------------------------------
def stage_compose(scene_id: str, paths: dict[str, Path]) -> bool:
    """Build the composed GLB from layout.json + the asset library."""
    if not paths["layout"].exists():
        logger.error("[%s] compose: no layout.json", scene_id)
        return False
    glb, missing = compose_mod.SceneComposer().compose_one_scene(scene_id)
    return bool(glb) and Path(glb).exists()


def stage_render(scene_id: str, paths: dict[str, Path], blender: str) -> bool:
    """Render the composed GLB to a perspective PNG via Blender (headless)."""
    if not paths["composed"].exists():
        logger.error("[%s] render: no composed GLB", scene_id)
        return False
    paths["render_dir"].mkdir(parents=True, exist_ok=True)
    cmd = [
        blender, "--background", "--python", str(HERE / "glb_render.py"), "--",
        "--glb", str(paths["composed"]),
        "--out", str(paths["render_dir"]),
        "--engine=EEVEE",
    ]
    logger.info("[%s] render: %s", scene_id, " ".join(cmd[-3:]))
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        logger.error("[%s] render FAILED (rc=%d): %s", scene_id, proc.returncode,
                     proc.stderr[-800:])
        return False
    ok = paths["perspective"].exists()
    if not ok:
        logger.warning("[%s] render: no perspective.png produced", scene_id)
    return ok


def stage_topdown(scene_id: str, paths: dict[str, Path], venv_python: str) -> bool:
    """Produce the 2D top-down projection PNG for the scene."""
    if not paths["layout"].exists():
        logger.error("[%s] topdown: no layout.json", scene_id)
        return False
    cmd = [venv_python, str(HERE / "topdown_projection.py"), scene_id,
           "--out", str(paths["topdown"])]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        logger.error("[%s] topdown FAILED (rc=%d): %s", scene_id, proc.returncode,
                     proc.stderr[-800:])
        return False
    return paths["topdown"].exists()


def stage_info(scene_id: str, paths: dict[str, Path]) -> bool:
    """Export the scene-information JSON (dimensions, objects, Go2 placement)."""
    if not paths["layout"].exists():
        logger.error("[%s] info: no layout.json", scene_id)
        return False
    try:
        info = scene_info.build_scene_info(scene_id, paths["layout"])
    except Exception as exc:  # pragma: no cover - defensive
        logger.error("[%s] info: %s", scene_id, exc)
        return False
    info["renders"] = {
        "blender_perspective": str(paths["perspective"]) if paths["perspective"].exists() else None,
        "topdown": str(paths["topdown"]) if paths["topdown"].exists() else None,
        "composed_glb": str(paths["composed"]) if paths["composed"].exists() else None,
    }
    scene_info.write_scene_info(info, paths["info"])
    return paths["info"].exists()


STAGES = ("compose", "render", "topdown", "info")
STAGE_FN = {
    "compose": stage_compose,
    "render": stage_render,
    "topdown": stage_topdown,
    "info": stage_info,
}
# output file that signals a stage is already done (for --resume)
STAGE_DONE = {
    "compose": "composed",
    "render": "perspective",
    "topdown": "topdown",
    "info": "info",
}


# ---------------------------------------------------------------------------
# orchestration
# ---------------------------------------------------------------------------
def run_scene(
    scene_id: str,
    blender: str,
    venv_python: str,
    resume: bool,
) -> dict[str, Any]:
    """Run the full pipeline for one scene; return a status dict."""
    paths = _paths(scene_id)
    status: dict[str, Any] = {"scene_id": scene_id, "stages": {}}
    for stage in STAGES:
        t0 = time.time()
        if resume and paths[STAGE_DONE[stage]].exists():
            status["stages"][stage] = "skipped(exists)"
            continue
        try:
            if stage == "render":
                ok = STAGE_FN["render"](scene_id, paths, blender)
            elif stage == "topdown":
                ok = STAGE_FN["topdown"](scene_id, paths, venv_python)
            else:
                ok = STAGE_FN[stage](scene_id, paths)
        except Exception as exc:  # never let one scene kill the whole batch
            logger.exception("[%s] %s raised", scene_id, stage)
            ok = False
            status["stages"][stage] = f"error({type(exc).__name__})"
        dt = time.time() - t0
        status["stages"][stage] = f"ok({dt:.1f}s)" if ok else f"failed({dt:.1f}s)"
        logger.info("[%s] %s -> %s", scene_id, stage, status["stages"][stage])
    status["status"] = "complete" if all(
        v.startswith("ok") or v.startswith("skipped") for v in status["stages"].values()
    ) else "incomplete"
    return status


def main() -> int:
    ap = argparse.ArgumentParser(description="Batch InternScenes pipeline")
    ap.add_argument("-n", type=int, default=50, help="scenes per category")
    ap.add_argument("--seed", type=int, default=0, help="RNG seed for sampling")
    ap.add_argument("--blender",
                    default=os.environ.get("BLENDER",
                        "/home/ubadmin/tools/blender/blender-5.1.2-linux-x64/blender"))
    ap.add_argument("--venv-python",
                    default=os.environ.get("VENV_PY", str(ROOT / ".venv311" / "bin" / "python")))
    ap.add_argument("--datasets", default=",".join(sampler.DATASETS),
                    help="comma-separated datasets to include")
    ap.add_argument("--resume", action="store_true",
                    help="skip stages whose output file already exists")
    ap.add_argument("--manifest", default=str(ROOT / "output" / "batch" / "manifest.json"))
    ap.add_argument("--log", default=str(ROOT / "output" / "batch" / "batch.log"))
    args = ap.parse_args()

    log_dir = ROOT / "output" / "batch"
    log_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(args.log),
            logging.StreamHandler(),
        ],
    )

    # --- sample ---
    inventory = sampler.scan_all(ROOT / "data" / "Layout_info")
    picked = sampler.sample(inventory, n=args.n, seed=args.seed)
    wanted = set(args.datasets.split(","))
    picked = {k: v for k, v in picked.items() if k in wanted}
    sampler.save_sample(picked, log_dir / "sample_manifest.json")
    total = sum(len(v) for v in picked.values())
    logger.info("batch start: %d scenes across %d categories (n=%d, seed=%d)",
                total, len(picked), args.n, args.seed)

    # --- run ---
    results: list[dict[str, Any]] = []
    n_ok = 0
    t_start = time.time()
    for dataset, scene_ids in picked.items():
        for i, scene_id in enumerate(scene_ids, 1):
            logger.info("=== %s [%d/%d] ===", scene_id, i, len(scene_ids))
            st = run_scene(scene_id, args.blender, args.venv_python, args.resume)
            results.append(st)
            if st["status"] == "complete":
                n_ok += 1
            _flush_manifest(args.manifest, results, picked, t_start)
            logger.info("progress: %d/%d scenes, %d complete so far",
                        len(results), total, n_ok)

    # --- summary ---
    elapsed = time.time() - t_start
    logger.info("BATCH DONE in %.1f min: %d/%d complete", elapsed / 60, n_ok, total)
    print(json.dumps({
        "total": total,
        "complete": n_ok,
        "elapsed_min": round(elapsed / 60, 1),
    }))
    return 0


def _flush_manifest(manifest: str, results: list[dict[str, Any]],
                    picked: dict[str, list[str]], t_start: float) -> None:
    """Atomically persist the running manifest so a crash loses nothing."""
    doc = {
        "started": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(t_start)),
        "updated": time.strftime("%Y-%m-%d %H:%M:%S"),
        "sample": picked,
        "results": results,
    }
    tmp = manifest + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, manifest)


if __name__ == "__main__":
    raise SystemExit(main())
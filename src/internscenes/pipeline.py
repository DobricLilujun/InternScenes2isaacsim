"""End-to-end InternScenes pipeline exposed as a Python API.

All paths honour ``INTERN_DATA_DIR`` and ``INTERN_OUTPUT_DIR``.
"""
from __future__ import annotations

import json
import logging
import os
import random
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from . import compose as _compose
from . import download as _download
from . import glb_to_usd as _glb_to_usd
from . import place_go2 as _place_go2  # noqa: F401
from . import sampler as _sampler
from . import scene_info as _scene_info
from . import topdown as _topdown

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src" / "internscenes"  # noqa: F841
DATA = Path(os.environ.get("INTERN_DATA_DIR", ROOT / "data"))
OUTPUT = Path(os.environ.get("INTERN_OUTPUT_DIR", ROOT / "output"))


# ---------------------------------------------------------------------------
# path helpers
# ---------------------------------------------------------------------------
def slug(scene_id: str) -> str:
    return scene_id.replace("/", "_")


def paths_for(scene_id: str) -> dict[str, Path]:
    """Canonical output paths for one scene (legacy layout)."""
    flat = slug(scene_id)
    return {
        "layout": DATA / "Layout_info" / scene_id / "layout.json",
        "composed": OUTPUT / "composed" / scene_id / "glb_scene.glb",
        "render_dir": OUTPUT / "render" / scene_id,
        "perspective": OUTPUT / "render" / scene_id / "perspective.png",
        "topdown": OUTPUT / "topdown" / f"{flat}_topdown.png",
        "info": OUTPUT / "info" / f"{flat}.json",
        "missing": OUTPUT / "info" / f"{flat}_missing.json",
        "normalized": OUTPUT / "normalized" / flat,
    }


# ---------------------------------------------------------------------------
# environment defaults
# ---------------------------------------------------------------------------
def blender_path() -> str:
    return os.environ.get(
        "BLENDER",
        "/home/ubadmin/tools/blender/blender-5.1.2-linux-x64/blender",
    )


def venv_python() -> str:
    return os.environ.get("VENV_PY", str(ROOT / ".venv311" / "bin" / "python"))


# ---------------------------------------------------------------------------
# individual stages
# ---------------------------------------------------------------------------
def stage_compose(
    scene_id: str,
    write_missing_report: bool = True,
    verbose_missing: bool = False,
) -> bool:
    """Compose the scene GLB from layout.json + asset library."""
    p = paths_for(scene_id)
    if not p["layout"].exists():
        logger.error("[%s] no layout.json", scene_id)
        return False
    try:
        glb, missing = _compose.SceneComposer().compose_one_scene(
            scene_id,
            write_missing_report=write_missing_report,
            verbose_missing=verbose_missing,
        )
        return Path(glb).exists() if glb else False
    except Exception as exc:
        logger.exception("[%s] compose failed", scene_id)
        return False


def stage_render(scene_id: str) -> bool:
    """Render perspective PNG via Blender.

    Blender ships its own isolated Python runtime (no trimesh, no project venv).
    We therefore spawn a *subprocess* using the system Blender as the executable
    but pass the project venv Python via the ``VENV_PY`` environment variable.
    The Blender script at ``src/internscenes/_render_in_blender.py`` bootstraps
    the project interpreter and runs :mod:`internscenes.render` from there.
    """
    p = paths_for(scene_id)
    if not p["composed"].exists():
        logger.error("[%s] render: no composed GLB", scene_id)
        return False
    p["render_dir"].mkdir(parents=True, exist_ok=True)

    script = ROOT / "src" / "internscenes" / "_render_in_blender.py"
    env = os.environ.copy()
    env["INTERN_VENV_PY"] = venv_python()
    env["INTERN_SRC_ROOT"] = str(ROOT / "src")
    cmd = [
        blender_path(),
        "--background",
        "--python",
        str(script),
        "--",
        "--glb",
        str(p["composed"]),
        "--out",
        str(p["render_dir"]),
        "--engine=EEVEE",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, env=env)
    if proc.returncode != 0:
        logger.error("[%s] render failed (rc=%d): %s",
                     scene_id, proc.returncode, proc.stderr[-800:])
        return False
    return p["perspective"].exists()


def stage_topdown(scene_id: str) -> bool:
    """Render top-down PNG."""
    p = paths_for(scene_id)
    if not p["layout"].exists():
        logger.error("[%s] topdown: no layout.json", scene_id)
        return False
    try:
        _topdown.draw_scene(scene_id, str(p["layout"]), str(p["topdown"]))
    except Exception:
        logger.exception("[%s] topdown failed", scene_id)
        return False
    return p["topdown"].exists()


def stage_info(scene_id: str) -> bool:
    """Export per-scene metadata JSON."""
    p = paths_for(scene_id)
    if not p["layout"].exists():
        logger.error("[%s] info: no layout.json", scene_id)
        return False
    try:
        info = _scene_info.build_scene_info(scene_id, p["layout"])
    except Exception as exc:
        logger.error("[%s] info: %s", scene_id, exc)
        return False
    info["renders"] = {
        "blender_perspective": str(p["perspective"]) if p["perspective"].exists() else None,
        "topdown": str(p["topdown"]) if p["topdown"].exists() else None,
        "composed_glb": str(p["composed"]) if p["composed"].exists() else None,
    }
    _scene_info.write_scene_info(info, p["info"])
    return p["info"].exists()


def stage_usd(scene_id: str) -> dict[str, Path] | None:
    """Convert composed GLB to USD / USDZ in the normalized folder."""
    p = paths_for(scene_id)
    if not p["composed"].exists():
        logger.error("[%s] usd: no composed GLB", scene_id)
        return None
    p["normalized"].mkdir(parents=True, exist_ok=True)
    try:
        usd_path = Path(
            _glb_to_usd.build_usd(str(p["composed"]), str(p["normalized"] / "scene.usd"))
        )
    except Exception as exc:
        logger.exception("[%s] usd conversion failed", scene_id)
        return None

    # Mesh-viewer / three.js need a self-contained .usdz with
    # UsdPreviewSurface + UsdUVTexture; always generate that via fallback.
    try:
        usdz_path = Path(
            _glb_to_usd.build_usdz(
                str(p["composed"]), str(p["normalized"] / "scene.usdz")
            )
        )
    except Exception as exc:
        logger.exception("[%s] usdz packaging failed", scene_id)
        usdz_path = None

    return {"usd": usd_path, "usdz": usdz_path} if usdz_path else {"usd": usd_path}


# ---------------------------------------------------------------------------
# auto-fill
# ---------------------------------------------------------------------------
def collect_missing_uids(scene_ids: list[str]) -> dict[str, set[str]]:
    """Return {source_prefix: {uid, ...}} from missing reports."""
    from collections import defaultdict
    found: dict[str, set[str]] = defaultdict(set)
    for sid in scene_ids:
        mp = paths_for(sid)["missing"]
        if not mp.exists():
            continue
        try:
            data = json.loads(mp.read_text())
        except Exception:
            continue
        for m in data.get("missing", []):
            uid = m.get("uid")
            if uid:
                found[uid.split("/", 1)[0]].add(uid)
    return found


def auto_fill_assets(scene_ids: list[str]) -> int:
    """Download only the missing per-object GLBs for ``scene_ids``."""
    logger.info("auto-fill: %d scene(s)", len(scene_ids))
    return _download.download_missing(
        scene_ids=scene_ids,
        auto=True,
        log=OUTPUT / "batch" / "download.log",
    )


# ---------------------------------------------------------------------------
# normalize (final assembly)
# ---------------------------------------------------------------------------
def assemble_normalized(scene_id: str) -> dict[str, str]:
    """Collect all artefacts into ``output/normalized/<ds>_<id>/``.

    Returns a mapping of the artefacts that succeeded.
    """
    p = paths_for(scene_id)
    dest = p["normalized"]
    dest.mkdir(parents=True, exist_ok=True)
    got: dict[str, str] = {}

    def copy(src: Path, name: str, key: str) -> None:
        if src.exists():
            dst = dest / name
            if src.resolve() != dst.resolve():
                shutil.copy2(src, dst)
            got[key] = str(dst)

    copy(p["topdown"], "topdown.png", "topdown")
    copy(p["perspective"], "perspective.png", "perspective")

    usd_result = stage_usd(scene_id)
    if usd_result is not None:
        usd = usd_result.get("usd")
        if usd is not None and usd.exists():
            dst = dest / "scene.usd"
            if usd.resolve() != dst.resolve():
                shutil.copy2(usd, dst)
            got["usd"] = str(dst)
        usdz = usd_result.get("usdz")
        if usdz is not None and usdz.exists():
            dst = dest / "scene.usdz"
            if usdz.resolve() != dst.resolve():
                shutil.copy2(usdz, dst)
            got["usdz"] = str(dst)

    # rebuild scene.json so it always reflects current renders / go2
    try:
        info = _scene_info.build_scene_info(scene_id, p["layout"])
        info["renders"] = {
            "blender_perspective": str(dest / "perspective.png")
            if (dest / "perspective.png").exists() else None,
            "topdown": str(dest / "topdown.png")
            if (dest / "topdown.png").exists() else None,
            "composed_glb": str(p["composed"]) if p["composed"].exists() else None,
            "usd": str(dest / "scene.usd") if (dest / "scene.usd").exists() else None,
            "usdz": str(dest / "scene.usdz") if (dest / "scene.usdz").exists() else None,
        }
        dst = dest / "scene.json"
        _scene_info.write_scene_info(info, dst)
        got["scene.json"] = str(dst)
    except Exception as exc:
        logger.warning("[%s] could not rebuild scene.json: %s", scene_id, exc)
        copy(p["info"], "scene.json", "scene.json")

    return got


# ---------------------------------------------------------------------------
# scene selection
# ---------------------------------------------------------------------------
def room_extent(layout_path: str | Path) -> tuple[float, float]:
    """Return (width, depth) in metres for a scene.

    Uses the real interior bounds from ``StructureMesh/floor.glb`` when
    available; otherwise falls back to the axis-aligned footprint spanned by
    all object bboxes in ``layout.json``.
    """
    layout_path = Path(layout_path)
    interior = _scene_info.structure_mesh_bounds(layout_path)
    if interior is not None:
        return float(interior["width"]), float(interior["depth"])

    # Fallback: span of object footprints.
    try:
        objs = json.loads(layout_path.read_text(encoding="utf-8"))
    except Exception:
        return (0.0, 0.0)
    xs: list[float] = []
    ys: list[float] = []
    for o in objs:
        b = o.get("bbox")
        if b is None or len(b) < 5:
            continue
        cx, cy, dx, dy = b[0], b[1], b[3], b[4]
        xs += [cx - dx / 2, cx + dx / 2]
        ys += [cy - dy / 2, cy + dy / 2]
    if not xs:
        return (0.0, 0.0)
    return float(max(xs) - min(xs)), float(max(ys) - min(ys))


def _extent_ok(scene_id: str, min_room_extent_m: float) -> bool:
    """Return True if a scene's smaller floor dimension >= threshold."""
    if min_room_extent_m <= 0:
        return True
    layout = paths_for(scene_id)["layout"]
    if not layout.exists():
        return False
    w, d = room_extent(layout)
    return min(w, d) >= min_room_extent_m


def resolve_scenes(
    n: int = 0,
    seed: int = 0,
    datasets: list[str] | None = None,
    scene_ids: list[str] | None = None,
    dataset_filter: list[str] | None = None,
    min_room_extent_m: float = 0.0,
) -> list[str]:
    """Resolve CLI scene selection into a flat list of scene IDs.

    Priority:
      1. explicit ``scene_ids`` (filtered by ``min_room_extent_m``)
      2. sample ``n`` random scenes per dataset with ``seed``,
         keeping only scenes whose smaller floor dimension is at least
         ``min_room_extent_m``.
    """
    if scene_ids:
        kept = [sid for sid in scene_ids if _extent_ok(sid, min_room_extent_m)]
        dropped = set(scene_ids) - set(kept)
        if dropped:
            logger.warning(
                "dropped %d scene(s) smaller than %.2fm: %s",
                len(dropped), min_room_extent_m, sorted(dropped),
            )
        return kept

    inventory = _sampler.scan_all(DATA / "Layout_info")
    wanted = set(datasets or _sampler.DATASETS)
    if dataset_filter:
        wanted &= set(dataset_filter)
    inventory = {k: v for k, v in inventory.items() if k in wanted}

    rng = random.Random(seed)
    picked: dict[str, list[str]] = {name: [] for name in _sampler.DATASETS if name in wanted}
    for name in _sampler.DATASETS:
        if name not in wanted:
            continue
        ids = inventory.get(name, [])
        if not ids:
            continue
        # Reservoir-sample until we have n valid scenes or exhaust the pool.
        pool = ids[:]
        rng.shuffle(pool)
        chosen: list[str] = []
        for sid in pool:
            if _extent_ok(sid, min_room_extent_m):
                chosen.append(sid)
                if len(chosen) >= n:
                    break
        chosen.sort()
        picked[name] = chosen
        if len(chosen) < n:
            logger.warning(
                "%s: only %d/%d scenes meet min_room_extent_m >= %.2fm",
                name, len(chosen), n, min_room_extent_m,
            )
    return [sid for name in _sampler.DATASETS for sid in picked.get(name, [])]


def scene_inventory() -> dict[str, list[str]]:
    """Return {dataset: [scene_id, ...]} for all known datasets."""
    return _sampler.scan_all(DATA / "Layout_info")


# ---------------------------------------------------------------------------
# full scene run
# ---------------------------------------------------------------------------
def run_scene(
    scene_id: str,
    *,
    resume: bool = False,
    skip_render: bool = False,
    skip_topdown: bool = False,
) -> dict[str, Any]:
    """Run compose → render → topdown → info → normalize for one scene."""
    p = paths_for(scene_id)
    status: dict[str, Any] = {"scene_id": scene_id, "stages": {}}
    stages = [
        ("compose", lambda: stage_compose(scene_id)),
        ("render", lambda: stage_render(scene_id) if not skip_render else True),
        ("topdown", lambda: stage_topdown(scene_id) if not skip_topdown else True),
        ("info", lambda: stage_info(scene_id)),
        ("normalize", lambda: bool(assemble_normalized(scene_id))),
    ]
    for name, fn in stages:
        t0 = time.time()
        if resume:
            if name == "compose" and p["composed"].exists():
                status["stages"][name] = "skipped(exists)"
                continue
            if name == "render" and p["perspective"].exists():
                status["stages"][name] = "skipped(exists)"
                continue
            if name == "topdown" and p["topdown"].exists():
                status["stages"][name] = "skipped(exists)"
                continue
            if name == "info" and p["info"].exists():
                status["stages"][name] = "skipped(exists)"
                continue
            if name == "normalize" and (p["normalized"] / "scene.usd").exists() and (
                p["normalized"] / "perspective.png").exists() and (
                p["normalized"] / "topdown.png").exists():
                status["stages"][name] = "skipped(exists)"
                continue
        try:
            ok = fn()
        except Exception as exc:
            logger.exception("[%s] %s raised", scene_id, name)
            ok = False
            status["stages"][name] = f"error({type(exc).__name__})"
            continue
        dt = time.time() - t0
        status["stages"][name] = f"ok({dt:.1f}s)" if ok else f"failed({dt:.1f}s)"
        logger.info("[%s] %s -> %s", scene_id, name, status["stages"][name])

    status["status"] = "complete" if all(
        v.startswith("ok") or v.startswith("skipped") for v in status["stages"].values()
    ) else "incomplete"
    return status


# ---------------------------------------------------------------------------
# batch manifest helpers
# ---------------------------------------------------------------------------
def flush_manifest(
    manifest_path: Path,
    results: list[dict[str, Any]],
    picked: dict[str, list[str]],
    t_start: float,
) -> None:
    doc = {
        "started": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(t_start)),
        "updated": time.strftime("%Y-%m-%d %H:%M:%S"),
        "sample": picked,
        "results": results,
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = manifest_path.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(doc, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, manifest_path)

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
from . import evaluate_graph as _evaluate_graph
from . import glb_to_usd as _glb_to_usd
from . import place_go2 as _place_go2  # noqa: F401
from . import questions as _questions
from . import render_multi as _render_multi
from . import sampler as _sampler
from . import scene_graph as _scene_graph
from . import scene_info as _scene_info
from . import topdown as _topdown
from . import vlm_annotate as _vlm_annotate

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
        "graph": OUTPUT / "graph" / f"{flat}.json",
    }


# ---------------------------------------------------------------------------
# environment defaults
# ---------------------------------------------------------------------------
def blender_path() -> str:
    configured = os.environ.get("BLENDER")
    if configured:
        return configured
    installed = shutil.which("blender")
    if installed:
        return installed
    legacy = Path("/home/ubadmin/tools/blender/blender-5.1.2-linux-x64/blender")
    if legacy.is_file() and os.access(legacy, os.X_OK):
        return str(legacy)
    raise FileNotFoundError("Blender not found on PATH; set BLENDER to its executable path")


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
        if missing:
            logger.error(
                "[%s] incomplete composition: %d missing object instance(s); "
                "enable auto-fill or prepare the models manually",
                scene_id, len(missing),
            )
            return False
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
    blender = blender_path()
    # System Blender discovers its Python through PATH; prefer sibling executables.
    binary = shutil.which(blender) or blender
    env["PATH"] = str(Path(binary).resolve().parent) + os.pathsep + env.get("PATH", os.defpath)
    cmd = [
        blender,
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


def stage_usd(scene_id: str) -> Path | None:
    """Convert composed GLB to USD in the normalized folder."""
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
    return usd_path


def _multi_render_paths(scene_id: str, n_views: int = 8) -> dict[str, Path]:
    """Expected orbit and top-down image paths for a scene."""
    flat = slug(scene_id)
    render_dir = paths_for(scene_id)["render_dir"]
    views = {
        f"view_{k}": render_dir / f"{flat}__view_{k}.png"
        for k in range(n_views)
    }
    views["topdown"] = render_dir / f"{flat}__topdown.png"
    return views


def stage_render_multi(scene_id: str, n_views: int = 8, height: float = 1.6) -> bool:
    """Render a ring of orbit views + top-down for VLM annotation.

    Mirrors :func:`stage_render` but bootstraps :mod:`internscenes.render_multi`
    (via ``INTERN_RENDER_FILE``) so a single Blender session produces N orbit
    views + a top-down.  Depends on the composed GLB; degrades to a no-op
    warning when the GLB is missing (the graph stage then falls back to the
    deterministic affordances).
    """
    p = paths_for(scene_id)
    if not p["composed"].exists():
        logger.warning("[%s] render_multi: no composed GLB", scene_id)
        return False
    p["render_dir"].mkdir(parents=True, exist_ok=True)

    script = ROOT / "src" / "internscenes" / "_render_in_blender.py"
    env = os.environ.copy()
    env["INTERN_VENV_PY"] = venv_python()
    env["INTERN_SRC_ROOT"] = str(ROOT / "src")
    env["INTERN_RENDER_FILE"] = "render_multi.py"
    blender = blender_path()
    binary = shutil.which(blender) or blender
    env["PATH"] = str(Path(binary).resolve().parent) + os.pathsep + env.get("PATH", os.defpath)
    cmd = [
        blender,
        "--background",
        "--python",
        str(script),
        "--",
        "--glb",
        str(p["composed"]),
        "--out",
        str(p["render_dir"]),
        "--engine=EEVEE",
        f"--views={n_views}",
        f"--height={height}",
        f"--scene={scene_id}",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, env=env)
    if proc.returncode != 0:
        logger.error("[%s] render_multi failed (rc=%d): %s",
                     scene_id, proc.returncode, proc.stderr[-800:])
        return False
    expected = _multi_render_paths(scene_id, n_views)
    missing = [name for name, path in expected.items() if not path.is_file()]
    if missing:
        logger.error("[%s] render_multi did not produce expected images: %s",
                     scene_id, ", ".join(missing))
        return False
    logger.info("[%s] render_multi: %d view(s)", scene_id, len(expected))
    return True


def stage_graph(
    scene_id: str,
    vlm: bool = False,
    skip_render_multi: bool = False,
) -> bool:
    """Build the scene graph JSON (deterministic + optional VLM layer).

    When ``vlm`` is True, the VLM annotation layer is applied (falls back to
    deterministic rules when no endpoint is configured).  Writes
    ``output/graph/<scene>.json`` and copies it into the normalized folder.
    """
    p = paths_for(scene_id)
    if not p["layout"].exists():
        logger.error("[%s] graph: no layout.json", scene_id)
        return False
    try:
        records = _scene_info.load_layout(p["layout"])
        for i, r in enumerate(records):
            r2 = dict(r)
            r2["_idx"] = i
            records[i] = r2
        vlm_result = None
        cfg = _vlm_annotate.VLMConfig.from_env() if vlm else None
        render_paths = _multi_render_paths(scene_id)
        if vlm:
            if cfg is not None and cfg.endpoint is not None and not all(
                path.is_file() for path in render_paths.values()
            ):
                if skip_render_multi:
                    logger.error(
                        "[%s] VLM endpoint configured but multi-view renders are "
                        "missing and rendering was skipped",
                        scene_id,
                    )
                    return False
                if not stage_render_multi(scene_id):
                    return False
            views = {
                name: str(path) for name, path in render_paths.items()
                if path.is_file()
            }
            vlm_result = _vlm_annotate.annotate(
                scene_id, records, cfg, views,
            )
        graph = _scene_graph.build_scene_graph(
            scene_id,
            p["layout"],
            vlm_result=vlm_result,
            render_views={name: str(path) for name, path in render_paths.items()
                          if path.is_file()},
        )
        _scene_graph.write_scene_graph(graph, p["graph"])
        p["normalized"].mkdir(parents=True, exist_ok=True)
        shutil.copy2(p["graph"], p["normalized"] / "scene_graph.json")
        # self-consistency gate
        rep = _vlm_annotate.consistency_check(graph)
        if not rep["ok"]:
            logger.warning("[%s] graph inconsistency: %d issues", scene_id,
                           rep["num_issues"])
        return p["graph"].exists()
    except Exception as exc:
        logger.exception("[%s] graph failed", scene_id)
        return False


def stage_questions(scene_id: str, n: int = 5, seed: int | None = None) -> bool:
    """Generate object-finding questions into the normalized folder."""
    try:
        qs = _questions.generate_for_scene(scene_id, n=n, seed=seed)
    except Exception as exc:
        logger.exception("[%s] question generation failed", scene_id)
        return False
    return len(qs) > 0


def _stage_plan_questions(
    scene_id: str,
    grid_res: float = 0.05,
) -> bool:
    """Run A* path planning for every question of a scene."""
    from . import path_planner
    try:
        summary = path_planner.plan_for_scene(scene_id, grid_res=grid_res)
        return summary["successful"] == summary["num_questions"]
    except Exception:
        logger.exception("[%s] plan-questions failed", scene_id)
        return False


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
    """Download and verify missing models referenced by the selected layouts."""
    if not scene_ids:
        raise ValueError("auto_fill_assets requires at least one scene")
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
    copy(p["graph"], "scene_graph.json", "graph")

    usd_path = stage_usd(scene_id)
    if usd_path is not None and usd_path.exists():
        dst = dest / "scene.usd"
        if usd_path.resolve() != dst.resolve():
            shutil.copy2(usd_path, dst)
        got["usd"] = str(dst)

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
def _can_resume_composed(scene_id: str) -> bool:
    p = paths_for(scene_id)
    if not all(p[key].is_file() for key in ("layout", "composed", "missing")):
        return False
    try:
        report = json.loads(p["missing"].read_text(encoding="utf-8"))
        verified = (
            report["scene_id"] == scene_id
            and report["num_missing"] == 0
            and report["missing"] == []
            and p["missing"].stat().st_mtime_ns >= max(
                p["layout"].stat().st_mtime_ns, p["composed"].stat().st_mtime_ns
            )
        )
        return verified and not _download._filter_existing(_download._collect_uids([scene_id]))
    except (OSError, ValueError, KeyError, TypeError):
        logger.warning("[%s] cannot verify composition for resume; rebuilding", scene_id)
        return False


def run_scene(
    scene_id: str,
    *,
    resume: bool = False,
    skip_render: bool = False,
    skip_topdown: bool = False,
    skip_questions: bool = False,
    skip_graph: bool = False,
    skip_render_multi: bool = False,
    vlm: bool = False,
    questions_n: int = 5,
    questions_seed: int | None = None,
    plan_questions: bool = False,
    plan_questions_grid_res: float = 0.05,
    auto_fill: bool = True,
) -> dict[str, Any]:
    """Run the configured scene stages from composition through questions.

    Missing models are downloaded and verified before composition by default.
    Set ``auto_fill=False`` to use local assets only. ``vlm=True`` enables
    multi-view rendering and VLM annotation (deterministic fallback when no
    endpoint is configured).
    """
    p = paths_for(scene_id)
    status: dict[str, Any] = {"scene_id": scene_id, "stages": {}}
    stages = [
        ("compose", lambda: stage_compose(scene_id)),
        ("render", lambda: stage_render(scene_id) if not skip_render else True),
        ("render_multi", lambda: stage_render_multi(scene_id)),
        ("topdown", lambda: stage_topdown(scene_id) if not skip_topdown else True),
        ("info", lambda: stage_info(scene_id)),
        ("graph", lambda: stage_graph(
            scene_id, vlm=vlm, skip_render_multi=skip_render_multi
        )),
        ("normalize", lambda: bool(assemble_normalized(scene_id))),
        ("questions", lambda: stage_questions(scene_id, n=questions_n, seed=questions_seed) if not skip_questions else True),
        ("plan_questions", lambda: _stage_plan_questions(scene_id, grid_res=plan_questions_grid_res) if plan_questions and not skip_questions else True),
    ]
    if auto_fill:
        if auto_fill_assets([scene_id]) != 0:
            logger.error("[%s] auto-fill verification failed", scene_id)
            status["stages"]["auto_fill"] = "failed(verification)"
            for name, _ in stages:
                status["stages"][name] = "blocked(auto_fill)"
            status["status"] = "incomplete"
            return status
        status["stages"]["auto_fill"] = "ok(verified)"
    for name, fn in stages:
        t0 = time.time()
        if name == "render_multi" and (not vlm or skip_render_multi):
            status["stages"][name] = "skipped(not_requested)"
            continue
        if name == "graph" and skip_graph:
            status["stages"][name] = "skipped(not_requested)"
            continue
        if resume:
            if name == "compose" and _can_resume_composed(scene_id):
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
            if name == "render_multi" and all(
                path.is_file() for path in _multi_render_paths(scene_id).values()
            ):
                status["stages"][name] = "skipped(exists)"
                continue
            if name == "graph" and p["graph"].exists():
                status["stages"][name] = "skipped(exists)"
                continue
            if name == "questions" and (p["normalized"] / "questions.jsonl").exists():
                status["stages"][name] = "skipped(exists)"
                continue
            if name == "plan_questions" and (p["normalized"] / "questions" / "summary.json").exists():
                status["stages"][name] = "skipped(exists)"
                continue
        try:
            ok = fn()
        except Exception as exc:
            logger.exception("[%s] %s raised", scene_id, name)
            ok = False
            status["stages"][name] = f"error({type(exc).__name__})"
        else:
            dt = time.time() - t0
            status["stages"][name] = f"ok({dt:.1f}s)" if ok else f"failed({dt:.1f}s)"
        logger.info("[%s] %s -> %s", scene_id, name, status["stages"][name])
        if name == "compose":
            if not ok:
                for downstream, _ in stages[1:]:
                    status["stages"][downstream] = "blocked(compose)"
                break
            # Rebuilt geometry invalidates all downstream outputs, even on resume.
            resume = False

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

"""Generate English natural-language object-finding questions for a scene.

Each scene produces up to 5 questions of the form
"Please find the <color> <category>".  Targets are chosen to be at a
medium-to-long distance from the Unitree Go2 starting position, with a
strong preference for objects whose representative colour is known.
"""
from __future__ import annotations

import bisect
import json
import logging
import math
import random
from pathlib import Path
from typing import Any

from . import pipeline

logger = logging.getLogger(__name__)


_COLOR_NAMES: list[tuple[tuple[float, float, float], str]] = [
    ((1.0, 0.0, 0.0), "red"),
    ((0.0, 1.0, 0.0), "green"),
    ((0.0, 0.0, 1.0), "blue"),
    ((1.0, 1.0, 0.0), "yellow"),
    ((1.0, 0.5, 0.0), "orange"),
    ((0.5, 0.0, 0.5), "purple"),
    ((1.0, 0.7, 0.7), "pink"),
    ((0.5, 0.3, 0.1), "brown"),
    ((0.5, 0.5, 0.5), "gray"),
    ((1.0, 1.0, 1.0), "white"),
    ((0.0, 0.0, 0.0), "black"),
]


_TEMPLATES: list[str] = [
    "Please find the {color} {category}.",
    "Where is the {color} {category}?",
    "Navigate to the {color} {category}.",
    "I need to find the {color} {category}.",
    "Go to the {color} {category}.",
]

_TEMPLATES_NO_COLOR: list[str] = [
    "Please find the {category}.",
    "Where is the {category}?",
    "Navigate to the {category}.",
    "I need to find the {category}.",
    "Go to the {category}.",
]


def _rgb_to_name(rgb: dict[str, float]) -> str | None:
    """Map an RGB triple to the closest basic-colour name."""
    best = None
    best_dist = float("inf")
    r, g, b = rgb.get("r", 0.0), rgb.get("g", 0.0), rgb.get("b", 0.0)
    for ref, name in _COLOR_NAMES:
        dist = math.sqrt(
            (r - ref[0]) ** 2 + (g - ref[1]) ** 2 + (b - ref[2]) ** 2
        )
        if dist < best_dist:
            best_dist = dist
            best = name
    return best


def _distance_to_go2(obj: dict[str, Any], go2_pos: dict[str, float]) -> float:
    pos = obj["position_m"]
    return math.hypot(
        pos["x"] - go2_pos["x"],
        pos["y"] - go2_pos["y"],
    )


def _percentile_rank(value: float, sorted_values: list[float]) -> float:
    if len(sorted_values) <= 1:
        return 0.5
    idx = bisect.bisect_left(sorted_values, value)
    return idx / (len(sorted_values) - 1)


def select_targets(
    objects: list[dict[str, Any]],
    go2_pos: dict[str, float],
    n: int = 5,
    seed: int | None = None,
) -> list[tuple[float, float, dict[str, Any]]]:
    """Pick ``n`` objects that are medium-to-far from the Go2 start pose.

    Returns a list of ``(score, distance_m, object)`` sorted by preference.
    """
    valid = [o for o in objects if o.get("valid") and "position_m" in o]
    if not valid:
        return []

    distances = [_distance_to_go2(o, go2_pos) for o in valid]
    sorted_distances = sorted(distances)

    scored: list[tuple[float, float, dict[str, Any]]] = []
    for obj, d in zip(valid, distances):
        p = _percentile_rank(d, sorted_distances)
        # optimal around the 60th percentile (medium-to-long)
        score = 1.0 - abs(p - 0.6)
        if obj.get("color") is not None:
            score += 0.3
        scored.append((score, d, obj))

    scored.sort(key=lambda x: (-x[0], -x[1]))

    chosen: list[tuple[float, float, dict[str, Any]]] = []
    category_counts: dict[str, int] = {}
    for item in scored:
        cat = item[2].get("category", "unknown")
        if category_counts.get(cat, 0) >= 2:
            continue
        chosen.append(item)
        category_counts[cat] = category_counts.get(cat, 0) + 1
        if len(chosen) >= n:
            break

    # If diversity constraints left us short, relax them.
    if len(chosen) < n:
        chosen_ids = {id(o[2]) for o in chosen}
        for item in scored:
            if id(item[2]) in chosen_ids:
                continue
            chosen.append(item)
            chosen_ids.add(id(item[2]))
            if len(chosen) >= n:
                break

    rng = random.Random(seed)
    rng.shuffle(chosen)
    return chosen


def build_question(
    scene_id: str,
    obj: dict[str, Any],
    go2_pos: dict[str, float],
    distance_m: float,
    rng: random.Random,
) -> dict[str, Any]:
    """Create one JSON record for an object-finding task."""
    color = obj.get("color")
    color_name = _rgb_to_name(color) if color else None
    category = obj.get("category", "object")

    if color_name is not None:
        template = rng.choice(_TEMPLATES)
        question = template.format(color=color_name, category=category)
    else:
        template = rng.choice(_TEMPLATES_NO_COLOR)
        question = template.format(category=category)

    return {
        "scene_id": scene_id,
        "question": question,
        "question_en": question,
        "target_category": category,
        "target_color": color_name,
        "target_color_en": color_name,
        "target_object": obj,
        "target_position_m": obj["position_m"],
        "go2_position_m": go2_pos,
        "distance_m": round(float(distance_m), 3),
    }


def generate_for_scene(
    scene_id: str,
    out_path: str | Path | None = None,
    n: int = 5,
    seed: int | None = None,
) -> list[dict[str, Any]]:
    """Generate ``n`` questions for ``scene_id`` and write them as JSONL."""
    p = pipeline.paths_for(scene_id)
    scene_json = p["normalized"] / "scene.json"
    if not scene_json.exists():
        scene_json = p["info"]
    if not scene_json.exists():
        logger.error("[%s] no scene.json found", scene_id)
        return []

    data = json.loads(scene_json.read_text(encoding="utf-8"))
    go2 = data.get("go2_placement", {})
    if not go2.get("valid"):
        logger.warning("[%s] Go2 placement invalid, skipping", scene_id)
        return []
    go2_pos = go2["position_m"]

    targets = select_targets(data.get("objects", []), go2_pos, n=n, seed=seed)
    if not targets:
        logger.warning("[%s] no suitable target objects", scene_id)
        return []

    rng = random.Random(seed)
    questions = [
        build_question(scene_id, obj, go2_pos, dist, rng)
        for _, dist, obj in targets
    ]

    if out_path is None:
        out_path = pipeline.OUTPUT / "questions" / f"{pipeline.slug(scene_id)}.jsonl"
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as fh:
        for q in questions:
            fh.write(json.dumps(q, ensure_ascii=False) + "\n")
    logger.info("[%s] wrote %d questions -> %s", scene_id, len(questions), out_path)
    return questions


def generate_for_scenes(
    scene_ids: list[str],
    out_dir: str | Path | None = None,
    n: int = 5,
    seed: int | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Generate questions for many scenes and also write a merged JSONL."""
    out_dir = Path(out_dir or pipeline.OUTPUT / "questions")
    out_dir.mkdir(parents=True, exist_ok=True)
    results: dict[str, list[dict[str, Any]]] = {}
    all_questions: list[dict[str, Any]] = []
    for sid in scene_ids:
        path = out_dir / f"{pipeline.slug(sid)}.jsonl"
        qs = generate_for_scene(sid, out_path=path, n=n, seed=seed)
        results[sid] = qs
        all_questions.extend(qs)
    if all_questions:
        merged = out_dir / "all.jsonl"
        with merged.open("w", encoding="utf-8") as fh:
            for q in all_questions:
                fh.write(json.dumps(q, ensure_ascii=False) + "\n")
        logger.info("merged %d questions -> %s", len(all_questions), merged)
    return results

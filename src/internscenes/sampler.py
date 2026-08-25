"""Deterministic scene sampling for the InternScenes batch pipeline.

Scans ``data/Layout_info/<dataset>/`` for every folder that contains a
``layout.json`` (that folder *is* a scene) and, for each dataset (category),
randomly selects up to ``n`` of them. Selection is seed-controlled so a given
seed always yields the same sample — useful for reproducible batch runs and
for debugging a specific scene without re-rolling the dice.
"""

from __future__ import annotations

import json
import logging
import random
from pathlib import Path
from typing import Any

try:  # imported as part of the ``internscenes`` package
    from . import scene_info  # noqa: F401  (shared DATASETS / helpers)
except ImportError:  # imported as a standalone module on sys.path
    import scene_info  # type: ignore

logger = logging.getLogger(__name__)

DATASETS: tuple[str, ...] = scene_info.DATASETS


def scan_dataset(dataset_dir: Path) -> list[str]:
    """Return every scene id under ``dataset_dir`` (folders with layout.json).

    A scene id is the path relative to the dataset root, in POSIX form, e.g.
    ``Training/43896449`` for ARKitScenes or ``region51`` for Matterport3D.
    """
    if not dataset_dir.is_dir():
        return []
    ids: list[str] = []
    for path in dataset_dir.rglob("layout.json"):
        rel = path.parent.relative_to(dataset_dir)
        ids.append("/".join(rel.parts))
    ids.sort()
    return ids


def scan_all(layout_dir: Path) -> dict[str, list[str]]:
    """Return {dataset: [full_scene_id, ...]} for every known dataset.

    Scene ids are **full Layout_info-relative paths**, e.g. ``scannet/scene0013_00``
    or ``matterport3d/uNb9QFRL6hY/region9`` so they can be used uniformly by the
    compose step (which needs ``LAYOUT_DIR/<id>/layout.json``) and the output
    tree.
    """
    inventory: dict[str, list[str]] = {}
    for name in DATASETS:
        d = layout_dir / name
        rel = scan_dataset(d)
        inventory[name] = [f"{name}/{sid}" for sid in rel]
    return inventory


def sample(
    inventory: dict[str, list[str]],
    n: int = 50,
    seed: int = 0,
) -> dict[str, list[str]]:
    """Randomly pick up to ``n`` scene ids per dataset.

    Parameters
    ----------
    inventory:
        Output of :func:`scan_all`.
    n:
        Number of scenes to sample per category (capped by the dataset size).
    seed:
        RNG seed for reproducibility.
    """
    rng = random.Random(seed)
    picked: dict[str, list[str]] = {}
    for name in DATASETS:
        ids = inventory.get(name, [])
        chosen = rng.sample(ids, min(n, len(ids)))
        chosen.sort()
        picked[name] = chosen
        logger.info("sampled %d/%d scenes from %s", len(chosen), len(ids), name)
    return picked


def save_sample(sampled: dict[str, list[str]], out_path: str | Path) -> None:
    """Persist the chosen sample to JSON so a batch run is reproducible."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as fh:
        json.dump(sampled, fh, ensure_ascii=False, indent=2)
    logger.info("saved sample -> %s", out_path)


if __name__ == "__main__":  # pragma: no cover
    import argparse

    logging.basicConfig(level=logging.INFO)
    ap = argparse.ArgumentParser(description="Sample N random scenes per category")
    ap.add_argument("--layout-dir", default="data/Layout_info")
    ap.add_argument("-n", type=int, default=50)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", default="output/sample_manifest.json")
    args = ap.parse_args()
    inv = scan_all(Path(args.layout_dir))
    picked = sample(inv, n=args.n, seed=args.seed)
    save_sample(picked, args.out)
    for name, ids in picked.items():
        print(f"{name}: {len(ids)} scenes")
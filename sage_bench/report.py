"""Generate the SAGE-Bench dataset card + charts from the results.

Reads ``results/leaderboard.json`` and ``dataset/manifest.json`` and produces:
  * ``results/dataset_card.csv``      -- one row per scene (dataset / sizes)
  * ``results/fig_leaderboard.png``   -- bar chart of the factorised metrics
  * ``results/fig_per_dataset.png``   -- relation F1 by method x dataset
  * ``results/fig_pareto.png``        -- accuracy-vs-efficiency Pareto frontier
"""
from __future__ import annotations

import json
import pathlib

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent
RESULTS = ROOT / "results"
MANIFEST = ROOT / "dataset" / "manifest.json"

# colour per method (robotic / CV palette: navy + neon)
COLORS = {
    "vlm_augmented": "#00e6c3",
    "geometric_3d": "#2f81f7",
    "semantic": "#a371f7",
    "knn_spatial": "#f77933",
    "random": "#8b949e",
}
METHOD_ORDER = ["vlm_augmented", "geometric_3d", "semantic", "knn_spatial", "random"]


def _load() -> dict:
    return json.load((RESULTS / "leaderboard.json").open(encoding="utf-8"))


def write_dataset_card(report: dict) -> None:
    manifest = json.load(MANIFEST.open(encoding="utf-8"))
    refs = manifest.get("refs", manifest if isinstance(manifest, list) else [])
    with open(RESULTS / "dataset_card.csv", "w", encoding="utf-8") as fh:
        fh.write("scene_id,dataset,num_objects,num_nodes,num_edges\n")
        for r in refs:
            fh.write(f"{r['scene_id']},{r['dataset']},{r['num_objects']},"
                     f"{r['num_nodes']},{r['num_edges']}\n")
    print(f"  wrote {RESULTS / 'dataset_card.csv'}")


def fig_leaderboard(report: dict) -> None:
    board = {r["method"]: r for r in report["leaderboard"]}
    methods = [m for m in METHOD_ORDER if m in board]
    metrics = [
        ("relations_F1", "relation F1"),
        ("relations_precision", "relation P"),
        ("relations_recall", "relation R"),
        ("nodes_macro_F1", "node F1"),
        ("spatial_F1", "spatial F1"),
        ("mRecall@8", "mRecall@8"),
    ]
    x = range(len(metrics))
    w = 0.8 / len(methods)
    fig, ax = plt.subplots(figsize=(9.0, 5.2))
    for i, m in enumerate(methods):
        vals = [board[m][key] for key, _ in metrics]
        ax.bar([xi + (i - (len(methods) - 1) / 2) * w for xi in x],
               vals, width=w, label=m, color=COLORS.get(m, "#888"))
    ax.set_xticks(list(x))
    ax.set_xticklabels([label for _, label in metrics], fontsize=9)
    ax.set_ylabel("score (0–1)")
    ax.set_ylim(0, 1.05)
    ax.set_title("SAGE-Bench — factorised metrics by method\n(12 scenes, 4 datasets)",
                 fontsize=11)
    ax.grid(axis="y", alpha=0.3)
    ax.legend(fontsize=8, ncol=2, loc="upper right")
    fig.tight_layout()
    fig.savefig(RESULTS / "fig_leaderboard.png", dpi=150)
    print(f"  wrote {RESULTS / 'fig_leaderboard.png'}")


def fig_per_dataset(report: dict) -> None:
    # per-dataset relation F1
    from collections import defaultdict
    agg = defaultdict(dict)
    for ps in report["per_scene"]:
        ds = ps["scene_id"].split("/", 1)[0]
        for name, m in ps["by_method"].items():
            if "error" not in m:
                agg[ds].setdefault(name, []).append(m["relations"]["F1"])
    datasets = sorted(agg)
    methods = [m for m in METHOD_ORDER if any(m in agg[d] for d in datasets)]
    x = range(len(datasets))
    w = 0.8 / len(methods)
    fig, ax = plt.subplots(figsize=(9.0, 5.0))
    for i, m in enumerate(methods):
        vals = [sum(agg[d].get(m, [0.0])) / len(agg[d].get(m, [1])) for d in datasets]
        ax.bar([xi + (i - (len(methods) - 1) / 2) * w for xi in x],
               vals, width=w, label=m, color=COLORS.get(m, "#888"))
    ax.set_xticks(list(x))
    ax.set_xticklabels(datasets, fontsize=9)
    ax.set_ylabel("relation F1")
    ax.set_ylim(0, 1.05)
    ax.set_title("Relation F1 by method and dataset\n(stability across the 4 source datasets)",
                 fontsize=11)
    ax.grid(axis="y", alpha=0.3)
    ax.legend(fontsize=8, ncol=3, loc="lower center", bbox_to_anchor=(0.5, -0.12))
    fig.tight_layout()
    fig.savefig(RESULTS / "fig_per_dataset.png", dpi=150)
    print(f"  wrote {RESULTS / 'fig_per_dataset.png'}")


def fig_pareto(report: dict) -> None:
    # accuracy vs efficiency (cost = bytes + 8*edges)
    pts = []
    # use the first scene's per-method metrics as a representative point set
    first = report["per_scene"][0]["by_method"]
    for name, m in first.items():
        if "error" in m:
            continue
        acc = (m["relations"]["F1"] + m["nodes"]["macro_F1"] + m["spatial"]["F1"]) / 3.0
        cost = m["efficiency"]["bytes"] + m["efficiency"]["num_edges"] * 8
        pts.append((name, acc, cost))
    # also use the aggregate leaderboard for the accuracy axis
    fig, ax = plt.subplots(figsize=(7.4, 5.2))
    for name, acc, cost in pts:
        ax.scatter(cost, acc, color=COLORS.get(name, "#888"), s=90, zorder=3)
        ax.annotate(name, (cost, acc), textcoords="offset points",
                    xytext=(6, 4), fontsize=8)
    ax.set_xlabel("efficiency cost (bytes + 8 × edges)")
    ax.set_ylabel("accuracy (mean of rel-F1, node-F1, spatial-F1)")
    ax.set_title("Accuracy vs. efficiency — Pareto view\n(single representative scene)",
                 fontsize=11)
    ax.grid(alpha=0.3)
    ax.set_xscale("log")
    fig.tight_layout()
    fig.savefig(RESULTS / "fig_pareto.png", dpi=150)
    print(f"  wrote {RESULTS / 'fig_pareto.png'}")


def main() -> None:
    report = _load()
    write_dataset_card(report)
    fig_leaderboard(report)
    fig_per_dataset(report)
    fig_pareto(report)
    # stage the charts into the docs site so the build copies them
    try:
        import shutil
        figs = ROOT.parent / "docs-site" / "assets" / "figs"
        figs.mkdir(parents=True, exist_ok=True)
        for png in ("fig_leaderboard.png", "fig_per_dataset.png", "fig_pareto.png"):
            shutil.copy2(RESULTS / png, figs / png)
        print(f"  staged charts -> {figs}")
    except Exception as e:  # noqa: BLE001
        print(f"  (chart staging skipped: {e})")
    print("done.")


if __name__ == "__main__":
    main()

---
title: Benchmark
description: A small scene-graph dataset and five-method evaluation on real InternScenes scenes.
---

# Benchmark

SAGE-Bench ships a **small, reproducible dataset** plus a harness that
evaluates **five scene-graph-building methods** against a deterministic
reference ("gold") graph, using the [factorised
metrics](evaluation.html). It answers the question a benchmark must answer:
*given the same scene, which way of building a scene graph is closest to the
best graph we can produce?*

Everything lives in the [`sage_bench/`](https://github.com/DobricLilujun/InternScenes2isaacsim/tree/main/sage_bench)
package of the main repository.

## The reference (gold) graph

For each scene the reference is the **deterministic oracle** from
`scene_graph.build_scene_graph` — metric + hierarchy + semantic edges derived
from `layout.json`. It is the strongest graph we can produce without a trained
model, so it is a reproducible, well-defined target (not hand annotation).

## The dataset

`dataset.py` selects **12 scenes** — 3 from each of the four source datasets —
chosen to span the object-count range (small / medium / large, ~5–212 nodes):

| dataset | scenes | object range |
| --- | --- | --- |
| ScanNet | 3 | 3–140 |
| 3RScan | 3 | 6–212 |
| ARKitScenes | 3 | 5–93 |
| Matterport3D | 3 | 5–157 |

```sh
python -m sage_bench.dataset --per-dataset 3   # -> sage_bench/dataset/
```

## The 5 methods

Running the *actual* external SOTA systems (GPU VLMs, trained detectors) is not
feasible in a CPU-only environment, so each method is a **faithful,
deterministic proxy for its paradigm**, built on the same InternScenes data —
then measured against the reference by the shared harness, exactly as a
benchmark does.

| method | what it builds | paradigm |
| --- | --- | --- |
| `geometric_3d` | metric + hierarchy edges (spatial / containment), no category semantics | classical **3D scene graph** (boxes / point clouds) |
| `semantic` | semantic + hierarchy edges, no metric | **ontology / category-driven** scene graph |
| `vlm_augmented` | deterministic base + a **VLM functional / affordance** layer (interactive parts + affordances) | **VLM / LLM** scene graph (image/text-grounded) |
| `knn_spatial` | only `distance` / `near` / `touching` | **k-nearest-neighbour / spatial** scene graph |
| `random` | random edges between nodes | **null / random baseline** |

## Results

Ranked by **relation F1** across the 12-scene dataset:

| rank | method | rel. F1 | P | R | node F1 | spatial F1 | mRecall@8 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | **vlm_augmented** | **0.992** | 0.985 | 1.000 | 0.869 | 0.750 | 1.000 |
| 2 | geometric_3d | 0.956 | 1.000 | 0.923 | 1.000 | 0.750 | 0.930 |
| 3 | semantic | 0.559 | 1.000 | 0.464 | 1.000 | 0.000 | 0.502 |
| 4 | knn_spatial | 0.421 | 0.750 | 0.295 | 1.000 | 0.544 | 0.360 |
| 5 | random | 0.013 | 0.018 | 0.011 | 1.000 | 0.015 | 0.294 |

The ranking is **stable across all four datasets** (per-dataset relation F1:
`vlm` ≈ 0.997, `geometric` ≈ 0.99, `knn` ≈ 0.57, `semantic` ≈ 0.18,
`random` ≈ 0.03).

<div class="figure">
<img src="assets/figs/fig_leaderboard.png" alt="Factorised metrics by method" />
<figcaption>Figure 1. Factorised metrics by method. `vlm_augmented` leads on
relation F1; `random` collapses, confirming the harness discriminates signal
from noise.</figcaption>
</div>

<div class="figure">
<img src="assets/figs/fig_per_dataset.png" alt="Relation F1 by method and dataset" />
<figcaption>Figure 2. Relation F1 by method and dataset — stable across all four
source datasets.</figcaption>
</div>

<div class="figure">
<img src="assets/figs/fig_pareto.png" alt="Accuracy vs. efficiency" />
<figcaption>Figure 3. Accuracy vs. efficiency (accuracy = mean of relation-F1,
node-F1, spatial-F1; cost = bytes + 8 × edges).</figcaption>
</div>

### Reading the table

- **`vlm_augmented` wins** — it keeps the full deterministic base (recall 1.0)
  and adds a VLM functional/affordance layer. Its node F1 is slightly lower
  (0.869) because it *adds* interactive-part nodes the reference lacks.
- **`geometric_3d` is the best non-VLM method** — perfect precision, near-full
  recall on the spatial / containment edges.
- **`semantic` is precise but sparse** — only category rules, so low recall.
- **`knn_spatial`** captures proximity but misses containment / semantics.
- **`random` ≈ 0** confirms the harness separates signal from noise.

## Caveats

- **Proxies, not the real systems.** These are deterministic stand-ins for each
  paradigm, not the actual external SOTA models. To score a *real* method,
  point `vlm_augmented` at a live VLM endpoint
  (`INTERN_VLM_ENDPOINT=…`, see [`vlm_annotate`](vlm_annotation.html)) — the
  harness then scores its real output against the reference.
- **VLM calibration (ECE/Brier)** is reported but *not* a fair VLM-quality
  score here: the reference is the deterministic oracle and contains no VLM
  edges, so VLM edges register as "not in the reference." Treat **relations
  F1 as the primary signal**.

## Run it yourself

```sh
python -m sage_bench.dataset --per-dataset 3   # build the reference dataset
python -m sage_bench.run                        # -> sage_bench/results/leaderboard.{md,json}
```

Extend it by adding a function to `METHODS` in `methods.py` (signature
`(scene_id, ref_graph, records) -> graph`) — `run.py` scores it automatically —
or by growing the dataset with `--per-dataset 5`.

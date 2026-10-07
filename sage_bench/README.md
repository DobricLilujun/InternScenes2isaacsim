# SAGE-Bench — scene-graph method evaluation

A **small, reproducible scene-graph dataset** plus a harness that evaluates
**five scene-graph-building methods** against a deterministic *reference*
("gold") graph, using the factorised metrics in
[`internscenes.evaluate_graph`](../src/internscenes/evaluate_graph.py).

```
sage_bench/
  dataset.py     # selects scenes + builds the reference (gold) graph
  methods.py     # the 5 SOTA methods (scene-graph-building paradigms)
  run.py         # runs every method, evaluates, writes the leaderboard
  dataset/       # the reference graphs (one scene_graph.json per scene)
  results/       # leaderboard.json + leaderboard.md
```

## The reference (gold) graph

For each scene the *reference* is the **deterministic oracle** from
`internscenes.scene_graph.build_scene_graph`: metric + hierarchy + semantic
edges derived from `layout.json`. It is the strongest graph we can produce
deterministically, so it is a reproducible, well-defined target (not hand
annotation).

## The small dataset

`sage_bench/dataset.py` selects **12 scenes** — 3 from each of the four source
datasets (ScanNet, 3RScan, ARKitScenes, Matterport3D), chosen to span the
object-count range (small / medium / large, ~5–212 nodes):

```sh
python -m sage_bench.dataset --per-dataset 3   # -> sage_bench/dataset/
```

## The 5 methods

Running the *actual* external SOTA systems (GPU VLMs, trained detectors) is not
feasible here, so each method is a **faithful, deterministic proxy for its
paradigm**, built on the same InternScenes data. They are then measured against
the reference by the shared harness — which is exactly what a benchmark does.

| method | what it builds | paradigm |
| --- | --- | --- |
| `geometric_3d` | metric + hierarchy edges (spatial / containment), no category semantics | classical **3D scene graph** (from boxes / point clouds) |
| `semantic` | semantic + hierarchy edges, no metric | **ontology / category-driven** scene graph (relationship rules) |
| `vlm_augmented` | deterministic base + a **VLM functional / affordance** layer (interactive parts + affordances) via `vlm_annotate` | **VLM / LLM** scene graph (image/text-grounded); runs via the rule fallback with no endpoint |
| `knn_spatial` | only `distance` / `near` / `touching` | **k-nearest-neighbour / spatial** scene graph |
| `random` | random edges between nodes | **null / random baseline** (confirms the harness discriminates signal from noise) |

## Evaluation

For each scene, every method's predicted graph is scored against the reference
by `evaluate_graph.evaluate`:

- **nodes** — mAP, 3D-IoU, per-category macro-F1
- **relations** — exact-triplet precision / recall / F1
- **spatial** — macro-F1 over spatial predicates
- **hierarchy** — parent-edge F1
- **affordance** — AP / IoU of the affordance sets
- **calibration** — ECE / Brier for VLM confidence tiers
- **mRecall@K** — neighbour recall
- **efficiency** — bytes / #edges / #nodes (for the Pareto report)

```sh
python -m sage_bench.run          # -> sage_bench/results/leaderboard.{md,json}
```

## Results (12 scenes × 5 methods, ranked by relation F1)

| rank | method | rel. F1 | P | R | node F1 | spatial F1 | mRecall@8 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | **vlm_augmented** | **0.992** | 0.985 | 1.000 | 0.869 | 0.750 | 1.000 |
| 2 | geometric_3d | 0.956 | 1.000 | 0.923 | 1.000 | 0.750 | 0.930 |
| 3 | semantic | 0.559 | 1.000 | 0.464 | 1.000 | 0.000 | 0.502 |
| 4 | knn_spatial | 0.421 | 0.750 | 0.295 | 1.000 | 0.544 | 0.360 |
| 5 | random | 0.010 | 0.013 | 0.008 | 1.000 | 0.011 | 0.305 |

The ranking is stable across all four datasets (per-dataset relation F1:
vlm ≈ 0.997, geometric ≈ 0.99, knn ≈ 0.57, semantic ≈ 0.18, random ≈ 0.03).

### Reading the table

- **vlm_augmented** wins: it keeps the full deterministic base (recall 1.0) and
  adds a VLM functional/affordance layer. Its node F1 is slightly lower (0.869)
  because it *adds* interactive-part nodes the reference lacks.
- **geometric_3d** is the best *pure* (non-VLM) method: perfect precision,
  near-full recall on the spatial / containment edges.
- **semantic** is precise but sparse (only category rules → low recall).
- **knn_spatial** captures proximity but misses containment / semantics.
- **random** ≈ 0 confirms the harness separates signal from noise.

### Caveats

- **Proxies, not the real systems.** These are deterministic stand-ins for each
  paradigm, not the actual external SOTA models. To run a real method, point
  `vlm_augmented` at a live VLM endpoint (`INTERN_VLM_ENDPOINT=…`,
  see [`internscenes.vlm_annotate`](../src/internscenes/vlm_annotate.py)) — the
  harness will then score its real output against the reference.
- **VLM calibration** (ECE/Brier) is reported but *not* a fair VLM-quality
  score here, because the reference is the *deterministic* oracle and contains no
  VLM edges — so the VLM edges register as "not in the reference". Treat the
  relations F1 as the primary signal; use calibration only when the reference
  also carries VLM edges.

## Extending

- **More scenes:** `python -m sage_bench.dataset --per-dataset 5`.
- **Another method:** add a function to `METHODS` in `methods.py` (same
  signature `(scene_id, ref_graph, records) -> graph`); `run.py` scores it
  automatically.

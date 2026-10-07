---
title: Evaluation Metrics
description: The factorised evaluation harness for scene-graph assessment
---

# Evaluation Metrics

SAGE-Bench evaluates a predicted graph against a reference with a
**factorised** harness (`internscenes.evaluate_graph`) — not a single
Recall@K. It scores nodes, relations, spatial, hierarchy, affordance and
efficiency, and reports a **Pareto** frontier of accuracy vs efficiency.

## The factorised score

```python
from internscenes import evaluate_graph as ev

ref = json.load(open("ref.json"))
pred = json.load(open("pred.json"))
metrics = ev.evaluate(ref, pred)
```

`evaluate(reference, predicted)` returns:

| Group | Metric | Meaning |
| --- | --- | --- |
| **nodes** | `mAP` | mean average precision of predicted nodes vs reference |
| | `mean_3d_IoU` | mean 3D intersection-over-union of matched boxes |
| | `macro_F1` | macro-averaged F1 over categories |
| | `num_matched` / `num_predicted` / `num_reference` | counts |
| **relations** | `precision` / `recall` / `F1` | over (source, predicate, target) triplets |
| **spatial** | `precision` / `recall` / `F1` | the metric-family subset |
| **hierarchy** | `precision` / `recall` / `F1` | the hierarchy-family subset |
| **affordance** | `mean_AP` / `mean_IoU` | affordance / interactive-element scoring |
| **efficiency** | `bytes` / `num_nodes` / `num_edges` | graph cost |
| **mRecall@K** | float | long-tail-aware recall (default K = 8) |

### Example

```python
metrics = ev.evaluate(ref, pred)
print(metrics["relations"]["F1"])     # 0.994
print(metrics["spatial"]["F1"])       # 1.0
print(metrics["nodes"]["macro_F1"])  # 0.867
```

## Calibration (VLM)

For VLM-derived edges, calibration measures how well the confidence predicts
correctness. Provide `(confidence, is_correct)` pairs:

```python
pairs = [(0.9, True), (0.8, False), (0.6, True), ...]
cal = ev.calibration(pairs)
# {"ECE": 0.31, "Brier": 0.15, "n": 3}
```

- **ECE** — expected calibration error (10 equal-width bins)
- **Brier** — mean squared (confidence − outcome) error

## Pareto (accuracy vs efficiency)

Compare several methods on the accuracy / efficiency frontier:

```python
entries = [
    ("deterministic", ev.evaluate(ref, det)),
    ("vlm",          ev.evaluate(ref, vlm)),
]
frontier = ev.pareto(entries)
# {"frontier": [...], "points": {...}, "num_entries": 2}
```

Each point is (accuracy, cost) where accuracy is the mean of the reported F1
scores and cost is `bytes + 8 · num_edges`. The frontier keeps non-dominated
points (accuracy up, cost down).

## Self-consistency

`self_report(graph)` checks a single graph against its own invariants (no
reference needed):

```python
rep = ev.self_report(pred)
# {"consistent": True, "issues": 0, "by_family": {...}, "by_level": {...}, ...}
```

## CLI

```sh
# self-consistency
internscenes graph <scene> --self

# evaluate a prediction against a reference
internscenes graph <scene> --reference output/graph/ref.json
```

## Next

- [VLM Annotation](/vlm_annotation.html) — where the calibrated edges come from.
- [Scene-Graph Schema](/scene_graph_schema.html) — what the metrics score over.

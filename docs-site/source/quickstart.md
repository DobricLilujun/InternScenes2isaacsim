---
title: Quickstart
description: Build your first scene graph and evaluate it in 60 seconds
---

# Quickstart

This page gets you from an installed SAGE-Bench to a **built, evaluated scene
graph** for one scene. Everything runs from the project root with the virtual
environment active.

## 1. Build a scene graph (deterministic)

```sh
internscenes graph scannet/scene0313_00 --out output/graph
```

This reads `data/Layout_info/scannet/scene0313_00/layout.json`, builds nodes
(object / room / structure / agent) and edges (metric + hierarchy), and writes
`output/graph/scannet_scene0313_00.json`.

The CLI reports a summary:

```json
{
  "scene_id": "scannet/scene0313_00",
  "nodes": 20,
  "edges": 326,
  "by_family": { "metric": 296, "hierarchy": 30 }
}
```

## 2. Build with the VLM annotation layer

```sh
internscenes graph scannet/scene0313_00 --vlm --out output/graph
```

The VLM layer adds **functional / affordance / interactive-part** edges and
nodes. With no endpoint configured it falls back to a deterministic rule set,
so the pipeline never blocks:

```json
{
  "scene_id": "scannet/scene0313_00",
  "nodes": 24,
  "edges": 330,
  "by_family": { "metric": 296, "hierarchy": 30, "functional": 4 }
}
```

The VLM configuration (endpoint / model / prompt / temperature) is recorded in
the graph's `vlm_manifest` for reproducibility — see
[VLM Annotation](/vlm_annotation.html).

## 3. Check self-consistency

```sh
internscenes graph scannet/scene0313_00 --self
```

Runs inverse / symmetry / containment consistency checks and prints a report.
A healthy graph reports `consistent: true` with `issues: 0`.

## 4. Evaluate a prediction against a reference

Build a reference, then evaluate another graph against it with the factorised
harness:

```sh
# reference = deterministic
internscenes graph scannet/scene0313_00 --out output/graph/ref.json

# prediction = VLM-augmented
internscenes graph scannet/scene0313_00 --vlm --out output/graph/pred.json

# evaluate
internscenes graph scannet/scene0313_00 --reference output/graph/ref.json
```

The factorised score spans nodes, relations, spatial, hierarchy, affordance and
efficiency — see [Evaluation Metrics](/evaluation.html).

## 5. Use the Python API

```python
from internscenes import pipeline

# whole pipeline for one scene (compose → render → graph → …)
status = pipeline.run_scene("scannet/scene0313_00", resume=True, vlm=False)
print(status["status"], status["stages"])

# just the graph stage
ok = pipeline.stage_graph("scannet/scene0313_00", vlm=False)
```

Or use the modules directly:

```python
from internscenes import scene_graph, evaluate_graph

graph = scene_graph.build_scene_graph(
    "scannet/scene0313_00",
    "data/Layout_info/scannet/scene0313_00/layout.json",
)
report = evaluate_graph.self_report(graph)
print(report["consistent"], report["issues"])
```

## 6. Run the full pipeline

```sh
internscenes run --scene scannet/scene0313_00 --resume --vlm
```

The full pipeline composes the GLB, renders perspective + multi-view + top-down,
exports metadata, builds the graph, and generates navigation questions. Use
`--resume` to reuse verified existing output and `--disable-auto-fill` to skip
downloads.

## Next

- [Scene-Graph Schema](/scene_graph_schema.html) — what every field means.
- [Relations &amp; Edge Families](/relations.html) — the typed edge catalogue.
- [Python API](/python_api.html) — the full programmatic surface.

---
title: SAGE-Bench
description: Scene-graph Assessment and Generation Evaluation for Indoor Environments
---

<div class="hero">
  <img src="/assets/logo.svg" alt="SAGE-Bench" class="logo-big" />
  <h1>SAGE-Bench</h1>
  <div class="sub">Scene-graph <strong>Assessment</strong> &amp; <strong>Generation</strong> Evaluation</div>
  <div class="badges">
    <span class="badge"><span class="dot"></span> open source</span>
    <span class="badge"><span class="dot"></span> MIT license</span>
    <span class="badge"><span class="dot"></span> Python 3.11+</span>
    <span class="badge"><span class="dot"></span> InternScenes</span>
  </div>
</div>

**SAGE-Bench** turns the raw indoor layouts of
[InternScenes](https://github.com/InternRobotics/InternScenes) into a
first-class **scene-graph benchmark**: typed nodes, a degradable canonical
schema, a full family of spatial / hierarchical / semantic / functional
relations, a documented **reference-frame standard**, a **VLM annotation**
track, and a **factorised evaluation harness** — all built on the 2,847
scenes, 87,733 objects and 258 categories already present in InternScenes.

It powers two research questions at once:

- **Assessment** — how well does a method *read* a scene?
  (node / relation / spatial / hierarchy / affordance recall)
- **Generation** — how well does a method *build* a scene graph from
  geometry + images, with a reproducible confidence provenance?

## Why SAGE-Bench

| Ingredient | What you get |
| --- | --- |
| Object **nodes** | grounded geometry + category + colour per object |
| Room **structure** | real floor / wall / ceiling meshes → containment &amp; footprint |
| **Edges** | metric / hierarchy / semantic / functional families, each with a confidence tier |
| **Reference frame** | gravity-aligned world, room-canonical (PCA), object-intrinsic |
| **Multi-view** | orbit + top-down captures for a VLM annotation track |
| **Evaluation** | node mAP / 3D-IoU / Macro-F1, relation Triplet P/R/F1, mRecall@K, ECE/Brier, Pareto |

## The stack

<div class="features">
  <div class="feat">
    <div class="f-ico">◈</div>
    <h4>scene_graph</h4>
    <p>Assemble a degradable graph from <code>layout.json</code> and write <code>scene_graph.json</code>.</p>
  </div>
  <div class="feat">
    <div class="f-ico">⌗</div>
    <h4>relations</h4>
    <p>Deterministic + heuristic edge families with explicit confidence tiers.</p>
  </div>
  <div class="feat">
    <div class="f-ico">⌁</div>
    <h4>coordinate</h4>
    <p>Room-canonical &amp; object-intrinsic frames so "front / behind" is well-defined.</p>
  </div>
  <div class="feat">
    <div class="f-ico">⚿</div>
    <h4>vlm_annotate</h4>
    <p>Configurable VLM backend + deterministic fallback + a reproducibility manifest.</p>
  </div>
  <div class="feat">
    <div class="f-ico">∑</div>
    <h4>evaluate_graph</h4>
    <p>Factorised metrics, calibration and an accuracy/efficiency Pareto frontier.</p>
  </div>
  <div class="feat">
    <div class="f-ico">⌖</div>
    <h4>render_multi</h4>
    <p>Multi-view orbit + top-down capture inside Blender for the annotation track.</p>
  </div>
</div>

## 60-second quickstart

```sh
# 1. install the library
uv pip install -e .          # or: pip install -e .

# 2. build a scene graph for one scene (deterministic)
internscenes graph scannet/scene0313_00 --out output/graph

# 3. build with the VLM layer (deterministic fallback if no endpoint)
internscenes graph scannet/scene0313_00 --vlm --out output/graph

# 4. evaluate a prediction against a reference
internscenes graph scannet/scene0330_00 --reference output/graph/ref.json
```

See the [Quickstart](/quickstart.html) for the full walkthrough and the
[Python API](/python_api.html) for programmatic use.

## What's inside

- **[Scene-Graph Schema](/scene_graph_schema.html)** — the degradable canonical schema.
- **[Relations &amp; Edge Families](/relations.html)** — every predicate + confidence tier.
- **[Reference Frames](/reference_frames.html)** — the coordinate standard.
- **[VLM Annotation](/vlm_annotation.html)** — the annotation track + manifest.
- **[Evaluation Metrics](/evaluation.html)** — the factorised harness.
- **[Multi-View Rendering](/rendering.html)** — the capture stage.

## Cite

```bibtex
@software{sagebench2026,
  title  = {SAGE-Bench: Scene-graph Assessment and Generation Evaluation},
  author = {DobricLilujun},
  year   = {2026},
  url    = {https://github.com/DobricLilujun/SAGE-Bench},
  version = {1.0}
}
```

---
title: Contributing
description: How to contribute to SAGE-Bench
---

# Contributing

SAGE-Bench is open source (MIT). Contributions — new edge families, better
reference frames, evaluation metrics, VLM backends, fixes and docs — are
welcome.

## Prerequisites

- Python **3.11+**
- InternScenes layout data (see [Installation](/installation.html))
- Blender **4.5+** for rendering stages (optional for the graph / evaluation
  stages)

## Local setup

```sh
uv venv --python 3.11 .venv311
source .venv311/bin/activate
uv pip install -e ".[dev]"
```

## Run the tests

```sh
python -m unittest discover -s tests -v
```

All tests must pass before you open a pull request. The scene-graph core
(`coordinate`, `relations`, `scene_graph`) is testable **without** Blender or
asset composition — it uses `layout.json` and structure-mesh data only.

## How to add an edge family

1. Add a predicate + confidence tier to the family table in
   `src/internscenes/relations.py` (or `vlm_annotate.py`).
2. Derive it in `derive_edges` with an explicit `reference_frame`
   ([Reference Frames](/reference_frames.html)).
3. Add a consistency invariant in `consistency_check` (inverse / symmetry /
   containment).
4. Add it to the factorised score in `src/internscenes/evaluate_graph.py`.
5. Add a unit test under `tests/`.

## How to add an evaluation metric

Extend `evaluate_graph.evaluate` (or add a standalone helper) and document it in
[Evaluation Metrics](/evaluation.html). Keep the harness **factorised** — one
metric per group, never a single Recall@K.

## Build the docs

The site is built by `docs-site/build.py` (a dependency-free, stdlib builder):

```sh
cd docs-site
python3 build.py        # -> docs-site/output/
```

The output is served by GitHub Pages at
`https://dobriclilujun.github.io/SAGE-Bench` (see
[.github/workflows/pages.yml](https://github.com/DobricLilujun/SAGE-Bench/blob/main/.github/workflows/pages.yml)).

## Pull requests

- Keep commits focused and describe the *why* in the description.
- Add or update tests for behaviour changes.
- Keep the schema degradable — a missing layer should never fail the build.
- Update the relevant page under `docs-site/source/`.

## Code of conduct

Be kind. Assume good intent. Cite the data and the model behind any claim.

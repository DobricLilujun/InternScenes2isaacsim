---
title: Python API
description: The programmatic surface of SAGE-Bench
---

# Python API

All public modules live under `internscenes`. The package uses lazy imports so
`import internscenes` works even inside Blender's Python (which lacks optional
dependencies).

## Run the pipeline

```python
from internscenes import pipeline

# whole pipeline for one scene
status = pipeline.run_scene("scannet/scene0313_00")
if status["status"] != "complete":
    raise RuntimeError(status)

# reuse verified existing output; skip Blender; use the VLM layer
pipeline.run_scene("scannet/scene0313_00", resume=True, vlm=True,
                   skip_render=True, auto_fill=False)
```

`run_scene` signature:

| Parameter | Default | Meaning |
| --- | --- | --- |
| `resume` | `False` | reuse verified existing output |
| `skip_render` / `skip_render_multi` / `skip_topdown` / `skip_graph` / `skip_questions` | `False` | skip a stage |
| `vlm` | `False` | apply the VLM annotation layer |
| `auto_fill` | `True` | download missing models before compose |
| `questions_n` / `questions_seed` | `5` / `None` | navigation questions |
| `plan_questions` | `False` | also plan paths + render path top-downs |

## Individual stages

```python
from internscenes import pipeline

pipeline.stage_compose(scene_id)
pipeline.stage_render(scene_id)
pipeline.stage_render_multi(scene_id, n_views=8)
pipeline.stage_topdown(scene_id)
pipeline.stage_info(scene_id)
pipeline.stage_graph(scene_id, vlm=False)
pipeline.assemble_normalized(scene_id)
```

## Scene-graph builder

```python
from internscenes import scene_graph

graph = scene_graph.build_scene_graph(
    scene_id="scannet/scene0313_00",
    layout_path="data/Layout_info/scannet/scene0313_00/layout.json",
    vlm_result=None,        # optional vlm_annotate result
    cfg=None,               # optional relations.RelationConfig
    include_relative=True,  # include left/right/front/behind
)
scene_graph.write_scene_graph(graph, "output/graph/scene_graph.json")
```

## Relations

```python
from internscenes import relations as rel

cfg = rel.RelationConfig(near_dist=1.0, far_dist=4.0)
boxes = rel.build_boxes(object_records)
edges = rel.derive_edges(boxes, cfg, frame=frame)   # metric + hierarchy + semantic
```

## Coordinate

```python
from internscenes import coordinate as coord

frame = coord.room_canonical_frame(object_records)
pred  = coord.relative_horizontal(a, b, frame)   # front|behind|left|right
vrel  = coord.vertical_relation(a, b)            # above|below|None
obj   = coord.object_intrinsic_frame(record)
```

## VLM annotation

```python
from internscenes import vlm_annotate

cfg = vlm_annotate.VLMConfig.from_env()
result = vlm_annotate.annotate(scene_id, object_records, cfg, views)
rep = vlm_annotate.consistency_check(graph)
```

## Evaluation

```python
from internscenes import evaluate_graph as ev

metrics  = ev.evaluate(reference, predicted)
selfrep  = ev.self_report(predicted)
cal      = ev.calibration([(0.9, True), (0.7, False), ...])
frontier = ev.pareto([("det", metrics), ("vlm", ev.evaluate(ref, vlm))])
```

## Utilities

```python
from internscenes import pipeline

pipeline.resolve_scenes(n=10, seed=0, datasets=["scannet"])
pipeline.scene_inventory()
```

## Next

- [CLI Reference](/cli.html) — the command-line surface.
- [Quickstart](/quickstart.html) — an end-to-end example.

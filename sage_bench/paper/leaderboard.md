# SAGE-Bench — scene-graph method evaluation

**12 scenes** across 4 datasets, **5 methods** vs. a deterministic oracle reference.

| rank | method | rel. F1 | rel. P | rel. R | node F1 | 3D-IoU | spatial F1 | mRecall@8 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | vlm_augmented | 0.992 | 0.985 | 1.000 | 0.869 | 0.670 | 0.750 | 1.000 |
| 2 | geometric_3d | 0.956 | 1.000 | 0.923 | 1.000 | 0.670 | 0.750 | 0.930 |
| 3 | semantic | 0.559 | 1.000 | 0.464 | 1.000 | 0.670 | 0.000 | 0.502 |
| 4 | knn_spatial | 0.421 | 0.750 | 0.295 | 1.000 | 0.670 | 0.544 | 0.360 |
| 5 | random | 0.013 | 0.018 | 0.011 | 1.000 | 0.670 | 0.015 | 0.294 |

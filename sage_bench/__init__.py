"""SAGE-Bench — a small scene-graph dataset + SOTA-method evaluation harness.

Turns a diverse subset of InternScenes scenes into reference ("gold") scene
graphs and evaluates five scene-graph-building paradigms against them, using
the factorised metrics in :mod:`internscenes.evaluate_graph`.
"""
from __future__ import annotations

from . import dataset as dataset
from . import methods as methods

__all__ = ["dataset", "methods"]

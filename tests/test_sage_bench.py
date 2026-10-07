"""Tests for the SAGE-Bench method evaluation harness."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

import sys as _sys
_sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
_sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "sage_bench"))

from sage_bench import methods as M
from internscenes import evaluate_graph as ev
from internscenes import scene_graph as sg
from internscenes import scene_info as si

SCENES = [
    "scannet/scene0013_00",
    "arkitscenes/Validation/47331337",
]


def _ref(scene_id: str) -> dict:
    layout = Path(__file__).resolve().parents[1] / "data" / "Layout_info" / scene_id / "layout.json"
    return sg.build_scene_graph(scene_id, layout)


class TestMethods(unittest.TestCase):
    def setUp(self):
        self.scene_id = SCENES[0]
        self.ref = _ref(self.scene_id)
        self.records = si.load_layout(
            Path(__file__).resolve().parents[1]
            / "data" / "Layout_info" / self.scene_id / "layout.json")
        self.assertGreater(len(self.ref["edges"]), 0)

    def test_all_methods_produce_a_graph(self):
        for name, fn in M.METHODS.items():
            pred = fn(self.scene_id, self.ref, self.records, seed=0) \
                if name == "random" else fn(self.scene_id, self.ref, self.records)
            self.assertIn("nodes", pred)
            self.assertIn("edges", pred)
            # every method keeps all reference nodes (vlm_augmented may *add*
            # interactive-part nodes, so its count can only grow)
            ref_ids = {n["id"] for n in self.ref["nodes"]}
            pred_ids = {n["id"] for n in pred["nodes"]}
            self.assertTrue(ref_ids <= pred_ids, f"{name} dropped reference nodes")

    def test_vlm_augmented_is_superset(self):
        pred = M.vlm_augmented(self.scene_id, self.ref, self.records)
        self.assertGreaterEqual(len(pred["edges"]), len(self.ref["edges"]))
        m = ev.evaluate(self.ref, pred)
        # full recall on the deterministic base
        self.assertGreaterEqual(m["relations"]["recall"], 0.99)

    def test_random_is_worst(self):
        random = M.random_baseline(self.scene_id, self.ref, self.records, seed=0)
        m = ev.evaluate(self.ref, random)
        self.assertLess(m["relations"]["F1"], 0.05)

    def test_ranking_holds(self):
        """VLM-augmented should beat the random baseline on relation F1."""
        preds = {
            "vlm": M.vlm_augmented(self.scene_id, self.ref, self.records),
            "random": M.random_baseline(self.scene_id, self.ref, self.records, seed=0),
        }
        f_vlm = ev.evaluate(self.ref, preds["vlm"])["relations"]["F1"]
        f_rnd = ev.evaluate(self.ref, preds["random"])["relations"]["F1"]
        self.assertGreater(f_vlm, f_rnd)

    def test_reference_evaluates_against_itself(self):
        m = ev.evaluate(self.ref, self.ref)
        # identical graphs -> F1 1.0 on relations
        self.assertGreaterEqual(m["relations"]["F1"], 0.99)
        self.assertGreaterEqual(m["relations"]["precision"], 0.99)


if __name__ == "__main__":
    unittest.main()

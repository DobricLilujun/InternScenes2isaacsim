"""Tests for scene-graph assembly, VLM fallback, and evaluation."""
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
os.environ.setdefault("INTERN_DATA_DIR", str(Path(__file__).resolve().parents[1] / "data"))

from internscenes import scene_graph as scene_graph  # noqa: E402
from internscenes import scene_info as scene_info  # noqa: E402
from internscenes import vlm_annotate as vlm_annotate  # noqa: E402
from internscenes import evaluate_graph as evaluate_graph  # noqa: E402

HERE = Path(__file__).resolve().parents[1] / "data" / "Layout_info" / "scannet" / "scene0313_00"
LAYOUT = HERE / "layout.json"
SCENE = "scannet/scene0313_00"


def _tagged_records():
    records = scene_info.load_layout(str(LAYOUT))
    for i, r in enumerate(records):
        r2 = dict(r)
        r2["_idx"] = i
        records[i] = r2
    return records


class SceneGraphTests(unittest.TestCase):
    def setUp(self):
        self.graph = scene_graph.build_scene_graph(SCENE, str(LAYOUT))

    def test_schema_version(self):
        self.assertEqual(self.graph["schema_version"], "1.0")

    def test_nodes_and_edges_present(self):
        self.assertGreater(len(self.graph["nodes"]), 0)
        self.assertGreater(len(self.graph["edges"]), 0)

    def test_room_and_agent_nodes(self):
        levels = {n["level"] for n in self.graph["nodes"]}
        self.assertIn("room", levels)
        self.assertIn("object", levels)
        self.assertIn("agent", levels)

    def test_frame_embedded(self):
        self.assertEqual(self.graph["frame"]["name"], "room_canonical")
        self.assertIn("forward", self.graph["frame"])

    def test_stats_consistent(self):
        self.assertEqual(self.graph["stats"]["num_nodes"], len(self.graph["nodes"]))
        self.assertEqual(self.graph["stats"]["num_edges"], len(self.graph["edges"]))

    def test_edge_ids_reference_nodes(self):
        ids = {n["id"] for n in self.graph["nodes"]}
        for e in self.graph["edges"]:
            self.assertIn(e["source"], ids)
            self.assertIn(e["target"], ids)

    def test_write_and_reload(self):
        import json
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "g.json"
            scene_graph.write_scene_graph(self.graph, out)
            self.assertTrue(out.exists())
            reloaded = json.load(open(out, encoding="utf-8"))
            self.assertEqual(reloaded["scene_id"], SCENE)

    def test_vlm_fallback_and_consistency(self):
        records = _tagged_records()
        result = vlm_annotate.annotate(SCENE, records, vlm_annotate.VLMConfig())
        self.assertEqual(result["manifest"]["mode"], "deterministic_fallback")
        g = scene_graph.build_scene_graph(SCENE, str(LAYOUT), vlm_result=result)
        rep = vlm_annotate.consistency_check(g)
        self.assertTrue(rep["ok"], f"consistency issues: {rep['issues'][:3]}")

    def test_affordances_attached_as_attributes(self):
        records = _tagged_records()
        result = vlm_annotate.annotate(SCENE, records, vlm_annotate.VLMConfig())
        g = scene_graph.build_scene_graph(SCENE, str(LAYOUT), vlm_result=result)
        # at least one node has affordances attached
        self.assertTrue(any(n.get("affordances") for n in g["nodes"]))


class EvaluateTests(unittest.TestCase):
    def setUp(self):
        self.records = _tagged_records()
        self.ref = scene_graph.build_scene_graph(SCENE, str(LAYOUT))
        self.result = vlm_annotate.annotate(SCENE, self.records, vlm_annotate.VLMConfig())
        self.pred = scene_graph.build_scene_graph(SCENE, str(LAYOUT),
                                                  vlm_result=self.result)

    def test_self_perfect(self):
        m = evaluate_graph.evaluate(self.ref, self.ref)
        self.assertEqual(m["relations"]["F1"], 1.0)
        self.assertEqual(m["nodes"]["mAP"], 1.0)

    def test_spatial_perfect(self):
        m = evaluate_graph.evaluate(self.ref, self.ref)
        self.assertEqual(m["spatial"]["F1"], 1.0)

    def test_pareto(self):
        m_ref = evaluate_graph.evaluate(self.ref, self.ref)
        m_pred = evaluate_graph.evaluate(self.ref, self.pred)
        frontier = evaluate_graph.pareto([("deterministic", m_ref),
                                          ("vlm", m_pred)])
        self.assertIsInstance(frontier["frontier"], list)
        self.assertEqual(frontier["num_entries"], 2)

    def test_calibration(self):
        cal = evaluate_graph.calibration(
            [(0.9, True), (0.5, True), (0.3, False), (0.8, True)])
        self.assertIn("ECE", cal)
        self.assertIn("Brier", cal)
        self.assertGreaterEqual(cal["Brier"], 0.0)

    def test_mrecall(self):
        r = evaluate_graph.mrecall_at_k(self.ref, self.ref, 8)
        self.assertEqual(r, 1.0)

    def test_efficiency(self):
        eff = evaluate_graph.efficiency(self.ref)
        self.assertGreater(eff["bytes"], 0)
        self.assertGreater(eff["num_edges"], 0)


if __name__ == "__main__":
    unittest.main()

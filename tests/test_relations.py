"""Tests for relation derivation (internscenes.relations)."""
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
os.environ.setdefault("INTERN_DATA_DIR", str(Path(__file__).resolve().parents[1] / "data"))

from internscenes import coordinate as coord  # noqa: E402
from internscenes import relations as rel  # noqa: E402
from internscenes import scene_info as scene_info  # noqa: E402

HERE = Path(__file__).resolve().parents[1] / "data" / "Layout_info" / "scannet" / "scene0313_00"
LAYOUT = HERE / "layout.json"


def _records():
    import json
    return json.load(open(LAYOUT, encoding="utf-8"))


class RelationsTests(unittest.TestCase):
    def setUp(self):
        self.records = _records()
        self.interior = scene_info.structure_mesh_bounds(str(LAYOUT))
        self.frame = coord.room_canonical_frame(self.records, self.interior)

    def test_derive_returns_edges(self):
        edges = rel.derive_edges(self.records, self.frame, interior_bounds=self.interior)
        self.assertGreater(len(edges), 0)

    def test_edge_has_required_fields(self):
        edges = rel.derive_edges(self.records, self.frame, interior_bounds=self.interior)
        for e in edges:
            self.assertIn("source", e.as_dict())
            self.assertIn("predicate", e.as_dict())
            self.assertIn("family", e.as_dict())
            self.assertIn("reference_frame", e.as_dict())
            self.assertIn(e.as_dict()["family"],
                         {"metric", "hierarchy", "semantic", "functional"})

    def test_families_present(self):
        edges = rel.derive_edges(self.records, self.frame, interior_bounds=self.interior)
        families = {e.family for e in edges}
        self.assertIn("metric", families)
        self.assertIn("hierarchy", families)

    def test_hierarchy_references_room(self):
        edges = rel.derive_edges(self.records, self.frame, interior_bounds=self.interior)
        hierarchy = [e for e in edges if e.family == "hierarchy"]
        self.assertTrue(all(e.source == "room" or e.target == "room"
                            for e in hierarchy),
                        "hierarchy edges must involve the room node")

    def test_above_below_not_mutual(self):
        edges = rel.derive_edges(self.records, self.frame, interior_bounds=self.interior)
        above = {(e.source, e.target) for e in edges if e.predicate == "above"}
        for a, b in above:
            self.assertNotIn((b, a), above, "above must not be its own inverse")

    def test_distance_is_numeric(self):
        edges = rel.derive_edges(self.records, self.frame, interior_bounds=self.interior)
        dist = [e for e in edges if e.predicate == "distance"]
        self.assertTrue(dist)
        for e in dist:
            self.assertIsInstance(e.value, float)
            self.assertGreaterEqual(e.value, 0.0)

    def test_relative_edges_carry_room_frame(self):
        edges = rel.derive_edges(self.records, self.frame, interior_bounds=self.interior)
        rel_edges = [e for e in edges
                     if e.predicate in {"front", "behind", "left", "right"}]
        self.assertTrue(rel_edges)
        self.assertTrue(all(e.reference_frame == "room_canonical" for e in rel_edges))

    def test_config_caps(self):
        cfg = rel.RelationConfig(max_edges_per_predicate=50)
        edges = rel.derive_edges(self.records, self.frame, cfg=cfg,
                                  interior_bounds=self.interior)
        # metric edges capped
        metric = [e for e in edges if e.family == "metric"]
        self.assertLessEqual(len(metric), 600)

    def test_no_edges_for_empty_scene(self):
        edges = rel.derive_edges([], self.frame)
        self.assertEqual(len(edges), 0)


if __name__ == "__main__":
    unittest.main()

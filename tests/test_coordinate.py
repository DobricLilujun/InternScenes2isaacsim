"""Tests for the reference-frame standard (internscenes.coordinate)."""
import os
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
os.environ.setdefault("INTERN_DATA_DIR", str(Path(__file__).resolve().parents[1] / "data"))

from internscenes import coordinate as coord  # noqa: E402

HERE = Path(__file__).resolve().parents[1] / "data" / "Layout_info" / "scannet" / "scene0313_00"
LAYOUT = HERE / "layout.json"


def _records():
    import json
    return json.load(open(LAYOUT, encoding="utf-8"))


class CoordinateTests(unittest.TestCase):
    def setUp(self):
        self.records = _records()

    def test_room_frame_is_orthonormal(self):
        frame = coord.room_canonical_frame(self.records)
        m = frame.matrix
        self.assertAlmostEqual(
            float((m.T @ m).trace() / 3), 1.0, places=6,
            msg="room-canonical matrix must be orthonormal")
        self.assertAlmostEqual(float(np.linalg.det(m)), 1.0, places=6)

    def test_up_is_gravity_aligned(self):
        frame = coord.room_canonical_frame(self.records)
        up = frame.up()
        self.assertGreater(abs(up[2]), 0.99)
        self.assertLess(abs(up[0]), 1e-6)
        self.assertLess(abs(up[1]), 1e-6)

    def test_forward_is_horizontal(self):
        frame = coord.room_canonical_frame(self.records)
        fwd = frame.forward()
        self.assertLess(abs(fwd[2]), 1e-6, "forward must lie in the XY plane")
        self.assertAlmostEqual(float(np.linalg.norm(fwd)), 1.0, places=6)

    def test_frame_is_right_handed(self):
        frame = coord.room_canonical_frame(self.records)
        right = frame.right()
        cross = np.cross(right, frame.forward())
        self.assertTrue(np.allclose(cross, frame.up(), atol=1e-6))

    def test_fallback_forward_is_deterministic(self):
        # a single point -> no PCA -> fallback axis
        one = [{"bbox": [0.0, 0.0, 0.0, 1.0, 1.0, 1.0]}]
        f = coord.room_canonical_frame(one)
        # forward should be a unit horizontal vector
        self.assertAlmostEqual(float(np.linalg.norm(f.forward())), 1.0, places=6)

    def test_relative_horizontal_classifies(self):
        frame = coord.room_canonical_frame(self.records)
        if len(self.records) >= 2:
            rel = coord.relative_horizontal(self.records[0], self.records[1], frame)
            self.assertIn(rel, {"front", "behind", "left", "right"})

    def test_vertical_relation(self):
        a = {"bbox": [0.0, 0.0, 5.0, 1.0, 1.0, 1.0]}   # high
        b = {"bbox": [0.0, 0.0, 0.0, 1.0, 1.0, 1.0]}   # low
        self.assertEqual(coord.vertical_relation(a, b), "above")
        self.assertEqual(coord.vertical_relation(b, a), "below")
        c = {"bbox": [0.0, 0.0, 0.5, 1.0, 1.0, 1.0]}
        self.assertEqual(coord.vertical_relation(a, c), "above")

    def test_object_intrinsic_frame(self):
        rec = {"bbox": [0.0, 0.0, 0.0, 1.0, 1.0, 1.0, 0.0, 0.0, np.pi / 2]}
        frame = coord.object_intrinsic_frame(rec)
        # 90 deg about Z rotates local +X to world +Y
        self.assertGreater(abs(frame.forward()[1]), 0.99)
        self.assertLess(abs(frame.forward()[0]), 1e-6)

    def test_resolve_frame_names(self):
        f1 = coord.resolve_frame("world", self.records)
        self.assertEqual(f1.name, "world")
        f2 = coord.resolve_frame("room_canonical", self.records)
        self.assertEqual(f2.name, "room_canonical")
        f3 = coord.resolve_frame(None, self.records)
        self.assertEqual(f3.name, "room_canonical")

    def test_round_trip(self):
        frame = coord.room_canonical_frame(self.records)
        p = np.array([1.0, 2.0, 3.0])
        back = frame.to_world(frame.world_to_frame(p))
        self.assertTrue(np.allclose(back, p, atol=1e-6))


if __name__ == "__main__":
    unittest.main()

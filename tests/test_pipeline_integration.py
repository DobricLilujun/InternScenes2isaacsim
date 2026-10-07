import base64
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from internscenes import evaluate_graph, pipeline, vlm_annotate  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SCENE = "scannet/scene0330_00"


class VLMImageTests(unittest.TestCase):
    def test_local_images_are_encoded_as_data_urls(self):
        image_bytes = b"test-png-image"
        with tempfile.TemporaryDirectory() as tmp:
            image = Path(tmp) / "view.png"
            image.write_bytes(image_bytes)
            response = io.BytesIO(json.dumps({
                "choices": [{"message": {"content": '{"ok": true}'}}],
            }).encode())
            cfg = vlm_annotate.VLMConfig(endpoint="https://vlm.example/v1")
            with patch("urllib.request.urlopen", return_value=response) as urlopen:
                result = vlm_annotate._call_vlm(cfg, "inspect", [str(image)])

        self.assertEqual(result, {"ok": True})
        request = urlopen.call_args.args[0]
        body = json.loads(request.data)
        image_url = body["messages"][0]["content"][1]["image_url"]["url"]
        prefix, payload = image_url.split(",", 1)
        self.assertEqual(prefix, "data:image/png;base64")
        self.assertEqual(base64.b64decode(payload), image_bytes)


class PipelineIntegrationTests(unittest.TestCase):
    def test_stage_graph_uses_flat_view_paths_and_saves_normalized_graph(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            render_dir = root / "render"
            render_dir.mkdir()
            flat = SCENE.replace("/", "_")
            for index in range(8):
                (render_dir / f"{flat}__view_{index}.png").touch()
            (render_dir / f"{flat}__topdown.png").touch()
            paths = {
                "layout": ROOT / "data" / "Layout_info" / SCENE / "layout.json",
                "render_dir": render_dir,
                "graph": root / "graph" / f"{flat}.json",
                "normalized": root / "normalized" / flat,
            }
            captured = {}
            annotate = vlm_annotate.annotate

            def capture_views(scene_id, records, cfg, render_views):
                captured.update(render_views)
                return annotate(scene_id, records, cfg, render_views)

            with patch.object(pipeline, "paths_for", return_value=paths), patch.object(
                pipeline._vlm_annotate, "annotate", side_effect=capture_views
            ):
                self.assertTrue(pipeline.stage_graph(SCENE, vlm=True))

            self.assertEqual(len(captured), 9)
            self.assertIn("topdown", captured)
            self.assertTrue(all(Path(path).is_file() for path in captured.values()))
            graph_path = paths["normalized"] / "scene_graph.json"
            self.assertTrue(graph_path.is_file())
            graph = json.loads(graph_path.read_text(encoding="utf-8"))
            self.assertEqual(set(graph["renders"]), set(captured))

    def test_configured_vlm_fails_if_multiview_is_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = {
                "layout": ROOT / "data" / "Layout_info" / SCENE / "layout.json",
                "render_dir": root / "render",
                "graph": root / "graph.json",
                "normalized": root / "normalized",
            }
            cfg = vlm_annotate.VLMConfig(endpoint="https://vlm.example/v1")
            with patch.object(pipeline, "paths_for", return_value=paths), patch.object(
                pipeline._vlm_annotate.VLMConfig, "from_env", return_value=cfg
            ), patch.object(pipeline, "stage_render_multi") as render_multi, patch.object(
                pipeline._vlm_annotate, "annotate"
            ) as annotate:
                self.assertFalse(
                    pipeline.stage_graph(SCENE, vlm=True, skip_render_multi=True)
                )

            render_multi.assert_not_called()
            annotate.assert_not_called()

    def test_graph_stage_precedes_normalization_and_multiview_is_vlm_only(self):
        events = []
        stage_patches = (
            patch.object(pipeline, "stage_compose",
                         side_effect=lambda *_: events.append("compose") or True),
            patch.object(pipeline, "stage_render",
                         side_effect=lambda *_: events.append("render") or True),
            patch.object(pipeline, "stage_render_multi",
                         side_effect=lambda *_: events.append("render_multi") or True),
            patch.object(pipeline, "stage_topdown",
                         side_effect=lambda *_: events.append("topdown") or True),
            patch.object(pipeline, "stage_info",
                         side_effect=lambda *_: events.append("info") or True),
            patch.object(pipeline, "stage_graph",
                         side_effect=lambda *_, **__: events.append("graph") or True),
            patch.object(pipeline, "assemble_normalized",
                         side_effect=lambda *_: events.append("normalize") or {"scene": "ok"}),
        )
        with stage_patches[0], stage_patches[1], stage_patches[2], stage_patches[3], \
                stage_patches[4], stage_patches[5], stage_patches[6]:
            result = pipeline.run_scene(
                SCENE, auto_fill=False, vlm=True, skip_questions=True,
            )

        self.assertEqual(result["status"], "complete")
        self.assertLess(events.index("graph"), events.index("normalize"))
        self.assertIn("render_multi", events)

        with patch.object(pipeline, "stage_compose", return_value=True), patch.object(
            pipeline, "stage_render", return_value=True
        ), patch.object(pipeline, "stage_render_multi") as render_multi, patch.object(
            pipeline, "stage_topdown", return_value=True
        ), patch.object(pipeline, "stage_info", return_value=True), patch.object(
            pipeline, "stage_graph", return_value=True
        ), patch.object(pipeline, "assemble_normalized", return_value={"scene": "ok"}):
            pipeline.run_scene(
                SCENE, auto_fill=False, skip_questions=True,
            )
        render_multi.assert_not_called()


class EvaluationCalibrationTests(unittest.TestCase):
    def test_evaluate_reports_calibration_for_vlm_edges(self):
        reference = {
            "nodes": [],
            "edges": [{"source": "a", "target": "b", "predicate": "opens"}],
        }
        predicted = {
            "nodes": [],
            "edges": [{
                "source": "a",
                "target": "b",
                "predicate": "opens",
                "tier": "vlm",
                "confidence": 0.8,
            }],
        }
        result = evaluate_graph.evaluate(reference, predicted)
        self.assertEqual(result["calibration"]["n"], 1)
        self.assertEqual(result["calibration"]["Brier"], 0.04)

    def test_consistency_check_detects_symmetric_duplicates_and_cycles(self):
        graph = {
            "nodes": [{"id": "a"}, {"id": "b"}],
            "edges": [
                {"source": "a", "target": "b", "predicate": "near",
                 "reference_frame": "world"},
                {"source": "b", "target": "a", "predicate": "near",
                 "reference_frame": "world"},
                {"source": "a", "target": "b", "predicate": "contains",
                 "reference_frame": "world"},
                {"source": "b", "target": "a", "predicate": "contains",
                 "reference_frame": "world"},
            ],
        }
        result = vlm_annotate.consistency_check(graph)
        issue_types = {issue["type"] for issue in result["issues"]}
        self.assertIn("duplicate_symmetric_relation", issue_types)
        self.assertIn("containment_cycle", issue_types)


if __name__ == "__main__":
    unittest.main()

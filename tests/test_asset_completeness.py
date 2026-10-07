import json
from logging import FileHandler
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from internscenes import cli, compose, download, pipeline


class AssetCompletenessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        logging_patcher = patch.object(
            cli.logging, "FileHandler", side_effect=lambda *a: cli.logging.NullHandler()
        )
        logging_patcher.start()
        self.addCleanup(logging_patcher.stop)
        self.root = Path(self.temp.name)
        self.sid = "scannet/example"
        self.uid = "hssd-models/chair"
        self.assets = self.root / "assets"
        self.layout = self.root / "layouts" / self.sid / "layout.json"
        self.layout.parent.mkdir(parents=True)
        self.layout.write_text(json.dumps([{"model_uid": self.uid}]))
        for module, name, value in (
            (download, "ASSET_LIBRARY", self.assets),
            (download, "LAYOUT_DIR", self.root / "layouts"),
            (download, "INFO", self.root / "output/info"),
            (download, "DATA", self.root),
            (compose, "ASSET_LIBRARY", self.assets),
            (compose, "LAYOUT_DIR", self.root / "layouts"),
            (compose, "COMPOSED_DIR", self.root / "output/composed"),
            (compose, "OUTPUT_ROOT", self.root / "output"),
            (pipeline, "DATA", self.root),
            (pipeline, "OUTPUT", self.root / "output"),
        ):
            patcher = patch.object(module, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.paths = pipeline.paths_for(self.sid)
        self.paths["layout"] = self.layout
        patcher = patch.object(pipeline, "paths_for", return_value=self.paths)
        patcher.start()
        self.addCleanup(patcher.stop)

    def write_asset(self):
        path = self.assets / f"{self.uid}.glb"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"test")

    def download(self, **kwargs):
        return download.download_missing(
            scene_ids=[self.sid], auto=True, log=self.root / "download.log", **kwargs
        )

    def test_download_rejects_unmatched_remote_patterns(self):
        with patch.object(download, "snapshot_download") as fetch:
            self.assertEqual(self.download(), 1)
        self.assertEqual(fetch.call_args.kwargs["allow_patterns"],
                         ["asset_library/hssd-models/chair.glb"])

    def test_download_verifies_files_and_does_not_redownload_existing(self):
        with patch.object(download, "snapshot_download", side_effect=lambda *a, **k: self.write_asset()) as fetch:
            self.assertEqual(self.download(), 0)
            self.assertEqual(self.download(), 0)
            self.assertEqual(fetch.call_count, 1)

    def test_dry_run_does_not_download(self):
        with patch.object(download, "snapshot_download") as fetch:
            self.assertEqual(self.download(dry_run=True), 0)
            fetch.assert_not_called()

    def test_directory_is_not_an_asset(self):
        (self.assets / f"{self.uid}.glb").mkdir(parents=True)
        self.assertFalse(download._exists_on_disk(self.uid, "hssd-models"))
        loader = compose.AssetMeshLoader.__new__(compose.AssetMeshLoader)
        self.assertIsNone(loader.resolve_mesh_path(self.uid))

    def test_nested_and_partnet_paths_are_supported(self):
        nested = self.assets / "objaverse/objaverse/model.glb"
        nested.parent.mkdir(parents=True)
        nested.touch()
        partnet = self.assets / "partnet_mobility/1/whole.glb"
        partnet.parent.mkdir(parents=True)
        partnet.touch()
        self.assertFalse(download._filter_existing({
            "objaverse": {"objaverse/model"},
            "partnet_mobility": {"partnet_mobility/1"},
        }))

    def test_missing_layout_raises_instead_of_claiming_success(self):
        self.layout.unlink()
        with self.assertRaises(FileNotFoundError):
            self.download()

    def test_download_exception_is_not_hidden(self):
        with patch.object(download, "snapshot_download", side_effect=OSError("network")):
            with self.assertRaises(OSError):
                self.download()

    def test_stage_compose_rejects_partial_glb(self):
        self.paths["composed"].parent.mkdir(parents=True)
        self.paths["composed"].touch()
        with patch.object(compose, "SceneComposer") as factory:
            factory.return_value.compose_one_scene.return_value = (
                self.paths["composed"], [{"uid": self.uid}]
            )
            self.assertFalse(pipeline.stage_compose(self.sid))
            factory.return_value.compose_one_scene.return_value = (self.paths["composed"], [])
            self.assertTrue(pipeline.stage_compose(self.sid))

    def test_compose_refreshes_old_report_to_zero(self):
        composer = compose.SceneComposer(asset_mesh_loader=Mock())
        self.paths["missing"].parent.mkdir(parents=True)
        self.paths["missing"].write_text('{"num_missing": 1}')
        with patch.object(composer, "compose_scene_from_instance_infos",
                          return_value=(compose.trimesh.Scene(), [])), patch.object(
                              compose.trimesh.exchange.export, "export_mesh"
                          ):
            composer.compose_one_scene(self.sid, add_floor=False, add_wall=False, add_ceiling=False)
        report = json.loads(self.paths["missing"].read_text())
        self.assertEqual(report, {"scene_id": self.sid, "num_missing": 0, "missing": []})

    def test_load_errors_propagate_from_workers(self):
        loader = Mock()
        loader.load_canonical_mesh.side_effect = ValueError("corrupt mesh")
        composer = compose.SceneComposer(asset_mesh_loader=loader)
        with self.assertRaisesRegex(ValueError, "corrupt mesh"):
            composer.compose_scene_from_instance_infos(
                [{"model_uid": self.uid}], None, True
            )

    def test_resume_requires_fresh_zero_report_and_present_assets(self):
        self.write_asset()
        self.paths["composed"].parent.mkdir(parents=True)
        self.paths["composed"].touch()
        self.assertFalse(pipeline._can_resume_composed(self.sid))
        self.paths["missing"].parent.mkdir(parents=True)
        self.paths["missing"].write_text(json.dumps({
            "scene_id": self.sid, "num_missing": 0, "missing": [],
        }))
        self.assertTrue(pipeline._can_resume_composed(self.sid))
        (self.assets / f"{self.uid}.glb").unlink()
        self.assertFalse(pipeline._can_resume_composed(self.sid))
        self.write_asset()
        os.utime(self.paths["missing"], ns=(1, 1))
        self.assertFalse(pipeline._can_resume_composed(self.sid))

    def test_failed_compose_blocks_downstream_even_on_resume(self):
        self.paths["composed"].parent.mkdir(parents=True)
        self.paths["composed"].touch()
        with patch.object(pipeline, "stage_compose", return_value=False), patch.object(
            pipeline, "assemble_normalized"
        ) as normalize:
            result = pipeline.run_scene(self.sid, resume=True, auto_fill=False)
        self.assertEqual(result["status"], "incomplete")
        self.assertEqual(result["stages"]["normalize"], "blocked(compose)")
        normalize.assert_not_called()

    def test_cli_stops_when_auto_fill_verification_fails(self):
        with patch("sys.argv", ["internscenes", "run", "--scene", self.sid, "--auto-fill",
                                "--log", str(self.root / "run.log")]), patch.object(
            pipeline, "resolve_scenes", return_value=[self.sid]
        ), patch.object(pipeline, "stage_compose", return_value=False), patch.object(
            pipeline, "auto_fill_assets", return_value=1
        ), patch.object(pipeline, "run_scene") as run:
            self.assertEqual(cli.main(), 1)
            run.assert_not_called()
        manifest = json.loads((self.root / "output/batch/manifest.json").read_text())
        self.assertEqual(manifest["results"][0]["stages"]["auto_fill"], "failed(verification)")

    def test_cli_incomplete_run_returns_nonzero(self):
        with patch("sys.argv", ["internscenes", "run", "--scene", self.sid, "--disable-auto-fill",
                                "--log", str(self.root / "run.log")]), patch.object(
            pipeline, "resolve_scenes", return_value=[self.sid]
        ), patch.object(pipeline, "run_scene", return_value={"status": "incomplete"}), patch.object(
            pipeline, "flush_manifest"
        ):
            self.assertEqual(cli.main(), 1)

    def test_rebuilding_on_resume_reruns_downstream(self):
        self.paths["composed"].parent.mkdir(parents=True)
        self.paths["composed"].touch()
        self.paths["topdown"].parent.mkdir(parents=True)
        self.paths["topdown"].touch()
        with patch.object(pipeline, "stage_compose", return_value=True), patch.object(
            pipeline, "stage_topdown", return_value=True
        ) as topdown, patch.object(pipeline, "stage_info", return_value=True), patch.object(
            pipeline, "assemble_normalized", return_value={"usd": "scene.usd"}
        ):
            result = pipeline.run_scene(
                self.sid, resume=True, skip_render=True, skip_questions=True,
                skip_render_multi=True, skip_graph=True, auto_fill=False
            )
        self.assertEqual(result["status"], "complete")
        topdown.assert_called_once_with(self.sid)

    def test_auto_fill_preserves_resume_and_returns_success(self):
        with patch("sys.argv", ["internscenes", "run", "--scene", self.sid, "--auto-fill",
                                "--resume", "--log", str(self.root / "run.log")]), patch.object(
            pipeline, "resolve_scenes", return_value=[self.sid]
        ), patch.object(pipeline, "stage_compose", return_value=False), patch.object(
            pipeline, "auto_fill_assets", return_value=0
        ), patch.object(pipeline, "run_scene", return_value={"status": "complete"}) as run, patch.object(
            pipeline, "flush_manifest"
        ):
            self.assertEqual(cli.main(), 0)
        self.assertTrue(run.call_args.kwargs["resume"])
        self.assertFalse(run.call_args.kwargs["auto_fill"])

    def test_cli_defaults_to_one_scoped_auto_fill_without_precomposition(self):
        with patch("sys.argv", ["internscenes", "run", "--scene", self.sid,
                                "--log", str(self.root / "run.log")]), patch.object(
            pipeline, "resolve_scenes", return_value=[self.sid]
        ), patch.object(pipeline, "auto_fill_assets", return_value=0) as fill, patch.object(
            pipeline, "run_scene", return_value={"status": "complete"}
        ) as run, patch.object(pipeline, "stage_compose") as compose_stage, patch.object(
            pipeline, "flush_manifest"
        ):
            self.assertEqual(cli.main(), 0)
        fill.assert_called_once_with([self.sid])
        compose_stage.assert_not_called()
        self.assertFalse(run.call_args.kwargs["auto_fill"])

    def test_cli_disable_auto_fill_never_calls_downloader(self):
        with patch("sys.argv", ["internscenes", "run", "--scene", self.sid,
                                "--disable-auto-fill", "--log", str(self.root / "run.log")]), patch.object(
            pipeline, "resolve_scenes", return_value=[self.sid]
        ), patch.object(pipeline, "auto_fill_assets") as fill, patch.object(
            pipeline, "run_scene", return_value={"status": "complete"}
        ) as run, patch.object(pipeline, "flush_manifest"):
            self.assertEqual(cli.main(), 0)
        fill.assert_not_called()
        self.assertFalse(run.call_args.kwargs["auto_fill"])

    def test_cli_empty_selection_does_not_download(self):
        with patch("sys.argv", ["internscenes", "run", "--scene", self.sid,
                                "--log", str(self.root / "run.log")]), patch.object(
            pipeline, "resolve_scenes", return_value=[]
        ), patch.object(pipeline, "auto_fill_assets") as fill:
            self.assertEqual(cli.main(), 1)
        fill.assert_not_called()

    def test_python_api_auto_fills_by_default_and_blocks_failure(self):
        with patch.object(pipeline, "auto_fill_assets", return_value=1) as fill, patch.object(
            pipeline, "stage_compose"
        ) as compose_stage:
            result = pipeline.run_scene(self.sid)
        fill.assert_called_once_with([self.sid])
        compose_stage.assert_not_called()
        self.assertEqual(result["status"], "incomplete")
        self.assertEqual(result["stages"]["compose"], "blocked(auto_fill)")

    def test_python_api_can_disable_auto_fill(self):
        with patch.object(pipeline, "auto_fill_assets") as fill, patch.object(
            pipeline, "stage_compose", return_value=False
        ):
            result = pipeline.run_scene(self.sid, auto_fill=False)
        fill.assert_not_called()
        self.assertTrue(result["stages"]["compose"].startswith("failed("))

    def test_python_api_default_success_verifies_assets_before_composing(self):
        events = []
        with patch.object(pipeline, "auto_fill_assets", side_effect=lambda scenes: events.append("fill") or 0), patch.object(
            pipeline, "stage_compose", side_effect=lambda scene: events.append("compose") or True
        ), patch.object(pipeline, "stage_info", return_value=True), patch.object(
            pipeline, "assemble_normalized", return_value={"usd": "scene.usd"}
        ):
            result = pipeline.run_scene(
                self.sid, skip_render=True, skip_topdown=True, skip_questions=True,
                skip_render_multi=True, skip_graph=True
            )
        self.assertEqual(events, ["fill", "compose"])
        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["stages"]["auto_fill"], "ok(verified)")

    def test_auto_fill_requires_explicit_scenes(self):
        with self.assertRaisesRegex(ValueError, "at least one scene"):
            pipeline.auto_fill_assets([])

    def test_batch_uses_same_auto_fill_policy(self):
        for enabled in (True, False):
            with self.subTest(enabled=enabled), patch.object(cli, "cmd_run", return_value=0) as run:
                self.assertEqual(cli.cmd_batch(2, 200, True, "", auto_fill=enabled), 0)
            self.assertEqual(run.call_args.kwargs["auto_fill"], enabled)

    def test_auto_fill_parser_defaults_aliases_and_conflicts(self):
        parser = cli.build_parser()
        for command in ("run", "batch"):
            for flags, expected in (([], True), (["--disable-auto-fill"], False),
                                    (["--auto-fill"], True), (["--auto-fill-once"], True)):
                with self.subTest(command=command, flags=flags):
                    self.assertEqual(parser.parse_args([command, *flags]).auto_fill, expected)
            for alias in ("--auto-fill", "--auto-fill-once"):
                with self.subTest(command=command, alias=alias), patch("sys.stderr"), self.assertRaises(SystemExit) as caught:
                    parser.parse_args([command, "--disable-auto-fill", alias])
                self.assertEqual(caught.exception.code, 2)

    def test_cli_log_is_written_even_when_logging_is_already_configured(self):
        log = self.root / "run.log"
        with patch.object(cli.logging, "FileHandler", FileHandler), patch(
            "sys.argv", ["internscenes", "run", "--scene", self.sid,
                         "--disable-auto-fill", "--log", str(log)]
        ), patch.object(pipeline, "resolve_scenes", return_value=[self.sid]), patch.object(
            pipeline, "run_scene", return_value={"status": "complete"}
        ), patch.object(pipeline, "flush_manifest"):
            self.assertEqual(cli.main(), 0)
        cli.logging.shutdown()
        self.assertIn("auto-fill disabled", log.read_text())


if __name__ == "__main__":
    unittest.main()

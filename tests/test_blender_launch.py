import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from internscenes import _render_in_blender as bootstrap
from internscenes import pipeline


class BlenderLaunchTests(unittest.TestCase):
    def test_explicit_path_takes_precedence(self):
        with patch.dict(os.environ, {"BLENDER": "/custom/blender"}), patch.object(
            pipeline.shutil, "which", return_value="/usr/bin/blender"
        ):
            self.assertEqual(pipeline.blender_path(), "/custom/blender")

    def test_system_installation_is_discovered(self):
        with patch.dict(os.environ, {"BLENDER": ""}), patch.object(
            pipeline.shutil, "which", return_value="/usr/bin/blender"
        ):
            self.assertEqual(pipeline.blender_path(), "/usr/bin/blender")

    def test_missing_installation_is_explicit(self):
        with patch.dict(os.environ, {"BLENDER": ""}), patch.object(
            pipeline.shutil, "which", return_value=None
        ), patch.object(Path, "is_file", return_value=False):
            with self.assertRaisesRegex(FileNotFoundError, "set BLENDER"):
                pipeline.blender_path()

    def test_bootstrap_uses_blender_not_system_python(self):
        bpy = SimpleNamespace(app=SimpleNamespace(binary_path="/usr/bin/blender"))
        with patch.dict(sys.modules, {"bpy": bpy}), patch.object(
            sys, "executable", "/usr/local/bin/python3.12"
        ), patch.object(bootstrap.subprocess, "run", return_value=SimpleNamespace(returncode=1)) as run:
            result = bootstrap._run_via_blender_script(
                Path("/venv/bin/python"), "/project/src", ["--glb", "/scene.glb"]
            )
        command = run.call_args.args[0]
        self.assertEqual(command[0], "/usr/bin/blender")
        self.assertIn("--python-exit-code", command)
        self.assertEqual(command[-3:], ["--", "--glb", "/scene.glb"])
        self.assertEqual(result, 1)
        self.assertFalse(Path(command[command.index("--python") + 1]).exists())

    def test_render_prefers_blender_directory_for_python_discovery(self):
        paths = {
            "composed": Path("/scene.glb"),
            "render_dir": Path("/output"),
            "perspective": Path("/output/perspective.png"),
        }
        with patch.object(pipeline, "paths_for", return_value=paths), patch.object(
            pipeline, "blender_path", return_value="/usr/bin/blender"
        ), patch.object(Path, "exists", return_value=True), patch.object(
            Path, "mkdir"
        ), patch.object(pipeline.subprocess, "run", return_value=SimpleNamespace(returncode=0)) as run:
            self.assertTrue(pipeline.stage_render("scannet/example"))
        self.assertEqual(run.call_args.kwargs["env"]["PATH"].split(os.pathsep)[0], "/usr/bin")


if __name__ == "__main__":
    unittest.main()

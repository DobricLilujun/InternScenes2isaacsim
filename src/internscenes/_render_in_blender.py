"""Blender bootstrap script: run ``internscenes.render`` inside Blender's interpreter.

Blender 5.x ships a self-contained Python runtime where ``bpy`` is available
but the project venv packages are not.  Conversely the project venv has
``internscenes`` but not ``bpy``.  This script is executed *inside* Blender;
it generates a temporary Python script that adds the package source to
``sys.path`` and calls ``internscenes.render.main()`` with the forwarded
``--glb``/``--out``/``--engine`` arguments.  Because the temp script runs in
Blender's interpreter, ``import bpy`` succeeds and the render produces the
perspective PNG.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path


def _forward_args() -> list[str]:
    """Collect everything after ``--`` from Blender's sys.argv."""
    argv = sys.argv
    if "--" in argv:
        return argv[argv.index("--") + 1:]
    # Some Blender builds strip the ``--`` separator; reconstruct from the
    # known option keys so the argument parser still receives its values.
    keys = ("--glb", "--out", "--engine")
    out: list[str] = []
    i = 0
    while i < len(argv):
        a = argv[i]
        if a.startswith("--") and any(a.startswith(k) for k in keys):
            out.append(a)
            if "=" not in a:
                i += 1
                if i < len(argv):
                    out.append(argv[i])
        i += 1
    return out


def _run_via_blender_script(venv_py: Path, src_root: str, forward: list[str]) -> int:
    """Run ``internscenes.render`` from within Blender's own Python interpreter.

    ``sys.executable`` inside Blender is the embedded Python binary (e.g.
    ``.../5.1/python/bin/python3.13``).  It does not understand ``--background``
    or ``--python`` because those are Blender CLI options.  We must re-invoke
    the real Blender binary and pass the generated script via ``--python``.
    """
    script = textwrap.dedent(
        """
        import sys
        import os
        sys.path.insert(0, os.environ.get("INTERN_SRC_ROOT", ""))
        # Import the render submodule without triggering a full internscenes import
        # (Blender's Python does not have project dependencies like trimesh).
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "internscenes.render",
            os.path.join(os.environ.get("INTERN_SRC_ROOT", ""), "internscenes", "render.py"),
        )
        render_mod = importlib.util.module_from_spec(spec)
        sys.modules["internscenes.render"] = render_mod
        spec.loader.exec_module(render_mod)
        sys.argv = ["__main__.py"] + (sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else [])
        raise SystemExit(render_mod.main())
        """
    ).strip()

    env = os.environ.copy()
    env["INTERN_SRC_ROOT"] = src_root
    env["INTERN_VENV_PY"] = str(venv_py)

    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as f:
        f.write(script)
        tmp_script = Path(f.name)

    # Locate the outer Blender binary from the embedded Python path.
    # Typical layout: <BLENDER_DIR>/5.1/python/bin/python3.13
    # Blender binary is <BLENDER_DIR>/blender.
    blender_bin = Path(sys.executable)
    parts = blender_bin.parts
    try:
        # Find the version directory (e.g. "5.1") and go two levels up.
        version_idx = next(
            i for i, p in enumerate(parts)
            if p.count(".") == 1 and p[0].isdigit() and parts[i - 1] == "python"
        )
        blender_bin = Path(*parts[:version_idx - 1]) / "blender"
    except StopIteration:
        # Fallback: search upward for a directory containing "blender".
        for parent in blender_bin.parents:
            candidate = parent / "blender"
            if candidate.exists():
                blender_bin = candidate
                break

    try:
        cmd = [str(blender_bin), "--background", "--python", str(tmp_script), "--"] + forward
        print("[blender bootstrap] running:", " ".join(cmd))
        proc = subprocess.run(cmd, env=env)
        return proc.returncode
    finally:
        try:
            tmp_script.unlink()
        except OSError:
            pass


def main() -> int:
    venv_py = os.environ.get("INTERN_VENV_PY")
    if not venv_py:
        print("ERROR: INTERN_VENV_PY is not set; cannot find project Python", file=sys.stderr)
        return 1
    venv_py = Path(venv_py)
    if not venv_py.exists():
        print(f"ERROR: project Python not found: {venv_py}", file=sys.stderr)
        return 1

    src_root = os.environ.get("INTERN_SRC_ROOT", str(Path(__file__).resolve().parent.parent))
    forward = _forward_args()
    return _run_via_blender_script(venv_py, src_root, forward)


if __name__ == "__main__":
    raise SystemExit(main())

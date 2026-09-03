"""Regression tests for using ManimLive without a desktop display."""

import os
from pathlib import Path
import subprocess
import sys
import textwrap
import unittest

REPO_ROOT = Path(__file__).resolve().parents[1]


class HeadlessImportTests(unittest.TestCase):
    def run_without_display(self, *args: str) -> subprocess.CompletedProcess:
        env = os.environ.copy()
        for name in (
            "DISPLAY",
            "WAYLAND_DISPLAY",
            "MIR_SOCKET",
        ):
            env.pop(name, None)
        return subprocess.run(
            [sys.executable, *args],
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )

    def assert_succeeded(self, result: subprocess.CompletedProcess) -> None:
        self.assertEqual(
            result.returncode,
            0,
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}",
        )

    def test_package_and_star_import_touch_no_window_toolkit(self):
        # The pyglet window is retired (2026-09-02): importing maniml must
        # not pull in pyglet or moderngl-window, which would try to reach
        # a display and are no longer dependencies.
        script = textwrap.dedent("""
            import sys
            import maniml
            from maniml import *

            assert "pyglet" not in sys.modules
            assert "moderngl_window" not in sys.modules
            assert not hasattr(maniml, "Window")
            assert Scene.__module__ == "maniml.scene.scene"
            """)
        self.assert_succeeded(self.run_without_display("-c", script))

    def test_cli_help_does_not_require_a_display(self):
        result = self.run_without_display("-m", "maniml", "--help")
        self.assert_succeeded(result)
        self.assertIn("usage:", result.stdout.lower())


if __name__ == "__main__":
    unittest.main()

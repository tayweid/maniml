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
            "PYGLET_HEADLESS",
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

    def test_package_and_star_import_do_not_create_a_shadow_window(self):
        script = textwrap.dedent("""
            import pyglet
            import maniml
            from maniml import *

            assert pyglet.options["shadow_window"] is False
            assert pyglet.gl._shadow_window is None
            assert maniml.Window is Window
            assert Scene.__module__ == "maniml.scene.scene"
            """)
        self.assert_succeeded(self.run_without_display("-c", script))

    def test_input_constants_match_native_pyglet_events(self):
        script = textwrap.dedent("""
            import maniml
            from maniml.event_constants import MouseButtons, WindowKeys
            from pyglet.window import key, mouse

            for name in (
                "MOD_SHIFT", "MOD_CTRL", "MOD_ALT", "MOD_CAPSLOCK",
                "MOD_COMMAND", "BACKSPACE", "TAB", "ENTER", "ESCAPE",
                "LEFT", "UP", "RIGHT", "DOWN", "SPACE",
            ):
                assert getattr(WindowKeys, name) == getattr(key, name), name
            for name in ("LEFT", "MIDDLE", "RIGHT"):
                assert getattr(MouseButtons, name) == getattr(mouse, name), name
            """)
        self.assert_succeeded(self.run_without_display("-c", script))

    def test_cli_help_does_not_require_a_display(self):
        result = self.run_without_display("-m", "maniml", "--help")
        self.assert_succeeded(result)
        self.assertIn("usage:", result.stdout.lower())


if __name__ == "__main__":
    unittest.main()

"""Windowed interactive tests. Each scenario opens a real OpenGL window
and drives the actual key/mouse handlers, so they need a display and are
opt-in:

    MANIML_WINDOW_TESTS=1 python -m unittest tests.test_interactive

Each scenario runs in its own subprocess for a fresh GL context; the
scripts can also be run directly (python -m tests.interactive.dev_mode).
"""
import os
import subprocess
import sys
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

requires_window = unittest.skipUnless(
    os.environ.get("MANIML_WINDOW_TESTS"),
    "windowed test; set MANIML_WINDOW_TESTS=1 to run",
)


def run_scenario(module: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", module],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=600,
    )


@requires_window
class TestInteractive(unittest.TestCase):
    def assert_scenario_passes(self, module: str):
        result = run_scenario(module)
        if result.returncode != 0:
            self.fail(
                f"{module} failed (exit {result.returncode})\n"
                f"--- stdout ---\n{result.stdout[-3000:]}\n"
                f"--- stderr ---\n{result.stderr[-3000:]}"
            )

    def test_dev_mode(self):
        self.assert_scenario_passes("tests.interactive.dev_mode")

    def test_present_mode(self):
        self.assert_scenario_passes("tests.interactive.present_mode")

    def test_ghost_regression(self):
        self.assert_scenario_passes("tests.interactive.ghost_regression")


if __name__ == "__main__":
    unittest.main()

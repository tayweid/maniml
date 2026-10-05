"""The presentation player seeks to a checkpoint's last frame, not the
next animation's first (tests/presentation_seek.cjs, driven in Node)."""
import shutil
import subprocess
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


@unittest.skipIf(shutil.which("node") is None, "node not available")
class PresentationSeekTests(unittest.TestCase):
    def test_a_seek_lands_on_the_checkpoints_last_frame(self):
        result = subprocess.run(
            ["node", str(REPO / "tests" / "presentation_seek.cjs")],
            capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("presentation seeks: ok", result.stdout)

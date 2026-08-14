"""End-to-end test of the baked web player (--export).

Exports a scene via the CLI, checks the static folder is complete, and
replays the recorded geometry stream through the reference renderer in
order — exactly what the player page does — verifying the delta chain
resolves and the frames render.
"""

import json
import os
import subprocess
import sys
import unittest

import numpy as np

SCENE_SOURCE = """
from manim import *

class ExportDemo(Scene):
    def construct(self):
        circle = Circle(color=BLUE, fill_opacity=0.6).shift(LEFT * 2)
        self.play(Create(circle))
        self.play(circle.animate.shift(RIGHT * 4))
"""

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class WebExportE2E(unittest.TestCase):
    def test_export_and_replay(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            scene_path = os.path.join(tmp, "export_scene.py")
            with open(scene_path, "w") as f:
                f.write(SCENE_SOURCE)
            result = subprocess.run(
                [sys.executable, "-m", "maniml", scene_path, "ExportDemo",
                 "--export"],
                cwd=tmp, env={**os.environ, "PYTHONPATH": REPO_ROOT},
                capture_output=True, text=True, timeout=120)
            self.assertEqual(result.returncode, 0,
                             result.stdout + result.stderr)

            out = os.path.join(tmp, "media", "ExportDemo_web")
            for name in ["index.html", "player.js", "gl.js", "webgpu.js",
                         "scene.json", "scene.bin.gz"]:
                self.assertTrue(os.path.exists(os.path.join(out, name)),
                                f"missing {name}")
            for dirname in ["glsl", "wgsl"]:
                self.assertTrue(
                    os.listdir(os.path.join(out, dirname)),
                    f"empty {dirname}")

            with open(os.path.join(out, "scene.json")) as f:
                meta = json.load(f)
            self.assertEqual(meta["scene"], "ExportDemo")
            self.assertEqual(meta["segments"], 2)
            self.assertGreater(len(meta["frames"]), 10)

            import gzip
            with gzip.open(os.path.join(out, "scene.bin.gz"), "rb") as f:
                blob = f.read()
            self.assertEqual(sum(fr["len"] for fr in meta["frames"]),
                             len(blob))

            # Replay in order through the reference renderer — the
            # player's exact procedure; the delta chain must resolve
            from maniml.web.geometry import parse_geometry_message
            from maniml.web.reference_renderer import ReferenceRenderer
            renderer = ReferenceRenderer()
            offset = 0
            last = None
            for frame in meta["frames"]:
                message = blob[offset:offset + frame["len"]]
                offset += frame["len"]
                header, vertex_bytes = parse_geometry_message(message)
                last = renderer.render(header, vertex_bytes)
            image = np.asarray(last.convert("RGB"), dtype=np.float64)
            background = np.array([26.0, 26.0, 26.0])
            frac_content = (
                np.abs(image - background).max(axis=2) > 8).mean()
            self.assertGreater(frac_content, 0.005,
                               "final frame looks empty")


if __name__ == "__main__":
    unittest.main()

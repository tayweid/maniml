"""End-to-end test of the baked web player (--export).

Exports a scene via the CLI, checks the static folder is complete, and walks
the recorded geometry stream in order — exactly what the player page does —
verifying that every cached batch resolves to content sent earlier.
"""

import json
import os
import subprocess
import sys
import unittest

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
            for name in ["index.html", "player.js", "webgpu.js",
                         "scene.json", "scene.bin.gz"]:
                self.assertTrue(os.path.exists(os.path.join(out, name)),
                                f"missing {name}")
            for dirname in ["wgsl"]:
                self.assertTrue(
                    os.listdir(os.path.join(out, dirname)),
                    f"empty {dirname}")
            self.assertFalse(os.path.exists(os.path.join(out, "gl.js")))
            self.assertFalse(os.path.exists(os.path.join(out, "glsl")))

            with open(os.path.join(out, "scene.json")) as f:
                meta = json.load(f)
            from maniml.web.geometry import GEOMETRY_FORMAT_VERSION

            self.assertEqual(meta["format_version"], GEOMETRY_FORMAT_VERSION)
            self.assertEqual(meta["scene"], "ExportDemo")
            self.assertEqual(meta["segments"], 2)
            self.assertGreater(len(meta["frames"]), 10)

            import gzip
            with gzip.open(os.path.join(out, "scene.bin.gz"), "rb") as f:
                blob = f.read()
            self.assertEqual(sum(fr["len"] for fr in meta["frames"]),
                             len(blob))

            # Replay the delta ledger in order. A cached batch is valid only
            # if an earlier frame supplied its bytes; this is the invariant
            # the player relies on before it can seek directly.
            from maniml.web.geometry import parse_geometry_message

            available_batches = set()
            offset = 0
            last_header = None
            for frame in meta["frames"]:
                message = blob[offset:offset + frame["len"]]
                offset += frame["len"]
                header, vertex_bytes = parse_geometry_message(message)
                self.assertEqual(
                    header["format_version"], GEOMETRY_FORMAT_VERSION)
                self.assertEqual(header["unsupported"], [])
                for batch in header["batches"]:
                    content_hash = batch["hash"]
                    if batch.get("cached"):
                        self.assertIn(content_hash, available_batches)
                    else:
                        self.assertIn("offset", batch)
                        self.assertLess(batch["offset"], len(vertex_bytes))
                        available_batches.add(content_hash)
                last_header = header
            self.assertTrue(available_batches)
            self.assertTrue(last_header["batches"])


if __name__ == "__main__":
    unittest.main()

"""The present bundle: mp4 + pausepoint table for video presenting.

A cheap unit layer over build_meta with a stub scene, and one real
end-to-end render (subprocess, real ffmpeg) that pins the property the
whole mode rests on: the frame of the video at a checkpoint's recorded
time matches the checkpoint PNG the render saves.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from types import SimpleNamespace

from maniml.web.present_bundle import build_meta, write_pausepoints

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def stub_scene(tmpdir, pause_anchored=False, checkpoints=None):
    source = Path(tmpdir) / "scene.py"
    source.write_text("class Fake: pass\n")

    class FakeScene:
        pass

    scene = FakeScene()
    scene._scene_filepath = str(source)
    scene._pause_anchored = lambda: pause_anchored
    scene._get_source_units = lambda: []
    scene.time = 2.5
    scene.camera = SimpleNamespace(fps=30, get_pixel_shape=lambda: (640, 360))
    scene.animation_checkpoints = checkpoints or [
        {"index": 0, "unit_index": -1, "line_number": 0,
         "state": SimpleNamespace(time=0.0)},
        {"index": 1, "unit_index": 0, "line_number": 7,
         "state": SimpleNamespace(time=1.0)},
        {"index": 2, "unit_index": 1, "line_number": 9, "stop": True,
         "name": "beat", "state": SimpleNamespace(time=2.0)},
    ]
    return scene


class BuildMetaTests(unittest.TestCase):
    def test_table_shape_and_stop_normalization(self):
        with tempfile.TemporaryDirectory() as d:
            meta = build_meta(stub_scene(d, pause_anchored=True))
        self.assertEqual(meta["format"], 1)
        self.assertEqual(meta["duration"], 2.5)
        self.assertEqual(meta["resolution"], [640, 360])
        times = [c["time"] for c in meta["checkpoints"]]
        self.assertEqual(times, [0.0, 1.0, 2.0])
        # pause-anchored: only flagged checkpoints (and Start) are stops
        self.assertEqual([c["stop"] for c in meta["checkpoints"]],
                         [True, False, True])
        self.assertEqual(meta["checkpoints"][2]["name"], "beat")
        self.assertIn("hash", meta["source"])

    def test_plain_files_make_every_checkpoint_a_stop(self):
        with tempfile.TemporaryDirectory() as d:
            meta = build_meta(stub_scene(d, pause_anchored=False))
        self.assertTrue(all(c["stop"] for c in meta["checkpoints"]))

    def test_table_lands_beside_the_movie_and_nothing_else(self):
        """The presentation cache is the rendered mp4 plus ONE json — no
        folder, no page, no copies."""
        with tempfile.TemporaryDirectory() as d:
            scene = stub_scene(d)
            dest = write_pausepoints(scene)
            self.assertEqual(dest, Path(d) / "media"
                             / "FakeScene.pausepoints.json")
            meta = json.loads(dest.read_text())
            self.assertEqual(meta["scene"], "FakeScene")
            self.assertFalse((Path(d) / "media" / "FakeScene_present").exists())


class PresentBundleTests(unittest.TestCase):
    """The --export-present student bundle: a standalone folder beside
    the cache, never part of it."""

    def test_bundle_is_complete_and_standalone(self):
        from maniml.web.present_bundle import write_present_bundle

        with tempfile.TemporaryDirectory() as d:
            scene = stub_scene(d)
            movie = Path(d) / "media" / "FakeScene.mp4"
            movie.parent.mkdir(parents=True, exist_ok=True)
            movie.write_bytes(b"fake-mp4-bytes")
            dest = write_present_bundle(scene, movie)
            self.assertEqual(dest, Path(d) / "media" / "FakeScene_present")
            self.assertEqual(
                sorted(p.name for p in dest.iterdir()),
                ["index.html", "present.json", "present_meta.js",
                 "presentation.js", "rail.js", "scene.mp4"])
            self.assertEqual(json.loads((dest / "present.json").read_text()),
                             build_meta(scene))
            # The table rides as a script (file:// has no fetch) and
            # matches build_meta exactly
            meta_js = (dest / "present_meta.js").read_text()
            self.assertTrue(meta_js.startswith("window.MANIML_PRESENT = "))
            embedded = json.loads(
                meta_js[len("window.MANIML_PRESENT = "):].rstrip().rstrip(";"))
            self.assertEqual(embedded, build_meta(scene))
            self.assertEqual((dest / "scene.mp4").read_bytes(),
                             b"fake-mp4-bytes")
            self.assertIn('<script src="presentation.js"></script>',
                          (dest / "index.html").read_text())

    def test_republish_replaces_atomically(self):
        from maniml.web.present_bundle import write_present_bundle

        with tempfile.TemporaryDirectory() as d:
            scene = stub_scene(d)
            movie = Path(d) / "media" / "FakeScene.mp4"
            movie.parent.mkdir(parents=True, exist_ok=True)
            movie.write_bytes(b"take-one")
            dest = write_present_bundle(scene, movie)
            stale = dest / "leftover.txt"
            stale.write_text("from an older bundle")
            movie.write_bytes(b"take-two")
            write_present_bundle(scene, movie)
            self.assertEqual((dest / "scene.mp4").read_bytes(), b"take-two")
            self.assertFalse(stale.exists(),
                             "a republish must be a clean replacement")

    def test_consume_movie_leaves_only_the_bundle(self):
        from maniml.web.present_bundle import write_present_bundle

        with tempfile.TemporaryDirectory() as d:
            scene = stub_scene(d)
            media = Path(d) / "media"
            media.mkdir(parents=True, exist_ok=True)
            movie = media / "FakeScene.mp4"
            movie.write_bytes(b"movie")
            stale = media / "FakeScene.pausepoints.json"
            stale.write_text("{}")
            dest = write_present_bundle(scene, movie, consume_movie=True)
            self.assertFalse(movie.exists())
            self.assertFalse(stale.exists())
            self.assertEqual(sorted(p.name for p in media.iterdir()),
                             ["FakeScene_present"])
            self.assertEqual((dest / "scene.mp4").read_bytes(), b"movie")

    def test_missing_movie_is_an_error(self):
        from maniml.web.present_bundle import write_present_bundle

        with tempfile.TemporaryDirectory() as d:
            scene = stub_scene(d)
            with self.assertRaises(FileNotFoundError):
                write_present_bundle(
                    scene, Path(d) / "media" / "FakeScene.mp4")


class PresentationSourcesTests(unittest.TestCase):
    """The viewer presents from the root cache or the student bundle,
    whichever table is newer — so the root pair is deletable once a
    bundle exists."""

    def make(self, d, root=False, bundle=False):
        scene = stub_scene(d)
        media = Path(d) / "media"
        media.mkdir(parents=True, exist_ok=True)
        if root:
            (media / "FakeScene.mp4").write_bytes(b"root-movie")
            (media / "FakeScene.pausepoints.json").write_text("{}")
        if bundle:
            folder = media / "FakeScene_present"
            folder.mkdir(exist_ok=True)
            (folder / "scene.mp4").write_bytes(b"bundle-movie")
            (folder / "present.json").write_text("{}")
        return scene, media

    def test_bundle_alone_is_a_complete_source(self):
        from maniml.web.present_bundle import presentation_sources

        with tempfile.TemporaryDirectory() as d:
            scene, media = self.make(d, bundle=True)
            table, movie = presentation_sources(scene)
            self.assertEqual(table, media / "FakeScene_present" / "present.json")
            self.assertEqual(movie, media / "FakeScene_present" / "scene.mp4")

    def test_newer_table_wins(self):
        from maniml.web.present_bundle import presentation_sources

        with tempfile.TemporaryDirectory() as d:
            scene, media = self.make(d, root=True, bundle=True)
            old, new = 1_000_000_000, 2_000_000_000
            os.utime(media / "FakeScene_present" / "present.json", (old, old))
            os.utime(media / "FakeScene.pausepoints.json", (new, new))
            table, movie = presentation_sources(scene)
            self.assertEqual(table, media / "FakeScene.pausepoints.json")
            self.assertEqual(movie, media / "FakeScene.mp4")
            os.utime(media / "FakeScene_present" / "present.json", (new, new))
            os.utime(media / "FakeScene.pausepoints.json", (old, old))
            table, movie = presentation_sources(scene)
            self.assertEqual(table, media / "FakeScene_present" / "present.json")

    def test_nothing_rendered_falls_back_to_root_paths(self):
        from maniml.web.present_bundle import presentation_sources

        with tempfile.TemporaryDirectory() as d:
            scene, media = self.make(d)
            table, movie = presentation_sources(scene)
            self.assertEqual(table, media / "FakeScene.pausepoints.json")
            self.assertEqual(movie, media / "FakeScene.mp4")

    def test_table_without_movie_is_not_a_source(self):
        from maniml.web.present_bundle import presentation_sources

        with tempfile.TemporaryDirectory() as d:
            scene, media = self.make(d, root=True, bundle=True)
            (media / "FakeScene_present" / "scene.mp4").unlink()
            new = 2_000_000_000
            os.utime(media / "FakeScene_present" / "present.json", (new, new))
            table, movie = presentation_sources(scene)
            self.assertEqual(table, media / "FakeScene.pausepoints.json")
            self.assertEqual(movie, media / "FakeScene.mp4")


RENDER_SCENE = textwrap.dedent('''\
    from manim import *

    class Tiny(Scene):
        def construct(self):
            square = Square(fill_opacity=1.0, fill_color="#2255AA")
            self.play(FadeIn(square), run_time=0.4)
            self.play(square.animate.shift(RIGHT * 2), run_time=0.4)
            self.wait(0.3)
''')


@unittest.skipIf(shutil.which("ffmpeg") is None, "ffmpeg not available")
class RenderAlignmentE2E(unittest.TestCase):
    """--render writes the bundle, and the video frame at each checkpoint's
    recorded time matches the checkpoint PNG the render saves."""

    @classmethod
    def setUpClass(cls):
        cls.tmpdir = tempfile.TemporaryDirectory()
        scene_path = os.path.join(cls.tmpdir.name, "tiny_scene.py")
        with open(scene_path, "w") as f:
            f.write(RENDER_SCENE)
        result = subprocess.run(
            [sys.executable, "-m", "maniml", scene_path, "Tiny", "--render"],
            cwd=cls.tmpdir.name,
            env={**os.environ, "PYTHONPATH": REPO_ROOT},
            capture_output=True, text=True, timeout=300,
        )
        cls.render_output = result.stdout + result.stderr
        cls.media = Path(cls.tmpdir.name) / "media"

    @classmethod
    def tearDownClass(cls):
        cls.tmpdir.cleanup()

    def test_table_exists_with_sane_meta(self):
        self.assertTrue((self.media / "Tiny.mp4").is_file(), self.render_output)
        self.assertFalse((self.media / "Tiny_present").exists())
        meta = json.loads((self.media / "Tiny.pausepoints.json").read_text())
        self.assertEqual(meta["format"], 1)
        self.assertGreaterEqual(len(meta["checkpoints"]), 3)
        times = [c["time"] for c in meta["checkpoints"]]
        self.assertEqual(times, sorted(times))
        self.assertGreater(meta["duration"], times[-1] - 1e-6)

    def test_video_frame_at_checkpoint_time_matches_the_png(self):
        from PIL import Image
        import numpy as np

        meta = json.loads((self.media / "Tiny.pausepoints.json").read_text())
        pngs = self.media / "Tiny_checkpoints"
        # compare the post-shift checkpoint (clearly distinct picture)
        checkpoint = meta["checkpoints"][2]
        png_path = pngs / f"{checkpoint['index']:03d}.png"
        self.assertTrue(png_path.is_file(), self.render_output)

        frame_path = Path(self.tmpdir.name) / "extract.png"
        # a hair before the timestamp: the checkpoint records the state at
        # the end of its play, whose frame is the last one written before
        # scene.time reached it
        seek = max(0.0, checkpoint["time"] - 0.5 / meta["fps"])
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error",
             "-ss", f"{seek:.4f}", "-i", str(self.media / "Tiny.mp4"),
             "-frames:v", "1", str(frame_path)],
            check=True, timeout=60,
        )
        video = np.asarray(
            Image.open(frame_path).convert("RGB"), dtype=float)
        png = np.asarray(
            Image.open(png_path).convert("RGB").resize(
                (video.shape[1], video.shape[0])), dtype=float)
        mean_diff = float(np.abs(video - png).mean())
        self.assertLess(
            mean_diff, 8.0,
            f"video frame at t={checkpoint['time']} diverges from the "
            f"checkpoint PNG (mean |diff| {mean_diff:.2f})")


if __name__ == "__main__":
    unittest.main()

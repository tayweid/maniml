"""benchmarks.play_frames on a small headless scene: each mode replays the
whole play, the modes taking turns, with what the messages carry and the
movers at the middle frame; the browser streams replay in Node. No
episode, no TeX, no GPU. The scene runs from a temp file, as
tests.test_episode_frames runs its own."""

import os
import shutil
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest.mock import patch

from benchmarks import episode_frames, play_frames
from benchmarks.browser_frames import replay_rounds
from maniml.web.triangle_geometry import _packaged_library

requires_lyon = unittest.skipUnless(os.environ.get("MANIML_LYON_LIBRARY") or _packaged_library(),
                                    "Lyon helper is neither packaged nor explicitly built")

# A path without fill created while a filled square moves: under strokes
# the ring is a program (docs/phase_b4_plan.md, B5.3), the square the CPU's.
PLAY_SCENE = textwrap.dedent('''\
    from maniml import *

    class PlayScene(Scene):
        def construct(self):
            ring = Circle(radius=1, stroke_width=6)
            square = Square(fill_opacity=1).shift(2 * RIGHT)
            self.add(square)
            self.play(ShowCreation(ring), square.animate.shift(UP), run_time=0.3)
    ''')


@requires_lyon
class PlayFrames(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        path = Path(self.tmpdir.name) / "play_scene.py"
        path.write_text(PLAY_SCENE)
        # The harness sets the modes in the environment; this puts it back.
        self.environ = patch.dict(os.environ, play_frames.ENVIRONMENT)
        self.environ.start()
        self.scene, error = episode_frames.load_episode(path, "PlayScene")
        self.assertIsNone(error)

    def tearDown(self):
        # A headless scene owns a standalone GPU context.
        self.scene.camera.release()
        self.environ.stop()
        self.tmpdir.cleanup()

    def test_each_mode_replays_the_whole_play(self):
        frames = episode_frames.play_frame_count(self.scene.camera.fps, .3)
        for fmt in (7, 8):
            with self.subTest(format=fmt):
                result = play_frames.measure_play(self.scene, 1, ["off", "strokes"], 2, fmt, render=False)
                for data in result.values():
                    self.assertEqual(len(data["per_frame"]["serialize_ms"]), frames)
                    self.assertEqual(data["summary"]["serialize_ms"]["n"], frames - 1)
                    self.assertIsNone(data["per_frame"]["scene_ms"][0], "the entry follows the still")
                    self.assertEqual(len(data["carried_first_replay"]), frames)
                self.assertEqual((result["off"]["middle"]["movers"], result["strokes"]["middle"]["movers"]), (2, 2))
                self.assertEqual((result["off"]["middle"]["programs"], result["strokes"]["middle"]["programs"]),
                                 (0, 1))
                off, strokes = (result[mode]["carried_first_replay"] for mode in ("off", "strokes"))
                if fmt == 7:
                    self.assertEqual({row["program_batches"] for row in off}, {0})
                    self.assertEqual({row["program_batches"] for row in strokes}, {1})
                else:
                    # The entry is a delta against the still; past it the
                    # ring's program holds its place and sends its scalars.
                    self.assertFalse(any(row.get("scalars_ops") for row in off))
                    self.assertTrue(all(row["scalars_ops"] == 1 for row in strokes[1:]))

    @unittest.skipUnless(shutil.which("node"), "node plays the streams")
    def test_browser_streams_replay_in_both_formats(self):
        with tempfile.TemporaryDirectory() as tmp:
            folders = play_frames.record_browser(self.scene, 1, ["off", "strokes"], Path(tmp))
            self.assertEqual(set(folders), {(mode, fmt) for mode in ("off", "strokes") for fmt in (7, 8)})
            replayed = replay_rounds(list(folders.values()), 1, realm="main")
        frames = episode_frames.play_frame_count(self.scene.camera.fps, .3)
        summaries = {key: play_frames.browser_summary(replayed[folder]["frames"]) for key, folder in folders.items()}
        for summary in summaries.values():
            self.assertEqual(summary["frames"], frames)
        # The ring's program is a compute pass of its own each frame.
        for fmt in (7, 8):
            self.assertGreater(summaries[("strokes", fmt)]["compute_passes"], summaries[("off", fmt)]["compute_passes"])


if __name__ == "__main__":
    unittest.main()

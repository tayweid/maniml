"""Stream recording, Node replay and report shape of
benchmarks.browser_frames on a small headless scene: the recorded folder is
the export recorder's format (the recording indexer reads it back and draws
every frame), the counting fake device returns one row per frame, and the
classes reduce as documented. No GPU: the Lyon helper tessellates the Phase
A fills and Node runs the driver, as tests.test_generated_webgpu_commands
needs them."""

import gzip
import importlib.util
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
from unittest.mock import patch

from benchmarks import browser_frames, episode_frames

TESTS = Path(__file__).resolve().parent

# A fade, a pausepoint, then a shift watched by an updater, so the second
# pausepoint ticks and both plays are recorded mid-interpolation.
SCENE = textwrap.dedent('''\
    from maniml import *

    class PlayScene(Scene):
        def construct(self):
            square = Square(fill_color=BLUE, fill_opacity=0.6)
            self.play(FadeIn(square), run_time=0.2)
            self.pause()
            dot = Dot(color=RED)
            dot.add_updater(lambda m: m.next_to(square, UP))
            self.add(dot)
            self.play(square.animate.shift(RIGHT), run_time=0.3)
            self.wait(0.1)
            self.pause()
    ''')


def _lyon():
    return bool(os.environ.get("MANIML_LYON_LIBRARY")) or importlib.util.find_spec("maniml.web.maniml_lyon_fill")


def messages_of(stream):
    from maniml.web.geometry import parse_geometry_message

    blob = gzip.open(stream.directory / "scene.bin.gz").read()
    offset, parsed = 0, []
    for entry in stream.meta["frames"]:
        parsed.append(parse_geometry_message(blob[offset:offset + entry["len"]]))
        offset += entry["len"]
    assert offset == len(blob)
    return parsed


@unittest.skipIf(shutil.which("node") is None, "node not available")
@unittest.skipUnless(_lyon(), "the Lyon helper is the frame preparer's tessellator")
class BrowserFrames(unittest.TestCase):
    """Both variants recorded once from one headless scene, two rounds after
    one warmup per frame, updaters ticking and the plays recorded."""

    @classmethod
    def setUpClass(cls):
        cls.tmpdir = tempfile.TemporaryDirectory()
        root = Path(cls.tmpdir.name)
        (root / "play_scene.py").write_text(SCENE)
        cls.scene, error = episode_frames.load_episode(root / "play_scene.py", "PlayScene")
        assert error is None, error
        cls.indices = episode_frames.select_frames(cls.scene.animation_checkpoints)
        cls.streams = {}
        for variant in browser_frames.VARIANTS:
            with patch.dict(os.environ, browser_frames.ENVIRONMENTS[variant]):
                messages, entries, frames = browser_frames.record_stream(
                    cls.scene, cls.indices, samples=2, warmups=1, tick_updaters=True, play_frames=True)
            directory = root / variant
            meta = browser_frames.write_stream(directory, cls.scene, messages, entries, variant=variant,
                                               environment=browser_frames.ENVIRONMENTS[variant])
            cls.streams[variant] = SimpleNamespace(directory=directory, entries=entries, frames=frames, meta=meta,
                                                   bytes=sum(map(len, messages)))

    @classmethod
    def tearDownClass(cls):
        # A headless scene owns a standalone GPU context; release it as
        # tests.test_episode_frames does.
        cls.scene.camera.release()
        cls.tmpdir.cleanup()

    def test_the_stream_is_the_export_recorders_folder_with_the_frames_named(self):
        from maniml.web.geometry import GEOMETRY_FORMAT_VERSION

        stream = self.streams["phase_a"]
        meta = stream.meta
        self.assertEqual((meta["format_version"], meta["scene"], meta["fps"]),
                         (GEOMETRY_FORMAT_VERSION, "PlayScene", int(self.scene.camera.fps)))
        self.assertEqual((meta["harness"], meta["variant"]), ("browser_frames", "phase_a"))
        self.assertEqual(self.indices, [2, 4])
        # Two pausepoints, each one warmup + two samples, then three frames
        # of the play into it: a segment per group, dense from zero.
        self.assertEqual(len(meta["frames"]), 2 * 3 + 3 + 3)
        self.assertEqual(meta["segments"], 4)
        self.assertEqual([entry["segment"] for entry in meta["frames"]], [0] * 3 + [1] * 3 + [2] * 3 + [3] * 3)
        self.assertEqual(sum(entry["len"] for entry in meta["frames"]), stream.bytes)
        pausepoints = [entry for entry in meta["frames"] if entry["phase"] == "pausepoint"]
        self.assertEqual([(entry["iteration"], entry["warmup"], entry["cold"]) for entry in pausepoints],
                         [(0, True, True), (1, False, False), (2, False, False)] * 2)
        self.assertEqual([entry["updaters_ticked"] for entry in pausepoints], [False] * 3 + [True] * 3)
        plays = [entry for entry in meta["frames"] if entry["phase"] == "play"]
        self.assertEqual([entry["play_checkpoint"] for entry in plays], [1] * 3 + [3] * 3)
        self.assertEqual([entry["warmup"] for entry in plays], [True, False, False] * 2)
        for first, second in zip(plays, plays[1:]):
            if first["play_checkpoint"] == second["play_checkpoint"]:
                self.assertLess(first["alpha"], second["alpha"])
        self.assertTrue(all(0 < entry["alpha"] <= 1 and entry["serialize_ms"] > 0 for entry in plays))
        self.assertEqual([frame["checkpoint"] for frame in stream.frames], [2, 4])
        self.assertEqual([frame["updaters_ticked"] for frame in stream.frames], [False, True])
        self.assertEqual([frame["play"]["checkpoint"] for frame in stream.frames], [1, 3])
        self.assertEqual([len(frame["play"]["measured_alphas"]) for frame in stream.frames], [2, 2])
        # A segment is a recorded group and names its own line: the
        # pausepoint's checkpoint, then the play's, so the player's chips
        # name the frames.
        checkpoints = self.scene.animation_checkpoints
        self.assertEqual(meta["lines"], [checkpoints[index]["line_number"] for index in (2, 1, 4, 3)])
        self.assertEqual(len(meta["lines"]), meta["segments"])
        # The replay invariant the player relies on: a cached batch was sent
        # by an earlier message. One cache spans the stream, so a cold row
        # re-sends only what the previous message did not carry; here both
        # cold rows send every batch, the first because nothing precedes it
        # and the second because it follows a mid-FadeIn frame of a square
        # that has since moved (the episode streams' cold rows are mostly
        # partial, which cached_batches reports).
        available, cold_batches = set(), []
        for entry, (header, payload) in zip(meta["frames"], messages_of(stream)):
            self.assertEqual((header["renderer"], header["format_version"]), ("triangles", GEOMETRY_FORMAT_VERSION))
            cached = [batch.get("cached", False) for batch in header["batches"]]
            if entry["cold"]:
                cold_batches.append(cached)
            for batch in header["batches"]:
                if batch.get("cached"):
                    self.assertIn(batch["hash"], available)
                else:
                    self.assertLess(batch["offset"], len(payload))
                    available.add(batch["hash"])
        self.assertEqual(cold_batches, [[False] * 2, [False] * 3])
        # The player's own load path over the folder, as tests.test_export
        # drives it on an export: every frame forward, back and by segment.
        result = subprocess.run(["node", str(TESTS / "player_commands.cjs"), "export", str(stream.directory)],
                                input="", capture_output=True, text=True, timeout=120)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout)["frames"], len(meta["frames"]))

    def test_the_phase_b_stream_carries_programs_and_the_indexer_draws_it_back(self):
        stream = self.streams["phase_b"]
        self.assertEqual(stream.meta["environment"], browser_frames.ENVIRONMENTS["phase_b"])
        kinds = set()
        for entry, (header, _) in zip(stream.meta["frames"], messages_of(stream)):
            for batch in header["batches"]:
                kinds.add((entry["phase"], batch["pipeline"], "program" in batch))
        self.assertLessEqual({("pausepoint", "patch", False), ("play", "patch", True), ("play", "stroke", True)}, kinds)
        # Every frame reconstructed by geometry_recording.js, forward, back
        # and out of order, draws with nothing missing.
        result = subprocess.run(["node", str(TESTS / "generated_webgpu_commands.cjs"), "recordingReplay",
                                 str(stream.directory)], capture_output=True, text=True, timeout=120)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout)["frames"], len(stream.meta["frames"]))

    def test_the_replay_reports_one_row_per_frame_with_the_drivers_calls(self):
        stream = self.streams["phase_a"]
        replayed = browser_frames.replay_stream(stream.directory)
        self.assertEqual(replayed["node"], subprocess.run(["node", "--version"], capture_output=True,
                                                          text=True).stdout.strip())
        self.assertGreater(replayed["init_ms"], 0)
        rows = browser_frames.join_rows(stream.entries, replayed["frames"])
        self.assertEqual(len(rows), len(stream.entries))
        for row, (header, _) in zip(rows, messages_of(stream)):
            self.assertGreater(row["js_ms"], 0)
            self.assertEqual(row["batches"], len(header["batches"]))
            self.assertEqual(row["cached_batches"], sum(bool(batch.get("cached")) for batch in header["batches"]))
            self.assertEqual(row["submits"], 1)
            self.assertGreaterEqual(row["render_passes"], 2, "the scene pass and the present pass")
            self.assertNotIn("cache_misses", row)
            self.assertNotIn("index", row)
        cold, warm = rows[0], rows[1:3]
        self.assertTrue(cold["cold"])
        self.assertGreater(cold["buffers_created"], 0)
        self.assertGreater(cold["bytes_uploaded"], 0)
        self.assertGreater(cold["uniform_writes"], 0)
        # A still redraw uploads nothing and draws what the cold frame drew.
        for row in warm:
            self.assertEqual((row["buffers_created"], row["bytes_uploaded"], row["uniform_writes"]), (0, 0, 0))
            self.assertEqual(row["draws"], cold["draws"])
            self.assertGreater(row["set_pipeline_calls"], 0)
        self.assertTrue(all(row["buffers_created"] > 0 for row in rows if row["phase"] == "play"),
                        "a play frame moves its square, so its geometry is re-sent")
        self.assertEqual([browser_frames.frame_class(row) for row in rows],
                         ["cold", "pausepoint", "pausepoint", "play", "play", "play",
                          "cold", "ticked", "ticked", "play", "play", "play"])
        classes = {cls: browser_frames.summarize(browser_frames.measured(rows, cls)) for cls in browser_frames.CLASSES}
        self.assertEqual({cls: stats["js_ms"]["n"] for cls, stats in classes.items()},
                         {"pausepoint": 2, "ticked": 2, "play": 4, "cold": 2})
        self.assertEqual(set(classes["play"]), set(browser_frames.COLUMNS))
        self.assertEqual(classes["cold"]["draws"], {"p50": cold["draws"] + .5, "min": cold["draws"], "n": 2})
        # A miss or a short replay is the harness's error, not a column.
        with self.assertRaises(RuntimeError):
            browser_frames.join_rows(stream.entries, replayed["frames"][:-1])
        missed = [dict(row, cache_misses=1) for row in replayed["frames"]]
        with self.assertRaises(RuntimeError):
            browser_frames.join_rows(stream.entries, missed)

    def test_report_summary_and_table_shape(self):
        report = {"frames": [], "variants": {}}
        for variant, stream in self.streams.items():
            replayed = browser_frames.replay_stream(stream.directory)
            rows = browser_frames.join_rows(stream.entries, replayed["frames"])
            classes = browser_frames.assemble(report, variant, rows, stream.frames,
                                              environment=browser_frames.ENVIRONMENTS[variant],
                                              stream={"frames": len(rows)})
            self.assertEqual(set(classes), set(browser_frames.CLASSES))
        self.assertEqual([frame["checkpoint"] for frame in report["frames"]], [2, 4])
        first, second = report["frames"]
        for variant in browser_frames.VARIANTS:
            self.assertEqual(set(first["variants"][variant]), {"pausepoint", "play", "cold", "cold_row"})
            self.assertEqual(set(second["variants"][variant]), {"ticked", "play", "cold", "cold_row"})
            self.assertTrue(first["variants"][variant]["cold_row"]["cold"])
            self.assertEqual(first["variants"][variant]["play"]["js_ms"]["n"], 2)
        summary = browser_frames.summary_of(report)
        self.assertNotIn("rows", summary["variants"]["phase_a"])
        self.assertEqual(summary["variants"]["phase_b"]["stream"], {"frames": 12})
        table = browser_frames.markdown_table(summary)
        lines = table.splitlines()
        # Header, rule, three classes per frame, then one closing line per class.
        self.assertEqual(len(lines), 2 + 3 * 2 + 4)
        self.assertTrue(all(line.count("|") == lines[0].count("|") for line in lines))
        self.assertIn("phase_b js p50/min", lines[0])
        self.assertIn("phase_a batches (cached)", lines[0])
        # A still redraw's batches are all cached; the shape is "n (m)".
        still = first["variants"]["phase_a"]["pausepoint"]
        self.assertIn(f"| {still['batches']['p50']:.0f} ({still['cached_batches']['p50']:.0f}) |", lines[2])
        alphas = first["play"]["measured_alphas"]
        self.assertIn(f"| play α {alphas[0]:.2f}–{alphas[-1]:.2f} |", table)
        self.assertIn("| 1 | 4 | 13 |  | ticked |", table)
        self.assertEqual(lines[-4].split(" | ")[4], "pausepoint")
        self.assertTrue(lines[-1].startswith("| all |  |  |  | cold |"))


if __name__ == "__main__":
    unittest.main()

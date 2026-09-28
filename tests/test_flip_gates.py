"""benchmarks.flip_gates (docs/phase_b4_plan.md, "The flips"): the stacks
it serializes are the other harnesses' variants, its serializers take turns
on a real headless scene, and the complete frame, the verdict and the pixel
pick on stand-in reports. No episode, no TeX, no GPU."""

import json
import os
import tempfile
import textwrap
from pathlib import Path
import unittest

from unittest.mock import patch

from benchmarks import browser_frames, episode_frames, flip_gates, gpu_borders, play_frames
from maniml.web.triangle_geometry import _packaged_library
from tests import surface_fixtures

requires_lyon = unittest.skipUnless(os.environ.get("MANIML_LYON_LIBRARY") or _packaged_library(),
                                    "Lyon helper is neither packaged nor explicitly built")


class Stacks(unittest.TestCase):
    def test_a_flip_is_the_variant_the_other_harnesses_measure(self):
        for flip, (browser, frames) in flip_gates.FLIPS.items():
            with self.subTest(flip=flip):
                self.assertIn(browser, browser_frames.ENVIRONMENTS)
                self.assertIn(frames, episode_frames.VARIANTS)
                self.assertIn(f"{'patch' if flip == 'patches' else 'nets'}_vs_gpu_border",
                              [name for name, _, _ in episode_frames.PIXEL_PAIRS])
                (a, a_renderer, _), (b, b_renderer, environment) = flip_gates.stacks(flip)
                self.assertEqual((a, a_renderer), ("phase_a", "phase_a"))
                self.assertEqual((b, b_renderer), (browser, "triangles"))
                # The stack episode_frames draws the flip's pixels and GPU with.
                for key, value in gpu_borders.SWITCHES[frames].items():
                    self.assertEqual(environment[key], value, key)
        self.assertEqual(flip_gates.PHASE_A, ("phase_a", "gpu_border"))
        self.assertEqual(gpu_borders.ROUTES["gpu_border"], "phase_a")

    def test_the_fixtures_draw_nets_as_the_harnesses_do(self):
        self.assertEqual(surface_fixtures.NETS, browser_frames.ENVIRONMENTS["phase_a_nets"])


SCENE = textwrap.dedent('''\
    from maniml import *

    class Flips(Scene):
        def construct(self):
            square = Square(fill_opacity=1)
            self.play(FadeIn(square), run_time=0.2)
            self.pause()
            clock = ValueTracker(0)
            dot = Dot().add_updater(lambda d, dt: d.shift(RIGHT * dt))
            self.add(clock, dot)
            self.play(square.animate.shift(RIGHT), run_time=0.3)
            self.pause()
    ''')


@requires_lyon
class Serialize(unittest.TestCase):
    """The four serializers on a real headless scene: a still pausepoint,
    a ticked one, their camera moves and plays."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        path = Path(self.tmpdir.name) / "flips.py"
        path.write_text(SCENE)
        self.scene, error = episode_frames.load_episode(path, "Flips")
        self.assertIsNone(error)

    def tearDown(self):
        self.scene.camera.release()
        self.tmpdir.cleanup()

    def test_the_serializers_take_turns_per_class(self):
        scene = self.scene
        indices = episode_frames.select_frames(scene.animation_checkpoints)
        frames = flip_gates.measure_serialize(scene, indices, "patches", samples=2, warmups=1, replays=1,
                                              tick_updaters=True, play_frames=True, camera_moves=True)
        keys = ["phase_a_f7", "phase_a_f8", "phase_a_patches_f7", "phase_a_patches_f8"]
        still, ticked = frames
        self.assertEqual((still["class"], ticked["class"]), ("pausepoint", "ticked"))
        for frame in frames:
            block = frame[frame["class"]]
            self.assertEqual(list(block), keys)
            self.assertTrue(all(block[key]["n"] == 2 for key in keys))
            self.assertEqual(list(frame["camera"]), keys)
            self.assertTrue(all(frame["camera"][key]["n"] == 2 * 3 for key in keys), "two rounds of three moves")
            play = frame["play"]
            self.assertEqual(play["checkpoint"], frame["checkpoint"] - 1)
            for key in keys:
                self.assertEqual(len(play[key]["per_frame_p50"]), len(play["measured_frames"]))
                self.assertEqual(play[key]["n"], len(play["measured_frames"]))
        # A still frame sends a negotiated page nothing, a full frame each
        # round otherwise; a tick moves the dot, and a camera move is a delta.
        self.assertEqual((still["pausepoint"]["phase_a_f8"]["sent"], still["pausepoint"]["phase_a_f7"]["sent"]), (0, 2))
        self.assertEqual(ticked["ticked"]["phase_a_patches_f8"]["sent"], 2)
        self.assertEqual(still["camera"]["phase_a_f8"]["sent"], 6)
        by_frame = flip_gates.serialize_by_frame(frames, "phase_a_patches_f8")
        self.assertEqual(sorted(by_frame), sorted([(still["checkpoint"], "pausepoint"), (still["checkpoint"], "camera"),
                                                   (still["checkpoint"], "play"), (ticked["checkpoint"], "ticked"),
                                                   (ticked["checkpoint"], "camera"), (ticked["checkpoint"], "play")]))


def browser_rows(checkpoint, cls, page, sent=True, count=3):
    phase = {"ticked": "pausepoint", "pausepoint": "pausepoint"}.get(cls, cls)
    return [{"checkpoint": checkpoint, "phase": phase, "warmup": False, "cold": False,
             "updaters_ticked": cls == "ticked", "page_ms": page, "sent": sent} for _ in range(count)]


def gpu_report(values, column="gpu_total_ms"):
    """An episode_frames report: {(checkpoint, phase, ticked): [ms, ...]}
    per variant, as ``column`` (an attribution run's gpu_total_ms, or a
    flag-off run's wall clock)."""
    frames, variants = {}, {}
    for variant, rows in values.items():
        samples = []
        for (checkpoint, phase, ticked), gpus in rows.items():
            frame = frames.setdefault(checkpoint, {"checkpoint": checkpoint, "updaters_ticked": False})
            if phase == "pausepoint":
                frame["updaters_ticked"] = ticked
            samples += [{"checkpoint": checkpoint, "phase": phase, "warmup": False, column: gpu} for gpu in gpus]
            samples.append({"checkpoint": checkpoint, "phase": phase, "warmup": True, column: 99.})
        variants[variant] = {"samples": samples}
    return {"frames": list(frames.values()), "variants": variants}


class Complete(unittest.TestCase):
    """Two frames, a still (2) and a ticked one (5, with its play): per
    frame serialize + page + sent GPU, then the class's median."""

    def reports(self):
        def serialize_block(ms):
            return {name: {"p50": value, "min": value, "n": 12, "sent": 12} for name, value in ms.items()}

        serialize = {"frames": [
            {"checkpoint": 2, "class": "pausepoint",
             "pausepoint": serialize_block({"phase_a_f7": 1., "phase_a_f8": 1., "phase_a_nets_f7": 2.,
                                            "phase_a_nets_f8": 2.})},
            {"checkpoint": 5, "class": "ticked",
             "ticked": serialize_block({"phase_a_f7": 3., "phase_a_f8": 3., "phase_a_nets_f7": 3., "phase_a_nets_f8": 3.}),
             "play": {name: {"per_frame_p50": [4., 6.]} for name in
                      ("phase_a_f7", "phase_a_f8", "phase_a_nets_f7", "phase_a_nets_f8")}}]}
        browser = {"variants": {}}
        for name, page in (("phase_a", .5), ("phase_a_nets", .5)):
            browser["variants"][name] = {"rows": browser_rows(2, "pausepoint", page) + browser_rows(5, "ticked", page)
                                         + browser_rows(5, "play", 1.)}
            # Format 8: the still is not sent, the ticked frame is.
            browser["variants"][name + "_delta"] = {"rows": browser_rows(2, "pausepoint", 0., sent=False)
                                                    + browser_rows(5, "ticked", .2) + browser_rows(5, "play", .8)}
        gpu = [gpu_report({"gpu_border": {(2, "pausepoint", False): [2., 2., 4.], (5, "pausepoint", True): [3.],
                                          (5, "play", False): [5.]},
                           "nets": {(2, "pausepoint", False): [3., 3., 1.], (5, "pausepoint", True): [3.],
                                    (5, "play", False): [5.]}})]
        return serialize, browser, gpu

    def test_the_complete_frame_is_serialize_page_and_the_gpu_of_what_was_sent(self):
        serialize, browser, gpu = self.reports()
        complete = flip_gates.complete_frames(serialize, browser, gpu, "nets")
        still = complete["7"]["phase_a"]["pausepoint"]
        self.assertEqual((still["frames"], still["complete_ms"]), (1, 1. + .5 + 2.))
        self.assertEqual(still["gpu_min_ms"], 2.)
        self.assertEqual(complete["7"]["phase_a_nets"]["pausepoint"]["complete_ms"], 2. + .5 + 3.)
        # Format 8 sends the still nothing: its serialize alone.
        self.assertEqual(complete["8"]["phase_a"]["pausepoint"]["complete_ms"], 1.)
        self.assertEqual(complete["8"]["phase_a"]["ticked"]["complete_ms"], 3. + .2 + 3.)
        play = complete["8"]["phase_a_nets"]["play"]
        self.assertEqual((play["frames"], play["checkpoints"]), (2, 1))
        self.assertEqual([frame["complete_ms"] for frame in play["per_frame"]], [4. + .8 + 5., 6. + .8 + 5.])
        self.assertEqual(play["complete_ms"], 5. + .8 + 5.)
        self.assertNotIn("camera", complete["7"]["phase_a"])

        judged = flip_gates.verdict(complete, "nets", 1.05)
        self.assertAlmostEqual(judged["7"]["pausepoint"]["ratio"], 5.5 / 3.5)
        self.assertFalse(judged["7"]["pausepoint"]["within_limit"])
        self.assertAlmostEqual(judged["8"]["pausepoint"]["ratio"], 2.)
        self.assertTrue(judged["8"]["ticked"]["within_limit"])
        self.assertTrue(judged["8"]["play"]["within_limit"])
        table = flip_gates.markdown_table({"flip": "nets", "limit": 1.05, "complete": complete, "verdict": judged,
                                           "pixels": None})
        self.assertEqual(len(table.splitlines()), 2 + 6)
        self.assertIn("**no**", table)

    def test_the_flag_off_check_reads_the_wall_clock_of_the_runs_without_stamps(self):
        # The nets' play frame reads 5 ms of GPU stamped and 4 by the flag-off
        # wall clock: the check charges the frame what the flag-off run took.
        serialize, browser, _ = self.reports()
        flag_off = [gpu_report({"gpu_border": {(2, "pausepoint", False): [2.], (5, "pausepoint", True): [3.],
                                               (5, "play", False): [5.]},
                                "nets": {(2, "pausepoint", False): [3.], (5, "pausepoint", True): [3.],
                                         (5, "play", False): [4.]}}, column=flip_gates.FLAG_OFF_GPU)]
        checked = flip_gates.complete_frames(serialize, browser, flag_off, "nets", flip_gates.FLAG_OFF_GPU)
        self.assertEqual([frame["complete_ms"] for frame in checked["8"]["phase_a_nets"]["play"]["per_frame"]],
                         [4. + .8 + 4., 6. + .8 + 4.])
        self.assertEqual(flip_gates.complete_frames(serialize, browser, flag_off, "nets"), {"7": {
            "phase_a": {}, "phase_a_nets": {}}, "8": {"phase_a": {}, "phase_a_nets": {}}}, "no stamps, no frames")
        judged = flip_gates.verdict(checked, "nets", 1.05)
        self.assertAlmostEqual(judged["8"]["play"]["ratio"], (5. + .8 + 4.) / (5. + .8 + 5.))
        summary = {"flip": "nets", "limit": 1.05, "complete": checked, "verdict": judged, "pixels": None,
                   "flag_off_check": judged}
        self.assertIn("ratio, GPU part flag off", flip_gates.markdown_table(summary))

    def test_a_browser_report_without_the_format_8_stream_is_refused(self):
        serialize, browser, gpu = self.reports()
        del browser["variants"]["phase_a_nets_delta"]
        with self.assertRaisesRegex(ValueError, "--deltas"):
            flip_gates.complete_frames(serialize, browser, gpu, "nets")

    def test_the_pixel_verdict_is_the_worst_frame_each_frame_counted_once(self):
        def frame(checkpoint, still, play, target, inside):
            return {"checkpoint": checkpoint, "pixels": {"nets_vs_gpu_border": pair(still)},
                    "play": {"checkpoint": target, "pixel_frames": inside,
                             "pixels": {"nets_vs_gpu_border": {**pair(play), "play_frame": inside[-1]}}}}

        def pair(fraction):
            return {"fraction_pixels_rgb_over24": fraction, "max_rgba": 30.}

        # Two pausepoints after one play (a pause between them) share its
        # frames; a second run over the same frames adds none.
        report = {"frames": [frame(2, .001, .004, 1, [3, 4, 5]), frame(3, .002, .004, 1, [3, 4, 5]),
                             frame(6, .0, .0, 5, [0, 1])]}
        pixels = flip_gates.pixels_of([report, report], "nets")
        self.assertEqual((pixels["frames"], pixels["pausepoints"], pixels["play_frames"]), (3 + 5, 3, 5))
        self.assertEqual((pixels["worst"]["checkpoint"], pixels["worst"]["phase"], pixels["worst"]["play_frame"]),
                         (2, "play", 5))
        self.assertTrue(pixels["passes"])
        pixels = flip_gates.pixels_of([{"frames": [frame(2, .001, .006, 1, [0])]}], "nets")
        self.assertFalse(pixels["passes"])

    def test_the_command_refuses_pixels_of_a_plays_last_sampled_frame(self):
        serialize, browser, gpu = self.reports()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            old = {"frames": [{"checkpoint": 5, "play": {"checkpoint": 4, "pixels": {}}}]}
            for name, report in (("serialize", serialize), ("browser", browser),
                                 ("gpu", {**gpu[0], "gpu_timestamps": True}), ("pixels", old)):
                (root / name).mkdir()
                report = {**report, "scene": {"measured_checkpoints": [2, 5]}, "git": {}}
                (root / name / "report.json").write_text(json.dumps(report))
            with self.assertRaisesRegex(SystemExit, "landing"):
                flip_gates.main(["complete", "--flip", "nets", "--serialize", str(root / "serialize"),
                                 "--browser", str(root / "browser"), "--gpu", str(root / "gpu"),
                                 "--pixels", str(root / "pixels"), "--limit", "1.05", "--output", str(root / "out")])

    def test_the_command_refuses_reports_of_other_frames(self):
        serialize, browser, gpu = self.reports()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name, report, frames in (("serialize", serialize, [2, 5]), ("browser", browser, [2, 5]),
                                         ("gpu", {**gpu[0], "gpu_timestamps": True}, [2, 6])):
                (root / name).mkdir()
                report = {**report, "scene": {"measured_checkpoints": frames}, "git": {}}
                (root / name / "report.json").write_text(json.dumps(report))
            with self.assertRaisesRegex(SystemExit, "other frames"):
                flip_gates.main(["complete", "--flip", "nets", "--serialize", str(root / "serialize"),
                                 "--browser", str(root / "browser"), "--gpu", str(root / "gpu"), "--limit", "1.05",
                                 "--output", str(root / "out")])


PLAYS = textwrap.dedent('''\
    from maniml import *

    class Plays(Scene):
        def construct(self):
            ring = Circle(radius=1, stroke_width=6)
            square = Square(fill_opacity=1).shift(2 * RIGHT)
            self.add(square)
            self.play(ShowCreation(ring), square.animate.shift(UP), run_time=0.3)
            self.play(square.animate.shift(DOWN), run_time=0.2)
    ''')


class Programs(unittest.TestCase):
    """The programs flip's reduction of play_frames reports."""

    def test_the_balanced_ratio_cancels_what_opening_a_play_costs(self):
        # The candidate saves 5%; opening a play costs 3% more than following,
        # so the plays the reference opened read 0.95 / 1.03 and those the
        # candidate opened 0.95 * 1.03. The geometric mean is the 5% alone,
        # every resample alike.
        rows = [(True, 103., 95.)] * 4 + [(False, 100., 97.85)] * 6
        judged = flip_gates.balanced(rows)
        self.assertAlmostEqual(judged["ratio"], .95)
        self.assertAlmostEqual(judged["interval_95"][0], .95)
        self.assertAlmostEqual(judged["interval_95"][1], .95)
        self.assertEqual((judged["reference_opened"]["plays"], judged["candidate_opened"]["plays"]), (4, 6))
        self.assertAlmostEqual(judged["reference_opened"]["ratio"], 95. / 103.)
        self.assertEqual(judged, flip_gates.balanced(rows), "seeded")
        self.assertIsNone(flip_gates.balanced([(True, 1., 1.)]), "one mode opened every play")
        # Unequal plays resample to an interval around the ratio.
        rows = [(True, 10. + k, 9.5 + k) for k in range(8)] + [(False, 10. + k, 9.8 + k) for k in range(8)]
        low, high = flip_gates.balanced(rows)["interval_95"]
        self.assertLess(low, flip_gates.balanced(rows)["ratio"])
        self.assertGreater(high, flip_gates.balanced(rows)["ratio"])

    def test_a_plays_python_is_serialize_and_the_scene_the_entry_its_serialize(self):
        mode = {"per_frame": {"serialize_ms": [1., 2., 3.], "scene_ms": [None, .5, .25]}}
        self.assertEqual(flip_gates.play_python(mode), [1., 2.5, 3.25])

    @requires_lyon
    def test_every_play_is_measured_and_reduced_per_frame(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ):
            path = Path(tmp) / "plays.py"
            path.write_text(PLAYS)
            play_frames.main(["--scene", str(path), "Plays", "--every-play", "--replays", "1", "--format", "8",
                              "--output", str(Path(tmp) / "f8")])
            report = json.loads((Path(tmp) / "f8" / "report.json").read_text())
        self.assertEqual([play["play"] for play in report["plays"]], [1, 2])
        # The opener alternates play by play.
        self.assertEqual([play["opened_by"] for play in report["plays"]], ["off", "strokes"])

        def rendered(play, complete, pixels):
            return {"play": play["play"], "line": play["line"], "opened_by": play["opened_by"], "modes": {
                mode: {**play["modes"][mode], "per_frame": {"complete_ms": complete[mode]},
                       **({"pixels": pixels} if mode == "strokes" else {})} for mode in ("off", "strokes")}}

        first, second = report["plays"]
        render = {"modes": ["off", "strokes"], "scene": {"name": "Plays"}, "plays": [
            rendered(first, {"off": [10., 10.], "strokes": [12., 12.]},
                     {"frames": 18, "max_channel_diff": 3, "max_fraction_over_24": 0.}),
            rendered(second, {"off": [10.], "strokes": [11.]},
                     {"frames": 12, "max_channel_diff": 40, "max_fraction_over_24": .001})]}
        gate = flip_gates.programs_gate([report], [render])
        episode = gate["episodes"]["Plays format 8"]
        frames = [len(play["modes"]["off"]["per_frame"]["serialize_ms"]) for play in report["plays"]]
        self.assertEqual((episode["plays"], episode["frames"]), (2, sum(frames)))
        self.assertEqual(episode["plays_with_programs"], 1, "the ring's creation, not the square's move")
        # The square's move records nothing, though under strokes its begin
        # still decides and its frames still note revisions.
        self.assertEqual((episode["recorded"]["plays"], episode["same_path"]["plays"]), (1, 1))
        self.assertEqual(episode["recorded"]["frames"] + episode["same_path"]["frames"], sum(frames))
        self.assertEqual([play["recorded"] for play in episode["per_play"]], [True, False])
        # Each mode opened one play: the balanced ratio is the geometric mean
        # of the two plays' ratios; a group of one play is not balanced.
        totals = [play["totals"] for play in episode["per_play"]]
        self.assertAlmostEqual(episode["balanced"]["ratio"],
                               ((totals[0]["strokes"] / totals[0]["off"]) * (totals[1]["strokes"] / totals[1]["off"]))
                               ** .5)
        self.assertEqual(episode["lower"], episode["balanced"]["ratio"] < 1)
        self.assertIsNone(episode["recorded"]["balanced"])
        for mode in ("off", "strokes"):
            total = sum(sum(flip_gates.play_python(play["modes"][mode])) for play in report["plays"])
            self.assertAlmostEqual(episode["per_frame_ms"][mode], total / sum(frames))
            self.assertAlmostEqual(episode["entries_ms"][mode], sum(
                play["modes"][mode]["per_frame"]["serialize_ms"][0] for play in report["plays"]))
        self.assertAlmostEqual(episode["ratio"], episode["per_frame_ms"]["strokes"] / episode["per_frame_ms"]["off"])
        native = gate["native_complete"]["Plays"]
        self.assertAlmostEqual(native["every_play"]["balanced"]["ratio"], (1.2 * 1.1) ** .5)
        self.assertEqual(native["recorded"]["per_frame_ms"], {"off": 10., "strokes": 12.})
        self.assertAlmostEqual(native["same_path"]["ratio"], 1.1)
        self.assertEqual((gate["pixels"]["frames"], gate["pixels"]["worst"]["play"]), (30, 2))
        self.assertTrue(gate["pixels"]["passes"])
        table = flip_gates.programs_table(gate)
        self.assertIn("Plays format 8", table)
        self.assertIn("(unbalanced)", table)

    def test_the_command_refuses_a_run_one_mode_opened_throughout(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "run").mkdir()
            (root / "run" / "report.json").write_text(json.dumps({"modes": ["off", "strokes"], "plays": [{"play": 1}]}))
            with self.assertRaisesRegex(SystemExit, "opened every play"):
                flip_gates.main(["programs", "--plays", str(root / "run"), "--output", str(root / "out")])


if __name__ == "__main__":
    unittest.main()

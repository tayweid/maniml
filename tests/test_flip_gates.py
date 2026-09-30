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

    def test_the_command_records_what_the_serialize_run_measured_and_the_inputs_sources(self):
        # What the gate command reads of a run: the serialize run's switches
        # and classes, and the sources its inputs hashed (one of them
        # hashed a.py otherwise).
        serialize, browser, gpu = self.reports()
        serialize = {**serialize, "tick_updaters": True, "play_frames": True, "camera_moves": False,
                     "source_files_sha256": {"a.py": "1", "b.py": "2"}}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name, report in (("serialize", serialize), ("browser", {**browser, "source_files_sha256": {"a.py": "1"}}),
                                 ("gpu", {**gpu[0], "gpu_timestamps": True, "source_files_sha256": {"a.py": "9"}})):
                (root / name).mkdir()
                report = {**report, "scene": {"measured_checkpoints": [2, 5]}, "git": {"commit": "c0ffee"}}
                (root / name / "report.json").write_text(json.dumps(report))
            with patch("sys.stdout"):
                flip_gates.main(["complete", "--flip", "nets", "--serialize", str(root / "serialize"),
                                 "--browser", str(root / "browser"), "--gpu", str(root / "gpu"), "--limit", "1.05",
                                 "--output", str(root / "out")])
            summary = json.loads((root / "out" / "summary.json").read_text())
        self.assertEqual(summary["measured"], {"tick_updaters": True, "play_frames": True, "camera_moves": False,
                                               "classes": ["pausepoint", "ticked", "play"]})
        self.assertEqual((summary["source_files_sha256"], summary["source_files_disagree"]),
                         ({"a.py": "1", "b.py": "2"}, ["a.py"]))
        self.assertEqual(flip_gates.run_commits(summary), {"c0ffee"})

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


class TimedSet(unittest.TestCase):
    """The gate command (B5.7): a flip passes only over every scene of its
    timed set, the ones mostly surfaces included, each judged at the
    flip's limit on every class its serialize run measured, every run of
    one tree."""

    GIT = {"commit": "c0ffee", "branch": "b", "dirty": True}
    GOOD_REFERENCE = {"within_tolerance": True, "error_px": .03, "net_defined": 0}
    FIXTURES = {"measure": "accuracy", "passes": True, "failing": [], "unsound": {}, "git": GIT,
                "source_files_sha256": {"tests/surface_fixtures.py": "f"},
                "fixtures": {"orbs": {"grids": {"pixels_rgb_over24": 2834}, "nets": {"pixels_rgb_over24": 1006},
                                      "reference": GOOD_REFERENCE}}}

    @classmethod
    def accuracy(cls, file, name, nets=.0067, grids=.0138, *, commit="c0ffee", sources=None, **fields):
        """An accuracy run's summary: each stack's share of pixels over
        24/255 from the true surface, over 12 pausepoints chosen as the
        serialize command chooses them and 36 frames inside plays, every
        reference within its tolerance and of its surfaces' functions;
        ``fields`` override any of it."""
        judged = {"frames": 48, "grids": round(grids * 2073600), "nets": round(nets * 2073600)}
        return {"flip": "nets", "scene": {"path": f"/somewhere/{file}", "name": name,
                                          "measured_checkpoints": list(range(1, 13))},
                "git": {**cls.GIT, "commit": commit}, "every": 1, "max_frames": 12,
                "source_files_sha256": {"tests/surface_fixtures.py": "f", f"/somewhere/{file}": f"h-{file}",
                                        **(sources or {})},
                "frames": 48, "pausepoints": 12, "play_frames": 36, "tie_frames": 0, "judged": judged,
                "grids": {"fraction_pixels_rgb_over24": grids, "pixels_rgb_over24": round(grids * 2073600)},
                "nets": {"fraction_pixels_rgb_over24": nets, "pixels_rgb_over24": round(nets * 2073600)},
                "reference_within_tolerance": True, "reference_error_px": .031, "net_defined_surfaces": 0,
                "passes": judged["nets"] <= judged["grids"], **fields}

    def accurate(self):
        return [self.accuracy(file, name) for file, name in flip_gates.TIMED_SCENES["nets"]]

    @staticmethod
    def summary(file, name, ratio=1.0, pixels=.001, *, limit=1.05, classes=("pausepoint", "camera", "play"),
                measured=None, switches=None, commit="c0ffee", sources=None, disagree=()):
        judged = {"phase_a_ms": 1.0, "flip_ms": ratio, "ratio": ratio, "ratio_gpu_min": ratio,
                  "within_limit": ratio <= limit}
        git = {"commit": commit, "branch": "b", "dirty": True}
        return {"flip": "nets", "limit": limit, "scene": {"path": f"/somewhere/{file}", "name": name},
                "input_commits": {"serialize": git, "browser": git, "gpu": [git, git], "pixels": [git]},
                "measured": {**{switch: True for switch in flip_gates.GATE_SWITCHES}, **(switches or {}),
                             "classes": list(classes if measured is None else measured)},
                "source_files_sha256": {"maniml/web/geometry.py": "g", f"/somewhere/{file}": f"h-{file}",
                                        **(sources or {})},
                "source_files_disagree": list(disagree),
                "verdict": {fmt: {cls: dict(judged) for cls in classes} for fmt in ("7", "8")},
                "flag_off_check": None,
                "pixels": {"passes": pixels <= flip_gates.PIXEL_LIMIT,
                           "worst": {"fraction_pixels_rgb_over24": pixels}}}

    def every(self):
        return [self.summary(file, name) for file, name in flip_gates.TIMED_SCENES["nets"]]

    def test_the_nets_set_holds_the_scenes_mostly_surfaces(self):
        scenes = flip_gates.TIMED_SCENES["nets"]
        self.assertIn(("surface_scenes.py", "OrbsScene"), scenes)
        self.assertIn(("surface_scenes.py", "LatticeScene"), scenes)
        self.assertEqual(len(scenes), 5)
        from benchmarks import surface_scenes
        self.assertTrue(all(hasattr(surface_scenes, name) for file, name in scenes if file == "surface_scenes.py"))
        self.assertEqual(flip_gates.GATE_LIMITS["nets"], 1.05, "the plan's table: ≤ 1.05× grids")

    def test_a_scene_missing_from_the_set_fails_the_gate(self):
        fixtures, every = self.FIXTURES, self.every()
        self.assertTrue(flip_gates.gate_verdict(every, fixtures, "nets", self.accurate())["passes"])
        without = flip_gates.gate_verdict(every[:3], fixtures, "nets", self.accurate())
        self.assertFalse(without["passes"])
        self.assertEqual(without["missing"], ["OrbsScene (surface_scenes.py)", "LatticeScene (surface_scenes.py)"])
        over = flip_gates.gate_verdict(every[:4] + [self.summary("surface_scenes.py", "LatticeScene", 1.2)],
                                       fixtures, "nets", self.accurate())
        self.assertFalse(over["passes"])
        self.assertEqual(len(over["failures"]), 6, "three classes in two formats")
        self.assertEqual((over["timing_passes"], over["pixels_pass"]), (False, True))
        self.assertIn("; pixels pass", flip_gates.gate_table(over))
        # B5.7's lattice, 0.98% of its pixels off the grids': since B5.9 a
        # diagnostic, the pixels judged against the true surface.
        pixels = flip_gates.gate_verdict(every[:4] + [self.summary("surface_scenes.py", "LatticeScene", 1.0, .0098)],
                                         fixtures, "nets", self.accurate())
        self.assertTrue(pixels["passes"], pixels["failures"])
        self.assertFalse(pixels["scenes"]["LatticeScene (surface_scenes.py)"]["pixels_pass"])
        self.assertFalse(flip_gates.gate_verdict(every, None, "nets", self.accurate())["passes"], "the fixtures are part of it")
        with self.assertRaises(SystemExit):
            flip_gates.gate_verdict(every + every[:1], fixtures, "nets", self.accurate())
        self.assertIn("Missing from the timed set", flip_gates.gate_table(without))

    def test_a_run_judged_at_another_limit_fails_the_gate(self):
        # 1.24 passes a run judged at 1.5 by its own flags; the gate judges
        # it at the flip's limit and fails the run for the limit besides.
        loose = flip_gates.gate_verdict(
            self.every()[:4] + [self.summary("surface_scenes.py", "LatticeScene", 1.24, limit=1.5)],
            self.FIXTURES, "nets", self.accurate())
        self.assertFalse(loose["passes"])
        self.assertEqual(loose["failures"][0], "LatticeScene: judged at --limit 1.5, the gate's is 1.05")
        self.assertEqual(len(loose["failures"]), 1 + 6)
        self.assertIn("**1.240**", flip_gates.gate_table(loose))
        # A stricter limit is another limit too: the verdict is the gate's.
        strict = flip_gates.gate_verdict(
            self.every()[:4] + [self.summary("surface_scenes.py", "LatticeScene", 1.0, limit=1.0)],
            self.FIXTURES, "nets", self.accurate())
        self.assertEqual(strict["failures"], ["LatticeScene: judged at --limit 1.0, the gate's is 1.05"])

    def test_every_class_the_run_measured_is_judged_in_both_formats(self):
        def gate(last):
            return flip_gates.gate_verdict(self.every()[:4] + [last], self.FIXTURES, "nets", self.accurate())

        lattice = ("surface_scenes.py", "LatticeScene")
        # The pausepoints alone, of a run that measured the camera and plays.
        still = gate(self.summary(*lattice, classes=("pausepoint",), measured=("pausepoint", "camera", "play")))
        self.assertFalse(still["passes"])
        self.assertEqual(still["failures"], [f"LatticeScene: format {fmt} {cls} not measured"
                                             for fmt in ("8", "7") for cls in ("camera", "play")])
        table = flip_gates.gate_table(still)
        self.assertEqual(table.count("**missing**"), 4, table)
        # An empty verdict: every class missing.
        empty = gate(self.summary(*lattice, classes=(), measured=("pausepoint", "camera", "play")))
        self.assertEqual(len(empty["failures"]), 6)
        # A ticked frame the serialize run measured is required as well.
        b3 = self.every()
        b3[1] = self.summary("B3_Animation.py", "EpisodeB3", measured=("pausepoint", "ticked", "camera", "play"))
        ticked = flip_gates.gate_verdict(b3, self.FIXTURES, "nets", self.accurate())
        self.assertEqual(ticked["failures"], ["EpisodeB3: format 8 ticked not measured",
                                              "EpisodeB3: format 7 ticked not measured"])
        # A serialize run without camera moves measured none, and the gate
        # still requires them.
        uncamera = gate(self.summary(*lattice, classes=("pausepoint", "play"), switches={"camera_moves": False}))
        self.assertEqual(uncamera["failures"], ["LatticeScene: serialize ran without --camera-moves",
                                                "LatticeScene: format 8 camera not measured",
                                                "LatticeScene: format 7 camera not measured"])
        # A complete run from before the gate read what it measured.
        old = self.summary(*lattice)
        del old["measured"], old["source_files_sha256"]
        self.assertEqual(gate(old)["failures"], [
            "LatticeScene: the complete run records neither what it measured nor its sources: re-run complete"])

    def test_every_run_is_of_one_tree(self):
        every = self.every()
        other = flip_gates.gate_verdict(every[:4] + [self.summary("surface_scenes.py", "LatticeScene",
                                                                  commit="decade")], self.FIXTURES, "nets", self.accurate())
        self.assertEqual(other["failures"], ["the runs name more than one commit: c0ffee, decade"])
        edited = flip_gates.gate_verdict(every[:4] + [self.summary("surface_scenes.py", "LatticeScene",
                                                                   sources={"maniml/web/geometry.py": "g2"})],
                                         self.FIXTURES, "nets", self.accurate())
        self.assertEqual(edited["failures"], ["the scenes' runs hash maniml/web/geometry.py differently"])
        mixed = flip_gates.gate_verdict(every[:4] + [self.summary("surface_scenes.py", "LatticeScene",
                                                                  disagree=["maniml/web/webgpu.js"])],
                                        self.FIXTURES, "nets", self.accurate())
        self.assertEqual(mixed["failures"], ["LatticeScene: its inputs hash maniml/web/webgpu.js differently"])
        # The two surface scenes share their file, hashed alike (every()
        # passes); edited between their runs, it fails.
        scene_file = {"/somewhere/surface_scenes.py": "h-edited"}
        moved = flip_gates.gate_verdict(every[:4] + [self.summary("surface_scenes.py", "LatticeScene",
                                                                  sources=scene_file)], self.FIXTURES, "nets", self.accurate())
        self.assertEqual(moved["failures"], ["the scenes' runs hash /somewhere/surface_scenes.py differently"])

    def test_the_nets_pixels_are_judged_against_the_true_surface(self):
        """B5.9: the nets flip's pixel gate is each stack against the true
        surface, an accuracy run per scene of the set and the fixtures
        run, nets no further than grids; nets against grids is reported."""
        every, fixtures = self.every(), self.FIXTURES
        passed = flip_gates.gate_verdict(every, fixtures, "nets", self.accurate())
        self.assertTrue(passed["passes"], passed["failures"])
        self.assertEqual(set(passed["accuracy"]), {f"{name} ({file})" for file, name in flip_gates.TIMED_SCENES["nets"]})
        table = flip_gates.gate_table(passed)
        self.assertIn("from the true surface: grids; nets", table)
        self.assertIn("1.3800%; 0.6700%", table)
        # A scene without its accuracy run, one where nets are the further.
        missing = flip_gates.gate_verdict(every, fixtures, "nets", self.accurate()[:4])
        self.assertEqual(missing["failures"], ["LatticeScene: accuracy not measured"])
        self.assertEqual((missing["timing_passes"], missing["pixels_pass"]), (True, False))
        self.assertIn("**not measured**", flip_gates.gate_table(missing))
        self.assertIn("Verdict: **fails**: timing pass; pixels **fail** (LatticeScene: accuracy not measured)",
                      flip_gates.gate_table(missing))
        further = self.accurate()[:4] + [self.accuracy("surface_scenes.py", "LatticeScene", .013, .012)]
        worse = flip_gates.gate_verdict(every, fixtures, "nets", further)
        self.assertEqual(worse["failures"], ["LatticeScene: nets further from the true surface than grids "
                                             "(26957 pixels over 24/255 against 24883, over its 48 frames that "
                                             "are not ties)"])
        self.assertIn("**1.3000%**", flip_gates.gate_table(worse))
        # A tie passes: no further.
        tie = self.accurate()[:4] + [self.accuracy("surface_scenes.py", "LatticeScene", .012, .012)]
        self.assertTrue(flip_gates.gate_verdict(every, fixtures, "nets", tie)["passes"])
        with self.assertRaises(SystemExit):
            flip_gates.gate_verdict(every, fixtures, "nets", self.accurate() + self.accurate()[:1])

    def test_the_fixtures_are_judged_against_the_true_surface(self):
        every, accurate = self.every(), self.accurate()
        failing = {**self.FIXTURES, "passes": False, "failing": ["translucent"],
                   "fixtures": {"translucent": {"grids": {"pixels_rgb_over24": 307},
                                                "nets": {"pixels_rgb_over24": 794},
                                                "reference": self.GOOD_REFERENCE}}}
        self.assertEqual(flip_gates.gate_verdict(every, failing, "nets", accurate)["failures"],
                         ["Surface fixture translucent: nets further from the true surface than grids "
                          "(794 pixels against 307)"])
        # A fixture whose reference is no measure of the true surface fails,
        # read from the fixture's own reference whatever the run's verdict.
        for reference, problem in (({**self.GOOD_REFERENCE, "within_tolerance": False, "error_px": 7.5},
                                    "its reference 7.500 px from the surface, beyond its tolerance"),
                                   ({**self.GOOD_REFERENCE, "net_defined": 1},
                                    "1 surface(s) of its reference drawn from their own net, not their function")):
            unsound = {**self.FIXTURES, "fixtures": {"bent": {**self.FIXTURES["fixtures"]["orbs"],
                                                              "reference": reference}}}
            self.assertEqual(flip_gates.gate_verdict(every, unsound, "nets", accurate)["failures"],
                             [f"Surface fixture bent: {problem}"])
        # B5.7's fixtures run measured nets against grids.
        old = {"passes": True, "worst": "orbs", "git": self.GIT,
               "fixtures": {"orbs": {"fraction_pixels_rgb_over24": .003}}}
        self.assertEqual(flip_gates.gate_verdict(every, old, "nets", accurate)["failures"],
                         ["Surface fixtures measured nets against grids, not against the true surface: "
                          "re-run fixtures"])
        verdict = flip_gates.gate_verdict(every, None, "nets", accurate)
        self.assertEqual(verdict["failures"], ["Surface fixtures not measured"])
        self.assertIn("Surface fixtures, nets no further from the true surface than grids: **no**",
                      flip_gates.gate_table(verdict))

    def test_an_accuracy_run_measures_the_true_surface_over_the_gates_frames(self):
        """A scene's accuracy run passes the gate only where its references
        measured the true surface (every one within its tolerance, every
        surface its function's: a surface drawn from its own net is what
        nets converge to) and it measured the serialize command's frames
        and frames inside the plays into them."""
        every, fixtures, lattice = self.every(), self.FIXTURES, ("surface_scenes.py", "LatticeScene")
        cases = (
            ({"reference_within_tolerance": False, "reference_error_px": 7.5},
             "LatticeScene: its reference 7.500 px from the surface, beyond its tolerance"),
            ({"net_defined_surfaces": 3},
             "LatticeScene: 3 surface(s) of its reference drawn from their own net, not their function"),
            ({"play_frames": 0, "frames": 12}, "LatticeScene: no frame inside a play measured (--play-frames)"),
            ({"max_frames": 1}, "LatticeScene: its frames chosen with --every 1 --max-frames 1, not as the "
                                "serialize command chooses them (1, 12)"),
            ({"pausepoints": 11}, "LatticeScene: 11 of its 12 chosen frames measured"),
            ({"source_files_unchanged_during_run": False}, "LatticeScene: a source file changed during its "
                                                           "accuracy run"),
        )
        for fields, failure in cases:
            with self.subTest(fields=fields):
                runs = self.accurate()[:4] + [self.accuracy(*lattice, **fields)]
                verdict = flip_gates.gate_verdict(every, fixtures, "nets", runs)
                self.assertEqual(verdict["failures"], [failure])
                self.assertEqual((verdict["timing_passes"], verdict["pixels_pass"]), (True, False))

    def test_the_accuracy_runs_are_of_one_tree(self):
        """The accuracy runs and the fixtures run, of one tree among
        themselves (the timing's runs are held to theirs)."""
        every = self.every()
        other = self.accurate()[:4] + [self.accuracy("surface_scenes.py", "LatticeScene", commit="decade")]
        self.assertEqual(flip_gates.gate_verdict(every, self.FIXTURES, "nets", other)["failures"],
                         ["the accuracy runs name more than one commit: c0ffee, decade"])
        edited = self.accurate()[:4] + [self.accuracy("surface_scenes.py", "LatticeScene",
                                                      sources={"tests/surface_fixtures.py": "f2"})]
        self.assertEqual(flip_gates.gate_verdict(every, self.FIXTURES, "nets", edited)["failures"],
                         ["the accuracy runs hash tests/surface_fixtures.py differently"])
        # The complete runs may be of another tree than the accuracy runs.
        timed = [self.summary(file, name, commit="efcb262c") for file, name in flip_gates.TIMED_SCENES["nets"]]
        self.assertTrue(flip_gates.gate_verdict(timed, self.FIXTURES, "nets", self.accurate())["passes"])


class Accuracy(unittest.TestCase):
    """The accuracy and fixtures commands' reductions (B5.9), on stand-in
    frames."""

    @staticmethod
    def frame(grids, nets, *, phase="pausepoint", checkpoint=1, within=True, apart=None, net_defined=0, **where):
        """A frame's accuracy: ``apart``, the pixels over 24/255 between
        grids and nets (by default the difference of their counts; 0 is a
        tie)."""
        pair = lambda count: {"pixels_rgb_over24": count, "fraction_pixels_rgb_over24": count / 100}
        apart = abs(grids - nets) if apart is None else apart
        return {"checkpoint": checkpoint, "phase": phase, **where, "resolution": [10, 10],
                "grids": pair(grids), "nets": pair(nets), "nets_vs_grids": pair(apart),
                "reference_orders": pair(0),
                "where_they_differ": {"pixels": 3, "nets_nearer": 2, "grids_nearer": 1, "equal": 0},
                "reference": {"within_tolerance": within, "error_px": .03, "net_defined": net_defined},
                "tie": apart == 0, "passes": apart == 0 or nets <= grids}

    def test_a_scene_passes_on_its_frames_summed(self):
        frames = [self.frame(10, 4), self.frame(3, 5, phase="play", play_checkpoint=1, play_frame=5),
                  self.frame(0, 0, checkpoint=2)]
        summary = flip_gates.accuracy_summary(frames)
        self.assertEqual((summary["frames"], summary["pausepoints"], summary["play_frames"]), (3, 2, 1))
        self.assertEqual((summary["grids"]["pixels_rgb_over24"], summary["nets"]["pixels_rgb_over24"]), (13, 9))
        self.assertAlmostEqual(summary["nets"]["fraction_pixels_rgb_over24"], 9 / 300)
        self.assertTrue(summary["passes"])
        self.assertEqual(summary["frames_nets_further"],
                         [{"checkpoint": 1, "phase": "play", "play_checkpoint": 1, "play_frame": 5, "nets": 5,
                           "grids": 3}])
        self.assertEqual(summary["where_they_differ"], {"pixels": 9, "nets_nearer": 6, "grids_nearer": 3, "equal": 0})
        self.assertTrue(summary["reference_within_tolerance"])
        self.assertEqual((summary["tie_frames"], summary["judged"]), (1, {"frames": 2, "grids": 13, "nets": 9}))
        self.assertFalse(flip_gates.accuracy_summary(frames + [self.frame(1, 6)])["passes"])
        self.assertFalse(flip_gates.accuracy_summary([self.frame(1, 1, within=False)])["reference_within_tolerance"])
        self.assertIn("nets no further: yes", flip_gates.accuracy_table(summary))

    def test_a_frame_where_grids_and_nets_agree_is_a_tie(self):
        """Grids and nets nowhere more than 24/255 apart are one picture by
        the gate's threshold: their counts against their references differ
        by noise at its edge (the orbit demo: 596 against 589), which the
        gate does not judge."""
        noise = self.frame(596, 589, apart=0, phase="play", play_checkpoint=1, play_frame=17)
        self.assertTrue(noise["tie"])
        summary = flip_gates.accuracy_summary([self.frame(72, 70), noise])
        self.assertEqual((summary["tie_frames"], summary["judged"]), (1, {"frames": 1, "grids": 72, "nets": 70}))
        self.assertEqual((summary["grids"]["pixels_rgb_over24"], summary["nets"]["pixels_rgb_over24"]), (668, 659))
        self.assertTrue(summary["passes"])
        # A tie's nets further than its grids do not fail the scene either.
        summary = flip_gates.accuracy_summary([self.frame(72, 70), self.frame(589, 596, apart=0)])
        self.assertTrue(summary["passes"])
        self.assertEqual(summary["frames_nets_further"], [])
        self.assertIn("1 ties", flip_gates.accuracy_table(summary))
        self.assertIn("(a tie)", flip_gates.accuracy_line("frame", {**self.frame(3, 5, apart=0),
                                                                    "reference": {"error_px": .03, "triangles": 9}}))

    def test_a_plays_frames_are_spread_strictly_inside_it(self):
        self.assertEqual(flip_gates.play_picks(30, 30, 1.0, 3), [7, 14, 21])
        # The landing (alpha 1) is the pausepoint's own picture.
        self.assertEqual(flip_gates.play_picks(2, 30, 2 / 30, 3), [0])
        self.assertEqual(flip_gates.play_picks(30, 30, 1.0, 0), [])

    def test_the_fixtures_verdict_is_every_fixtures_accuracy(self):
        def result(grids, nets, apart):
            return {**self.frame(grids, nets), "nets_vs_grids": {"fraction_pixels_rgb_over24": apart}}

        report = flip_gates.fixture_report({"orbs": result(28, 10, .0028), "translucent": result(0, 0, .0008)})
        self.assertEqual((report["measure"], report["passes"], report["failing"]), ("accuracy", True, []))
        self.assertEqual(report["nets_vs_grids"]["worst"], "orbs")
        self.assertTrue(report["nets_vs_grids"]["within"])
        report = flip_gates.fixture_report({"orbs": result(28, 10, .0028), "translucent": result(3, 8, .0098)})
        self.assertEqual((report["passes"], report["failing"]), (False, ["translucent"]))
        self.assertFalse(report["nets_vs_grids"]["within"], "reported, not judged")
        # A reference that is no measure of the true surface fails the run,
        # however the stacks compare against it.
        bent = {**self.frame(28, 10, net_defined=1), "nets_vs_grids": {"fraction_pixels_rgb_over24": .0028}}
        report = flip_gates.fixture_report({"orbs": result(28, 10, .0028), "bent": bent})
        self.assertEqual((report["passes"], report["failing"]), (False, []))
        self.assertEqual(report["unsound"], {"bent": ["1 surface(s) of its reference drawn from their own net, "
                                                      "not their function"]})
        wide = {**self.frame(28, 10, within=False), "nets_vs_grids": {"fraction_pixels_rgb_over24": .0028}}
        self.assertFalse(flip_gates.fixture_report({"wide": wide})["passes"])


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

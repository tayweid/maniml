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

import numpy as np

from benchmarks import browser_frames, episode_frames, flip_gates, gpu_borders, play_frames
from maniml.web.triangle_geometry import _packaged_library
from tests import surface_fixtures

requires_lyon = unittest.skipUnless(os.environ.get("MANIML_LYON_LIBRARY") or _packaged_library(),
                                    "Lyon helper is neither packaged nor explicitly built")


class Stacks(unittest.TestCase):
    def test_a_flip_is_the_variant_the_other_harnesses_measure(self):
        pairs = {name: (image, reference) for name, image, reference in episode_frames.PIXEL_PAIRS}
        for flip, (browser, frames) in flip_gates.FLIPS.items():
            with self.subTest(flip=flip):
                self.assertIn(browser, browser_frames.ENVIRONMENTS)
                self.assertIn(frames, episode_frames.VARIANTS)
                self.assertEqual(pairs[flip_gates.PIXEL_PAIRS[flip]][0], frames)
                for pair in flip_gates.REPORTED_PAIRS.get(flip, ()):
                    self.assertEqual(pairs[pair], (frames, "gpu_border"))
                (a, a_renderer, _), (b, b_renderer, environment) = flip_gates.stacks(flip)
                self.assertEqual((a, a_renderer), ("phase_a", "phase_a"))
                if flip == "phase_b":
                    # The viewer's forced Phase B, its patch source taken
                    # out as the selection's is, its plays recording GPU
                    # programs; judged against Phase A with nets beside it.
                    self.assertEqual((b, b_renderer), ("phase_b_forced", "phase_b"))
                    self.assertIsNone(environment["MANIML_PATCH_SOURCE"])
                    self.assertEqual(gpu_borders.ROUTES[episode_frames.SAMPLED_AS[frames]], "phase_b")
                    self.assertEqual(pairs[flip_gates.PIXEL_PAIRS[flip]], (frames, "nets"))
                    continue
                self.assertEqual((b, b_renderer), (browser, "triangles"))
                self.assertEqual(pairs[flip_gates.PIXEL_PAIRS[flip]], (frames, "gpu_border"))
                # The stack episode_frames draws the flip's pixels and GPU with.
                for key, value in gpu_borders.SWITCHES[frames].items():
                    self.assertEqual(environment[key], value, key)
        self.assertEqual(flip_gates.PHASE_A, ("phase_a", "gpu_border"))
        self.assertEqual(gpu_borders.ROUTES["gpu_border"], "phase_a")

    def test_phase_b_as_the_default_measures_the_default_it_replaces_beside_it(self):
        names = [name for name, _, _ in flip_gates.stacks("phase_b", diagnostics=True)]
        self.assertEqual(names, ["phase_a", "phase_b_forced", "phase_a_nets"])
        _, renderer, environment = flip_gates.stacks("phase_b", diagnostics=True)[2]
        self.assertEqual(renderer, "triangles")
        # Phase A with nets: the default stack B5.9 left, whatever the
        # defaults say now.
        for key, value in gpu_borders.SWITCHES["nets"].items():
            self.assertEqual(environment[key], value, key)
        self.assertEqual(flip_gates.stacks("nets", diagnostics=True), flip_gates.stacks("nets"))
        self.assertEqual(flip_gates.PLAY_ENVIRONMENTS["phase_b_forced"], {"MANIML_PROGRAMS": "gpu"})
        self.assertEqual((flip_gates.GATE_LIMITS["phase_b"], flip_gates.GATE_MAJORITY["phase_b"],
                          flip_gates.GATE_FORMATS["phase_b"]), (1.25, 1.0, ("8",)))
        scenes = flip_gates.TIMED_SCENES["phase_b"]
        self.assertEqual([name for _, name in scenes],
                         ["EpisodeB2", "PriceDiscovery", "EpisodeB3", "OrbsScene", "LatticeScene"])
        self.assertIn("navigations", flip_gates.FLIP_SWITCHES["phase_b"])

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


    def test_a_navigation_and_the_recorded_streams(self):
        """B5.10: a step from the frame measured before, each serializer
        restoring for itself, its first round a warmup; every message each
        serializer made recorded in order as its stream, the Phase B plays
        recording programs and the diagnostic stack beside them."""
        scene = self.scene
        indices = episode_frames.select_frames(scene.animation_checkpoints)
        record = {(name, fmt): [] for name, _, _ in flip_gates.stacks("phase_b", diagnostics=True)
                  for fmt in flip_gates.FORMATS}
        frames = flip_gates.measure_serialize(scene, indices, "phase_b", samples=2, warmups=1, replays=1,
                                              tick_updaters=True, play_frames=True, camera_moves=True,
                                              navigations=3, record=record, diagnostics=True)
        keys = [flip_gates.key_name(*key) for key in record]
        self.assertEqual(len(keys), 6)
        still, ticked = frames
        self.assertNotIn("navigation", still, "the first frame has no frame before it")
        navigation = ticked["navigation"]
        self.assertEqual(sorted(navigation), sorted(keys))
        for key in keys:
            self.assertEqual((navigation[key]["n"], len(navigation[key]["per_round_ms"])), (2, 3))
            self.assertEqual(navigation[key]["first_ms"], navigation[key]["per_round_ms"][0])
            self.assertEqual(navigation[key]["previous"], still["checkpoint"])
        self.assertEqual(navigation["phase_a_f8"]["sent"], 2, "a step between frames sends a delta")
        self.assertIn(((ticked["checkpoint"], "navigation")), flip_gates.serialize_by_frame(frames, "phase_a_f8"))
        for (name, fmt), messages in record.items():
            entries = [fields for _, fields in messages]
            classes = [entry["cls"] for entry in entries]
            self.assertEqual(classes[0], "seek")
            self.assertEqual(classes.count("navigation"), 3)
            self.assertEqual(classes.count("navigation_base"), 3)
            self.assertEqual([entry["warmup"] for entry in entries if entry["cls"] == "navigation"],
                             [True, False, False])
            self.assertEqual(classes.count("camera"), 3 * 3 * 2, "three moves a round, two frames")
            if fmt == 7:
                self.assertTrue(all(message is not None for message, _ in messages))
            else:
                self.assertTrue(any(message is None for message, fields in messages if fields["cls"] == "pausepoint"))
        # The Phase B plays record GPU programs (format 8: a program run's
        # scalars op), Phase A's none.
        from maniml.web.geometry import parse_geometry_message

        def programs(name):
            found = 0
            for message, fields in record[(name, 8)]:
                if message is not None and fields["cls"] == "play":
                    header, _ = parse_geometry_message(message)
                    found += len(header.get("scalars", ())) + sum(bool(batch.get("program"))
                                                                  for splice in header.get("splices", ())
                                                                  for batch in splice[2])
            return found

        self.assertGreater(programs("phase_b_forced"), 0)
        self.assertEqual((programs("phase_a"), programs("phase_a_nets")), (0, 0))
        with tempfile.TemporaryDirectory() as tmp:
            streams = flip_gates.write_streams(Path(tmp), scene, record)
            self.assertEqual(sorted(streams), sorted(keys))
            meta = json.loads((Path(tmp) / "phase_b_forced_f8" / "scene.json").read_text())
            self.assertEqual(meta["format_version"], 8)
            self.assertEqual([entry["index"] for entry in meta["frames"]], list(range(len(record[("phase_b_forced", 8)]))))
            self.assertEqual(sum(entry["len"] for entry in meta["frames"]), streams["phase_b_forced_f8"]["bytes"])


    def test_a_first_visit_is_measured_by_a_serializer_alone(self):
        """B5.10: a step from each measured frame to the next, restored for
        the first time, for one serializer; the seek and the steps' bases
        are warmups."""
        scene = self.scene
        indices = episode_frames.select_frames(scene.animation_checkpoints)
        name, renderer, environment = flip_gates.stacks("phase_b")[1]
        record = {(name, 8): []}
        frames = flip_gates.measure_first_visits(scene, indices, {(name, 8): (renderer, environment, {})},
                                                 record=record)
        self.assertEqual(len(frames), len(indices) - 1)
        frame = frames[0]
        self.assertEqual((frame["checkpoint"], frame["previous"]), (indices[1], indices[0]))
        self.assertEqual(list(frame["first_visit"]), ["phase_b_forced_f8"])
        self.assertTrue(frame["first_visit"]["phase_b_forced_f8"]["sent"], "a step between frames sends a delta")
        self.assertEqual([(fields["cls"], fields["warmup"]) for _, fields in record[(name, 8)]],
                         [("seek", True), ("first_visit_base", True), ("first_visit", False)])

    def test_the_first_visits_run_a_process_a_serializer_and_merge(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "first"
            flip_gates.main(["serialize", "--flip", "phase_b", "--scene", str(Path(self.tmpdir.name) / "flips.py"),
                             "Flips", "--first-visits", "--record", "--output", str(out)])
            report = json.loads((out / "report.json").read_text())
            keys = ["phase_a_f7", "phase_a_f8", "phase_b_forced_f7", "phase_b_forced_f8"]
            self.assertTrue(report["first_visits"])
            self.assertEqual(sorted(report["processes"]), keys)
            self.assertEqual(sorted(report["streams"]), keys)
            self.assertEqual(sorted(report["frames"][0]["first_visit"]), keys)
            self.assertTrue(report["source_files_unchanged_during_run"])
            streams = flip_gates.recorded_streams(out, report)
            self.assertEqual([entry["cls"] for entry in streams["phase_a_f7"]],
                             ["seek", "first_visit_base", "first_visit"])
            measured = flip_gates.measured_of({"flip": "phase_b", "frames": []}, report)
            self.assertEqual((measured["first_visits"], measured["classes"]), (True, ["first_visit"]))


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


class Device(unittest.TestCase):
    """B5.10's complete frame from a recorded stream played on the device:
    each message's serialize, its page and GPU on the device over every
    run (the page a median over the plain rounds, the GPU a mean over the
    stamped ones), per unit and then per class, with an interval from
    resampling the units, the rounds and the runs; an unsent message costs
    its serialize alone."""

    @staticmethod
    def stream(serialize, gpu, page=.1, done=2., sent=True, runs=1, scale=(1.,)):
        """Entries and device rows (``runs`` of them a message, the GPU of
        run r scaled by ``scale[r]``): a still frame at 2 (two warmup
        rounds, two measured, the second unsent under ``sent`` False), a
        camera move, a play of two frames over two replays and a
        navigation of three rounds (the first a warmup), and a first visit
        to 3."""
        entries, played = [], {}

        def add(fields, ms, gpus, length=100):
            index = len(entries)
            entries.append({"index": index, "len": length, "serialize_ms": ms, **fields})
            if length:
                played[index] = [{"index": index, "page": [page, page * 3, page], "done": [done] * 3,
                                  "gpu": [value * scale[run % len(scale)] for value in gpus],
                                  "passes": [2] * len(gpus)} for run in range(runs)]

        add({"checkpoint": 2, "cls": "seek", "warmup": True}, 50., [9.])
        add({"checkpoint": 2, "cls": "pausepoint", "warmup": True}, 9., [9.])
        add({"checkpoint": 2, "cls": "pausepoint", "warmup": False}, serialize, gpu)
        add({"checkpoint": 2, "cls": "pausepoint", "warmup": False}, serialize, gpu, 100 if sent else 0)
        add({"checkpoint": 2, "cls": "camera", "warmup": False, "move": "pan"}, 2 * serialize, gpu)
        for replay in range(2):
            for k in (4, 5):
                add({"checkpoint": 2, "cls": "play", "warmup": False, "play_frame": k, "replay": replay},
                    serialize + k, gpu)
        for turn in range(3):
            add({"checkpoint": 3, "cls": "navigation_base", "warmup": True, "round": turn}, 7., [9.])
            add({"checkpoint": 3, "cls": "navigation", "warmup": turn == 0, "round": turn}, 4. if turn else 8., gpu)
        add({"checkpoint": 3, "cls": "first_visit_base", "warmup": True}, 7., [9.])
        add({"checkpoint": 3, "cls": "first_visit", "warmup": False}, 11., gpu)
        return entries, played

    def test_a_class_is_its_units_each_the_mean_of_its_messages_device_parts(self):
        entries, played = self.stream(1., [1., 1.262144, 1.])
        classes = flip_gates.device_classes(entries, played)
        self.assertEqual(sorted(classes), ["camera", "first_visit", "navigation", "pausepoint", "play"])
        still = classes["pausepoint"]
        self.assertEqual((still["frames"], still["per_frame"][0]["messages"]), (1, 2), "warmups left out")
        self.assertAlmostEqual(still["gpu_ms"], 3.262144 / 3, msg="the mean of the stamped rounds")
        self.assertAlmostEqual(still["page_ms"], .1, msg="the median of the plain rounds")
        self.assertAlmostEqual(still["complete_ms"], 1. + .1 + 3.262144 / 3)
        self.assertAlmostEqual(still["complete_done_ms"], 1. + .1 + 2.)
        play = classes["play"]
        self.assertEqual((play["frames"], play["checkpoints"]), (2, 1))
        self.assertEqual([frame["serialize_ms"] for frame in play["per_frame"]], [5., 6.])
        self.assertEqual(classes["navigation"]["serialize_ms"], 4., "a revisit: the rounds after the first")
        self.assertEqual(classes["first_visit"]["serialize_ms"], 11.)
        # A format 8 frame the stream did not send: its serialize, no page
        # or GPU, and the unit's parts are the means over its messages.
        entries, played = self.stream(1., [2., 2., 2.], sent=False)
        still = flip_gates.device_classes(entries, played)["pausepoint"]
        self.assertEqual((still["sent"], still["gpu_ms"], still["page_ms"]), (.5, 1., .05))
        # A sent message the device did not time, in any run, is an error.
        del played[2]
        with self.assertRaisesRegex(ValueError, "did not time"):
            flip_gates.device_classes(entries, played)
        entries, played = self.stream(1., [2.], runs=2)
        played[2][1] = None
        with self.assertRaisesRegex(ValueError, "every run"):
            flip_gates.device_classes(entries, played)

    def test_the_runs_are_pooled_and_the_interval_spans_them(self):
        # Three runs whose GPU reads 1x, 2x and 1x: the message's GPU is the
        # mean over every stamped round of every run, and the interval over
        # the runs spans what one run alone would have read.
        entries, played = self.stream(1., [1., 1., 1.], runs=3, scale=(1., 2., 1.))
        classes = flip_gates.device_classes(entries, played)
        self.assertAlmostEqual(classes["pausepoint"]["gpu_ms"], 4 / 3)
        reference_entries, reference_played = self.stream(1., [1., 1., 1.], runs=3)
        samples = {name: flip_gates.class_samples(entries_, played_, "pausepoint")
                   for name, (entries_, played_) in (("b", (entries, played)),
                                                     ("a", (reference_entries, reference_played)))}
        units, serialize, page, gpu = samples["b"]
        self.assertEqual(units, [(2,)])
        self.assertEqual(page.shape, (1, 2, 3, 3))
        self.assertFalse(np.isnan(page).any(), "two messages, three runs of three plain rounds")
        # The resample that draws every unit, run and round once is the point.
        every = np.arange(3)
        point = flip_gates.resampled_complete(samples["b"], np.arange(1), every, np.tile(every, (3, 1)),
                                              np.tile(every, (3, 1)))
        self.assertAlmostEqual(point, classes["pausepoint"]["complete_ms"])
        interval = flip_gates.ratio_interval(samples["b"], samples["a"], resamples=400)
        ratio = classes["pausepoint"]["complete_ms"] / flip_gates.device_classes(
            reference_entries, reference_played)["pausepoint"]["complete_ms"]
        self.assertLess(interval[0], ratio)
        self.assertGreater(interval[1], ratio)
        self.assertAlmostEqual(interval[0], (1 + .1 + 1) / 2.1, msg="every run drawn one that read 1x")
        # Its top: two or three of the draws the run that read 2x (a draw
        # of three runs is all three that run once in 27).
        self.assertGreater(interval[1], (1 + .1 + 5 / 3) / 2.1)
        self.assertLessEqual(interval[1], (1 + .1 + 2) / 2.1 + 1e-12)
        self.assertEqual(interval, flip_gates.ratio_interval(samples["b"], samples["a"], resamples=400), "seeded")
        self.assertIsNone(flip_gates.ratio_interval(None, samples["a"]))

    def device_report(self, runs=3, gpus=None):
        streams, device = {}, {"streams": {}}
        for name, (serialize, gpu) in (gpus or {"phase_a": (1., [1.]), "phase_b_forced": (1., [2.]),
                                                 "phase_a_nets": (1., [1.5])}).items():
            for fmt in flip_gates.FORMATS:
                entries, played = self.stream(serialize, gpu, runs=runs)
                streams[flip_gates.key_name(name, fmt)] = entries
                device["streams"][flip_gates.key_name(name, fmt)] = {"runs": [
                    {"run": run, "messages": [rows[run] for rows in played.values()]} for run in range(runs)]}
        return streams, device

    def test_the_flip_is_judged_on_the_device_with_its_diagnostics_beside(self):
        streams, device = self.device_report()
        self.assertEqual(flip_gates.device_runs(device), 3)
        complete = flip_gates.device_complete(streams, device, "phase_b")
        self.assertEqual(sorted(complete["8"]), ["phase_a", "phase_a_nets", "phase_b_forced"])
        self.assertNotIn("first_visit", complete["8"]["phase_a"], "first visits come from their own runs")
        intervals = flip_gates.device_intervals(streams, device, "phase_b", resamples=50)
        self.assertEqual(sorted(intervals["8"]), ["phase_a_nets/phase_a", "phase_b_forced/phase_a",
                                                  "phase_b_forced/phase_a_nets"])
        judged = flip_gates.verdict(complete, "phase_b", 1.25, intervals)
        self.assertAlmostEqual(judged["8"]["pausepoint"]["ratio"], (1. + .1 + 2.) / (1. + .1 + 1.))
        self.assertFalse(judged["8"]["pausepoint"]["within_limit"])
        self.assertEqual(len(judged["8"]["pausepoint"]["interval_95"]), 2)
        self.assertNotIn("first_visit", judged["8"])
        diagnostics = flip_gates.diagnostic_ratios(complete, "phase_b", intervals)["8"]["phase_a_nets"]["pausepoint"]
        self.assertAlmostEqual(diagnostics["flip_over_other"], 3.1 / 2.6)
        self.assertAlmostEqual(diagnostics["other_over_phase_a"], 2.6 / 2.1)
        self.assertEqual(len(diagnostics["flip_over_other_95"]), 2)
        # The first visits, each serializer's stream from a process of its
        # own, played on the device apart: their class beside the rest.
        first_streams, first_device = self.device_report(gpus={"phase_a": (2., [1.]), "phase_b_forced": (1., [1.])})
        complete = flip_gates.device_complete(streams, device, "phase_b", first_streams, first_device)
        first = flip_gates.verdict(complete, "phase_b", 1.25)["8"]["first_visit"]
        self.assertAlmostEqual(first["ratio"], (11. + .1 + 1.) / (11. + .1 + 1.))
        self.assertNotIn("first_visit", complete["8"]["phase_a_nets"])
        del first_streams["phase_b_forced_f8"]
        with self.assertRaisesRegex(ValueError, "first visits"):
            flip_gates.device_complete(streams, device, "phase_b", first_streams, first_device)
        # The diagnostic stack is optional; the two judged stacks are not.
        del streams["phase_a_nets_f7"], streams["phase_a_nets_f8"]
        self.assertEqual(sorted(flip_gates.device_complete(streams, device, "phase_b")["7"]),
                         ["phase_a", "phase_b_forced"])
        del streams["phase_a_f8"]
        with self.assertRaisesRegex(ValueError, "phase_a_f8"):
            flip_gates.device_complete(streams, device, "phase_b")
        # A report of one run holds its messages alone.
        entries, played = self.stream(1., [1.])
        self.assertEqual(flip_gates.device_played({"streams": {"s": {"messages": [rows[0] for rows in played.values()]}}},
                                                  "s")[2], played[2])

    def test_every_stream_is_served_with_its_parts(self):
        # The page reads parts.json for every stream: the whole stream one
        # part, or a stream too large for one buffer (the lattice's Phase A
        # is 2.18 GB of messages) in parts of whole messages, the bytes the
        # recording's.
        import gzip
        from benchmarks import device_frames

        messages = [bytes([index]) * length for index, length in enumerate((5, 0, 7, 3, 9, 0, 4))]
        with tempfile.TemporaryDirectory() as tmp:
            stream, served = Path(tmp) / "stream", Path(tmp) / "served"
            stream.mkdir()
            with gzip.open(stream / "scene.bin.gz", "wb") as file:
                file.write(b"".join(messages))
            (stream / "scene.json").write_text(json.dumps({"frames": [{"len": len(m)} for m in messages]}))
            with patch.object(device_frames, "PART_BYTES", 10):
                device_frames.split_stream(stream, served)
            parts = json.loads((served / "parts.json").read_text())
            self.assertEqual([(part["first"], part["end"]) for part in parts], [(0, 2), (2, 4), (4, 6), (6, 7)])
            for part in parts:
                with gzip.open(served / part["file"]) as file:
                    self.assertEqual(file.read(), b"".join(messages[part["first"]:part["end"]]))
            small = Path(tmp) / "small"
            device_frames.split_stream(stream, small)
            self.assertTrue((small / "scene.bin.gz").is_symlink())
            self.assertEqual(json.loads((small / "parts.json").read_text()),
                             [{"first": 0, "end": 7, "file": "scene.bin.gz"}])

    def test_the_gpu_is_waited_for_until_it_reads_quiet(self):
        from benchmarks import device_frames

        readings, clock = iter([40, 0, 0, 5, 0, 12, 3, 4, 9]), [0.]

        def sleep(seconds):
            clock[0] += seconds

        quiet = device_frames.quiet_gpu(read=lambda: next(readings), sleep=sleep, clock=lambda: clock[0])
        self.assertEqual((quiet["quiet"], quiet["gpu_percent"]), (True, [3, 4, 9]))
        self.assertEqual(quiet["waited_s"], 16.)
        busy = device_frames.quiet_gpu(limit=10, read=lambda: 50, sleep=sleep, clock=lambda: clock[0])
        self.assertFalse(busy["quiet"])
        self.assertGreater(busy["waited_s"], 10)

    def test_a_scenes_runs_are_collected_with_their_quiet_readings(self):
        from benchmarks import device_frames

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            serialize, serve = root / "serialize", root / "serve"
            entries, played = self.stream(1., [1.])
            names = ["phase_a_f8", "phase_b_forced_f8"]
            for name in names:
                (serialize / "streams" / name).mkdir(parents=True)
                (serialize / "streams" / name / "scene.json").write_text(json.dumps({"frames": entries}))
                (serialize / "streams" / name / "scene.bin.gz").write_bytes(name.encode())
            (serialize / "report.json").write_text(json.dumps({"scene": {"name": "S"},
                                                               "streams": {name: {} for name in names}}))
            (serve / "results").mkdir(parents=True)
            (serve / "sources.json").write_text(json.dumps({"served": {}, "tree": {}}))
            (serve / "campaign.json").write_text(json.dumps([{"scene": "S", "streams": names, "rounds": 3, "run": run}
                                                             for run in range(2)]))
            self.assertEqual(device_frames.next_job(serve)["run"], 0)

            def result(run, name, **extra):
                return {"userAgent": "u", "adapter": {}, "timestamps": True, "crossOriginIsolated": True,
                        "rounds": 3, "modes": [], "overflow": 0, "errors": [], "seconds": 1., "started": "s",
                        "finished": "f", "order": names[::1 - 2 * (run % 2)],
                        "messages": [rows[0] for rows in played.values()], **extra}

            for run in range(2):
                for name in names:
                    (serve / "results" / f"S__run{run}__{name}.json").write_text(json.dumps(result(run, name)))
            (serve / "results" / "S__run0__quiet.json").write_text(json.dumps({"quiet": True, "gpu_percent": [0]}))
            self.assertIsNone(device_frames.next_job(serve))
            report = device_frames.collect(serve, "S", serialize, root / "out")
            self.assertEqual([run["run"] for run in report["runs"]], [0, 1])
            self.assertEqual(report["runs"][0]["quiet"]["quiet"], True)
            self.assertIsNone(report["runs"][1]["quiet"])
            self.assertEqual(report["runs"][1]["order"], names[::-1])
            self.assertEqual(flip_gates.device_runs(report), 2)
            self.assertEqual(len(flip_gates.device_played(report, "phase_a_f8")[2]), 2)
            (serve / "results" / "S__run1__phase_a_f8.json").write_text(json.dumps(result(1, "x", adapter={"a": 1})))
            with self.assertRaisesRegex(SystemExit, "another browser"):
                device_frames.collect(serve, "S", serialize, root / "out")

    def test_the_gate_is_every_cell_within_its_limit_and_most_at_or_below_phase_a(self):
        classes = ("pausepoint", "camera", "play", "navigation", "first_visit")

        def summary(file, name, ratios, runs=3, spread=.01, **extra):
            git = {"commit": "c0ffee"}
            verdict = {fmt: {cls: {"ratio": ratio, "within_limit": ratio <= 1.25,
                                   "interval_95": [ratio - spread, ratio + spread]} for cls, ratio in ratios.items()}
                       for fmt in ("8", "7")}
            return {"flip": "phase_b", "limit": 1.25, "scene": {"path": f"/somewhere/{file}", "name": name},
                    "inputs": {"serialize": "s", "browser": None, "device": "d", "gpu": [], "pixels": ["p"]},
                    "input_commits": {"serialize": git, "browser": None, "device": git, "gpu": [], "pixels": [git]},
                    "measured": {**{switch: True for switch in flip_gates.FLIP_SWITCHES["phase_b"]},
                                 "classes": list(ratios)},
                    "source_files_sha256": {}, "source_files_disagree": [],
                    "device": {"rounds": 5, "runs": [{}] * runs}, "first_visits_device": {"runs": [{}] * runs},
                    "verdict": verdict, "pixels": {"passes": True, "worst": {"fraction_pixels_rgb_over24": 0.}},
                    **extra}

        def gate(ratios, **kwargs):
            return flip_gates.gate_verdict([summary(file, name, ratios, **kwargs)
                                            for file, name in flip_gates.TIMED_SCENES["phase_b"]], None, "phase_b")

        fast = dict(zip(classes, (.9, .8, .7, 1.2, .9)))
        passed = gate(fast)
        self.assertTrue(passed["passes"], passed["failures"])
        self.assertEqual((passed["majority"]["cells"], passed["majority"]["at_or_below"]), (25, 20))
        self.assertTrue(passed["resolution"]["passes"])
        table = flip_gates.gate_table(passed)
        self.assertIn("20 of 25", table)
        self.assertIn("| revisit | first visit |", table)
        self.assertIn("1.200 [1.19–1.21]", table)
        # Half at or below 1.0 is not most.
        even = gate(dict(zip(classes, (.9, .8, 1.1, 1.2, 1.1))))
        self.assertFalse(even["passes"])
        self.assertEqual(even["failures"], ["10 of 25 cells at or below 1.0×, not more than half"])
        self.assertTrue(even["resolution"]["fails"], "no interval reaches 1.0 from above")
        # One cell over 1.25 fails, whatever the rest; its interval says
        # whether the failure is resolved.
        over = gate(dict(zip(classes, (.5, .5, .5, 1.3, .5))))
        self.assertEqual(len(over["failures"]), 5, over["failures"])
        self.assertIn("format 8 navigation 1.300", over["failures"][0])
        self.assertTrue(over["resolution"]["fails"])
        spanning = gate(dict(zip(classes, (.5, .5, .5, 1.3, .5))), spread=.1)
        self.assertFalse(spanning["passes"])
        self.assertFalse(spanning["resolution"]["fails"], "1.2-1.4 spans the limit")
        self.assertEqual(len(spanning["resolution"]["over_limit_within_interval"]), 5)
        self.assertIn("Resolved by the intervals: no", flip_gates.gate_table(spanning))
        # Fewer device runs than DEVICE_RUNS fail.
        few = gate(fast, runs=1)
        self.assertIn("EpisodeB2: its device ran 1 time, the gate reads at least 3", few["failures"])
        self.assertIn("EpisodeB2: its first visits device ran 1 time, the gate reads at least 3", few["failures"])
        # Format 7 is quoted, not judged: a full frame over the limit there
        # fails nothing.
        scenes = [summary(file, name, fast) for file, name in flip_gates.TIMED_SCENES["phase_b"]]
        scenes[0]["verdict"]["7"]["camera"] = {"ratio": 2.0, "within_limit": False}
        self.assertTrue(flip_gates.gate_verdict(scenes, None, "phase_b")["passes"])
        self.assertIn("(2.000)", flip_gates.gate_table(flip_gates.gate_verdict(scenes, None, "phase_b")))
        # A run without navigations or first visits, or whose page and GPU
        # are not the device's, fails.
        scenes[1]["measured"]["navigations"] = False
        del scenes[1]["verdict"]["8"]["navigation"]
        scenes[3]["measured"]["first_visits"] = False
        del scenes[3]["verdict"]["8"]["first_visit"]
        scenes[2]["device"] = None
        failures = flip_gates.gate_verdict(scenes, None, "phase_b")["failures"]
        self.assertIn("PriceDiscovery: serialize ran without --navigations", failures)
        self.assertIn("PriceDiscovery: format 8 navigation not measured", failures)
        self.assertIn("OrbsScene: serialize ran without --first-visits", failures)
        self.assertIn("OrbsScene: format 8 first_visit not measured", failures)
        self.assertIn("EpisodeB3: its page and GPU parts are not the device's (complete --device)", failures)


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

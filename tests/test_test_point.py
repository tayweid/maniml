"""benchmarks.test_point (docs/phase_b4_plan.md, B6): its stacks are the
viewer's selections as the other harnesses measure them, the default stack
as the flips left it serializes Phase A's bytes whatever the environment
says, the serializers and the instrumented run take turns on a real
headless scene, and the table adds the parts per frame on stand-in reports.
No episode, no TeX, no GPU."""

import gzip
import json
import os
import subprocess
import tempfile
import textwrap
from pathlib import Path
import unittest

from unittest.mock import patch

from benchmarks import browser_frames, episode_frames, flip_gates, gpu_borders, test_point
from maniml.web.triangle_geometry import _packaged_library
from tests.test_flip_gates import browser_rows, gpu_report

requires_lyon = unittest.skipUnless(os.environ.get("MANIML_LYON_LIBRARY") or _packaged_library(),
                                    "Lyon helper is neither packaged nor explicitly built")


class Stacks(unittest.TestCase):
    def test_each_stack_is_the_variant_the_other_harnesses_measure(self):
        from maniml.web import geometry

        pairs = {name: (image, reference) for name, image, reference in episode_frames.PIXEL_PAIRS}
        for name, stack in test_point.STACKS.items():
            with self.subTest(stack=name):
                self.assertIn(stack.renderer, geometry.RENDERERS)
                self.assertIn(stack.browser, browser_frames.ENVIRONMENTS)
                self.assertIn(stack.frames, episode_frames.VARIANTS)
                self.assertEqual(browser_frames.RENDERERS.get(stack.browser, "triangles"), stack.renderer)
                # The retained frame as episode_frames runs the variant.
                self.assertEqual(stack.environment["MANIML_RETAINED_FRAME"],
                                 episode_frames.RETAINED.get(stack.frames, "0"))
                if stack.pair is not None:
                    self.assertEqual(pairs[stack.pair], (stack.frames, "gpu_border"))
        self.assertIsNone(test_point.STACKS["today"].pair, "the reference")
        self.assertTrue(test_point.STACKS["today"].revision_page)
        self.assertEqual(test_point.STACKS["today"].formats, (7,))
        # The default stack takes out the same switches in every harness,
        # so the defaults select it and a default that flips moves all of
        # them alike; its plays record under the programs' default (None)
        # and the forced Phase B's as the viewer's selection has them, in
        # every harness.
        default = test_point.STACKS["default"]
        self.assertEqual({key for key, value in default.environment.items() if value is None},
                         set(browser_frames.UNSET["default"]))
        self.assertEqual(set(gpu_borders.UNSET["default"]), set(browser_frames.UNSET["default"]))
        for name in ("default", "phase_b", "phase_b_records"):
            stack = test_point.STACKS[name]
            self.assertEqual(stack.play["MANIML_PROGRAMS"], episode_frames.PLAY_PROGRAMS[stack.frames], name)
        for name in ("phase_b", "phase_b_records"):
            stack = test_point.STACKS[name]
            self.assertEqual(stack.play["MANIML_PROGRAMS"],
                             browser_frames.ENVIRONMENTS[stack.browser]["MANIML_PROGRAMS"], name)
        # The forced Phase B takes the patch source out in every harness,
        # as the viewer's selection sends it (B5.6); phase_b_records states
        # the records packed in every harness, as B6 measured it.
        self.assertIsNone(test_point.STACKS["phase_b"].environment["MANIML_PATCH_SOURCE"])
        self.assertEqual(browser_frames.UNSET[test_point.STACKS["phase_b"].browser], ("MANIML_PATCH_SOURCE",))
        self.assertEqual(gpu_borders.UNSET[episode_frames.SAMPLED_AS[test_point.STACKS["phase_b"].frames]],
                         ("MANIML_PATCH_SOURCE",))
        records = test_point.STACKS["phase_b_records"]
        self.assertEqual(records.environment["MANIML_PATCH_SOURCE"], "records")
        self.assertEqual(browser_frames.ENVIRONMENTS[records.browser]["MANIML_PATCH_SOURCE"], "records")
        self.assertNotIn(episode_frames.SAMPLED_AS[records.frames], gpu_borders.UNSET, "sample pins records")
        self.assertEqual(list(test_point.serializers()), [("today", 7), ("phase_a", 7), ("phase_a", 8), ("default", 7),
                                                          ("default", 8), ("phase_b", 7), ("phase_b", 8),
                                                          ("phase_b_records", 7), ("phase_b_records", 8)])


SCENE = textwrap.dedent('''\
    from maniml import *

    class Point(Scene):
        def construct(self):
            square = Square(fill_opacity=1)
            self.play(FadeIn(square), run_time=0.2)
            self.pause()
            dot = Dot().add_updater(lambda d, dt: d.shift(RIGHT * dt))
            self.add(dot)
            self.play(square.animate.shift(RIGHT), run_time=0.3)
            self.pause()
    ''')


@requires_lyon
class Serialize(unittest.TestCase):
    """The seven serializers, and the instrumented run, on a real headless
    scene: a still pausepoint and a ticked one, with their plays."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.path = Path(self.tmpdir.name) / "point.py"
        self.path.write_text(SCENE)
        self.scene, error = episode_frames.load_episode(self.path, "Point")
        self.assertIsNone(error)

    def tearDown(self):
        self.scene.camera.release()
        self.tmpdir.cleanup()

    def test_the_default_stack_as_the_flips_left_it_is_phase_bs_draws(self):
        # Whatever the environment says, the default stack takes the
        # defaults' switches, and since 2026-10-07 they are the whole Phase
        # B stack: its full frames are the forced Phase B's but for the
        # renderer the header names, which the page's selection reads.
        # today's and phase_a's are Phase A's, with or without the retained
        # frame, and the forced Phase B's patches go as the selection sends
        # them (rows, B5.6) and as phase_b_records states (records).
        from maniml.web.geometry import GeometryCache, parse_geometry_message, serialize_scene

        scene = self.scene
        episode_frames.show_frame(scene, episode_frames.select_frames(scene.animation_checkpoints)[0])
        messages = {}
        with patch.dict(os.environ, MANIML_FILL="meshes", MANIML_SURFACE="grids", MANIML_PROGRAMS="off",
                        MANIML_PATCH_SOURCE="records"):
            for (name, fmt), (renderer, environment, _) in test_point.serializers().items():
                if fmt == 7:
                    with flip_gates.stack_environment(environment):
                        messages[name] = serialize_scene(scene, GeometryCache(), renderer=renderer)
            self.assertEqual(os.environ["MANIML_FILL"], "meshes", "the environment is handed back")
        self.assertEqual(messages["today"], messages["phase_a"])
        default, default_payload = parse_geometry_message(messages["default"])
        phase_b, phase_b_payload = parse_geometry_message(messages["phase_b"])
        self.assertEqual(default.pop("renderer"), "triangles")
        self.assertEqual(phase_b.pop("renderer"), "phase_b")
        self.assertEqual(default, phase_b)
        self.assertEqual(default_payload, phase_b_payload)
        for name, rows in (("phase_b", True), ("phase_b_records", False)):
            header = parse_geometry_message(messages[name])[0]
            self.assertEqual(header["renderer"], "phase_b")
            self.assertEqual(any("rows" in batch for batch in header["batches"]), rows, name)

    def test_the_serializers_take_turns_per_class(self):
        scene = self.scene
        indices = episode_frames.select_frames(scene.animation_checkpoints)
        with patch.dict(os.environ, MANIML_PROGRAMS="off"):
            frames = flip_gates.measure_serializers(scene, indices, test_point.serializers(), samples=2, warmups=1,
                                                    replays=1, tick_updaters=True, play_frames=True)
        keys = [flip_gates.key_name(*key) for key in test_point.serializers()]
        still, ticked = frames
        self.assertEqual((still["class"], ticked["class"]), ("pausepoint", "ticked"))
        for frame in frames:
            self.assertEqual(list(frame[frame["class"]]), keys)
            self.assertEqual(list(frame["play"])[4:], keys)
        # A still frame sends a negotiated page nothing and a full frame
        # each round otherwise; a tick moves the dot.
        self.assertEqual([still["pausepoint"][key]["sent"] for key in keys], [2, 2, 0, 2, 0, 2, 0, 2, 0])
        self.assertEqual([ticked["ticked"][key]["sent"] for key in keys], [2] * 9)

    def test_the_instrumented_run_attributes_each_stacks_python(self):
        with patch.dict(os.environ):
            test_point.main(["python", "--scene", str(self.path), "Point", "--tick-updaters", "--play-frames",
                             "--samples", "2", "--warmups", "1", "--replays", "1",
                             "--output", str(Path(self.tmpdir.name) / "python")])
        report = json.loads((Path(self.tmpdir.name) / "python" / "report.json").read_text())
        reduced = report["reduced"]
        self.assertEqual(sorted(reduced), ["default_f8", "phase_b_f8", "today_f7"])
        for key, classes in reduced.items():
            self.assertEqual(sorted(classes), ["pausepoint", "play", "ticked"], key)
        # The whole-frame path keeps nothing; the retained frame keeps the
        # still frame whole and sends it nothing.
        self.assertNotIn("leaves_kept", reduced["today_f7"]["pausepoint"])
        still = reduced["default_f8"]["pausepoint"]
        self.assertEqual((still["leaves_prepared"]["mean"], still["sent"]["mean"]), (0, 0))
        self.assertGreater(still["leaves_kept"]["mean"], 0)
        # The updaters' tick is the scene's Python; a play's is its
        # interpolation, and the forced Phase B's plays record programs.
        self.assertGreater(reduced["default_f8"]["ticked"]["scene_ms"]["mean"], 0)
        self.assertEqual(reduced["today_f7"]["play"]["programs"]["mean"], 0)
        self.assertGreater(reduced["phase_b_f8"]["play"]["programs"]["mean"], 0)
        self.assertEqual(report["environment"].get("MANIML_PROGRAMS"), "off")


def serialize_block(ms):
    return {key: {"p50": value, "min": value, "n": 12, "sent": 12} for key, value in ms.items()}


def with_wire(rows, wire):
    return [dict(row, wire_bytes=wire if row["sent"] else 0) for row in rows]


class Table(unittest.TestCase):
    """Two frames, a still (2) and a ticked one (5, with its play): per
    stack, format and class, serialize + page + the sent GPU, the wire
    riding along, today's page the revision's, and the pixels per class."""

    KEYS = ("today_f7", "phase_a_f7", "phase_a_f8", "default_f7", "default_f8", "phase_b_f7", "phase_b_f8",
            "phase_b_records_f7", "phase_b_records_f8")

    def reports(self):
        serialize = {"frames": [
            {"checkpoint": 2, "class": "pausepoint",
             "pausepoint": serialize_block({key: 20. if key == "today_f7" else 1. for key in self.KEYS})},
            {"checkpoint": 5, "class": "ticked", "ticked": serialize_block({key: 3. for key in self.KEYS}),
             "play": {key: {"per_frame_p50": [4., 6.]} for key in self.KEYS}}]}
        browser = {"variants": {}}
        for name, page in (("phase_a", .5), ("default", .5), ("phase_b_forced", .7), ("phase_b_forced_records", .6)):
            browser["variants"][name] = {"rows": with_wire(
                browser_rows(2, "pausepoint", page) + browser_rows(5, "ticked", page) + browser_rows(5, "play", 1.),
                1000)}
            # Format 8: the still is not sent, the ticked frame is.
            browser["variants"][name + "_delta"] = {"rows": with_wire(
                browser_rows(2, "pausepoint", 0., sent=False) + browser_rows(5, "ticked", .2)
                + browser_rows(5, "play", .8), 100)}
        page = {"pages": {"revision": {"rows": browser_rows(2, "pausepoint", 2.) + browser_rows(5, "ticked", 2.)
                                       + browser_rows(5, "play", 3.)},
                          "tree": {"rows": []}}}
        gpu = [gpu_report({variant: {(2, "pausepoint", False): [4.], (5, "pausepoint", True): [3.],
                                     (5, "play", False): [{"phase_b_retained": 7.,
                                                           "phase_b_retained_records": 6.5}.get(variant, 5.)]}
                           for variant in ("gpu_border", "retained", "default", "phase_b_retained",
                                           "phase_b_retained_records")})]

        def frame(checkpoint, ticked, pairs):
            return {"checkpoint": checkpoint, "updaters_ticked": ticked,
                    "pixels": {pair: {"fraction_pixels_rgb_over24": value, "max_rgba": 9.} for pair, value in pairs},
                    "play": {"checkpoint": checkpoint - 1, "pixel_frames": [3, 4],
                             "pixels": {pair: {"fraction_pixels_rgb_over24": value / 2, "max_rgba": 3.}
                                        for pair, value in pairs}}}

        flag_off = {variant: {(2, "pausepoint", False): [6.], (5, "pausepoint", True): [6.], (5, "play", False): [6.]}
                    for variant in ("gpu_border", "retained", "default", "phase_b_retained",
                                    "phase_b_retained_records")}
        frames_b = {**gpu_report({key: flag_off[key]
                                  for key in ("gpu_border", "phase_b_retained", "phase_b_retained_records")},
                                 column=flip_gates.FLAG_OFF_GPU),
                    "frames": [frame(2, False, [("phase_b_vs_gpu_border", .001),
                                                ("phase_b_records_vs_gpu_border", .001)]),
                               frame(5, True, [("phase_b_vs_gpu_border", .002),
                                               ("phase_b_records_vs_gpu_border", .002)])]}
        frames_a = {**gpu_report({key: flag_off[key] for key in ("gpu_border", "retained", "default")},
                                 column=flip_gates.FLAG_OFF_GPU),
                    "frames": [frame(2, False, [("retained_vs_gpu_border", 0.), ("default_vs_gpu_border", 0.)]),
                               frame(5, True, [("retained_vs_gpu_border", 0.), ("default_vs_gpu_border", 0.)])]}
        return serialize, browser, page, gpu, [frames_b, frames_a]

    def test_the_complete_frame_per_stack_format_and_class(self):
        result = test_point.test_point(*self.reports())
        self.assertEqual(list(result), list(self.KEYS))
        today = result["today_f7"]["classes"]
        # Today's page is the revision's, drawing every full frame.
        self.assertEqual(today["pausepoint"]["complete_ms"], 20. + 2. + 4.)
        self.assertEqual(today["pausepoint"]["wire_bytes"], 1000)
        self.assertEqual([frame["complete_ms"] for frame in today["play"]["per_frame"]], [4. + 3. + 5., 6. + 3. + 5.])
        self.assertEqual(result["phase_a_f7"]["classes"]["pausepoint"]["complete_ms"], 1. + .5 + 4.)
        # Format 8 sends the still nothing: its serialize alone, no bytes.
        still = result["phase_a_f8"]["classes"]["pausepoint"]
        self.assertEqual((still["complete_ms"], still["wire_bytes"], still["sent"]), (1., 0, 0))
        self.assertEqual(result["default_f8"]["classes"]["ticked"]["complete_ms"], 3. + .2 + 3.)
        self.assertEqual(result["phase_b_f8"]["classes"]["play"]["complete_ms"], 5. + .8 + 7.)
        self.assertEqual(result["phase_b_f8"]["flag_off_check"]["play"]["complete_ms"], 5. + .8 + 6.)
        self.assertEqual(result["phase_b_records_f7"]["classes"]["play"]["complete_ms"], 5. + 1. + 6.5)
        self.assertEqual(result["phase_b_records_f7"]["classes"]["pausepoint"]["complete_ms"], 1. + .6 + 4.)
        # The pixels against Phase A without the retained frame, per class.
        self.assertEqual(result["today_f7"]["pixels"], "reference")
        pixels = result["phase_b_f8"]["pixels"]
        self.assertEqual({cls: (value["frames"], value["worst"]["fraction_pixels_rgb_over24"])
                          for cls, value in pixels.items()},
                         {"pausepoint": (1, .001), "ticked": (1, .002), "play": (4, .001)})
        self.assertTrue(all(value["passes"] for value in pixels.values()))
        ratios = test_point.ratios(result)
        self.assertAlmostEqual(ratios["phase_a_f8"]["pausepoint"], 1. / 26.)
        self.assertEqual(ratios["today_f7"], {"pausepoint": 1., "ticked": 1., "play": 1.})
        summary = {"stacks": result, "ratios": ratios}
        self.assertEqual(len(test_point.markdown_table(summary).splitlines()), 2 + 3 * 9)

    def test_the_command_refuses_inputs_that_do_not_belong_together(self):
        serialize, browser, page, gpu, pixels = self.reports()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            def write(name, report, frames=(2, 5)):
                (root / name).mkdir(exist_ok=True)
                report = {**report, "scene": {"measured_checkpoints": list(frames)}, "git": {}}
                (root / name / "report.json").write_text(json.dumps(report))

            def table():
                test_point.main(["table", "--serialize", str(root / "serialize"), "--browser", str(root / "browser"),
                                 "--page", str(root / "page"), "--gpu", str(root / "gpu"), "--pixels",
                                 str(root / "frames_b"), str(root / "frames_a"), "--output", str(root / "out")])

            write("serialize", serialize)
            write("browser", browser)
            write("page", {**page, "stream": str(root / "browser" / "phase_a"), "revision": "main",
                           "revision_commit": "0" * 40})
            write("frames_b", pixels[0])
            write("frames_a", pixels[1])
            write("gpu", gpu[0])
            with self.assertRaisesRegex(SystemExit, "not an attribution run"):
                table()
            write("gpu", {**gpu[0], "gpu_timestamps": True}, frames=(2, 6))
            with self.assertRaisesRegex(SystemExit, "other frames"):
                table()
            write("gpu", {**gpu[0], "gpu_timestamps": True})
            write("frames_a", {**pixels[1], "gpu_timestamps": True})
            with self.assertRaisesRegex(SystemExit, "pixel pairs come from a flag-off run"):
                table()
            write("frames_a", pixels[1])
            write("page", {**page, "stream": str(root / "browser" / "default"), "revision": "main",
                           "revision_commit": "0" * 40})
            with self.assertRaisesRegex(SystemExit, "not the browser run's phase_a stream"):
                table()
            write("page", {**page, "stream": str(root / "browser" / "phase_a"), "revision": "main",
                           "revision_commit": "0" * 40})
            table()
            summary = json.loads((root / "out" / "summary.json").read_text())
            # The instrumented run is reduced from its rows, so a run
            # recorded before a reduction was added still reads.
            write("python", {"frames": python_frames()})
            test_point.main(["table", "--serialize", str(root / "serialize"), "--browser", str(root / "browser"),
                             "--page", str(root / "page"), "--gpu", str(root / "gpu"), "--pixels",
                             str(root / "frames_b"), str(root / "frames_a"), "--python", str(root / "python"),
                             "--output", str(root / "with_python")])
            with_python = json.loads((root / "with_python" / "summary.json").read_text())
            markdown = (root / "with_python" / "summary.md").read_text()
        self.assertEqual(summary["stacks"]["phase_a_f8"]["classes"]["pausepoint"]["complete_ms"], 1.)
        self.assertNotIn("per_frame", summary["stacks"]["phase_a_f8"]["classes"]["pausepoint"])
        self.assertEqual(with_python["python"], test_point.reduce_python(python_frames()))
        self.assertEqual(sorted(with_python["python_by_checkpoint"]), ["2", "5"])
        self.assertIn("| 5: default_f8, ticked (1) |", markdown)

    def test_the_python_table_reads_medians_per_class_and_checkpoint(self):
        # A collection pause among a class's rows moves its mean by tens of
        # milliseconds; the table reads the median, per class and per
        # checkpoint, the means kept in the JSON.
        frames = python_frames()
        reduced = test_point.reduce_python(frames)
        still = reduced["today_f7"]["pausepoint"]["serialize_ms"]
        self.assertEqual((still["p50"], still["mean"], still["n"]), (1., 34., 3))
        by_checkpoint = test_point.reduce_python_by_checkpoint(frames)
        self.assertEqual({checkpoint: {key: sorted(classes) for key, classes in serializers.items()}
                          for checkpoint, serializers in by_checkpoint.items()},
                         {"2": {"today_f7": ["pausepoint"]},
                          "5": {"today_f7": ["play", "ticked"], "default_f8": ["play", "ticked"]}})
        lines = test_point.python_table(reduced, by_checkpoint).splitlines()
        self.assertEqual(lines[2:], [
            "| today_f7, pausepoint (3) | 0 | 1.00 | 0.50 | 0 | – | 0.25 | – | – | 2.0 KB |",
            "| today_f7, ticked (1) | 2.00 | 3.00 | 1.50 | 0 | – | 0.75 | – | – | 2.0 KB |",
            "| today_f7, play (1) | 0.50 | 6.00 | 3.00 | 1.20 (4) | – | 1.50 | – | – | 2.0 KB |",
            "| default_f8, ticked (1) | 2.00 | 0.80 | 0.40 | 0 | 0.30 (9) | 0.20 | 0.010 | 12 / 9 / 0 | 0 |",
            "| default_f8, play (1) | 0.50 | 2.00 | 1.00 | 0 | 0 | 0.50 | 0.020 | 10 / 0 / 2 | 2.0 KB |",
            "| 2: today_f7, pausepoint (3) | 0 | 1.00 | 0.50 | 0 | – | 0.25 | – | – | 2.0 KB |",
            "| 5: today_f7, ticked (1) | 2.00 | 3.00 | 1.50 | 0 | – | 0.75 | – | – | 2.0 KB |",
            "| 5: today_f7, play (1) | 0.50 | 6.00 | 3.00 | 1.20 (4) | – | 1.50 | – | – | 2.0 KB |",
            "| 5: default_f8, ticked (1) | 2.00 | 0.80 | 0.40 | 0 | 0.30 (9) | 0.20 | 0.010 | 12 / 9 / 0 | 0 |",
            "| 5: default_f8, play (1) | 0.50 | 2.00 | 1.00 | 0 | 0 | 0.50 | 0.020 | 10 / 0 / 2 | 2.0 KB |"])


def python_row(ms, **columns):
    """A row of the instrumented run: the whole-frame path's, unless
    ``columns`` give the retained frame's."""
    return {"scene_ms": 0., "serialize_ms": ms, "prepare_ms": ms / 2, "encode_ms": ms / 4, "lyon_ms": 0.,
            "lyon_calls": 0, "compare_ms": 0., "compare_calls": 0, "diff_ms": 0., "wire_bytes": 2048, "sent": True,
            **columns}


def python_frames():
    """Two frames of the instrumented run: a still (2) with one slow
    serialization, and a ticked one (5) with the play into it."""
    retained = {"leaves": 12, "leaves_adopted": 0, "batches_encoded": 0, "batches_reused": 3}
    return [
        {"checkpoint": 2, "class": "pausepoint",
         "pausepoint": {"today_f7": [python_row(1.), python_row(1.), python_row(100.)]}},
        {"checkpoint": 5, "class": "ticked",
         "ticked": {"today_f7": [python_row(3., scene_ms=2.)],
                    "default_f8": [python_row(.8, scene_ms=2., compare_ms=.3, compare_calls=9, diff_ms=.01,
                                              wire_bytes=0, sent=False, leaves_kept=12, leaves_compared=9,
                                              leaves_prepared=0, **retained)]},
         "play": {"checkpoint": 4, "line": 9,
                  "today_f7": [python_row(6., scene_ms=.5, lyon_ms=1.2, lyon_calls=4)],
                  "default_f8": [python_row(2., scene_ms=.5, diff_ms=.02, leaves_kept=10, leaves_compared=0,
                                            leaves_prepared=2, **retained)]}}]


class Page(unittest.TestCase):
    def test_a_revisions_page_is_its_static_beside_this_trees_harness(self):
        with tempfile.TemporaryDirectory() as tmp:
            harness, commit = test_point.page_tree("HEAD", Path(tmp))
            committed = subprocess.run(["git", "show", f"{commit}:maniml/web/static/webgpu.js"],
                                       cwd=test_point.ROOT, capture_output=True, check=True).stdout
            self.assertEqual((Path(tmp) / "maniml/web/static/webgpu.js").read_bytes(), committed)
            self.assertEqual(harness.read_bytes(), browser_frames.HARNESS.read_bytes())
            self.assertEqual((Path(tmp) / "tests/webgpu_fake_device.cjs").read_bytes(),
                             browser_frames.FAKE_DEVICE.read_bytes())

    def test_only_a_format_7_stream_is_played_through_another_revisions_page(self):
        with tempfile.TemporaryDirectory() as tmp:
            stream = Path(tmp) / "phase_a_delta"
            stream.mkdir()
            (stream / "scene.json").write_text(json.dumps({"format_version": 8, "frames": []}))
            (stream / "scene.bin.gz").write_bytes(gzip.compress(b""))
            with self.assertRaisesRegex(SystemExit, "not a format 7 stream"):
                test_point.main(["page", "--stream", str(stream), "--output", str(Path(tmp) / "page")])


if __name__ == "__main__":
    unittest.main()

"""Frame selection and report shape of benchmarks.episode_frames, with a
stand-in scene and sampler: no episode, no TeX, no GPU. The play-frame
replay runs a real headless Scene from a temp file, as
tests.test_checkpoint_reload does."""

import json
import tempfile
import textwrap
from pathlib import Path
from types import SimpleNamespace
import unittest

from PIL import Image

from benchmarks import episode_frames
from benchmarks.gpu_borders import gpu_columns


def checkpoints(count, stops=(), run_time=None):
    # Only pause() flags a dict; every other checkpoint lacks the key. A
    # play's checkpoint carries its run_time, a pause's None.
    return [dict({"index": index, "line_number": 10 + index, "name": None,
                  "run_time": None if index in stops or index == 0 else run_time},
                 **({"stop": True, "name": f"p{index}"} if index in stops else {}))
            for index in range(count)]


TIMINGS = {"period_ns": 41.7, "total_ms": 3., "sum_ms": 2.5, "readback_ms": 1.4, "begin_tick": 10, "end_tick": 82,
           "passes": [{"label": "borders", "ms": .5, "exclusive_ms": .5}, {"label": "out/0", "ms": 1., "exclusive_ms": .8},
                      {"label": "out/1", "ms": .5, "exclusive_ms": .4}, {"label": "resolve", "ms": .25, "exclusive_ms": .2},
                      {"label": "resolve", "ms": .25, "exclusive_ms": 1.1}]}


class FrameSelection(unittest.TestCase):
    def test_pause_anchored_files_measure_their_pausepoints(self):
        self.assertEqual(episode_frames.select_frames(checkpoints(10, stops=(3, 7, 9)), every=4), [3, 7, 9])

    def test_unanchored_files_stride_after_the_empty_first_checkpoint(self):
        self.assertEqual(episode_frames.select_frames(checkpoints(10)), list(range(1, 10)))
        self.assertEqual(episode_frames.select_frames(checkpoints(10), every=3), [1, 4, 7, 9])
        self.assertEqual(episode_frames.select_frames(checkpoints(10), every=4), [1, 5, 9])

    def test_cap_thins_evenly_and_keeps_the_last(self):
        pool = list(range(2, 62, 2))
        picked = episode_frames.select_frames(checkpoints(62, stops=pool), max_frames=4)
        self.assertEqual(len(picked), 4)
        self.assertEqual(picked, sorted(set(picked)))
        self.assertEqual((picked[0], picked[-1]), (pool[0], pool[-1]))
        self.assertEqual(episode_frames.select_frames(checkpoints(62, stops=pool), max_frames=1), [pool[-1]])

    def test_a_scene_that_never_reached_a_checkpoint_measures_the_blank_frame(self):
        self.assertEqual(episode_frames.select_frames(checkpoints(1)), [0])

    def test_the_play_before_a_pausepoint_is_the_last_checkpoint_with_a_run_time(self):
        chain = checkpoints(6, stops=(2, 5), run_time=.5)
        self.assertEqual(episode_frames.play_before(chain, 2), 1)
        self.assertEqual(episode_frames.play_before(chain, 5), 4)
        self.assertEqual(episode_frames.play_before(chain, 4), 4)
        self.assertIsNone(episode_frames.play_before(chain, 0))
        self.assertIsNone(episode_frames.play_before(checkpoints(3, stops=(1, 2)), 2), "pauses only")

    def test_play_frame_count_is_the_time_progressions(self):
        self.assertEqual(episode_frames.play_frame_count(30, .2), 6)
        self.assertEqual(episode_frames.play_frame_count(30, 1), 30)
        self.assertEqual(episode_frames.play_frame_count(30, .01), 1)


class Rotation(unittest.TestCase):
    def test_every_variant_leads_and_follows_every_other(self):
        orders = [episode_frames.rotation(("a", "b", "c"), i) for i in range(6)]
        self.assertEqual(orders, [("a", "b", "c"), ("b", "c", "a"), ("c", "a", "b"),
                                  ("c", "b", "a"), ("a", "c", "b"), ("b", "a", "c")])


class GpuColumns(unittest.TestCase):
    """gpu_borders.gpu_columns, the one set of column names both harnesses
    write."""

    def test_labels_become_columns_and_numbered_or_repeated_passes_add(self):
        columns = gpu_columns(TIMINGS)
        self.assertEqual((columns["gpu_total_ms"], columns["gpu_readback_ms"]), (3., 1.4))
        self.assertEqual(columns["gpu_pass_out_ms"], 1.5)
        self.assertAlmostEqual(columns["gpu_exclusive_out_ms"], 1.2)
        self.assertEqual(columns["gpu_pass_resolve_ms"], .5)
        self.assertAlmostEqual(columns["gpu_exclusive_resolve_ms"], 1.3)
        self.assertEqual(len(columns["gpu_passes"]), 5)
        self.assertNotIn("gpu_pass_programs_ms", columns, "a pass the frame did not encode has no column")


class Summary(unittest.TestCase):
    def test_columns_missing_from_some_rows_reduce_over_the_rows_that_have_them(self):
        rows = [{"serialize_through_rgba_image_ms": 4., "prepare_ms": 1., "gpu_total_ms": 2., "gpu_pass_out_ms": 1.5,
                 "post_readback_ms": .3, "gpu_readback_ms": 1.4},
                {"serialize_through_rgba_image_ms": 6., "prepare_ms": 1., "gpu_total_ms": 3., "gpu_pass_out_ms": 2.,
                 "gpu_pass_programs_ms": .5, "post_readback_ms": .4, "gpu_readback_ms": 1.5},
                {"serialize_through_rgba_image_ms": 5., "prepare_ms": 1., "post_readback_ms": .3}]
        summary = episode_frames.summarize(rows)
        self.assertEqual(list(summary), ["serialize_through_rgba_image_ms", "post_readback_ms", "prepare_ms",
                                         "gpu_total_ms", "gpu_readback_ms", "gpu_pass_out_ms", "gpu_pass_programs_ms"])
        self.assertEqual(summary["serialize_through_rgba_image_ms"], {"p50": 5., "min": 4., "n": 3})
        self.assertEqual(summary["gpu_total_ms"], {"p50": 2.5, "min": 2., "n": 2})
        self.assertEqual(summary["gpu_readback_ms"]["n"], 2)
        self.assertEqual(summary["gpu_pass_programs_ms"]["n"], 1)


def pictures(**colors):
    return {variant: Image.new("RGBA", (8, 4), color) for variant, color in colors.items()}


class PixelPairs(unittest.TestCase):
    def test_the_gate_pairs_are_reported_for_the_variants_that_rendered(self):
        pairs = episode_frames.pixel_pairs(pictures(patch_fill=(0, 0, 0, 255), gpu_border=(0, 0, 0, 255),
                                                    original_2d=(255, 255, 255, 255)))
        self.assertEqual(list(pairs), ["patch_vs_gpu_border", "patch_vs_original", "gpu_vs_original"])
        self.assertEqual(pairs["patch_vs_gpu_border"]["fraction_pixels_rgb_over24"], 0.)
        self.assertEqual(pairs["patch_vs_original"]["fraction_pixels_rgb_over24"], 1.)
        with_cpu = episode_frames.pixel_pairs(pictures(patch_fill=(0, 0, 0, 255), cpu_border=(0, 0, 0, 255)))
        self.assertEqual(list(with_cpu), ["patch_vs_cpu"])
        self.assertEqual(episode_frames.pixel_pairs(pictures(original_2d=(0, 0, 0, 255))), {})


class FakeScene:
    """Just what measure() touches: checkpoints to restore, an empty draw
    list (the source contract digests nothing), a camera packet and the
    updater switches."""
    def __init__(self, count, stops, live=False):
        self.animation_checkpoints = checkpoints(count, stops)
        self.render_groups = []
        self.mobjects = []
        self.camera = SimpleNamespace(uniforms={"frame_shape": [14.2, 8.]}, draw_fbo=SimpleNamespace(size=(64, 36)),
                                      refresh_uniforms=lambda: None, fps=30)
        self.restored, self.updates, self.live = [], [], live
        self.ambient_rotation_active = True

    def _restore_checkpoint_for_display(self, index):
        self.restored.append(index)

    def should_update_mobjects(self):
        return self.live

    def update_mobjects(self, dt):
        self.updates.append(dt)


def make_sampler(variants, *, failing=None):
    calls = []

    def sampler(variant):
        calls.append(variant)
        if variant == failing:
            raise ValueError("unsupported prototype")
        row = {"serialize_through_rgba_image_ms": 5. + len(calls) % 3, "submit_through_full_readback_ms": 2.,
               "post_readback_ms": .3, "prepare_ms": .5, "render_cpu_encode_ms": .7}
        if variant != "original_2d":
            row.update(gpu_columns(TIMINGS))
        # The reference and patch_fill agree; original_2d differs on one row of pixels.
        image = Image.new("RGBA", (64, 36), (0, 0, 0, 255))
        if variant == "original_2d":
            image.paste((255, 255, 255, 255), (0, 0, 64, 9))
        return row, image, {"resolution": [64, 36], "unsupported": ["Surface"] if variant == "original_2d" else []}
    return sampler, calls


class Measure(unittest.TestCase):
    variants = ("patch_fill", "gpu_border", "original_2d")

    def measure(self, scene, sampler, **kwargs):
        with tempfile.TemporaryDirectory() as tmp:
            report = episode_frames.measure(scene, episode_frames.select_frames(scene.animation_checkpoints),
                                            self.variants, samples=2, warmups=1, sampler=sampler,
                                            output=Path(tmp), report={"variants_in_rotation": list(self.variants)},
                                            **kwargs)
            written = json.loads((Path(tmp) / "report.json").read_text())
            pngs = sorted(path.name for path in Path(tmp).glob("*.png"))
        return report, written, pngs

    def test_report_and_summary_shape(self):
        scene = FakeScene(6, stops=(2, 5))
        sampler, calls = make_sampler(self.variants)
        report, written, pngs = self.measure(scene, sampler)
        self.assertEqual(scene.restored, [2, 5])
        self.assertEqual(scene.updates, [0, 0], "one dt=0 pass per restore, no ticking by default")
        self.assertFalse(scene.ambient_rotation_active, "show_frame switches the ambient rotation off")
        self.assertEqual(len(calls), 2 * 3 * 3)  # two frames, one warmup + two samples, three variants
        self.assertEqual([frame["checkpoint"] for frame in report["frames"]], [2, 5])
        frame = report["frames"][0]
        self.assertEqual((frame["line"], frame["name"], frame["stop"]), (12, "p2", True))
        self.assertEqual((frame["should_update_mobjects"], frame["updaters_ticked"]), (False, False))
        self.assertEqual(set(frame["cold"]), set(self.variants))
        self.assertEqual(set(frame["variants"]), set(self.variants))
        self.assertEqual(list(frame["pixels"]), ["patch_vs_gpu_border", "patch_vs_original", "gpu_vs_original"])
        self.assertEqual(frame["pixels"]["patch_vs_gpu_border"]["fraction_pixels_rgb_over24"], 0.)
        self.assertAlmostEqual(frame["pixels"]["patch_vs_original"]["fraction_pixels_rgb_over24"], .25)
        self.assertNotIn("play", frame)
        for variant in self.variants:
            rows = report["variants"][variant]["samples"]
            self.assertEqual(len(rows), 4)
            self.assertTrue(all(not row["warmup"] and row["phase"] == "pausepoint" for row in rows))
            self.assertEqual({row["checkpoint"] for row in rows}, {2, 5})
            self.assertNotIn("play_timing_ms", report["variants"][variant])
        self.assertIn("gpu_pass_borders_ms", report["variants"]["gpu_border"]["timing_ms"])
        self.assertIn("gpu_readback_ms", report["variants"]["gpu_border"]["timing_ms"])
        self.assertNotIn("gpu_total_ms", report["variants"]["original_2d"]["timing_ms"])
        self.assertEqual(report["variants"]["original_2d"]["samples"][0]["unsupported"], ["Surface"])
        self.assertEqual(written["frames"][1]["checkpoint"], 5)
        self.assertEqual(pngs, [])
        summary = episode_frames.summary_of(report)
        self.assertNotIn("cold", summary["frames"][0])
        self.assertEqual(summary["variants"]["patch_fill"]["gpu_total_ms"]["n"], 4)
        self.assertEqual(summary["variants"]["patch_fill"]["post_readback_ms"]["p50"], .3)
        self.assertEqual(summary["play_variants"], {})
        table = episode_frames.markdown_table(summary)
        lines = table.splitlines()
        self.assertEqual(len(lines), 2 + 2 + 1)
        self.assertTrue(all(line.count("|") == lines[0].count("|") for line in lines))
        self.assertIn("patch_vs_original px>24", lines[0])
        self.assertIn("| pausepoint |", lines[2])
        self.assertIn("| all |", lines[-1])
        self.assertIn("25.000%", lines[2])

    def test_a_failing_variant_is_recorded_and_the_frame_kept(self):
        scene = FakeScene(4, stops=(3,))
        sampler, calls = make_sampler(self.variants, failing="original_2d")
        report, _, _ = self.measure(scene, sampler)
        frame = report["frames"][0]
        self.assertIn("unsupported prototype", frame["errors"]["original_2d"]["error"])
        self.assertEqual(calls.count("original_2d"), 1)  # skipped for the rest of the frame
        self.assertEqual(set(frame["variants"]), {"patch_fill", "gpu_border"})
        self.assertEqual(list(frame["pixels"]), ["patch_vs_gpu_border"])
        self.assertNotIn("original_2d", report["variants"])
        self.assertIn("–", episode_frames.markdown_table(episode_frames.summary_of(report)))

    def test_images_flag_writes_each_variant_once_per_frame(self):
        scene = FakeScene(3, stops=(1, 2))
        sampler, _ = make_sampler(self.variants)
        _, _, pngs = self.measure(scene, sampler, images=True)
        self.assertEqual(pngs, [f"frame_{index:03}_{variant}.png" for index in (1, 2) for variant in sorted(self.variants)])

    def test_tick_updaters_ticks_only_frames_that_have_them(self):
        live = FakeScene(3, stops=(2,), live=True)
        sampler, _ = make_sampler(self.variants)
        report, _, _ = self.measure(live, sampler, tick_updaters=True)
        self.assertEqual(live.updates, [0] + [1 / 30] * 3, "the restore's dt=0, then one tick per round")
        frame = report["frames"][0]
        self.assertEqual((frame["should_update_mobjects"], frame["updaters_ticked"]), (True, True))
        self.assertIn("pausepoint, updaters ticking", episode_frames.markdown_table(episode_frames.summary_of(report)))
        static = FakeScene(3, stops=(2,))
        report, _, _ = self.measure(static, sampler, tick_updaters=True)
        self.assertEqual(static.updates, [0])
        self.assertEqual(report["frames"][0]["updaters_ticked"], False)


PLAY_SCENE = textwrap.dedent('''\
    from maniml import *

    class PlayScene(Scene):
        def construct(self):
            square = Square()
            self.play(FadeIn(square), run_time=0.2)
            self.pause()
            self.play(square.animate.shift(RIGHT), run_time=0.3)
            self.wait(0.1)
            self.pause()
    ''')


class PlayFrames(unittest.TestCase):
    """The play leading into each pausepoint, replayed through the scene's
    own retained replay with the variants sampled mid-interpolation."""
    variants = ("patch_fill", "gpu_border")

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        path = Path(self.tmpdir.name) / "play_scene.py"
        path.write_text(PLAY_SCENE)
        self.scene, error = episode_frames.load_episode(path, "PlayScene")
        self.assertIsNone(error)

    def tearDown(self):
        # A headless scene owns a standalone GPU context; release it as
        # tests.test_checkpoint_reload does.
        self.scene.camera.release()
        self.tmpdir.cleanup()

    def test_play_frames_are_sampled_mid_interpolation(self):
        scene = self.scene
        chain = scene.animation_checkpoints
        indices = episode_frames.select_frames(chain)
        self.assertEqual(indices, [2, 4])
        self.assertEqual([episode_frames.play_before(chain, index) for index in indices], [1, 3])
        centers = []

        def sampler(variant):
            centers.append((variant, float(scene.mobjects[0].get_center()[0])))
            row = {"serialize_through_rgba_image_ms": 5., "submit_through_full_readback_ms": 2.,
                   "post_readback_ms": .3, "prepare_ms": .5, "render_cpu_encode_ms": .7}
            return row, Image.new("RGBA", (64, 36), (0, 0, 0, 255)), {"resolution": [64, 36]}

        with tempfile.TemporaryDirectory() as tmp:
            report = episode_frames.measure(scene, indices, self.variants, samples=2, warmups=1, sampler=sampler,
                                            output=Path(tmp), report={"variants_in_rotation": list(self.variants)},
                                            play_frames=True)
        first, second = [frame["play"] for frame in report["frames"]]
        fps = scene.camera.fps  # 24 headless, from config

        def expected(run_time):
            # A window of warmups + samples frames centred on the play, the
            # first of them a warmup.
            frames = episode_frames.play_frame_count(fps, run_time)
            start = (frames - 3) // 2
            return frames, [(k + 1) / fps / run_time for k in (start + 1, start + 2)]

        frames, alphas = expected(.2)
        self.assertEqual((first["checkpoint"], first["run_time"], first["frames"]), (1, .2, frames))
        self.assertEqual(first["measured_alphas"], alphas)
        frames, alphas = expected(.3)
        self.assertEqual((second["checkpoint"], second["run_time"], second["frames"]), (3, .3, frames))
        self.assertEqual(second["measured_alphas"], alphas)
        self.assertTrue(all(0 < alpha <= 1 for alpha in first["measured_alphas"] + second["measured_alphas"]))
        self.assertEqual(set(first["variants"]), set(self.variants))
        self.assertEqual(list(second["pixels"]), ["patch_vs_gpu_border"])
        for variant in self.variants:
            rows = report["variants"][variant]["samples"]
            plays = [row for row in rows if row["phase"] == "play"]
            self.assertEqual(len(plays), 4)
            self.assertEqual([row["play_checkpoint"] for row in plays], [1, 1, 3, 3])
            self.assertTrue(all(not row["warmup"] for row in plays))
            self.assertEqual(len([row for row in rows if row["phase"] == "pausepoint"]), 4)
            self.assertEqual(report["variants"][variant]["play_timing_ms"]["prepare_ms"]["n"], 4)
        # The shift's frames saw the square moving: strictly between its
        # ends, further along on the later frame.
        shift = [x for variant, x in centers if variant == "patch_fill"][-3:]
        self.assertTrue(all(0 < x < 1 for x in shift), shift)
        self.assertEqual(shift, sorted(shift))
        self.assertLess(shift[0], shift[-1])
        # The replay leaves its play's checkpoint on screen and the scene
        # skipping again, as the harness found it.
        self.assertEqual(scene.current_animation_index, 3)
        self.assertTrue(scene.skip_animations)
        summary = episode_frames.summary_of(report)
        table = episode_frames.markdown_table(summary)
        self.assertEqual(len(table.splitlines()), 2 + 2 * 2 + 2)
        low, high = first["measured_alphas"][0], first["measured_alphas"][-1]
        self.assertIn(f"play α {low:.2f}–{high:.2f}", table)
        self.assertIn("| all |  |  |  | plays |", table)


if __name__ == "__main__":
    unittest.main()

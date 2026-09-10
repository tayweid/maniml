"""Source-motion contracts without allocating a GPU or building fake glyphs."""

import os
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from benchmarks.renderer_motion import _source_state, build_motion_sequence
from maniml.utils.safe_text_cache import SafeTextCache
from tests.renderer_quality_fixtures import QualityFixtureUnavailable, require_tex_tools


def _point_rows(quality):
    return [(mob, mob.get_points().copy()) for obj in quality.scene.mobjects
            for mob in obj.get_family() if mob.has_points()]


class RendererMotionSources(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            require_tex_tools()
        except QualityFixtureUnavailable as exc:
            raise unittest.SkipTest(str(exc)) from exc
        cls.directory = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.directory.cleanup)
        cache = patch("maniml.utils.cache._cache", SafeTextCache(
            cls.directory.name, size_limit=10_000_000))
        cache.start()
        cls.addClassCleanup(cache.stop)

    def test_camera_motion_keeps_source_geometry_and_returns_to_start(self):
        sequence = build_motion_sequence("perspective_zoom", camera_steps=9)
        sequence.apply(0)
        first = sequence.snapshot(0)
        original = _source_state(first)
        points = _point_rows(first)
        sequence.apply(4)
        middle = sequence.snapshot(4)
        self.assertIs(first.scene, middle.scene)
        self.assertNotEqual(original[3], _source_state(middle)[3])
        for mob, before in points:
            np.testing.assert_array_equal(mob.get_points(), before)
        sequence.apply(8)
        final = _source_state(sequence.snapshot(8))
        self.assertEqual(final[:2], original[:2])
        # Production camera arrays are float32; repeated set_shape calls can
        # round a few ulps while returning to the same requested camera pose.
        for actual, expected in zip(final[2:5], original[2:5]):
            np.testing.assert_allclose(actual, expected, atol=3e-6, rtol=0)
        self.assertEqual(final[5:], original[5:])

    def test_actual_transform_only_changes_selected_source_glyphs(self):
        sequence = build_motion_sequence("tex_transform", animation_steps=5)
        sequence.apply(0)
        first = sequence.snapshot(0)
        before = _point_rows(first)
        original_ids = _source_state(first)[1]
        sequence.apply(4)
        final = sequence.snapshot(4)
        changed = [mob for mob, points in before if not np.array_equal(mob.get_points(), points)]
        self.assertGreater(len(changed), 0)
        self.assertLess(len(changed), len(before)//4)
        self.assertEqual(_source_state(final)[1], original_ids)
        for obj in final.scene.mobjects[1:]:
            self.assertFalse(any(mob in changed for mob in obj.get_family()))
        sequence.finish()

    @unittest.skipUnless(os.environ.get("MANIML_LYON_LIBRARY"), "optional Lyon helper not built")
    def test_fourfold_zoom_crosses_mesh_headroom_without_changing_sources(self):
        from benchmarks.triangle_scene import TriangleMeshCache, prepare_triangle_frame
        from maniml.web.triangle_geometry import LyonFillTessellator
        sequence = build_motion_sequence("tex_zoom_4x", camera_steps=9)
        cache, tessellator = TriangleMeshCache(), LyonFillTessellator()
        regenerations = []
        for index in range(sequence.steps):
            sequence.apply(index)
            quality = sequence.snapshot(index)
            if index == 0:
                source = _source_state(quality)[:2]
            self.assertEqual(_source_state(quality)[:2], source)
            frame = prepare_triangle_frame(quality.scene, tessellator,
                                           mesh_cache=cache, diagnostic=True)
            regenerations.append(frame.mesh_cache_stats["regenerations"])
            if index == sequence.steps//2:
                self.assertEqual(quality.metadata["zoom"], 4)
        self.assertGreater(sum(regenerations[1:5]), 0)
        self.assertEqual(sum(regenerations[5:]), 0)


    def test_actual_write_progresses_with_static_other_text(self):
        sequence = build_motion_sequence("tex_write", animation_steps=5)
        sequence.apply(0)
        first = sequence.snapshot(0)
        moving = first.scene.mobjects[0]
        static = [(mob, mob.get_points().copy()) for obj in first.scene.mobjects[1:]
                  for mob in obj.get_family() if mob.has_points()]
        self.assertTrue(all(np.all(mob.data["fill_rgba"][:, 3] == 0)
                            for mob in moving.get_family() if mob.has_points()))
        original_ids = _source_state(first)[1]
        sequence.apply(4)
        final = sequence.snapshot(4)
        self.assertTrue(any(np.any(mob.data["fill_rgba"][:, 3] > 0)
                            for mob in moving.get_family() if mob.has_points()))
        self.assertEqual(_source_state(final)[1], original_ids)
        for mob, before in static:
            np.testing.assert_array_equal(mob.get_points(), before)
        sequence.finish()

    @unittest.skipUnless(os.environ.get("MANIML_LYON_LIBRARY"), "optional Lyon helper not built")
    def test_opacity_sequence_updates_paint_without_rebuilding_glyphs(self):
        from benchmarks.triangle_scene import TriangleMeshCache, prepare_triangle_frame
        from maniml.web.triangle_geometry import LyonFillTessellator
        sequence = build_motion_sequence("tex_opacity", animation_steps=5)
        cache, tessellator = TriangleMeshCache(), LyonFillTessellator()
        sequence.apply(0)
        first = sequence.snapshot(0)
        points = _point_rows(first)
        prepare_triangle_frame(first.scene, tessellator, mesh_cache=cache, diagnostic=True)
        for index in range(1, sequence.steps):
            sequence.apply(index)
            quality = sequence.snapshot(index)
            frame = prepare_triangle_frame(quality.scene, tessellator, mesh_cache=cache, diagnostic=True)
            self.assertEqual(frame.mesh_cache_stats["regenerations"], 0)
            self.assertGreater(frame.mesh_cache_stats["paint_updates"], 0)
            for mob, before in points:
                np.testing.assert_array_equal(mob.get_points(), before)


class RendererTimingSummary(unittest.TestCase):
    def test_completion_modes_preserve_slow_samples_and_empty_state(self):
        from benchmarks.renderer_timing import completion_distribution
        summary = completion_distribution([1.4, 1.5, 12.7, 12.9])
        self.assertEqual(summary["samples"], 4)
        self.assertEqual(summary["min_ms"], 1.4)
        self.assertEqual(summary["fraction_under_3_ms"], .5)
        self.assertEqual(summary["fraction_over_10_ms"], .5)
        self.assertIsNone(completion_distribution([])["min_ms"])


if __name__ == "__main__":
    unittest.main()

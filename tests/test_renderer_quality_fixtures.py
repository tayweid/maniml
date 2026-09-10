"""CPU contracts for quality inputs, independent of a renderer's output."""

import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from maniml.mobject.types.vectorized_mobject import VMobject
from maniml.utils.safe_text_cache import SafeTextCache
from tests.winding_reference_geometry import parse_geometry_message, serialize_scene
from tests.renderer_quality_fixtures import (
    QualityFixtureUnavailable, RESOLUTION, build_quality_frame,
    quality_cases, quality_sequence, require_tex_tools,
)


def _paths(frame):
    return [mob for obj in frame.scene.mobjects for mob in obj.get_family()
            if isinstance(mob, VMobject) and mob.has_points()]


def _camera_pixels(points, frame):
    """Physical pinhole camera reference, independent of ROI uniform code."""
    local = frame.get_orientation().inv().apply(np.asarray(points) - frame.get_center())
    ratio = frame.get_focal_distance() / (frame.get_focal_distance() - local[:, 2])
    fraction = local[:, :2] * ratio[:, None] / [frame.get_width(), frame.get_height()]
    return (fraction * [1, -1] + 0.5) * RESOLUTION


class QualityFixtureCPU(unittest.TestCase):
    def test_missing_real_tex_tools_fail_without_substitution(self):
        with patch("tests.renderer_quality_fixtures.shutil.which", return_value=None), \
                patch("tests.renderer_quality_fixtures.Tex") as tex:
            with self.assertRaisesRegex(QualityFixtureUnavailable, "latex, dvisvgm"):
                build_quality_frame("tex")
            tex.assert_not_called()

    def test_hairlines_have_distinct_local_crops_and_tiny_holes(self):
        frame = build_quality_frame("hairlines")
        self.assertEqual(len(frame.rois), 4)
        self.assertEqual(len(set(roi.name for roi in frame.rois)), 4)
        hole_paths = frame.scene.mobjects[-3:]
        radii = [min(np.linalg.norm(contour[0] - path.get_center())
                     for contour in path.get_subpaths()) for path in hole_paths]
        self.assertEqual(len(set(radii)), 3)
        self.assertLess(radii[0] * RESOLUTION[1] / frame.scene.camera.frame.get_height(), 1)
        for path in hole_paths:
            self.assertEqual(len(path.get_subpaths()), 2)
        header, _ = parse_geometry_message(serialize_scene(frame.scene))
        self.assertEqual(header["unsupported"], [])

    def test_fractional_camera_motion_preserves_source_geometry(self):
        frames = quality_sequence("hairlines", motion="fractional_translation")
        first = next(frames)
        paths = _paths(first)
        before = [path.get_points().copy() for path in paths]
        reference = _camera_pixels([[0., 0., 0.]], first.scene.camera.frame)
        for frame in frames:
            self.assertIs(frame.scene, first.scene)
            self.assertEqual([id(path) for path in _paths(frame)], [id(path) for path in paths])
            pixels = _camera_pixels([[0., 0., 0.]], frame.scene.camera.frame)
            np.testing.assert_allclose(pixels - reference,
                                       [frame.metadata["pixel_offset"]], atol=2e-5)
            for path, original in zip(paths, before):
                np.testing.assert_array_equal(path.get_points(), original)

    def test_invalid_motion_and_style_are_errors(self):
        with self.assertRaises(ValueError):
            build_quality_frame("hairlines", border_policy="implicit")
        with self.assertRaises(ValueError):
            list(quality_sequence("hairlines", steps=1))
        with self.assertRaises(ValueError):
            list(quality_sequence("hairlines", motion="unknown"))

    def test_translucent_border_fixture_isolates_coverage_combination(self):
        authored = build_quality_frame("border")
        control = build_quality_frame("border", border_policy="zero_for_aa")
        self.assertEqual(len(authored.rois), 5)
        fill = authored.scene.mobjects[-1]
        self.assertTrue(np.all(fill.data["fill_border_width"] == 12))
        np.testing.assert_allclose(fill.data["fill_rgba"][:, 3], 0.4)
        for panel in authored.scene.mobjects[:-1]:
            self.assertTrue(np.all(panel.data["fill_rgba"][:, 3] == 1))
        self.assertFalse(np.array_equal(authored.scene.mobjects[0].data["fill_rgba"][0],
                                       authored.scene.mobjects[1].data["fill_rgba"][0]))
        for source, stripped in zip(_paths(authored), _paths(control)):
            for field in ("point", "fill_rgba", "stroke_rgba", "stroke_width"):
                np.testing.assert_array_equal(source.data[field], stripped.data[field])
        self.assertTrue(authored.diagnostic_limitations)
        self.assertFalse(control.diagnostic_limitations)
        self.assertEqual(set(authored.metadata["semantic_controls"]),
                         {*(roi.name for roi in authored.rois), "alpha"})


class RealTexQualityFixtures(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            require_tex_tools()
        except QualityFixtureUnavailable as exc:
            raise unittest.SkipTest(str(exc)) from exc
        cls.cache_dir = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.cache_dir.cleanup)
        cls.cache_patch = patch("maniml.utils.cache._cache", SafeTextCache(
            cls.cache_dir.name, size_limit=10_000_000))
        cls.cache_patch.start()
        cls.addClassCleanup(cls.cache_patch.stop)
        cls.frames = {case.name: case.build() for case in quality_cases()}

    def test_real_source_fixtures_serialize_and_crops_contain_geometry(self):
        for name, frame in self.frames.items():
            with self.subTest(case=name):
                header, _ = parse_geometry_message(serialize_scene(frame.scene))
                self.assertEqual(header["unsupported"], [])
                self.assertEqual(tuple(header["resolution"]), RESOLUTION)
                self.assertGreater(len(_paths(frame)), 0)
                for roi in frame.rois:
                    left, top, right, bottom = roi.box
                    self.assertTrue(0 <= left < right <= RESOLUTION[0])
                    self.assertTrue(0 <= top < bottom <= RESOLUTION[1])
                    source = frame._regions[roi.name]
                    points = np.concatenate([mob.get_points() for mob in source.get_family()
                                             if mob.has_points()])
                    pixels = _camera_pixels(points, frame.scene.camera.frame)
                    self.assertTrue((pixels.min(axis=0) >= [left, top]).all())
                    self.assertTrue((pixels.max(axis=0) <= [right, bottom]).all())

    def test_default_text_border_and_aa_control_differ_only_in_border(self):
        default = self.frames["tex_normal_production_default"]
        isolated = self.frames["tex_normal_zero_for_aa"]
        self.assertTrue(default.diagnostic_limitations)
        self.assertFalse(isolated.diagnostic_limitations)
        self.assertGreater(len(_paths(default)), 60)  # Real multi-glyph paragraph/math.
        for normal, control in zip(_paths(default), _paths(isolated)):
            for name in ("point", "fill_rgba", "stroke_rgba", "stroke_width"):
                np.testing.assert_array_equal(normal.data[name], control.data[name])
            self.assertTrue(np.all(normal.data["fill_border_width"] == 0.5))
            self.assertTrue(np.all(control.data["fill_border_width"] == 0))

    def test_zoom_changes_projection_without_changing_source_or_styles(self):
        normal = self.frames["tex_normal_production_default"]
        zoom = self.frames["tex_zoom_production_default"]
        self.assertEqual(normal.metadata["source_sha256"], zoom.metadata["source_sha256"])
        for small, large in zip(normal.rois, zoom.rois):
            small_width = small.box[2] - small.box[0]
            large_width = large.box[2] - large.box[0]
            self.assertGreater(large_width, 1.8 * small_width)
        sequence = quality_sequence("tex", steps=5)
        sources = []
        zooms = []
        for frame in sequence:
            sources.append(frame.metadata["source_sha256"])
            zooms.append(frame.metadata["zoom"])
        self.assertEqual(len(set(sources)), 1)
        self.assertEqual(zooms[0], zooms[-1])
        self.assertEqual(max(zooms), 2)

    def test_perspective_uses_equal_source_sizes_at_distinct_depths(self):
        frame = self.frames["perspective_normal_production_default"]
        far, near, tilted = frame.scene.mobjects
        np.testing.assert_allclose(far.get_width(), near.get_width(), atol=1e-6)
        np.testing.assert_allclose(far.get_height(), near.get_height(), atol=1e-6)
        self.assertLess(far.get_center()[2], near.get_center()[2])
        self.assertGreater(tilted.get_depth(), 0.5)
        crops = {roi.name: roi.box for roi in frame.rois}
        self.assertGreater(crops["near"][3] - crops["near"][1],
                           crops["far"][3] - crops["far"][1])
        self.assertFalse(any(path.depth_test for path in _paths(frame)))


if __name__ == "__main__":
    unittest.main()

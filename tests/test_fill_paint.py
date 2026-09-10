"""Independent source-space paint checks; no coverage or mesh implementation oracle."""

import unittest
import os
from unittest.mock import patch

import numpy as np
from scipy.interpolate import RBFInterpolator

from maniml.web.fill_paint import build_paint, evaluate_paint, PAINT_EPSILON
from maniml.web.triangle_geometry import TessellationError, TessellationLimitError, _packaged_library


class FillPaint(unittest.TestCase):
    def setUp(self):
        self.points = np.array([[-1., -1., 0], [1., -1., 0], [1., 1., 0],
                                [-1., 1., 0], [0., 0., 0]])
        self.colors = np.array([[1., 0, 0, .2], [0, 1., 0, .4], [0, 0, 1., .8],
                                [1., 1., 0, 1.], [.2, .4, .6, .7]])

    def test_affine_field_is_exact_at_interior_and_outside_samples(self):
        colors = np.column_stack((.5 + self.points[:, 0] / 4,
                                  .5 + self.points[:, 1] / 4,
                                  np.full(5, .2), np.full(5, .6)))
        field = build_paint(self.points, colors)
        self.assertEqual(len(field.data), 6)
        probes = np.array([[.25, -.75, 0], [1.5, 1.5, 0], [0, 0, 0]])
        expected = np.column_stack((.5 + probes[:, 0] / 4, .5 + probes[:, 1] / 4,
                                    np.full(3, .2), np.full(3, .6)))
        np.testing.assert_allclose(evaluate_paint(field, probes), expected, atol=2e-7)

    def test_nonaffine_matches_independent_scipy_spline(self):
        field = build_paint(self.points, self.colors)
        self.assertEqual(field.data[2, 3], 0)
        probes = np.random.default_rng(91).uniform(-1, 1, (71, 3))
        probes[:, 2] = 0
        reference = RBFInterpolator(self.points[:, :2], self.colors,
                                    kernel="thin_plate_spline", degree=1)
        np.testing.assert_allclose(evaluate_paint(field, probes),
                                   np.clip(reference(probes[:, :2]), 0, 1), atol=3e-6)
        np.testing.assert_allclose(evaluate_paint(field, self.points), self.colors,
                                   atol=PAINT_EPSILON)

    def test_affine_transform_preserves_paint_under_rigid_motion_and_scale(self):
        from scipy.spatial.transform import Rotation
        transform = Rotation.from_euler("xyz", [17, 43, -21], degrees=True).as_matrix()
        original = build_paint(self.points, self.colors)
        moved_points = self.points @ transform.T * 2.7 + [3, -2, 1]
        moved = build_paint(moved_points, self.colors)
        probes = np.array([[.2, -.3, 0], [-.7, .4, 0], [.8, .1, 0]])
        np.testing.assert_allclose(evaluate_paint(original, probes),
                                   evaluate_paint(moved, probes @ transform.T * 2.7 + [3, -2, 1]),
                                   atol=3e-6)

    def test_duplicate_positions_have_one_deterministic_mean(self):
        points = np.concatenate((self.points, self.points[:1]))
        colors = np.concatenate((self.colors, [[0., 0, 1., .8]]))
        field = build_paint(points, colors)
        np.testing.assert_allclose(evaluate_paint(field, points[:1]), [[.5, 0, .5, .5]], atol=2e-6)
        order = np.array([5, 3, 1, 4, 0, 2])
        reordered = build_paint(points[order], colors[order])
        np.testing.assert_allclose(evaluate_paint(reordered, points), evaluate_paint(field, points), atol=2e-6)

    def test_positive_fallback_preserves_samples_and_color_range(self):
        with patch("maniml.web.fill_paint.MAX_SPLINE_SAMPLES", 3):
            field = build_paint(self.points, self.colors)
        self.assertEqual(field.data[2, 3], 1)
        np.testing.assert_allclose(evaluate_paint(field, self.points), self.colors, atol=2e-6)
        probes = np.random.default_rng(4).uniform(-20, 20, (500, 3))
        values = evaluate_paint(field, probes)
        self.assertTrue(np.isfinite(values).all())
        self.assertTrue((values >= self.colors.min(axis=0) - 1e-6).all())
        self.assertTrue((values <= self.colors.max(axis=0) + 1e-6).all())

    def test_source_and_output_are_immutable_and_invalid_input_is_bounded(self):
        points, colors = self.points.copy(), self.colors.copy()
        field = build_paint(points, colors)
        with self.assertRaises(ValueError):
            field.data.setflags(write=True)
        np.testing.assert_array_equal(points, self.points)
        np.testing.assert_array_equal(colors, self.colors)
        for p, c in ((points, colors[:1]), (points * np.nan, colors), (points, np.full_like(colors, np.inf))):
            with self.subTest(), self.assertRaises(TessellationError):
                build_paint(p, c)
        with patch("maniml.web.fill_paint.MAX_PAINT_SAMPLES", 3), self.assertRaises(TessellationLimitError):
            build_paint(points, colors)


@unittest.skipUnless(os.environ.get("MANIML_LYON_LIBRARY") or _packaged_library(), "Lyon helper unavailable")
class FillPaintScene(unittest.TestCase):
    def test_paint_refresh_reuses_connectivity_and_refinement_preserves_field(self):
        from maniml.mobject.geometry import Circle
        from maniml.web.triangle_geometry import LyonFillTessellator
        from maniml.web.triangle_scene import TriangleMeshCache, prepare_triangle_frame
        from tests.renderer_fixtures import build_scene
        shape = Circle(fill_opacity=1, stroke_width=0, fill_border_width=0)
        points = shape.get_points().copy()
        shape.data["fill_rgba"][:, 0] = .5 + .2 * points[:, 0]
        shape.data["fill_rgba"][:, 1] = .5 + .2 * points[:, 1]
        scene, tessellator, cache = build_scene(shape), LyonFillTessellator(), TriangleMeshCache()
        def frame():
            return prepare_triangle_frame(scene, tessellator, mesh_cache=cache)
        before = frame().draws[0]
        self.assertEqual(before.pipeline, "paint")
        shape.data["fill_rgba"][:, 3] = .3
        with patch("maniml.web.triangle_scene._generate_mesh", side_effect=AssertionError("paint rebuilt mesh")):
            after = frame().draws[0]
        self.assertIs(before.indices, after.indices)
        self.assertNotEqual(before.paint, after.paint)
        self.assertEqual(cache.stats["paint_updates"], 1)
        scene.camera.frame.scale(.1)
        refined = frame().draws[0]
        self.assertGreater(len(refined.indices), len(after.indices))
        np.testing.assert_array_equal(refined.paint, after.paint)
        np.testing.assert_array_equal(shape.get_points(), points)

    def test_lighting_uses_fragment_material_without_source_or_topology_changes(self):
        from maniml.mobject.geometry import Square
        from maniml.web.triangle_geometry import LyonFillTessellator
        from maniml.web.triangle_scene import TriangleMeshCache, prepare_triangle_frame
        from tests.renderer_fixtures import build_scene
        shape = Square(fill_opacity=1, stroke_width=0, fill_border_width=0)
        scene, cache, tessellator = build_scene(shape), TriangleMeshCache(), LyonFillTessellator()
        first = prepare_triangle_frame(scene, tessellator, mesh_cache=cache).draws[0]
        shape.set_shading(.2, .3, .4)
        second = prepare_triangle_frame(scene, tessellator, mesh_cache=cache).draws[0]
        self.assertEqual(second.pipeline, "paint")
        self.assertEqual(second.uniforms["shading"], [.2, .3, .4])
        self.assertIs(first.indices, second.indices)
        self.assertEqual(len(second.paint), 24)

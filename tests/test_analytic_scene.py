"""CPU validation of analytic scene ordering, capability gates and retention."""

import unittest

import numpy as np

from benchmarks.analytic_geometry import PATCH_DTYPE
from benchmarks.analytic_scene import AnalyticMeshCache, prepare_analytic_frame
from benchmarks.triangle_scene import TriangleMeshCache, UnsupportedPrototype, prepare_triangle_frame
from maniml.mobject.geometry import Circle
from maniml.mobject.types.vectorized_mobject import VMobject
from tests.renderer_fixtures import build_scene, get_fixture


def circle(**kwargs):
    return Circle(fill_opacity=1, stroke_width=0, fill_border_width=0, **kwargs)


class AnalyticSceneTests(unittest.TestCase):
    def test_one_fill_draw_combines_interior_and_patches_without_source_edits(self):
        scene = get_fixture("curved_fill").build()
        source = scene.mobjects[0].get_points().copy()
        frame = prepare_analytic_frame(scene)
        self.assertEqual(len(frame.draws), 1)
        draw = frame.draws[0]
        self.assertEqual(draw.pipeline, "analytic")
        self.assertEqual(draw.vertices.dtype, PATCH_DTYPE)
        self.assertIsNone(draw.indices)
        self.assertEqual(draw.count, len(draw.vertices))
        self.assertEqual(draw.count % 3, 0)
        self.assertTrue(np.any(draw.vertices["fill_side"] == 0))
        self.assertTrue(np.any(draw.vertices["fill_side"] != 0))
        np.testing.assert_array_equal(scene.mobjects[0].get_points(), source)

    def test_fill_stroke_order_and_depth_remain_per_object(self):
        front = circle().set_stroke(width=3).set_z_index(2)
        back = circle().set_stroke(width=3).set_z_index(-1)
        back.stroke_behind = True
        back.depth_test = True
        frame = prepare_analytic_frame(build_scene(front, back))
        self.assertEqual([draw.pipeline for draw in frame.draws],
                         ["stroke_depth", "analytic_depth", "analytic", "stroke"])

    def test_gradient_lighting_and_border_gates_are_not_bypassed_by_callback(self):
        for diagnostic in (False, True):
            with self.subTest(diagnostic=diagnostic), self.assertRaises(UnsupportedPrototype):
                prepare_analytic_frame(get_fixture("gradient_curve").build(), diagnostic=diagnostic)
            lit = circle()
            lit.uniforms["shading"] = [1., 0., 0.]
            with self.assertRaises(UnsupportedPrototype):
                prepare_analytic_frame(build_scene(lit), diagnostic=diagnostic)
        bordered = get_fixture("fill_border_wide").build()
        with self.assertRaisesRegex(UnsupportedPrototype, "fill-border"):
            prepare_analytic_frame(bordered)
        diagnostic = prepare_analytic_frame(bordered, diagnostic=True)
        self.assertTrue(any("fill-border" in message for message in diagnostic.limitations))

    def test_cache_reuses_camera_frames_but_rebuilds_changed_source_and_paint(self):
        mob = circle()
        scene = build_scene(mob)
        cache = AnalyticMeshCache()
        first = prepare_analytic_frame(scene, cache=cache)
        self.assertEqual(first.mesh_cache_stats["regenerations"], 1)
        for scale, offset in ((.5, [.2, -.3, 0]), (2., [0, 0, 0])):
            scene.camera.frame.scale(scale).move_to(offset)
            frame = prepare_analytic_frame(scene, cache=cache)
            self.assertEqual(frame.mesh_cache_stats["hits"], 1)
            self.assertEqual(frame.mesh_cache_stats["regenerations"], 0)
            self.assertIs(frame.draws[0].vertices, first.draws[0].vertices)
        # Bypass the revision machinery: actual array changes must invalidate.
        mob.data["point"][:, 0] *= 1.125
        changed = prepare_analytic_frame(scene, cache=cache)
        self.assertEqual(changed.mesh_cache_stats["regenerations"], 1)
        self.assertIsNot(changed.draws[0].vertices, first.draws[0].vertices)
        mob.data["fill_rgba"][:, 3] = .5
        painted = prepare_analytic_frame(scene, cache=cache)
        self.assertEqual(painted.mesh_cache_stats["regenerations"], 1)
        np.testing.assert_allclose(painted.draws[0].vertices["rgba"][:, 3], .5)
        self.assertFalse(painted.draws[0].vertices.flags.writeable)
        with self.assertRaises(ValueError):
            painted.draws[0].vertices.setflags(write=True)

    def test_cache_bounds_and_removal_release_retained_arrays(self):
        scene = build_scene(circle(), circle().shift([3, 0, 0]))
        cache = AnalyticMeshCache(max_entries=1)
        frame = prepare_analytic_frame(scene, cache=cache)
        self.assertEqual(len(frame.draws), 2)
        self.assertEqual(cache.stats["entries"], 1)
        self.assertLessEqual(cache.stats["retained_bytes"], cache.max_bytes)
        prepare_analytic_frame(build_scene(), cache=cache)
        self.assertEqual(cache.stats["entries"], 0)
        self.assertEqual(cache.stats["retained_bytes"], 0)
        small = AnalyticMeshCache(max_bytes=1)
        frame = prepare_analytic_frame(scene, cache=small)
        self.assertEqual(len(frame.draws), 2)
        self.assertEqual(small.stats["retained_bytes"], 0)

    def test_projection_failure_never_returns_or_retains_stale_cache(self):
        scene = build_scene(circle())
        cache = AnalyticMeshCache()
        prepare_analytic_frame(scene, cache=cache)
        scene.camera.frame.move_to([0, 0, -100])
        with self.assertRaisesRegex(UnsupportedPrototype, "projection"):
            prepare_analytic_frame(scene, cache=cache)
        self.assertEqual(cache.stats["entries"], 0)
        self.assertEqual(cache.stats["retained_bytes"], 0)

    def test_zoom_rechecks_small_plane_fit_error_before_reusing_a_mesh(self):
        mob = circle()
        mob.data["point"][1, 2] = 1e-8
        scene, cache = build_scene(mob), AnalyticMeshCache()
        prepare_analytic_frame(scene, cache=cache)
        scene.camera.frame.scale(1e-6)
        with self.assertRaisesRegex(UnsupportedPrototype, "pixel error budget"):
            prepare_analytic_frame(scene, cache=cache)
        self.assertEqual(cache.stats["entries"], 0)

    def test_zoom_rechecks_reported_numerical_curve_error(self):
        height = 2.**-44
        xy = np.array([[0., -1], [.5, -1], [1, -1], [1, -.5], [1, 0],
                       [.5, height], [0, 0], [0, -.5], [0, -1]])
        mob = VMobject(fill_opacity=1, stroke_width=0, fill_border_width=0)
        mob.set_points(np.column_stack((xy, np.zeros(len(xy)))))
        scene, cache = build_scene(mob), AnalyticMeshCache()
        prepare_analytic_frame(scene, cache=cache)
        entry = next(iter(cache._entries.values()))
        self.assertGreater(entry.geometry.linearization_displacement, 0)
        scene.camera.frame.scale(1e-12)
        with self.assertRaisesRegex(UnsupportedPrototype, "error budget"):
            prepare_analytic_frame(scene, cache=cache)
        self.assertEqual(cache.stats["entries"], 0)

    def test_unsupported_geometry_does_not_silently_draw_partial_scene(self):
        repeated = get_fixture("repeated_winding").build().mobjects[0]
        scene, cache = build_scene(circle(), repeated), AnalyticMeshCache()
        with self.assertRaisesRegex(UnsupportedPrototype, "analytic geometry"):
            prepare_analytic_frame(scene, diagnostic=True, cache=cache)
        self.assertEqual(cache.stats["entries"], 0)

    def test_shared_callback_cannot_accidentally_use_flattening_cache(self):
        with self.assertRaisesRegex(ValueError, "mutually exclusive"):
            prepare_triangle_frame(build_scene(), None, mesh_cache=TriangleMeshCache(),
                                   fill_builder=lambda *_: None)
        for value in (0, -1, np.nan, np.inf):
            with self.assertRaises(ValueError):
                prepare_analytic_frame(build_scene(), pixel_tolerance=value)
        with self.assertRaises(TypeError):
            prepare_analytic_frame(build_scene(), cache=TriangleMeshCache())


if __name__ == "__main__":
    unittest.main()

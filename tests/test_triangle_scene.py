"""CPU checks for the opt-in source-to-triangle scene preparation experiment.

Camera tests use a geometric pinhole projection as an independent reference.
Native cases validate covered regions and source/draw semantics, not a specific
tessellator's vertex order or the production renderer's batching decisions.
"""

import os
import unittest
from unittest.mock import Mock, patch

import numpy as np

from benchmarks.triangle_scene import (
    TriangleDraw,
    TriangleMeshCache,
    UnsupportedPrototype,
    coalesce_draws,
    planar_coordinates,
    plane_tolerance,
    prepare_triangle_frame,
    projection_scale_bound,
    projection_matrix,
    world_to_pixel,
)
from maniml.constants import BLUE, GREEN, RED, WHITE, YELLOW
from maniml.mobject.geometry import Circle, Square
from maniml.mobject.types.vectorized_mobject import VMobject
from maniml.utils.color import color_to_rgb
from maniml.web.triangle_geometry import LyonFillTessellator, _packaged_library
from maniml.web.geometry import SURFACE_DTYPE
from tests.renderer_fixtures import (
    build_scene, closed_contours, concave_quad, get_fixture, renderer_cases,
)


def _camera_pixels(points, camera):
    """Project using camera pose, physical frame dimensions, and focal length."""
    frame = camera.frame
    local = frame.get_orientation().inv().apply(np.asarray(points) - frame.get_center())
    perspective = frame.get_focal_distance() / (frame.get_focal_distance() - local[:, 2])
    fraction = local[:, :2] * perspective[:, None] / [frame.get_width(), frame.get_height()]
    return (fraction * [1, -1] + 0.5) * camera.draw_fbo.size


def _quadratic(points, t):
    t = np.asarray(t)[:, None]
    return (1 - t) ** 2 * points[0] + 2 * (1 - t) * t * points[1] + t ** 2 * points[2]


def _covered(draw, samples):
    """Inclusive geometric coverage; samples can lie on internal mesh edges."""
    triangles = draw.vertices["point"][draw.indices.reshape(-1, 3), :2].astype(float)
    covered = np.zeros(len(samples), dtype=bool)
    for triangle in triangles:
        delta = np.roll(triangle, -1, axis=0) - triangle
        relative = np.asarray(samples)[:, None, :] - triangle
        cross = (delta[None, :, 0] * relative[:, :, 1]
                 - delta[None, :, 1] * relative[:, :, 0])
        # Ignore zero-area triangles: an entirely collapsed triangle must not
        # classify every point along its supporting line as covered.
        ab, ac = triangle[1] - triangle[0], triangle[2] - triangle[0]
        area = ab[0] * ac[1] - ab[1] * ac[0]
        if abs(float(area)) > 1e-10:
            covered |= (cross >= -1e-6).all(axis=1) | (cross <= 1e-6).all(axis=1)
    return covered


def _area(draw):
    triangles = draw.vertices["point"][draw.indices.reshape(-1, 3)].astype(float)
    return float(np.linalg.norm(np.cross(triangles[:, 1] - triangles[:, 0],
                                         triangles[:, 2] - triangles[:, 0]), axis=1).sum() / 2)


def _max_boundary_error(path, draw, camera):
    """Dense exact quadratic samples versus the mesh's projected outer edges."""
    triangles = draw.indices.reshape(-1, 3)
    edges = np.sort(np.concatenate((triangles[:, [0, 1]], triangles[:, [1, 2]],
                                    triangles[:, [2, 0]])), axis=1)
    edges, counts = np.unique(edges, axis=0, return_counts=True)
    projected = _camera_pixels(draw.vertices["point"], camera)[edges[counts == 1]]
    points = path.get_points()
    samples = np.concatenate([_quadratic(points[index:index + 3], np.linspace(0, 1, 65))
                              for index in range(0, len(points) - 2, 2)])
    samples = _camera_pixels(samples, camera)
    start, delta = projected[:, 0], projected[:, 1] - projected[:, 0]
    nonzero = np.sum(delta * delta, axis=-1) > 1e-18
    start, delta = start[nonzero], delta[nonzero]
    relative = samples[:, None, :] - start
    t = np.clip(np.sum(relative * delta, axis=-1) / np.sum(delta * delta, axis=-1), 0, 1)
    distance = np.linalg.norm(relative - t[..., None] * delta, axis=-1)
    return float(distance.min(axis=1).max())


class TriangleProjectionReuse(unittest.TestCase):
    def test_contour_reuse_requires_exact_points_and_the_same_builtin_rule(self):
        from maniml.web.triangle_scene import _MeshSource
        path = Circle()
        first = _MeshSource.read(path).frozen()
        same = _MeshSource.read(path, previous=first)
        self.assertIs(same.points, first.points)
        self.assertIs(same.ends, first.ends)
        path.data["point"][1, 0] += .125  # Deliberately no revision notification.
        changed = _MeshSource.read(path, previous=first)
        self.assertIsNot(changed.points, first.points)
        np.testing.assert_array_equal(changed.points, path.get_points())
        # A custom rule must be evaluated even if the point values match.
        with patch.object(path, "get_subpath_end_indices_from_points",
                          return_value=np.array([2])) as custom:
            overridden = _MeshSource.read(path, previous=changed).frozen()
            _MeshSource.read(path, previous=overridden)
            self.assertEqual(custom.call_count, 2)
        restored = _MeshSource.read(path, previous=overridden)
        np.testing.assert_array_equal(restored.ends,
                                      path.get_subpath_end_indices_from_points(path.get_points()))

    def test_shared_hull_bounds_charge_both_plane_fit_and_flattening(self):
        from types import SimpleNamespace
        from maniml.web.triangle_scene import _MeshGeometry, planar_projection_error
        scene = build_scene(resolution=(960, 540))
        points = np.array([[-1.3, -.4, 0], [.2, .7, 0], [1.4, -.3, 0]])
        basis = np.eye(3)[:2]
        bases = np.zeros((2, 3, 3))
        bases[0, :2], bases[1] = basis, np.eye(3)
        for angle in (0, 27, 64):
            for residual in (1e-15, 1e-7):
                scene.camera.frame.reorient(13, angle, 7)
                scene.camera.refresh_uniforms()
                source_points = points + [[0, 0, residual], [0, 0, -residual], [0, 0, 0]]
                source = SimpleNamespace(points=source_points, border_settings=(0, "bevel"))
                geometry = _MeshGeometry(np.empty(0), np.empty(0), points, basis, .001,
                                         residual, np.concatenate([source_points, points]), bases)
                uniforms, resolution = scene.camera.uniforms, scene.camera.draw_fbo.size
                separate = (planar_projection_error(source_points, points, uniforms, resolution)
                            + .001 * projection_scale_bound(points, basis, uniforms, resolution))
                shared = geometry.pixel_error(source, uniforms, resolution)
                self.assertGreaterEqual(shared + 1e-12, separate)
                self.assertLess(shared, separate * 1.00001 + 1e-12)

    def test_projection_scratch_keys_actual_camera_values_and_supports_nested_views(self):
        from maniml.web.triangle_scene import _projection_state
        scene = build_scene()
        scene.camera.refresh_uniforms()
        uniforms = {**scene.camera.uniforms, "view": list(scene.camera.uniforms["view"])}
        scratch = {}
        first = _projection_state(uniforms, (960, 540), scratch)
        self.assertIs(_projection_state(uniforms, (960, 540), scratch), first)
        uniforms["view"][12] += .125
        changed = _projection_state(uniforms, (960, 540), scratch)
        self.assertNotEqual(first[0], changed[0])
        uniforms["view"] = np.asarray(uniforms["view"]).reshape(4, 4).tolist()
        nested = _projection_state(uniforms, (960, 540), scratch)
        self.assertEqual(changed[0], nested[0])


class TriangleDrawCoalescing(unittest.TestCase):
    def fill(self, position, *, pipeline="surface", uniforms=None):
        vertices = np.zeros(3, dtype=SURFACE_DTYPE)
        vertices["point"] = [[position, 0, 0], [position + 1, 0, 0], [position, 1, 0]]
        vertices["rgba"] = [position / 10, 0.5, 0.8, 0.4]
        return TriangleDraw(pipeline, vertices, uniforms or {"shading": [0, 0, 0]},
                            np.array([0, 1, 2], dtype="u4"), 3)

    def test_indexed_merge_preserves_order_and_every_vertex_attribute(self):
        draws = [self.fill(index) for index in (3, 1, 2)]
        original = [draw.vertices.copy() for draw in draws]
        combined, = coalesce_draws(draws)
        np.testing.assert_array_equal(combined.vertices[combined.indices],
                                      np.concatenate([draw.vertices[draw.indices] for draw in draws]))
        self.assertEqual(combined.count, 9)
        combined.vertices["point"][:] = 99
        for draw, before in zip(draws, original):
            np.testing.assert_array_equal(draw.vertices, before)

    def test_stroke_runs_use_maximum_strip_count_and_preserve_curve_instances(self):
        short = np.zeros(6, dtype=VMobject.data_dtype)
        long = np.zeros(3, dtype=VMobject.data_dtype)
        short["point"] = np.arange(18).reshape(6, 3)
        long["point"] = -np.arange(9).reshape(3, 3)
        draws = [TriangleDraw("stroke", short, {}, count=4, instances=2),
                 TriangleDraw("stroke", long, {}, count=32, instances=1)]
        combined, = coalesce_draws(draws)
        self.assertEqual((combined.count, combined.instances), (32, 3))
        np.testing.assert_array_equal(combined.vertices, np.concatenate([short, long]))

    def test_fill_stroke_depth_uniform_and_partial_ranges_are_order_barriers(self):
        fill = self.fill(0)
        stroke = TriangleDraw("stroke", np.zeros(3, dtype=VMobject.data_dtype), {}, count=4)
        depth = self.fill(1, pipeline="surface_depth")
        lit = self.fill(2, uniforms={"shading": [0.5, 0, 0]})
        partial = self.fill(3)
        partial.count = 0
        draws = [fill, stroke, fill, depth, lit, fill, partial, fill]
        result = coalesce_draws(draws)
        self.assertEqual(len(result), len(draws))
        for actual, expected in zip(result, draws):
            self.assertIs(actual, expected)


class TriangleSceneCoordinates(unittest.TestCase):
    def test_rotated_plane_roundtrips_without_flattening_world_z(self):
        path = get_fixture("rotated_plane").build().mobjects[0]
        source = path.get_points().copy()
        xy, origin, basis, normal = planar_coordinates(source)
        np.testing.assert_allclose(xy @ basis + origin, source, atol=1e-12)
        np.testing.assert_allclose(basis @ basis.T, np.eye(2), atol=1e-12)
        np.testing.assert_allclose((source - origin) @ normal, 0, atol=1e-12)
        self.assertGreater(np.ptp(source[:, 2]), 0.5)
        np.testing.assert_array_equal(path.get_points(), source)

    def test_projection_matches_camera_pose_and_preserves_fixed_frame(self):
        scene = build_scene(resolution=(768, 432))
        camera = scene.camera
        camera.frame.shift([0.4, -0.3, 0.1]).scale(0.8).reorient(23, 31, -12)
        camera.refresh_uniforms()
        points = np.array([[-1.3, 0.4, 0.2], [0.2, -0.8, 0.7], [1.1, 1.4, -0.3]])
        np.testing.assert_allclose(
            world_to_pixel(points, camera.uniforms, camera.draw_fbo.size),
            _camera_pixels(points, camera), atol=2e-5,
        )
        fixed = {**camera.uniforms, "is_fixed_in_frame": 1.0}
        before = world_to_pixel(points, fixed, camera.draw_fbo.size)
        camera.frame.shift([2, -1, 0]).reorient(-35, 45, 19)
        camera.refresh_uniforms()
        after = world_to_pixel(points, {**camera.uniforms, "is_fixed_in_frame": 1.0},
                               camera.draw_fbo.size)
        np.testing.assert_array_equal(before, after)

    def test_plane_tolerance_bounds_projected_curve_error(self):
        scene = build_scene(resolution=(768, 432))
        scene.camera.frame.shift([0.3, -0.2, 0]).reorient(28, 39, 7)
        scene.camera.refresh_uniforms()
        # A non-axis-aligned plane viewed through the actual perspective camera.
        basis0 = np.array([[1, 0, 0], [0, np.cos(0.7), np.sin(0.7)]])
        points = np.array([[-1.4, -0.4], [0.2, 1.8], [1.1, -0.3]]) @ basis0
        xy, origin, basis, _ = planar_coordinates(points)
        pixel_tolerance = 0.25
        tolerance = plane_tolerance(points, basis, scene.camera.uniforms,
                                    scene.camera.draw_fbo.size, pixel_tolerance)
        second_difference = np.linalg.norm(xy[0] - 2 * xy[1] + xy[2])
        segments = max(1, int(np.ceil(np.sqrt(second_difference / (4 * tolerance)))))
        ts = np.linspace(0, 1, 2049)
        left = np.minimum(np.floor(ts * segments).astype(int), segments - 1)
        fraction = ts * segments - left
        chord = ((1 - fraction[:, None]) * _quadratic(xy, left / segments)
                 + fraction[:, None] * _quadratic(xy, (left + 1) / segments))
        exact_pixels = _camera_pixels(_quadratic(points, ts), scene.camera)
        chord_pixels = _camera_pixels(chord @ basis + origin, scene.camera)
        error = np.linalg.norm(exact_pixels - chord_pixels, axis=1)
        self.assertLessEqual(float(error.max()), pixel_tolerance + 1e-6)

    def test_nonplanar_and_singular_inputs_are_explicitly_rejected(self):
        with self.assertRaisesRegex(UnsupportedPrototype, "nonplanar"):
            planar_coordinates(np.array([[0., 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1]]))
        scene = build_scene()
        scene.camera.refresh_uniforms()
        points = np.array([[0., 0, 2 * scene.camera.frame.get_focal_distance()]])
        with self.assertRaisesRegex(UnsupportedPrototype, "singularity"):
            world_to_pixel(points, scene.camera.uniforms, scene.camera.draw_fbo.size)


class TriangleSceneCapabilityGate(unittest.TestCase):
    def test_invalid_quality_is_rejected_even_without_fills_or_with_a_cache(self):
        for tolerance in (0, -1, np.inf, np.nan):
            with self.subTest(tolerance=tolerance):
                generator = Mock()
                with self.assertRaisesRegex(ValueError, "finite and positive"):
                    prepare_triangle_frame(build_scene(), generator,
                                           pixel_tolerance=tolerance,
                                           mesh_cache=TriangleMeshCache())
                generator.tessellate.assert_not_called()

    def test_cache_limits_and_refinement_factor_are_explicit(self):
        for kwargs in ({"max_bytes": -1}, {"max_entries": 1.5}, {"max_entries": True},
                       {"refinement_factor": 0}, {"refinement_factor": 1.1},
                       {"refinement_factor": np.nan}):
            with self.subTest(options=kwargs), self.assertRaises(ValueError):
                TriangleMeshCache(**kwargs)

    def test_diagnostic_candidates_cannot_bypass_paint_and_border_contracts(self):
        for name, message in (("gradient_curve", "per-point fill"),
                              ("fill_border_wide", "fill-border")):
            with self.subTest(fixture=name):
                tessellator = Mock()
                with self.assertRaisesRegex(UnsupportedPrototype, message):
                    prepare_triangle_frame(get_fixture(name).build(), tessellator, fill_builder=Mock())
                tessellator.tessellate.assert_not_called()

    def test_diagnostic_candidate_without_material_support_rejects_lighting(self):
        path = Square(fill_opacity=1, stroke_width=0)
        path.set_shading(0.2, 0.3, 0.4)
        tessellator = Mock()
        with self.assertRaises(UnsupportedPrototype):
            prepare_triangle_frame(build_scene(path), tessellator, fill_builder=Mock())
        tessellator.tessellate.assert_not_called()


@unittest.skipUnless(os.environ.get("MANIML_LYON_LIBRARY") or _packaged_library(),
                     "Lyon helper is neither packaged nor explicitly built")
class TriangleSceneMeshes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tessellator = LyonFillTessellator()

    def test_disappearing_fill_has_no_geometry(self):
        for points in (np.empty((0, 3)), np.zeros((1, 3)), np.zeros((5, 3))):
            with self.subTest(source_points=len(points)):
                path = VMobject(fill_opacity=1, stroke_width=0)
                path.set_points(points)
                frame = prepare_triangle_frame(build_scene(path), self.tessellator)
                self.assertEqual(frame.draws, [])
                self.assertEqual(frame.limitations, [])

    def test_visible_plane_fit_residual_cannot_spend_the_curve_error_budget(self):
        path = closed_contours([
            (-1e-5, -1e-5, 0), (1e-5, -1e-5, 0),
            (1e-5, 1e-5, 0), (-1e-5, 1e-5, 1e-7),
        ])
        scene = build_scene(path, resolution=(768, 432))
        scene.camera.frame.scale(1e-5).reorient(25, 35, 5)
        scene.camera.refresh_uniforms()
        points = path.get_points().copy()
        xy, origin, basis, _ = planar_coordinates(points)
        # The old world-space plane threshold accepts this source, and the
        # perspective map is well-defined, but its fitted plane is visibly wrong.
        world_to_pixel(points, scene.camera.uniforms, scene.camera.draw_fbo.size)
        error = np.linalg.norm(_camera_pixels(points, scene.camera)
                               - _camera_pixels(xy @ basis + origin, scene.camera), axis=1)
        self.assertGreater(float(error.max()), 0.01)
        with self.assertRaises(UnsupportedPrototype):
            prepare_triangle_frame(scene, self.tessellator, pixel_tolerance=0.01)

    def test_source_frame_corpus_prepares_and_matches_coverage_probes(self):
        for case in renderer_cases():
            if case.name in ("gradient_curve", "fill_border_wide"):
                continue
            with self.subTest(fixture=case.name):
                frame = prepare_triangle_frame(case.build(), self.tessellator)
                self.assertEqual(frame.limitations, [])
                for draw in frame.draws:
                    self.assertTrue(np.isfinite(draw.vertices["point"]).all())
                    if draw.indices is not None and draw.indices.size:
                        self.assertLess(int(draw.indices.max()), len(draw.vertices))
                if case.probes:
                    fills = [draw for draw in frame.draws if draw.indices is not None]
                    coverage = np.zeros(len(case.probes), dtype=bool)
                    for draw in fills:
                        coverage |= _covered(draw, [probe.point for probe in case.probes])
                    np.testing.assert_array_equal(coverage, [probe.covered for probe in case.probes])

    def test_preparation_and_mesh_edits_do_not_mutate_source_points_or_styles(self):
        scene = get_fixture("stroke_behind_overlap").build()
        columns = ("point", "fill_rgba", "stroke_rgba", "stroke_width", "fill_border_width")
        snapshots = [{name: mob.data[name].copy() for name in columns} for mob in scene.mobjects]
        frame = prepare_triangle_frame(scene, self.tessellator)
        for draw in frame.draws:
            draw.vertices["point"][:] = 999
            if draw.indices is not None:
                draw.indices[:] = 0
        for mob, snapshot in zip(scene.mobjects, snapshots):
            for name in columns:
                np.testing.assert_array_equal(mob.data[name], snapshot[name])

    def test_authored_fill_stroke_order_z_index_and_depth_survive_preparation(self):
        raised = Square(fill_color=RED, fill_opacity=1, stroke_color=BLUE,
                        stroke_width=8, z_index=5)
        behind = Circle(fill_color=GREEN, fill_opacity=1, stroke_color=YELLOW,
                        stroke_width=8, stroke_behind=True)
        depth = Square(fill_color=WHITE, fill_opacity=1, stroke_width=0, depth_test=True)
        frame = prepare_triangle_frame(build_scene(raised, behind, depth), self.tessellator)
        expected = [("stroke", YELLOW), ("surface", GREEN), ("surface_depth", WHITE),
                    ("surface", RED), ("stroke", BLUE)]
        self.assertEqual(len(frame.draws), len(expected))
        for draw, (pipeline, color) in zip(frame.draws, expected):
            self.assertEqual(draw.pipeline, pipeline)
            channel = "stroke_rgba" if pipeline.startswith("stroke") else "rgba"
            np.testing.assert_allclose(draw.vertices[channel][0, :3], color_to_rgb(color), atol=1e-7)

    def test_rotated_mesh_retains_plane_area_and_mixed_depth_overlay(self):
        scene = get_fixture("rotated_plane").build()
        frame = prepare_triangle_frame(scene, self.tessellator)
        fill = frame.draws[0]
        self.assertAlmostEqual(_area(fill), 2.4 ** 2, places=5)
        self.assertGreater(np.ptp(fill.vertices["point"][:, 2]), 0.5)
        mixed = prepare_triangle_frame(get_fixture("mixed_depth").build(), self.tessellator,
                                        coalesce=False)
        self.assertEqual([draw.pipeline.endswith("_depth") for draw in mixed.draws],
                         [True, True, False])
        self.assertEqual(mixed.draws[-1].uniforms["is_fixed_in_frame"], 1.0)

    def test_source_morph_rebuilds_correct_concave_coverage(self):
        path = concave_quad(0)
        scene = build_scene(path)
        original_points = path.get_points().copy()
        first = prepare_triangle_frame(scene, self.tessellator).draws[0]
        path.set_points(concave_quad(1).get_points().copy())
        self.assertEqual(path.get_points().shape, original_points.shape)
        last = prepare_triangle_frame(scene, self.tessellator).draws[0]
        self.assertAlmostEqual(_area(first), 16, places=5)
        self.assertAlmostEqual(_area(last), 4, places=5)
        probes = [(-1.5, 1.5), (-1 / 3, 1 / 3)]
        np.testing.assert_array_equal(_covered(first, probes), [True, True])
        np.testing.assert_array_equal(_covered(last, probes), [True, False])


@unittest.skipUnless(os.environ.get("MANIML_LYON_LIBRARY") or _packaged_library(),
                     "Lyon helper is neither packaged nor explicitly built")
class TriangleSceneMeshCache(unittest.TestCase):
    def setUp(self):
        self.tessellator = LyonFillTessellator()
        self.cache = TriangleMeshCache()
        self.scene = get_fixture("curved_fill").build()
        self.path = self.scene.mobjects[0]

    def prepare(self, **kwargs):
        return prepare_triangle_frame(self.scene, self.tessellator,
                                      mesh_cache=self.cache, **kwargs)

    def assert_quality(self, frame, tolerance=0.25):
        self.assertLessEqual(_max_boundary_error(self.path, frame.draws[0], self.scene.camera),
                             tolerance + 1e-4)

    def test_opaque_constant_painter_borders_coalesce_without_changing_object_order(self):
        red = Square(fill_color=RED, fill_opacity=1, stroke_width=0, fill_border_width=20)
        blue = Circle(fill_color="#0000ff", fill_opacity=1, stroke_width=0, fill_border_width=20).shift([.2, .1, 0])
        self.scene = build_scene(red, blue)
        source = [(shape.data["point"].copy(), shape.data["fill_rgba"].copy()) for shape in (red, blue)]
        separate = self.prepare(fill_borders=True, coalesce=False)
        self.assertEqual(len(separate.draws), 2)
        self.assertTrue(all(not draw.coverage for draw in separate.draws))
        merged = self.prepare(fill_borders=True)
        self.assertEqual(len(merged.draws), 1)
        np.testing.assert_array_equal(merged.draws[0].vertices[merged.draws[0].indices],
            np.concatenate([draw.vertices[draw.indices] for draw in separate.draws]))
        for shape, (points, rgba) in zip((red, blue), source):
            np.testing.assert_array_equal(shape.data["point"], points)
            np.testing.assert_array_equal(shape.data["fill_rgba"], rgba)

    def test_translucent_paint_shading_and_depth_borders_keep_coverage_ownership(self):
        for kind in ("translucent", "paint", "shaded", "depth"):
            with self.subTest(kind=kind):
                shape = Square(fill_color=RED, fill_opacity=1, stroke_width=0, fill_border_width=20)
                if kind == "translucent":
                    shape.data["fill_rgba"][:, 3] = .999
                elif kind == "paint":
                    shape.data["fill_rgba"][0] = [0, 0, 1, 1]
                elif kind == "shaded":
                    shape.uniforms["shading"] = [.2, 0, 0]
                else:
                    shape.depth_test = True
                self.scene = build_scene(shape)
                frame = self.prepare(fill_borders=True)
                self.assertEqual(len(frame.draws), 1)
                self.assertTrue(frame.draws[0].coverage)

    def test_fill_only_runs_skip_stroke_expansion_share_camera_and_preserve_exact_edits(self):
        other = self.path.copy().shift([1.5, 0, 0])
        self.scene = build_scene(self.path, other)
        source = [path.data.copy() for path in (self.path, other)]
        self.prepare()
        self.scene.camera.frame.scale(0.95)
        with (patch.object(self.path, "get_shader_data", side_effect=AssertionError("unused stroke data")),
              patch.object(other, "get_shader_data", side_effect=AssertionError("unused stroke data")),
              patch("benchmarks.triangle_scene.projection_matrix", wraps=projection_matrix) as projection):
            merged = self.prepare()
        self.assertEqual(len(merged.draws), 1)
        self.assertEqual(merged.mesh_cache_stats["hits"], 2)
        self.assertEqual(projection.call_count, 1)
        separate = self.prepare(coalesce=False)
        np.testing.assert_array_equal(
            merged.draws[0].vertices[merged.draws[0].indices],
            np.concatenate([draw.vertices[draw.indices] for draw in separate.draws]))
        for path, before in zip((self.path, other), source):
            # Derived normal/joint data may refresh; authored geometry/paint cannot.
            for field in ("point", "fill_rgba", "stroke_rgba", "stroke_width", "fill_border_width"):
                np.testing.assert_array_equal(path.data[field], before[field])
        other.data["point"][1, 0] += 0.125
        edited = self.prepare()
        self.assertEqual(edited.mesh_cache_stats["hits"], 1)
        self.assertEqual(edited.mesh_cache_stats["regenerations"], 1)
        self.assertFalse(np.array_equal(merged.draws[0].vertices, edited.draws[0].vertices))

    def test_unchanged_projection_reuses_error_but_tighter_quality_still_refines(self):
        self.prepare()
        self.prepare()  # Establish the first retained projection-error value.
        with patch("benchmarks.triangle_scene.projection_scale_bound",
                   wraps=projection_scale_bound) as bound:
            same = self.prepare()
            self.assertEqual(same.mesh_cache_stats["hits"], 1)
            bound.assert_not_called()
            # Lighting position affects draw uniforms, not geometric projection.
            self.scene.camera.light_source.shift([1, 0, 0])
            self.assertEqual(self.prepare().mesh_cache_stats["hits"], 1)
            bound.assert_not_called()
            self.assertEqual(self.prepare(pixel_tolerance=0.3).mesh_cache_stats["hits"], 1)
            bound.assert_not_called()
            refined = self.prepare(pixel_tolerance=0.025)
            self.assertEqual(refined.mesh_cache_stats["regenerations"], 1)
            self.assertGreater(bound.call_count, 0)
            self.assert_quality(refined, tolerance=0.025)

    def test_every_projection_dependency_rechecks_a_retained_mesh(self):
        def change_view(scene, path):
            view = list(scene.camera.uniforms["view"])
            view[12] += 0.25
            scene.camera.uniforms["view"] = view

        def change_rescale(scene, path):
            scale = list(scene.camera.uniforms["frame_rescale_factors"])
            scale[0] *= 1.25
            scene.camera.uniforms["frame_rescale_factors"] = scale

        def change_fixed(scene, path):
            path.uniforms["is_fixed_in_frame"] = 0.5

        def change_resolution(scene, path):
            width, height = scene.camera.draw_fbo.size
            scene.camera.draw_fbo.size = (width * 2, height)

        for change in (change_view, change_rescale, change_fixed, change_resolution):
            with self.subTest(dependency=change.__name__):
                self.cache = TriangleMeshCache()
                self.scene = get_fixture("curved_fill").build()
                self.path = self.scene.mobjects[0]
                self.prepare()
                self.prepare()
                # Keep these exact camera uniforms, including deliberate direct
                # array/list edits that do not bump a broad camera revision.
                self.scene.camera.refresh_uniforms = lambda: None
                change(self.scene, self.path)
                with patch("benchmarks.triangle_scene.projection_scale_bound",
                           wraps=projection_scale_bound) as bound:
                    self.prepare()
                    self.assertGreater(bound.call_count, 0)

    def test_failed_projection_keys_never_turn_into_successful_cache_hits(self):
        for field in ("view", "frame_rescale_factors", "is_fixed_in_frame", "resolution"):
            with self.subTest(dependency=field):
                self.cache = TriangleMeshCache()
                self.scene = get_fixture("curved_fill").build()
                self.path = self.scene.mobjects[0]
                self.prepare()
                self.prepare()
                self.scene.camera.refresh_uniforms = lambda: None
                if field == "resolution":
                    self.scene.camera.draw_fbo.size = (384, np.nan)
                elif field == "is_fixed_in_frame":
                    self.path.uniforms[field] = np.nan
                else:
                    values = list(self.scene.camera.uniforms[field])
                    values[0] = np.nan
                    self.scene.camera.uniforms[field] = values
                for attempt in range(2):
                    with self.subTest(attempt=attempt), self.assertRaisesRegex(
                            UnsupportedPrototype, "nonfinite"):
                        self.prepare()

    def test_camera_zoom_refines_before_quality_failure_and_reuses_on_return(self):
        first = self.prepare()
        self.assertEqual(first.mesh_cache_stats["regenerations"], 1)
        self.assert_quality(first)
        old_vertices = first.draws[0].vertices
        # Small steps fit within the refinement headroom; both source and
        # primitive buffers are retained despite distinct camera uniforms.
        for _ in range(5):
            self.scene.camera.frame.scale(0.95)
            frame = self.prepare()
            self.assertEqual(frame.mesh_cache_stats["hits"], 1)
            self.assertIs(frame.draws[0].vertices, old_vertices)
            self.assert_quality(frame)
        self.scene.camera.frame.scale(0.25)
        refined = self.prepare()
        self.assertEqual(refined.mesh_cache_stats["regenerations"], 1)
        self.assertGreater(len(refined.draws[0].vertices), len(old_vertices))
        self.assert_quality(refined)
        self.scene.camera.frame.scale(8)
        returned = self.prepare()
        self.assertEqual(returned.mesh_cache_stats["hits"], 1)
        self.assertIs(returned.draws[0].vertices, refined.draws[0].vertices)
        self.assertEqual(self.cache.stats["entries"], 1)

    def test_uniform_opacity_updates_preserve_mesh_and_old_frames(self):
        first = self.prepare()
        vertices = first.draws[0].vertices.copy()
        indices = first.draws[0].indices
        points = self.path.get_points().copy()
        revision = self.path.revision
        # Public array writes must work even without a revision increment.
        self.path.data["fill_rgba"][:] = [.2, .4, .7, .35]
        self.assertEqual(self.path.revision, revision)
        with patch("benchmarks.triangle_scene._generate_mesh",
                   side_effect=AssertionError("paint rebuilt geometry")):
            updated = self.prepare()
            repeated = self.prepare()
        draw = updated.draws[0]
        self.assertIs(draw.indices, indices)
        np.testing.assert_array_equal(draw.vertices["point"], vertices["point"])
        np.testing.assert_array_equal(draw.vertices["d_normal_point"], vertices["d_normal_point"])
        np.testing.assert_allclose(draw.vertices["rgba"], np.tile([.2, .4, .7, .35], (len(draw.vertices), 1)))
        np.testing.assert_array_equal(first.draws[0].vertices, vertices)
        np.testing.assert_array_equal(self.path.get_points(), points)
        self.assertEqual(updated.mesh_cache_stats["regenerations"], 0)
        self.assertEqual(updated.mesh_cache_stats["paint_updates"], 1)
        self.assertEqual(repeated.mesh_cache_stats["paint_updates"], 0)
        self.assertEqual(updated.mesh_cache_stats["retained_bytes"], first.mesh_cache_stats["retained_bytes"])
        with self.assertRaises(ValueError):
            draw.vertices.flags.writeable = True

    def test_float64_paint_overflow_rejects_cache_refresh_like_fresh_generation(self):
        first = self.prepare()
        preserved = first.draws[0].vertices.copy()
        self.path.data = self.path.data.astype(np.dtype([
            (name, "f8", self.path.data.dtype.fields[name][0].shape)
            for name in self.path.data.dtype.names]))
        self.path.data["fill_rgba"][:, 0] = 1e300
        self.assertTrue(np.isfinite(self.path.data["fill_rgba"]).all())
        source = self.path.data.tobytes()
        for cache in (self.cache, None):
            with self.subTest(cached=cache is not None), self.assertRaisesRegex(
                    ValueError, "attributes must be finite float32 values"):
                prepare_triangle_frame(self.scene, self.tessellator, mesh_cache=cache)
        self.assertEqual(self.cache.stats["entries"], 0)
        self.assertEqual(self.path.data.tobytes(), source)
        np.testing.assert_array_equal(first.draws[0].vertices, preserved)

    def test_changed_paint_does_not_skip_geometry_or_camera_invalidation(self):
        self.prepare()
        self.path.set_fill(opacity=.3)
        self.scene.camera.frame.scale(.2)
        refined = self.prepare()
        self.assertEqual(refined.mesh_cache_stats["regenerations"], 1)
        self.assert_quality(refined)
        self.path.set_fill(opacity=.6)
        self.path.data["point"][:, 0] += .1
        moved = self.prepare()
        self.assertEqual(moved.mesh_cache_stats["regenerations"], 1)
        self.assert_quality(moved)

    def test_perspective_camera_distance_pan_rotation_and_resolution(self):
        self.scene.camera.frame.reorient(10, 25, 0)
        first = self.prepare()
        focal = self.scene.camera.frame.get_focal_distance()
        self.scene.camera.frame.shift([0, 0, -0.75 * focal])
        near = self.prepare()
        self.assertEqual(near.mesh_cache_stats["regenerations"], 1)
        self.assert_quality(near)
        self.scene.camera.frame.shift([0, 0, focal])
        far = self.prepare()
        self.assertEqual(far.mesh_cache_stats["hits"], 1)
        self.assertIs(far.draws[0].vertices, near.draws[0].vertices)
        self.scene.camera.frame.shift([0.1, -0.1, 0]).reorient(12, 23, 2)
        moved = self.prepare()
        self.assertEqual(moved.mesh_cache_stats["hits"], 1)
        self.assert_quality(moved)
        self.scene.camera.draw_fbo.size = (6144, 3456)
        resized = self.prepare()
        self.assertEqual(resized.mesh_cache_stats["regenerations"], 1)
        self.assert_quality(resized)
        self.assertGreater(len(resized.draws[0].vertices), len(first.draws[0].vertices))

    def test_quality_change_refines_then_keeps_the_finer_mesh(self):
        coarse = self.prepare(pixel_tolerance=1.0)
        fine = self.prepare(pixel_tolerance=0.05)
        self.assertEqual(fine.mesh_cache_stats["regenerations"], 1)
        self.assertGreater(len(fine.draws[0].vertices), len(coarse.draws[0].vertices))
        self.assert_quality(fine, tolerance=0.05)
        relaxed = self.prepare(pixel_tolerance=2.0)
        self.assertEqual(relaxed.mesh_cache_stats["hits"], 1)
        self.assertIs(relaxed.draws[0].vertices, fine.draws[0].vertices)

    def test_in_place_source_paint_normal_and_generator_changes_invalidate(self):
        first = self.prepare()
        self.path.data["point"][:, 0] *= 0.7
        moved = self.prepare()
        self.assertEqual(moved.mesh_cache_stats["regenerations"], 1)
        self.assertLess(_area(moved.draws[0]), _area(first.draws[0]))
        self.path.data["fill_rgba"][:, :3] = [1, 0, 0]
        painted = self.prepare()
        self.assertEqual(painted.mesh_cache_stats["regenerations"], 0)
        self.assertEqual(painted.mesh_cache_stats["paint_updates"], 1)
        np.testing.assert_array_equal(painted.draws[0].vertices["rgba"][:, 1:3], 0)
        normal = self.path.get_unit_normal().copy()
        with patch.object(self.path, "get_unit_normal", return_value=-normal):
            flipped = self.prepare()
        self.assertEqual(flipped.mesh_cache_stats["regenerations"], 1)
        first_delta = painted.draws[0].vertices["d_normal_point"] - painted.draws[0].vertices["point"]
        last_delta = flipped.draws[0].vertices["d_normal_point"] - flipped.draws[0].vertices["point"]
        np.testing.assert_allclose(last_delta, -first_delta, atol=1e-7)
        self.tessellator = LyonFillTessellator()
        self.assertEqual(self.prepare().mesh_cache_stats["regenerations"], 1)
        self.tessellator.cache_key = "different-settings"
        self.assertEqual(self.prepare().mesh_cache_stats["regenerations"], 1)

    def test_only_changed_subobjects_regenerate_and_contour_changes_keep_holes(self):
        other = get_fixture("annulus_hole").build().mobjects[0]
        self.scene = build_scene(self.path, other)
        self.assertEqual(self.prepare().mesh_cache_stats["regenerations"], 2)
        original = other.get_points().copy()
        other.data["point"][:, :2] *= 0.9
        frame = self.prepare(coalesce=False)
        self.assertEqual(frame.mesh_cache_stats["hits"], 1)
        self.assertEqual(frame.mesh_cache_stats["regenerations"], 1)
        np.testing.assert_array_equal(_covered(frame.draws[1], [(0, 0), (0.75, 0)]), [False, True])
        other.set_points(original[:len(original) // 2])
        updated = self.prepare()
        self.assertEqual(updated.mesh_cache_stats["hits"], 1)
        self.assertEqual(updated.mesh_cache_stats["regenerations"], 1)

    def test_retained_bytes_entries_and_lifetime_are_bounded(self):
        first = self.prepare()
        size = first.mesh_cache_stats["retained_bytes"]
        self.assertGreater(size, first.geometry_bytes)  # Source and plane metadata count.
        self.cache = TriangleMeshCache(max_bytes=size, max_entries=1)
        self.scene = build_scene(self.path, self.path.copy())
        bounded = self.prepare()
        self.assertEqual(bounded.mesh_cache_stats["entries"], 1)
        self.assertLessEqual(bounded.mesh_cache_stats["retained_bytes"], size)
        self.assertEqual(bounded.mesh_cache_stats["evictions"], 1)
        self.cache = TriangleMeshCache(max_bytes=1)
        oversized = self.prepare()
        self.assertEqual(oversized.mesh_cache_stats["entries"], 0)
        self.assertEqual(oversized.mesh_cache_stats["retained_bytes"], 0)
        self.assertEqual(len(oversized.draws), 1)
        self.assertAlmostEqual(_area(oversized.draws[0]), 2 * _area(first.draws[0]), places=5)
        self.cache = TriangleMeshCache()
        self.prepare()
        self.scene = build_scene()
        absent = self.prepare()
        self.assertEqual(absent.mesh_cache_stats["entries"], 0)
        self.assertEqual(absent.mesh_cache_stats["retained_bytes"], 0)
        self.assertEqual(absent.mesh_cache_stats["evictions"], 2)

    def test_cached_arrays_cannot_be_changed_by_frame_consumers(self):
        frame = self.prepare()
        for array in (frame.draws[0].vertices, frame.draws[0].indices):
            with self.assertRaises(ValueError):
                array.setflags(write=True)
            with self.assertRaises(ValueError):
                array[:] = 0
        self.assertIs(self.prepare().draws[0].vertices, frame.draws[0].vertices)

    def test_projection_failure_never_reuses_under_resolved_geometry(self):
        self.prepare()
        self.scene.camera.frame.shift([0, 0, -2 * self.scene.camera.frame.get_focal_distance()])
        with self.assertRaisesRegex(UnsupportedPrototype, "projection"):
            self.prepare()

    def test_cached_plane_residual_is_rechecked_when_camera_magnifies_it(self):
        self.path = closed_contours([
            (-1e-5, -1e-5, 0), (1e-5, -1e-5, 0),
            (1e-5, 1e-5, 0), (-1e-5, 1e-5, 1e-7),
        ])
        self.scene = build_scene(self.path, resolution=(768, 432))
        self.prepare(pixel_tolerance=0.01)
        self.scene.camera.frame.scale(1e-5).reorient(25, 35, 5)
        with self.assertRaisesRegex(UnsupportedPrototype, "plane-fitting residual"):
            self.prepare(pixel_tolerance=0.01)
        self.assertEqual(self.cache.stats["entries"], 0)

    def test_failed_source_regeneration_cannot_publish_the_previous_fill(self):
        self.prepare()
        self.path.data["point"][1, 0] += 0.2
        with patch.object(self.tessellator, "tessellate",
                          side_effect=UnsupportedPrototype("generation failed")):
            with self.assertRaisesRegex(UnsupportedPrototype, "generation failed"):
                self.prepare()
        self.assertEqual(self.cache.stats["entries"], 0)
        self.assertEqual(self.prepare().mesh_cache_stats["regenerations"], 1)


if __name__ == "__main__":
    unittest.main()

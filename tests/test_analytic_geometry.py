"""Independent interior ownership tests for the gated analytic A0 candidate."""

import unittest
from unittest.mock import patch

import numpy as np

from benchmarks.analytic_geometry import (
    PATCH_DTYPE, PATCH_UV, UnsupportedAnalyticGeometry, build_analytic_mesh,
)
from tests.renderer_fixtures import get_fixture


def polygon(anchors):
    anchors = np.asarray(anchors, dtype=float)
    result = [anchors[0]]
    for a, b in zip(anchors, np.roll(anchors, -1, axis=0)):
        result.extend(((a+b)/2, b))
    return np.array(result)


def winding(path, point):
    """Ray crossings solved on source quadratics, independently of the mesh."""
    total = 0
    curves = [path[i:i+3] for i in range(0, len(path)-2, 2)]
    if not np.allclose(path[-1], path[0], atol=1e-14, rtol=0):
        curves.append(np.array([path[-1], (path[-1]+path[0])/2, path[0]]))
    for a, b, c in curves:
        coefficients = [a[1]-2*b[1]+c[1], 2*(b[1]-a[1]), a[1]-point[1]]
        roots = np.roots(np.trim_zeros(coefficients, "f"))
        for root in roots:
            if abs(root.imag) > 1e-10 or not 0 <= root.real < 1:
                continue
            t = root.real
            x = (1-t)**2*a[0] + 2*t*(1-t)*b[0] + t*t*c[0]
            dy = 2*((1-t)*(b[1]-a[1]) + t*(c[1]-b[1]))
            if x > point[0] and abs(dy) > 1e-9:
                total += 1 if dy > 0 else -1
    return total


def ownership(mesh, points):
    counts = np.zeros(len(points), dtype=int)
    interior = mesh.positions[mesh.indices.reshape(-1, 3)]
    for triangle in interior:
        matrix = np.column_stack((triangle[1]-triangle[0], triangle[2]-triangle[0]))
        uv = np.linalg.solve(matrix, (points-triangle[0]).T).T
        counts += (uv[:, 0] > 1e-10) & (uv[:, 1] > 1e-10) & (uv.sum(axis=1) < 1-1e-10)
    for triangle, side in zip(mesh.patches, mesh.sides):
        matrix = np.column_stack((triangle[1]-triangle[0], triangle[2]-triangle[0]))
        bary = np.linalg.solve(matrix, (points-triangle[0]).T).T
        inside = (bary[:, 0] > 1e-10) & (bary[:, 1] > 1e-10) & (bary.sum(axis=1) < 1-1e-10)
        uv = bary @ PATCH_UV[1:]
        counts += inside & (side * (uv[:, 1]-uv[:, 0]**2) > 1e-10)
    return counts


class AnalyticGeometryTests(unittest.TestCase):
    def assert_coverage(self, contours, mesh=None):
        mesh = mesh or build_analytic_mesh(contours)
        all_points = np.concatenate(contours)
        lower, upper = all_points.min(axis=0)-.13, all_points.max(axis=0)+.13
        points = np.random.default_rng(149).uniform(lower, upper, (550, 2))
        expected = np.array([sum(winding(path, point) for path in contours) != 0 for point in points])
        actual = ownership(mesh, points)
        self.assertLessEqual(actual.max(initial=0), 1, "a translucent fill would double-paint")
        np.testing.assert_array_equal(actual, expected.astype(int))
        return mesh

    def test_inward_quadratic_excludes_anchor_polygon_overfill(self):
        # The review's rectangle example: the top edge dips through (0,0).
        path = np.array([[-1., -1], [0, -1], [1, -1], [1, 0], [1, 1],
                         [0, -1], [-1, 1], [-1, 0], [-1, -1]])
        mesh = self.assert_coverage([path])
        self.assertTrue(np.all(mesh.sides == -1))
        np.testing.assert_array_equal(ownership(mesh, [[.123, .5], [.123, -.5]]), [0, 1])

    def test_outward_curve_adds_only_region_between_chord_and_curve(self):
        path = np.array([[-1., -1], [0, -1], [1, -1], [1, 0], [1, 1],
                         [0, 3], [-1, 1], [-1, 0], [-1, -1]])
        mesh = self.assert_coverage([path])
        np.testing.assert_array_equal(mesh.sides, [1])
        np.testing.assert_array_equal(ownership(mesh, [[.123, 1.5], [.123, 2.3]]), [1, 0])
        self.assert_coverage([path[::-1]])

    def test_overlapping_control_hulls_subdivide_without_flattening(self):
        path = np.array([[-1., -1], [0, .8], [1, -1], [1, 0], [1, 1],
                         [0, -.8], [-1, 1], [-1, 0], [-1, -1]])
        mesh = self.assert_coverage([path])
        self.assertGreater(mesh.subdivision_rounds, 0)
        self.assertGreater(len(mesh.patches), 2)
        with self.assertRaisesRegex(UnsupportedAnalyticGeometry, "subdivision budget"):
            build_analytic_mesh([path], max_subdivisions=0)

    def test_holes_nested_islands_and_disconnected_components(self):
        paths = [polygon([(-3, -3), (3, -3), (3, 3), (-3, 3)]),
                 polygon([(-2, -2), (-2, 2), (2, 2), (2, -2)]),
                 polygon([(-.5, -.5), (.5, -.5), (.5, .5), (-.5, .5)]),
                 polygon([(4, 0), (5, 0), (5, 1), (4, 1)])]
        self.assert_coverage(paths)
        self.assert_coverage([p[::-1] for p in paths])

    def test_real_circle_and_annulus_preserve_source_and_single_coverage(self):
        for name in ("curved_fill", "annulus_hole"):
            with self.subTest(name=name):
                mob = get_fixture(name).build().mobjects[0]
                before = mob.get_points().copy()
                paths = [p[:, :2] for p in mob.get_subpaths()]
                mesh = self.assert_coverage(paths)
                self.assertGreater(len(mesh.patches), 0)
                self.assertLessEqual(mesh.closure_displacement, 1e-12)
                np.testing.assert_array_equal(mob.get_points(), before)

    def test_two_quadratic_lens(self):
        self.assert_coverage([np.array([[-1., 0], [0, -1], [1, 0], [0, 1], [-1, 0]])])

    def test_crossing_touching_and_repeated_nonzero_are_explicitly_rejected(self):
        square = polygon([(0, 0), (2, 0), (2, 2), (0, 2)])
        cases = [[polygon([(0, 0), (2, 2), (0, 2), (2, 0)])],
                 [square, square], [square, square + [2, 0]],
                 [square, square/2 + [.5, .5]]]
        for paths in cases:
            with self.subTest(paths=paths), self.assertRaises(UnsupportedAnalyticGeometry):
                build_analytic_mesh(paths)

    def test_invalid_input_limits_and_no_aliasing(self):
        for path in (np.zeros((2, 2)), np.zeros((3, 3)), np.full((3, 2), np.nan),
                     np.ones((3, 2), dtype=complex), np.array([["x", "y"]])):
            with self.subTest(path=path), self.assertRaises(ValueError):
                build_analytic_mesh([path])
        for limit in (True, 0, 8193, 2.5):
            with self.assertRaises(ValueError):
                build_analytic_mesh([], max_segments=limit)
        path = polygon([(0, 0), (1, 0), (1, 1), (0, 1)])
        original = path.copy()
        path.flags.writeable = False
        mesh = build_analytic_mesh([path])
        mesh.positions[:] = -100
        np.testing.assert_array_equal(path, original)
        self.assertEqual(build_analytic_mesh([]).indices.size, 0)

    def test_numerical_curve_linearization_requires_and_reports_an_error_bound(self):
        height = 2.**-44
        path = np.array([[0., -1], [.5, -1], [1, -1], [1, -.5], [1, 0],
                         [.5, height], [0, 0], [0, -.5], [0, -1]])
        with self.assertRaisesRegex(UnsupportedAnalyticGeometry, "geometry error budget"):
            build_analytic_mesh([path])
        with self.assertRaisesRegex(UnsupportedAnalyticGeometry, "geometry error budget"):
            build_analytic_mesh([path], max_linearization_error=height/4)
        mesh = build_analytic_mesh([path], max_linearization_error=height)
        self.assertGreater(mesh.linearization_displacement, 0)
        ts = np.linspace(0, 1, 513)
        exact_height = 2*ts*(1-ts)*height
        self.assertLessEqual(exact_height.max(), mesh.linearization_displacement)
        self.assertLessEqual(mesh.linearization_displacement, height)
        self.assertEqual(len(mesh.patches), 0)

    def test_exact_zero_area_triangles_can_be_removed_without_losing_coverage(self):
        path = polygon([(0, 0), (1, 0), (1, 1), (0, 1), (0, .5)])
        # A complete square plus an exactly collinear redundant triangle.
        output = np.array([0, 1, 2, 0, 2, 3, 0, 3, 4], dtype="u4")
        with patch("benchmarks.analytic_geometry.mapbox_earcut.triangulate_float64", return_value=output):
            mesh = build_analytic_mesh([path])
        self.assertEqual(mesh.degenerate_triangles_removed, 1)
        self.assertEqual(mesh.nonzero_sliver_triangles, 0)
        self.assert_coverage([path], mesh=mesh)

    def test_nonzero_sliver_retains_its_covered_samples(self):
        epsilon = 2.**-43
        path = polygon([(0, 0), (1, 0), (1, 1), (0, 1), (.5, .5+epsilon)])
        # A valid partition of this concave polygon; its last triangle has a
        # nonzero area below the former rejection threshold.
        output = np.array([0, 1, 2, 2, 3, 4, 0, 2, 4], dtype="u4")
        with patch("benchmarks.analytic_geometry.mapbox_earcut.triangulate_float64", return_value=output):
            mesh = build_analytic_mesh([path])
        self.assertEqual(mesh.degenerate_triangles_removed, 0)
        self.assertEqual(mesh.nonzero_sliver_triangles, 1)
        self.assertEqual(ownership(mesh, np.array([[.5, .5+epsilon/2]]))[0], 1)
        self.assert_coverage([path], mesh=mesh)

    def test_gpu_layout_maps_uv_and_constant_paint(self):
        path = np.array([[-1., 0], [0, -1], [1, 0], [0, 1], [-1, 0]])
        mesh = build_analytic_mesh([path])
        vertices = mesh.patch_vertices(origin=[3, 4, 5], basis=[[1, 0, 0], [0, 1, 0]],
                                       rgba=[.2, .3, .4, .5])
        self.assertEqual(vertices.dtype, PATCH_DTYPE)
        np.testing.assert_allclose(vertices["point"][:, :2], mesh.patches.reshape(-1, 2)+[3, 4])
        np.testing.assert_allclose(vertices["point"][:, 2], 5)
        np.testing.assert_allclose(vertices["rgba"], np.tile([.2, .3, .4, .5], (len(vertices), 1)))
        np.testing.assert_allclose(vertices["uv"].reshape(-1, 3, 2), np.tile(PATCH_UV, (len(mesh.patches), 1, 1)))
        np.testing.assert_array_equal(vertices["fill_side"], np.repeat(mesh.sides, 3))


if __name__ == "__main__":
    unittest.main()

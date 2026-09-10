"""Independent geometry checks for the optional A0 Lyon adapter (no GPU).

Native cases use the packaged helper or an explicit MANIML_LYON_LIBRARY.
These test covered regions and attribute fields, not one tessellator's exact
choice of triangles or vertex order.
"""

import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import numpy as np

from maniml.web.triangle_geometry import (
    LyonFillTessellator, TessellationError, TessellationLimitError,
    _packaged_library,
)


def contour(anchors):
    """Straight polygon in Manim's quadratic control-point representation."""
    anchors = np.asarray(anchors, dtype=float)
    result = [anchors[0]]
    for left, right in zip(anchors, anchors[1:]):
        result.extend([(left + right) / 2, right])
    return np.asarray(result)


def area(mesh):
    if not mesh.indices.size:
        return 0.0
    triangles = mesh.positions[mesh.indices.reshape(-1, 3)].astype(float)
    ab = triangles[:, 1] - triangles[:, 0]
    ac = triangles[:, 2] - triangles[:, 0]
    return float(np.abs(ab[:, 0] * ac[:, 1] - ab[:, 1] * ac[:, 0]).sum() / 2)


def strict_coverage(mesh, samples, *, epsilon=1e-7):
    """Count triangle interiors; sample locations deliberately avoid edges."""
    triangles = mesh.positions[mesh.indices.reshape(-1, 3)].astype(float)
    counts = np.zeros(len(samples), dtype=int)
    for tri in triangles:
        delta = np.roll(tri, -1, axis=0) - tri
        relative = np.asarray(samples)[:, None, :] - tri
        cross = delta[None, :, 0] * relative[:, :, 1] - delta[None, :, 1] * relative[:, :, 0]
        counts += (cross > epsilon).all(axis=1) | (cross < -epsilon).all(axis=1)
    return counts


class OptionalLyonLoading(unittest.TestCase):
    def test_missing_library_has_explicit_opt_in_message(self):
        with patch.dict(os.environ, {}, clear=True), patch(
                "maniml.web.triangle_geometry._packaged_library", return_value=None):
            with self.assertRaisesRegex(TessellationError, "MANIML_LYON_LIBRARY"):
                LyonFillTessellator()

    def test_packaged_abi_suffix_discovery_and_ambiguity(self):
        with TemporaryDirectory() as folder:
            module = Path(folder) / "triangle_geometry.py"
            with patch("maniml.web.triangle_geometry.__file__", str(module)):
                self.assertIsNone(_packaged_library())
                binary = Path(folder) / "maniml_lyon_fill.abi3.so"
                binary.touch()
                self.assertEqual(_packaged_library(), binary)
                (Path(folder) / "maniml_lyon_fill.dylib").touch()
                with self.assertRaisesRegex(TessellationError, "Multiple packaged"):
                    _packaged_library()


@unittest.skipUnless(os.environ.get("MANIML_LYON_LIBRARY") or _packaged_library(),
                     "Lyon helper is neither packaged nor explicitly built")
class LyonFillGeometry(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tess = LyonFillTessellator()

    def square(self):
        return contour([(0, 0), (4, 0), (4, 4), (0, 4), (0, 0)])

    def test_compound_hole_and_disconnected_component(self):
        outer = self.square()
        hole = contour([(1, 1), (1, 3), (3, 3), (3, 1), (1, 1)])
        island = contour([(5, 0), (6, 0), (6, 1), (5, 1), (5, 0)])
        mesh = self.tess.tessellate([outer, hole, island])
        self.assertEqual(mesh.status, "success")
        self.assertAlmostEqual(area(mesh), 13)
        np.testing.assert_array_equal(strict_coverage(mesh, [(.2, .7), (2, 2.1), (5.2, .7)]), [1, 0, 1])

    def test_repeated_contours_distinguish_fill_rules(self):
        square = self.square()
        nonzero = self.tess.tessellate([square, square])
        evenodd = self.tess.tessellate([square, square], fill_rule="evenodd")
        opposite = self.tess.tessellate([square, square[::-1]])
        self.assertEqual(nonzero.fill_rule, "nonzero")
        self.assertAlmostEqual(area(nonzero), 16)
        self.assertEqual(evenodd.status, "empty")
        self.assertEqual(opposite.status, "empty")

    def test_self_intersection_inserts_vertex_and_interpolates_attributes(self):
        path = contour([(0, 0), (2, 2), (0, 2), (2, 0), (0, 0)])
        # An affine field is unambiguous even when multiple source edges meet.
        attrs = np.column_stack([3 * path[:, 0] - 2 * path[:, 1], path, np.full(len(path), .4)])
        mesh = self.tess.tessellate([path], attributes=[attrs])
        self.assertAlmostEqual(area(mesh), 2)
        self.assertTrue(np.any(np.all(np.isclose(mesh.positions, [1, 1]), axis=1)))
        np.testing.assert_allclose(mesh.attributes[:, 0], 3 * mesh.positions[:, 0] - 2 * mesh.positions[:, 1])
        np.testing.assert_allclose(mesh.attributes[:, 1:3], mesh.positions)
        np.testing.assert_allclose(mesh.attributes[:, 3], .4)
        np.testing.assert_array_equal(strict_coverage(mesh, [(1.05, .2), (1.05, 1.8), (.1, 1.05)]), [1, 1, 0])

    def test_quadratic_curve_refines_with_tolerance(self):
        path = np.array([[-1., 0.], [0., 2.], [1., 0.]])
        rough = self.tess.tessellate([path], tolerance=.1)
        fine = self.tess.tessellate([path], tolerance=.001)
        self.assertGreater(len(fine.positions), len(rough.positions))
        self.assertLess(abs(area(fine) - 4 / 3), .005)
        curved = fine.positions[fine.positions[:, 1] > 0]
        np.testing.assert_allclose(curved[:, 1], 1 - curved[:, 0] ** 2, atol=2e-6)

    def test_convex_to_concave_regenerates_without_overfill(self):
        path = contour([(0, 0), (4, 0), (4, 4), (0, 4), (0, 0)])
        original = self.tess.tessellate([path])
        path[:] = contour([(0, 0), (1, 3), (4, 4), (0, 4), (0, 0)])
        concave = self.tess.tessellate([path])
        self.assertAlmostEqual(area(original), 16)
        self.assertAlmostEqual(area(concave), 4)
        np.testing.assert_array_equal(strict_coverage(concave, [(.3, 2.5), (2.1, 1.3)]), [1, 0])

    def test_empty_disappearing_and_repeated_points(self):
        for inputs in ([], [np.empty((0, 2))], [np.zeros((1, 2))], [np.zeros((5, 2))]):
            with self.subTest(inputs=inputs):
                mesh = self.tess.tessellate(inputs)
                self.assertEqual(mesh.status, "empty")
                self.assertEqual(mesh.positions.shape[1], 2)
                self.assertEqual(mesh.attributes.shape[1], 0)

    def test_readonly_strided_inputs_and_outputs_do_not_alias(self):
        original = self.square()
        backing = np.zeros((len(original), 4))
        backing[:, ::2] = original
        path = backing[:, ::2]
        path.flags.writeable = False
        mesh = self.tess.tessellate([path])
        mesh.positions[:] = -100
        np.testing.assert_array_equal(path, original)
        second = self.tess.tessellate([path])
        self.assertAlmostEqual(area(second), 16)

    def test_invalid_values_fail_explicitly(self):
        invalid = [np.zeros((2, 2)), np.zeros((3, 3)), np.array([[np.nan, 0.]]),
                   np.array([[np.inf, 0.]]), np.array([[1 + 2j, 0.]]),
                   np.array([["1", "0"]])]
        for path in invalid:
            with self.subTest(path=path), self.assertRaises(ValueError):
                self.tess.tessellate([path])
        for tol in (0, -1, float("nan"), float("inf"), 1e-60):
            with self.subTest(tolerance=tol), self.assertRaises(ValueError):
                self.tess.tessellate([self.square()], tolerance=tol)
        with self.assertRaises(ValueError):
            self.tess.tessellate([self.square()], fill_rule="default")
        with self.assertRaises(ValueError):
            self.tess.tessellate([self.square()], attributes=[np.zeros((2, 4))])
        with self.assertRaises(ValueError):
            self.tess.tessellate([self.square()], attributes=[np.ones((9, 1), dtype=complex)])

    def test_limits_do_not_return_partial_or_stale_meshes(self):
        for limits in ({"max_vertices": 2}, {"max_indices": 3}):
            with self.subTest(limits=limits), self.assertRaises(TessellationLimitError):
                self.tess.tessellate([self.square()], **limits)
        with self.assertRaises(TessellationLimitError):
            self.tess.tessellate([np.array([[-1., 0.], [0., 2.], [1., 0.]])], tolerance=1e-15)
        with self.assertRaises(TessellationLimitError):
            self.tess.tessellate([np.zeros((65_537, 2))])
        self.assertAlmostEqual(area(self.tess.tessellate([self.square()])), 16)

    def test_border_join_area_and_uniform_translucent_paint(self):
        path = self.square()
        rgba = np.tile([.8, .4, .2, .3], (len(path), 1))
        # Handle paint is not an endpoint field and remains deliberately unused.
        rgba[1::2] = 0
        for join, expected in (("bevel", 24.5), ("miter", 25), ("round", 24 + np.pi / 4)):
            with self.subTest(join=join):
                mesh = self.tess.tessellate([path], attributes=[rgba], border_width=1,
                                            border_join=join, tolerance=.0005)
                self.assertAlmostEqual(area(mesh), expected, delta=.002)
                np.testing.assert_allclose(mesh.attributes, np.tile(rgba[0], (len(mesh.positions), 1)))
                np.testing.assert_array_equal(strict_coverage(mesh,
                    [(.11, .31), (-.2, .31), (2.13, 2.37)]), [1, 1, 1])
                self.assertEqual(mesh.border_width, 1)
                self.assertEqual(mesh.border_join, join)

    def test_border_shrinks_and_closes_holes_without_overpainting(self):
        hole = contour([(1, 1), (1, 3), (3, 3), (3, 1), (1, 1)])
        for width, expected_area in ((1, 24), (2.4, 6.4 ** 2)):
            mesh = self.tess.tessellate([self.square(), hole], border_width=width,
                                        border_join="miter", tolerance=.001)
            self.assertAlmostEqual(area(mesh), expected_area, delta=2e-5)
            np.testing.assert_array_equal(strict_coverage(mesh,
                [(1.21, 1.67), (2.13, 2.37), (-.31, .79)]),
                [1, int(width > 2), 1])

    def test_round_border_union_matches_independent_polygon_distance_oracle(self):
        # For closed polygons with round joins, the stroke region is the union
        # of radius-width/2 capsules around the straight segments. This oracle
        # does not reuse Lyon's connectivity or join implementation.
        outer = np.array([(0, 0), (4, 0), (4, 4), (0, 4), (0, 0)], dtype=float)
        hole = np.array([(1, 1), (1, 3), (3, 3), (3, 1), (1, 1)], dtype=float)
        concave = np.array([(0, 0), (4, 0), (4, 1), (1, 1), (1, 4), (0, 4), (0, 0)], dtype=float)
        crossing = np.array([(0, 0), (4, 4), (0, 4), (4, 0), (0, 0)], dtype=float)
        cases = [[outer, hole], [outer[::-1], hole[::-1]], [concave],
                 [crossing], [outer, outer], [outer, outer[::-1]]]
        samples = np.random.default_rng(91).uniform(-.8, 4.8, (1200, 2))
        radius = .35
        for anchors in cases:
            winding = np.zeros(len(samples), dtype=int)
            distance = np.full(len(samples), np.inf)
            for polygon in anchors:
                for a, b in zip(polygon[:-1], polygon[1:]):
                    ab = b - a
                    relative = samples - a
                    cross = ab[0] * relative[:, 1] - ab[1] * relative[:, 0]
                    winding += ((a[1] <= samples[:, 1]) & (samples[:, 1] < b[1]) & (cross > 0))
                    winding -= ((b[1] <= samples[:, 1]) & (samples[:, 1] < a[1]) & (cross < 0))
                    t = np.clip(relative @ ab / (ab @ ab), 0, 1)
                    distance = np.minimum(distance, np.linalg.norm(relative - t[:, None] * ab, axis=1))
            away = np.abs(distance - radius) > .002
            expected = (winding != 0) | (distance < radius)
            mesh = self.tess.tessellate([contour(polygon) for polygon in anchors],
                border_width=2 * radius, border_join="round", tolerance=.0001)
            counts = strict_coverage(mesh, samples[away])
            np.testing.assert_array_equal(counts, expected[away].astype(int))

    def test_border_curve_refinement_and_source_invariants(self):
        curve = np.array([[-1., 0.], [0., 2.], [1., 0.]])
        original = curve.copy()
        curve.flags.writeable = False
        rough = self.tess.tessellate([curve], border_width=.3, border_join="round", tolerance=.03)
        fine = self.tess.tessellate([curve], border_width=.3, border_join="round", tolerance=.0001)
        finer = self.tess.tessellate([curve], border_width=.3, border_join="round", tolerance=.000025)
        self.assertLess(abs(area(fine) - area(finer)), .002)
        self.assertLess(abs(area(fine) - area(finer)), abs(area(rough) - area(finer)))
        np.testing.assert_array_equal(curve, original)
        fine.positions[:] = -100
        np.testing.assert_array_equal(curve, original)

    def test_small_curved_holes_survive_or_close_at_the_geometric_width(self):
        from maniml.mobject.geometry import Annulus
        # Manim's quadratic circle is not an exact mathematical circle. Use
        # its actual convex contour area/perimeter in the parallel-body formula,
        # evaluated independently by high-order quadrature, not pi*radius**2.
        nodes, weights = np.polynomial.legendre.leggauss(64)
        t = (nodes + 1) / 2
        weights = weights / 2
        def curve_measure(path):
            signed_area = perimeter = 0.
            for a, b, c in zip(path[::2], path[1::2], path[2::2]):
                values = (1 - t[:, None]) ** 2 * a + 2 * (t * (1 - t))[:, None] * b + t[:, None] ** 2 * c
                derivatives = 2 * (1 - t[:, None]) * (b - a) + 2 * t[:, None] * (c - b)
                signed_area += float(weights @ (values[:, 0] * derivatives[:, 1] - values[:, 1] * derivatives[:, 0])) / 2
                perimeter += float(weights @ np.linalg.norm(derivatives, axis=1))
            return abs(signed_area), perimeter
        for radius in (.009, .018, .035):
            annulus = Annulus(inner_radius=radius, outer_radius=.13, stroke_width=0)
            original = annulus.get_points().copy()
            paths = [p[:, :2] for p in annulus.get_subpaths()]
            mesh = self.tess.tessellate(paths,
                border_width=.04, border_join="round", tolerance=.000025)
            (outer_area, outer_length), (inner_area, inner_length) = sorted(
                [curve_measure(path) for path in paths], reverse=True)
            expected = outer_area + .02 * outer_length + np.pi * .02 ** 2
            if radius > .02:
                expected -= inner_area - .02 * inner_length + np.pi * .02 ** 2
            self.assertAlmostEqual(area(mesh), expected, delta=.00005)
            np.testing.assert_array_equal(strict_coverage(mesh,
                [(0.00017, .00031), (.14, .013)], epsilon=1e-16),
                [int(radius < .02), 1])
            np.testing.assert_array_equal(annulus.get_points(), original)

    def test_border_rejects_invalid_style_and_varying_endpoint_paint(self):
        for kwargs in ({"border_width": -1}, {"border_width": np.nan},
                       {"border_width": 1e-60}, {"border_join": "auto"},
                       {"border_miter_limit": .5}, {"border_miter_limit": np.inf}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.tess.tessellate([self.square()], **kwargs)
        attrs = np.ones((len(self.square()), 4))
        attrs[-1, 3] = .3
        with self.assertRaisesRegex(ValueError, "uniform endpoint"):
            self.tess.tessellate([self.square()], attributes=[attrs], border_width=1)
        with self.assertRaisesRegex(ValueError, "uniform endpoint"):
            self.tess.tessellate([self.square(), self.square()],
                attributes=[np.ones((9, 4)), np.zeros((9, 4))], border_width=1)

    def test_border_limits_empty_and_recovery(self):
        for limits in ({"max_vertices": 2}, {"max_indices": 3}, {"max_vertices": 20}):
            with self.subTest(limits=limits), self.assertRaises(TessellationLimitError):
                self.tess.tessellate([self.square()], border_width=1, **limits)
        for inputs in ([], [np.empty((0, 2))], [np.zeros((1, 2))], [np.zeros((5, 2))]):
            self.assertEqual(self.tess.tessellate(inputs, border_width=1).status, "empty")
        self.assertAlmostEqual(area(self.tess.tessellate([self.square()], border_width=1)), 24.5)

    def test_real_tex_border_keeps_fill_single_coverage(self):
        from tests.renderer_quality_fixtures import (
            build_quality_frame, QualityFixtureUnavailable,
        )
        from maniml.mobject.types.vectorized_mobject import VMobject
        try:
            frame = build_quality_frame("tex")
        except QualityFixtureUnavailable as error:
            self.skipTest(str(error))
        count = 0
        for group in frame.scene.render_groups:
            for obj in group.family_members_with_points():
                if not isinstance(obj, VMobject) or not np.any(obj.data["fill_rgba"][:, 3] > 0):
                    continue
                original = obj.get_points().copy()
                # The fixture is genuinely in XY. Exercise an independent
                # orthonormal coordinate change too; no source arrays are edited.
                angle = .431
                rotation = np.array([[np.cos(angle), -np.sin(angle)],
                                     [np.sin(angle), np.cos(angle)]])
                contours = [(part[:, :2] - original[0, :2]) @ rotation
                            for part in obj.get_subpaths()]
                fill = self.tess.tessellate(contours, tolerance=.001)
                bordered = self.tess.tessellate(contours, tolerance=.001,
                    border_width=.01 * float(obj.data["fill_border_width"][0, 0]))
                points = np.concatenate(contours)
                samples = np.random.default_rng(101).uniform(
                    points.min(axis=0) - .005, points.max(axis=0) + .005, (60, 2))
                # Cross products have squared-coordinate units: the unit-square
                # tests' epsilon is too coarse for tiny glyph/sliver triangles.
                fill_counts = strict_coverage(fill, samples, epsilon=1e-16)
                union_counts = strict_coverage(bordered, samples, epsilon=1e-16)
                self.assertLessEqual(int(union_counts.max()), 1)
                np.testing.assert_array_equal(union_counts[fill_counts == 1], 1)
                self.assertGreaterEqual(area(bordered) + 1e-10, area(fill))
                np.testing.assert_array_equal(obj.get_points(), original)
                count += 1
        self.assertEqual(count, 101)


if __name__ == "__main__":
    unittest.main()

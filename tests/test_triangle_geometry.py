"""Independent geometry checks for the optional A0 Lyon adapter (no GPU).

Set MANIML_LYON_LIBRARY to the explicitly built helper to run native cases.
These test covered regions and attribute fields, not one tessellator's exact
choice of triangles or vertex order.
"""

import os
import unittest
from unittest.mock import patch

import numpy as np

from maniml.web.triangle_geometry import (
    LyonFillTessellator, TessellationError, TessellationLimitError,
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


def strict_coverage(mesh, samples):
    """Count triangle interiors; sample locations deliberately avoid edges."""
    triangles = mesh.positions[mesh.indices.reshape(-1, 3)].astype(float)
    counts = np.zeros(len(samples), dtype=int)
    for tri in triangles:
        delta = np.roll(tri, -1, axis=0) - tri
        relative = np.asarray(samples)[:, None, :] - tri
        cross = delta[None, :, 0] * relative[:, :, 1] - delta[None, :, 1] * relative[:, :, 0]
        counts += (cross > 1e-7).all(axis=1) | (cross < -1e-7).all(axis=1)
    return counts


class OptionalLyonLoading(unittest.TestCase):
    def test_missing_library_has_explicit_opt_in_message(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(TessellationError, "MANIML_LYON_LIBRARY"):
                LyonFillTessellator()


@unittest.skipUnless(os.environ.get("MANIML_LYON_LIBRARY"), "optional Lyon helper not built")
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


if __name__ == "__main__":
    unittest.main()

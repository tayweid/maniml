"""Independent geometry checks for the bounded Earcut-vs-Lyon experiment."""

import os
import unittest

import numpy as np

from benchmarks.earcut_probe import (
    evaluate_case, flatten_contours, mesh_coverage, probe_cases,
    source_oracle, tessellate_existing_earcut, tessellate_single_ring_earcut,
)
from maniml.web.triangle_geometry import LyonFillTessellator


def _case(name):
    return next(case for case in probe_cases(include_tex=False) if case.name == name)


class EarcutProbeGeometry(unittest.TestCase):
    def test_quadratic_flattening_has_bounded_geometric_error(self):
        path = np.array([[-1., 0.], [0., 2.], [1., 0.]])
        tolerance = .003
        flat = flatten_contours([path], tolerance)[0]
        samples = np.linspace(0, 1, 2001)[:, None]
        curve = (1-samples)**2*path[0] + 2*(1-samples)*samples*path[1] + samples**2*path[2]
        # For this quadratic, x is linear in t. Compare the chord at the same
        # x, independently from the segment-count formula being checked.
        chord_y = np.interp(curve[:, 0], flat[:, 0], flat[:, 1])
        self.assertLessEqual(float(np.max(abs(curve[:, 1]-chord_y))), tolerance)

    def test_reference_oracle_distinguishes_nested_winding_and_cancellation(self):
        points = np.array([[.2, .3], [1.5, .3], [2.5, .3]])
        expected = {
            "same_winding_nested": [2, 1, 0],
            "opposite_winding_nested": [0, 1, 0],
            "opposed_duplicate": [0, 0, 0],
        }
        for name, values in expected.items():
            with self.subTest(case=name):
                winding, safe = source_oracle(_case(name).contours, points, .001)
                np.testing.assert_array_equal(safe, True)
                np.testing.assert_array_equal(winding, values)

    def test_typed_existing_wrapper_handles_simple_polygon_and_hole(self):
        points = np.array([[.2, .3], [1.5, .3], [2.5, .3]])
        case = _case("opposite_winding_nested")
        before = [contour.copy() for contour in case.contours]
        mesh = tessellate_existing_earcut(case.contours)
        covered, count = mesh_coverage(mesh, points)
        np.testing.assert_array_equal(covered, [False, True, False])
        np.testing.assert_array_equal(count, [0, 1, 0])
        for original, contour in zip(before, case.contours):
            np.testing.assert_array_equal(original, contour)

    def test_direct_earcut_bowtie_misses_required_nonzero_region(self):
        case = _case("crossing_morph_1.000000")
        points = np.array([[1.05, .2], [1.05, 1.8], [.1, 1.05]])
        winding, safe = source_oracle(case.contours, points, .001)
        np.testing.assert_array_equal(safe, True)
        np.testing.assert_array_equal(winding != 0, [True, True, False])
        mesh = tessellate_single_ring_earcut(case.contours)
        covered, _ = mesh_coverage(mesh, points)
        self.assertFalse(np.array_equal(covered, winding != 0))

    def test_repeated_contour_overdraw_is_not_counted_as_correct_coverage(self):
        case = _case("repeated_winding")
        mesh = tessellate_single_ring_earcut(case.contours)
        covered, count = mesh_coverage(mesh, [[.2, .3]])
        np.testing.assert_array_equal(covered, [True])
        self.assertGreater(count[0], 1)

    def test_invalid_flattening_arguments_fail(self):
        for tolerance in (0, -1, np.nan):
            with self.assertRaises(ValueError):
                flatten_contours([np.zeros((3, 2))], tolerance)
        with self.assertRaises(ValueError):
            flatten_contours([np.zeros((4, 2))], .01)


@unittest.skipUnless(os.environ.get("MANIML_LYON_LIBRARY"), "optional Lyon helper not built")
class EarcutVersusLyon(unittest.TestCase):
    def test_required_crossing_morphs_fail_direct_earcut_but_pass_lyon(self):
        tess = LyonFillTessellator()
        for name in ("crossing_morph_0.800000", "crossing_morph_1.000000"):
            with self.subTest(case=name):
                result = evaluate_case(_case(name), tess, grid_size=25)
                self.assertGreater(result["tested_probes"], 500)
                generators = result["generators"]
                self.assertEqual(generators["lyon_nonzero"]["status"], "pass")
                self.assertEqual(generators["direct_earcut_single_ring"]["status"], "fail")
                self.assertGreater(generators["direct_earcut_single_ring"]["coverage_mismatches"], 0)


if __name__ == "__main__":
    unittest.main()

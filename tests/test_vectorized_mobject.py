"""Corner construction must preserve the scalar path's geometry and state.

``add_line_to`` is the independent reference for the bulk operation.  In
particular, each scalar line starts at a float32 *stored* anchor even when
the caller supplies float64 endpoints.
"""

import unittest

import numpy as np

from maniml.mobject.functions import ParametricCurve
from maniml.mobject.mobject import Mobject
from maniml.mobject.types.dot_cloud import DotCloud
from maniml.mobject.types.vectorized_mobject import VGroup, VMobject
from maniml.utils.iterables import resize_array


def add_corners_scalar(mobject, points):
    for point in points:
        mobject.add_line_to(point)
    return mobject


@Mobject.affects_data
def append_points_legacy(mobject, points):
    """The old append algorithm, independent of production append_points."""
    n = mobject.get_num_points()
    mobject.resize_points(n + len(points))
    mobject.data[n:] = mobject.data[n - 1]
    mobject.data["point"][n:] = points
    mobject.refresh_bounding_box()
    return mobject


class ScalarParametricCurve(ParametricCurve):
    add_points_as_corners = add_corners_scalar


class CornerConstructionTests(unittest.TestCase):
    def assertSamePath(self, actual, expected):
        # Check every vertex field, including inherited per-point styling.
        np.testing.assert_array_equal(actual.data, expected.data)
        np.testing.assert_array_equal(
            actual.get_subpath_end_indices(), expected.get_subpath_end_indices()
        )
        np.testing.assert_array_equal(actual.get_bounding_box(), expected.get_bounding_box())

    def test_bulk_matches_scalar_for_input_dtypes_and_long_lines(self):
        rng = np.random.default_rng(42)
        for long_lines in (False, True):
            for dtype in (np.float32, np.float64, np.int64):
                with self.subTest(long_lines=long_lines, dtype=dtype):
                    points = (rng.normal(size=(80, 3)) * 100).astype(dtype)
                    actual = VMobject(long_lines=long_lines).start_new_path([0.1, 0.2, 0.3])
                    expected = actual.copy()
                    result = actual.add_points_as_corners(points)
                    add_corners_scalar(expected, points)
                    self.assertIs(result, actual)
                    self.assertSamePath(actual, expected)

    def test_float64_endpoints_start_next_line_at_stored_float32_anchor(self):
        # Adjacent integers here round differently in float32.  Using the
        # original preceding endpoint instead of its stored value changes
        # the next handle, even though all anchors still look correct.
        points = np.array([
            [16777217.0, 0.100000001, -0.333333333],
            [16777219.0, 0.200000001, -0.666666667],
            [16777213.0, 0.300000001, -0.999999999],
        ])
        for long_lines in (False, True):
            with self.subTest(long_lines=long_lines):
                actual = VMobject(long_lines=long_lines).start_new_path([16777215, 0, 0])
                expected = actual.copy()
                actual.add_points_as_corners(points)
                add_corners_scalar(expected, points)
                self.assertSamePath(actual, expected)

    def test_existing_subpaths_duplicates_and_closed_paths_are_preserved(self):
        for long_lines in (False, True):
            with self.subTest(long_lines=long_lines):
                actual = VMobject(long_lines=long_lines).start_new_path([0, 0, 0])
                actual.add_line_to([1, 0, 0]).add_line_to([0, 0, 0])
                actual.start_new_path([4, 2, 0])
                actual.add_line_to([5, 2, 0])
                expected = actual.copy()
                prefix = actual.data.copy()
                points = np.array([[5, 2, 0], [5, 3, 0], [5, 3, 0], [4, 2, 0]])
                actual.add_points_as_corners(points)
                add_corners_scalar(expected, points)
                np.testing.assert_array_equal(actual.data[:len(prefix)], prefix)
                self.assertSamePath(actual, expected)
                self.assertEqual(len(actual.get_subpaths()), 2)

    def test_extension_inherits_last_vertex_style(self):
        actual = VMobject().set_points_as_corners([[0, 0, 0], [1, 1, 0], [2, 0, 0]])
        actual.set_stroke(color=["#ff0000", "#0000ff"], width=[1, 9], opacity=[0.2, 0.8])
        actual.set_fill(color=["#00ff00", "#ffffff"], opacity=[0.3, 0.7], border_width=2)
        expected = actual.copy()
        last = actual.data[-1].copy()
        prefix_length = len(actual.data)
        points = np.array([[3, -1, 0], [4, 0, 0], [5, 1, 0]])
        actual.add_points_as_corners(points)
        add_corners_scalar(expected, points)
        self.assertSamePath(actual, expected)
        for field in ("stroke_rgba", "stroke_width", "fill_rgba", "fill_border_width"):
            np.testing.assert_array_equal(
                actual.data[field][prefix_length:],
                np.repeat(last[field][None, :], len(actual.data) - prefix_length, axis=0),
            )

    def test_lists_tuples_and_generators_match_array_input(self):
        points = [[1.25, 2, 0], [2.5, -1, 0], [-3, 0, 0]]
        for input_type in (list, tuple, np.array, iter):
            with self.subTest(input_type=input_type):
                actual = VMobject().start_new_path([0, 0, 0])
                expected = actual.copy()
                actual.add_points_as_corners(input_type(points))
                add_corners_scalar(expected, points)
                self.assertSamePath(actual, expected)

    def test_stateful_generator_sees_each_appended_endpoint(self):
        def points_from_current_endpoint(mobject):
            for _ in range(4):
                yield mobject.get_last_point() + np.array([1.25, -0.5, 0.25])

        actual = VMobject().start_new_path([0, 0, 0])
        expected = actual.copy()
        actual.add_points_as_corners(points_from_current_endpoint(actual))
        add_corners_scalar(expected, points_from_current_endpoint(expected))
        self.assertSamePath(actual, expected)
        np.testing.assert_array_equal(actual.get_last_point(), [5, -2, 1])

    def test_overridden_add_line_to_is_still_called_for_each_point(self):
        class CustomLine(VMobject):
            def add_line_to(self, point, allow_null_line=True):
                self.calls.append(tuple(point))
                self.set_stroke(width=len(self.calls))
                return super().add_line_to(np.array(point) + [0, 0, 1], allow_null_line)

        actual = CustomLine().start_new_path([0, 0, 0])
        actual.calls = []
        expected = actual.copy()
        expected.calls = []
        points = np.array([[1, 0, 0], [2, 1, 0], [3, 0, 0]])
        actual.add_points_as_corners(points)
        add_corners_scalar(expected, points)
        self.assertEqual(actual.calls, [tuple(p) for p in points])
        self.assertSamePath(actual, expected)

    def test_nonfinite_coordinates_preserve_scalar_propagation(self):
        for long_lines in (False, True):
            with self.subTest(long_lines=long_lines), np.errstate(invalid="ignore"):
                actual = VMobject(long_lines=long_lines).start_new_path([0, 0, 0])
                expected = actual.copy()
                points = np.array([[np.inf, 1, 0], [2, 2, 0], [3, np.nan, 0], [4, 4, 0]])
                actual.add_points_as_corners(points)
                add_corners_scalar(expected, points)
                for field in actual.data.dtype.names:
                    np.testing.assert_array_equal(actual.data[field], expected.data[field])

    def test_overridden_append_points_keeps_per_line_updates(self):
        class CustomAppend(VMobject):
            def append_points(self, points):
                # The following line must start at this adjusted endpoint.
                return super().append_points(np.asarray(points) + [0, 0, 1])

        actual = CustomAppend().start_new_path([0, 0, 0])
        expected = actual.copy()
        points = np.array([[1, 0, 0], [2, 1, 0], [3, 0, 0]])
        actual.add_points_as_corners(points)
        add_corners_scalar(expected, points)
        self.assertSamePath(actual, expected)

    def test_empty_inputs_are_noop_even_without_started_path(self):
        for has_points in (False, True):
            for input_type in (list, tuple, np.array, iter):
                with self.subTest(has_points=has_points, input_type=input_type):
                    actual = VMobject()
                    if has_points:
                        actual.start_new_path([0, 0, 0]).add_line_to([1, 0, 0])
                    group = VGroup(actual)
                    before_data = actual.data
                    before_revisions = (actual.revision, group.revision)
                    result = actual.add_points_as_corners(input_type([]))
                    self.assertIs(result, actual)
                    self.assertIs(actual.data, before_data)
                    self.assertEqual((actual.revision, group.revision), before_revisions)

    def test_nonempty_input_still_requires_started_path(self):
        actual = VMobject()
        with self.assertRaisesRegex(Exception, "Mobject with no points"):
            actual.add_points_as_corners(np.array([[1, 2, 0]]))
        self.assertFalse(actual.has_points())

    def test_append_invalidates_derived_geometry_and_ancestor_revisions(self):
        actual = VMobject().set_points_as_corners([[0, 0, 0], [1, 0, 0], [1, 1, 0]])
        middle = VGroup(actual)
        top = VGroup(middle)
        for mob in (actual, middle, top):
            mob.get_bounding_box()
            mob._triangulation_cache = object()
            mob._data_has_changed = False
        actual.get_subpath_end_indices()
        actual.get_joint_angles()
        actual.get_unit_normal()
        expected = actual.copy()
        revisions = [mob.revision for mob in (actual, middle, top)]
        points = np.array([[2, 3, 1], [-3, 4, 2]])
        actual.add_points_as_corners(points)
        add_corners_scalar(expected, points)
        self.assertIsNone(actual.subpath_end_indices)
        self.assertTrue(actual.needs_new_joint_angles)
        self.assertTrue(actual.needs_new_unit_normal)
        for mob, revision in zip((actual, middle, top), revisions):
            self.assertGreater(mob.revision, revision)
            self.assertTrue(mob._data_has_changed)
            self.assertFalse(hasattr(mob, "_triangulation_cache"))
        self.assertSamePath(actual, expected)
        np.testing.assert_array_equal(top.get_bounding_box(), actual.get_bounding_box())
        np.testing.assert_array_equal(actual.get_joint_angles(), expected.get_joint_angles())
        np.testing.assert_array_equal(actual.get_unit_normal(), expected.get_unit_normal())


class PointAppendTests(unittest.TestCase):
    mobject_classes = (Mobject, DotCloud, VMobject)

    def test_initial_append_inherits_empty_objects_style_defaults(self):
        points = np.array([[1, 2, 0], [3, 4, 1]])
        for mobject_class in self.mobject_classes:
            with self.subTest(mobject_class=mobject_class):
                actual = mobject_class(color="#369abc").clear_points()
                actual.set_opacity(0.37)
                if isinstance(actual, DotCloud):
                    actual.set_radius(0.123)
                if isinstance(actual, VMobject):
                    actual.set_stroke(width=7.5)
                expected = actual.copy()
                defaults = actual._data_defaults.copy()
                actual.append_points(points)
                append_points_legacy(expected, points)
                np.testing.assert_array_equal(actual.data, expected.data)
                for field in actual.data.dtype.names:
                    if field != "point":
                        np.testing.assert_array_equal(
                            actual.data[field], np.repeat(defaults[field], len(points), axis=0)
                        )

    def test_append_preserves_nonuniform_existing_styles_and_aliased_points(self):
        initial = np.array([[0, 0, 0], [1, 2, 0], [2, -1, 1]])
        for mobject_class in self.mobject_classes:
            for alias in (False, True):
                with self.subTest(mobject_class=mobject_class, alias=alias):
                    actual = mobject_class().set_points(initial)
                    actual.set_color(["#ff0000", "#00ff00"], opacity=[0.2, 0.9])
                    if isinstance(actual, DotCloud):
                        actual.set_radii([0.1, 0.2, 0.3])
                    if isinstance(actual, VMobject):
                        actual.set_stroke(width=[1, 5, 9])
                    expected = actual.copy()
                    prefix = actual.data.copy()
                    actual_points = actual.get_points()[1:]
                    expected_points = expected.get_points()[1:]
                    if not alias:
                        actual_points = actual_points.copy()
                        expected_points = expected_points.copy()
                    actual.append_points(actual_points)
                    append_points_legacy(expected, expected_points)
                    np.testing.assert_array_equal(actual.data, expected.data)
                    np.testing.assert_array_equal(actual.data[:len(prefix)], prefix)
                    np.testing.assert_array_equal(actual.get_points()[-2:], initial[1:])

    def test_append_calls_custom_resize_points_hook(self):
        for mobject_class in self.mobject_classes:
            with self.subTest(mobject_class=mobject_class):
                class TracksResize(mobject_class):
                    def resize_points(self, new_length, resize_func=resize_array):
                        self.last_resize = new_length
                        return super().resize_points(new_length, resize_func=resize_func)

                actual = TracksResize().set_points([[0, 0, 0]])
                expected = actual.copy()
                del actual.last_resize
                points = np.array([[1, 1, 0], [2, 0, 0]])
                self.assertIs(actual.append_points(points), actual)
                append_points_legacy(expected, points)
                self.assertEqual(actual.last_resize, 3)
                np.testing.assert_array_equal(actual.data, expected.data)

    def test_empty_append_to_existing_points_preserves_data_and_revision_behavior(self):
        for mobject_class in self.mobject_classes:
            with self.subTest(mobject_class=mobject_class):
                actual = mobject_class().set_points([[0, 0, 0]])
                expected = actual.copy()
                data = actual.data
                revision = actual.revision
                expected_revision = expected.revision
                actual.append_points(np.empty((0, 3)))
                append_points_legacy(expected, np.empty((0, 3)))
                self.assertIs(actual.data, data)
                np.testing.assert_array_equal(actual.data, expected.data)
                self.assertEqual(actual.revision - revision, expected.revision - expected_revision)

    def test_empty_append_to_empty_object_preserves_legacy_error(self):
        for mobject_class in self.mobject_classes:
            with self.subTest(mobject_class=mobject_class):
                actual = mobject_class().clear_points()
                expected = actual.copy()
                with self.assertRaises(IndexError):
                    append_points_legacy(expected, np.empty((0, 3)))
                with self.assertRaises(IndexError):
                    actual.append_points(np.empty((0, 3)))
                np.testing.assert_array_equal(actual.data, expected.data)


class ParametricCurveCornerTests(unittest.TestCase):
    def test_sampling_order_discontinuities_and_smoothing_match_scalar_path(self):
        for smoothing in (False, True):
            for long_lines in (False, True):
                with self.subTest(smoothing=smoothing, long_lines=long_lines):
                    def build(curve_class):
                        calls = []

                        def callback(t):
                            # The callback is intentionally stateful: changing
                            # its number/order of evaluations changes the curve.
                            calls.append(float(t))
                            return [t, np.sin(t) + len(calls) / 1000, t * t / 10]

                        curve = curve_class(
                            callback, t_range=(-1, 1, 0.13), discontinuities=[0],
                            epsilon=0.01, use_smoothing=smoothing, long_lines=long_lines,
                        )
                        return curve, calls

                    actual, actual_calls = build(ParametricCurve)
                    expected, expected_calls = build(ScalarParametricCurve)
                    self.assertEqual(actual_calls, expected_calls)
                    self.assertEqual(len(actual_calls), 18)
                    self.assertEqual(len(actual.get_subpaths()), 2)
                    np.testing.assert_array_equal(actual.data, expected.data)
                    np.testing.assert_array_equal(
                        actual.get_subpath_end_indices(), expected.get_subpath_end_indices()
                    )


if __name__ == "__main__":
    unittest.main()

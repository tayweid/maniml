"""Behavioral tests for CE-compatible coordinate systems.

Pure mobject construction — no Scene, no GL context.
"""

import math
from types import MethodType
import unittest

import numpy as np

from maniml.mobject.coordinate_systems import Axes, ComplexPlane, NumberPlane
from maniml.mobject.functions import ParametricCurve
from maniml.mobject.mobject_update_utils import always_redraw
from maniml.mobject.number_line import NumberLine
from maniml.mobject.value_tracker import ValueTracker


class AxisNumberOrientation(unittest.TestCase):
    def test_y_axis_numbers_stay_upright(self):
        # CE parity: the y-axis rotates into place before its numbers
        # are added, so labels are laid out against the vertical line
        # and stay upright. Rotating a numbered axis instead carried
        # the labels with it — every label came out 90 degrees over.
        axes = Axes(
            x_range=[0, 10, 1], y_range=[0, 40, 5],
            width=6, height=6,
            y_axis_config={'numbers_to_include': np.arange(10, 50, 10)},
        )
        for number in axes.y_axis.numbers:
            # A two-digit label is wider than it is tall only upright
            self.assertGreater(
                number.get_width(), number.get_height(),
                f"y-axis label {number.get_value()} is not upright")
        # The labels sit to the left of the vertical line
        line_x = axes.y_axis.n2p(20)[0]
        for number in axes.y_axis.numbers:
            self.assertLess(number.get_center()[0], line_x)

    def test_include_numbers_survives_axis_creation(self):
        # include_numbers is deferred until after the y-rotation, so it
        # is popped from the NumberLine config; both axes must still
        # get their numbers, upright.
        axes = Axes(
            x_range=[-3, 3, 1], y_range=[-3, 3, 1],
            width=6, height=6,
            axis_config={'include_numbers': True},
        )
        self.assertGreater(len(axes.x_axis.numbers), 0)
        self.assertGreater(len(axes.y_axis.numbers), 0)
        # Single-digit labels are taller than wide even upright, so
        # compare each label's aspect against a freshly built upright
        # one of the same value instead
        from maniml.mobject.numbers import DecimalNumber
        for number in axes.y_axis.numbers:
            config = dict(axes.y_axis.decimal_number_config)
            config.setdefault('font_size', 24)
            upright = DecimalNumber(number.get_value(), **config)
            self.assertAlmostEqual(
                number.get_width() / number.get_height(),
                upright.get_width() / upright.get_height(),
                places=2,
                msg=f"y-axis label {number.get_value()} is rotated")


class GraphCoordinateSampling(unittest.TestCase):
    @staticmethod
    def make_axes(cls=Axes, **kwargs):
        return cls(
            x_range=(-2, 3, 1), y_range=(-3, 4, 1),
            width=5.7, height=3.1,
            axis_config={'include_ticks': False, 'include_tip': False},
            **kwargs,
        )

    @staticmethod
    def scalar_graph(axes, function, x_range=None, *, plot=False, **kwargs):
        """The original per-sample mapping, independent of get_graph()."""
        source_range = axes.x_range if x_range is None else x_range
        t_range = np.ones(3)
        t_range[:len(source_range)] = source_range
        if not (plot and x_range is not None and len(x_range) > 2):
            t_range[2] /= axes.num_sampled_graph_points_per_tick
        return ParametricCurve(
            lambda t: axes.c2p(t, function(t)),
            t_range=tuple(t_range), **kwargs,
        )

    def assert_same_geometry(self, actual, expected):
        np.testing.assert_array_equal(actual.get_points(), expected.get_points())
        for field in ('stroke_rgba', 'stroke_width', 'fill_rgba'):
            np.testing.assert_array_equal(actual.data[field], expected.data[field])
        actual_paths = actual.get_subpaths()
        expected_paths = expected.get_subpaths()
        self.assertEqual(len(actual_paths), len(expected_paths))
        for actual_path, expected_path in zip(actual_paths, expected_paths):
            np.testing.assert_array_equal(actual_path, expected_path)

    def test_scalar_callbacks_keep_sample_order_and_count(self):
        for method in ('get_graph', 'plot'):
            with self.subTest(method=method):
                axes = self.make_axes()
                actual_calls, expected_calls = [], []

                def function(calls):
                    def evaluate(x):
                        self.assertEqual(np.ndim(x), 0)
                        calls.append(float(x))
                        return math.sin(x) if x < 0 else math.sqrt(x + 1)
                    return evaluate

                x_range = (-1, 1, 0.25)
                actual = getattr(axes, method)(function(actual_calls), x_range=x_range)
                expected = self.scalar_graph(
                    axes, function(expected_calls), x_range,
                    plot=method == 'plot',
                )
                self.assertEqual(actual_calls, expected_calls)
                self.assertGreater(len(actual_calls), 2)
                self.assert_same_geometry(actual, expected)

    def test_default_and_two_element_ranges_keep_sampling(self):
        axes = self.make_axes(num_sampled_graph_points_per_tick=7)
        for x_range in (None, (-0.8, 1.3)):
            for method in ('get_graph', 'plot'):
                with self.subTest(x_range=x_range, method=method):
                    actual_calls, expected_calls = [], []

                    def record(calls, x):
                        calls.append(float(x))
                        return x * x

                    actual = getattr(axes, method)(
                        lambda x: record(actual_calls, x), x_range=x_range,
                    )
                    expected = self.scalar_graph(
                        axes, lambda x: record(expected_calls, x), x_range,
                        plot=method == 'plot',
                    )
                    self.assertEqual(actual_calls, expected_calls)
                    self.assert_same_geometry(actual, expected)

    def test_transformed_axes_and_nonzero_crossings(self):
        for x_range, y_range in (((2, 9, 1), (3, 8, 1)),
                                 ((-9, -2, 1), (-8, -3, 1))):
            with self.subTest(x_range=x_range):
                axes = Axes(
                    x_range=x_range, y_range=y_range, width=7.3, height=2.9,
                    axis_config={'include_ticks': False, 'include_tip': False},
                )
                axes.stretch(0.731, 0).rotate(0.37).shift([1.17, -0.63, 0.29])
                function = lambda x: 0.713 * x + 0.19
                sample_range = (x_range[0], x_range[1], 0.37)
                actual = axes.plot(function, x_range=sample_range)
                expected = self.scalar_graph(axes, function, sample_range, plot=True)
                self.assert_same_geometry(actual, expected)

    def test_discontinuities_and_smoothing_preserve_geometry(self):
        axes = self.make_axes()
        for smoothing in (False, True):
            with self.subTest(smoothing=smoothing):
                actual_calls, expected_calls = [], []

                def evaluate(calls, x):
                    calls.append(float(x))
                    return 1 / (x - 0.2)

                kwargs = dict(
                    discontinuities=[0.2], epsilon=0.025,
                    use_smoothing=smoothing, stroke_width=3.5,
                )
                actual = axes.get_graph(
                    lambda x: evaluate(actual_calls, x), (-1, 1, 0.5), **kwargs,
                )
                expected = self.scalar_graph(
                    axes, lambda x: evaluate(expected_calls, x), (-1, 1, 0.5),
                    **kwargs,
                )
                self.assertEqual(actual_calls, expected_calls)
                self.assertEqual(len(actual.get_subpaths()), 2)
                self.assert_same_geometry(actual, expected)

    def test_function_accessors_use_current_axes(self):
        axes = self.make_axes()
        function = lambda x: math.sin(x)
        graph = axes.plot(function, x_range=(-1, 1, 0.2))
        original_points = graph.get_points().copy()
        axes.scale(1.3).shift([0.4, 0.7, -0.1])
        self.assertIs(graph.get_function(), function)
        self.assertIs(graph.underlying_function, function)
        for x in (-0.73, 0.31):
            expected = axes.c2p(x, function(x))
            np.testing.assert_array_equal(graph.get_t_func()(x), expected)
            np.testing.assert_array_equal(graph.get_point_from_function(x), expected)
        np.testing.assert_array_equal(graph.get_points(), original_points)

    def test_bind_graph_preserves_updates(self):
        axes = self.make_axes()
        tracker = ValueTracker(0.5)
        function = lambda x: tracker.get_value() * x ** 2
        graph = axes.get_graph(function, (-1, 1, 0.5), bind=True)
        expected = self.scalar_graph(axes, function, (-1, 1, 0.5))
        axes.bind_graph_to_func(expected, function)
        self.assert_same_geometry(graph, expected)
        tracker.set_value(1.7)
        axes.rotate(-0.21).shift([0.13, -0.26, 0.4])
        graph.update(1 / 30)
        expected.update(1 / 30)
        self.assert_same_geometry(graph, expected)

    def test_always_redraw_tracks_function_and_axes_changes(self):
        axes = self.make_axes()
        tracker = ValueTracker(0.5)
        function = lambda x: tracker.get_value() * math.sin(x)
        graph = always_redraw(lambda: axes.plot(function, x_range=(-1, 1, 0.1)))
        for value, offset in ((1.3, [0.3, -0.2, 0]), (0.7, [-0.1, 0.4, 0.2])):
            tracker.set_value(value)
            axes.shift(offset)
            graph.update(1 / 30)
            expected = self.scalar_graph(axes, function, (-1, 1, 0.1), plot=True)
            self.assert_same_geometry(graph, expected)

    def test_custom_c2p_is_still_called_for_each_sample(self):
        class CustomAxes(Axes):
            def c2p(self, x, y):
                if np.ndim(x) or np.ndim(y):
                    raise AssertionError('Custom mapping requires scalar inputs')
                return super().c2p(x, y) + np.array([0, 0, 0.17 * x * y])

        axes = self.make_axes(CustomAxes)
        function = lambda x: math.cos(x)
        actual = axes.plot(function, x_range=(-1, 1, 0.17))
        expected = self.scalar_graph(axes, function, (-1, 1, 0.17), plot=True)
        self.assert_same_geometry(actual, expected)

    def test_custom_coords_to_point_is_still_called_for_each_sample(self):
        class CustomAxes(Axes):
            def coords_to_point(self, x, y):
                if np.ndim(x) or np.ndim(y):
                    raise AssertionError('Custom mapping requires scalar inputs')
                return super().coords_to_point(x, y) + np.array([0.07 * y * y, 0, 0])

        axes = self.make_axes(CustomAxes)
        function = lambda x: math.cos(x)
        actual = axes.get_graph(function, (-1, 1, 0.7))
        expected = self.scalar_graph(axes, function, (-1, 1, 0.7))
        self.assert_same_geometry(actual, expected)

    def test_custom_number_to_point_keeps_scalar_mapping(self):
        axes = self.make_axes()

        def custom_number_to_point(axis, number):
            if np.ndim(number):
                raise AssertionError('Custom axis requires scalar inputs')
            return NumberLine.number_to_point(axis, number) + [0, 0, 0.11 * number ** 2]

        axes.y_axis.number_to_point = MethodType(custom_number_to_point, axes.y_axis)
        function = lambda x: x * x - 0.3
        actual = axes.get_graph(function, (-1, 1, 0.7))
        expected = self.scalar_graph(axes, function, (-1, 1, 0.7))
        self.assert_same_geometry(actual, expected)

    def check_axes_mutation_during_sampling(self, mutate):
        actual_axes, expected_axes = self.make_axes(), self.make_axes()
        actual_calls, expected_calls = [], []

        def function(axes, calls):
            def evaluate(x):
                calls.append(float(x))
                if len(calls) == 4:
                    mutate(axes)
                return math.sin(x)
            return evaluate

        actual = actual_axes.plot(function(actual_axes, actual_calls), x_range=(-1, 1, 0.2))
        expected = self.scalar_graph(
            expected_axes, function(expected_axes, expected_calls),
            (-1, 1, 0.2), plot=True,
        )
        self.assertEqual(actual_calls, expected_calls)
        self.assert_same_geometry(actual, expected)

    def test_callback_can_move_axes_between_samples(self):
        self.check_axes_mutation_during_sampling(
            lambda axes: axes.shift([0.5, -0.7, 0.3]),
        )

    def test_callback_can_assign_axis_range_between_samples(self):
        def mutate(axes):
            axes.x_axis.x_min = 0.5
            axes.x_axis.x_max = 4.3
            axes.y_axis.x_max = 8.7

        self.check_axes_mutation_during_sampling(mutate)

    def test_callback_can_write_axis_points_between_samples(self):
        def mutate(axes):
            axes.x_axis.get_points()[-1] += [0.6, 0.4, 0.2]

        self.check_axes_mutation_during_sampling(mutate)

    def test_mixed_scalar_numeric_types_preserve_geometry(self):
        axes = self.make_axes()
        axes.rotate(0.31).shift([0.73, -0.41, 0.2])
        actual_calls, expected_calls = [], []
        types = (np.float32, np.float64, int, np.longdouble)

        def function(calls):
            def evaluate(x):
                scalar_type = types[len(calls) % len(types)]
                calls.append(float(x))
                return scalar_type(0.713 * x + 0.193)
            return evaluate

        actual = axes.plot(function(actual_calls), x_range=(-1, 1, 0.1))
        expected = self.scalar_graph(
            axes, function(expected_calls), (-1, 1, 0.1), plot=True,
        )
        self.assertEqual(actual_calls, expected_calls)
        self.assert_same_geometry(actual, expected)

    def test_zero_axis_range_raises_before_another_callback(self):
        actual_axes, expected_axes = self.make_axes(), self.make_axes()
        actual_calls, expected_calls = [], []

        def function(axes, calls):
            def evaluate(x):
                calls.append(float(x))
                if len(calls) == 3:
                    axes.x_axis.x_min = 1.0
                    axes.x_axis.x_max = 1.0
                return math.sin(x)
            return evaluate

        with self.assertRaises(ZeroDivisionError):
            actual_axes.plot(function(actual_axes, actual_calls), x_range=(-1, 1, 0.2))
        with self.assertRaises(ZeroDivisionError):
            self.scalar_graph(
                expected_axes, function(expected_axes, expected_calls),
                (-1, 1, 0.2), plot=True,
            )
        self.assertEqual(len(actual_calls), 3)
        self.assertEqual(actual_calls, expected_calls)

    def test_invalid_coordinate_raises_before_another_callback(self):
        axes = self.make_axes()
        actual_calls, expected_calls = [], []

        def function(calls):
            def evaluate(x):
                calls.append(float(x))
                return float('inf') if len(calls) == 3 else math.sin(x)
            return evaluate

        with np.errstate(invalid='raise'):
            with self.assertRaises(FloatingPointError):
                axes.plot(function(actual_calls), x_range=(-1, 1, 0.2))
            with self.assertRaises(FloatingPointError):
                self.scalar_graph(axes, function(expected_calls), (-1, 1, 0.2), plot=True)
        self.assertEqual(len(actual_calls), 3)
        self.assertEqual(actual_calls, expected_calls)

    def test_number_and_complex_planes_preserve_scalar_plot_geometry(self):
        for plane_type in (NumberPlane, ComplexPlane):
            with self.subTest(plane_type=plane_type.__name__):
                plane = self.make_axes(plane_type, faded_line_ratio=0)
                plane.rotate(0.19).stretch(0.87, 1).shift([0.3, -0.2, 0.1])
                function = lambda x: math.sin(x) + 0.1 * x
                actual = plane.plot(function, x_range=(-1, 1, 0.1))
                expected = self.scalar_graph(plane, function, (-1, 1, 0.1), plot=True)
                self.assert_same_geometry(actual, expected)

    def test_reinitializing_graph_uses_replaced_parametric_function(self):
        axes = self.make_axes()
        graph = axes.plot(math.sin, x_range=(-1, 1, 0.1))
        actual_calls, expected_calls = [], []

        def function(calls):
            def evaluate(t):
                calls.append(float(t))
                return [t + 0.73, math.cos(t), 0.29 * t]
            return evaluate

        graph.t_func = function(actual_calls)
        graph.clear_points()
        graph.init_points()
        expected = ParametricCurve(function(expected_calls), t_range=graph.t_range)
        self.assertEqual(actual_calls, expected_calls)
        self.assert_same_geometry(graph, expected)


if __name__ == '__main__':
    unittest.main()

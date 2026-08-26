"""Behavioral tests for CE-compatible coordinate systems.

Pure mobject construction — no Scene, no GL context.
"""

import unittest

import numpy as np

from maniml.mobject.coordinate_systems import Axes


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


if __name__ == '__main__':
    unittest.main()

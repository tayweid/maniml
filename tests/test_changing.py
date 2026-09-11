"""TracedPath and AnimatedBoundary, ported from CE (2026-09-11)."""

import unittest

import numpy as np

from maniml import AnimatedBoundary, Dot, RIGHT, ORIGIN, Square, TracedPath, UP
import maniml


class TracedPathTests(unittest.TestCase):
    def test_traces_the_point_as_it_moves(self):
        dot = Dot(ORIGIN)
        trace = TracedPath(dot.get_center)
        # add_updater runs the updater once, so the path starts where the
        # point is (a zero-length first segment, as in CE)
        np.testing.assert_allclose(trace.get_start(), ORIGIN, atol=1e-9)
        curves = trace.get_num_curves()
        for step in range(3):
            dot.shift(RIGHT)
            trace.update(1 / 30)
        np.testing.assert_allclose(trace.get_start(), ORIGIN, atol=1e-9)
        np.testing.assert_allclose(trace.get_end(), RIGHT * 3, atol=1e-9)
        # one curve per update, sharing anchors
        self.assertEqual(trace.get_num_curves(), curves + 3)

    def test_dissipating_path_forgets_its_oldest_segment(self):
        dot = Dot(ORIGIN)
        trace = TracedPath(dot.get_center, dissipating_time=0.5)
        for step in range(30):
            dot.shift(UP * 0.1)
            trace.update(0.1)
        # 30 segments were drawn; only those from the last half second remain
        self.assertLess(trace.get_num_curves(), 30)
        self.assertGreater(trace.get_start()[1], 0.5)
        np.testing.assert_allclose(trace.get_end(), UP * 3, atol=1e-9)

    def test_is_exported(self):
        self.assertIn('TracedPath', maniml.__all__)
        self.assertIn('AnimatedBoundary', maniml.__all__)


class AnimatedBoundaryTests(unittest.TestCase):
    def test_boundary_copies_draw_and_recolour_over_time(self):
        square = Square()
        boundary = AnimatedBoundary(square, colors=["#ff0000", "#00ff00"], cycle_rate=1)
        growing, fading = boundary.boundary_copies
        boundary.update(0.25)
        self.assertGreater(growing.get_stroke_width(), 0)
        self.assertEqual(growing.get_stroke_color().lower(), "#ff0000")
        # partway through the first cycle only part of the outline is drawn
        self.assertLess(growing.get_arc_length(), 0.9 * square.get_arc_length())
        boundary.update(1.0)   # total_time advances after the copies are drawn
        boundary.update(0.0)   # ...so the next colour shows on the following update
        self.assertEqual(growing.get_stroke_color().lower(), "#00ff00")


if __name__ == '__main__':
    unittest.main()

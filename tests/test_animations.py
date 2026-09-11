"""Unit tests for maniml-specific animations (no GL context needed)."""

import unittest

import numpy as np

from maniml import (
    DOWN, LEFT, RIGHT, UP, Animation, FadeIn, FlickerIn, Polygon, Rotating,
    ShowIncreasingSubsets, Square, Transform, VGroup, ValueTracker,
    always_redraw,
)
from maniml.animation.fading import _flicker_schedule


class FlickerInTests(unittest.TestCase):
    def test_schedule_is_deterministic(self):
        """Checkpoint replays re-run the animation from source; the sputter
        pattern must come out identical every time."""
        self.assertEqual(_flicker_schedule(4, 0), _flicker_schedule(4, 0))
        self.assertNotEqual(_flicker_schedule(4, 0), _flicker_schedule(4, 1))

    def test_schedule_starts_dark_and_settles_lit(self):
        anim = FlickerIn(Square())
        self.assertEqual(anim._level_at(0.0), 0.0)
        self.assertEqual(anim._level_at(1.0), 1.0)
        # steady from the settle point on: no sputter in the final stretch
        self.assertEqual(anim._level_at(0.8), 1.0)

    def test_schedule_actually_sputters(self):
        anim = FlickerIn(Square())
        levels = [anim._level_at(a / 200) for a in range(200)]
        drops = sum(
            1 for a, b in zip(levels, levels[1:]) if b == 0.0 and a > 0.0
        )
        self.assertGreaterEqual(drops, 2, "no off-sputters after lighting")

    def test_dark_during_an_off_sputter_and_lit_when_done(self):
        square = Square(fill_opacity=0.8, fill_color='#FF0000')
        anim = FlickerIn(square, run_time=1)
        anim.begin()
        # first off-sputter after the light has come on at least once
        off_at = next(t for t, level in anim.schedule[1:] if level == 0.0)
        anim.interpolate(off_at + 1e-4)
        self.assertAlmostEqual(square.get_fill_opacity(), 0.0, places=3)
        anim.finish()
        self.assertAlmostEqual(square.get_fill_opacity(), 0.8, places=3)

    def test_zero_flickers_is_a_clean_switch_on(self):
        anim = FlickerIn(Square(), flickers=0)
        self.assertEqual(anim.schedule, [(0.0, 0.0), (0.62, 1.0)])


if __name__ == '__main__':
    unittest.main()


class UpdatersDuringAnimationTests(unittest.TestCase):
    """CE pauses the animated mobject's own updaters for the play (2026-09-11
    field-report fix: a FadeIn of an always_redraw snapped in at full
    opacity, and a rebuild with a different point count broke the
    interpolation)."""

    @staticmethod
    def live_polygon():
        sides = ValueTracker(3)
        corners = [RIGHT, UP, LEFT, DOWN]
        live = always_redraw(
            lambda: Polygon(*corners[:int(sides.get_value())], fill_opacity=1))
        return sides, live

    def test_defaults_follow_ce(self):
        self.assertTrue(Animation(Square()).suspend_mobject_updating)
        self.assertTrue(Transform(Square(), Square()).suspend_mobject_updating)
        self.assertTrue(Rotating(Square()).suspend_mobject_updating)
        # CE keeps these reading their updaters each frame
        self.assertFalse(
            ShowIncreasingSubsets(VGroup(Square())).suspend_mobject_updating)

    def test_fade_in_pauses_the_live_mobject_and_resumes_after(self):
        _, live = self.live_polygon()
        anim = FadeIn(live)
        anim.begin()
        self.assertTrue(live.updating_suspended)
        anim.interpolate(0.5)
        live.update(1 / 30)   # what the scene loop does after each step
        self.assertAlmostEqual(live.get_fill_opacity(), 0.5, places=6)
        anim.finish()
        self.assertFalse(live.updating_suspended)
        self.assertAlmostEqual(live.get_fill_opacity(), 1.0, places=6)

    def test_interpolation_survives_an_endpoint_rebuild_with_another_point_count(self):
        sides, live = self.live_polygon()
        anim = FadeIn(live)
        anim.begin()
        n_aligned = live.get_num_points()
        sides.set_value(4)
        # The endpoint copies carry the always_redraw closure, which
        # rebuilds the original as a square: more points than the aligned
        # endpoints.
        anim.update_mobjects(1 / 30)
        self.assertNotEqual(live.get_num_points(), n_aligned)
        anim.interpolate(0.5)   # raised "could not broadcast" before
        self.assertEqual(live.get_num_points(), n_aligned)
        self.assertAlmostEqual(live.get_fill_opacity(), 0.5, places=6)
        np.testing.assert_allclose(
            live.get_points(),
            0.5 * anim.starting_mobject.get_points() + 0.5 * anim.target_copy.get_points())

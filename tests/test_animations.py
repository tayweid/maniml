"""Unit tests for maniml-specific animations (no GL context needed)."""

import unittest

from maniml import FlickerIn, Square
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

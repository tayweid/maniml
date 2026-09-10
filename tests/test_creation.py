"""Creation interpolation invariants; no renderer or font tools required."""

import unittest

import numpy as np

from maniml import Circle, VGroup
from maniml.animation.creation import DrawBorderThenFill, Unwrite, Write
from maniml.utils.rate_functions import linear, there_and_back


def glyph():
    # Nontrivial float32 coordinates expose roundoff from blending a point
    # with itself during the fill phase.
    return Circle(fill_opacity=0.6, stroke_width=0.7).scale(0.731).shift([0.137, 0.283, 0])


class CreationInterpolationTests(unittest.TestCase):
    def test_fill_changes_paint_without_moving_complete_point_arrays(self):
        mob = glyph()
        expected = mob.get_points().copy()
        animation = Write(mob, lag_ratio=0)
        animation.begin()
        opacities = []
        for alpha in (0.5, 0.53, 0.57, 0.69, 0.81, 0.99, 1):
            animation.interpolate(alpha)
            np.testing.assert_array_equal(mob.get_points(), expected)
            opacities.append(mob.get_fill_opacity())
        self.assertTrue(all(a < b for a, b in zip(opacities, opacities[1:])))
        self.assertAlmostEqual(opacities[-1], 0.6)

    def test_fixed_fill_normal_remains_exact_across_shader_preparation(self):
        mob = glyph().rotate(np.pi, axis=[1, 0, 0])
        animation = Write(mob, lag_ratio=0)
        animation.begin()
        expected_points = animation.starting_mobject.get_points().copy()
        expected_normal = animation.starting_mobject.get_unit_normal().copy()
        for alpha in (0.51, 0.7, 0.83, 1):
            animation.interpolate(alpha)
            mob.get_shader_data()
            np.testing.assert_array_equal(mob.get_points(), expected_points)
            np.testing.assert_array_equal(mob.get_unit_normal(), expected_normal)

    def test_completed_glyph_stays_unchanged_while_later_glyphs_animate(self):
        group = VGroup(*(glyph().shift([i, 0, 0]) for i in range(4)))
        animation = Write(group, lag_ratio=0.2)
        animation.begin()
        animation.interpolate(0.8)
        data, revision = group[0].data.copy(), group[0].revision
        later_data = group[-1].data.copy()
        animation.interpolate(0.9)
        np.testing.assert_array_equal(group[0].data, data)
        self.assertEqual(group[0].revision, revision)
        self.assertFalse(np.array_equal(group[-1].data, later_data))

    def test_repeated_completed_frames_preserve_family_revisions(self):
        group = VGroup(glyph(), VGroup(glyph().shift([1, 0, 0])))
        animation = Write(group)
        animation.begin()
        animation.interpolate(1)
        revisions = [mob.revision for mob in group.get_family()]
        for _ in range(3):
            animation.interpolate(1)
            self.assertEqual([mob.revision for mob in group.get_family()], revisions)
        for mob, target, _ in animation.families:
            np.testing.assert_array_equal(mob.get_points(), target.get_points())

    def test_backward_seek_matches_fresh_evaluation_in_each_phase(self):
        mob = glyph()
        animation = DrawBorderThenFill(mob, rate_func=linear)
        animation.begin()
        for alpha in (1, 0.25, 0.75, 0.1, 1, 0.5, 0.9):
            animation.interpolate(alpha)
            expected = glyph()
            fresh = DrawBorderThenFill(expected, rate_func=linear)
            fresh.begin()
            fresh.interpolate(alpha)
            np.testing.assert_array_equal(mob.data, expected.data)
            for key in mob.uniforms:
                np.testing.assert_array_equal(mob.uniforms[key], expected.uniforms[key])

    def test_reverse_and_nonmonotonic_rate_functions_reenter_border_phase(self):
        mob = glyph()
        mob.get_joint_angles(refresh=True)
        expected = mob.data.copy()
        animation = Unwrite(mob, lag_ratio=0)
        animation.begin()
        np.testing.assert_array_equal(mob.data, expected)
        animation.interpolate(0.9)
        self.assertEqual(mob.get_fill_opacity(), 0)
        animation.interpolate(0)
        np.testing.assert_array_equal(mob.data, expected)

        animation = Write(mob, lag_ratio=0, rate_func=there_and_back)
        animation.begin()
        animation.interpolate(0.5)
        np.testing.assert_array_equal(mob.data, expected)
        animation.interpolate(0.9)
        self.assertEqual(mob.get_fill_opacity(), 0)
        animation.interpolate(0.5)
        np.testing.assert_array_equal(mob.data, expected)

    def test_completed_evaluation_observes_live_and_endpoint_mutations(self):
        mob = glyph()
        animation = Write(mob, lag_ratio=0)
        animation.begin()
        animation.interpolate(1)
        mob.shift([0.25, 0.1, 0]).set_fill(opacity=0.2)
        animation.interpolate(1)
        np.testing.assert_array_equal(mob.data, animation.starting_mobject.data)

        animation.starting_mobject.shift([0.321, 0.456, 0]).set_fill(opacity=0.8)
        animation.interpolate(1)
        np.testing.assert_array_equal(mob.data, animation.starting_mobject.data)
        # Moving a single endpoint must still interpolate, not freeze all
        # geometry merely because this is a fill animation.
        animation.interpolate(0.75)
        expected = 0.5 * animation.outline.get_points() + 0.5 * animation.starting_mobject.get_points()
        np.testing.assert_array_equal(mob.get_points(), expected)

    def test_endpoint_updater_raw_writes_are_not_skipped(self):
        def move_raw(endpoint, dt):
            endpoint.get_family()[-1].data['point'][:, 0] += dt

        for updater_on_ancestor in (False, True):
            with self.subTest(updater_on_ancestor=updater_on_ancestor):
                mob = glyph()
                animation = Write(VGroup(mob) if updater_on_ancestor else mob, lag_ratio=0)
                animation.begin()
                animation.interpolate(1)
                animation.starting_mobject.add_updater(move_raw)
                target = animation.starting_mobject.get_family()[-1]
                animation.update_mobjects(0.25)
                animation.interpolate(1)
                np.testing.assert_array_equal(mob.get_points(), target.get_points())
                previous = mob.get_points().copy()
                animation.update_mobjects(0.25)
                animation.interpolate(1)
                self.assertFalse(np.array_equal(mob.get_points(), previous))
                np.testing.assert_array_equal(mob.get_points(), target.get_points())

    def test_restarting_animation_reinitializes_completion_state(self):
        mob = glyph()
        animation = Write(mob, lag_ratio=0)
        animation.begin()
        animation.finish()
        mob.shift([0.31, -0.27, 0]).set_fill(opacity=0.8)
        mob.get_joint_angles(refresh=True)
        expected = mob.data.copy()
        animation.begin()
        self.assertEqual(mob.get_fill_opacity(), 0)
        animation.finish()
        np.testing.assert_array_equal(mob.data, expected)


if __name__ == '__main__':
    unittest.main()

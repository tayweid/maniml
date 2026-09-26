"""CE spells a parametric surface Surface(func, u_range, v_range, ...);
maniml's Surface is GL's (colour first, uv_func a method). Both must build."""

import unittest

import numpy as np

from maniml import BLUE_D, GREY, RED, Surface, Torus
from maniml.mobject.types.surface import ParametricSurface
from maniml.utils.color import color_to_rgb


def saddle(u, v):
    return np.array([u, v, u * v])


class TestCESurfaceSpelling(unittest.TestCase):
    def test_ce_call_builds_the_function(self):
        surface = Surface(saddle, u_range=(-1, 1), v_range=(-1, 1), resolution=8,
                          fill_color=RED, fill_opacity=0.5,
                          checkerboard_colors=[RED, BLUE_D], stroke_width=0.5)
        self.assertEqual(surface.resolution, (9, 9))
        self.assertEqual(surface.get_points().shape, (81, 3))
        self.assertTrue(np.allclose(surface.uv_to_point(0.5, 0.5), [0.5, 0.5, 0.25], atol=0.05))
        self.assertTrue(np.allclose(surface.data["rgba"][0, :3], color_to_rgb(RED)))
        self.assertAlmostEqual(float(surface.data["rgba"][0, 3]), 0.5)

    def test_ce_call_defaults_to_ce_blue(self):
        surface = Surface(saddle, resolution=(4, 4))
        self.assertTrue(np.allclose(surface.data["rgba"][0, :3], color_to_rgb(BLUE_D)))

    def test_gl_spelling_is_unchanged(self):
        self.assertTrue(np.allclose(Torus().data["rgba"][0, :3], color_to_rgb(GREY)))
        parametric = ParametricSurface(saddle, u_range=(-1, 1), v_range=(-1, 1),
                                       resolution=(5, 5))
        self.assertEqual(parametric.get_points().shape, (25, 3))


if __name__ == "__main__":
    unittest.main()

"""Surfaces as control nets (docs/phase_b2_plan.md): construction, the CPU
grid the reference renderers draw, alignment, and what stays untouched."""

import os
import tempfile
import unittest

import numpy as np
from PIL import Image

from maniml.constants import RIGHT
from maniml.mobject.three_dimensions import Sphere, Square3D, SurfaceMesh, Torus
from maniml.mobject.types.surface import ParametricSurface, Surface, TexturedSurface
from maniml.mobject.types.vectorized_mobject import VMobject
from maniml.mobject.types.vmobject_3d import VMobject3D
from maniml.utils import bezier_net


def sampled(surface):
    """What today's construction produced: uv_func on the resolution grid."""
    nu, nv = surface.resolution
    return np.array([surface.uv_func(u, v) for u in np.linspace(*surface.u_range, nu)
                     for v in np.linspace(*surface.v_range, nv)], dtype=float)


class NetConstruction(unittest.TestCase):
    def test_resolution_is_the_net_size_and_the_grid_is_the_sample_grid(self):
        sphere = Sphere(radius=1.4)
        self.assertEqual(sphere.resolution, (101, 51))
        self.assertEqual(sphere.get_num_points(), 101 * 51)
        # The reference renderers draw the net evaluated at two steps per
        # patch: exactly the samples the construction took, so their
        # pixels are unchanged.
        np.testing.assert_allclose(sphere.get_grid_points(), sampled(sphere), atol=2e-6)
        np.testing.assert_allclose(sphere.get_shader_data()["point"],
                                   sampled(sphere)[sphere.get_triangle_indices()], atol=2e-6)
        # The handles of the net lie off the sphere; the surface lies on it.
        radii = np.linalg.norm(sphere.get_points(), axis=1)
        self.assertGreater(radii.max(), 1.4 + 1e-3)
        grid = bezier_net.evaluate(sphere.get_points().reshape(101, 51, 3), 6, 6)
        self.assertLess(np.abs(np.linalg.norm(grid, axis=-1) - 1.4).max(), 1e-3)

    def test_even_resolutions_round_up_to_one_patch(self):
        square = Square3D(side_length=2)
        self.assertEqual(square.resolution, (3, 3))
        self.assertEqual(square.get_num_points(), 9)
        np.testing.assert_allclose(square.get_grid_points()[:, 2], 0, atol=1e-12)
        self.assertEqual(len(square.get_triangle_indices()), 6 * 4)
        plane = Surface(u_range=(-1, 1), v_range=(-1, 1), resolution=(2, 2))
        self.assertEqual(plane.resolution, (3, 3))

    def test_uv_to_point_is_exact_on_the_samples_and_smooth_between(self):
        surface = ParametricSurface(lambda u, v: [u, v, u * u + v], u_range=(0, 2), v_range=(0, 1),
                                    resolution=(5, 5))
        np.testing.assert_allclose(surface.uv_to_point(1.0, 0.5), [1, .5, 1.5], atol=1e-12)
        np.testing.assert_allclose(surface.uv_to_point(2.0, 1.0), [2, 1, 5], atol=1e-12)
        # u² is quadratic: the net reproduces it everywhere, not only at samples.
        np.testing.assert_allclose(surface.uv_to_point(1.3, .2), [1.3, .2, 1.3 ** 2 + .2], atol=1e-12)

    def test_grid_cache_follows_the_revision(self):
        sphere = Sphere(resolution=(9, 5))
        before = sphere.get_grid_points().copy()
        self.assertIs(sphere.get_grid_data(), sphere.get_grid_data())
        sphere.shift(RIGHT)
        after = sphere.get_grid_points()
        np.testing.assert_allclose(after - before, np.broadcast_to([1, 0, 0], after.shape), atol=1e-6)
        self.assertFalse(after.flags.writeable)

    def test_surface_mesh_lines_lie_on_the_surface(self):
        mesh = SurfaceMesh(Sphere(radius=2), resolution=(5, 3))
        for line in mesh.submobjects:
            radii = np.linalg.norm(line.get_points(), axis=1)
            self.assertLess(np.abs(radii - 2).max(), 0.03)

    def test_textured_surface_carries_image_coordinates_per_control_point(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "t.png")
            Image.new("RGBA", (4, 4), (255, 0, 0, 255)).save(path)
            textured = TexturedSurface(Sphere(resolution=(9, 5)), path)
            self.assertEqual(textured.resolution, (9, 5))
            grid = textured.get_shader_data()
            self.assertEqual(grid.dtype.names, ("point", "d_normal_point", "im_coords", "opacity"))
            self.assertLessEqual(grid["im_coords"].max(), 1.0)
            self.assertGreaterEqual(grid["im_coords"].min(), 0.0)

    def test_vmobject3d_keeps_its_explicit_mesh(self):
        path = VMobject(fill_opacity=.5).set_points_as_corners(
            [[-1, -1, 0], [1, -1, 0], [1, 1, 1], [-1, 1, 0], [-1, -1, 0]])
        surface = VMobject3D(path, resolution=12)
        self.assertFalse(surface.net)
        np.testing.assert_array_equal(surface.get_shader_data()["point"],
                                      surface.get_points()[surface.get_triangle_indices()])


class NetAlignment(unittest.TestCase):
    def test_transform_alignment_subdivides_without_moving_either_surface(self):
        coarse, fine = Sphere(radius=1, resolution=(9, 5)), Torus()
        # The coarse sphere's true deviation, from a dense evaluation.
        worst = np.abs(np.linalg.norm(bezier_net.evaluate(coarse.get_net(), 40, 40)[..., :3], axis=-1) - 1).max()
        coarse.align_points(fine)
        self.assertEqual(coarse.resolution, fine.resolution)
        self.assertEqual(coarse.get_num_points(), fine.get_num_points())
        # The subdivided coarse sphere is still the coarse sphere: no
        # evaluated point is further from the unit sphere than it could be.
        radii = np.linalg.norm(bezier_net.evaluate(coarse.get_net(), 4, 4)[..., :3], axis=-1)
        self.assertLessEqual(np.abs(radii - 1).max(), worst + 1e-4)  # two samplings of one surface
        self.assertGreater(worst, 0.01, "a four-by-two patch sphere is visibly approximate")
        self.assertEqual(len(coarse.get_triangle_indices()), len(fine.get_triangle_indices()))
        # And a blend is now a blend of control points of equal count.
        coarse.interpolate(coarse.copy(), fine, 0.5)
        self.assertEqual(coarse.get_num_points(), fine.get_num_points())


if __name__ == "__main__":
    unittest.main()

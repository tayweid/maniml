"""The biquadratic net mathematics of Phase B2 (docs/phase_b2_plan.md)."""

import unittest

import numpy as np

from maniml.utils.bezier_net import (
    align, arc_net, evaluate, evaluate_at, interpolating_net, net_shape, patch_counts,
    second_difference, steps_for, subdivide,
)


def sphere_net(around=16, along=8, radius=1.0):
    """The sixteen-curve circle swept along the eight-curve half circle:
    the product of the two arc nets, a ``(33, 17, 3)`` net."""
    circle = arc_net(around)  # (33, 2): cos, sin with the handles pushed out
    profile = arc_net(along, np.pi)  # (17, 2): the half circle from (1, 0) to (-1, 0)
    # Profile x is the radius at v (sin v), profile y turned into the axis
    # gives -cos v: rotate the half circle so it runs pole to pole.
    r, z = profile[:, 1], -profile[:, 0]
    net = np.empty((2 * around + 1, 2 * along + 1, 3))
    net[:, :, 0] = circle[:, 0][:, None] * r[None, :]
    net[:, :, 1] = circle[:, 1][:, None] * r[None, :]
    net[:, :, 2] = z[None, :]
    return radius * net


class NetShape(unittest.TestCase):
    def test_resolution_rounds_up_to_odd_and_at_least_three(self):
        self.assertEqual(net_shape((2, 2)), (3, 3))
        self.assertEqual(net_shape((101, 51)), (101, 51))
        self.assertEqual(net_shape((100, 1)), (101, 3))
        self.assertEqual(net_shape((0, 0)), (0, 0))
        self.assertEqual(patch_counts((33, 17)), (16, 8))
        self.assertEqual(patch_counts((0, 5)), (0, 0))
        with self.assertRaises(ValueError):
            patch_counts((4, 5))


class Interpolation(unittest.TestCase):
    def test_net_passes_through_every_sample(self):
        rng = np.random.default_rng(1)
        samples = rng.normal(size=(7, 9, 3))
        net = interpolating_net(samples)
        grid = evaluate(net, 2, 2)  # two steps per patch: anchors and midpoints
        np.testing.assert_allclose(grid, samples, atol=1e-12)
        self.assertEqual(net.shape, samples.shape)

    def test_plane_is_exact_everywhere(self):
        u, v = np.meshgrid(np.linspace(-1, 1, 5), np.linspace(0, 2, 7), indexing="ij")
        samples = np.stack([u, v, 3 * u - 2 * v + 1], axis=-1)
        net = interpolating_net(samples)
        rng = np.random.default_rng(2)
        pu, pv = rng.uniform(0, 1, 50), rng.uniform(0, 1, 50)
        points = evaluate_at(net, pu, pv)
        np.testing.assert_allclose(points[:, 2], 3 * points[:, 0] - 2 * points[:, 1] + 1, atol=1e-12)
        np.testing.assert_allclose(points[:, 0], -1 + 2 * pu, atol=1e-12)

    def test_evaluate_at_agrees_with_the_grid(self):
        net = sphere_net()
        grid = evaluate(net, 3, 5)
        pu, pv = patch_counts(net.shape[:2])
        u = np.linspace(0, 1, pu * 3 + 1)
        v = np.linspace(0, 1, pv * 5 + 1)
        uu, vv = np.meshgrid(u, v, indexing="ij")
        np.testing.assert_allclose(evaluate_at(net, uu, vv), grid, atol=1e-12)


class Sphere(unittest.TestCase):
    def test_sixteen_curve_sphere_is_within_hundredths_of_a_percent(self):
        net = sphere_net(radius=2.0)
        grid = evaluate(net, 8, 8)
        radii = np.linalg.norm(grid, axis=-1)
        self.assertLess(np.abs(radii / 2.0 - 1).max(), 5e-4)
        self.assertGreater(np.abs(radii / 2.0 - 1).max(), 1e-5, "a polynomial sphere is not exact")
        # Poles and the seam.
        np.testing.assert_allclose(grid[:, 0], np.broadcast_to([0, 0, -2], grid[:, 0].shape), atol=1e-12)
        np.testing.assert_allclose(grid[:, -1], np.broadcast_to([0, 0, 2], grid[:, -1].shape), atol=1e-12)
        np.testing.assert_allclose(grid[0], grid[-1], atol=1e-12)

    def test_derivative_normals_are_radial_away_from_the_poles(self):
        net = sphere_net()
        grid, du, dv = evaluate(net, 4, 4, derivatives=True)
        normals = np.cross(du, dv)
        interior = normals[:, 2:-2]
        unit = interior / np.linalg.norm(interior, axis=-1, keepdims=True)
        radial = grid[:, 2:-2] / np.linalg.norm(grid[:, 2:-2], axis=-1, keepdims=True)
        self.assertGreater(np.abs((unit * radial).sum(-1)).min(), 0.999)
        self.assertEqual(float(np.linalg.norm(normals[:, 0], axis=-1).max()), 0.0, "the pole row is degenerate")


class Subdivision(unittest.TestCase):
    def _mapped(self, u, count, index, t):
        i = np.minimum((u * count).astype(int), count - 1)
        local = u * count - i
        new = np.where(i < index, i + local,
                       np.where(i > index, i + 1 + local,
                                np.where(local < t, index + local / t, index + 1 + (local - t) / (1 - t))))
        return new / (count + 1)

    def test_split_evaluates_to_the_same_surface(self):
        net = sphere_net()
        rng = np.random.default_rng(3)
        u, v = rng.uniform(0, 1, 200), rng.uniform(0, 1, 200)
        for axis, index, t in ((0, 5, 0.5), (1, 0, 0.3), (0, 15, 0.7)):
            with self.subTest(axis=axis, index=index, t=t):
                split = subdivide(net, axis, index, t)
                count = patch_counts(net.shape[:2])[axis]
                self.assertEqual(split.shape[axis], net.shape[axis] + 2)
                mapped = (self._mapped(u, count, index, t), v) if axis == 0 else (u, self._mapped(v, count, index, t))
                np.testing.assert_allclose(evaluate_at(split, *mapped), evaluate_at(net, u, v), atol=1e-12)

    def test_alignment_matches_patch_counts_without_moving_either_surface(self):
        coarse = sphere_net(around=8, along=4, radius=1.0)
        fine = sphere_net(around=16, along=8, radius=3.0)
        a, b = align(coarse, fine)
        self.assertEqual(a.shape, b.shape)
        self.assertEqual(b.shape, fine.shape)
        np.testing.assert_array_equal(b, fine)
        # Subdivision cannot move the surface: the aligned coarse sphere is
        # no further from the unit sphere than the coarse net itself.
        radii = np.linalg.norm(evaluate(a, 6, 6), axis=-1)
        worst = np.abs(np.linalg.norm(evaluate(coarse, 12, 12), axis=-1) - 1).max()
        self.assertLessEqual(np.abs(radii - 1).max(), worst + 1e-9)
        self.assertGreater(worst, 1e-3, "an eight-curve circle is visibly approximate")
        plane, other = align(interpolating_net(np.zeros((3, 3, 3)) + [[[1, 2, 3]]]),
                             interpolating_net(np.zeros((7, 5, 3))))
        self.assertEqual(plane.shape, (7, 5, 3))
        np.testing.assert_allclose(plane, np.broadcast_to([1, 2, 3], plane.shape), atol=1e-12)


class Density(unittest.TestCase):
    def test_steps_follow_the_second_difference(self):
        self.assertEqual(second_difference(interpolating_net(np.zeros((5, 5, 3)))), 0.0)
        self.assertEqual(steps_for(0.0), 1)
        self.assertEqual(steps_for(1.0), 1)  # a quarter pixel of deviation needs one step
        self.assertEqual(steps_for(4.0), 2)
        self.assertEqual(steps_for(100.0), 10)
        self.assertEqual(steps_for(1e9), 32)
        self.assertEqual(steps_for(float("nan")), 1)
        sphere = second_difference(sphere_net())
        self.assertGreater(sphere, 0.05)
        self.assertLess(sphere, 0.2)


if __name__ == "__main__":
    unittest.main()

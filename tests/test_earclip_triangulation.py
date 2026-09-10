"""Native Earcut calls must preserve concavities and holes in production fills."""

import unittest
from unittest.mock import patch

import numpy as np

from maniml.mobject.geometry import Polygon, Square
from maniml.mobject.types.vectorized_mobject import VMobject
from maniml.mobject.types.vmobject_3d import VMobject3D
from maniml.rendering.shader_wrapper import VShaderWrapper
from maniml.utils.space_ops import earclip_triangulation


def covered(vertices, indices, point):
    triangles = vertices[np.asarray(indices).reshape(-1, 3), :2]
    edge = np.roll(triangles, -1, axis=1) - triangles
    relative = np.asarray(point) - triangles
    side = edge[..., 0]*relative[..., 1] - edge[..., 1]*relative[..., 0]
    area = (edge[:, 0, 0]*edge[:, 1, 1] - edge[:, 0, 1]*edge[:, 1, 0])
    return bool(np.any(((side >= -1e-9).all(axis=1) |
                       (side <= 1e-9).all(axis=1)) & (abs(area) > 1e-12)))


class EarclipTriangulation(unittest.TestCase):
    def test_real_binding_accepts_list_ends_and_float64_vertices(self):
        points = np.array([[0., 0.], [3., 0.], [3., 1.],
                           [1., 1.], [1., 3.], [0., 3.]])
        indices = earclip_triangulation(points, [len(points)])
        self.assertEqual(len(indices), 12)
        self.assertTrue(covered(points, indices, [.4, 2.1]))
        self.assertTrue(covered(points, indices, [2.1, .4]))
        self.assertFalse(covered(points, indices, [2.1, 2.1]))

    def test_production_triangulation_does_not_fall_back_to_fan(self):
        concave = Polygon([0, 0, 0], [3, 0, 0], [3, 1, 0],
                          [1, 1, 0], [1, 3, 0], [0, 3, 0], fill_opacity=1)
        hole = VMobject(fill_opacity=1)
        hole.set_points_as_corners([[-2, -2, 0], [2, -2, 0], [2, 2, 0],
                                    [-2, 2, 0], [-2, -2, 0]])
        hole.start_new_path([-1, -1, 0])
        for point in ([-1, 1, 0], [1, 1, 0], [1, -1, 0], [-1, -1, 0]):
            hole.add_line_to(point)
        cases = [(Square(fill_opacity=1), [.2, .3], [2.1, .3]),
                 (concave, [.4, 2.1], [2.1, 2.1]),
                 (hole, [1.5, .3], [.2, .3])]
        for path, inside, outside in cases:
            for axes in ((0, 1), (0, 2), (1, 2)):
                with self.subTest(shape=type(path).__name__, axes=axes):
                    oriented = path.copy()
                    points = np.zeros_like(path.get_points())
                    points[:, axes] = path.get_points()[:, :2]
                    oriented.set_points(points)
                    before = oriented.get_points().copy()
                    with patch.object(VMobject3D, "init_simple_triangulation",
                                      side_effect=AssertionError("unexpected center fan")):
                        vertices, indices = VShaderWrapper._get_triangulation(oriented)
                    self.assertTrue(covered(vertices[:, axes], indices, inside))
                    self.assertFalse(covered(vertices[:, axes], indices, outside))
                    np.testing.assert_array_equal(oriented.get_points(), before)


if __name__ == "__main__":
    unittest.main()

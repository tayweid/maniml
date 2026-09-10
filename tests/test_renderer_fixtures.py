"""Independent source-coverage checks for the shared renderer corpus.

The oracle uses ray crossings of sampled source contours, not a fill mesh,
renderer shader, serialized batch, or cached raster image. Interior probes are
far from boundaries, so the conservative sampling is sufficient for these
specific fixtures; it is not a production curve-containment implementation.
"""

import unittest

import numpy as np

from tests.renderer_fixtures import get_fixture, renderer_cases


def _winding_at(path, point):
    px, py = point
    winding = 0
    for contour in path.get_subpaths():
        samples = []
        for index in range(0, len(contour) - 2, 2):
            p0, p1, p2 = contour[index:index + 3, :2]
            t = np.linspace(0, 1, 32, endpoint=False)[:, None]
            samples.extend((1 - t) ** 2 * p0 + 2 * (1 - t) * t * p1 + t ** 2 * p2)
        for start, end in zip(samples, samples[1:] + samples[:1]):
            cross = (end[0] - start[0]) * (py - start[1]) - (end[1] - start[1]) * (px - start[0])
            if start[1] <= py < end[1] and cross > 0:
                winding += 1
            elif end[1] <= py < start[1] and cross < 0:
                winding -= 1
    return winding


class RendererFixtureCoverage(unittest.TestCase):
    def test_source_contours_satisfy_interior_probes(self):
        for case in renderer_cases():
            if not case.probes:
                continue
            scene = case.build()
            for probe in case.probes:
                with self.subTest(fixture=case.name, point=probe.point):
                    winding = _winding_at(scene.mobjects[0], probe.point)
                    self.assertEqual(winding != 0, probe.covered)

    def test_repeated_contour_distinguishes_nonzero_from_even_odd(self):
        path = get_fixture("repeated_winding").build().mobjects[0]
        winding = _winding_at(path, (0, 0))
        self.assertEqual(abs(winding), 2)
        self.assertNotEqual(winding != 0, winding % 2 != 0)

    def test_quad_morph_changes_interior_without_changing_point_count(self):
        paths = [get_fixture(name).build().mobjects[0] for name in (
            "quad_convex", "quad_before_flip", "quad_after_flip", "quad_concave",
        )]
        self.assertEqual(len({path.get_num_points() for path in paths}), 1)
        wedge_probe = (-1 / 3, 1 / 3)
        self.assertNotEqual(_winding_at(paths[0], wedge_probe), 0)
        self.assertEqual(_winding_at(paths[-1], wedge_probe), 0)


if __name__ == "__main__":
    unittest.main()

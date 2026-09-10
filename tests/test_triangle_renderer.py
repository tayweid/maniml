"""Opt-in real-device checks for the A0 comparison harness, not production CI.

Set MANIML_TEST_GPU=1 on a machine with the optional locked WebGPU dependencies.
"""

import os
import unittest

import numpy as np


@unittest.skipUnless(os.environ.get("MANIML_TEST_GPU") == "1", "A0 real GPU check not requested")
class TriangleRendererGPU(unittest.TestCase):
    @unittest.skipUnless(os.environ.get("MANIML_LYON_LIBRARY"), "optional Lyon helper not built")
    def test_uniform_opacity_refresh_reaches_gpu_without_retessellation(self):
        from benchmarks.triangle_renderer import TrianglePrototype
        from benchmarks.triangle_scene import TriangleMeshCache, prepare_triangle_frame
        from maniml.mobject.geometry import Square
        from maniml.web.triangle_geometry import LyonFillTessellator
        from tests.renderer_fixtures import build_scene

        square = Square(fill_opacity=.25, stroke_width=0)
        scene = build_scene(square, resolution=(64, 36))
        scene.camera.background_rgba = [0, 0, 0, 0]
        cache, tessellator, renderer = TriangleMeshCache(), LyonFillTessellator(), TrianglePrototype()
        first = prepare_triangle_frame(scene, tessellator, mesh_cache=cache)
        before, _ = renderer.frame(first, image=True)
        square.set_fill(opacity=.5)
        second = prepare_triangle_frame(scene, tessellator, mesh_cache=cache)
        after, _ = renderer.frame(second, image=True)
        self.assertEqual(second.mesh_cache_stats["regenerations"], 0)
        self.assertEqual(second.mesh_cache_stats["paint_updates"], 1)
        self.assertEqual(np.asarray(before)[18, 32, 3], 64)
        self.assertEqual(np.asarray(after)[18, 32, 3], 128)
        third = prepare_triangle_frame(scene, tessellator, mesh_cache=cache)
        _, unchanged = renderer.frame(third)
        self.assertEqual(unchanged["uploaded_geometry_bytes"], 0)

    def test_analytic_shader_preserves_hole_and_single_opacity(self):
        from benchmarks.analytic_scene import AnalyticMeshCache, prepare_analytic_frame
        from benchmarks.triangle_renderer import TrianglePrototype
        from tests.renderer_fixtures import get_fixture

        scene = get_fixture("annulus_hole").build()
        scene.camera.background_rgba = [0, 0, 0, 0]
        scene.mobjects[0].set_fill(opacity=0.4)
        cache = AnalyticMeshCache()
        frame = prepare_analytic_frame(scene, cache=cache)
        frame.samples = 4
        picture, _ = TrianglePrototype().frame(frame, image=True)
        pixels = np.asarray(picture)
        width, height = frame.resolution
        self.assertEqual(pixels[height // 2, width // 2, 3], 0)
        # Every source/pixel sample is painted at most once. Both ordinary
        # interior triangles and analytic patches therefore cap at alpha0.4.
        self.assertEqual(int(pixels[:, :, 3].max()), 102)
        self.assertGreater(int((pixels[:, :, 3] == 102).sum()), 100)
        again = prepare_analytic_frame(scene, cache=cache)
        self.assertEqual(again.mesh_cache_stats["regenerations"], 0)

    def test_gpu_box_resolve_matches_four_texel_average(self):
        from benchmarks.triangle_renderer import TrianglePrototype
        from benchmarks.triangle_scene import TriangleDraw, TriangleFrame
        from maniml.web.geometry import SURFACE_DTYPE
        from tests.renderer_fixtures import build_scene

        scene = build_scene(resolution=(64, 36))
        scene.camera.refresh_uniforms()
        vertices = np.zeros(3, dtype=SURFACE_DTYPE)
        vertices["point"] = [[-3.25, -1.17, 0], [2.73, -1.17, 0], [0, 1.62, 0]]
        vertices["d_normal_point"] = vertices["point"] + [0, 0, 0.001]
        vertices["rgba"] = [[1, 0, 0, 0.4], [0, 1, 0, 0.7], [0, 0, 1, 1]]
        frame = TriangleFrame((64, 36), (0.2, 0.1, 0.3, 0.25), 1,
                              [TriangleDraw("surface", vertices, scene.camera.uniforms, count=3)])
        renderer = TrianglePrototype()
        high, initial = renderer.frame(frame, image=True)
        low, reused = renderer.frame(frame, image=True, output_resolution=(32, 18))
        expected = np.asarray(high).reshape(18, 2, 32, 2, 4).mean(axis=(1, 3))
        self.assertLessEqual(float(np.abs(np.asarray(low) - expected).max()), 0.501)
        self.assertGreater(initial["uploaded_geometry_bytes"], 0)
        self.assertEqual(reused["uploaded_geometry_bytes"], 0)
        self.assertEqual(reused["passes"], 2)
        with self.assertRaisesRegex(ValueError, "exactly 2x"):
            renderer.frame(frame, output_resolution=(31, 18))
        # Reallocate a different-size target and return to MSAA after resolving.
        frame.resolution, frame.samples = (32, 18), 4
        picture, _ = renderer.frame(frame, image=True)
        self.assertEqual(picture.size, (32, 18))

    def test_ordered_output_preserves_all_fixture_pixels(self):
        from benchmarks.ordered_output import OrderedOutputControl
        from maniml.web.geometry import parse_geometry_message, serialize_scene
        from maniml.web.wgpu_renderer import WgpuRenderer
        from tests.renderer_fixtures import renderer_cases

        current, ordered = WgpuRenderer(), OrderedOutputControl()
        for samples in (0, 4):
            for fixture in renderer_cases():
                with self.subTest(samples=samples, fixture=fixture.name):
                    scene = fixture.build()
                    scene.camera.samples = samples
                    header, data = parse_geometry_message(serialize_scene(scene))
                    expected = np.asarray(current.render(header, data))
                    actual = np.asarray(ordered.render(header, data))
                    np.testing.assert_array_equal(actual, expected)


if __name__ == "__main__":
    unittest.main()

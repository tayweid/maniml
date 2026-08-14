"""Fidelity test for the WebGPU backend (the future canonical renderer).

Same methodology as test_gl_port, different GPU API: render a scene
natively, serialize it, render the payload with wgpu + the WGSL
shaders, pixel-diff. Thresholds are slightly looser than the GL
reference tests: Metal's rasterizer and f16 blending round differently
than OpenGL's at anti-aliased edges.
"""

import unittest

import numpy as np

try:
    import wgpu  # noqa: F401
    HAVE_WGPU = True
except ImportError:
    HAVE_WGPU = False

from tests.test_gl_port import build_scene
from maniml.web.geometry import serialize_scene, parse_geometry_message


@unittest.skipUnless(HAVE_WGPU, "wgpu not installed")
class WgpuPortFidelity(unittest.TestCase):
    def test_wgpu_matches_native_2d(self):
        scene = build_scene()
        native = np.asarray(scene.get_image().convert("RGB"), dtype=np.float64)

        header, vertex_bytes = parse_geometry_message(serialize_scene(scene))
        self.assertEqual(header["unsupported"], [])

        from maniml.web.wgpu_renderer import WgpuRenderer
        ported = WgpuRenderer().render(header, vertex_bytes)
        ported = np.asarray(ported.convert("RGB"), dtype=np.float64)

        self.assertEqual(native.shape, ported.shape)
        diff = np.abs(native - ported)
        mean_diff = diff.mean()
        frac_off = (diff.max(axis=2) > 24).mean()
        self.assertLess(
            mean_diff, 1.5,
            f"wgpu mean |diff| {mean_diff:.3f}; "
            f"{frac_off * 100:.3f}% of pixels off by >24")
        self.assertLess(
            frac_off, 0.005,
            f"wgpu: {frac_off * 100:.3f}% of pixels off by >24 "
            f"(mean {mean_diff:.3f})")


if __name__ == "__main__":
    unittest.main()

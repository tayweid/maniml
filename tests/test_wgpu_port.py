"""Fidelity tests for the WebGPU backend (the future canonical renderer).

Same methodology as test_gl_port, different GPU API: render a scene
natively, serialize it, render the payload with wgpu + the WGSL
shaders, pixel-diff. Covers the whole parity-ledger scope: 2D winding
fills/strokes/Text, clip planes, dot clouds, images, depth-tested 3D
with MSAA, surfaces and textured surfaces.

Thresholds are slightly looser than the GL reference tests: Metal's
rasterizer, MSAA resolve, and f16 blending round differently than
OpenGL's at anti-aliased edges.
"""

import unittest

import numpy as np

try:
    import wgpu  # noqa: F401
    HAVE_WGPU = True
except ImportError:
    HAVE_WGPU = False

from tests.test_gl_port import (
    build_scene, build_clip_scene, build_dot_scene, build_image_scene,
    build_3d_scene, build_surfaces_scene,
)
from maniml.web.geometry import serialize_scene, parse_geometry_message

# (name, scene builder, mean threshold, fraction-off-by->24 threshold)
CASES = [
    ("2d", build_scene, 1.5, 0.005),
    ("clip", build_clip_scene, 1.5, 0.005),
    ("dots", build_dot_scene, 1.5, 0.005),
    ("image", build_image_scene, 1.5, 0.005),
    ("3d", build_3d_scene, 2.0, 0.01),
    ("surfaces", build_surfaces_scene, 2.0, 0.01),
]


@unittest.skipUnless(HAVE_WGPU, "wgpu not installed")
class WgpuPortFidelity(unittest.TestCase):
    def test_wgpu_matches_native(self):
        from maniml.web.wgpu_renderer import WgpuRenderer
        # Capture every native image before instantiating the wgpu
        # renderer (native standalone-GL contexts and wgpu coexist, but
        # keep the native work batched up front like the GL tests do)
        captured = []
        for name, builder, mean_max, frac_max in CASES:
            scene = builder()
            native = np.asarray(
                scene.get_image().convert("RGB"), dtype=np.float64)
            header, vertex_bytes = parse_geometry_message(
                serialize_scene(scene))
            self.assertEqual(header["unsupported"], [], name)
            captured.append(
                (name, native, header, vertex_bytes, mean_max, frac_max))

        renderer = WgpuRenderer()
        for name, native, header, vertex_bytes, mean_max, frac_max in captured:
            with self.subTest(case=name):
                ported = renderer.render(header, vertex_bytes)
                ported = np.asarray(ported.convert("RGB"), dtype=np.float64)
                self.assertEqual(native.shape, ported.shape)
                diff = np.abs(native - ported)
                mean_diff = diff.mean()
                frac_off = (diff.max(axis=2) > 24).mean()
                self.assertLess(
                    mean_diff, mean_max,
                    f"[{name}] mean |diff| {mean_diff:.3f}; "
                    f"{frac_off * 100:.3f}% of pixels off by >24")
                self.assertLess(
                    frac_off, frac_max,
                    f"[{name}] {frac_off * 100:.3f}% of pixels off by >24 "
                    f"(mean {mean_diff:.3f})")


if __name__ == "__main__":
    unittest.main()

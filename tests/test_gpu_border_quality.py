"""Production-source image regression for GPU borders against CPU Phase A."""

import os
import unittest

import numpy as np

from maniml.web.generated_geometry import serialize_generated_frame
from maniml.web.geometry import GeometryCache, parse_geometry_message
from maniml.web.triangle_geometry import LyonFillTessellator
from maniml.web.triangle_scene import TriangleMeshCache, prepare_triangle_frame
from tests.renderer_quality_fixtures import build_quality_frame, _source_digest


@unittest.skipUnless(os.environ.get("MANIML_TEST_GPU") == "1", "GPU image comparison not requested")
class GpuBorderQuality(unittest.TestCase):
    def test_real_text_perspective_hairlines_and_translucent_borders(self):
        from maniml.web.wgpu_renderer import WgpuRenderer
        drivers = (WgpuRenderer(), WgpuRenderer())
        tessellator = LyonFillTessellator()
        try:
            for content in ("tex", "perspective", "hairlines", "border"):
                for view in ("normal", "zoom"):
                    with self.subTest(content=content, view=view):
                        quality = build_quality_frame(content, view, border_policy="production_default")
                        scene = quality.scene
                        source = _source_digest(scene.mobjects)
                        images = []
                        for gpu, driver in zip((False, True), drivers):
                            frame = prepare_triangle_frame(scene, tessellator,
                                mesh_cache=TriangleMeshCache(), fill_borders=True, gpu_borders=gpu)
                            frame.samples, frame.supersample = 4, 2
                            message = serialize_generated_frame(frame, scene.camera.uniforms, GeometryCache())
                            header, payload = parse_geometry_message(message)
                            images.append(np.asarray(driver.render(header, payload), dtype=int))
                            self.assertEqual(_source_digest(scene.mobjects), source)
                        difference = np.abs(images[0] - images[1])
                        # The local Metal run is pixel-exact for all eight
                        # controls. Other devices may move a float32 edge
                        # across one of sixteen final AA samples. Bound that
                        # quantum and the affected fraction within each ROI.
                        self.assertLessEqual(difference.max(), 17)
                        for roi in quality.rois:
                            left, top, right, bottom = roi.box
                            error = difference[top:bottom, left:right]
                            self.assertLessEqual(np.any(error != 0, axis=2).mean(), .002)
        finally:
            for driver in drivers:
                driver.close()


if __name__ == "__main__":
    unittest.main()

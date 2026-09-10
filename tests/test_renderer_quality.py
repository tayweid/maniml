"""GPU-free contracts for the optional A0 quality harness.

The harness imports wgpu, so these checks skip if that optional dependency is
absent. They never allocate an adapter/device, render a frame, or invoke TeX.
"""

from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image

from maniml.mobject.geometry import Line
from maniml.mobject.mobject import Group
from tests.renderer_fixtures import build_scene
from tests.renderer_quality_fixtures import build_quality_frame


@unittest.skipUnless(importlib.util.find_spec("wgpu"), "optional wgpu dependency not installed")
class RendererQualityContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import wgpu
        # Fail loudly if a future contract helper starts allocating a real GPU.
        cls.adapter_guard = patch.object(
            wgpu.gpu, "request_adapter_sync", side_effect=AssertionError("CPU test requested a GPU"))
        cls.adapter_guard.start()
        cls.addClassCleanup(cls.adapter_guard.stop)
        from benchmarks.renderer_quality import read_native, source_contract, supersampled_scene
        cls.read_native = staticmethod(read_native)
        cls.source_contract = staticmethod(source_contract)
        cls.supersampled_scene = staticmethod(supersampled_scene)

    def _golden_manifest(self, quality, directory):
        path = directory / "reference.png"
        Image.new("RGBA", quality.scene.camera.draw_fbo.size, (20, 28, 36, 255)).save(path)
        # Roundtrip exactly as an on-disk golden manifest does, not just an
        # in-memory structure containing NumPy values or tuples.
        return json.loads(json.dumps({"cases": {quality.name: {
            "source_contract": self.source_contract(quality), "image": path.name,
            "sha256": sha256(path.read_bytes()).hexdigest(),
        }}}))

    def test_unchanged_source_contract_survives_manifest_roundtrip(self):
        quality = build_quality_frame("hairlines")
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            manifest = self._golden_manifest(quality, directory)
            picture = self.read_native(quality, directory, manifest)
            self.assertEqual(picture.size, quality.scene.camera.draw_fbo.size)
            self.assertEqual(self.source_contract(quality), manifest["cases"][quality.name]["source_contract"])

    def test_region_metrics_do_not_claim_the_full_frame_gate(self):
        from benchmarks.renderer_quality import difference_metrics
        pixels = np.full((4, 4, 4), 255, dtype=np.uint8)
        frame = difference_metrics(pixels, pixels)
        region = difference_metrics(pixels, pixels, scope="region")
        self.assertTrue(frame["existing_rgb_threshold_met"])
        self.assertNotIn("existing_rgb_threshold_met", region)
        self.assertEqual(region["mean_rgb_difference"], 0)
        self.assertEqual(region["scope"], "region")

    def test_native_reference_rejects_live_points_aa_uniform_and_draw_order_changes(self):
        def change_points(quality):
            quality.scene.mobjects[0].data["point"][:, 0] += 0.25

        def change_aa(quality):
            quality.scene.mobjects[0].uniforms["anti_alias_width"] *= 3

        def change_order(quality):
            # Preserve object geometry, styles, and z_index; only change which
            # equally ordered source object is drawn first.
            quality.scene.render_groups = [Group(*reversed(quality.scene.mobjects))]

        for change in (change_points, change_aa, change_order):
            with self.subTest(change=change.__name__), tempfile.TemporaryDirectory() as temporary:
                quality = build_quality_frame("hairlines")
                directory = Path(temporary)
                manifest = self._golden_manifest(quality, directory)
                change(quality)
                with self.assertRaisesRegex(ValueError, "native golden source changed"):
                    self.read_native(quality, directory, manifest)

    def test_native_reference_rejects_live_background_samples_and_height_changes(self):
        def change_background(quality):
            quality.scene.camera.background_rgba = [0.4, 0.1, 0.8, 1.0]

        def change_samples(quality):
            quality.scene.camera.samples = 4

        def change_height(quality):
            width, height = quality.scene.camera.draw_fbo.size
            quality.scene.camera.draw_fbo.size = (width, height * 2)

        # These changes leave the old camera uniform contract unchanged. In
        # particular, pixel_size depends on width and misses height-only resize.
        for change in (change_background, change_samples, change_height):
            with self.subTest(change=change.__name__), tempfile.TemporaryDirectory() as temporary:
                quality = build_quality_frame("hairlines")
                directory = Path(temporary)
                manifest = self._golden_manifest(quality, directory)
                original_uniforms = dict(quality.scene.camera.uniforms)
                change(quality)
                quality.scene.camera.refresh_uniforms()
                self.assertEqual(quality.scene.camera.uniforms, original_uniforms)
                with self.assertRaisesRegex(ValueError, "native golden source changed"):
                    self.read_native(quality, directory, manifest)

    def test_supersampling_preserves_authored_stroke_and_final_pixel_aa_width(self):
        from benchmarks.triangle_scene import prepare_triangle_frame

        stroke = Line([-1, 0, 0], [1, 0.4, 0], stroke_width=0.7)
        scene = build_scene(stroke, resolution=(320, 180), samples=4)
        scene.camera.frame.scale(0.75).reorient(12, 25, 0)
        scene.camera.refresh_uniforms()
        # A shared family member must have its AA uniform scaled once.
        scene.render_groups.append(scene.render_groups[0])
        original_points = stroke.get_points().copy()
        original_widths = stroke.data["stroke_width"].copy()
        old_aa = stroke.uniforms["anti_alias_width"]
        old_pixel_size = scene.camera.uniforms["pixel_size"]
        old_fbo, old_draw = scene.camera.fbo, scene.camera.draw_fbo
        with self.supersampled_scene(scene):
            frame = prepare_triangle_frame(scene, None)
            self.assertEqual(frame.resolution, (640, 360))
            self.assertEqual(frame.samples, 1)
            self.assertEqual(stroke.uniforms["anti_alias_width"], 2 * old_aa)
            self.assertEqual(scene.camera.uniforms["pixel_size"], old_pixel_size / 2)
            for draw in frame.draws:
                self.assertAlmostEqual(draw.uniforms["anti_alias_width"] * draw.uniforms["pixel_size"],
                                       old_aa * old_pixel_size)
            np.testing.assert_array_equal(stroke.get_points(), original_points)
            np.testing.assert_array_equal(stroke.data["stroke_width"], original_widths)
        self.assertIs(scene.camera.fbo, old_fbo)
        self.assertIs(scene.camera.draw_fbo, old_draw)
        self.assertEqual(scene.camera.samples, 4)
        self.assertEqual(stroke.uniforms["anti_alias_width"], old_aa)
        self.assertEqual(scene.camera.uniforms["pixel_size"], old_pixel_size)
        # Restoring the source uniform must not change already-prepared draws.
        self.assertEqual(frame.draws[0].uniforms["anti_alias_width"], old_aa * 2)

    def test_supersampling_restores_distinct_targets_and_uniforms_after_failure(self):
        stroke = Line([-1, 0, 0], [1, 0, 0], stroke_width=1)
        scene = build_scene(stroke, resolution=(320, 180), samples=4)
        scene.camera.draw_fbo = SimpleNamespace(size=(320, 180))
        scene.camera.refresh_uniforms()
        old_fbo, old_draw = scene.camera.fbo, scene.camera.draw_fbo
        old_camera_uniforms = dict(scene.camera.uniforms)
        old_stroke_uniforms = dict(stroke.uniforms)
        with self.assertRaisesRegex(RuntimeError, "forced preparation failure"):
            with self.supersampled_scene(scene):
                scene.camera.refresh_uniforms()
                self.assertEqual(scene.camera.samples, 0)
                raise RuntimeError("forced preparation failure")
        self.assertIs(scene.camera.fbo, old_fbo)
        self.assertIs(scene.camera.draw_fbo, old_draw)
        self.assertEqual(scene.camera.samples, 4)
        self.assertEqual(scene.camera.uniforms, old_camera_uniforms)
        self.assertEqual(stroke.uniforms, old_stroke_uniforms)


if __name__ == "__main__":
    unittest.main()

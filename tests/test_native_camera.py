"""Shared native capture boundary: no GL context, straight RGBA, safe copies."""

from copy import deepcopy
import json
import os
import struct
import tempfile
import subprocess
import sys
from contextlib import contextmanager
import unittest
from unittest.mock import Mock, patch

import numpy as np
from PIL import Image

from maniml import Scene, Square, VGroup
from maniml.camera.camera import Camera
from maniml.scene.checkpoints import deepcopy_namespace


def wire():
    header = json.dumps({"renderer": "triangles", "batches": []}).encode()
    return b"\x03" + struct.pack("<I", len(header)) + header


@contextmanager
def without_gl_imports():
    """Reject any attempt to load the retired runtime, installed or not."""
    import builtins
    original = builtins.__import__

    def checked(name, *args, **kwargs):
        if name.split(".")[0] in {"moderngl", "OpenGL"}:
            raise AssertionError(f"retired GL import: {name}")
        return original(name, *args, **kwargs)

    with patch("builtins.__import__", side_effect=checked):
        yield


class NativeCameraBoundary(unittest.TestCase):
    def test_scene_construction_and_batching_need_no_context_or_shader_wrapper(self):
        with without_gl_imports():
            scene = Scene(window=None, camera_config={"resolution": (32, 18)})
            scene.add(VGroup(Square(), Square().shift([1, 0, 0])))
        self.assertIsNone(scene.camera._renderer)
        self.assertEqual(scene.camera.get_pixel_shape(), (32, 18))
        self.assertTrue(scene.render_groups)
        scene.camera.release()

    def test_fresh_import_and_source_scene_do_not_require_gl_packages(self):
        program = """
import importlib.abc
import sys
class RejectGL(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'moderngl', 'OpenGL'}:
            raise AssertionError('retired GL import: ' + fullname)
sys.meta_path.insert(0, RejectGL())
from maniml import *
scene = Scene(window=None, camera_config={'resolution': (32, 18)})
scene.add(Square(), DotCloud(points=[[0, 0, 0]]), Sphere(resolution=(3, 3)))
assert scene.camera._renderer is None
assert not hasattr(scene.mobjects[0], 'shader_wrapper')
"""
        result = subprocess.run([sys.executable, '-c', program], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_shared_order_keeps_fixed_overlays_last_and_z_order_in_each_partition(self):
        scene = Scene(window=None, camera_config={"resolution": (32, 18)})
        world_low = Square(z_index=-20)
        world_high = Square(z_index=100)
        overlay_low = Square(z_index=-10).fix_in_frame()
        overlay_high = Square(z_index=1).fix_in_frame()
        overlay_tie = Square(z_index=1).fix_in_frame()
        scene.add(overlay_high, world_high, overlay_low, world_low, overlay_tie)
        order = [mob for group in scene.render_groups for mob in group.mobjects if mob is not scene.frame]
        self.assertEqual(order, [world_low, world_high, overlay_low, overlay_high, overlay_tie])

    def test_straight_alpha_pixel_reads_and_bottom_up_movie_bytes(self):
        camera = Camera(resolution=(2, 2))
        premultiplied = np.array([[[128, 0, 0, 128], [10, 20, 30, 0]],
                                  [[0, 0, 64, 64], [0, 255, 0, 255]]], dtype=np.uint8)
        renderer = Mock()
        renderer.render.return_value = Image.fromarray(premultiplied)
        with patch("maniml.web.wgpu_renderer.WgpuRenderer", return_value=renderer), \
             patch("maniml.web.geometry.serialize_scene", return_value=wire()) as encode:
            camera.capture(Square())
            self.assertEqual(encode.call_args.kwargs["renderer"], "triangles")
        expected = np.array([[[255, 0, 0, 128], [0, 0, 0, 0]],
                             [[0, 0, 255, 64], [0, 255, 0, 255]]], dtype=np.uint8)
        np.testing.assert_array_equal(camera.get_image(), expected)
        np.testing.assert_array_equal(camera.get_pixel_array(), expected)
        self.assertEqual(camera.read_pixel(0, 0), (255, 0, 0, 128))
        raw = np.frombuffer(camera.get_raw_fbo_data(), dtype=np.uint8).reshape(2, 2, 4)
        np.testing.assert_array_equal(raw, expected[::-1])
        floats = np.frombuffer(camera.get_raw_fbo_data('f4'), dtype=np.float32).reshape(2, 2, 4)
        np.testing.assert_allclose(floats, expected[::-1] / 255, atol=1e-7)
        camera.get_image().putpixel((0, 0), (0, 0, 0, 0))
        self.assertEqual(camera.read_pixel(0, 0), (255, 0, 0, 128))
        camera.release()
        renderer.close.assert_called_once()

    def test_configured_channels_preserve_pixel_array_shape_and_raw_layout(self):
        rgba = np.array([[[10, 20, 30, 255], [40, 50, 60, 128]],
                         [[70, 80, 90, 64], [100, 110, 120, 0]]], dtype=np.uint8)
        for channels in range(1, 5):
            with self.subTest(channels=channels):
                camera = Camera(resolution=(2, 2), n_channels=channels)
                camera._image = Image.fromarray(rgba)
                expected = rgba[..., :channels]
                self.assertEqual(camera.get_pixel_array().shape, (2, 2, channels))
                np.testing.assert_array_equal(camera.get_pixel_array(), expected)
                self.assertEqual(camera.get_raw_fbo_data(), expected[::-1].tobytes())
                floats = np.frombuffer(camera.get_raw_fbo_data("f4"), dtype=np.float32)
                np.testing.assert_allclose(floats.reshape(2, 2, channels), expected[::-1] / 255, atol=1e-7)
                self.assertEqual(camera.get_image().mode, "RGBA")
        for invalid in (0, 5, 3.5, True, "3"):
            with self.subTest(invalid=invalid), self.assertRaisesRegex(ValueError, "n_channels"):
                Camera(n_channels=invalid)

    def test_explicit_show_captures_pixels_even_when_live_updates_bypass_native(self):
        scene = Scene(window=None, camera_config={"resolution": (8, 4)})
        scene.add(Square(fill_opacity=1))
        scene._web_viewer = Mock()
        scene._web_viewer.can_skip_native_capture.return_value = True
        with patch.object(scene.camera, "capture") as capture, patch("PIL.Image.Image.show") as show:
            scene.show()
        capture.assert_called_once_with(*scene.render_groups)
        show.assert_called_once()
        scene._web_viewer = None
        with patch.object(scene.camera, "capture") as capture, patch("PIL.Image.Image.show"):
            scene.show()
        capture.assert_called_once_with(*scene.render_groups)

    def test_scene_teardown_releases_native_after_output_even_when_output_fails(self):
        for output_failure in (False, True):
            with self.subTest(output_failure=output_failure):
                scene = Scene(window=None, camera_config={"resolution": (8, 4)})
                scene.camera._renderer = renderer = Mock()
                scene.camera._geometry_cache = object()
                calls = []
                def finish():
                    calls.append("finish")
                    if output_failure:
                        raise ValueError("output failed")
                def close():
                    calls.append("close")
                renderer.close.side_effect = close
                with patch.object(scene.file_writer, "finish", side_effect=finish):
                    if output_failure:
                        with self.assertRaisesRegex(ValueError, "output failed"):
                            scene.tear_down()
                    else:
                        scene.tear_down()
                self.assertEqual(calls, ["finish", "close"])
                self.assertIsNone(scene.camera._renderer)
                self.assertIsNone(scene.camera._geometry_cache)

    def test_native_cleanup_failure_preserves_output_error_and_finishes_other_cleanup(self):
        scene = Scene(window=None, camera_config={"resolution": (8, 4)})
        scene.camera._renderer = Mock()
        scene.camera._renderer.close.side_effect = RuntimeError("GPU cleanup failed")
        viewer = scene.window = Mock()
        with patch.object(scene.file_writer, "finish", side_effect=ValueError("output failed")):
            with self.assertRaisesRegex(ValueError, "output failed") as caught:
                scene.tear_down()
        viewer.destroy.assert_called_once()
        self.assertTrue(any("GPU cleanup failed" in note for note in caught.exception.__notes__))

    def test_failed_capture_resets_transport_before_retry(self):
        camera = Camera(resolution=(2, 2))
        renderer = Mock()
        renderer.render.side_effect = [RuntimeError("submission failed"), Image.new("RGBA", (2, 2))]
        knowledge = []

        def encode(scene, cache, **kwargs):
            knowledge.append(set(cache.sent))
            cache.sent.add("shape")
            return wire()

        with patch("maniml.web.wgpu_renderer.WgpuRenderer", return_value=renderer), \
             patch("maniml.web.geometry.serialize_scene", side_effect=encode):
            with self.assertRaisesRegex(RuntimeError, "submission failed"):
                camera.capture(Square())
            camera.capture(Square())
        self.assertEqual(knowledge, [set(), set()])
        camera.release()

    def test_failed_release_discards_driver_and_sender_state_before_next_capture(self):
        from maniml.web.geometry import GeometryCache

        camera = Camera(resolution=(2, 2))
        camera._renderer = old_renderer = Mock()
        old_renderer.close.side_effect = RuntimeError("GPU cleanup failed")
        camera._geometry_cache = old_cache = GeometryCache()
        old_cache.sent.add("old shape")
        with self.assertRaisesRegex(RuntimeError, "GPU cleanup failed"):
            camera.release()
        self.assertIsNone(camera._renderer)
        self.assertIsNone(camera._geometry_cache)
        camera.release()
        old_renderer.close.assert_called_once()

        new_renderer = Mock()
        new_renderer.render.return_value = Image.new("RGBA", (2, 2), (20, 30, 40, 255))
        knowledge = []

        def encode(scene, cache, **kwargs):
            self.assertIsNot(cache, old_cache)
            knowledge.append(set(cache.sent))
            return wire()

        with patch("maniml.web.wgpu_renderer.WgpuRenderer", return_value=new_renderer) as create, \
             patch("maniml.web.geometry.serialize_scene", side_effect=encode):
            camera.capture(Square())
        create.assert_called_once()
        old_renderer.render.assert_not_called()
        new_renderer.render.assert_called_once()
        self.assertEqual(knowledge, [set()])
        self.assertEqual(camera.read_pixel(0, 0), (20, 30, 40, 255))
        camera.release()
        new_renderer.close.assert_called_once()

    def test_checkpoint_aliases_copy_source_frame_and_omit_native_runtime(self):
        class Uncopyable:
            def __deepcopy__(self, memo):
                raise AssertionError("GPU/runtime objects must not enter a checkpoint")

        camera = Camera(resolution=(8, 4))
        camera._renderer = camera._geometry_cache = Uncopyable()
        copied = deepcopy_namespace({"camera": camera, "frame": camera.frame})
        self.assertIs(copied["camera"].frame, copied["frame"])
        self.assertIsNot(copied["frame"], camera.frame)
        self.assertIsNone(copied["camera"]._renderer)
        self.assertIsNone(copied["camera"]._geometry_cache)
        self.assertIsNone(copied["camera"]._image)
        np.testing.assert_array_equal(copied["frame"].get_points(), camera.frame.get_points())
        self.assertEqual(deepcopy(camera).get_image().size, (8, 4))

    def test_browser_capture_bypass_never_initializes_native_driver(self):
        scene = Scene(window=None, camera_config={"resolution": (32, 18)})
        scene._web_viewer = Mock()
        scene._web_viewer.can_skip_native_capture.return_value = True
        scene.add(Square(fill_opacity=1))
        with patch("maniml.web.wgpu_renderer.WgpuRenderer", side_effect=AssertionError("native capture")):
            scene.update_frame(force_draw=True)
        self.assertIsNone(scene.camera._renderer)
        scene._web_viewer.on_frame_rendered.assert_called_once()

    def test_geometry_only_recorder_bypasses_native_but_movie_output_does_not(self):
        from maniml.web.export import GeometryRecorder

        scene = Scene(window=None, camera_config={"resolution": (32, 18)})
        scene.add(Square(fill_opacity=1))
        recorder = GeometryRecorder(scene)
        scene._web_viewer = recorder
        with patch("maniml.web.export.serialize_scene", return_value=wire()), \
             patch.object(scene.camera, "capture", side_effect=AssertionError("native capture")):
            scene.update_frame(force_draw=True)
        self.assertEqual(len(recorder.frames), 1)
        self.assertIsNone(scene.camera._renderer)
        scene.file_writer.write_to_movie = True
        self.assertFalse(recorder.can_skip_native_capture())
        scene.file_writer.write_to_movie = False
        scene.file_writer.save_last_frame = True
        self.assertFalse(recorder.can_skip_native_capture())


@unittest.skipUnless(os.environ.get("MANIML_TEST_GPU") == "1", "real WebGPU check not requested")
class NativeCameraPixels(unittest.TestCase):
    def test_transparent_capture_png_orientation_and_reinitialization_without_gl(self):
        with without_gl_imports():
            scene = Scene(window=None, camera_config={"resolution": (160, 90), "background_opacity": 0})
            scene.add(Square(side_length=2, fill_color="#FF0000", fill_opacity=.5,
                             stroke_width=0).shift([0, 1.3, 0]))
            scene.add(Square(side_length=2, fill_color="#0000FF", fill_opacity=1,
                             stroke_width=0).shift([0, -1.3, 0]))
            scene.update_frame(force_draw=True)
            image = scene.get_image()
            # Camera's y axis points upward; pixel y increases downward.
            np.testing.assert_allclose(image.getpixel((80, 30)), [255, 0, 0, 128], atol=1)
            np.testing.assert_array_equal(image.getpixel((80, 60)), [0, 0, 255, 255])
            with tempfile.TemporaryDirectory() as directory:
                path = os.path.join(directory, "transparent.png")
                image.save(path)
                with Image.open(path) as saved:
                    np.testing.assert_array_equal(saved, image)
            scene.camera.release()
            scene.update_frame(force_draw=True)
            np.testing.assert_array_equal(scene.get_image(), image)
            scene.camera.release()

    def test_3d_and_textured_native_capture_uses_shared_generated_operations(self):
        from maniml import ThreeDScene
        from maniml.mobject.types.image_mobject import ImageMobject
        from maniml.mobject.types.surface import Surface, TexturedSurface

        with tempfile.TemporaryDirectory() as directory, \
             without_gl_imports():
            path = os.path.join(directory, "texture.png")
            Image.new("RGBA", (8, 8), (40, 160, 230, 255)).save(path)
            scene = ThreeDScene(window=None, camera_config={"resolution": (128, 72)})
            surface = Surface(u_range=(-1, 1), v_range=(-1, 1), resolution=(2, 2), color="#55CC99")
            scene.add(TexturedSurface(surface, path))
            scene.add(ImageMobject(path, height=1).fix_in_frame().shift([2, 0, 0]))
            scene.update_frame(force_draw=True)
            image = np.asarray(scene.get_image())
            self.assertGreater(np.count_nonzero(image[..., :3]), 50)
            self.assertEqual(image.shape, (72, 128, 4))
            scene.camera.release()


if __name__ == '__main__':
    unittest.main()

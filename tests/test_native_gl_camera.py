"""The packaged GL oracle remains explicit and owns its GPU resources."""

from copy import deepcopy
import os
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, Mock, patch

import numpy as np

from maniml import NativeGLCamera, Scene, ShaderWrapper, Square, VGroup
from maniml.camera.camera import Camera
from maniml.camera.camera_frame import CameraFrame
from maniml.rendering import shader_wrapper
from maniml.rendering.gl_shaders import (
    context_resources, get_shader_code_from_file, get_shader_program, release_context_resources,
)


class NativeGLCameraBoundary(unittest.TestCase):
    def setUp(self):
        self.camera = NativeGLCamera.__new__(NativeGLCamera)
        self.camera.ctx = MagicMock()
        self.camera.fbo = Mock()
        self.camera.uniforms = {}
        self.camera.background_rgba = (0, 0, 0, 1)
        self.camera._wrappers = {}
        self.camera._released = False
        self.camera.clear = Mock()
        self.camera.refresh_uniforms = Mock()
        self.factory = patch.object(shader_wrapper, "VShaderWrapper", side_effect=lambda **kwargs: Mock())
        self.factory.start()
        self.addCleanup(self.factory.stop)
        self.addCleanup(self.camera.release)

    def test_public_classes_and_assets_do_not_change_default_camera(self):
        self.assertIs(Scene.camera_class, Camera)
        self.assertIs(ShaderWrapper, shader_wrapper.ShaderWrapper)
        namespace = {}
        exec("from maniml.rendering import *", namespace)
        self.assertIs(namespace["ShaderWrapper"], ShaderWrapper)
        from maniml.utils.shaders import get_shader_code_from_file as compatibility_loader
        self.assertIs(compatibility_loader, get_shader_code_from_file)
        for shader in ("quadratic_bezier/fill/geom.glsl", "quadratic_bezier/stroke/geom.glsl",
                       "surface/vert.glsl", "image/frag.glsl"):
            source = get_shader_code_from_file(shader)
            self.assertIn("#version", source)
            self.assertNotIn("#INSERT", source)

    def test_style_depth_and_replaced_uniform_dict_refresh_retained_wrapper(self):
        path = Square(fill_opacity=.5)
        first = self.camera._get_wrapper(path)
        first.refresh_id.reset_mock()
        path.uniforms = dict(path.uniforms, shading=(.5, .2, .1))
        path.apply_depth_test()
        path.stroke_behind = True
        second = self.camera._get_wrapper(path)
        self.assertIs(second, first)
        second.bind_to_mobject_uniforms.assert_called_with(path.uniforms)
        self.assertTrue(second.depth_test)
        self.assertTrue(second.stroke_behind)
        second.refresh_id.assert_called_once()
        path.replace_shader_code("// test", "// replacement")
        replacement = self.camera._get_wrapper(path)
        self.assertIsNot(replacement, first)
        first.release.assert_called_once()

    def test_capture_refreshes_direct_array_edits_and_copy_contains_no_wrapper(self):
        path = Square(fill_opacity=.5)
        group = VGroup(path)
        self.camera.capture(group)
        wrapper = self.camera._wrappers[path][1]
        first = wrapper.read_in.call_args.args[0][0].copy()
        path.data["point"][:, 0] += .25
        self.camera.capture(group)
        updated = wrapper.read_in.call_args.args[0][0]
        np.testing.assert_allclose(updated["point"][:, 0], first["point"][:, 0] + .25)
        self.assertFalse(hasattr(path, "shader_wrapper"))
        self.assertFalse(hasattr(group, "shader_wrapper"))
        copied = deepcopy(group)
        np.testing.assert_array_equal(copied[0].data, path.data)
        self.assertFalse(hasattr(copied[0], "shader_wrapper"))
        self.camera.capture()
        wrapper.release.assert_called_once()
        self.assertFalse(self.camera._wrappers)

    def test_release_is_idempotent_and_released_camera_cannot_capture(self):
        wrapper = self.camera._get_wrapper(Square())
        self.camera.release()
        self.camera.release()
        wrapper.release.assert_called_once()
        self.camera.ctx.release.assert_called_once()
        with self.assertRaisesRegex(RuntimeError, "released"):
            self.camera.capture()

    def test_release_still_closes_context_when_wrapper_cleanup_fails(self):
        self.camera._get_wrapper(Square()).release.side_effect = RuntimeError("wrapper failed")
        later = self.camera._get_wrapper(Square())
        with self.assertRaisesRegex(RuntimeError, "wrapper failed"):
            self.camera.release()
        later.release.assert_called_once()
        self.camera.ctx.release.assert_called_once()
        self.assertFalse(self.camera._wrappers)

    def test_checkpoint_copy_preserves_camera_frame_alias_without_copying_runtime(self):
        class NoRuntimeCopy(MagicMock):
            def __deepcopy__(self, memo):
                raise AssertionError("GL state entered the checkpoint")

        self.camera.ctx = NoRuntimeCopy()
        self.camera.fbo = NoRuntimeCopy(size=(64, 36))
        self.camera.frame = CameraFrame()
        self.camera._wrappers = {Square(): ((), NoRuntimeCopy())}
        for namespace in ({"camera": self.camera, "frame": self.camera.frame},
                          {"frame": self.camera.frame, "camera": self.camera}):
            copied = deepcopy(namespace)
            camera = copied["camera"]
            self.assertIs(camera.frame, copied["frame"])
            self.assertIsNone(camera.ctx)
            self.assertIsNone(camera.fbo)
            self.assertFalse(camera._wrappers)
            self.assertFalse(camera._released)
            self.assertEqual(camera.get_pixel_shape(), (64, 36))
            with self.assertRaisesRegex(RuntimeError, "capture"):
                camera.get_image()
            camera.release()

    def test_context_resource_retirement_preserves_other_active_context(self):
        first = SimpleNamespace(program=Mock(side_effect=lambda **kwargs: Mock()))
        other = SimpleNamespace(program=Mock(side_effect=lambda **kwargs: Mock()))
        program = get_shader_program(first, "vertex", "fragment")
        self.assertIs(get_shader_program(first, "vertex", "fragment"), program)
        separate = get_shader_program(other, "vertex", "fragment")
        self.assertIsNot(program, separate)
        canvas = Mock()
        context_resources(first)["fill_canvas"] = ((canvas, canvas), (canvas,))
        release_context_resources(first)
        program.release.assert_called_once()
        canvas.release.assert_called_once()
        separate.release.assert_not_called()
        self.assertIs(get_shader_program(other, "vertex", "fragment"), separate)
        self.assertIsNone(first._maniml_gl_resources)
        release_context_resources(other)
        separate.release.assert_called_once()


@unittest.skipUnless(os.environ.get("MANIML_TEST_GPU") == "1", "native GL device check not requested")
class NativeGLCameraPixels(unittest.TestCase):
    def test_copied_camera_allocates_independently_and_survives_original_release(self):
        original = NativeGLCamera(resolution=(96, 54))
        cloned = None
        path = Square(fill_opacity=.5)
        try:
            original.capture(path)
            expected = np.asarray(original.get_image()).copy()
            copied = deepcopy({"camera": original, "frame": original.frame})
            cloned = copied["camera"]
            self.assertIsNone(cloned.ctx)
            self.assertIs(cloned.frame, copied["frame"])
            cloned.capture(path)
            self.assertIsNot(cloned.ctx, original.ctx)
            np.testing.assert_array_equal(cloned.get_image(), expected)
            original.release()
            cloned.capture(path)
            np.testing.assert_array_equal(cloned.get_image(), expected)
        finally:
            original.release()
            if cloned is not None:
                cloned.release()

    def test_packaged_camera_matches_frozen_native_oracle_across_edits(self):
        from tests.gl_reference_camera import Camera as FrozenGLCamera

        frames = []
        for camera_class in (FrozenGLCamera, NativeGLCamera):
            camera = camera_class(resolution=(160, 90))
            path = Square(side_length=2, fill_color="#DD4422", fill_opacity=.55,
                          stroke_width=3, fill_border_width=4)
            other = Square(side_length=1.2, fill_color="#2266DD", fill_opacity=.8,
                           stroke_width=0).shift([.6, .25, 0])
            states = []
            try:
                for step in range(3):
                    if step == 1:
                        path.data["fill_rgba"][:] = [.1, .8, .2, .4]
                        path.set_stroke(width=7, behind=True)
                        camera.frame.scale(.8).shift([.1, .15, 0])
                    elif step == 2:
                        path.apply_depth_test()
                        other.apply_depth_test()
                        other.shift([0, 0, .1])
                    camera.capture(VGroup(path, other))
                    states.append(np.asarray(camera.get_image()).copy())
                    self.assertFalse(hasattr(path, "shader_wrapper"))
                self.assertFalse(np.array_equal(states[0], states[1]))
            finally:
                camera.release()
            frames.append(states)
        for expected, actual in zip(*frames):
            np.testing.assert_array_equal(actual, expected)

    def test_explicit_scene_camera_selection_captures_and_releases(self):
        class OracleScene(Scene):
            camera_class = NativeGLCamera

        scene = OracleScene(window=None, camera_config={"resolution": (96, 54)})
        try:
            scene.add(Square(fill_opacity=1, stroke_width=0))
            scene.update_frame(force_draw=True)
            self.assertIsInstance(scene.camera, NativeGLCamera)
            self.assertEqual(scene.get_image().size, (96, 54))
            self.assertGreater(np.asarray(scene.get_image())[..., :3].max(), 0)
        finally:
            scene.camera.release()

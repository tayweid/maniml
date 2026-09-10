"""Generated-wire driver checks, with opt-in real WebGPU pixel assertions."""

from copy import deepcopy
import importlib.util
import os
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock

import numpy as np

from maniml.web.geometry import SURFACE_DTYPE, parse_geometry_message
from maniml.web.generated_geometry import serialize_generated_frame
from tests.renderer_fixtures import build_scene


def _draw(color=(1, 0, 0, .5), *, pipeline="surface", indexed=True, uniforms=None):
    vertices = np.zeros(4, dtype=SURFACE_DTYPE)
    vertices["point"] = [[-2, -2, 0], [2, -2, 0], [2, 2, 0], [-2, 2, 0]]
    vertices["d_normal_point"] = vertices["point"] + [0, 0, .001]
    vertices["rgba"] = color
    indices = np.array([0, 1, 2, 0, 2, 3], dtype="u4")
    if not indexed:
        vertices, indices = vertices[indices], None
    return SimpleNamespace(pipeline=pipeline, vertices=vertices, indices=indices,
                           count=6, instances=1, uniforms={} if uniforms is None else uniforms)


def _message(*draws, samples=1, cache=None, background=(0, 0, 0, 0)):
    scene = build_scene(resolution=(64, 36))
    scene.camera.refresh_uniforms()
    frame = SimpleNamespace(draws=draws, resolution=(64, 36), samples=samples,
                            background=background, limitations=[])
    return parse_geometry_message(serialize_generated_frame(frame, scene.camera.uniforms, cache))


class _Buffer:
    def __init__(self, data, events):
        self.data = bytes(data)
        self.size = len(data)
        self.events = events
        self.destroyed = False

    def destroy(self):
        self.destroyed = True
        self.events.append(("destroy", self))


class _Pass:
    def __init__(self, events):
        self.events = events

    def __getattr__(self, name):
        return lambda *args, **kwargs: self.events.append((name, *args))


class _Encoder:
    def __init__(self, events):
        self.events = events

    def begin_render_pass(self, **descriptor):
        self.events.append(("begin_render_pass", descriptor))
        return _Pass(self.events)

    def finish(self):
        self.events.append(("finish",))
        return self


class _Device:
    def __init__(self):
        self.events, self.buffers = [], []
        self.queue = SimpleNamespace(
            submit=lambda commands: self.events.append(("submit", commands)),
            read_texture=lambda source, layout, size: bytes(size[0] * size[1] * 4))

    def create_command_encoder(self):
        return _Encoder(self.events)

    def create_buffer_with_data(self, *, data, usage):
        buffer = _Buffer(data, self.events)
        self.buffers.append(buffer)
        return buffer

    def create_bind_group(self, **descriptor):
        return descriptor


@unittest.skipUnless(importlib.util.find_spec("wgpu"), "optional WebGPU dependency unavailable")
class GeneratedWgpuCommands(unittest.TestCase):
    def setUp(self):
        from maniml.web.wgpu_renderer import WgpuRenderer
        self.renderer = WgpuRenderer.__new__(WgpuRenderer)
        self.renderer.device = _Device()
        self.renderer.batch_cache = {"legacy": {}}
        self.renderer._generated_geometry = {}
        self.renderer._generated_uniforms = {}
        self.renderer._generated_textures = {}
        self.renderer.texture_cache = {}
        self.renderer._ensure_targets = Mock()
        self.renderer.resolve_texture = None
        self.renderer.out_texture = self.renderer.out_view = object()
        self.renderer.depth_view = object()
        self.renderer._pipeline = Mock(side_effect=lambda name, samples: SimpleNamespace(
            name=name, get_bind_group_layout=lambda group: (name, samples, group)))

    def test_one_pass_preserves_indexed_plain_and_uniform_draw_order(self):
        from maniml.web.wgpu_renderer import UNIFORM_FIELDS
        header, data = _message(_draw(), _draw(indexed=False, uniforms={"is_fixed_in_frame": 1}),
                                 _draw(pipeline="surface_depth"), background=(.4, .2, .8, .25))
        self.renderer.render(header, data)
        events = self.renderer.device.events
        passes = [event for event in events if event[0] == "begin_render_pass"]
        self.assertEqual(len(passes), 1)
        self.assertEqual(passes[0][1]["color_attachments"][0]["clear_value"], (.1, .05, .2, .25))
        self.assertEqual([event for event in events if event[0] in ("draw", "draw_indexed")],
                         [("draw_indexed", 6, 1), ("draw", 6, 1), ("draw_indexed", 6, 1)])
        self.assertEqual([event[1].name for event in events if event[0] == "set_pipeline"],
                         ["generated_surface", "generated_surface", "generated_surface_depth"])
        self.renderer._ensure_targets.assert_called_once_with((64, 36), 1)
        offset = sum(count for name, count, default in
                     UNIFORM_FIELDS[:[field[0] for field in UNIFORM_FIELDS].index("premultiplied_output")])
        for buffer, group in self.renderer._generated_uniforms.values():
            self.assertEqual(np.frombuffer(buffer.data, dtype="f4")[offset], 1)
        self.assertEqual(self.renderer.batch_cache, {"legacy": {}})

    def test_same_geometry_can_have_different_uniforms_without_buffer_mutation(self):
        header, data = _message(_draw(), _draw(uniforms={"is_fixed_in_frame": 1}))
        self.assertEqual(header["batches"][0]["hash"], header["batches"][1]["hash"])
        self.renderer.render(header, data)
        self.assertEqual(len(self.renderer._generated_geometry), 1)
        self.assertEqual(len(self.renderer._generated_uniforms), 2)
        values = [buffer.data for buffer, group in self.renderer._generated_uniforms.values()]
        self.assertNotEqual(*values)

    def test_delta_reuses_resources_and_absent_entries_retire_after_submit(self):
        from maniml.web.geometry import GeometryCache
        cache = GeometryCache()
        header, data = _message(_draw(), cache=cache)
        self.renderer.render(header, data)
        buffers = list(self.renderer.device.buffers)
        header, data = _message(_draw(), cache=cache)
        self.assertEqual(data, b"")
        self.renderer.render(header, data)
        self.assertEqual(self.renderer.device.buffers, buffers)
        header, data = _message(cache=cache)
        self.renderer.device.events.clear()
        self.renderer.render(header, data)
        events = self.renderer.device.events
        submitted = next(index for index, event in enumerate(events) if event[0] == "submit")
        self.assertTrue(all(index > submitted for index, event in enumerate(events) if event[0] == "destroy"))
        self.assertTrue(all(buffer.destroyed for buffer in buffers))
        self.assertFalse(self.renderer._generated_geometry)
        self.assertFalse(self.renderer._generated_uniforms)
        returning, data = _message(_draw(), cache=cache)
        self.assertNotIn("cached", returning["batches"][0])
        self.renderer.render(returning, data)
        self.assertEqual(len(self.renderer._generated_geometry), 1)

    def test_missing_delta_and_invalid_payload_fail_without_submission(self):
        header, data = _message(_draw())
        for change, message in ((lambda batch: batch.update(cached=True), "cache miss"),
                                (lambda batch: batch.update(offset=len(data) + 1), "beyond payload"),
                                (lambda batch: batch.update(stride=12), "vertex layout")):
            with self.subTest(message=message):
                bad = deepcopy(header)
                change(bad["batches"][0])
                with self.assertRaisesRegex((KeyError, ValueError), message):
                    self.renderer.render(bad, data)
        self.assertFalse(any(event[0] == "submit" for event in self.renderer.device.events))

    def test_generated_pipeline_blend_and_depth_preserve_legacy_specs(self):
        from maniml.web.wgpu_renderer import ALPHA_BLEND, COMPOSITE_BLEND, PIPELINE_SPECS
        for base in ("surface", "stroke", "dot", "image", "texsurface"):
            for suffix in ("", "_depth"):
                old, new = PIPELINE_SPECS[base + suffix], PIPELINE_SPECS["generated_" + base + suffix]
                self.assertEqual(old[4], ALPHA_BLEND)
                self.assertEqual(new[4], COMPOSITE_BLEND)
                self.assertEqual(old[:4], new[:4])
                self.assertEqual(new[-1], bool(suffix))


@unittest.skipUnless(os.environ.get("MANIML_TEST_GPU") == "1", "real WebGPU check not requested")
class GeneratedWgpuPixels(unittest.TestCase):
    def test_all_primitive_layouts_textures_and_delta_lifetime(self):
        from PIL import Image
        from maniml.mobject.geometry import Square
        from maniml.mobject.types.dot_cloud import DotCloud
        from maniml.mobject.types.image_mobject import ImageMobject
        from maniml.mobject.types.surface import Surface, TexturedSurface
        from maniml.web.geometry import GeometryCache, serialize_scene
        from maniml.web.triangle_scene import prepare_triangle_frame
        from maniml.web.wgpu_renderer import WgpuRenderer
        generated, legacy = WgpuRenderer(), WgpuRenderer()
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "texture.png")
            Image.new("RGBA", (8, 8), (40, 160, 230, 255)).save(path)
            surface = Surface(u_range=(-1, 1), v_range=(-1, 1),
                              resolution=(2, 2), color="#55CC99")
            cases = {"stroke": Square(fill_opacity=0, stroke_width=8),
                     "dot": DotCloud(points=np.array([[0., 0., 0.]]), radius=.7),
                     "image": ImageMobject(path, height=2),
                     "surface": surface,
                     "texsurface": TexturedSurface(surface.copy(), path)}
            for kind, mobject in cases.items():
                with self.subTest(primitive=kind):
                    scene = build_scene(mobject, resolution=(96, 54))
                    frame = prepare_triangle_frame(scene, None)
                    self.assertEqual({draw.pipeline.removesuffix("_depth") for draw in frame.draws}, {kind})
                    cache = GeometryCache()
                    first = parse_geometry_message(serialize_generated_frame(frame, scene.camera.uniforms, cache))
                    pixels = np.asarray(generated.render(*first))
                    reference = np.asarray(legacy.render(*parse_geometry_message(serialize_scene(scene))))
                    np.testing.assert_allclose(pixels[..., :3], reference[..., :3], atol=1)
                    self.assertGreater(np.count_nonzero(pixels[..., :3]), 0)
                    same = parse_geometry_message(serialize_generated_frame(frame, scene.camera.uniforms, cache))
                    self.assertEqual(same[1], b"")
                    np.testing.assert_array_equal(generated.render(*same), pixels)
                    absent = deepcopy(frame)
                    absent.draws = []
                    generated.render(*parse_geometry_message(serialize_generated_frame(absent, scene.camera.uniforms, cache)))
                    self.assertFalse(generated._generated_geometry)
                    self.assertFalse(generated._generated_uniforms)
                    self.assertFalse(generated._generated_textures)
                    returning = parse_geometry_message(serialize_generated_frame(frame, scene.camera.uniforms, cache))
                    self.assertTrue(all(not batch.get("cached") for batch in returning[0]["batches"]))
                    np.testing.assert_array_equal(generated.render(*returning), pixels)

    def test_depth_draws_occlude_independently_of_order_and_painter_overlay_wins(self):
        from maniml.web.wgpu_renderer import WgpuRenderer
        renderer = WgpuRenderer()
        red = _draw((1, 0, 0, 1), pipeline="surface_depth")
        blue = _draw((0, 0, 1, 1), pipeline="surface_depth")
        blue.vertices["point"][:, 2] = .5
        blue.vertices["d_normal_point"][:, 2] = .501
        first = renderer.render(*_message(red, blue, samples=4))
        second = renderer.render(*_message(blue, red, samples=4))
        np.testing.assert_array_equal(first, second)
        overlay = _draw((1, 1, 1, 1))
        overlay.vertices["point"][:, 2] = -10
        overlay.vertices["d_normal_point"][:, 2] = -9.999
        overlaid = renderer.render(*_message(red, blue, overlay, samples=4))
        np.testing.assert_array_equal(np.asarray(overlaid)[18, 32], [255, 255, 255, 255])

    def test_painter_order_and_premultiplied_alpha_at_both_sample_counts(self):
        from maniml.web.wgpu_renderer import WgpuRenderer
        renderer = WgpuRenderer()
        red, blue = _draw(), _draw((0, 0, 1, .5), indexed=False)
        for samples in (1, 4):
            with self.subTest(samples=samples):
                image = renderer.render(*_message(red, blue, samples=samples))
                np.testing.assert_allclose(np.asarray(image)[18, 32], [64, 0, 128, 192], atol=1)
                image = renderer.render(*_message(blue, red, samples=samples))
                np.testing.assert_allclose(np.asarray(image)[18, 32], [128, 0, 64, 192], atol=1)

    def test_clip_plane_and_cached_camera_update_reach_shader(self):
        from maniml.web.geometry import GeometryCache
        from maniml.web.wgpu_renderer import WgpuRenderer
        renderer, cache = WgpuRenderer(), GeometryCache()
        square = _draw((1, 0, 0, 1), uniforms={"clip_plane": [1, 0, 0, 0]})
        first = renderer.render(*_message(square, cache=cache))
        pixels = np.asarray(first)
        self.assertEqual(pixels[18, 29, 3], 0)
        self.assertEqual(pixels[18, 35, 3], 255)
        square.uniforms["clip_plane"] = [-1, 0, 0, 0]
        header, data = _message(square, cache=cache)
        self.assertEqual(data, b"")
        second = renderer.render(header, data)
        pixels = np.asarray(second)
        self.assertEqual(pixels[18, 29, 3], 255)
        self.assertEqual(pixels[18, 35, 3], 0)


if __name__ == "__main__":
    unittest.main()

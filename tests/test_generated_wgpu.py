"""Generated-wire driver checks, with opt-in real WebGPU pixel assertions."""

from copy import deepcopy
import importlib.util
import io
import hashlib
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


def _constant_paint(color):
    return [0, 0, 0, 1, 1, 0, 0, 0, 0, 1, 0, 0, *color, *([0] * 8)]


def _message(*draws, samples=1, cache=None, background=(0, 0, 0, 0), supersample=1):
    scene = build_scene(resolution=(64, 36))
    scene.camera.refresh_uniforms()
    frame = SimpleNamespace(draws=draws, resolution=(64, 36), samples=samples,
                            background=background, limitations=[])
    header, raw = parse_geometry_message(serialize_generated_frame(frame, scene.camera.uniforms, cache))
    header["supersample"] = supersample
    return header, raw


def _binary_paint_message(*colors, samples=1):
    """Construct the material ABI independently of the production serializer."""
    header, raw = _message(*(_draw() for _ in colors), samples=samples)
    header["format_version"] = 4
    header["paint_data"] = {}
    raw += b"x"  # Deliberately unaligned float32 storage in the raw payload.
    for index, (batch, color) in enumerate(zip(header["batches"], colors)):
        paint_hash = f"{index + 1:032x}"
        batch.update(pipeline="paint", paint_hash=paint_hash)
        values = np.asarray(_constant_paint(color), dtype="<f4").tobytes()
        header["paint_data"][paint_hash] = {"offset": len(raw), "nbytes": len(values)}
        raw += values
    return header, raw


def _border_wire(*, curves=1, fill_count=4, copies=1, samples=4, capacity=None):
    """A GPU border message. ``capacity=None`` is the format 5 wire, whose
    complete index buffer travelled at 64 vertices per curve; a capacity
    makes the format 6 wire: fill indices plus the run layout."""
    from maniml.web.gpu_border_geometry import indices_per_curve
    from tests.test_border_compute import source_records, strip_indices
    from tests.test_border_geometry import segment
    data = np.concatenate([segment(points=((-2, -2, 0), (0, -3, 0), (2, -2, 0)),
                           widths=(40, 40, 40)) for _ in range(curves)])
    data["fill_rgba"] = [1, 0, 0, .5]
    records = source_records(data)
    fill = np.resize(_draw().vertices, fill_count)
    fill_indices = np.array([0, 1, 2, 0, 2, 3] if fill_count else [], dtype="<u4")
    if capacity is None:
        indices = np.concatenate([fill_indices,
            *(strip_indices().reshape(-1) + fill_count + 64 * i for i in range(curves))]).astype("<u4")
        border = {"hash": None, "num_curves": curves}
        version, vertex_count, count = 5, fill_count + 64 * curves, len(indices)
    else:
        indices = fill_indices
        border = {"hash": None, "num_curves": curves, "capacity": capacity,
                  "layout": [[len(indices), fill_count, curves]]}
        version = 6
        vertex_count = fill_count + capacity * curves
        count = len(indices) + indices_per_curve(capacity) * curves
    header, _ = _message(_draw(), samples=samples, supersample=2)
    key = hashlib.blake2b(records.tobytes(), digest_size=16).hexdigest()
    border["hash"] = key
    raw = fill.tobytes() + indices.tobytes() + b"x"
    header.update(format_version=version, border_data={key: {"offset": len(raw), "nbytes": records.nbytes}})
    raw += records.tobytes()
    batch = header["batches"][0]
    batch.update(hash="border-fill", offset=0, index_offset=fill.nbytes,
        fill_num_verts=fill_count, num_verts=vertex_count,
        index_count=len(indices), count=count, border=border,
        coverage=True, uniforms={"flat_stroke": 0, "scale_stroke_with_zoom": 0})
    header["batches"] = [deepcopy(batch) for _ in range(copies)]
    return header, raw, data, fill


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

    def begin_compute_pass(self):
        self.events.append(("begin_compute_pass",))
        return _Pass(self.events)

    def copy_buffer_to_buffer(self, source, source_offset, target, target_offset, size):
        self.events.append(("copy_buffer_to_buffer", source, source_offset, target, target_offset, size))

    def finish(self):
        self.events.append(("finish",))
        return self


class _Device:
    def __init__(self):
        self.events, self.buffers = [], []
        self.limits = {}
        self.queue = SimpleNamespace(
            write_texture=Mock(),
            submit=lambda commands: self.events.append(("submit", commands)),
            read_texture=lambda source, layout, size: bytes(size[0] * size[1] * 4))

    def create_command_encoder(self):
        return _Encoder(self.events)

    def create_buffer_with_data(self, *, data, usage):
        buffer = _Buffer(data, self.events)
        buffer.usage = usage
        self.buffers.append(buffer)
        return buffer

    def create_buffer(self, *, size, usage):
        return self.create_buffer_with_data(data=bytes(size), usage=usage)

    def create_compute_pipeline(self, **descriptor):
        return SimpleNamespace(name="border_compute", get_bind_group_layout=lambda group: ("compute", group))

    def create_bind_group(self, **descriptor):
        return descriptor

    def create_texture(self, **descriptor):
        return SimpleNamespace(create_view=lambda: descriptor, destroy=Mock(), size=descriptor["size"])

    def create_render_pipeline(self, **descriptor):
        return SimpleNamespace(name="spatial_resolve", get_bind_group_layout=lambda group: group)


@unittest.skipUnless(importlib.util.find_spec("wgpu"), "optional WebGPU dependency unavailable")
class GeneratedWgpuCommands(unittest.TestCase):
    def setUp(self):
        from maniml.web.wgpu_renderer import WgpuRenderer
        self.renderer = WgpuRenderer.__new__(WgpuRenderer)
        self.renderer.device = _Device()
        self.renderer._generated_geometry = {}
        self.renderer._generated_uniforms = {}
        self.renderer._generated_textures = {}
        self.renderer._generated_paints = {}
        self.renderer._generated_paint_bindings = {}
        self.renderer._border_sources = {}
        self.renderer._border_outputs = {}
        self.renderer._border_compute_pipeline = None
        self.renderer._object_tables = {}
        self.renderer._patch_uniforms = {}
        self.renderer._patch_layouts = None
        self.renderer._net_sources = {}
        self.renderer._net_outputs = {}
        self.renderer._net_compute_pipeline = None
        self.renderer._program_sources = {}
        self.renderer._program_outputs = {}
        self.renderer._program_pipelines = {}
        self.renderer._stale_index_buffers = []
        self.renderer.texture_cache = {}
        self.renderer.sampler = object()
        self.renderer._ensure_targets = Mock()
        self.renderer._modules = {"resolve2": object(), "border_compute": object()}
        self.renderer._spatial_pipeline = None
        self.renderer._spatial_texture = None
        self.renderer._spatial_binding = None
        self.renderer.resolve_texture = None
        self.renderer.out_texture = self.renderer.device.create_texture(size=(128, 72, 1))
        self.renderer.out_view = self.renderer.out_texture.create_view()
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
        self.assertFalse(hasattr(self.renderer, "batch_cache"))

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

    def test_generated_pipeline_blend_and_depth_use_shared_scene_target(self):
        from maniml.web.wgpu_renderer import PREMULTIPLIED_BLEND, PIPELINE_SPECS
        self.assertTrue(all(name.startswith("generated_") for name in PIPELINE_SPECS))
        for base in ("surface", "paint", "stroke", "dot", "image", "texsurface"):
            for suffix in ("", "_depth"):
                spec = PIPELINE_SPECS["generated_" + base + suffix]
                self.assertEqual(spec[3:5], ("out", PREMULTIPLIED_BLEND))
                self.assertEqual(spec[-1], bool(suffix))

    def test_legacy_wire_is_rejected_without_submission(self):
        header, raw = _message(_draw())
        header.pop("renderer")
        with self.assertRaisesRegex(ValueError, "requires generated triangle"):
            self.renderer.render(header, raw)
        self.assertFalse(self.renderer.device.events)

    def test_paint_updates_reuse_geometry_and_retire_only_unused_materials(self):
        from maniml.web.geometry import GeometryCache
        cache = GeometryCache()
        first = _draw(pipeline="paint")
        first.paint = _constant_paint([1, 0, 0, .5])
        second = deepcopy(first)
        second.paint = _constant_paint([0, 0, 1, .75])
        header, raw = _message(first, second, cache=cache)
        self.renderer.render(header, raw)
        self.assertEqual(len(self.renderer._generated_geometry), 1)
        self.assertEqual(len(self.renderer._generated_paints), 2)
        geometry = next(iter(self.renderer._generated_geometry.values()))["buffer"]
        materials = list(self.renderer._generated_paints.values())
        header, raw = _message(second, cache=cache)
        self.assertEqual(raw, b"")
        self.renderer.render(header, raw)
        self.assertIs(next(iter(self.renderer._generated_geometry.values()))["buffer"], geometry)
        self.assertTrue(materials[0][0].destroyed)
        self.assertFalse(materials[1][0].destroyed)

    def test_binary_paint_reuses_storage_across_pipeline_layouts_and_sample_counts(self):
        header, raw = _binary_paint_message((1, 0, 0, .5), (0, 0, 1, .75), samples=4)
        depth = deepcopy(header["batches"][0])
        depth.update(hash="separate-depth-layout", pipeline="paint_depth", coverage=True)
        header["batches"].append(depth)
        self.renderer.render(header, raw)
        self.assertEqual(len(self.renderer._generated_paints), 2)
        self.assertEqual(len(self.renderer._generated_paint_bindings), 4)
        red_key = ("hash", header["batches"][0]["paint_hash"])
        red = self.renderer._generated_paints[red_key][0]
        groups = [group for key, group in self.renderer._generated_paint_bindings.items() if key[2] == red_key]
        self.assertEqual(len(groups), 3)
        self.assertTrue(all(group["entries"][0]["resource"]["buffer"] is red for group in groups))
        np.testing.assert_array_equal(np.frombuffer(red.data, dtype="<f4")[12:16], [1, 0, 0, .5])
        count = len(self.renderer.device.buffers)
        header["paint_data"] = {}
        for batch in header["batches"]:
            batch["cached"] = True
        self.renderer.render(header, b"")
        self.assertEqual(len(self.renderer.device.buffers), count)
        header["samples"] = 1
        header["batches"] = header["batches"][:1]
        self.renderer.render(header, b"")
        self.assertIs(self.renderer._generated_paints[red_key][0], red)
        self.assertEqual(len(self.renderer._generated_paint_bindings), 1)
        header["batches"] = []
        self.renderer.device.events.clear()
        self.renderer.render(header, b"")
        events = self.renderer.device.events
        submitted = next(i for i, event in enumerate(events) if event[0] == "submit")
        self.assertTrue(all(i > submitted for i, event in enumerate(events) if event[0] == "destroy"))
        self.assertTrue(red.destroyed)
        self.assertFalse(self.renderer._generated_paints)
        self.assertFalse(self.renderer._generated_paint_bindings)
        returning, raw = _binary_paint_message((1, 0, 0, .5))
        self.renderer.render(returning, raw)
        self.assertIsNot(self.renderer._generated_paints[red_key][0], red)

    def test_binary_paint_rejects_malformed_missing_and_redefined_materials_without_cache_poisoning(self):
        original, raw = _binary_paint_message((1, 0, 0, .5))
        self.renderer.render(original, raw)
        material = next(iter(self.renderer._generated_paints.values()))[0]
        previous_bindings = self.renderer._generated_paint_bindings.copy()
        def check(header, payload, message="paint"):
            self.renderer.device.events.clear()
            with self.assertRaisesRegex((KeyError, ValueError), message):
                self.renderer.render(header, payload)
            self.assertFalse(any(event[0] == "submit" for event in self.renderer.device.events))
            self.assertFalse(material.destroyed)
            self.assertEqual(len(self.renderer._generated_paints), 1)
            self.assertEqual(self.renderer._generated_paint_bindings, previous_bindings)
        missing = deepcopy(original)
        missing["paint_data"] = {}
        missing["batches"][0].update(cached=True, paint_hash="f" * 32)
        check(missing, b"", "paint cache miss")
        ref = next(iter(original["paint_data"].values()))
        for index, value in ((3, 0), (3, -1), (3, np.inf), (7, .5), (7, 4097),
                             (11, 2), (11, 1), (15, np.nan)):
            bad = bytearray(raw)
            bad[ref["offset"] + 4 * index:ref["offset"] + 4 * (index + 1)] = np.float32(value).tobytes()
            check(original, bad)
        for offset, size in ((-1, 96), (.5, 96), (False, 96), (0, -1), (0, 100000), (ref["offset"], 92)):
            bad = deepcopy(original)
            next(iter(bad["paint_data"].values())).update(offset=offset, nbytes=size)
            check(bad, raw)
        for records in (None, [], 1, True, "definitions"):
            bad = deepcopy(original)
            bad["paint_data"] = records
            check(bad, raw, "paint definitions")
        for span in (None, [], 1, True, "span"):
            bad = deepcopy(original)
            bad["paint_data"][bad["batches"][0]["paint_hash"]] = span
            check(bad, raw, "paint definition span")
        for inline in (None, 1, True, "paint", {}, [_constant_paint([1, 0, 0, .5])],
                       [*([0] * 12), "1", *([0] * 11)], [*([0] * 12), True, *([0] * 11)]):
            bad = deepcopy(original)
            bad.update(format_version=3, paint_data={})
            bad["batches"][0].pop("paint_hash")
            bad["batches"][0]["paint"] = inline
            check(bad, raw, "inline paint")
        changed, different_raw = _binary_paint_message((0, 0, 1, .5))
        check(changed, different_raw, "redefined")
        failed, payload = _binary_paint_message((0, 0, 1, .5))
        old_hash = failed["batches"][0]["paint_hash"]
        failed["paint_data"]["b" * 32] = failed["paint_data"].pop(old_hash)
        failed["batches"][0]["paint_hash"] = "b" * 32
        failed["batches"].append({"kind": "generated", "pipeline": "invalid"})
        check(failed, payload, "unsupported generated pipeline")
        failed["batches"].pop()
        self.renderer.render(failed, payload)
        self.assertTrue(material.destroyed)
        self.assertEqual(len(self.renderer._generated_paints), 1)

    def test_historical_inline_paint_remains_readable(self):
        header, raw = _message(_draw())
        header["format_version"] = 3
        header["batches"][0].update(pipeline="paint", paint=_constant_paint([1, .5, 0, .75]))
        self.renderer.render(header, raw)
        values = np.frombuffer(next(iter(self.renderer._generated_paints.values()))[1], dtype="<f4")
        np.testing.assert_array_equal(values[12:16], [1, .5, 0, .75])

    def test_gpu_border_retains_source_fill_and_separate_occurrence_outputs(self):
        header, raw, _, _ = _border_wire(curves=3, fill_count=40, copies=2)
        self.renderer.device.limits["max-compute-workgroups-per-dimension"] = 2
        header["batches"][1]["uniforms"]["camera_position"] = [0, -10, 10]
        self.renderer.render(header, raw)
        self.assertEqual(len(self.renderer._generated_geometry), 1)
        self.assertEqual(len(self.renderer._border_sources), 1)
        self.assertEqual(len(self.renderer._border_outputs), 2)
        outputs = [resource["buffer"] for resource in self.renderer._border_outputs.values()]
        self.assertIsNot(*outputs)
        events = self.renderer.device.events
        self.assertEqual([event[1] for event in events if event[0] == "dispatch_workgroups"], [2, 1, 2, 1])
        first_scene = next(i for i, event in enumerate(events) if event[0] == "begin_render_pass")
        self.assertTrue(all(i < first_scene for i, event in enumerate(events) if event[0] == "dispatch_workgroups"))
        copies = [event for event in events if event[0] == "copy_buffer_to_buffer"]
        self.assertEqual(len(copies), 2)
        self.assertEqual(copies[0][-1], 40 * 40)
        for resource in self.renderer._border_outputs.values():
            view = resource["binding"]["entries"][1]["resource"]
            self.assertEqual(view["offset"], 1280)
            self.assertEqual(view["size"], (8 + 3 * 64) * 40)
        header["border_data"] = {}
        for batch in header["batches"]:
            batch["cached"] = True
        self.renderer.device.events.clear()
        self.renderer.render(header, b"")
        self.assertFalse(any(event[0] in ("dispatch_workgroups", "copy_buffer_to_buffer") for event in self.renderer.device.events))
        header["camera"]["frame_scale"] *= .95
        self.renderer.device.events.clear()
        self.renderer.render(header, b"")
        self.assertEqual([event[1] for event in self.renderer.device.events if event[0] == "dispatch_workgroups"], [2, 1, 2, 1])
        self.assertEqual([resource["buffer"] for resource in self.renderer._border_outputs.values()], outputs)
        header["batches"] = []
        self.renderer.render(header, b"")
        self.assertFalse(self.renderer._border_sources)
        self.assertFalse(self.renderer._border_outputs)
        self.assertTrue(all(buffer.destroyed for buffer in outputs))

    def test_format_6_border_runs_expand_indices_locally_and_rekey_by_occurrence(self):
        import struct
        from maniml.web.gpu_border_geometry import expand_run_indices, indices_per_curve
        header, raw, _, _ = _border_wire(curves=3, fill_count=40, capacity=8)
        batch = header["batches"][0]
        self.assertEqual(batch["index_count"], 6)
        self.assertEqual(batch["count"], 6 + 3 * indices_per_curve(8))
        self.renderer.render(header, raw)
        resources = self.renderer._generated_geometry["border-fill"]
        fill_indices = np.array([0, 1, 2, 0, 2, 3], dtype="<u4")
        self.assertEqual(resources["fill_indices"], fill_indices.tobytes())
        self.assertNotIn("index_buffer", resources)
        (capacity, index_buffer), = resources["index_buffers"].items()
        self.assertEqual(capacity, 8)
        expected = expand_run_indices(fill_indices, [[6, 40, 3]], 40, 8)
        self.assertEqual(len(expected), batch["count"])
        self.assertEqual(index_buffer.data, expected.tobytes())
        self.assertEqual(int(expected.max()), 40 + 3 * 8 - 1)
        events = self.renderer.device.events
        self.assertEqual([e[1] for e in events if e[0] == "draw_indexed"], [batch["count"]])
        self.assertIs(next(e[1] for e in events if e[0] == "set_index_buffer"), index_buffer)
        params = next(e[2]["entries"][1]["resource"] for e in events
                      if e[0] == "set_bind_group" and e[1] == 0 and e[2]["layout"] == ("compute", 0))
        self.assertEqual(params["size"], 32)
        self.assertEqual(struct.unpack("<IIIfIIII", params["buffer"].data)[4], 8)
        output, = self.renderer._border_outputs.values()
        self.assertEqual(output["buffer"].size, (40 + 3 * 8) * 40)
        vertex_buffer = resources["buffer"]
        # A larger reservation on a cached batch uploads nothing: the fill
        # bytes stay, the index buffer and output are rebuilt at the new
        # capacity, and the old ones go only after the frame is submitted.
        header["border_data"] = {}
        batch["cached"] = True
        batch["border"]["capacity"] = 16
        batch["num_verts"] = 40 + 3 * 16
        batch["count"] = 6 + 3 * indices_per_curve(16)
        self.renderer.device.events.clear()
        self.renderer.render(header, b"")
        events = self.renderer.device.events
        self.assertIs(self.renderer._generated_geometry["border-fill"]["buffer"], vertex_buffer)
        (capacity, grown), = resources["index_buffers"].items()
        self.assertEqual(capacity, 16)
        self.assertEqual(grown.data, expand_run_indices(fill_indices, [[6, 40, 3]], 40, 16).tobytes())
        self.assertTrue(index_buffer.destroyed)
        self.assertTrue(output["buffer"].destroyed)
        submit = next(i for i, e in enumerate(events) if e[0] == "submit")
        for retired in (index_buffer, output["buffer"]):
            self.assertGreater(next(i for i, e in enumerate(events) if e[0] == "destroy" and e[1] is retired), submit)
        new_output, = self.renderer._border_outputs.values()
        self.assertEqual(new_output["buffer"].size, (40 + 3 * 16) * 40)
        self.assertEqual([e[1] for e in events if e[0] == "draw_indexed"], [batch["count"]])
        self.assertEqual(len([e for e in events if e[0] == "copy_buffer_to_buffer"]), 1)
        # Outputs are keyed by occurrence of the same geometry, so an
        # unrelated object inserted earlier in the frame rekeys nothing.
        plain = {"kind": "generated", "pipeline": "surface", "hash": "plain", "num_verts": 3, "stride": 40,
                 "uniforms": {}, "count": 3, "instances": 1, "indexed": False, "offset": 0}
        header["batches"] = [plain, batch]
        self.renderer.device.events.clear()
        self.renderer.render(header, bytes(3 * 40))
        events = self.renderer.device.events
        self.assertEqual(list(self.renderer._border_outputs.values()), [new_output])
        self.assertFalse(any(e[0] in ("dispatch_workgroups", "copy_buffer_to_buffer") for e in events))
        self.assertEqual([e[1] for e in events if e[0] == "draw_indexed"], [batch["count"]])
        # Layout and capacity are validated before any resource is touched.
        for field, value in (("capacity", 66), ("capacity", "16"), ("layout", [[6, 40]]),
                             ("layout", [[3, 40, 3]]), ("layout", [[6, 40, 0]]), ("layout", [])):
            bad = deepcopy(header)
            bad["batches"][1]["border"][field] = value
            with self.subTest(field=field, value=value), self.assertRaisesRegex(ValueError, "[Bb]order"):
                self.renderer.render(bad, bytes(3 * 40))
        for field, value in (("count", batch["count"] - 3), ("num_verts", batch["num_verts"] + 1)):
            bad = deepcopy(header)
            bad["batches"][1][field] = value
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "[Bb]order"):
                self.renderer.render(bad, bytes(3 * 40))
        header["batches"] = []
        self.renderer.render(header, b"")
        self.assertTrue(grown.destroyed)
        self.assertTrue(new_output["buffer"].destroyed)

    def test_gpu_border_validates_spans_counts_widths_indices_and_failed_generation_state(self):
        header, raw, _, _ = _border_wire(fill_count=40)
        # Whole output exceeds this fake storage limit; its aligned tail fits.
        self.renderer.device.limits.update({"max-storage-buffer-binding-size": 3000, "max-buffer-size": 5000})
        self.renderer.render(header, raw)
        old_sources, old_outputs = self.renderer._border_sources.copy(), self.renderer._border_outputs.copy()
        def reject(bad, payload, message="border"):
            self.renderer.device.events.clear()
            with self.assertRaisesRegex((ValueError, KeyError), message):
                self.renderer.render(bad, payload)
            self.assertFalse(any(event[0] == "submit" for event in self.renderer.device.events))
            self.assertEqual(self.renderer._border_sources, old_sources)
            self.assertEqual(self.renderer._border_outputs, old_outputs)
        for field, value in (("fill_num_verts", -1), ("num_verts", 1), ("count", 1), ("index_offset", len(raw)),
                             ("offset", len(raw)), ("instances", True)):
            bad = deepcopy(header); bad["batches"][0][field] = value
            reject(bad, raw)
        for field, value in ((7, -1), (36, -1), (37, .5), (38, .5), (39, 1), (0, np.nan)):
            payload = bytearray(raw)
            ref = next(iter(header["border_data"].values()))
            payload[ref["offset"] + 4 * field:ref["offset"] + 4 * (field + 1)] = np.float32(value).tobytes()
            reject(header, payload)
        bad = deepcopy(header); bad["batches"][0]["border"]["hash"] = "f" * 32; bad["border_data"] = {}
        reject(bad, raw, "border cache miss")
        # Failed encoding after dispatch never commits the new camera state.
        bad = deepcopy(header); bad["batches"][0]["uniforms"]["frame_scale"] = .9
        bad["batches"].append({"kind": "generated", "pipeline": "invalid"})
        state = next(iter(old_outputs.values()))["state"]
        reject(bad, raw, "unsupported generated pipeline")
        self.assertEqual(next(iter(old_outputs.values()))["state"], state)
        for index in range(5):
            late = deepcopy(bad)
            late["batches"][0]["hash"] = f"failed-fill-{index}"
            resident = [buffer for buffer in self.renderer.device.buffers if not buffer.destroyed]
            reject(late, raw, "unsupported generated pipeline")
            self.assertEqual([buffer for buffer in self.renderer.device.buffers if not buffer.destroyed], resident)
        bad["batches"].pop()
        self.renderer.device.events.clear(); self.renderer.render(bad, raw)
        self.assertTrue(any(event[0] == "dispatch_workgroups" for event in self.renderer.device.events))
        self.assertNotEqual(next(iter(old_outputs.values()))["state"], state)

    def test_spatial_resolve_preserves_wire_uniforms_and_final_output_size(self):
        header, raw = _message(_draw(uniforms={"pixel_size": .02, "anti_alias_width": 1.25}),
                                supersample=2)
        before = deepcopy(header)
        image = self.renderer.render(header, raw)
        self.assertEqual(image.size, (64, 36))
        self.renderer._ensure_targets.assert_called_once_with((128, 72), 1)
        self.assertEqual(self.renderer._spatial_texture.size, (64, 36, 1))
        passes = [event for event in self.renderer.device.events if event[0] == "begin_render_pass"]
        self.assertEqual(len(passes), 2)
        packed = np.frombuffer(next(iter(self.renderer._generated_uniforms.values()))[0].data, dtype="f4")
        self.assertAlmostEqual(float(packed[27]), .01)
        self.assertEqual(float(packed[31]), 2.5)
        self.assertEqual(header, before)

    def test_coverage_rollover_loads_color_and_depth_and_replays_depth_only(self):
        draw = _draw(pipeline="surface_depth")
        draw.coverage = True
        header, raw = _message(*([draw] * 256))
        self.renderer.render(header, raw)
        events = self.renderer.device.events
        passes = [event[1] for event in events if event[0] == "begin_render_pass"]
        self.assertEqual(len(passes), 2)
        self.assertEqual(passes[0]["depth_stencil_attachment"]["stencil_load_op"], "clear")
        self.assertEqual(passes[1]["color_attachments"][0]["load_op"], "load")
        self.assertEqual(passes[1]["depth_stencil_attachment"]["depth_load_op"], "load")
        self.assertEqual(passes[1]["depth_stencil_attachment"]["stencil_load_op"], "clear")
        refs = [event[1] for event in events if event[0] == "set_stencil_reference"]
        self.assertEqual(refs, [*range(1, 256), 1])
        names = [event[1].name for event in events if event[0] == "set_pipeline"]
        self.assertEqual(names, ["generated_surface_depth_coverage", "generated_surface_depth_depth_only"] * 256)
        self.assertEqual(len(self.renderer._generated_geometry), 1)
        self.assertEqual(len(self.renderer._generated_uniforms), 2)

    def test_texture_storage_and_bindings_retire_on_empty_frame_then_rehydrate(self):
        from PIL import Image
        encoded = io.BytesIO()
        Image.new("RGBA", (2, 2), "red").save(encoded, format="PNG")
        png = encoded.getvalue()
        header, _ = _message(_draw(indexed=False))
        batch = header["batches"][0]
        batch.update(pipeline="image", hash="image", stride=24, num_verts=3,
                     count=3, textures={"Texture": "red"})
        raw = bytes(72) + png
        header["texture_data"] = {"red": {"offset": 72, "nbytes": len(png)}}
        self.renderer.render(header, raw)
        original = self.renderer.texture_cache["red"]
        binding = next(iter(self.renderer._generated_textures.values()))
        self.renderer.render({**header, "texture_data": {}}, raw[:72])
        self.assertIs(self.renderer.texture_cache["red"], original)
        self.assertIs(next(iter(self.renderer._generated_textures.values())), binding)
        original.destroy.assert_not_called()
        self.renderer.render({**header, "batches": [], "texture_data": {}}, b"")
        original.destroy.assert_called_once()
        self.assertFalse(self.renderer.texture_cache)
        self.assertFalse(self.renderer._generated_textures)
        self.renderer.render(header, raw)
        self.assertIsNot(self.renderer.texture_cache["red"], original)
        self.assertIsNot(next(iter(self.renderer._generated_textures.values())), binding)

    def test_independent_triangle_area_reference_covers_boundary_pixels(self):
        from benchmarks.renderer_aa import exact_triangle_coverage
        coverage = exact_triangle_coverage([[0, 0], [2, 0], [0, 2]], (2, 2))
        np.testing.assert_array_equal(coverage, [[1, .5], [.5, 0]])
        self.assertEqual(coverage.sum(), 2)


@unittest.skipUnless(os.environ.get("MANIML_TEST_GPU") == "1", "real WebGPU check not requested")
class GeneratedWgpuPixels(unittest.TestCase):
    def test_real_tex_101_glyph_fast_path_is_identical_to_stencil_at_both_zooms(self):
        from dataclasses import replace
        from maniml.web.triangle_geometry import LyonFillTessellator
        from maniml.web.triangle_scene import TriangleMeshCache, coalesce_draws, prepare_triangle_frame
        from maniml.web.wgpu_renderer import WgpuRenderer
        from tests.renderer_quality_fixtures import _configure_camera, build_quality_frame
        renderer, tessellator, cache = WgpuRenderer(), LyonFillTessellator(), TriangleMeshCache()
        quality = build_quality_frame("tex", border_policy="production_default")
        for zoom in (1, 2):
            _configure_camera(quality.scene, zoom, (.37, .19))
            frame = prepare_triangle_frame(quality.scene, tessellator, mesh_cache=cache,
                                            fill_borders=True, coalesce=False)
            self.assertEqual(len(frame.draws), 101)
            self.assertTrue(all(not draw.coverage for draw in frame.draws))
            reference = replace(frame, samples=4, supersample=2,
                                 draws=[replace(draw, coverage=True) for draw in frame.draws])
            actual = replace(frame, samples=4, supersample=2, draws=coalesce_draws(frame.draws))
            self.assertEqual(len(actual.draws), 1)
            expected = renderer.render(*parse_geometry_message(
                serialize_generated_frame(reference, quality.scene.camera.uniforms)))
            observed = renderer.render(*parse_geometry_message(
                serialize_generated_frame(actual, quality.scene.camera.uniforms)))
            np.testing.assert_array_equal(observed, expected)
        renderer.close()

    def test_opaque_painter_fast_path_is_pixel_identical_to_per_object_stencil(self):
        from dataclasses import replace
        from maniml.mobject.geometry import Circle, Square
        from maniml.web.triangle_geometry import LyonFillTessellator
        from maniml.web.triangle_scene import TriangleMeshCache, coalesce_draws, prepare_triangle_frame
        from maniml.web.wgpu_renderer import WgpuRenderer
        renderer, tessellator, cache = WgpuRenderer(), LyonFillTessellator(), TriangleMeshCache()
        red = Square(fill_color="#ff0000", fill_opacity=1, stroke_width=0, fill_border_width=20)
        blue = Circle(fill_color="#0000ff", fill_opacity=1, stroke_width=0, fill_border_width=20).shift([.2, .1, 0])
        red.uniforms["clip_plane"] = blue.uniforms["clip_plane"] = [1, 0, 0, .7]
        scene = build_scene(red, blue, resolution=(128, 72))
        for offset in (0, .037, .081):
            scene.camera.frame.shift([offset, offset / 2, 0]).scale(.93)
            for shapes in ((red, blue), (blue, red)):
                scene.render_groups[0].set_submobjects(list(shapes))
                scene.mobjects[:] = shapes
                frame = prepare_triangle_frame(scene, tessellator, mesh_cache=cache,
                                                fill_borders=True, coalesce=False)
                self.assertEqual(len(frame.draws), 2)
                self.assertTrue(all(not draw.coverage for draw in frame.draws))
                for samples in (1, 4):
                    for supersample in (1, 2):
                        reference = replace(frame, samples=samples, supersample=supersample,
                            draws=[replace(draw, coverage=True) for draw in frame.draws])
                        actual = replace(frame, samples=samples, supersample=supersample,
                                         draws=coalesce_draws(frame.draws))
                        self.assertEqual(len(actual.draws), 1)
                        expected = renderer.render(*parse_geometry_message(
                            serialize_generated_frame(reference, scene.camera.uniforms)))
                        observed = renderer.render(*parse_geometry_message(
                            serialize_generated_frame(actual, scene.camera.uniforms)))
                        np.testing.assert_array_equal(observed, expected)
                        np.testing.assert_array_equal(np.asarray(observed)[36, 64, :3],
                            [0, 0, 255] if shapes[-1] is blue else [255, 0, 0])
        renderer.close()

    def test_coverage_union_is_once_per_sample_and_nearest_depth_is_retained(self):
        from maniml.web.wgpu_renderer import WgpuRenderer
        renderer = WgpuRenderer()
        draw = _draw(pipeline="surface_depth")
        # Fill comes first. The overlapping border lies closer to the camera;
        # it contributes no second alpha but must still update scene depth.
        border = draw.vertices.copy()
        border["point"][:, 2] = .5
        border["d_normal_point"][:, 2] = .501
        draw.vertices = np.concatenate([draw.vertices, border])
        draw.indices = np.concatenate([draw.indices, draw.indices + 4])
        draw.count = 12
        draw.coverage = True
        middle = _draw((0, 1, 0, 1), pipeline="surface_depth")
        middle.vertices["point"][:, 2] = .25
        middle.vertices["d_normal_point"][:, 2] = .251
        for samples in (1, 4):
            for supersample in (1, 2):
                image = renderer.render(*_message(draw, middle, samples=samples, supersample=supersample))
                np.testing.assert_allclose(np.asarray(image)[18, 32], [128, 0, 0, 128], atol=1)
                # An earlier occluder hides the fill, so its failed depth test
                # must not claim stencil coverage against the closer border.
                image = renderer.render(*_message(middle, draw, samples=samples, supersample=supersample))
                np.testing.assert_allclose(np.asarray(image)[18, 32], [128, 127, 0, 255], atol=1)
        renderer.close()

    def test_coverage_reference_rollover_matches_independent_object_compositing(self):
        from maniml.web.wgpu_renderer import WgpuRenderer
        renderer = WgpuRenderer()
        ordinary = _draw((.7, .2, .9, .05))
        covered = deepcopy(ordinary)
        covered.indices = np.tile(ordinary.indices, 2)
        covered.count = 12
        covered.coverage = True
        expected = renderer.render(*_message(*([ordinary] * 256), samples=4, supersample=2))
        actual = renderer.render(*_message(*([covered] * 256), samples=4, supersample=2))
        np.testing.assert_array_equal(actual, expected)
        renderer.close()

    def test_paint_storage_updates_change_pixels_without_geometry_upload(self):
        from maniml.web.geometry import GeometryCache
        from maniml.web.wgpu_renderer import WgpuRenderer
        renderer, cache = WgpuRenderer(), GeometryCache()
        draw = _draw(pipeline="paint")
        draw.paint = _constant_paint([1, 0, 0, .5])
        before = np.asarray(renderer.render(*_message(draw, cache=cache, samples=4, supersample=2)))
        geometry = next(iter(renderer._generated_geometry.values()))["buffer"]
        draw.paint = _constant_paint([0, 0, 1, .75])
        header, raw = _message(draw, cache=cache, samples=4, supersample=2)
        self.assertTrue(header["batches"][0]["cached"])
        self.assertEqual(len(raw), 96, "a new affine paint sends only its binary coefficients")
        after = np.asarray(renderer.render(header, raw))
        self.assertIs(next(iter(renderer._generated_geometry.values()))["buffer"], geometry)
        np.testing.assert_allclose(before[18, 32], [128, 0, 0, 128], atol=1)
        np.testing.assert_allclose(after[18, 32], [0, 0, 191, 191], atol=1)
        renderer.close()

    def test_binary_paint_shared_geometry_uses_distinct_materials_and_resets_cleanly(self):
        from maniml.web.geometry import GeometryCache
        from maniml.web.wgpu_renderer import WgpuRenderer
        renderer, cache = WgpuRenderer(), GeometryCache()
        left = _draw(pipeline="paint", uniforms={"clip_plane": [-1, 0, 0, 0]})
        right = _draw(pipeline="paint", uniforms={"clip_plane": [1, 0, 0, 0]})
        left.paint = _constant_paint([1, 0, 0, .5])
        right.paint = _constant_paint([0, 0, 1, .75])
        source = left.vertices.tobytes(), right.vertices.tobytes()
        try:
            header, raw = _message(left, right, cache=cache, samples=4, supersample=2)
            self.assertEqual(header["batches"][0]["hash"], header["batches"][1]["hash"])
            self.assertNotEqual(header["batches"][0]["paint_hash"], header["batches"][1]["paint_hash"])
            first = np.asarray(renderer.render(header, raw))
            np.testing.assert_allclose(first[18, 28], [128, 0, 0, 128], atol=1)
            np.testing.assert_allclose(first[18, 36], [0, 0, 191, 191], atol=1)
            geometry = next(iter(renderer._generated_geometry.values()))["buffer"]
            materials = dict(renderer._generated_paints)
            header, raw = _message(left, right, cache=cache, samples=4, supersample=2)
            self.assertEqual(raw, b"")
            np.testing.assert_array_equal(np.asarray(renderer.render(header, raw)), first)
            self.assertEqual(renderer._generated_paints, materials)
            self.assertIs(next(iter(renderer._generated_geometry.values()))["buffer"], geometry)
            missing = deepcopy(header)
            missing["batches"][0]["paint_hash"] = "f" * 32
            with self.assertRaisesRegex(KeyError, "paint cache miss"):
                renderer.render(missing, raw)
            np.testing.assert_array_equal(np.asarray(renderer.render(header, raw)), first)
            renderer.render(*_message(cache=cache, samples=4, supersample=2))
            self.assertFalse(renderer._generated_paints)
            self.assertFalse(renderer._generated_paint_bindings)
            np.testing.assert_array_equal(np.asarray(renderer.render(*_message(
                left, right, cache=cache, samples=4, supersample=2))), first)
            renderer.close()
            self.assertFalse(renderer._generated_paints)
            self.assertFalse(renderer._generated_paint_bindings)
            cache.reset()
            renderer = WgpuRenderer()
            np.testing.assert_array_equal(np.asarray(renderer.render(*_message(
                left, right, cache=cache, samples=4, supersample=2))), first)
            self.assertEqual((left.vertices.tobytes(), right.vertices.tobytes()), source)
        finally:
            renderer.close()

    def test_gpu_border_output_matches_cpu_emitter_and_keeps_source_immutable(self):
        from maniml.web.border_geometry import emit_border_triangles
        from maniml.web.wgpu_renderer import WgpuRenderer
        header, raw, source, fill = _border_wire(copies=2)
        header["batches"][1]["uniforms"].update(camera_position=[0, -10, 10], clip_plane=[1, 0, 0, 0])
        header["batches"][0]["uniforms"]["clip_plane"] = [-1, 0, 0, 0]
        source_bytes = source.tobytes(), fill.tobytes(), raw
        renderer = WgpuRenderer()
        try:
            for scale in (1, .95):
                header["camera"]["frame_scale"] = scale
                actual = np.asarray(renderer.render(header, raw))
                self.assertEqual(len(renderer._border_outputs), 2)
                cpu_draws = []
                for batch in header["batches"]:
                    uniforms = {**header["camera"], **batch["uniforms"]}
                    triangles, normals = emit_border_triangles(source, uniforms, return_normals=True)
                    vertices = np.zeros(len(fill) + triangles.size // 3, dtype=SURFACE_DTYPE)
                    vertices[:len(fill)] = fill
                    vertices["point"][len(fill):] = triangles.reshape(-1, 3)
                    vertices["d_normal_point"][len(fill):] = (triangles + .001 * normals).reshape(-1, 3)
                    vertices["rgba"][len(fill):] = [1, 0, 0, .5]
                    indices = np.r_[np.array([0, 1, 2, 0, 2, 3], dtype="u4"), np.arange(len(fill), len(vertices), dtype="u4")]
                    cpu_draws.append(SimpleNamespace(pipeline="surface", vertices=vertices, indices=indices,
                        count=len(indices), instances=1, uniforms=uniforms, coverage=True))
                expected = np.asarray(renderer.render(*_message(*cpu_draws, samples=4, supersample=2)))
                np.testing.assert_allclose(actual, expected, atol=1)
            self.assertEqual((source.tobytes(), fill.tobytes(), raw), source_bytes)
        finally:
            renderer.close()

    def test_gpu_border_only_geometry_with_empty_fill_renders(self):
        from maniml.web.border_geometry import emit_border_triangles
        from maniml.web.wgpu_renderer import WgpuRenderer
        header, raw, source, _ = _border_wire(fill_count=0)
        renderer = WgpuRenderer()
        try:
            actual = np.asarray(renderer.render(header, raw))
            self.assertTrue(np.any(actual[..., 3] > 0))
            uniforms = {**header["camera"], **header["batches"][0]["uniforms"]}
            triangles, normals = emit_border_triangles(source, uniforms, return_normals=True)
            vertices = np.zeros(triangles.size // 3, dtype=SURFACE_DTYPE)
            vertices["point"] = triangles.reshape(-1, 3)
            vertices["d_normal_point"] = (triangles + .001 * normals).reshape(-1, 3)
            vertices["rgba"] = [1, 0, 0, .5]
            draw = SimpleNamespace(pipeline="surface", vertices=vertices, indices=None,
                count=len(vertices), instances=1, uniforms=uniforms, coverage=True)
            expected = np.asarray(renderer.render(*_message(draw, samples=4, supersample=2)))
            np.testing.assert_allclose(actual, expected, atol=1)
        finally:
            renderer.close()

    def test_production_gpu_border_preserves_paint_depth_clip_fixed_family_and_stroke(self):
        from maniml import Circle, Square, VGroup
        from maniml.web.triangle_scene import prepare_triangle_frame, TriangleMeshCache
        from maniml.web.triangle_geometry import LyonFillTessellator
        from maniml.web.wgpu_renderer import WgpuRenderer
        from tests.renderer_quality_fixtures import _source_digest
        gradient = Square(fill_opacity=.45, fill_border_width=35, stroke_width=4).shift([-2, 0, 0])
        x = gradient.data["point"][:, 0]
        gradient.data["fill_rgba"][:, 0] = (x - x.min()) / (x.max() - x.min())
        gradient.data["fill_rgba"][:, 1] = .3
        gradient.data["fill_rgba"][:, 2] = .7
        depth = Circle(fill_opacity=.6, fill_border_width=25, stroke_width=3).shift([2, 0, .2])
        depth.apply_depth_test().set_clip_plane([1, 0, 0], -1.7).set_shading(.2, .1, .1)
        fixed = VGroup(Square(side_length=.6, fill_opacity=.35, fill_border_width=20,
                              stroke_width=2).shift([0, 1.5, 0])).fix_in_frame()
        scene = build_scene(gradient, depth, fixed, resolution=(160, 90))
        before = _source_digest(scene.mobjects)
        drivers = [WgpuRenderer(), WgpuRenderer()]
        caches = [TriangleMeshCache(), TriangleMeshCache()]
        from maniml.web.geometry import GeometryCache
        wires = [GeometryCache(), GeometryCache()]
        try:
            for scale in (1, .95):
                scene.camera.frame.scale(scale)
                scene.camera.refresh_uniforms()
                images, frames = [], []
                for gpu, driver, cache, wire in zip((False, True), drivers, caches, wires):
                    frame = prepare_triangle_frame(scene, LyonFillTessellator(), mesh_cache=cache,
                        fill_borders=True, gpu_borders=gpu)
                    frame.samples, frame.supersample = 4, 2
                    frames.append(frame)
                    header, payload = parse_geometry_message(serialize_generated_frame(frame, scene.camera.uniforms, wire))
                    images.append(np.asarray(driver.render(header, payload)))
                np.testing.assert_allclose(images[0], images[1], atol=1)
                cpu_strokes = [draw.vertices.tobytes() for draw in frames[0].draws if draw.pipeline.startswith("stroke")]
                gpu_strokes = [draw.vertices.tobytes() for draw in frames[1].draws if draw.pipeline.startswith("stroke")]
                self.assertTrue(cpu_strokes)
                self.assertEqual(cpu_strokes, gpu_strokes)
                self.assertEqual(_source_digest(scene.mobjects), before)
        finally:
            for driver in drivers:
                driver.close()

    def test_more_spatial_samples_converge_toward_exact_pixel_coverage(self):
        from benchmarks.renderer_aa import area_control
        from maniml.web.wgpu_renderer import WgpuRenderer
        renderer = WgpuRenderer()
        values = area_control(renderer)
        means = {name: np.mean([sample["rms_coverage_error"] for sample in samples])
                 for name, samples in values.items()}
        self.assertLess(means["ss2_msaa4"], means["msaa4"])
        self.assertLess(means["ss2_msaa4"], means["ss2"])
        renderer.close()

    def test_spatial_resolve_matches_high_resolution_rgba_during_subpixel_motion_and_resize(self):
        from maniml.web.wgpu_renderer import WgpuRenderer
        renderer = WgpuRenderer()
        draw = _draw((.8, .3, .5, .4))
        draw.vertices["point"][2, :2] = [.17, 1.51]
        pictures = []
        for samples in (1, 4):
            for shift in (0., .037, .081):
                moved = deepcopy(draw)
                moved.vertices["point"][:, 0] += shift
                header, raw = _message(moved, samples=samples, supersample=2,
                                        background=(.2, .3, .4, .25))
                before = deepcopy(header)
                low = np.asarray(renderer.render(header, raw))
                high_header = deepcopy(header)
                high_header["resolution"] = [128, 72]
                high_header["supersample"] = 1
                high_header["camera"]["pixel_size"] /= 2
                for batch in high_header["batches"]:
                    batch["uniforms"]["anti_alias_width"] = 2 * batch["uniforms"].get("anti_alias_width", 1.5)
                high = np.asarray(renderer.render(high_header, raw))
                expected = high.reshape(36, 2, 64, 2, 4).mean(axis=(1, 3))
                self.assertLessEqual(float(np.abs(low - expected).max()), .501)
                self.assertEqual(header, before)
                pictures.append(low)
        self.assertFalse(np.array_equal(pictures[0], pictures[2]))
        renderer.close()
        renderer.close()
        with self.assertRaisesRegex(RuntimeError, "closed"):
            renderer.render(header, raw)

    def test_all_primitive_layouts_textures_and_delta_lifetime(self):
        from PIL import Image
        from maniml.mobject.geometry import Square
        from maniml.mobject.types.dot_cloud import DotCloud
        from maniml.mobject.types.image_mobject import ImageMobject
        from maniml.mobject.types.surface import Surface, TexturedSurface
        from maniml.web.geometry import GeometryCache
        from tests.winding_reference_geometry import serialize_scene
        from tests.winding_reference_renderer import WgpuRenderer as WindingRenderer
        from maniml.web.triangle_scene import prepare_triangle_frame
        from maniml.web.wgpu_renderer import WgpuRenderer
        generated, legacy = WgpuRenderer(), WindingRenderer()
        def render(message):
            # This comparison isolates primitive semantics; spatial AA has its
            # own exact-resolve and quality tests against native goldens.
            header, raw = message
            header["supersample"] = 1
            return generated.render(header, raw)
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
                    frame.samples = 1
                    self.assertEqual({draw.pipeline.removesuffix("_depth") for draw in frame.draws}, {kind})
                    cache = GeometryCache()
                    first = parse_geometry_message(serialize_generated_frame(frame, scene.camera.uniforms, cache))
                    pixels = np.asarray(render(first))
                    reference = np.asarray(legacy.render(*parse_geometry_message(serialize_scene(scene))))
                    np.testing.assert_allclose(pixels[..., :3], reference[..., :3], atol=1)
                    self.assertGreater(np.count_nonzero(pixels[..., :3]), 0)
                    same = parse_geometry_message(serialize_generated_frame(frame, scene.camera.uniforms, cache))
                    self.assertEqual(same[1], b"")
                    np.testing.assert_array_equal(render(same), pixels)
                    absent = deepcopy(frame)
                    absent.draws = []
                    render(parse_geometry_message(serialize_generated_frame(absent, scene.camera.uniforms, cache)))
                    self.assertFalse(generated._generated_geometry)
                    self.assertFalse(generated._generated_uniforms)
                    self.assertFalse(generated._generated_textures)
                    self.assertFalse(generated.texture_cache)
                    returning = parse_geometry_message(serialize_generated_frame(frame, scene.camera.uniforms, cache))
                    self.assertTrue(all(not batch.get("cached") for batch in returning[0]["batches"]))
                    if kind in ("image", "texsurface"):
                        self.assertTrue(returning[0]["texture_data"])
                    np.testing.assert_array_equal(render(returning), pixels)

    def test_depth_draws_occlude_independently_of_order_and_painter_overlay_wins(self):
        from maniml.web.wgpu_renderer import WgpuRenderer
        renderer = WgpuRenderer()
        red = _draw((1, 0, 0, 1), pipeline="surface_depth")
        blue = _draw((0, 0, 1, 1), pipeline="surface_depth")
        blue.vertices["point"][:, 2] = .5
        blue.vertices["d_normal_point"][:, 2] = .501
        first = renderer.render(*_message(red, blue, samples=4, supersample=2))
        second = renderer.render(*_message(blue, red, samples=4, supersample=2))
        np.testing.assert_array_equal(first, second)
        overlay = _draw((1, 1, 1, 1))
        overlay.vertices["point"][:, 2] = -10
        overlay.vertices["d_normal_point"][:, 2] = -9.999
        overlaid = renderer.render(*_message(red, blue, overlay, samples=4, supersample=2))
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

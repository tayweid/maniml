"""Native mirror of the canonical browser WebGPU renderer.

Consumes the geometry messages emitted by web/geometry.py and renders them
with wgpu, compiling the WGSL shaders in web/static/wgsl/. The same WGSL and
pass structure run in the browser via WebGPU; this module is the pixel-diff
implementation used by native capture and file output.

WebGPU-vs-GL differences handled here rather than in shaders:
- blend and depth state are baked per pipeline (a lazy cache keyed on
  (name, sample_count) instead of dynamic GL state);
- uniforms travel in one packed 192-byte buffer (see UNIFORM_FIELDS,
  which must match struct Uniforms in wgsl/common.wgsl);
- MSAA is a multisampled color target resolved into a plain texture,
  declared per pipeline;
- readback rows come out top-down (no flip, unlike GL).
The clip-space depth-range difference lives in emit_gl_position.
"""

from __future__ import annotations

import io
import os
import json
import re
import struct
from math import lcm

import numpy as np

from maniml.web.gpu_border_geometry import (
    INDICES_PER_CURVE, MAX_BORDER_CURVES, MAX_VERTICES_PER_CURVE, OBJECT_BYTES, OBJECT_WORDS,
    PATCH_VERTICES_PER_CURVE, border_indices, expand_run_indices, indices_per_curve,
    patch_draw_count, patch_groups, validate_capacity, validate_layout, validate_objects,
    validate_patch_layout,
)
from maniml.web import gpu_net_geometry
from PIL import Image

import wgpu

WGSL_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "static", "wgsl")

VERTEX_STRIDE = 68
INSTANCE_STRIDE = 3 * VERTEX_STRIDE

# (name, components, default) in struct order; vec3s pair with the
# following scalar to satisfy WGSL's 16-byte alignment
UNIFORM_FIELDS = [
    ("view", 16, None),
    ("frame_rescale_factors", 3, None), ("is_fixed_in_frame", 1, 0.0),
    ("camera_position", 3, None), ("frame_scale", 1, 1.0),
    ("light_position", 3, None), ("pixel_size", 1, 1.0),
    ("shading", 3, (0.0, 0.0, 0.0)), ("anti_alias_width", 1, 1.5),
    ("clip_plane", 4, (0.0, 0.0, 0.0, 0.0)),
    ("joint_type", 1, 1.0), ("flat_stroke", 1, 0.0),
    ("scale_stroke_with_zoom", 1, 1.0), ("glow_factor", 1, 0.0),
    ("num_textures", 1, 0.0), ("border_mode", 1, 0.0),
    ("premultiplied_output", 1, 0.0), ("_pad1", 1, 0.0),
    ("clip_transform", 4, (1.0, 1.0, 0.0, 0.0)),
]
UNIFORM_BYTES = sum(n for _, n, _ in UNIFORM_FIELDS) * 4  # 192


def pack_uniforms(values: dict, border_mode: float = 0.0) -> bytes:
    out = np.zeros(UNIFORM_BYTES // 4, dtype=np.float32)
    cursor = 0
    for name, n, default in UNIFORM_FIELDS:
        value = values.get(name, default)
        if name == "border_mode":
            value = border_mode
        if value is None:
            raise KeyError(f"uniform {name} missing and has no default")
        out[cursor:cursor + n] = np.asarray(value, dtype=np.float32).ravel()
        cursor += n
    return out.tobytes()


def _attr(fmt, offset, location):
    return {"format": fmt, "offset": offset, "shader_location": location}


def _layout(stride, step_mode, attributes):
    return [{"array_stride": stride, "step_mode": step_mode,
             "attributes": attributes}]


_INSTANCE = wgpu.VertexStepMode.instance
_VERTEX = wgpu.VertexStepMode.vertex

STROKE_LAYOUT = _layout(INSTANCE_STRIDE, _INSTANCE, [
    _attr("float32x3", 0, 0), _attr("float32x3", 68, 1),
    _attr("float32x3", 136, 2),
    _attr("float32x4", 12, 3), _attr("float32x4", 80, 4),
    _attr("float32x4", 148, 5),
    _attr("float32", 28, 6), _attr("float32", 96, 7),
    _attr("float32", 164, 8),
    _attr("float32", 32, 9), _attr("float32", 168, 10),
    _attr("float32x3", 120, 11),
])
SURFACE_LAYOUT = _layout(40, _VERTEX, [
    _attr("float32x3", 0, 0), _attr("float32x3", 12, 1),
    _attr("float32x4", 24, 2),
])
DOT_LAYOUT = _layout(32, _INSTANCE, [
    _attr("float32x3", 0, 0), _attr("float32", 12, 1),
    _attr("float32x4", 16, 2),
])
IMAGE_LAYOUT = _layout(24, _VERTEX, [
    _attr("float32x3", 0, 0), _attr("float32x2", 12, 1),
    _attr("float32", 20, 2),
])
TEXSURFACE_LAYOUT = _layout(36, _VERTEX, [
    _attr("float32x3", 0, 0), _attr("float32x3", 12, 1),
    _attr("float32x2", 24, 2), _attr("float32", 32, 3),
])

PREMULTIPLIED_BLEND = {
    "color": {"src_factor": "one", "dst_factor": "one-minus-src-alpha",
              "operation": "add"},
    "alpha": {"src_factor": "one", "dst_factor": "one-minus-src-alpha",
              "operation": "add"},
}

DEPTH_FORMAT = "depth24plus-stencil8"

# Generated operations share one premultiplied scene target. The optional
# depth variant compares/writes scene depth; painter operations leave it alone.
# name -> (module, layout, topology, target, blend, depth_test)
PIPELINE_SPECS = {}
for _module, _layout_spec, _topology in (
    ("stroke", STROKE_LAYOUT, "triangle-strip"),
    ("surface", SURFACE_LAYOUT, "triangle-list"),
    ("paint", SURFACE_LAYOUT, "triangle-list"),
    ("dot", DOT_LAYOUT, "triangle-strip"),
    ("image", IMAGE_LAYOUT, "triangle-list"),
    ("texsurface", TEXSURFACE_LAYOUT, "triangle-list"),
):
    for _depth in (False, True):
        PIPELINE_SPECS[f"generated_{_module}" + ("_depth" if _depth else "")] = (
            _module, _layout_spec, _topology, "out", PREMULTIPLIED_BLEND, _depth)

# An object's fill and hard border share per-sample coverage ownership. Depth
# objects replay geometry without color writes to preserve nearest depth even
# where a later border triangle shared a covered fill sample.
for _name, _spec in tuple(PIPELINE_SPECS.items()):
    if _spec[0] in ("surface", "paint"):
        PIPELINE_SPECS[_name + "_coverage"] = _spec
        if _spec[-1]:
            PIPELINE_SPECS[_name + "_depth_only"] = _spec

# The patch fill (docs/phase_b1_plan.md): fan and patch triangles pulled
# from storage, counted on the stencil, then covered. Their pipelines carry
# explicit layouts and stencil states (WgpuRenderer._patch_pipeline); the
# object's border strips go through the surface and paint pipelines with the
# strip stencil states below.
for _depth in (False, True):
    PIPELINE_SPECS["generated_patch" + ("_depth" if _depth else "")] = (
        "patch_fill", [], "triangle-list", "out", PREMULTIPLIED_BLEND, _depth)
for _name, _spec in tuple(PIPELINE_SPECS.items()):
    if _spec[0] in ("surface", "paint") and _name.endswith(("surface", "paint", "_depth")):
        PIPELINE_SPECS[_name + "_strip_cover"] = _spec
        if _spec[0] == "surface":
            PIPELINE_SPECS[_name + "_strip_mark"] = _spec
PATCH_STRIP_REFERENCE = 0x80
PATCH_COUNT_MASK = 0x7F
STENCIL_KEEP = {"compare": "always", "fail_op": "keep", "depth_fail_op": "keep", "pass_op": "keep"}
STENCIL_STRIP_MARK = {"compare": "always", "fail_op": "keep", "depth_fail_op": "keep", "pass_op": "replace"}
STENCIL_COVER = {"compare": "not-equal", "fail_op": "keep", "depth_fail_op": "zero", "pass_op": "zero"}

MODULE_SOURCES = {
    "stroke": ("common.wgsl", "stroke.wgsl"),
    "surface": ("common.wgsl", "surface.wgsl"),
    "paint": ("common.wgsl", "paint_field.wgsl", "paint.wgsl"),
    "dot": ("common.wgsl", "dot.wgsl"),
    "image": ("common.wgsl", "image.wgsl"),
    "texsurface": ("common.wgsl", "texsurface.wgsl"),
    "resolve2": ("resolve2.wgsl",),
    "border_compute": ("common.wgsl", "border_compute.wgsl"),
    "patch_fill": ("common.wgsl", "paint_field.wgsl", "patch_fill.wgsl"),
    "net_compute": ("common.wgsl", "net_compute.wgsl"),
}


def load_wgsl(*names: str) -> str:
    parts = []
    for name in names:
        with open(os.path.join(WGSL_DIR, name)) as f:
            parts.append(f.read())
    return "\n".join(parts)


class WgpuRenderer:
    """Renders parsed geometry messages with WebGPU."""

    def __init__(self):
        adapter = wgpu.gpu.request_adapter_sync(
            power_preference="high-performance")
        self.device = adapter.request_device_sync()
        self._modules = {
            key: self.device.create_shader_module(code=load_wgsl(*sources))
            for key, sources in MODULE_SOURCES.items()
        }
        self._pipelines = {}  # (name, sample_count) -> pipeline
        self.sampler = self.device.create_sampler(
            mag_filter="linear", min_filter="linear",
            address_mode_u="repeat", address_mode_v="repeat")
        self.texture_cache: dict[str, wgpu.GPUTexture] = {}
        # Sender and receiver retain exactly the active frame resources.
        self._generated_geometry = {}
        self._generated_uniforms = {}
        self._generated_textures = {}
        self._generated_paints = {}  # paint identity -> (storage buffer, exact bytes)
        self._generated_paint_bindings = {}
        self._border_sources = {}
        self._border_outputs = {}
        self._border_compute_pipeline = None
        # Patch fills: object tables by hash, group-0 bindings by
        # (samples, uniforms), and the explicit layouts every patch pipeline
        # shares.
        self._object_tables = {}
        self._patch_uniforms = {}
        self._patch_layouts = None
        # Surface nets: sources by hash, evaluated outputs by occurrence.
        self._net_sources = {}
        self._net_outputs = {}
        self._net_compute_pipeline = None
        self._stale_index_buffers = []
        self._size = None
        self._spatial_texture = None
        self._spatial_pipeline = None
        self._spatial_binding = None
        self._closed = False

    def _pipeline(self, name, samples):
        key = (name, samples)
        if key in self._pipelines:
            return self._pipelines[key]
        module_key, layout, topology, target, blend, depth_test = \
            PIPELINE_SPECS[name]
        descriptor = dict(
            layout="auto",
            vertex={"module": self._modules[module_key],
                    "entry_point": "vs_main", "buffers": layout},
            primitive={"topology": topology},
        )
        coverage = name.endswith("_coverage")
        depth_only = name.endswith("_depth_only")
        strip_mark, strip_cover = name.endswith("_strip_mark"), name.endswith("_strip_cover")
        descriptor["fragment"] = {
            "module": self._modules[module_key], "entry_point": "fs_main",
            "targets": [{"format": "rgba8unorm", "blend": blend,
                         "write_mask": 0 if depth_only or strip_mark else wgpu.ColorWrite.ALL}]}
        if strip_mark or strip_cover:
            # A patch object's strips: the mark sets the border bit; the
            # cover paints where the byte is nonzero and zeroes it, writing
            # depth for a depth object (patch_fill.wgsl).
            face = STENCIL_STRIP_MARK if strip_mark else STENCIL_COVER
            descriptor["depth_stencil"] = {
                "format": DEPTH_FORMAT,
                "depth_write_enabled": depth_test and strip_cover,
                "depth_compare": "less" if depth_test and strip_cover else "always",
                "stencil_front": face, "stencil_back": face,
                "stencil_read_mask": 255,
                "stencil_write_mask": PATCH_STRIP_REFERENCE if strip_mark else 255,
            }
        else:
            descriptor["depth_stencil"] = {
                "format": DEPTH_FORMAT,
                "depth_write_enabled": depth_test and not coverage,
                "depth_compare": "less" if depth_test else "always",
                "stencil_front": {"compare": "not-equal" if coverage else "always",
                                  "fail_op": "keep", "depth_fail_op": "keep",
                                  "pass_op": "replace" if coverage else "keep"},
                "stencil_back": {"compare": "not-equal" if coverage else "always",
                                 "fail_op": "keep", "depth_fail_op": "keep",
                                 "pass_op": "replace" if coverage else "keep"},
                "stencil_read_mask": 255, "stencil_write_mask": 255 if coverage else 0,
            }
        descriptor["multisample"] = {"count": samples}
        pipeline = self.device.create_render_pipeline(**descriptor)
        self._pipelines[key] = pipeline
        return pipeline

    def _patch_bind_layouts(self):
        """(group 0, group 1, group 2, plain pipeline layout, paint pipeline
        layout) for the patch pipelines. Explicit, so one bind group serves
        every variant."""
        if self._patch_layouts is None:
            device = self.device
            both = wgpu.ShaderStage.VERTEX | wgpu.ShaderStage.FRAGMENT
            group0 = device.create_bind_group_layout(entries=[
                {"binding": 0, "visibility": both, "buffer": {"type": "uniform"}}])
            group1 = device.create_bind_group_layout(entries=[
                {"binding": index, "visibility": wgpu.ShaderStage.VERTEX,
                 "buffer": {"type": "read-only-storage"}} for index in range(2)])
            group2 = device.create_bind_group_layout(entries=[
                {"binding": 0, "visibility": wgpu.ShaderStage.FRAGMENT,
                 "buffer": {"type": "read-only-storage"}}])
            self._patch_layouts = (
                group0, group1, group2,
                device.create_pipeline_layout(bind_group_layouts=[group0, group1]),
                device.create_pipeline_layout(bind_group_layouts=[group0, group1, group2]))
        return self._patch_layouts

    def _patch_pipeline(self, kind, depth, samples):
        """``mark_fan`` and ``mark_patch`` count winding in the stencil's low
        seven bits (the patch draw per sample, with the curve test);
        ``cover`` and ``cover_paint`` paint where the byte is nonzero and
        zero it; see patch_fill.wgsl. The strips use the surface pipelines'
        strip states."""
        key = (("patch", kind, depth), samples)
        pipeline = self._pipelines.get(key)
        if pipeline is not None:
            return pipeline
        _, _, _, plain, with_paint = self._patch_bind_layouts()
        module = self._modules["patch_fill"]
        cover = kind.startswith("cover")
        vertex_entry = {"mark_fan": "vs_fan", "mark_patch": "vs_patch",
                        "cover": "vs_cover", "cover_paint": "vs_cover"}[kind]
        entry = {"mark_fan": "fs_mark_fan", "mark_patch": "fs_mark_patch",
                 "cover": "fs_surface", "cover_paint": "fs_paint"}[kind]
        if kind.startswith("mark"):
            stencil = {"front": "increment-wrap", "back": "decrement-wrap", "compare": "always",
                       "depth_fail": "keep", "write": PATCH_COUNT_MASK}
        else:
            stencil = {"front": "zero", "back": "zero", "compare": "not-equal",
                       "depth_fail": "zero", "write": 255}
        face = lambda op: {"compare": stencil["compare"], "fail_op": "keep",
                           "depth_fail_op": stencil["depth_fail"], "pass_op": op}
        pipeline = self.device.create_render_pipeline(
            layout=with_paint if kind == "cover_paint" else plain,
            vertex={"module": module, "entry_point": vertex_entry, "buffers": []},
            primitive={"topology": "triangle-list"},
            fragment={"module": module, "entry_point": entry, "targets": [
                {"format": "rgba8unorm", "blend": PREMULTIPLIED_BLEND,
                 "write_mask": wgpu.ColorWrite.ALL if cover else 0}]},
            depth_stencil={
                "format": DEPTH_FORMAT,
                "depth_write_enabled": depth and cover,
                "depth_compare": "less" if depth and cover else "always",
                "stencil_front": face(stencil["front"]), "stencil_back": face(stencil["back"]),
                "stencil_read_mask": 255, "stencil_write_mask": stencil["write"]},
            multisample={"count": samples})
        self._pipelines[key] = pipeline
        return pipeline

    def _net_index_buffer(self, batch, resources):
        """The triangle pattern over every patch of a net at its capacity."""
        net = batch["net"]
        capacity = net["capacity"]
        buffers = resources["index_buffers"]
        index_buffer = buffers.get(capacity)
        if index_buffer is None:
            patches = ((net["nu"] - 1) // 2) * ((net["nv"] - 1) // 2)
            index_buffer = self.device.create_buffer_with_data(
                data=gpu_net_geometry.net_indices(patches, capacity).tobytes(), usage=wgpu.BufferUsage.INDEX)
            self._stale_index_buffers.extend(buffers.values())
            buffers.clear()
            buffers[capacity] = index_buffer
        return index_buffer

    def _prepare_nets(self, header, payload, encoder, temporary):
        """Evaluate changed surface nets before the ordered render pass."""
        records = header.get("net_data", {})
        if not isinstance(records, dict):
            raise ValueError("net definitions must be an object")
        definitions = {}
        for key, ref in records.items():
            if not isinstance(key, str) or re.fullmatch(r"[0-9a-f]{32}", key) is None:
                raise ValueError("invalid net hash")
            if not isinstance(ref, dict):
                raise ValueError("invalid net definition span")
            offset, size = ref.get("offset"), ref.get("nbytes")
            if (type(offset) is not int or type(size) is not int or size <= 0 or size % 4
                    or offset < 0 or offset > len(payload) or size > len(payload) - offset):
                raise ValueError("invalid net definition span")
            data = bytes(payload[offset:offset + size])
            if not np.isfinite(np.frombuffer(data, dtype="<f4")).all():
                raise ValueError("net control points must be finite")
            previous = self._net_sources.get(key)
            if previous is not None and previous["data"] != data:
                raise ValueError("net hash redefined with different control points")
            definitions[key] = data
        limits = getattr(self.device, "limits", {})
        max_buffer = limits.get("max-buffer-size", 256 * 1024 ** 2)
        max_storage = limits.get("max-storage-buffer-binding-size", 128 * 1024 ** 2)
        max_dispatch = limits.get("max-compute-workgroups-per-dimension", 65535)
        outputs, used_sources, used_outputs, completed = {}, set(), set(), []
        uniform_buffers, occurrences = {}, {}
        for batch in header["batches"]:
            net = batch.get("net")
            if net is None:
                continue
            if header.get("format_version", 0) < 7 or not isinstance(net, dict):
                raise ValueError("a surface net requires a format 7 net descriptor")
            key, nu, nv = net.get("hash"), net.get("nu"), net.get("nv")
            channels, capacity, density = net.get("channels"), net.get("capacity"), net.get("density")
            if (not isinstance(key, str) or re.fullmatch(r"[0-9a-f]{32}", key) is None
                    or any(type(v) is not int for v in (nu, nv, channels, capacity))
                    or nu < 3 or nv < 3 or nu % 2 == 0 or nv % 2 == 0
                    or not isinstance(density, (int, float)) or isinstance(density, bool)
                    or not np.isfinite(density) or density < 0
                    or batch.get("pipeline") not in ("surface", "surface_depth", "texsurface", "texsurface_depth")
                    or channels * 4 != batch.get("stride") or batch.get("indexed") is not False
                    or batch.get("fill_num_verts") != 0 or batch.get("index_count") != 0
                    or type(batch.get("instances")) is not int or batch["instances"] != 1):
                raise ValueError("invalid surface net descriptor")
            capacity = gpu_net_geometry.validate_capacity(capacity)
            patches = ((nu - 1) // 2) * ((nv - 1) // 2)
            vertex_count = patches * gpu_net_geometry.vertices_per_patch(capacity)
            if (batch.get("num_verts") != vertex_count
                    or batch.get("count") != patches * gpu_net_geometry.indices_per_patch(capacity)):
                raise ValueError("invalid surface net vertex or draw count")
            size = vertex_count * batch["stride"]
            if size > max_buffer or size > max_storage:
                raise ValueError("surface net output exceeds device buffer limits")
            source = self._net_sources.get(key)
            data = definitions.get(key) if source is None else source["data"]
            if data is None:
                raise KeyError(f"net cache miss for {key}")
            if len(data) != nu * nv * channels * 4 or len(data) > max_storage:
                raise ValueError("net definition does not match its descriptor")
            values = {**header["camera"], **batch.get("uniforms", {})}
            packed = pack_uniforms(values)
            floats = np.frombuffer(packed, dtype="<f4")
            if not np.isfinite(floats).all() or floats[23] <= 0:
                raise ValueError("invalid surface net uniforms")
            resources = self._generated_resources(batch, payload)
            if source is None:
                source = {"data": data, "buffer": self.device.create_buffer_with_data(
                    data=data, usage=wgpu.BufferUsage.STORAGE)}
                self._net_sources[key] = source
            used_sources.add(key)
            occurrence = occurrences.get((batch["hash"], key), 0)
            occurrences[(batch["hash"], key)] = occurrence + 1
            output_key = (batch["hash"], key, capacity, occurrence)
            used_outputs.add(output_key)
            output = self._net_outputs.get(output_key)
            if self._net_compute_pipeline is None:
                self._net_compute_pipeline = self.device.create_compute_pipeline(layout="auto",
                    compute={"module": self._modules["net_compute"], "entry_point": "cs_main"})
            pipeline = self._net_compute_pipeline
            if output is None:
                buffer = self.device.create_buffer(size=size,
                    usage=wgpu.BufferUsage.STORAGE | wgpu.BufferUsage.VERTEX | wgpu.BufferUsage.COPY_DST)
                output = {"buffer": buffer, "state": None}
                self._net_outputs[output_key] = output
                output["binding"] = self.device.create_bind_group(layout=pipeline.get_bind_group_layout(1), entries=[
                    {"binding": 0, "resource": {"buffer": source["buffer"], "size": len(data)}},
                    {"binding": 1, "resource": {"buffer": buffer, "size": size}}])
            outputs[id(batch)] = output
            ppu = gpu_net_geometry.pixels_per_unit(values, header["resolution"])
            state = (float(floats[23]), float(density), float(ppu))
            if output["state"] == state:
                continue
            camera = uniform_buffers.get(packed)
            if camera is None:
                camera = self.device.create_buffer_with_data(data=packed, usage=wgpu.BufferUsage.UNIFORM)
                uniform_buffers[packed] = camera
                temporary.append(camera)
            compute = encoder.begin_compute_pass()
            compute.set_pipeline(pipeline)
            compute.set_bind_group(1, output["binding"])
            per_patch = gpu_net_geometry.vertices_per_patch(capacity)
            for offset in range(0, patches, max_dispatch):
                chunk = min(max_dispatch, patches - offset)
                params = self.device.create_buffer_with_data(data=struct.pack("<IIIIIIIIffff",
                    0, nu, nv, channels, capacity, offset * per_patch, offset, chunk, float(density), float(ppu), 0.0, 0.0),
                    usage=wgpu.BufferUsage.UNIFORM)
                temporary.append(params)
                group = self.device.create_bind_group(layout=pipeline.get_bind_group_layout(0), entries=[
                    {"binding": 0, "resource": {"buffer": camera, "size": UNIFORM_BYTES}},
                    {"binding": 1, "resource": {"buffer": params, "size": 48}}])
                compute.set_bind_group(0, group)
                compute.dispatch_workgroups(chunk, (per_patch + 63) // 64)
            compute.end()
            completed.append((output, state))
        return outputs, used_sources, used_outputs, completed

    def _patch_index_buffer(self, batch, resources):
        """The strip pattern of every curve in a patch run at its current
        capacity: the index buffer both strip draws address per object."""
        capacity, _ = self._border_run(batch)
        buffers = resources["index_buffers"]
        index_buffer = buffers.get(capacity)
        if index_buffer is None:
            indices = border_indices(batch["border"]["num_curves"], 0, capacity)
            index_buffer = self.device.create_buffer_with_data(
                data=indices.tobytes(), usage=wgpu.BufferUsage.INDEX)
            self._stale_index_buffers.extend(buffers.values())
            buffers.clear()
            buffers[capacity] = index_buffer
        return index_buffer

    def _ensure_targets(self, size, samples):
        if self._size == (size, samples):
            return
        for texture in (getattr(self, "out_texture", None), getattr(self, "resolve_texture", None),
                        getattr(self, "depth_texture", None), self._spatial_texture):
            if texture is not None:
                texture.destroy()
        self._spatial_texture = None
        self._spatial_binding = None
        self._size = (size, samples)
        device = self.device
        usage = wgpu.TextureUsage.RENDER_ATTACHMENT
        self.resolve_texture = None
        if samples > 1:
            self.out_texture = device.create_texture(
                size=(*size, 1), format="rgba8unorm", sample_count=samples,
                usage=usage)
            self.resolve_texture = device.create_texture(
                size=(*size, 1), format="rgba8unorm",
                usage=usage | wgpu.TextureUsage.COPY_SRC | wgpu.TextureUsage.TEXTURE_BINDING)
            self.resolve_view = self.resolve_texture.create_view()
        else:
            self.out_texture = device.create_texture(
                size=(*size, 1), format="rgba8unorm",
                usage=usage | wgpu.TextureUsage.COPY_SRC | wgpu.TextureUsage.TEXTURE_BINDING)
        self.out_view = self.out_texture.create_view()
        self.depth_texture = device.create_texture(
            size=(*size, 1), format=DEPTH_FORMAT, sample_count=samples,
            usage=wgpu.TextureUsage.RENDER_ATTACHMENT)
        self.depth_view = self.depth_texture.create_view()

    def _out_pass(self, encoder, clear_color=None, *, clear_stencil=False):
        color = {
            "view": self.out_view,
            "load_op": "clear" if clear_color is not None else "load",
            "store_op": "store",
        }
        if clear_color is not None:
            color["clear_value"] = tuple(clear_color)
        if self.resolve_texture is not None:
            color["resolve_target"] = self.resolve_view
        return encoder.begin_render_pass(
            color_attachments=[color],
            depth_stencil_attachment={
                "view": self.depth_view,
                "depth_load_op": "clear" if clear_color is not None
                else "load",
                "depth_store_op": "store",
                "depth_clear_value": 1.0,
                "stencil_load_op": "clear" if clear_color is not None or clear_stencil else "load",
                "stencil_store_op": "store", "stencil_clear_value": 0,
            })

    def _texture_bind_group(self, pipeline, batch):
        hashes = list(batch.get("textures", {}).values())
        views = [self.texture_cache[h].create_view() for h in hashes]
        if len(views) == 1 and PIPELINE_SPECS[
                self._batch_pipeline_name(batch)][0] == "texsurface":
            views.append(views[0])  # DarkTexture falls back to light
        entries = [{"binding": i, "resource": v} for i, v in enumerate(views)]
        entries.append({"binding": len(views), "resource": self.sampler})
        return self.device.create_bind_group(
            layout=pipeline.get_bind_group_layout(1), entries=entries)

    @staticmethod
    def _batch_pipeline_name(batch):
        return "generated_" + batch["pipeline"]

    def render(self, header: dict, vertex_bytes: bytes) -> Image.Image:
        """Return final-resolution premultiplied RGBA; Camera owns file conversion."""
        if getattr(self, "_closed", False):
            raise RuntimeError("renderer is closed")
        if header.get("renderer") != "triangles":
            raise ValueError("native renderer requires generated triangle geometry")
        return self._render_generated(header, vertex_bytes)

    def _border_run(self, batch):
        """(capacity, layout) of a GPU border batch; layout is None for the
        format 5 wire, whose complete index buffer travelled with the fill.
        A cached format 6 batch omits its layout: the retained geometry
        holds it."""
        border = batch.get("border")
        if border is None:
            return None, None
        if "capacity" not in border:
            return MAX_VERTICES_PER_CURVE, None
        capacity = validate_capacity(border.get("capacity"))
        layout = border.get("layout")
        if layout is None:
            resources = self._generated_geometry.get(batch["hash"])
            if resources is None or "run_layout" not in resources:
                raise KeyError(f"generated geometry cache miss for batch {batch['hash']}")
            layout = resources["run_layout"]
        return capacity, layout

    def _generated_resources(self, batch, vertex_bytes):
        capacity, run_layout = self._border_run(batch)
        # A run's reserved capacity changes its output size but not what
        # was uploaded, so it stays out of the retained layout identity; a
        # surface net's evaluated vertex count likewise.
        layout = (batch["pipeline"], batch["stride"],
                  None if run_layout is not None or "net" in batch else batch["num_verts"],
                  bool(batch.get("indexed")), batch.get("index_count", 0),
                  batch.get("fill_num_verts", batch["num_verts"]),
                  None if run_layout is None else json.dumps(run_layout))
        resources = self._generated_geometry.get(batch["hash"])
        if resources is not None:
            if resources["layout"] != layout:
                raise ValueError("cached generated geometry layout changed")
            return resources
        if batch.get("cached"):
            raise KeyError(f"generated geometry cache miss for batch {batch['hash']}")

        def buffer(offset, size, usage):
            if (type(offset) is not int or type(size) is not int
                    or not 0 <= offset <= len(vertex_bytes) or not 0 <= size <= len(vertex_bytes) - offset):
                raise ValueError("generated geometry buffer extends beyond payload")
            if size == 0:
                # Border-only paths have no fill prefix; no map or copy is needed.
                return self.device.create_buffer(size=4, usage=usage)
            return self.device.create_buffer_with_data(
                data=vertex_bytes[offset:offset + size], usage=usage)

        fill_count = batch.get("fill_num_verts", batch["num_verts"])
        vertex_usage = wgpu.BufferUsage.VERTEX | (wgpu.BufferUsage.COPY_SRC if batch.get("border") else 0)
        resources = {"layout": layout, "buffer": buffer(
            batch["offset"], fill_count * batch["stride"], vertex_usage)}
        try:
            if batch.get("indexed") and run_layout is not None:
                # Only the fill indices travel. Keep them to expand the
                # ordered fill/strip buffer for whatever capacity is drawn.
                offset, size = batch["index_offset"], batch["index_count"] * 4
                if (type(offset) is not int or not 0 <= offset <= len(vertex_bytes)
                        or not 0 <= size <= len(vertex_bytes) - offset):
                    raise ValueError("generated geometry buffer extends beyond payload")
                resources["fill_indices"] = bytes(vertex_bytes[offset:offset + size])
                resources["index_buffers"] = {}
                resources["run_layout"] = run_layout
            elif batch.get("indexed"):
                resources["index_buffer"] = buffer(
                    batch["index_offset"], batch["index_count"] * 4, wgpu.BufferUsage.INDEX)
            elif run_layout is not None:
                resources["run_layout"] = run_layout
                resources["index_buffers"] = {}
            elif "net" in batch:
                resources["index_buffers"] = {}
        except Exception:
            resources["buffer"].destroy()
            raise
        self._generated_geometry[batch["hash"]] = resources
        return resources

    def _run_index_buffer(self, batch, resources):
        """The expanded index buffer for a border run at its current capacity."""
        capacity, run_layout = self._border_run(batch)
        buffers = resources["index_buffers"]
        index_buffer = buffers.get(capacity)
        if index_buffer is None:
            fill_count = batch["fill_num_verts"]
            expanded = expand_run_indices(np.frombuffer(resources["fill_indices"], dtype="<u4"),
                                          run_layout, fill_count, capacity)
            if len(expanded) != batch["count"]:
                raise ValueError("invalid GPU border geometry layout or draw count")
            index_buffer = self.device.create_buffer_with_data(
                data=expanded.tobytes(), usage=wgpu.BufferUsage.INDEX)
            # An earlier reservation's buffer is retired after this frame's
            # commands, like every other generated resource.
            self._stale_index_buffers.extend(buffers.values())
            buffers.clear()
            buffers[capacity] = index_buffer
        return index_buffer

    def _prepare_borders(self, header, payload, encoder, temporary):
        """Generate changed border tails before the ordered render pass begins."""
        records = header.get("border_data", {})
        if not isinstance(records, dict):
            raise ValueError("border definitions must be an object")
        definitions = {}
        for key, ref in records.items():
            if not isinstance(key, str) or re.fullmatch(r"[0-9a-f]{32}", key) is None:
                raise ValueError("invalid border hash")
            if not isinstance(ref, dict):
                raise ValueError("invalid border definition span")
            offset, size = ref.get("offset"), ref.get("nbytes")
            if (type(offset) is not int or type(size) is not int or size <= 0
                    or size % 176 or size > MAX_BORDER_CURVES * 176 or offset < 0
                    or offset > len(payload) or size > len(payload) - offset):
                raise ValueError("invalid border definition span or curve count")
            data = bytes(payload[offset:offset + size])
            values = np.frombuffer(data, dtype="<f4").reshape(-1, 44)
            if (not np.isfinite(values).all() or np.any(values[:, [7, 19, 31, 36]] < 0)
                    or np.any((values[:, 37:39] != 0) & (values[:, 37:39] != 1))
                    or np.any(values[:, 39] != 0)):
                raise ValueError("invalid border coefficients, widths, density or active flags")
            previous = self._border_sources.get(key)
            if previous is not None and previous["data"] != data:
                raise ValueError("border hash redefined with different coefficients")
            definitions[key] = data
        tables = header.get("object_data", {})
        if not isinstance(tables, dict):
            raise ValueError("object table definitions must be an object")
        object_definitions = {}
        for key, ref in tables.items():
            if not isinstance(key, str) or re.fullmatch(r"[0-9a-f]{32}", key) is None:
                raise ValueError("invalid object table hash")
            if not isinstance(ref, dict):
                raise ValueError("invalid object table span")
            offset, size = ref.get("offset"), ref.get("nbytes")
            if (type(offset) is not int or type(size) is not int or size <= 0 or size % OBJECT_BYTES
                    or offset < 0 or offset > len(payload) or size > len(payload) - offset):
                raise ValueError("invalid object table span")
            data = bytes(payload[offset:offset + size])
            previous = self._object_tables.get(key)
            if previous is not None and previous["data"] != data:
                raise ValueError("object table hash redefined with different records")
            object_definitions[key] = data
        used_tables = set()
        limits = getattr(self.device, "limits", {})
        max_buffer = limits.get("max-buffer-size", 256 * 1024 ** 2)
        max_storage = limits.get("max-storage-buffer-binding-size", 128 * 1024 ** 2)
        max_dispatch = limits.get("max-compute-workgroups-per-dimension", 65535)
        alignment = limits.get("min-storage-buffer-offset-alignment", 256)
        outputs, used_sources, used_outputs, completed = {}, set(), set(), []
        uniform_buffers, occurrences = {}, {}
        for batch in header["batches"]:
            if "border" not in batch:
                continue
            border = batch["border"]
            if header.get("format_version", 0) < 5 or not isinstance(border, dict):
                raise ValueError("GPU border requires a format 5 border descriptor")
            key, count = border.get("hash"), border.get("num_curves")
            fill_count, vertex_count = batch.get("fill_num_verts"), batch.get("num_verts")
            index_count, draw_count = batch.get("index_count"), batch.get("count")
            patch = batch.get("pipeline") in ("patch", "patch_depth")
            if (not isinstance(key, str) or re.fullmatch(r"[0-9a-f]{32}", key) is None
                    or type(count) is not int or not 1 <= count <= MAX_BORDER_CURVES
                    or type(fill_count) is not int or fill_count < 0
                    or type(vertex_count) is not int or type(index_count) is not int
                    or type(draw_count) is not int or index_count % 3
                    or batch.get("stride") != 40
                    or type(batch.get("instances")) is not int or batch["instances"] != 1
                    or (not patch and (batch.get("indexed") is not True or batch.get("pipeline")
                                       not in ("surface", "surface_depth", "paint", "paint_depth")))
                    or (patch and (batch.get("indexed") is not False or fill_count or index_count
                                   or header.get("format_version", 0) < 7))):
                raise ValueError("invalid GPU border geometry layout or draw count")
            table_key = None
            try:
                capacity, run_layout = self._border_run(batch)
                if patch:
                    run_layout = validate_patch_layout(run_layout, count)
                    objects = batch.get("objects")
                    if (not isinstance(objects, dict) or objects.get("count") != len(run_layout)
                            or not isinstance(objects.get("hash"), str)
                            or re.fullmatch(r"[0-9a-f]{32}", objects["hash"]) is None):
                        raise ValueError("invalid patch object table reference")
                    table_key = objects["hash"]
                    table = self._object_tables.get(table_key)
                    data = object_definitions.get(table_key) if table is None else table["data"]
                    if data is None:
                        raise KeyError(f"object table cache miss for {table_key}")
                    validate_objects(np.frombuffer(data, dtype="<f4").reshape(-1, OBJECT_WORDS), run_layout)
                elif run_layout is not None:
                    run_layout = validate_layout(run_layout, index_count, fill_count, count)
            except ValueError as error:
                raise ValueError(f"invalid GPU border geometry layout or draw count: {error}")
            if patch:
                valid = draw_count == patch_draw_count(run_layout, capacity)
            elif run_layout is None:
                # Format 5: the complete ordered index buffer is on the wire.
                addressable = vertex_count
                valid = index_count >= INDICES_PER_CURVE * count and draw_count == index_count
            else:
                addressable = fill_count
                valid = draw_count == index_count + indices_per_curve(capacity) * count
            if not valid or vertex_count != fill_count + capacity * count:
                raise ValueError("invalid GPU border geometry layout or draw count")
            size = vertex_count * 40
            # Align the storage view to a whole Surface vertex as well as the
            # device requirement. Only the border tail is bound for compute.
            vertex_alignment = lcm(40, alignment)
            storage_offset = fill_count * 40 // vertex_alignment * vertex_alignment
            storage_size = size - storage_offset
            if size > max_buffer or storage_size > max_storage:
                raise ValueError("GPU border output exceeds device buffer limits")
            source = self._border_sources.get(key)
            data = definitions.get(key) if source is None else source["data"]
            if data is None:
                raise KeyError(f"border cache miss for {key}")
            if len(data) != count * 176 or len(data) > max_storage:
                raise ValueError("border definition curve count does not match geometry")
            if not batch.get("cached") and not patch:
                offset = batch.get("index_offset")
                if (type(offset) is not int or offset < 0 or offset > len(payload)
                        or 4 * index_count > len(payload) - offset):
                    raise ValueError("border indices extend beyond payload")
                vertex_offset = batch.get("offset")
                if (type(vertex_offset) is not int or vertex_offset < 0 or vertex_offset > len(payload)
                        or fill_count * 40 > len(payload) - vertex_offset):
                    raise ValueError("border fill vertices extend beyond payload")
                if not np.isfinite(np.frombuffer(payload[vertex_offset:vertex_offset + fill_count * 40], dtype="<f4")).all():
                    raise ValueError("border fill vertices must be finite")
                indices = np.frombuffer(payload[offset:offset + 4 * index_count], dtype="<u4")
                if np.any(indices >= addressable):
                    raise ValueError("border index exceeds generated vertex count")
            values = {**header["camera"], **batch.get("uniforms", {})}
            packed = pack_uniforms(values)
            floats = np.frombuffer(packed, dtype="<f4")
            factor = float(floats[23]) * (1 - float(floats[38])) + float(floats[38])
            if (not np.isfinite(floats).all() or floats[23] <= 0 or not np.isfinite(factor) or factor < 0
                    or floats[36] not in (0, 1, 2, 3)):
                raise ValueError("invalid GPU border generation uniforms")
            flat = floats[37] != 0 or floats[19] != 0
            state = floats[[23, 38, 36, 37, 19]].tobytes() + (b"" if flat else floats[20:23].tobytes())
            resources = self._generated_resources(batch, payload)
            if source is None:
                source = {"data": data, "buffer": self.device.create_buffer_with_data(
                    data=data, usage=wgpu.BufferUsage.STORAGE)}
                self._border_sources[key] = source
            used_sources.add(key)
            if patch:
                table = self._object_tables.get(table_key)
                if table is None:
                    table_data = object_definitions[table_key]
                    table = {"data": table_data, "buffer": self.device.create_buffer_with_data(
                        data=table_data, usage=wgpu.BufferUsage.STORAGE)}
                    self._object_tables[table_key] = table
                used_tables.add(table_key)
            # Outputs belong to draw occurrences: the same geometry drawn
            # twice with different uniforms needs two. Number occurrences of
            # the same geometry rather than every batch, so inserting an
            # unrelated object earlier in the frame rekeys nothing.
            occurrence = occurrences.get((batch["hash"], key), 0)
            occurrences[(batch["hash"], key)] = occurrence + 1
            output_key = (batch["hash"], key, capacity, occurrence)
            used_outputs.add(output_key)
            output = self._border_outputs.get(output_key)
            if self._border_compute_pipeline is None:
                self._border_compute_pipeline = self.device.create_compute_pipeline(layout="auto",
                    compute={"module": self._modules["border_compute"], "entry_point": "cs_main"})
            pipeline = self._border_compute_pipeline
            if output is None:
                buffer = self.device.create_buffer(size=size,
                    usage=wgpu.BufferUsage.STORAGE | wgpu.BufferUsage.VERTEX | wgpu.BufferUsage.COPY_DST)
                output = {"buffer": buffer, "state": None}
                self._border_outputs[output_key] = output
                output["binding"] = self.device.create_bind_group(layout=pipeline.get_bind_group_layout(1), entries=[
                    {"binding": 0, "resource": {"buffer": source["buffer"], "size": len(data)}},
                    {"binding": 1, "resource": {"buffer": buffer, "offset": storage_offset, "size": storage_size}}])
                if fill_count:
                    encoder.copy_buffer_to_buffer(resources["buffer"], 0, buffer, 0, fill_count * 40)
                if patch:
                    # The patch vertex stage reads the curve records and the
                    # object table; the strips draw this output as vertices.
                    _, group1, _, _, _ = self._patch_bind_layouts()
                    output["patch_binding"] = self.device.create_bind_group(layout=group1, entries=[
                        {"binding": 0, "resource": {"buffer": source["buffer"], "size": len(data)}},
                        {"binding": 1, "resource": {"buffer": table["buffer"], "size": len(table["data"])}}])
            outputs[id(batch)] = output
            if output["state"] == state:
                continue
            camera = uniform_buffers.get(packed)
            if camera is None:
                camera = self.device.create_buffer_with_data(data=packed, usage=wgpu.BufferUsage.UNIFORM)
                uniform_buffers[packed] = camera
                temporary.append(camera)
            compute = encoder.begin_compute_pass()
            compute.set_pipeline(pipeline)
            compute.set_bind_group(1, output["binding"])
            for offset in range(0, count, max_dispatch):
                chunk = min(max_dispatch, count - offset)
                params = self.device.create_buffer_with_data(data=struct.pack("<IIIfIIII", offset, chunk,
                    fill_count - storage_offset // 40 + capacity * offset, .0001, capacity, 0, 0, 0),
                    usage=wgpu.BufferUsage.UNIFORM)
                temporary.append(params)
                group = self.device.create_bind_group(layout=pipeline.get_bind_group_layout(0), entries=[
                    {"binding": 0, "resource": {"buffer": camera, "size": UNIFORM_BYTES}},
                    {"binding": 1, "resource": {"buffer": params, "size": 32}}])
                compute.set_bind_group(0, group)
                compute.dispatch_workgroups(chunk)
            compute.end()
            completed.append((output, state))
        return outputs, used_sources, used_outputs, used_tables, completed

    @staticmethod
    def _validate_paint(data):
        if not 96 <= len(data) <= (24 + 8 * 4096) * 4 or len(data) % 4:
            raise ValueError("invalid paint coefficient length")
        values = np.frombuffer(data, dtype="<f4")
        if not np.isfinite(values).all():
            raise ValueError("paint coefficients must be finite")
        count, mode = float(values[7]), float(values[11])
        if (values[3] <= 0 or not count.is_integer() or not 0 <= count <= 4096
                or len(values) != 24 + 8 * int(count) or mode not in (0, 1)
                or (mode == 1 and count == 0)):
            raise ValueError("invalid paint coefficient layout, scale, node count or mode")
        return data

    def _prepare_paints(self, header, payload):
        """Validate definitions before upload; keep storage independent of layouts."""
        definitions = {}
        records = header.get("paint_data", {})
        if not isinstance(records, dict):
            raise ValueError("paint definitions must be an object")
        for paint_hash, ref in records.items():
            if not isinstance(paint_hash, str) or re.fullmatch(r"[0-9a-f]{32}", paint_hash) is None:
                raise ValueError("invalid paint hash")
            if not isinstance(ref, dict):
                raise ValueError("invalid paint definition span")
            offset, size = ref.get("offset"), ref.get("nbytes")
            if (type(offset) is not int or type(size) is not int
                    or not 0 <= offset <= len(payload) or not 0 <= size <= len(payload) - offset):
                raise ValueError("paint definition extends beyond payload")
            key = ("hash", paint_hash)
            data = self._validate_paint(bytes(payload[offset:offset + size]))
            previous = self._generated_paints.get(key)
            if previous is not None and previous[1] != data:
                raise ValueError("paint hash redefined with different coefficients")
            definitions[key] = data
        keys = {}
        for batch in header["batches"]:
            if batch.get("pipeline") not in ("paint", "paint_depth") and not (
                    batch.get("pipeline") in ("patch", "patch_depth") and "paint_hash" in batch):
                continue
            if "paint_hash" in batch:
                paint_hash = batch["paint_hash"]
                if not isinstance(paint_hash, str) or re.fullmatch(r"[0-9a-f]{32}", paint_hash) is None:
                    raise ValueError("invalid paint hash")
                key = ("hash", paint_hash)
                if key not in self._generated_paints and key not in definitions:
                    raise KeyError(f"paint cache miss for {paint_hash}")
            elif header.get("format_version", 3) < 4 and "paint" in batch:
                inline = batch["paint"]
                if (not isinstance(inline, (list, tuple, np.ndarray))
                        or np.ndim(inline) != 1
                        or any(isinstance(value, (bool, np.bool_))
                               or not isinstance(value, (int, float, np.integer, np.floating))
                               for value in inline)):
                    raise ValueError("inline paint coefficients must be a numeric array")
                with np.errstate(over="ignore", invalid="ignore"):
                    values = np.asarray(inline, dtype="<f4")
                data = self._validate_paint(values.tobytes())
                key = ("inline", data)
                definitions[key] = data
            else:
                raise ValueError("paint operation requires a paint hash")
            keys[id(batch)] = key
        # Only definitions referenced by the frame become resident. Both depth
        # replay and distinct pipelines bind this one immutable storage buffer.
        for key in dict.fromkeys(keys.values()):
            if key not in self._generated_paints:
                data = definitions[key]
                buffer = self.device.create_buffer_with_data(data=data, usage=wgpu.BufferUsage.STORAGE)
                self._generated_paints[key] = (buffer, data)
        return keys

    def _encode_generated(self, encoder, header, vertex_bytes, samples, *, supersample=1, paint_keys, border_outputs,
                          net_outputs=None):
        net_outputs = {} if net_outputs is None else net_outputs
        """Replay all generated operations into exactly one ordered scene pass."""
        background = np.asarray(header["background"], dtype=float).copy()
        background[:3] *= background[3]
        render_pass = self._out_pass(encoder, clear_color=background)
        used_geometry, used_uniforms, used_textures, used_paints = set(), set(), set(), set()
        used_paint_bindings = set()
        coverage_ref = 0
        for batch in header["batches"]:
            if batch["kind"] != "generated":
                raise ValueError("triangle frame contains a non-generated operation")
            name = self._batch_pipeline_name(batch)
            if name not in PIPELINE_SPECS:
                raise ValueError(f"unsupported generated pipeline: {batch['pipeline']}")
            module, layout, _, _, _, depth_test = PIPELINE_SPECS[name]
            expected_stride = (40 if module == "patch_fill"
                               else layout[0]["array_stride"] // (3 if module == "stroke" else 1))
            if batch["stride"] != expected_stride:
                raise ValueError(f"unexpected vertex layout for {batch['pipeline']}")
            if module == "patch_fill":
                if batch.get("coverage"):
                    raise ValueError("a patch fill owns its samples without a coverage reference")
                if coverage_ref:
                    # The count starts from zero; a coverage reference left by
                    # an earlier object would be counted. Start clean.
                    render_pass.end()
                    render_pass = self._out_pass(encoder, clear_stencil=True)
                    coverage_ref = 0
                used_geometry.add(batch["hash"])
                resources = self._generated_resources(batch, vertex_bytes)
                self._encode_patch(render_pass, batch, header, samples, supersample, depth_test,
                                   paint_keys, border_outputs[id(batch)], resources,
                                   used_uniforms, used_paints, used_paint_bindings)
                continue
            coverage = bool(batch.get("coverage"))
            if coverage and module not in ("surface", "paint"):
                raise ValueError("coverage ownership requires surface geometry")
            if coverage:
                if coverage_ref == 255:
                    render_pass.end()
                    render_pass = self._out_pass(encoder, clear_stencil=True)
                    coverage_ref = 0
                coverage_ref += 1
                render_pass.set_stencil_reference(coverage_ref)
            names = [name + "_coverage"] if coverage else [name]
            if coverage and PIPELINE_SPECS[name][-1]:
                names.append(name + "_depth_only")
            resources = self._generated_resources(batch, vertex_bytes)
            used_geometry.add(batch["hash"])
            uniforms = {**header["camera"], **batch["uniforms"], "premultiplied_output": 1.0}
            # Preserve authored widths and AA footprint in final-output pixels.
            # Modify only this packed copy; source/camera metadata stays exact.
            uniforms["pixel_size"] = uniforms.get("pixel_size", 1.0) / supersample
            uniforms["anti_alias_width"] = uniforms.get("anti_alias_width", 1.5) * supersample
            packed = pack_uniforms(uniforms, border_mode=uniforms.get("border_mode", 0.0))
            for operation_name in names:
                pipeline = self._pipeline(operation_name, samples)
                uniform_key = (operation_name, samples, packed)
                used_uniforms.add(uniform_key)
                binding = self._generated_uniforms.get(uniform_key)
                if binding is None:
                    buffer = self.device.create_buffer_with_data(data=packed, usage=wgpu.BufferUsage.UNIFORM)
                    group = self.device.create_bind_group(
                        layout=pipeline.get_bind_group_layout(0),
                        entries=[{"binding": 0, "resource": {"buffer": buffer, "size": UNIFORM_BYTES}}])
                    binding = self._generated_uniforms[uniform_key] = (buffer, group)
                render_pass.set_pipeline(pipeline)
                render_pass.set_bind_group(0, binding[1])
                if module == "paint":
                    paint_key = paint_keys[id(batch)]
                    used_paints.add(paint_key)
                    binding_key = (operation_name, samples, paint_key)
                    used_paint_bindings.add(binding_key)
                    group = self._generated_paint_bindings.get(binding_key)
                    if group is None:
                        buffer, data = self._generated_paints[paint_key]
                        group = self.device.create_bind_group(
                            layout=pipeline.get_bind_group_layout(1),
                            entries=[{"binding": 0, "resource": {"buffer": buffer, "size": len(data)}}])
                        self._generated_paint_bindings[binding_key] = group
                    render_pass.set_bind_group(1, group)
                if batch.get("textures"):
                    texture_key = (operation_name, samples, tuple(batch["textures"].items()))
                    used_textures.add(texture_key)
                    if texture_key not in self._generated_textures:
                        self._generated_textures[texture_key] = self._texture_bind_group(pipeline, batch)
                    render_pass.set_bind_group(1, self._generated_textures[texture_key])
                output = border_outputs.get(id(batch))
                net_output = net_outputs.get(id(batch))
                if net_output is not None:
                    render_pass.set_vertex_buffer(0, net_output["buffer"])
                    render_pass.set_index_buffer(self._net_index_buffer(batch, resources), "uint32")
                    render_pass.draw_indexed(batch["count"], batch["instances"])
                    continue
                render_pass.set_vertex_buffer(0, resources["buffer"] if output is None else output["buffer"])
                if batch.get("indexed"):
                    index_buffer = (resources["index_buffer"] if "index_buffer" in resources
                                    else self._run_index_buffer(batch, resources))
                    render_pass.set_index_buffer(index_buffer, "uint32")
                    render_pass.draw_indexed(batch["count"], batch["instances"])
                else:
                    render_pass.draw(batch["count"], batch["instances"])
        render_pass.end()
        return used_geometry, used_uniforms, used_textures, used_paints, used_paint_bindings

    def _encode_patch(self, render_pass, batch, header, samples, supersample, depth_test,
                      paint_keys, output, resources, used_uniforms, used_paints, used_paint_bindings):
        """Mark, strip mark, cover and strip cover, per group of one patch run:
        consecutive objects sharing a stencil count draw as one instanced
        group, the rest one object each."""
        capacity, layout = self._border_run(batch)
        uniforms = {**header["camera"], **batch["uniforms"], "premultiplied_output": 1.0}
        uniforms["pixel_size"] = uniforms.get("pixel_size", 1.0) / supersample
        uniforms["anti_alias_width"] = uniforms.get("anti_alias_width", 1.5) * supersample
        packed = pack_uniforms(uniforms, border_mode=uniforms.get("border_mode", 0.0))
        group0, _, group2, _, _ = self._patch_bind_layouts()
        uniform_key = ("patch", samples, packed)
        used_uniforms.add(uniform_key)
        binding = self._patch_uniforms.get(uniform_key)
        if binding is None:
            buffer = self.device.create_buffer_with_data(data=packed, usage=wgpu.BufferUsage.UNIFORM)
            group = self.device.create_bind_group(layout=group0, entries=[
                {"binding": 0, "resource": {"buffer": buffer, "size": UNIFORM_BYTES}}])
            binding = self._patch_uniforms[uniform_key] = (buffer, group)
        painted = "paint_hash" in batch
        paint_group = paint_key = None
        if painted:
            paint_key = paint_keys[id(batch)]
            used_paints.add(paint_key)
            binding_key = ("patch", 0, paint_key)
            used_paint_bindings.add(binding_key)
            paint_group = self._generated_paint_bindings.get(binding_key)
            if paint_group is None:
                buffer, data = self._generated_paints[paint_key]
                paint_group = self.device.create_bind_group(layout=group2, entries=[
                    {"binding": 0, "resource": {"buffer": buffer, "size": len(data)}}])
                self._generated_paint_bindings[binding_key] = paint_group
        mark_fan = self._patch_pipeline("mark_fan", depth_test, samples)
        mark_patch = self._patch_pipeline("mark_patch", depth_test, samples)
        cover = self._patch_pipeline("cover_paint" if painted else "cover", depth_test, samples)
        depth_suffix = "_depth" if depth_test else ""
        strips = {}
        if any(bordered for _, bordered, _ in layout):
            # The strips draw through the ordinary pipelines, with their own
            # uniform bindings (and paint binding) like any surface draw.
            for role, name in (("mark", f"generated_surface{depth_suffix}_strip_mark"),
                               ("cover", f"generated_{'paint' if painted else 'surface'}{depth_suffix}_strip_cover")):
                pipeline = self._pipeline(name, samples)
                key = (name, samples, packed)
                used_uniforms.add(key)
                strip_binding = self._generated_uniforms.get(key)
                if strip_binding is None:
                    buffer = self.device.create_buffer_with_data(data=packed, usage=wgpu.BufferUsage.UNIFORM)
                    group = self.device.create_bind_group(
                        layout=pipeline.get_bind_group_layout(0),
                        entries=[{"binding": 0, "resource": {"buffer": buffer, "size": UNIFORM_BYTES}}])
                    strip_binding = self._generated_uniforms[key] = (buffer, group)
                strip_paint = None
                if role == "cover" and painted:
                    binding_key = (name, samples, paint_key)
                    used_paint_bindings.add(binding_key)
                    strip_paint = self._generated_paint_bindings.get(binding_key)
                    if strip_paint is None:
                        buffer, data = self._generated_paints[paint_key]
                        strip_paint = self.device.create_bind_group(
                            layout=pipeline.get_bind_group_layout(1),
                            entries=[{"binding": 0, "resource": {"buffer": buffer, "size": len(data)}}])
                        self._generated_paint_bindings[binding_key] = strip_paint
                strips[role] = (pipeline, strip_binding[1], strip_paint)
            render_pass.set_vertex_buffer(0, output["buffer"])
            render_pass.set_index_buffer(self._patch_index_buffer(batch, resources), "uint32")
        strip_indices = indices_per_curve(capacity)
        for first, count, first_curve, curves, bordered in patch_groups(layout):
            # Every instance draws the group's largest fan; the vertex stage
            # discards the vertices beyond its own object's curves.
            most = max(n for n, _, _ in layout[first:first + count])
            render_pass.set_pipeline(mark_fan)
            render_pass.set_bind_group(0, binding[1])
            render_pass.set_bind_group(1, output["patch_binding"])
            render_pass.draw(3 * most, count, 0, first)
            render_pass.set_pipeline(mark_patch)
            render_pass.draw(3 * most, count, 0, first)
            if bordered:
                pipeline, group, _ = strips["mark"]
                render_pass.set_pipeline(pipeline)
                render_pass.set_bind_group(0, group)
                render_pass.set_stencil_reference(PATCH_STRIP_REFERENCE)
                render_pass.draw_indexed(strip_indices * curves, 1, strip_indices * first_curve)
            render_pass.set_pipeline(cover)
            render_pass.set_bind_group(0, binding[1])
            render_pass.set_bind_group(1, output["patch_binding"])
            if paint_group is not None:
                render_pass.set_bind_group(2, paint_group)
            render_pass.set_stencil_reference(0)
            render_pass.draw(PATCH_VERTICES_PER_CURVE * most, count, 0, first)
            if bordered:
                pipeline, group, strip_paint = strips["cover"]
                render_pass.set_pipeline(pipeline)
                render_pass.set_bind_group(0, group)
                if strip_paint is not None:
                    render_pass.set_bind_group(1, strip_paint)
                render_pass.draw_indexed(strip_indices * curves, 1, strip_indices * first_curve)

    def _retire_generated(self, used, texture_hashes):
        """Retire inactive resources only after their last commands are submitted."""
        used_geometry, used_uniforms, used_textures, used_paints, used_paint_bindings = used
        for key in self._generated_geometry.keys() - used_geometry:
            resources = self._generated_geometry.pop(key)
            resources["buffer"].destroy()
            if "index_buffer" in resources:
                resources["index_buffer"].destroy()
            for index_buffer in resources.get("index_buffers", {}).values():
                index_buffer.destroy()
        for index_buffer in self._stale_index_buffers:
            index_buffer.destroy()
        self._stale_index_buffers = []
        for key in self._generated_uniforms.keys() - used_uniforms:
            self._generated_uniforms.pop(key)[0].destroy()
        for key in self._patch_uniforms.keys() - used_uniforms:
            self._patch_uniforms.pop(key)[0].destroy()
        for key in self._generated_textures.keys() - used_textures:
            del self._generated_textures[key]
        for key in self._generated_paint_bindings.keys() - used_paint_bindings:
            del self._generated_paint_bindings[key]
        for key in self._generated_paints.keys() - used_paints:
            self._generated_paints.pop(key)[0].destroy()
        for key in self.texture_cache.keys() - texture_hashes:
            self.texture_cache.pop(key).destroy()

    def _render_generated(self, header, vertex_bytes):
        samples = header.get("samples", 1)
        if isinstance(samples, bool) or samples not in (1, 4):
            raise ValueError("generated sample count must be 1 or 4")
        supersample = header.get("supersample", 2)
        if isinstance(supersample, bool) or supersample not in (1, 2):
            raise ValueError("generated supersample factor must be 1 or 2")
        size = tuple(header["resolution"])
        self._ensure_targets(tuple(value * supersample for value in size), samples)
        device = self.device
        previous_paints = set(self._generated_paints)
        previous_bindings = set(self._generated_paint_bindings)
        previous_sources, previous_outputs = set(self._border_sources), set(self._border_outputs)
        previous_geometry, previous_uniforms = set(self._generated_geometry), set(self._generated_uniforms)
        previous_tables, previous_patch_uniforms = set(self._object_tables), set(self._patch_uniforms)
        previous_net_sources, previous_net_outputs = set(self._net_sources), set(self._net_outputs)
        temporary = []
        try:
            paint_keys = self._prepare_paints(header, vertex_bytes)
            for tex_hash, ref in header.get("texture_data", {}).items():
                if tex_hash in self.texture_cache:
                    continue
                image = Image.open(io.BytesIO(vertex_bytes[
                    ref["offset"]:ref["offset"] + ref["nbytes"]])).convert("RGBA")
                texture = device.create_texture(
                    size=(*image.size, 1), format="rgba8unorm",
                    usage=wgpu.TextureUsage.TEXTURE_BINDING | wgpu.TextureUsage.COPY_DST)
                device.queue.write_texture(
                    {"texture": texture, "mip_level": 0, "origin": (0, 0, 0)}, image.tobytes(),
                    {"offset": 0, "bytes_per_row": image.size[0] * 4, "rows_per_image": image.size[1]},
                    (*image.size, 1))
                self.texture_cache[tex_hash] = texture
            encoder = device.create_command_encoder()
            borders, used_sources, used_outputs, used_tables, completed = self._prepare_borders(
                header, vertex_bytes, encoder, temporary)
            nets, used_net_sources, used_net_outputs, net_completed = self._prepare_nets(
                header, vertex_bytes, encoder, temporary)
            used = self._encode_generated(encoder, header, vertex_bytes, samples,
                supersample=supersample, paint_keys=paint_keys, border_outputs=borders, net_outputs=nets)
            output = self._resolve_generated(encoder, size, supersample)
            device.queue.submit([encoder.finish()])
            for border_output, state in completed + net_completed:
                border_output["state"] = state
        except Exception:
            # Failed decoding/encoding must preserve the last submitted frame
            # without accumulating materials that never reached the queue.
            for key in self._generated_paint_bindings.keys() - previous_bindings:
                del self._generated_paint_bindings[key]
            for key in self._generated_paints.keys() - previous_paints:
                self._generated_paints.pop(key)[0].destroy()
            for key in self._border_outputs.keys() - previous_outputs:
                self._border_outputs.pop(key)["buffer"].destroy()
            for key in self._border_sources.keys() - previous_sources:
                self._border_sources.pop(key)["buffer"].destroy()
            for key in self._object_tables.keys() - previous_tables:
                self._object_tables.pop(key)["buffer"].destroy()
            for key in self._net_outputs.keys() - previous_net_outputs:
                self._net_outputs.pop(key)["buffer"].destroy()
            for key in self._net_sources.keys() - previous_net_sources:
                self._net_sources.pop(key)["buffer"].destroy()
            for key in self._patch_uniforms.keys() - previous_patch_uniforms:
                self._patch_uniforms.pop(key)[0].destroy()
            for key in self._generated_geometry.keys() - previous_geometry:
                resource = self._generated_geometry.pop(key)
                resource["buffer"].destroy()
                if "index_buffer" in resource:
                    resource["index_buffer"].destroy()
            for key in self._generated_uniforms.keys() - previous_uniforms:
                self._generated_uniforms.pop(key)[0].destroy()
            raise
        finally:
            for buffer in temporary:
                buffer.destroy()
        for key in self._border_outputs.keys() - used_outputs:
            self._border_outputs.pop(key)["buffer"].destroy()
        for key in self._border_sources.keys() - used_sources:
            self._border_sources.pop(key)["buffer"].destroy()
        for key in self._object_tables.keys() - used_tables:
            self._object_tables.pop(key)["buffer"].destroy()
        for key in self._net_outputs.keys() - used_net_outputs:
            self._net_outputs.pop(key)["buffer"].destroy()
        for key in self._net_sources.keys() - used_net_sources:
            self._net_sources.pop(key)["buffer"].destroy()
        self._retire_generated(used, {
            value for batch in header["batches"]
            for value in batch.get("textures", {}).values()})
        raw = device.queue.read_texture(
            {"texture": output, "origin": (0, 0, 0)},
            {"offset": 0, "bytes_per_row": size[0] * 4, "rows_per_image": size[1]}, (*size, 1))
        return Image.frombytes("RGBA", size, bytes(raw))

    def _resolve_generated(self, encoder, output_size, supersample):
        source = self.resolve_texture or self.out_texture
        if supersample == 1:
            if self._spatial_texture is not None:
                self._spatial_texture.destroy()
                self._spatial_texture = self._spatial_binding = None
            return source
        if self._spatial_pipeline is None:
            module = self._modules["resolve2"]
            self._spatial_pipeline = self.device.create_render_pipeline(
                layout="auto", vertex={"module": module, "entry_point": "vs_main"},
                fragment={"module": module, "entry_point": "fs_main",
                          "targets": [{"format": "rgba8unorm"}]},
                primitive={"topology": "triangle-list"})
        if self._spatial_texture is None:
            self._spatial_texture = self.device.create_texture(
                size=(*output_size, 1), format="rgba8unorm",
                usage=wgpu.TextureUsage.RENDER_ATTACHMENT | wgpu.TextureUsage.COPY_SRC)
            self._spatial_binding = self.device.create_bind_group(
                layout=self._spatial_pipeline.get_bind_group_layout(0),
                entries=[{"binding": 0, "resource": source.create_view()}])
        render_pass = encoder.begin_render_pass(color_attachments=[{
            "view": self._spatial_texture.create_view(), "load_op": "clear",
            "store_op": "store", "clear_value": (0, 0, 0, 0)}])
        render_pass.set_pipeline(self._spatial_pipeline)
        render_pass.set_bind_group(0, self._spatial_binding)
        render_pass.draw(3)
        render_pass.end()
        return self._spatial_texture

    def close(self):
        """Release a completed native renderer; future captures create a new one."""
        if self._closed:
            return
        destroyed = set()

        def destroy(resource):
            if resource is not None and id(resource) not in destroyed:
                resource.destroy()
                destroyed.add(id(resource))

        for resources in self._generated_geometry.values():
            destroy(resources["buffer"])
            destroy(resources.get("index_buffer"))
        for buffer, _ in self._generated_uniforms.values():
            destroy(buffer)
        for buffer, _ in self._patch_uniforms.values():
            destroy(buffer)
        for buffer, _ in self._generated_paints.values():
            destroy(buffer)
        for cache in (self._border_outputs, self._border_sources, self._object_tables,
                      self._net_outputs, self._net_sources):
            for resource in cache.values():
                destroy(resource["buffer"])
            cache.clear()
        self._net_compute_pipeline = None
        self._patch_uniforms.clear()
        self._patch_layouts = None
        self._border_compute_pipeline = None
        for texture in self.texture_cache.values():
            destroy(texture)
        for name in ("out_texture", "resolve_texture", "depth_texture", "_spatial_texture"):
            destroy(getattr(self, name, None))
        self._generated_geometry.clear()
        self._generated_uniforms.clear()
        self._generated_textures.clear()
        self._generated_paints.clear()
        self._generated_paint_bindings.clear()
        self.texture_cache.clear()
        self._pipelines.clear()
        self._spatial_binding = self._spatial_pipeline = self._spatial_texture = None
        self.device.destroy()
        self._closed = True

    release = close

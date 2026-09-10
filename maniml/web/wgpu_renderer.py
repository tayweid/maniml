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

import numpy as np
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

MODULE_SOURCES = {
    "stroke": ("common.wgsl", "stroke.wgsl"),
    "surface": ("common.wgsl", "surface.wgsl"),
    "paint": ("common.wgsl", "paint.wgsl"),
    "dot": ("common.wgsl", "dot.wgsl"),
    "image": ("common.wgsl", "image.wgsl"),
    "texsurface": ("common.wgsl", "texsurface.wgsl"),
    "resolve2": ("resolve2.wgsl",),
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
        self._generated_paints = {}
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
        descriptor["fragment"] = {
            "module": self._modules[module_key], "entry_point": "fs_main",
            "targets": [{"format": "rgba8unorm", "blend": blend,
                         "write_mask": 0 if depth_only else wgpu.ColorWrite.ALL}]}
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

    def _generated_resources(self, batch, vertex_bytes):
        layout = (batch["pipeline"], batch["stride"], batch["num_verts"],
                  bool(batch.get("indexed")), batch.get("index_count", 0))
        resources = self._generated_geometry.get(batch["hash"])
        if resources is not None:
            if resources["layout"] != layout:
                raise ValueError("cached generated geometry layout changed")
            return resources
        if batch.get("cached"):
            raise KeyError(f"generated geometry cache miss for batch {batch['hash']}")

        def buffer(offset, size, usage):
            if not 0 <= offset <= len(vertex_bytes) or not 0 <= size <= len(vertex_bytes) - offset:
                raise ValueError("generated geometry buffer extends beyond payload")
            return self.device.create_buffer_with_data(
                data=vertex_bytes[offset:offset + size], usage=usage)

        resources = {"layout": layout, "buffer": buffer(
            batch["offset"], batch["num_verts"] * batch["stride"], wgpu.BufferUsage.VERTEX)}
        if batch.get("indexed"):
            resources["index_buffer"] = buffer(
                batch["index_offset"], batch["index_count"] * 4, wgpu.BufferUsage.INDEX)
        self._generated_geometry[batch["hash"]] = resources
        return resources

    def _encode_generated(self, encoder, header, vertex_bytes, samples, *, supersample=1):
        """Replay all generated operations into exactly one ordered scene pass."""
        background = np.asarray(header["background"], dtype=float).copy()
        background[:3] *= background[3]
        render_pass = self._out_pass(encoder, clear_color=background)
        used_geometry, used_uniforms, used_textures, used_paints = set(), set(), set(), set()
        coverage_ref = 0
        for batch in header["batches"]:
            if batch["kind"] != "generated":
                raise ValueError("triangle frame contains a non-generated operation")
            name = self._batch_pipeline_name(batch)
            if name not in PIPELINE_SPECS:
                raise ValueError(f"unsupported generated pipeline: {batch['pipeline']}")
            module, layout, _, _, _, _ = PIPELINE_SPECS[name]
            expected_stride = layout[0]["array_stride"] // (3 if module == "stroke" else 1)
            if batch["stride"] != expected_stride:
                raise ValueError(f"unexpected vertex layout for {batch['pipeline']}")
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
                    packed_paint = np.asarray(batch["paint"], dtype="f4").tobytes()
                    paint_key = (operation_name, samples, packed_paint)
                    used_paints.add(paint_key)
                    material = self._generated_paints.get(paint_key)
                    if material is None:
                        buffer = self.device.create_buffer_with_data(data=packed_paint, usage=wgpu.BufferUsage.STORAGE)
                        group = self.device.create_bind_group(
                            layout=pipeline.get_bind_group_layout(1),
                            entries=[{"binding": 0, "resource": {"buffer": buffer, "size": len(packed_paint)}}])
                        material = self._generated_paints[paint_key] = (buffer, group)
                    render_pass.set_bind_group(1, material[1])
                if batch.get("textures"):
                    texture_key = (operation_name, samples, tuple(batch["textures"].items()))
                    used_textures.add(texture_key)
                    if texture_key not in self._generated_textures:
                        self._generated_textures[texture_key] = self._texture_bind_group(pipeline, batch)
                    render_pass.set_bind_group(1, self._generated_textures[texture_key])
                render_pass.set_vertex_buffer(0, resources["buffer"])
                if batch.get("indexed"):
                    render_pass.set_index_buffer(resources["index_buffer"], "uint32")
                    render_pass.draw_indexed(batch["count"], batch["instances"])
                else:
                    render_pass.draw(batch["count"], batch["instances"])
        render_pass.end()
        return used_geometry, used_uniforms, used_textures, used_paints

    def _retire_generated(self, used, texture_hashes):
        """Retire inactive resources only after their last commands are submitted."""
        used_geometry, used_uniforms, used_textures, used_paints = used
        for key in self._generated_geometry.keys() - used_geometry:
            resources = self._generated_geometry.pop(key)
            resources["buffer"].destroy()
            if "index_buffer" in resources:
                resources["index_buffer"].destroy()
        for key in self._generated_uniforms.keys() - used_uniforms:
            self._generated_uniforms.pop(key)[0].destroy()
        for key in self._generated_textures.keys() - used_textures:
            del self._generated_textures[key]
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
        used = self._encode_generated(encoder, header, vertex_bytes, samples, supersample=supersample)
        output = self._resolve_generated(encoder, size, supersample)
        device.queue.submit([encoder.finish()])
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
        for buffer, _ in self._generated_paints.values():
            destroy(buffer)
        for texture in self.texture_cache.values():
            destroy(texture)
        for name in ("out_texture", "resolve_texture", "depth_texture", "_spatial_texture"):
            destroy(getattr(self, name, None))
        self._generated_geometry.clear()
        self._generated_uniforms.clear()
        self._generated_textures.clear()
        self._generated_paints.clear()
        self.texture_cache.clear()
        self._pipelines.clear()
        self._spatial_binding = self._spatial_pipeline = self._spatial_texture = None
        self.device.destroy()
        self._closed = True

    release = close

"""WebGPU reference renderer — the future canonical backend.

Consumes the same geometry messages as web/reference_renderer.py (the
desktop-GL mirror of the WebGL2 client) but renders them with wgpu,
compiling the WGSL shaders in web/wgsl/. Once this backend reaches
parity, the same WGSL and the same pass structure run in the browser
via WebGPU, and this module replaces the GL reference renderer — one
renderer everywhere (see the Stage 2 endgame in TODO.md).

Scope: full parity-ledger coverage — winding fill + border + composite,
strokes, triangulated 3D fill with depth test and MSAA, dot clouds,
images, surfaces, textured surfaces, clip planes.

WebGPU-vs-GL differences handled here rather than in shaders:
- blend and depth state are baked per pipeline (a lazy cache keyed on
  (name, sample_count) instead of dynamic GL state);
- uniforms travel in one packed 176-byte buffer (see UNIFORM_FIELDS,
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

WGSL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "wgsl")

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
    ("_pad0", 1, 0.0), ("_pad1", 1, 0.0),
]
UNIFORM_BYTES = sum(n for _, n, _ in UNIFORM_FIELDS) * 4  # 176


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

FILL_LAYOUT = _layout(INSTANCE_STRIDE, _INSTANCE, [
    _attr("float32x3", 0, 0), _attr("float32x3", 68, 1),
    _attr("float32x3", 136, 2),
    _attr("float32x4", 36, 3), _attr("float32x4", 104, 4),
    _attr("float32x4", 172, 5),
    _attr("float32x3", 52, 6), _attr("float32x3", 120, 7),
])
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
BORDER_LAYOUT = _layout(INSTANCE_STRIDE, _INSTANCE, [
    _attr("float32x3", 0, 0), _attr("float32x3", 68, 1),
    _attr("float32x3", 136, 2),
    _attr("float32x4", 36, 3), _attr("float32x4", 104, 4),
    _attr("float32x4", 172, 5),
    _attr("float32", 64, 6), _attr("float32", 132, 7),
    _attr("float32", 200, 8),
    _attr("float32", 32, 9), _attr("float32", 168, 10),
    _attr("float32x3", 120, 11),
])
COMPOSITE_LAYOUT = _layout(8, _VERTEX, [_attr("float32x2", 0, 0)])
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

ALPHA_BLEND = {
    "color": {"src_factor": "src-alpha", "dst_factor": "one-minus-src-alpha",
              "operation": "add"},
    "alpha": {"src_factor": "src-alpha", "dst_factor": "one-minus-src-alpha",
              "operation": "add"},
}
# The winding accumulation: standard color blend, but destination alpha
# accumulates via (1 - dst_a) * src_a + dst_a
FILL_ACCUMULATE_BLEND = {
    "color": {"src_factor": "src-alpha", "dst_factor": "one-minus-src-alpha",
              "operation": "add"},
    "alpha": {"src_factor": "one-minus-dst-alpha", "dst_factor": "one",
              "operation": "add"},
}
MAX_BLEND = {
    "color": {"src_factor": "one", "dst_factor": "one", "operation": "max"},
    "alpha": {"src_factor": "one", "dst_factor": "one", "operation": "max"},
}
COMPOSITE_BLEND = {
    "color": {"src_factor": "one", "dst_factor": "one-minus-src-alpha",
              "operation": "add"},
    "alpha": {"src_factor": "one", "dst_factor": "one-minus-src-alpha",
              "operation": "add"},
}

DEPTH_FORMAT = "depth24plus"

# name -> (module, layout, topology, target, blend, depth_test)
# target "fill" pipelines render into the 2x float winding texture
# (never depth/MSAA); "out" pipelines render into the scene target and
# declare depth state (compare always when depth_test is False).
PIPELINE_SPECS = {
    "fill": ("fill", FILL_LAYOUT, "triangle-list", "fill",
             FILL_ACCUMULATE_BLEND, False),
    "border": ("stroke", BORDER_LAYOUT, "triangle-strip", "fill",
               MAX_BLEND, False),
    "composite": ("composite", COMPOSITE_LAYOUT, "triangle-strip", "out",
                  COMPOSITE_BLEND, False),
    "stroke": ("stroke", STROKE_LAYOUT, "triangle-strip", "out",
               ALPHA_BLEND, False),
    "stroke_depth": ("stroke", STROKE_LAYOUT, "triangle-strip", "out",
                     ALPHA_BLEND, True),
    "surface": ("surface", SURFACE_LAYOUT, "triangle-list", "out",
                ALPHA_BLEND, False),
    "surface_depth": ("surface", SURFACE_LAYOUT, "triangle-list", "out",
                      ALPHA_BLEND, True),
    "dot": ("dot", DOT_LAYOUT, "triangle-strip", "out", ALPHA_BLEND, False),
    "dot_depth": ("dot", DOT_LAYOUT, "triangle-strip", "out",
                  ALPHA_BLEND, True),
    "image": ("image", IMAGE_LAYOUT, "triangle-list", "out",
              ALPHA_BLEND, False),
    "image_depth": ("image", IMAGE_LAYOUT, "triangle-list", "out",
                    ALPHA_BLEND, True),
    "texsurface": ("texsurface", TEXSURFACE_LAYOUT, "triangle-list", "out",
                   ALPHA_BLEND, False),
    "texsurface_depth": ("texsurface", TEXSURFACE_LAYOUT, "triangle-list",
                         "out", ALPHA_BLEND, True),
}

MODULE_SOURCES = {
    "fill": ("common.wgsl", "fill.wgsl"),
    "stroke": ("common.wgsl", "stroke.wgsl"),
    "composite": ("composite.wgsl",),
    "surface": ("common.wgsl", "surface.wgsl"),
    "dot": ("common.wgsl", "dot.wgsl"),
    "image": ("common.wgsl", "image.wgsl"),
    "texsurface": ("common.wgsl", "texsurface.wgsl"),
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
        quad = np.array([[0, 0], [0, 1], [1, 0], [1, 1]], dtype=np.float32)
        self.quad_buffer = self.device.create_buffer_with_data(
            data=quad.tobytes(), usage=wgpu.BufferUsage.VERTEX)
        self.sampler = self.device.create_sampler(
            mag_filter="linear", min_filter="linear",
            address_mode_u="repeat", address_mode_v="repeat")
        self.texture_cache: dict[str, wgpu.GPUTexture] = {}
        # Delta-encoding cache: batch content hash -> GPU buffers. A
        # batch marked "cached" whose hash is absent is a protocol
        # error here (the browser driver requests a reset instead).
        self.batch_cache: dict[str, dict] = {}
        self._size = None

    def _resources(self, batch, builder):
        resources = self.batch_cache.get(batch["hash"])
        if resources is None:
            if batch.get("cached"):
                raise KeyError(
                    f"geometry cache miss for batch {batch['hash']}")
            resources = builder()
            self.batch_cache[batch["hash"]] = resources
        return resources

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
        if target == "fill":
            descriptor["fragment"] = {
                "module": self._modules[module_key], "entry_point": "fs_main",
                "targets": [{"format": "rgba16float", "blend": blend}]}
        else:
            descriptor["fragment"] = {
                "module": self._modules[module_key], "entry_point": "fs_main",
                "targets": [{"format": "rgba8unorm", "blend": blend}]}
            descriptor["depth_stencil"] = {
                "format": DEPTH_FORMAT,
                "depth_write_enabled": depth_test,
                "depth_compare": "less" if depth_test else "always",
            }
            descriptor["multisample"] = {"count": samples}
        pipeline = self.device.create_render_pipeline(**descriptor)
        self._pipelines[key] = pipeline
        return pipeline

    def _ensure_targets(self, size, samples):
        if self._size == (size, samples):
            return
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
                usage=usage | wgpu.TextureUsage.COPY_SRC)
            self.resolve_view = self.resolve_texture.create_view()
        else:
            self.out_texture = device.create_texture(
                size=(*size, 1), format="rgba8unorm",
                usage=usage | wgpu.TextureUsage.COPY_SRC)
        self.out_view = self.out_texture.create_view()
        self.depth_texture = device.create_texture(
            size=(*size, 1), format=DEPTH_FORMAT, sample_count=samples,
            usage=wgpu.TextureUsage.RENDER_ATTACHMENT)
        self.depth_view = self.depth_texture.create_view()
        self.fill_texture = device.create_texture(
            size=(2 * size[0], 2 * size[1], 1), format="rgba16float",
            usage=usage | wgpu.TextureUsage.TEXTURE_BINDING)
        self.fill_view = self.fill_texture.create_view()

    def _out_pass(self, encoder, clear_color=None):
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
            })

    def _uniform_bind_group(self, pipeline, uniforms, border_mode=0.0):
        buffer = self.device.create_buffer_with_data(
            data=pack_uniforms(uniforms, border_mode),
            usage=wgpu.BufferUsage.UNIFORM)
        return self.device.create_bind_group(
            layout=pipeline.get_bind_group_layout(0),
            entries=[{"binding": 0,
                      "resource": {"buffer": buffer, "offset": 0,
                                   "size": UNIFORM_BYTES}}])

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
        base = {"dotcloud": "dot", "image": "image", "surface": "surface",
                "texsurface": "texsurface"}[batch["kind"]]
        return base + ("_depth" if batch.get("depth_test") else "")

    def render(self, header: dict, vertex_bytes: bytes) -> Image.Image:
        size = tuple(header["resolution"])
        samples = 4 if header.get("samples") else 1
        self._ensure_targets(size, samples)
        device = self.device

        for tex_hash, ref in header.get("texture_data", {}).items():
            if tex_hash in self.texture_cache:
                continue
            image = Image.open(io.BytesIO(vertex_bytes[
                ref["offset"]:ref["offset"] + ref["nbytes"]])).convert("RGBA")
            texture = device.create_texture(
                size=(*image.size, 1), format="rgba8unorm",
                usage=wgpu.TextureUsage.TEXTURE_BINDING
                | wgpu.TextureUsage.COPY_DST)
            device.queue.write_texture(
                {"texture": texture, "mip_level": 0, "origin": (0, 0, 0)},
                image.tobytes(),
                {"offset": 0, "bytes_per_row": image.size[0] * 4,
                 "rows_per_image": image.size[1]},
                (*image.size, 1))
            self.texture_cache[tex_hash] = texture

        encoder = device.create_command_encoder()
        self._out_pass(encoder, clear_color=header["background"]).end()

        for batch in header["batches"]:
            if batch["kind"] == "vmobject":
                self._encode_vmobject(encoder, header, batch, vertex_bytes,
                                      samples)
            else:
                self._encode_plain(encoder, header, batch, vertex_bytes,
                                   samples)

        device.queue.submit([encoder.finish()])
        read_texture = self.resolve_texture or self.out_texture
        raw = device.queue.read_texture(
            {"texture": read_texture, "mip_level": 0, "origin": (0, 0, 0)},
            {"offset": 0, "bytes_per_row": size[0] * 4,
             "rows_per_image": size[1]},
            (*size, 1))
        # WebGPU framebuffer rows are top-down already — no flip
        return Image.frombytes("RGBA", size, bytes(raw))

    def _encode_plain(self, encoder, header, batch, vertex_bytes, samples):
        """dotcloud / image / surface / texsurface batches."""
        name = self._batch_pipeline_name(batch)
        pipeline = self._pipeline(name, samples)
        uniforms = {**header["camera"], **batch["uniforms"]}

        def build():
            start = batch["offset"]
            return {"buffer": self.device.create_buffer_with_data(
                data=vertex_bytes[start:start + batch["num_verts"]
                                  * batch["stride"]],
                usage=wgpu.BufferUsage.VERTEX)}

        buffer = self._resources(batch, build)["buffer"]
        render_pass = self._out_pass(encoder)
        render_pass.set_pipeline(pipeline)
        render_pass.set_bind_group(
            0, self._uniform_bind_group(pipeline, uniforms))
        if batch.get("textures"):
            render_pass.set_bind_group(
                1, self._texture_bind_group(pipeline, batch))
        render_pass.set_vertex_buffer(0, buffer)
        if batch["kind"] == "dotcloud":
            render_pass.draw(4, batch["num_verts"])
        else:
            render_pass.draw(batch["num_verts"])
        render_pass.end()

    def _encode_vmobject(self, encoder, header, batch, vertex_bytes, samples):
        device = self.device
        uniforms = {**header["camera"], **batch["uniforms"]}
        instances = batch["num_verts"] // 3
        stroke_verts = batch.get("stroke_verts", 64)
        depth = bool(batch.get("depth_test"))

        def build():
            start = batch["offset"]
            resources = {"buffer": device.create_buffer_with_data(
                data=vertex_bytes[start:start + batch["num_verts"]
                                  * VERTEX_STRIDE],
                usage=wgpu.BufferUsage.VERTEX)}
            tri = batch.get("tri")
            if tri is not None:
                resources["tri_vbo"] = device.create_buffer_with_data(
                    data=vertex_bytes[
                        tri["voffset"]:tri["voffset"] + tri["vcount"] * 40],
                    usage=wgpu.BufferUsage.VERTEX)
                resources["tri_ibo"] = device.create_buffer_with_data(
                    data=vertex_bytes[
                        tri["ioffset"]:tri["ioffset"] + tri["icount"] * 4],
                    usage=wgpu.BufferUsage.INDEX)
                resources["tri_icount"] = tri["icount"]
            return resources

        resources = self._resources(batch, build)
        buffer = resources["buffer"]

        def draw_winding_fill():
            # Pass A: accumulate winding fill + border into fill_texture
            fill_pipeline = self._pipeline("fill", 1)
            border_pipeline = self._pipeline("border", 1)
            fill_pass = encoder.begin_render_pass(color_attachments=[{
                "view": self.fill_view, "load_op": "clear",
                "store_op": "store", "clear_value": (0.0, 0.0, 0.0, 0.0),
            }])
            fill_pass.set_pipeline(fill_pipeline)
            fill_pass.set_bind_group(
                0, self._uniform_bind_group(fill_pipeline, uniforms))
            fill_pass.set_vertex_buffer(0, buffer)
            fill_pass.draw(6, instances)
            fill_pass.set_pipeline(border_pipeline)
            fill_pass.set_bind_group(
                0, self._uniform_bind_group(border_pipeline, uniforms,
                                            border_mode=1.0))
            fill_pass.set_vertex_buffer(0, buffer)
            fill_pass.draw(stroke_verts, instances)
            fill_pass.end()
            # Pass B: composite onto the scene target
            composite_pipeline = self._pipeline("composite", samples)
            out_pass = self._out_pass(encoder)
            out_pass.set_pipeline(composite_pipeline)
            out_pass.set_bind_group(0, self.device.create_bind_group(
                layout=composite_pipeline.get_bind_group_layout(0),
                entries=[
                    {"binding": 0, "resource": self.fill_view},
                    {"binding": 1, "resource": self.sampler},
                ]))
            out_pass.set_vertex_buffer(0, self.quad_buffer)
            out_pass.draw(4)
            out_pass.end()

        def draw_triangulated_fill():
            if "tri_vbo" not in resources:
                return
            # Depth forced on, as in the native path
            pipeline = self._pipeline("surface_depth", samples)
            out_pass = self._out_pass(encoder)
            out_pass.set_pipeline(pipeline)
            out_pass.set_bind_group(
                0, self._uniform_bind_group(pipeline, uniforms))
            out_pass.set_vertex_buffer(0, resources["tri_vbo"])
            out_pass.set_index_buffer(resources["tri_ibo"], "uint32")
            out_pass.draw_indexed(resources["tri_icount"])
            out_pass.end()

        def draw_fill():
            if batch.get("fill_mode") == "triangulated":
                draw_triangulated_fill()
            else:
                draw_winding_fill()

        def draw_stroke():
            pipeline = self._pipeline(
                "stroke_depth" if depth else "stroke", samples)
            out_pass = self._out_pass(encoder)
            out_pass.set_pipeline(pipeline)
            out_pass.set_bind_group(
                0, self._uniform_bind_group(pipeline, uniforms))
            out_pass.set_vertex_buffer(0, buffer)
            out_pass.draw(stroke_verts, instances)
            out_pass.end()

        if batch.get("stroke_behind"):
            draw_stroke()
            draw_fill()
        else:
            draw_fill()
            draw_stroke()

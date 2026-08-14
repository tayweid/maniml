"""WebGPU reference renderer — the future canonical backend.

Consumes the same geometry messages as web/reference_renderer.py (the
desktop-GL mirror of the WebGL2 client) but renders them with wgpu,
compiling the WGSL shaders in web/wgsl/. Once this backend reaches
parity, the same WGSL and the same pass structure run in the browser
via WebGPU, and this module replaces the GL reference renderer — one
renderer everywhere (see the Stage 2 endgame in TODO.md).

Scope so far: the 2D VMobject path (winding fill + border + composite,
stroke), no depth/MSAA/textures yet.

WebGPU-vs-GL differences handled here rather than in shaders:
- blend state is baked per pipeline (fill-accumulate, border-max,
  composite, stroke) instead of set dynamically;
- uniforms travel in one packed 176-byte buffer (see UNIFORM_FIELDS,
  which must match struct Uniforms in wgsl/common.wgsl);
- readback rows come out top-down (no flip, unlike GL).
The clip-space depth-range difference lives in emit_gl_position.
"""

from __future__ import annotations

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


def _instance_layout(attributes):
    return [{
        "array_stride": INSTANCE_STRIDE,
        "step_mode": wgpu.VertexStepMode.instance,
        "attributes": attributes,
    }]


FILL_LAYOUT = _instance_layout([
    _attr("float32x3", 0, 0), _attr("float32x3", 68, 1),
    _attr("float32x3", 136, 2),
    _attr("float32x4", 36, 3), _attr("float32x4", 104, 4),
    _attr("float32x4", 172, 5),
    _attr("float32x3", 52, 6), _attr("float32x3", 120, 7),
])
STROKE_LAYOUT = _instance_layout([
    _attr("float32x3", 0, 0), _attr("float32x3", 68, 1),
    _attr("float32x3", 136, 2),
    _attr("float32x4", 12, 3), _attr("float32x4", 80, 4),
    _attr("float32x4", 148, 5),
    _attr("float32", 28, 6), _attr("float32", 96, 7),
    _attr("float32", 164, 8),
    _attr("float32", 32, 9), _attr("float32", 168, 10),
    _attr("float32x3", 120, 11),
])
BORDER_LAYOUT = _instance_layout([
    _attr("float32x3", 0, 0), _attr("float32x3", 68, 1),
    _attr("float32x3", 136, 2),
    _attr("float32x4", 36, 3), _attr("float32x4", 104, 4),
    _attr("float32x4", 172, 5),
    _attr("float32", 64, 6), _attr("float32", 132, 7),
    _attr("float32", 200, 8),
    _attr("float32", 32, 9), _attr("float32", 168, 10),
    _attr("float32x3", 120, 11),
])
COMPOSITE_LAYOUT = [{
    "array_stride": 8,
    "step_mode": wgpu.VertexStepMode.vertex,
    "attributes": [_attr("float32x2", 0, 0)],
}]

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


def load_wgsl(*names: str) -> str:
    parts = []
    for name in names:
        with open(os.path.join(WGSL_DIR, name)) as f:
            parts.append(f.read())
    return "\n".join(parts)


class WgpuRenderer:
    """Renders parsed geometry messages with WebGPU (2D scope so far)."""

    def __init__(self):
        adapter = wgpu.gpu.request_adapter_sync(
            power_preference="high-performance")
        self.device = adapter.request_device_sync()
        device = self.device

        fill_module = device.create_shader_module(
            code=load_wgsl("common.wgsl", "fill.wgsl"))
        stroke_module = device.create_shader_module(
            code=load_wgsl("common.wgsl", "stroke.wgsl"))
        composite_module = device.create_shader_module(
            code=load_wgsl("composite.wgsl"))

        def pipeline(module, buffers, topology, target_format, blend):
            return device.create_render_pipeline(
                layout="auto",
                vertex={"module": module, "entry_point": "vs_main",
                        "buffers": buffers},
                primitive={"topology": topology},
                fragment={"module": module, "entry_point": "fs_main",
                          "targets": [{"format": target_format,
                                       "blend": blend}]},
            )

        self.fill_pipeline = pipeline(
            fill_module, FILL_LAYOUT, "triangle-list",
            "rgba16float", FILL_ACCUMULATE_BLEND)
        self.border_pipeline = pipeline(
            stroke_module, BORDER_LAYOUT, "triangle-strip",
            "rgba16float", MAX_BLEND)
        self.stroke_pipeline = pipeline(
            stroke_module, STROKE_LAYOUT, "triangle-strip",
            "rgba8unorm", ALPHA_BLEND)
        self.composite_pipeline = pipeline(
            composite_module, COMPOSITE_LAYOUT, "triangle-strip",
            "rgba8unorm", COMPOSITE_BLEND)

        quad = np.array([[0, 0], [0, 1], [1, 0], [1, 1]], dtype=np.float32)
        self.quad_buffer = device.create_buffer_with_data(
            data=quad.tobytes(), usage=wgpu.BufferUsage.VERTEX)
        self.sampler = device.create_sampler(
            mag_filter="linear", min_filter="linear",
            address_mode_u="repeat", address_mode_v="repeat")
        self._size = None

    def _ensure_targets(self, size):
        if self._size == size:
            return
        self._size = size
        device = self.device
        self.out_texture = device.create_texture(
            size=(size[0], size[1], 1), format="rgba8unorm",
            usage=wgpu.TextureUsage.RENDER_ATTACHMENT
            | wgpu.TextureUsage.COPY_SRC)
        self.fill_texture = device.create_texture(
            size=(2 * size[0], 2 * size[1], 1), format="rgba16float",
            usage=wgpu.TextureUsage.RENDER_ATTACHMENT
            | wgpu.TextureUsage.TEXTURE_BINDING)
        self.out_view = self.out_texture.create_view()
        self.fill_view = self.fill_texture.create_view()
        self.composite_bind_group = device.create_bind_group(
            layout=self.composite_pipeline.get_bind_group_layout(0),
            entries=[
                {"binding": 0, "resource": self.fill_view},
                {"binding": 1, "resource": self.sampler},
            ])

    def _uniform_bind_group(self, pipeline, uniforms, border_mode=0.0):
        buffer = self.device.create_buffer_with_data(
            data=pack_uniforms(uniforms, border_mode),
            usage=wgpu.BufferUsage.UNIFORM)
        return self.device.create_bind_group(
            layout=pipeline.get_bind_group_layout(0),
            entries=[{"binding": 0,
                      "resource": {"buffer": buffer, "offset": 0,
                                   "size": UNIFORM_BYTES}}])

    def render(self, header: dict, vertex_bytes: bytes) -> Image.Image:
        size = tuple(header["resolution"])
        self._ensure_targets(size)
        device = self.device
        encoder = device.create_command_encoder()

        # Clear the scene target to the background color
        bg = header["background"]
        render_pass = encoder.begin_render_pass(color_attachments=[{
            "view": self.out_view, "load_op": "clear", "store_op": "store",
            "clear_value": tuple(bg),
        }])
        render_pass.end()

        for batch in header["batches"]:
            if batch["kind"] != "vmobject":
                raise NotImplementedError(
                    f"wgpu backend: batch kind {batch['kind']} not yet ported")
            if batch.get("fill_mode") == "triangulated" or batch.get(
                    "depth_test"):
                raise NotImplementedError(
                    "wgpu backend: 3D path not yet ported")
            self._encode_vmobject(encoder, header, batch, vertex_bytes)

        device.queue.submit([encoder.finish()])
        raw = device.queue.read_texture(
            {"texture": self.out_texture, "mip_level": 0,
             "origin": (0, 0, 0)},
            {"offset": 0, "bytes_per_row": size[0] * 4,
             "rows_per_image": size[1]},
            (size[0], size[1], 1))
        # WebGPU framebuffer rows are top-down already — no flip
        return Image.frombytes("RGBA", size, bytes(raw))

    def _encode_vmobject(self, encoder, header, batch, vertex_bytes):
        device = self.device
        uniforms = {**header["camera"], **batch["uniforms"]}
        instances = batch["num_verts"] // 3
        stroke_verts = batch.get("stroke_verts", 64)
        start = batch["offset"]
        buffer = device.create_buffer_with_data(
            data=vertex_bytes[start:start + batch["num_verts"] * VERTEX_STRIDE],
            usage=wgpu.BufferUsage.VERTEX)

        def draw_fill():
            # Pass A: accumulate winding fill + border into fill_texture
            fill_pass = encoder.begin_render_pass(color_attachments=[{
                "view": self.fill_view, "load_op": "clear",
                "store_op": "store", "clear_value": (0.0, 0.0, 0.0, 0.0),
            }])
            fill_pass.set_pipeline(self.fill_pipeline)
            fill_pass.set_bind_group(
                0, self._uniform_bind_group(self.fill_pipeline, uniforms))
            fill_pass.set_vertex_buffer(0, buffer)
            fill_pass.draw(6, instances)
            fill_pass.set_pipeline(self.border_pipeline)
            fill_pass.set_bind_group(
                0, self._uniform_bind_group(self.border_pipeline, uniforms,
                                            border_mode=1.0))
            fill_pass.set_vertex_buffer(0, buffer)
            fill_pass.draw(stroke_verts, instances)
            fill_pass.end()
            # Pass B: composite onto the scene target
            out_pass = encoder.begin_render_pass(color_attachments=[{
                "view": self.out_view, "load_op": "load",
                "store_op": "store",
            }])
            out_pass.set_pipeline(self.composite_pipeline)
            out_pass.set_bind_group(0, self.composite_bind_group)
            out_pass.set_vertex_buffer(0, self.quad_buffer)
            out_pass.draw(4)
            out_pass.end()

        def draw_stroke():
            out_pass = encoder.begin_render_pass(color_attachments=[{
                "view": self.out_view, "load_op": "load",
                "store_op": "store",
            }])
            out_pass.set_pipeline(self.stroke_pipeline)
            out_pass.set_bind_group(
                0, self._uniform_bind_group(self.stroke_pipeline, uniforms))
            out_pass.set_vertex_buffer(0, buffer)
            out_pass.draw(stroke_verts, instances)
            out_pass.end()

        if batch.get("stroke_behind"):
            draw_stroke()
            draw_fill()
        else:
            draw_fill()
            draw_stroke()

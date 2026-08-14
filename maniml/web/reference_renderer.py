"""Reference implementation of the Stage-2 client renderer, in Python.

Renders a geometry message (web/geometry.py) with moderngl on a
standalone desktop-GL context, using the SAME shader sources the
browser client compiles for WebGL2 (web/static/glsl/*, written in the
common GLSL 330 / 300 es subset; only the #version prelude differs).

Purpose: pixel-diff the ported instanced pipeline against the native
geometry-shader pipeline in plain unittest, with no browser involved
(tests/test_gl_port.py) — and serve as the executable spec for the JS
client, which must mirror this file's buffer layouts and pass sequence.

Instanced attribute layouts (stride 204 = 3 x 68-byte vertex structs;
one instance per bezier triple; byte offsets per the vertex formats in
rendering/shader_wrapper.py:293-303):

  fill:   p0@0  c0@36   base_point@52  p1@68  c1@104  unit_normal@120
          p2@136 c2@172
  stroke: p0@0  rgba0@12  width0@28  ja0@32   p1@68  rgba1@80
          width1@96  unit_normal1@120  p2@136  rgba2@148  width2@164
          ja2@168
  border: same as stroke but rgba* from fill_rgba (@36/@104/@172) and
          width* from fill_border_width (@64/@132/@200)
"""

from __future__ import annotations

import os

import moderngl
import numpy as np
from PIL import Image

GLSL_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "static", "glsl")

VERTEX_STRIDE = 68  # bytes; one interleaved VMobject vertex struct

FILL_FORMAT = "3f 24x 4f 3f 4x 3f 24x 4f 3f 4x 3f 24x 4f 16x/i"
FILL_ATTRS = ["p0", "c0", "base_point", "p1", "c1", "unit_normal",
              "p2", "c2"]
STROKE_FORMAT = "3f 4f 1f 1f 32x 3f 4f 1f 20x 3f 4x 3f 4f 1f 1f 32x/i"
STROKE_ATTRS = ["p0", "rgba0", "width0", "ja0", "p1", "rgba1", "width1",
                "unit_normal1", "p2", "rgba2", "width2", "ja2"]
BORDER_FORMAT = "3f 20x 1f 4f 12x 1f 3f 24x 4f 3f 4x 3f 20x 1f 4f 12x 1f/i"
BORDER_ATTRS = ["p0", "ja0", "rgba0", "width0", "p1", "rgba1",
                "unit_normal1", "p2", "ja2", "rgba2", "width2"]

DOT_FORMAT = "3f 1f 4f/i"
DOT_ATTRS = ["dot_point", "dot_radius", "dot_rgba"]

# Uniform names each program understands (camera + mobject, merged)
_UNIFORM_KEYS = [
    "view", "frame_rescale_factors", "frame_scale", "pixel_size",
    "camera_position", "light_position", "shading", "is_fixed_in_frame",
    "anti_alias_width", "joint_type", "flat_stroke",
    "scale_stroke_with_zoom", "glow_factor",
]


def load_source(*names: str, version: str = "#version 330") -> str:
    parts = [version]
    for name in names:
        with open(os.path.join(GLSL_DIR, name)) as f:
            parts.append(f.read())
    return "\n".join(parts)


def _set_uniforms(program, values: dict):
    for key in _UNIFORM_KEYS:
        if key in values and key in program:
            value = values[key]
            program[key].value = (
                tuple(value) if isinstance(value, (list, tuple)) else value)


class ReferenceRenderer:
    """Renders parsed geometry messages; one instance per resolution."""

    def __init__(self, ctx: moderngl.Context | None = None):
        self.ctx = ctx or moderngl.create_standalone_context()
        self.ctx.enable(moderngl.BLEND)
        self.fill_program = self.ctx.program(
            vertex_shader=load_source("common.glsl", "vfill.vert"),
            fragment_shader=load_source("vfill.frag"),
        )
        self.stroke_program = self.ctx.program(
            vertex_shader=load_source("common.glsl", "vstroke.vert"),
            fragment_shader=load_source("vstroke.frag"),
        )
        self.composite_program = self.ctx.program(
            vertex_shader=load_source("composite.vert"),
            fragment_shader=load_source("composite.frag"),
        )
        self.surface_program = self.ctx.program(
            vertex_shader=load_source("common.glsl", "vsurface.vert"),
            fragment_shader=load_source("vsurface.frag"),
        )
        self.dot_program = self.ctx.program(
            vertex_shader=load_source("common.glsl", "vdot.vert"),
            fragment_shader=load_source("common.glsl", "vdot.frag"),
        )
        quad = np.array([[0, 0], [0, 1], [1, 0], [1, 1]], dtype="f4")
        self.composite_vao = self.ctx.simple_vertex_array(
            self.composite_program, self.ctx.buffer(quad.tobytes()),
            "texcoord", mode=moderngl.TRIANGLE_STRIP)
        self._size = None
        # Delta-encoding cache: batch content hash -> GPU resources.
        # A batch marked "cached" whose hash is absent is a protocol
        # error here (the JS client requests a reset instead).
        self.batch_cache: dict[str, dict] = {}

    def _resources(self, batch, builder):
        resources = self.batch_cache.get(batch["hash"])
        if resources is None:
            if batch.get("cached"):
                raise KeyError(
                    f"geometry cache miss for batch {batch['hash']}")
            resources = builder()
            self.batch_cache[batch["hash"]] = resources
        return resources

    def _ensure_targets(self, size, samples):
        if self._size == (size, samples):
            return
        self._size = (size, samples)
        double = (2 * size[0], 2 * size[1])
        # Float texture so winding-trick alphas can go negative unclipped
        self.fill_texture = self.ctx.texture(double, components=4, dtype="f2")
        self.fill_fbo = self.ctx.framebuffer(self.fill_texture)
        # Depth attachment always present (2D batches simply don't test);
        # multisampled when the native camera is (ThreeDCamera: samples=4)
        self.out_fbo = self.ctx.framebuffer(
            self.ctx.renderbuffer(size, components=4, samples=samples),
            self.ctx.depth_renderbuffer(size, samples=samples))
        self.resolve_fbo = (
            self.ctx.framebuffer(self.ctx.renderbuffer(size, components=4))
            if samples else None)

    def render(self, header: dict, vertex_bytes: bytes) -> Image.Image:
        size = tuple(header["resolution"])
        self._ensure_targets(size, int(header.get("samples", 0)))
        self.out_fbo.use()
        self.out_fbo.clear(*header["background"], depth=1.0)

        for batch in header["batches"]:
            if batch["kind"] == "vmobject":
                self._render_vmobject(header, batch, vertex_bytes)
            elif batch["kind"] == "dotcloud":
                self._render_dotcloud(header, batch, vertex_bytes)
        self.ctx.disable(moderngl.DEPTH_TEST)

        read_fbo = self.out_fbo
        if self.resolve_fbo is not None:
            self.ctx.copy_framebuffer(self.resolve_fbo, self.out_fbo)
            read_fbo = self.resolve_fbo
        raw = read_fbo.read(components=4)
        image = Image.frombytes("RGBA", size, raw)
        return image.transpose(Image.FLIP_TOP_BOTTOM)

    def _render_dotcloud(self, header, batch, vertex_bytes):
        ctx = self.ctx

        def build():
            start = batch["offset"]
            buffer = ctx.buffer(
                vertex_bytes[start:start + batch["num_verts"] * 32])
            vao = ctx.vertex_array(
                self.dot_program, [(buffer, DOT_FORMAT, *DOT_ATTRS)])
            return {"buffer": buffer, "vao": vao}

        resources = self._resources(batch, build)
        _set_uniforms(self.dot_program,
                      {**header["camera"], **batch["uniforms"]})
        self.out_fbo.use()
        ctx.blend_func = moderngl.DEFAULT_BLENDING
        ctx.blend_equation = moderngl.FUNC_ADD
        if batch.get("depth_test"):
            ctx.enable(moderngl.DEPTH_TEST)
        else:
            ctx.disable(moderngl.DEPTH_TEST)
        resources["vao"].render(moderngl.TRIANGLE_STRIP, vertices=4,
                                instances=batch["num_verts"])

    def _render_vmobject(self, header, batch, vertex_bytes):
        ctx = self.ctx
        instances = batch["num_verts"] // 3
        # The batch's tightest strip; the shader clamps per curve anyway
        stroke_verts = batch.get("stroke_verts", 64)

        uniforms = {**header["camera"], **batch["uniforms"]}
        _set_uniforms(self.fill_program, uniforms)
        _set_uniforms(self.stroke_program, uniforms)

        def build():
            start = batch["offset"]
            nbytes = batch["num_verts"] * VERTEX_STRIDE
            buffer = ctx.buffer(vertex_bytes[start:start + nbytes])
            resources = {
                "buffer": buffer,
                "fill_vao": ctx.vertex_array(
                    self.fill_program, [(buffer, FILL_FORMAT, *FILL_ATTRS)]),
                "stroke_vao": ctx.vertex_array(
                    self.stroke_program,
                    [(buffer, STROKE_FORMAT, *STROKE_ATTRS)]),
                "border_vao": ctx.vertex_array(
                    self.stroke_program,
                    [(buffer, BORDER_FORMAT, *BORDER_ATTRS)]),
                "tri_vao": None,
            }
            tri = batch.get("tri")
            if tri is not None:
                vbo = ctx.buffer(vertex_bytes[
                    tri["voffset"]:tri["voffset"] + tri["vcount"] * 40])
                ibo = ctx.buffer(vertex_bytes[
                    tri["ioffset"]:tri["ioffset"] + tri["icount"] * 4])
                resources["tri_vbo"] = vbo
                resources["tri_ibo"] = ibo
                resources["tri_vao"] = ctx.vertex_array(
                    self.surface_program,
                    [(vbo, "3f 3f 4f", "point", "d_normal_point", "rgba")],
                    index_buffer=ibo, index_element_size=4)
            return resources

        resources = self._resources(batch, build)

        def draw_triangulated_fill():
            # Port of render_triangulated_fill: real triangles with real
            # z, depth test forced on (as in the native path)
            if resources["tri_vao"] is None:
                return
            _set_uniforms(self.surface_program, uniforms)
            self.out_fbo.use()
            ctx.blend_func = moderngl.DEFAULT_BLENDING
            ctx.blend_equation = moderngl.FUNC_ADD
            ctx.enable(moderngl.DEPTH_TEST)
            resources["tri_vao"].render(moderngl.TRIANGLES)

        def draw_fill():
            if batch.get("fill_mode") == "triangulated":
                draw_triangulated_fill()
                return
            # Pass sequence from VShaderWrapper.render_fill (2D branch);
            # the winding passes never depth-test
            ctx.disable(moderngl.DEPTH_TEST)
            self.fill_fbo.use()
            self.fill_fbo.clear(0.0, 0.0, 0.0, 0.0)
            ctx.blend_func = (
                moderngl.SRC_ALPHA, moderngl.ONE_MINUS_SRC_ALPHA,
                moderngl.ONE_MINUS_DST_ALPHA, moderngl.ONE)
            resources["fill_vao"].render(moderngl.TRIANGLES, vertices=6,
                                         instances=instances)
            # Fill border (stroke program over fill color/border width)
            ctx.blend_func = (moderngl.ONE, moderngl.ONE)
            ctx.blend_equation = moderngl.MAX
            self.stroke_program["border_mode"].value = 1.0
            resources["border_vao"].render(
                moderngl.TRIANGLE_STRIP, vertices=stroke_verts,
                instances=instances)
            # Composite onto the output frame
            self.out_fbo.use()
            ctx.blend_func = (moderngl.ONE, moderngl.ONE_MINUS_SRC_ALPHA)
            ctx.blend_equation = moderngl.FUNC_ADD
            self.fill_texture.use(0)
            self.composite_vao.render()
            ctx.blend_func = moderngl.DEFAULT_BLENDING

        def draw_stroke():
            self.out_fbo.use()
            ctx.blend_func = moderngl.DEFAULT_BLENDING
            ctx.blend_equation = moderngl.FUNC_ADD
            if batch.get("depth_test"):
                ctx.enable(moderngl.DEPTH_TEST)
            else:
                ctx.disable(moderngl.DEPTH_TEST)
            self.stroke_program["border_mode"].value = 0.0
            resources["stroke_vao"].render(
                moderngl.TRIANGLE_STRIP, vertices=stroke_verts,
                instances=instances)

        if batch["stroke_behind"]:
            draw_stroke()
            draw_fill()
        else:
            draw_fill()
            draw_stroke()

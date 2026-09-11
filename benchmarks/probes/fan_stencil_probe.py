"""Standalone probe of the B1-fan mechanism (docs/phase_b1_plan.md), 2026-09-11.

Run from anywhere with the project interpreter; needs wgpu and a GPU. Writes
probe_<case>_<sample_rate>.png beside the working directory and prints the
coverage probes and the circle-edge error against analytic coverage.

Draws quadratic-curve fills as fan + patch triangles into the stencil with
increment/decrement wrap (7-bit count, mask 0x7F), sets a border bit with
replace 0x80, then covers with compare != 0 and pass_op zero. Checks the
fixture corpus's coverage probes and measures curved-edge AA levels with and
without sample-rate shading on the is_patch test.
"""
import sys
import numpy as np
import wgpu

W, H = 384, 216
SAMPLES = 4

WGSL = """
struct U { scale: vec2f, sample_rate: f32, pad: f32 }
@group(0) @binding(0) var<uniform> u: U;
@group(0) @binding(1) var<storage, read> curves: array<f32>;   // 9 floats per curve: p0 p1 p2 (xy z unused)
@group(0) @binding(2) var<storage, read> objects: array<vec4f>; // base point xy per object, curve range

struct VOut {
  @builtin(position) pos: vec4f,
  @location(0) @interpolate(perspective, SAMPLE_OR_CENTER) uv: vec2f,
  @location(1) @interpolate(flat) is_patch: u32,
}

@vertex fn vs_main(@builtin(vertex_index) vid: u32) -> VOut {
  let curve = vid / 6u;
  let corner = vid % 6u;
  let src = 9u * curve;
  let p0 = vec2f(curves[src], curves[src + 1u]);
  let p1 = vec2f(curves[src + 3u], curves[src + 4u]);
  let p2 = vec2f(curves[src + 6u], curves[src + 7u]);
  let base = vec2f(curves[src + 2u], curves[src + 5u]);  // base point smuggled in z slots
  var out: VOut;
  var p: vec2f;
  if (corner < 3u) {
    // fan triangle base, p0, p2
    if (corner == 0u) { p = base; } else if (corner == 1u) { p = p0; } else { p = p2; }
    out.uv = vec2f(0.0, 1.0);  // always inside
    out.is_patch = 0u;
  } else {
    let c = corner - 3u;
    if (c == 0u) { p = p0; out.uv = vec2f(0.0, 0.0); }
    else if (c == 1u) { p = p1; out.uv = vec2f(0.5, 0.0); }
    else { p = p2; out.uv = vec2f(1.0, 1.0); }
    out.is_patch = 1u;
  }
  out.pos = vec4f(p * u.scale, 0.0, 1.0);
  return out;
}

@fragment fn fs_mark(v: VOut) {
  if (v.is_patch == 1u && v.uv.y - v.uv.x * v.uv.x < 0.0) { discard; }
}

@fragment fn fs_cover(v: VOut) -> @location(0) vec4f {
  if (v.is_patch == 1u && v.uv.y - v.uv.x * v.uv.x < 0.0) { discard; }
  return vec4f(1.0, 1.0, 1.0, 1.0);
}
"""


def curves_of(contours, base):
    """contours: list of point lists (anchors as straight lines) -> 9 floats/curve."""
    out = []
    for pts in contours:
        pts = [np.asarray(p, float) for p in pts]
        n = len(pts)
        for i in range(n):
            a, b = pts[i], pts[(i + 1) % n]
            out.append([a[0], a[1], base[0], (a[0] + b[0]) / 2, (a[1] + b[1]) / 2, base[1], b[0], b[1], 0.0])
    return np.asarray(out, np.float32)


def circle_curves(cx, cy, r, base, reverse=False, n=16):
    """A 16-curve quadratic circle, like Arc's, anchor-handle-anchor."""
    out = []
    angles = np.linspace(0, 2 * np.pi, n + 1)
    if reverse:
        angles = angles[::-1]
    for i in range(n):
        a0, a1 = angles[i], angles[i + 1]
        p0 = np.array([np.cos(a0), np.sin(a0)]) * r
        p2 = np.array([np.cos(a1), np.sin(a1)]) * r
        mid = (a0 + a1) / 2
        # handle so that the curve passes through the arc midpoint
        h = np.array([np.cos(mid), np.sin(mid)]) * r / np.cos((a1 - a0) / 2)
        h = 2 * (np.array([np.cos(mid), np.sin(mid)]) * r) - (p0 + p2) / 2  # exact quadratic midpoint
        out.append([p0[0] + cx, p0[1] + cy, base[0], h[0] + cx, h[1] + cy, base[1], p2[0] + cx, p2[1] + cy, 0.0])
    return np.asarray(out, np.float32)


class Probe:
    def __init__(self, sample_rate):
        adapter = wgpu.gpu.request_adapter_sync(power_preference="high-performance")
        self.device = adapter.request_device_sync()
        code = WGSL.replace("SAMPLE_OR_CENTER", "sample" if sample_rate else "center")
        module = self.device.create_shader_module(code=code)
        self.uniform = self.device.create_buffer_with_data(
            data=np.array([1 / 7.1111, 1 / 4.0, float(sample_rate), 0], np.float32).tobytes(),
            usage=wgpu.BufferUsage.UNIFORM)
        self.objects = self.device.create_buffer(size=16, usage=wgpu.BufferUsage.STORAGE)
        ds = lambda front, back, rmask, wmask, cmp="always": {
            "format": "depth24plus-stencil8", "depth_write_enabled": False, "depth_compare": "always",
            "stencil_front": {"compare": cmp, "fail_op": "keep", "depth_fail_op": "keep", "pass_op": front},
            "stencil_back": {"compare": cmp, "fail_op": "keep", "depth_fail_op": "keep", "pass_op": back},
            "stencil_read_mask": rmask, "stencil_write_mask": wmask}
        bgl = self.device.create_bind_group_layout(entries=[
            {"binding": 0, "visibility": wgpu.ShaderStage.VERTEX | wgpu.ShaderStage.FRAGMENT,
             "buffer": {"type": "uniform"}},
            {"binding": 1, "visibility": wgpu.ShaderStage.VERTEX, "buffer": {"type": "read-only-storage"}}])
        self.bgl = bgl
        pl = self.device.create_pipeline_layout(bind_group_layouts=[bgl])
        common = dict(layout=pl, vertex={"module": module, "entry_point": "vs_main", "buffers": []},
                      primitive={"topology": "triangle-list"}, multisample={"count": SAMPLES})
        self.mark = self.device.create_render_pipeline(
            **common, fragment={"module": module, "entry_point": "fs_mark", "targets": [
                {"format": "rgba8unorm", "write_mask": 0}]},
            depth_stencil=ds("increment-wrap", "decrement-wrap", 0xFF, 0x7F))
        self.border = self.device.create_render_pipeline(
            **common, fragment={"module": module, "entry_point": "fs_mark", "targets": [
                {"format": "rgba8unorm", "write_mask": 0}]},
            depth_stencil=ds("replace", "replace", 0xFF, 0x80))
        self.cover = self.device.create_render_pipeline(
            **common, fragment={"module": module, "entry_point": "fs_cover", "targets": [{"format": "rgba8unorm"}]},
            depth_stencil=ds("zero", "zero", 0xFF, 0xFF, cmp="not-equal"))
        self.color = self.device.create_texture(size=(W, H, 1), format="rgba8unorm", sample_count=SAMPLES,
                                                usage=wgpu.TextureUsage.RENDER_ATTACHMENT)
        self.resolve = self.device.create_texture(size=(W, H, 1), format="rgba8unorm",
                                                  usage=wgpu.TextureUsage.RENDER_ATTACHMENT | wgpu.TextureUsage.COPY_SRC)
        self.depth = self.device.create_texture(size=(W, H, 1), format="depth24plus-stencil8", sample_count=SAMPLES,
                                                usage=wgpu.TextureUsage.RENDER_ATTACHMENT)

    def render(self, objects):
        """objects: list of (curves array, border curves array or None)."""
        enc = self.device.create_command_encoder()
        rp = enc.begin_render_pass(
            color_attachments=[{"view": self.color.create_view(), "resolve_target": self.resolve.create_view(),
                                "load_op": "clear", "store_op": "store", "clear_value": (0, 0, 0, 1)}],
            depth_stencil_attachment={"view": self.depth.create_view(), "depth_load_op": "clear",
                                      "depth_store_op": "store", "depth_clear_value": 1.0,
                                      "stencil_load_op": "clear", "stencil_store_op": "store", "stencil_clear_value": 0})
        keep = []
        for curves, border in objects:
            buf = self.device.create_buffer_with_data(data=curves.tobytes(), usage=wgpu.BufferUsage.STORAGE)
            keep.append(buf)
            group = self.device.create_bind_group(layout=self.bgl, entries=[
                {"binding": 0, "resource": {"buffer": self.uniform, "size": 16}},
                {"binding": 1, "resource": {"buffer": buf, "size": curves.nbytes}}])
            rp.set_pipeline(self.mark); rp.set_bind_group(0, group); rp.draw(6 * len(curves))
            if border is not None:
                bbuf = self.device.create_buffer_with_data(data=border.tobytes(), usage=wgpu.BufferUsage.STORAGE)
                keep.append(bbuf)
                bgroup = self.device.create_bind_group(layout=self.bgl, entries=[
                    {"binding": 0, "resource": {"buffer": self.uniform, "size": 16}},
                    {"binding": 1, "resource": {"buffer": bbuf, "size": border.nbytes}}])
                rp.set_pipeline(self.border); rp.set_stencil_reference(0x80); rp.set_bind_group(0, bgroup); rp.draw(6 * len(border))
            rp.set_pipeline(self.cover); rp.set_stencil_reference(0); rp.set_bind_group(0, group); rp.draw(6 * len(curves))
            if border is not None:
                rp.set_bind_group(0, bgroup); rp.draw(6 * len(border))
        rp.end()
        self.device.queue.submit([enc.finish()])
        raw = self.device.queue.read_texture({"texture": self.resolve, "origin": (0, 0, 0)},
                                             {"offset": 0, "bytes_per_row": W * 4, "rows_per_image": H}, (W, H, 1))
        return np.frombuffer(raw, np.uint8).reshape(H, W, 4)[..., 0].astype(int)


def px(x, y):
    return int((y / 4.0 * -1 + 1) / 2 * H), int((x / 7.1111 + 1) / 2 * W)


def check(name, image, probes):
    ok = True
    for (x, y), covered in probes:
        r, c = px(x, y)
        value = image[r, c]
        good = (value > 200) == covered
        ok &= good
        print(f"  {name:20s} probe ({x:5.2f},{y:5.2f}) expect {'in ' if covered else 'out'} got {value:3d} {'ok' if good else 'FAIL'}")
    return ok


def main():
    base = (0.0, 0.0)
    cases = {
        "annulus_hole": ([circle_curves(0, 0, 1.2, base), circle_curves(0, 0, 0.55, base, reverse=True)],
                         [((0, 0), False), ((0.9, 0), True), ((1.5, 0), False)]),
        "nested_contours": ([curves_of([[(-2, -2), (2, -2), (2, 2), (-2, 2)]], base),
                             curves_of([[(-1.2, -1.2), (-1.2, 1.2), (1.2, 1.2), (1.2, -1.2)]], base),
                             curves_of([[(-0.45, -0.45), (0.45, -0.45), (0.45, 0.45), (-0.45, 0.45)]], base)],
                            [((0, 0), True), ((0.8, 0), False), ((1.6, 0), True), ((2.4, 0), False)]),
        "quad_concave": ([curves_of([[(-2, -2), (-1, 1), (2, 2), (-2, 2)]], (-2, 2))],
                         [((-1.5, 1.5), True), ((2.5, 0), False), ((-1 / 3, 1 / 3), False)]),
        "quad_convex": ([curves_of([[(-2, -2), (2, -2), (2, 2), (-2, 2)]], (-2, 2))],
                        [((-1.5, 1.5), True), ((2.5, 0), False), ((-1 / 3, 1 / 3), True)]),
        "repeated_winding": ([curves_of([[(-1, -1), (1, -1), (1, 1), (-1, 1)] * 2], base)],
                             [((0, 0), True), ((1.5, 0), False)]),
        "reversed_winding": ([curves_of([[(-1, 1), (1, 1), (1, -1), (-1, -1)]], base)],
                             [((0, 0), True), ((1.5, 0), False)]),
        "winding_127": ([curves_of([[(-1, -1), (1, -1), (1, 1), (-1, 1)] * 127], base)],
                        [((0, 0), True), ((1.5, 0), False)]),
        "winding_128_wraps": ([curves_of([[(-1, -1), (1, -1), (1, 1), (-1, 1)] * 128], base)],
                              [((0, 0), False), ((1.5, 0), False)]),
    }
    all_ok = True
    for sample_rate in (False, True):
        probe = Probe(sample_rate)
        print(f"sample_rate={sample_rate}")
        for name, (contours, probes) in cases.items():
            curves = np.concatenate(contours)
            image = probe.render([(curves, None)])
            from PIL import Image; Image.fromarray(image.astype(np.uint8)).save(f'probe_{name}_{int(sample_rate)}.png')
            all_ok &= check(name, image, probes)
        # Border bit: a strip (as a fan-less patchless quad) beside the circle,
        # marked with replace 0x80, must paint once even when it overlaps itself.
        circle = circle_curves(0, 0, 1.0, base)
        ring = curves_of([[(1.0, -0.2), (1.4, -0.2), (1.4, 0.2), (1.0, 0.2)]], (1.2, 0))
        ring2 = curves_of([[(1.2, -0.2), (1.6, -0.2), (1.6, 0.2), (1.2, 0.2)]], (1.4, 0))  # overlapping, reversed? same orientation
        image = probe.render([(circle, np.concatenate([ring, ring2]))])
        all_ok &= check("border_bit", image, [((0.5, 0), True), ((1.1, 0), True), ((1.3, 0), True), ((1.5, 0), True), ((1.8, 0), False)])
        # Two objects in sequence: second must not see first's leftovers.
        image = probe.render([(circle_curves(0, 0, 1.2, base), None), (circle_curves(0.5, 0, 0.6, (0.5, 0)), None)])
        all_ok &= check("sequence", image, [((-0.5, 0), True), ((0.5, 0), True), ((1.3, 0), False)])
        # AA levels along the circle's edge: count distinct intermediate values.
        image = probe.render([(circle_curves(0, 0, 1.2, base), None)])
        edge = image[(image > 0) & (image < 255)]
        # analytic coverage of the circle, 16x16 subsamples per pixel
        n = 16
        sub = (np.arange(n) + 0.5) / n
        cols = (np.arange(W)[:, None] + sub[None, :]).reshape(-1)
        rows = (np.arange(H)[:, None] + sub[None, :]).reshape(-1)
        xs = (cols / W * 2 - 1) * 7.1111
        ys = (1 - rows / H * 2) * 4.0
        inside = (xs[None, :] ** 2 + ys[:, None] ** 2) <= 1.2 ** 2
        exact = inside.reshape(H, n, W, n).mean(axis=(1, 3)) * 255
        err = np.abs(image - exact)
        print(f"  circle vs analytic (16-curve quadratic, r=1.2): {len(edge)} partial pixels; "
              f"max err {err.max():.0f}/255, pixels off by >24: {(err > 24).sum()}, mean err on edge pixels {err[exact % 255 != 0].mean():.1f}")
    print("ALL OK" if all_ok else "FAILURES")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())

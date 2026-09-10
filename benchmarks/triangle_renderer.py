"""Opt-in A0 triangle rendering and comparison; never selected by the viewer.

Run with the pinned Lyon helper and the optional locked WebGPU dependencies:
    MANIML_LYON_LIBRARY=/path/to/helper python -m benchmarks.triangle_renderer \
        --output /tmp/triangle-a0 --samples 5

Diagnostic images deliberately expose incomplete paint/border behavior. The
report records those gaps; a completed benchmark is not a compatibility pass.
"""

import argparse
from datetime import datetime, timezone
from hashlib import blake2b, sha256
import json
from pathlib import Path
import platform
from statistics import median
from time import perf_counter
import tomllib

import numpy as np
from PIL import Image, __version__ as pillow_version
import wgpu
from wgpu.backends import wgpu_native

from benchmarks.triangle_scene import prepare_triangle_frame
from tests.winding_reference_geometry import parse_geometry_message, serialize_scene
from maniml.web.triangle_geometry import GENERATOR_ID, LyonFillTessellator
from tests.winding_reference_renderer import (
    COMPOSITE_BLEND, DEPTH_FORMAT, MODULE_SOURCES, PIPELINE_SPECS,
    UNIFORM_BYTES, WgpuRenderer, load_wgsl, pack_uniforms,
)
from tests.renderer_fixtures import get_fixture, renderer_cases


def straight_alpha_preview(image):
    """Convert a copy of raw premultiplied pixels to PNG's straight RGBA.

    Attachment bytes remain untouched for differential measurements. Alpha-zero
    RGB is set to zero; quantization can make RGB exceed alpha slightly, so the
    reconstructed straight color is clamped to the representable PNG range.
    """
    pixels = np.asarray(image.convert("RGBA"), dtype=float)
    alpha = pixels[:, :, 3:4]
    straight = np.zeros_like(pixels)
    np.divide(pixels[:, :, :3] * 255, alpha, out=straight[:, :, :3], where=alpha > 0)
    straight[:, :, 3:4] = alpha
    return Image.fromarray(np.clip(np.rint(straight), 0, 255).astype("u1"))


def environment_metadata(tessellator, baseline, prototype):
    """Record the actual optional build/device used, outside timed work."""
    root = Path(__file__).resolve().parents[1]
    lock_bytes = (root / "tools/lyon_fill/Cargo.lock").read_bytes()
    packages = tomllib.loads(lock_bytes.decode())["package"]
    return {
        "recorded_utc": datetime.now(timezone.utc).isoformat(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "python": platform.python_version(),
        "numpy": np.__version__,
        "pillow": pillow_version,
        "wgpu_python": wgpu.__version__,
        "wgpu_native": list(wgpu_native.lib_version_info),
        "baseline_adapter": dict(baseline.device.adapter_info),
        "triangle_adapter": dict(prototype.device.adapter_info),
        "generator": GENERATOR_ID,
        "native_helper": {
            "path": tessellator.library_path,
            "abi": 1,  # LyonFillTessellator refuses any other ABI at load time.
            "sha256": sha256(Path(tessellator.library_path).read_bytes()).hexdigest(),
            "cargo_lock_sha256": sha256(lock_bytes).hexdigest(),
            "locked_packages": {package["name"]: package["version"] for package in packages},
        },
    }


def premultiplied_source(module):
    """Reuse production vertex/fragment geometry with one explicit alpha adapter.

    Keep the experiment's changed contract out of production WGSL. The old
    fragment becomes a helper called by a premultiplied-output entry point.
    """
    input_type = {"surface": "SurfaceOut", "stroke": "StrokeOut", "dot": "DotOut"}[module]
    source = load_wgsl(*MODULE_SOURCES[module])
    entry = "@fragment\nfn fs_main"
    if source.count(entry) != 1 or source.count("-> @location(0) vec4f") != 1:
        raise RuntimeError("production fragment contract changed; review the A0 adapter")
    source = source.replace(entry, "fn prototype_straight_color", 1)
    source = source.replace("-> @location(0) vec4f", "-> vec4f", 1)
    return source + f"""
@fragment
fn fs_main(vin: {input_type}) -> @location(0) vec4f {{
    let color = prototype_straight_color(vin);
    return vec4f(color.rgb * color.a, color.a);
}}
"""


class TrianglePrototype(WgpuRenderer):
    """Existing surface/stroke/dot geometry in one ordered output render pass."""

    def __init__(self):
        super().__init__()
        for module in ("surface", "stroke", "dot"):
            self._modules[module] = self.device.create_shader_module(
                code=premultiplied_source(module))
        self._geometry = {}
        self._bindings = {}
        self._downsample_texture = None
        self._downsample_pipeline = None

    def _analytic_pipeline(self, name, samples):
        """Sample-tested quadratic patches plus side=0 ordinary interiors.

        Sample interpolation is explicit: MSAA alone does not evaluate an
        implicit curve separately at every covered sample. See WGSL 13.3.1.4:
        https://gpuweb.github.io/gpuweb/wgsl/#interpolation
        """
        if "analytic" not in self._modules:
            self._modules["analytic"] = self.device.create_shader_module(code=load_wgsl("common.wgsl") + """
struct AnalyticIn {
    @location(0) point: vec3f,
    @location(1) uv: vec2f,
    @location(2) color: vec4f,
    @location(3) side: f32,
}
struct AnalyticOut {
    @builtin(position) position: vec4f,
    @location(0) @interpolate(perspective, sample) uv: vec2f,
    @location(1) @interpolate(flat) color: vec4f,
    @location(2) @interpolate(flat) side: f32,
    @location(3) @interpolate(perspective, sample) clip: f32,
}
@vertex fn vs_main(v: AnalyticIn) -> AnalyticOut {
    var o: AnalyticOut;
    o.position = emit_gl_position(v.point);
    o.uv = v.uv; o.color = v.color; o.side = v.side;
    o.clip = compute_clip_distance(v.point);
    return o;
}
@fragment fn fs_main(v: AnalyticOut) -> @location(0) vec4f {
    if (v.clip < 0.0) { discard; }
    if (v.side != 0.0 && v.side * (v.uv.y - v.uv.x * v.uv.x) < 0.0) { discard; }
    return vec4f(v.color.rgb * v.color.a, v.color.a);
}
""")
        module = self._modules["analytic"]
        depth = name.endswith("_depth")
        layout = {"array_stride": 40, "step_mode": "vertex", "attributes": [
            {"format": fmt, "offset": offset, "shader_location": location}
            for location, fmt, offset in ((0, "float32x3", 0), (1, "float32x2", 12),
                                           (2, "float32x4", 20), (3, "float32", 36))]}
        return self.device.create_render_pipeline(
            layout="auto", vertex={"module": module, "entry_point": "vs_main", "buffers": [layout]},
            fragment={"module": module, "entry_point": "fs_main",
                      "targets": [{"format": "rgba8unorm", "blend": COMPOSITE_BLEND}]},
            primitive={"topology": "triangle-list"},
            depth_stencil={"format": DEPTH_FORMAT, "depth_write_enabled": depth,
                           "depth_compare": "less" if depth else "always"},
            multisample={"count": samples})

    def _ensure_targets(self, size, samples):
        """Allow a measured GPU box resolve of a target doubled in each axis."""
        if self._size == (size, samples):
            return
        for texture in (getattr(self, "out_texture", None), getattr(self, "resolve_texture", None),
                        getattr(self, "depth_texture", None), self._downsample_texture):
            if texture is not None:
                texture.destroy()
        self._downsample_texture = None
        # The experiment has no winding attachments. Production allocation is
        # left alone; these output textures additionally support textureLoad.
        self._size = (size, samples)
        usage = wgpu.TextureUsage.RENDER_ATTACHMENT | wgpu.TextureUsage.COPY_SRC
        self.resolve_texture = None
        self.out_texture = self.device.create_texture(
            size=(*size, 1), format="rgba8unorm", sample_count=samples,
            usage=(wgpu.TextureUsage.RENDER_ATTACHMENT if samples > 1 else
                   usage | wgpu.TextureUsage.TEXTURE_BINDING))
        self.out_view = self.out_texture.create_view()
        if samples > 1:
            self.resolve_texture = self.device.create_texture(
                size=(*size, 1), format="rgba8unorm",
                usage=usage | wgpu.TextureUsage.TEXTURE_BINDING)
            self.resolve_view = self.resolve_texture.create_view()
        self.depth_texture = self.device.create_texture(
            size=(*size, 1), format=DEPTH_FORMAT, sample_count=samples,
            usage=wgpu.TextureUsage.RENDER_ATTACHMENT)
        self.depth_view = self.depth_texture.create_view()

    def _downsample(self, encoder, output_resolution):
        if tuple(v * 2 for v in output_resolution) != self._size[0]:
            raise ValueError("the A0 box resolve requires exactly 2x each output dimension")
        if self._downsample_pipeline is None:
            module = self.device.create_shader_module(code="""
@group(0) @binding(0) var source: texture_2d<f32>;
@vertex fn vs_main(@builtin(vertex_index) i: u32) -> @builtin(position) vec4f {
    let xy = array<vec2f, 3>(vec2f(-1., -1.), vec2f(3., -1.), vec2f(-1., 3.));
    return vec4f(xy[i], 0., 1.);
}
@fragment fn fs_main(@builtin(position) p: vec4f) -> @location(0) vec4f {
    let q = vec2i(p.xy) * 2;
    return 0.25 * (textureLoad(source, q, 0) + textureLoad(source, q + vec2i(1, 0), 0)
                 + textureLoad(source, q + vec2i(0, 1), 0)
                 + textureLoad(source, q + vec2i(1, 1), 0));
}
""")
            self._downsample_pipeline = self.device.create_render_pipeline(
                layout="auto", vertex={"module": module, "entry_point": "vs_main"},
                fragment={"module": module, "entry_point": "fs_main",
                          "targets": [{"format": "rgba8unorm"}]},
                primitive={"topology": "triangle-list"})
        if self._downsample_texture is None:
            self._downsample_texture = self.device.create_texture(
                size=(*output_resolution, 1), format="rgba8unorm",
                usage=wgpu.TextureUsage.RENDER_ATTACHMENT | wgpu.TextureUsage.COPY_SRC)
        pipeline = self._downsample_pipeline
        binding = self.device.create_bind_group(
            layout=pipeline.get_bind_group_layout(0), entries=[{
                "binding": 0, "resource": (self.resolve_texture or self.out_texture).create_view()}])
        render_pass = encoder.begin_render_pass(color_attachments=[{
            "view": self._downsample_texture.create_view(), "load_op": "clear",
            "store_op": "store", "clear_value": (0., 0., 0., 0.)}])
        render_pass.set_pipeline(pipeline)
        render_pass.set_bind_group(0, binding)
        render_pass.draw(3)
        render_pass.end()
        return self._downsample_texture

    def _pipeline(self, name, samples):
        key = (name, samples)
        if name in ("analytic", "analytic_depth"):
            if key not in self._pipelines:
                self._pipelines[key] = self._analytic_pipeline(name, samples)
            return self._pipelines[key]
        if key not in self._pipelines:
            module, layout, topology, target, _, depth = PIPELINE_SPECS[name]
            if target != "out" or module not in ("surface", "stroke", "dot"):
                raise ValueError(f"unsupported prototype pipeline: {name}")
            self._pipelines[key] = self.device.create_render_pipeline(
                layout="auto",
                vertex={"module": self._modules[module], "entry_point": "vs_main", "buffers": layout},
                fragment={"module": self._modules[module], "entry_point": "fs_main",
                          "targets": [{"format": "rgba8unorm", "blend": COMPOSITE_BLEND}]},
                primitive={"topology": topology},
                depth_stencil={"format": DEPTH_FORMAT, "depth_write_enabled": depth,
                               "depth_compare": "less" if depth else "always"},
                multisample={"count": samples})
        return self._pipelines[key]

    def _buffer(self, array, usage, used):
        raw = array.tobytes()
        key = (usage, blake2b(raw, digest_size=16).digest(), len(raw))
        used.add(key)
        if key not in self._geometry:
            self._geometry[key] = self.device.create_buffer_with_data(data=raw, usage=usage)
            self._uploaded_geometry_bytes += len(raw)
        return self._geometry[key]

    def frame(self, frame, *, image=False, output_resolution=None):
        if output_resolution is not None and tuple(v * 2 for v in output_resolution) != frame.resolution:
            raise ValueError("the A0 box resolve requires exactly 2x each output dimension")
        self._ensure_targets(frame.resolution, frame.samples)
        self._uploaded_geometry_bytes = 0
        uploaded_uniform_bytes = 0
        started = perf_counter()
        encoder = self.device.create_command_encoder()
        # Output storage is premultiplied, including a transparent clear color.
        background = np.asarray(frame.background, dtype=float).copy()
        background[:3] *= background[3]
        render_pass = self._out_pass(encoder, background)
        used_geometry, used_bindings = set(), set()
        for draw in frame.draws:
            pipeline = self._pipeline(draw.pipeline, frame.samples)
            packed = pack_uniforms(draw.uniforms)
            key = (draw.pipeline, frame.samples, packed)
            used_bindings.add(key)
            if key not in self._bindings:
                buffer = self.device.create_buffer_with_data(data=packed, usage=wgpu.BufferUsage.UNIFORM)
                uploaded_uniform_bytes += len(packed)
                binding = self.device.create_bind_group(
                    layout=pipeline.get_bind_group_layout(0),
                    entries=[{"binding": 0, "resource": {"buffer": buffer, "size": UNIFORM_BYTES}}])
                self._bindings[key] = (buffer, binding)
            render_pass.set_pipeline(pipeline)
            render_pass.set_bind_group(0, self._bindings[key][1])
            render_pass.set_vertex_buffer(0, self._buffer(draw.vertices, wgpu.BufferUsage.VERTEX,
                                                        used_geometry))
            if draw.indices is None:
                render_pass.draw(draw.count, draw.instances)
            else:
                render_pass.set_index_buffer(self._buffer(draw.indices, wgpu.BufferUsage.INDEX,
                                                         used_geometry), "uint32")
                render_pass.draw_indexed(draw.count)
        render_pass.end()
        texture = (self._downsample(encoder, output_resolution) if output_resolution is not None
                   else self.resolve_texture or self.out_texture)
        command = encoder.finish()
        encoded = perf_counter()
        self.device.queue.submit([command])
        # Timing uses the same one-pixel completion barrier as the old benchmark.
        self.device.queue.read_texture(
            {"texture": texture, "origin": (0, 0, 0)},
            {"offset": 0, "bytes_per_row": 4, "rows_per_image": 1}, (1, 1, 1))
        completed = perf_counter()
        picture = None
        if image:
            size = output_resolution or frame.resolution
            raw = self.device.queue.read_texture(
                {"texture": texture, "origin": (0, 0, 0)},
                {"offset": 0, "bytes_per_row": 4 * size[0], "rows_per_image": size[1]}, (*size, 1))
            picture = Image.frombytes("RGBA", size, bytes(raw))
        # This synchronous A0 harness can retire after its completion barrier.
        # No unbounded history of meshes/uniforms accumulates across morph frames.
        for key in self._geometry.keys() - used_geometry:
            self._geometry.pop(key).destroy()
        for key in self._bindings.keys() - used_bindings:
            buffer, _ = self._bindings.pop(key)
            buffer.destroy()
        return picture, {
            "encode_ms": 1000 * (encoded - started),
            "submit_through_completion_ms": 1000 * (completed - encoded),
            "total_ms": 1000 * (completed - started),
            "passes": 1 + int(output_resolution is not None),
            "draws": len(frame.draws) + int(output_resolution is not None),
            "geometry_bytes": frame.geometry_bytes,
            "retained_gpu_geometry_bytes": sum(key[2] for key in self._geometry),
            "retained_uniform_bytes": len(self._bindings) * UNIFORM_BYTES,
            "uploaded_geometry_bytes": self._uploaded_geometry_bytes,
            "uploaded_uniform_bytes": uploaded_uniform_bytes,
            "nominal_target_bytes": (np.prod(frame.resolution).item() * 4 * (
                2 * frame.samples + int(frame.samples > 1)) + (
                    0 if self._downsample_texture is None else
                    np.prod(tuple(v // 2 for v in frame.resolution)).item() * 4)),
        }


def baseline_frame(renderer, header, data):
    samples = 4 if header.get("samples") else 1
    renderer._ensure_targets(tuple(header["resolution"]), samples)
    renderer._fill_targets_used.clear()
    started = perf_counter()
    encoder = renderer.device.create_command_encoder()
    renderer._out_pass(encoder, header["background"]).end()
    for batch in header["batches"]:
        encode = renderer._encode_vmobject if batch["kind"] == "vmobject" else renderer._encode_plain
        encode(encoder, header, batch, data, samples)
    command = encoder.finish()
    encoded = perf_counter()
    renderer.device.queue.submit([command])
    renderer.device.queue.read_texture(
        {"texture": renderer.resolve_texture or renderer.out_texture, "origin": (0, 0, 0)},
        {"offset": 0, "bytes_per_row": 4, "rows_per_image": 1}, (1, 1, 1))
    completed = perf_counter()
    # Match production render()'s scratch-target retirement after completion.
    # The outer quality timer includes retirement; draw-only stages do not.
    for key in renderer._fill_targets.keys() - renderer._fill_targets_used:
        renderer._fill_targets.pop(key)["texture"].destroy()
    return {"encode_ms": 1000 * (encoded - started),
            "submit_through_completion_ms": 1000 * (completed - encoded),
            "total_ms": 1000 * (completed - started)}


def comparison(name, scene, tessellator, baseline, prototype, samples, directory,
               *, pixel_tolerance=0.25):
    started = perf_counter()
    header, data = parse_geometry_message(serialize_scene(scene))
    serialized = perf_counter()
    frame = prepare_triangle_frame(scene, tessellator, diagnostic=True,
                                   pixel_tolerance=pixel_tolerance)
    prepared = perf_counter()
    measurements = {"winding": [], "triangles": []}
    for iteration in range(samples + 3):
        order = ("winding", "triangles") if iteration % 2 else ("triangles", "winding")
        for variant in order:
            result = (baseline_frame(baseline, header, data) if variant == "winding"
                      else prototype.frame(frame)[1])
            if iteration >= 3:
                measurements[variant].append(result)
    old = baseline.render(header, data)
    new, resources = prototype.frame(frame, image=True)
    straight_alpha_preview(old).save(directory / f"{name}_winding.png")
    straight_alpha_preview(new).save(directory / f"{name}_triangles.png")
    difference = abs(np.asarray(old).astype(int) - np.asarray(new).astype(int))
    rgb = difference[:, :, :3]
    # A difference image's alpha is visualization opacity, not alpha error.
    # Save an opaque RGB visualization so zero alpha error cannot hide RGB error.
    Image.fromarray(np.clip(rgb * 4, 0, 255).astype("u1")).save(directory / f"{name}_diff_x4.png")
    image_gate = float(rgb.mean()) < 1.5 and float((rgb.max(axis=2) > 24).mean()) < 0.005
    return {
        "resolution": list(frame.resolution),
        "msaa_samples": frame.samples,
        "pixel_tolerance": frame.pixel_tolerance,
        "background_rgba": list(frame.background),
        "measurement_samples": samples,
        "warmup_iterations": 3,
        "limitations": frame.limitations,
        "initial_rgb_threshold_met": image_gate,
        "compatibility_accepted": False,  # These diagnostics alone never establish the A0 gate.
        "mean_rgb_difference": float(rgb.mean()),
        "fraction_rgb_over_24": float((rgb.max(axis=2) > 24).mean()),
        "max_rgba_difference": int(difference.max()),
        "mean_alpha_difference": float(difference[:, :, 3].mean()),
        "serialize_once_ms": 1000 * (serialized - started),
        "generate_once_ms": 1000 * (prepared - serialized),
        "baseline_batches": len(header["batches"]),
        "resources": resources,
        "median": {key: {metric: median(row[metric] for row in rows)
                         for metric in ("encode_ms", "submit_through_completion_ms", "total_ms")}
                   for key, rows in measurements.items()},
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--samples", type=int, default=5)
    parser.add_argument("--case", action="append", dest="cases")
    parser.add_argument("--msaa", action="store_true")
    args = parser.parse_args()
    if args.samples < 1:
        parser.error("--samples must be positive")
    args.output.mkdir(parents=True, exist_ok=True)
    tessellator = LyonFillTessellator()
    baseline, prototype = WgpuRenderer(), TrianglePrototype()
    cases = [get_fixture(name) for name in args.cases] if args.cases else renderer_cases()
    report = {"status": "A0 diagnostic; not a production compatibility pass",
              "generator": GENERATOR_ID,
              "environment": environment_metadata(tessellator, baseline, prototype),
              "variants": {
                  "winding": "Current baseline renderer, including its existing triangulated 3D fills and plain primitives; not exclusively winding.",
                  "triangles": "A0 generated fills plus existing direct primitives, premultiplied alpha, and one ordered output pass.",
              },
              "timing": "Warm static drawing, alternating order; total_ms is command encoding plus submission through a one-pixel completion readback. Excludes scene construction, source evaluation, CPU preparation, target allocation, full-image readback, preview conversion, post-completion resource retirement, transport, and browser presentation. One-time CPU preparation is reported separately after baseline serialization; it is not a warmed generation median.",
              "memory_scope": "Per-frame retained_gpu_geometry_bytes and retained_uniform_bytes describe the prototype's steady retained buffers after completion/retirement. They exclude targets, pipeline/driver storage, CPU source/mesh/scratch storage, and transient old-plus-new buffers during turnover. geometry_bytes sums logical draw arrays and may count shared data more than once. These are not peak-memory or budget-enforcement measurements.",
              "pixels": {
                  "comparison": "Raw attachment RGBA bytes, before PNG preview conversion; RGB remains in each renderer's attachment representation.",
                  "previews": "Straight-alpha RGBA PNGs derived by unpremultiplying attachment RGB; diff_x4 is an opaque RGB error visualization. Existing baseline alpha defects remain visible and can make baseline preview colors saturate.",
                  "alpha_semantics": "The prototype uses source-over premultiplied alpha. Existing baseline strokes/dots/surfaces use source-alpha for the alpha channel too, and repeated winding can accumulate excess opacity. These known semantic differences must be distinguished from triangle coverage errors.",
              },
              "samples": args.samples, "cases": {}}
    for fixture in cases:
        scene = fixture.build()
        if args.msaa:
            scene.camera.samples = 4
        report["cases"][fixture.name] = comparison(fixture.name, scene, tessellator,
                                                  baseline, prototype, args.samples, args.output)
        print(fixture.name, report["cases"][fixture.name]["mean_rgb_difference"], flush=True)
    (args.output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(args.output / "report.json")


if __name__ == "__main__":
    main()

"""Where the patch fill's GPU time goes on the 101-glyph text (docs/phase_b1_plan.md,
"Third candidate"), 2026-09-11. Run from the repository root with PYTHONPATH=.
and the Lyon helper; needs wgpu and a GPU.

No argument: the strip pattern at the reservation, at the steps the run needs,
and no strips at all, interleaved frame by frame with rotating order (a lighter
load alone is not faster on the M3, whose GPU clock follows the load).
"passes": each patch draw skipped in turn. "phasea": Phase A against the patch
path and the patch path without its draws."""
import statistics, sys, time
from copy import deepcopy
from unittest.mock import patch as mock_patch
import numpy as np
import wgpu
from maniml.web import wgpu_renderer
from maniml.web.border_geometry import _density_counts
from maniml.web.generated_geometry import serialize_generated_frame
from maniml.web.geometry import GeometryCache, parse_geometry_message
from maniml.web.gpu_border_geometry import OBJECT_WORDS, indices_per_curve, validate_capacity
from maniml.web.triangle_geometry import LyonFillTessellator
from maniml.web.triangle_scene import TriangleMeshCache, prepare_triangle_frame
from tests.renderer_quality_fixtures import build_quality_frame

SAMPLES, WARMUPS = 40, 5
tessellator = LyonFillTessellator()


def frame_for(view):
    q = build_quality_frame("tex", view, border_policy="production_default")
    frame = prepare_triangle_frame(q.scene, tessellator, mesh_cache=TriangleMeshCache(),
                                   fill_borders=True, gpu_borders=True, patch_fills=True)
    frame.samples, frame.supersample = 4, 2
    header, payload = parse_geometry_message(serialize_generated_frame(frame, q.scene.camera.uniforms, GeometryCache()))
    return header, payload, q.scene


def needed_steps(header, payload, scene):
    batch = header["batches"][0]
    span = header["border_data"][batch["border"]["hash"]]
    curves = np.frombuffer(payload[span["offset"]:span["offset"] + span["nbytes"]], dtype="<f4").reshape(-1, 44)
    density = np.where(curves[:, 38] == 1, np.inf, curves[:, 36])
    counts = _density_counts(density, scene.camera.uniforms["frame_scale"])
    return int(counts[curves[:, 37] == 1].max())


def pattern(curve_count, capacity, quads):
    steps = 2 * np.arange(quads, dtype="u4")
    strip = (steps[:, None] + np.array([0, 1, 2, 1, 2, 3], dtype="u4")).reshape(-1)
    return (np.arange(curve_count, dtype="u4")[:, None] * np.uint32(capacity) + strip).reshape(-1)


class Variant:
    def __init__(self, name, header, payload, quads=None):
        self.name, self.header, self.payload, self.quads = name, header, payload, quads
        self.renderer = wgpu_renderer.WgpuRenderer()
        self.times, self.frames = [], 0

    def render(self):
        h = deepcopy(self.header)
        if self.frames:
            for b in h["batches"]:
                b["cached"] = True
                for key in ("offset", "index_offset"):
                    b.pop(key, None)
                b.get("border", {}).pop("layout", None)
            h["border_data"], h["paint_data"], h["object_data"], h["texture_data"] = {}, {}, {}, {}
        quads = self.quads
        per_curve = None if quads is None else 6 * quads

        def index_buffer(self_, batch, resources):
            capacity, _ = self_._border_run(batch)
            key = (capacity, quads)
            buffers = resources["index_buffers"]
            if key not in buffers:
                q = capacity // 2 - 1 if quads is None else quads
                buffers[key] = self_.device.create_buffer_with_data(
                    data=pattern(batch["border"]["num_curves"], capacity, q).tobytes(), usage=wgpu.BufferUsage.INDEX)
            return buffers[key]

        original_encode = wgpu_renderer.WgpuRenderer._encode_patch

        def encode(self_, render_pass, batch, *args):
            if per_curve is not None:
                with mock_patch.object(wgpu_renderer, "indices_per_curve", lambda capacity: per_curve):
                    return original_encode(self_, render_pass, batch, *args)
            return original_encode(self_, render_pass, batch, *args)

        with mock_patch.object(wgpu_renderer.WgpuRenderer, "_patch_index_buffer", index_buffer), \
             mock_patch.object(wgpu_renderer.WgpuRenderer, "_encode_patch", encode):
            start = time.perf_counter()
            self.renderer.render(h, self.payload if not self.frames else b"")
            elapsed = 1000 * (time.perf_counter() - start)
        self.frames += 1
        if self.frames > WARMUPS:
            self.times.append(elapsed)


def run_interleaved(variants):
    for iteration in range(WARMUPS + SAMPLES):
        order = variants[iteration % len(variants):] + variants[:iteration % len(variants)]
        if iteration // len(variants) % 2:
            order = order[::-1]
        for variant in order:
            variant.render()
    for variant in variants:
        print(f"  {variant.name:44s} median {statistics.median(variant.times):5.2f} ms  min {min(variant.times):5.2f} ms")
        variant.renderer.close()


def strip_hack(header, payload):
    """A layout with no bordered objects: the strip draws are skipped."""
    header, payload = deepcopy(header), bytes(payload)
    b = header["batches"][0]
    b["border"]["layout"] = [[n, 0, g] for n, _, g in b["border"]["layout"]]
    span = header["object_data"][b["objects"]["hash"]]
    table = np.frombuffer(payload[span["offset"]:span["offset"] + span["nbytes"]], dtype="<f4").reshape(-1, OBJECT_WORDS).copy()
    table[:, 5] = 0
    import hashlib
    key = hashlib.blake2b(table.tobytes(), digest_size=16).hexdigest()
    header["object_data"] = {key: {"offset": len(payload), "nbytes": table.nbytes}}
    payload += table.tobytes()
    b["objects"] = {"hash": key, "count": len(table)}
    b["count"] = 6 * sum(n for n, _, _ in b["border"]["layout"])
    b["hash"] = hashlib.blake2b(b"nostrips" + key.encode(), digest_size=16).hexdigest()
    return header, payload


for view in ([] if "passes" in sys.argv else ("normal", "zoom")):
    header, payload, scene = frame_for(view)
    capacity = header["batches"][0]["border"]["capacity"]
    steps = needed_steps(header, payload, scene)
    print(f"tex {view}: capacity {capacity} ({capacity // 2 - 1} quads per curve), needed steps {steps} ({steps - 1} quads)")
    run_interleaved([Variant("pattern at the reservation (today)", header, payload),
                     Variant("pattern at the needed steps", header, payload, quads=steps - 1),
                     Variant("no strips at all (bound)", *strip_hack(header, payload))])


class SkipVariant(Variant):
    """Skip named patch draws (timing only; pixels are wrong on purpose)."""
    def __init__(self, name, header, payload, skip):
        super().__init__(name, header, payload)
        self.skip = skip

    def render(self):
        skip = self.skip
        original = wgpu_renderer.WgpuRenderer._patch_pipeline
        real_draw = None

        def encode(self_, render_pass, *args):
            pipelines = {}

            def pipeline(self__, kind, depth, samples):
                p = original(self__, kind, depth, samples)
                pipelines[id(p)] = kind
                return p
            draw = render_pass.draw
            set_pipeline = render_pass.set_pipeline
            current = {"kind": None}

            def my_set_pipeline(p):
                current["kind"] = pipelines.get(id(p), "strip")
                set_pipeline(p)

            def my_draw(*a, **k):
                if current["kind"] in skip:
                    return
                draw(*a, **k)
            render_pass.set_pipeline = my_set_pipeline
            render_pass.draw = my_draw
            with mock_patch.object(wgpu_renderer.WgpuRenderer, "_patch_pipeline", pipeline):
                return wgpu_renderer.WgpuRenderer._encode_patch_original(self_, render_pass, *args)

        h = deepcopy(self.header)
        if self.frames:
            for b in h["batches"]:
                b["cached"] = True
                for key in ("offset", "index_offset"):
                    b.pop(key, None)
                b.get("border", {}).pop("layout", None)
            h["border_data"], h["paint_data"], h["object_data"], h["texture_data"] = {}, {}, {}, {}
        with mock_patch.object(wgpu_renderer.WgpuRenderer, "_encode_patch", encode):
            start = time.perf_counter()
            self.renderer.render(h, self.payload if not self.frames else b"")
            elapsed = 1000 * (time.perf_counter() - start)
        self.frames += 1
        if self.frames > WARMUPS:
            self.times.append(elapsed)


wgpu_renderer.WgpuRenderer._encode_patch_original = wgpu_renderer.WgpuRenderer._encode_patch
if "passes" in sys.argv:
    for view in ("normal", "zoom"):
        header, payload, scene = frame_for(view)
        print(f"tex {view}, passes skipped")
        run_interleaved([Variant("all five draws", header, payload),
                         SkipVariant("no cover (fan+patch) draw", header, payload, {"cover", "cover_paint"}),
                         SkipVariant("no mark_patch draw", header, payload, {"mark_patch"}),
                         SkipVariant("no mark_fan draw", header, payload, {"mark_fan"}),
                         SkipVariant("no patch draws at all (strips only)", header, payload, {"cover", "cover_paint", "mark_patch", "mark_fan"})])


if "phasea" in sys.argv:
    for view in ("normal", "zoom"):
        q = build_quality_frame("tex", view, border_policy="production_default")
        frame = prepare_triangle_frame(q.scene, tessellator, mesh_cache=TriangleMeshCache(), fill_borders=True, gpu_borders=True)
        frame.samples, frame.supersample = 4, 2
        mesh_header, mesh_payload = parse_geometry_message(serialize_generated_frame(frame, q.scene.camera.uniforms, GeometryCache()))
        header, payload, scene = frame_for(view)
        print(f"tex {view}, Phase A against the patch path, interleaved")
        run_interleaved([Variant("Phase A (mesh fill + GPU border)", mesh_header, mesh_payload),
                         Variant("patch fill, all five draws", header, payload),
                         SkipVariant("patch fill, no patch draws", header, payload, {"cover", "cover_paint", "mark_patch", "mark_fan"})])

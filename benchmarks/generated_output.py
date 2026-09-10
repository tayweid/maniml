"""Small production A1 comparison with full RGBA readback on both paths.

    python -m benchmarks.generated_output --samples 12 \
        --output /private/tmp/maniml-a1-performance

Requires the packaged Lyon helper (or MANIML_LYON_LIBRARY), wgpu and real TeX
fixture tools. Sources/devices/caches are fresh for each case and renderer.
This is an integration measurement, not final performance or AA acceptance.
"""

import argparse
from collections import defaultdict
from contextlib import contextmanager
from hashlib import sha256
import json
import math
import os
from pathlib import Path
from time import perf_counter

import numpy as np

from benchmarks.renderer_motion import percentiles
from benchmarks.renderer_quality import difference_metrics
from benchmarks.renderer_timing import completion_distribution
from benchmarks.triangle_renderer import environment_metadata
from benchmarks.triangle_wordmark import build_wordmark_scene
from maniml.web import geometry
from maniml.web.geometry import GeometryCache, parse_geometry_message, serialize_scene
from maniml.web.wgpu_renderer import WgpuRenderer
from tests.renderer_quality_fixtures import _configure_camera, _source_digest, build_quality_frame


VARIANTS = ("winding", "triangles")
WARMUPS = 3


class StageObserver:
    """Observe existing production stages without retaining recorder history."""
    def __init__(self):
        self.reset()

    def reset(self):
        self.milliseconds = defaultdict(float)

    @contextmanager
    def stage(self, name):
        start = perf_counter()
        try:
            yield
        finally:
            self.milliseconds[name] += 1000 * (perf_counter() - start)

    def increment(self, *args, **kwargs):
        pass

    def gauge(self, *args, **kwargs):
        pass


class QueueObserver:
    """Time the public render call around its real submission/full readback.

    The interval includes host wait, polling/mapping and (for generated draws)
    post-submit resource retirement. It is deliberately not named GPU time.
    """
    def __init__(self, renderer):
        self.queue = renderer.device.queue
        self.original_submit = self.queue.submit
        self.original_read = self.queue.read_texture
        self.queue.submit = self.submit
        self.queue.read_texture = self.read_texture
        self.reset()

    def reset(self):
        self.submitted_at = self.read_completed_at = None
        self.submissions = self.reads = 0
        self.read_size = None
        self.inside_read = False
        self.readback_submissions = 0

    def submit(self, *args, **kwargs):
        if self.inside_read:
            self.readback_submissions += 1
        else:
            self.submissions += 1
            self.submitted_at = perf_counter()
        return self.original_submit(*args, **kwargs)

    def read_texture(self, source, layout, size):
        self.reads += 1
        self.read_size = tuple(size)
        self.inside_read = True
        try:
            result = self.original_read(source, layout, size)
        finally:
            self.inside_read = False
        self.read_completed_at = perf_counter()
        return result

    def close(self):
        self.queue.submit = self.original_submit
        self.queue.read_texture = self.original_read


def source_contract(scene):
    """Authored bytes, identity/order and draw style; excludes derived normals."""
    style = []
    identities = []
    for group in scene.render_groups:
        identities.append(tuple(id(mob) for mob in group.get_family()))
        style.append([(type(mob).__name__, mob.z_index, bool(mob.depth_test),
                       bool(getattr(mob, "stroke_behind", False)), mob.uniforms)
                      for mob in group.get_family()])
    return (_source_digest(scene.mobjects), tuple(identities),
            json.dumps(style, sort_keys=True, default=geometry._jsonable))


def build_case(name, variant):
    if name == "b0_static":
        scene, header, _, digest = build_wordmark_scene()
        metadata = {"fixture": "original B0 211-square wordmark", "objects": 211,
                    "original_winding_batches": len(header["batches"]),
                    "resolution": header["resolution"], "source_sha256": digest,
                    "motion": "static original 24x12 camera"}
    else:
        quality = build_quality_frame("tex", border_policy="production_default")
        scene = quality.scene
        metadata = dict(quality.metadata, motion="camera-only 1→2→1 zoom with fractional-pixel pan")
    # The selected production triangle candidate uses 4x MSAA. Winding retains
    # its original one-sample scene output and internal winding/stroke AA.
    scene.camera.samples = 4 if variant == "triangles" else 0
    return scene, metadata


def camera_pose(scene, case, phase):
    if case == "tex_camera":
        zoom = 1 + .5 * (1 - math.cos(2 * math.pi * phase))
        _configure_camera(scene, zoom, (.5 * math.sin(2 * math.pi * phase), .25 * phase))
    return camera_state(scene)


def camera_state(scene):
    scene.camera.refresh_uniforms()
    return json.dumps(scene.camera.uniforms, sort_keys=True, default=geometry._jsonable)


def resources(renderer, cache, header):
    stores = (renderer.batch_cache, renderer._generated_geometry)
    buffers = {id(value): value.size for store in stores for item in store.values()
               for value in item.values() if hasattr(value, "size") and hasattr(value, "destroy")}
    meshes = cache.triangle_meshes.stats if cache.triangle_meshes is not None else None
    return {
        "batches": len(header["batches"]),
        "cached_batches": sum(bool(batch.get("cached")) for batch in header["batches"]),
        "vertex_records": sum(batch["num_verts"] for batch in header["batches"]),
        "generated_fill_triangles": (sum(batch.get("index_count", 0) // 3
            for batch in header["batches"]) if header.get("renderer") == "triangles" else None),
        "retained_cpu_mesh_bytes": 0 if meshes is None else meshes["retained_bytes"],
        "retained_gpu_geometry_bytes": sum(buffers.values()),
        "retained_gpu_geometry_entries": sum(len(store) for store in stores),
        "retained_generated_uniform_bytes": sum(value[0].size for value in renderer._generated_uniforms.values()),
        "retained_winding_target_bytes": sum(8 * target["size"][0] * target["size"][1]
            for target in renderer._fill_targets.values()),
        "sender_hashes": len(cache.sent),
        "mesh_cache_totals": meshes,
    }


def sample(scene, variant, renderer, cache, stages, queue):
    stages.reset()
    queue.reset()
    started = perf_counter()
    message = serialize_scene(scene, cache, renderer=variant)
    serialized = perf_counter()
    header, payload = parse_geometry_message(message)
    parsed = perf_counter()
    image = renderer.render(header, payload)  # Both routes perform full RGBA readback.
    completed = perf_counter()
    size = tuple(header["resolution"])
    if queue.submissions != 1 or queue.reads != 1 or queue.read_size != (*size, 1):
        raise RuntimeError("Production render no longer performs exactly one full-frame readback")
    if image.mode != "RGBA" or image.size != size or header.get("unsupported"):
        raise RuntimeError("Incomplete production output")
    ms = stages.milliseconds
    prepare = (ms["geometry.triangle_prepare"] if variant == "triangles" else
               sum(ms[key] for key in ("geometry.camera_uniforms", "geometry.collect_shader_data",
                                      "geometry.merge_batches", "geometry.fill_bounds")))
    wire = (ms["geometry.triangle_encode"] if variant == "triangles" else
            ms["geometry.pack_and_hash"] + ms["geometry.json_and_join"])
    row = {
        "prepare_ms": prepare,
        "wire_encode_ms": wire,
        "serialize_ms": 1000 * (serialized - started),
        "parse_ms": 1000 * (parsed - serialized),
        "render_cpu_encode_ms": 1000 * (queue.submitted_at - parsed),
        "submit_through_full_readback_ms": 1000 * (queue.read_completed_at - queue.submitted_at),
        "post_readback_ms": 1000 * (completed - queue.read_completed_at),
        "serialize_through_rgba_image_ms": 1000 * (completed - started),
        "message_bytes": len(message), "geometry_payload_bytes": len(payload),
        "full_readback_bytes": size[0] * size[1] * 4,
        "internal_readback_submissions": queue.readback_submissions,
        **resources(renderer, cache, header),
    }
    return row, image, header


def run_case(name, count, stages):
    scenes, metadata, renderers, caches, queues, contracts = {}, {}, {}, {}, {}, {}
    for variant in VARIANTS:
        scenes[variant], metadata[variant] = build_case(name, variant)
        renderers[variant] = WgpuRenderer()
        caches[variant] = GeometryCache()
        queues[variant] = QueueObserver(renderers[variant])
        contracts[variant] = source_contract(scenes[variant])
    if metadata["winding"] != metadata["triangles"] or contracts["winding"][0] != contracts["triangles"][0]:
        raise RuntimeError("Variant source content differs before benchmarking")
    rows = {variant: [] for variant in VARIANTS}
    last_images, last_headers = {}, {}
    try:
        for iteration in range(WARMUPS + count):
            index = iteration - WARMUPS
            phase = max(0, index) / (count - 1)
            poses = {variant: camera_pose(scenes[variant], name, phase) for variant in VARIANTS}
            if poses["winding"] != poses["triangles"]:
                raise RuntimeError("Variant cameras differ")
            order = VARIANTS[iteration % 2:] + VARIANTS[:iteration % 2]
            for variant in order:
                row, image, header = sample(scenes[variant], variant, renderers[variant],
                    caches[variant], stages, queues[variant])
                if source_contract(scenes[variant]) != contracts[variant]:
                    raise RuntimeError(f"{variant} altered source geometry, style or object order")
                if camera_state(scenes[variant]) != poses[variant]:
                    raise RuntimeError(f"{variant} altered camera state")
                if index >= 0:
                    rows[variant].append(dict(frame=index, phase=phase, **row))
                    last_images[variant] = image
                    last_headers[variant] = header
        timing_names = [key for key in rows["winding"][0] if key.endswith("_ms")]
        report = {"source": metadata["winding"], "source_contract_preserved": True,
                  "variants": {variant: {
                      "timing_ms": {key: percentiles([row[key] for row in rows[variant]]) for key in timing_names},
                      "readback_distribution": completion_distribution([row["submit_through_full_readback_ms"] for row in rows[variant]]),
                      "samples": rows[variant],
                      "limitations": last_headers[variant].get("limitations", []),
                  } for variant in VARIANTS},
                  "last_matching_pose_pixels": difference_metrics(last_images["winding"], last_images["triangles"]),
                  "environment": environment_metadata(caches["triangles"].triangle_tessellator,
                      renderers["winding"], renderers["triangles"])}
        return report
    finally:
        for queue in queues.values():
            queue.close()
        # Cases use fresh devices, so earlier geometry cannot bias later cases.
        for renderer in renderers.values():
            renderer.device.destroy()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", type=int, default=12)
    parser.add_argument("--output", type=Path, default=Path("/private/tmp/maniml-a1-performance"))
    args = parser.parse_args()
    if not 10 <= args.samples <= 15:
        parser.error("--samples must be between 10 and 15 for this bounded integration run")
    # Fixture reconstruction helpers use the historical serializer default;
    # actual timed calls select the variant explicitly.
    os.environ.pop("MANIML_RENDERER", None)
    observer = StageObserver()
    previous = geometry.performance
    geometry.performance = observer
    root = Path(__file__).resolve().parents[1]
    sources = [Path(__file__), root / "maniml/web/geometry.py", root / "maniml/web/generated_geometry.py",
               root / "maniml/web/triangle_scene.py", root / "maniml/web/triangle_geometry.py",
               root / "maniml/web/wgpu_renderer.py", root / "tools/lyon_fill/src/lib.rs"]
    report = {
        "purpose": "Bounded production A1 integration measurement; not final speed or appearance acceptance",
        "samples_per_variant": args.samples, "excluded_warmups_per_variant": WARMUPS,
        "order": "Variant order alternates each frame. Fresh equal-content sources, devices and caches per case/variant.",
        "timing_scope": "Public serialize_scene plus parse_geometry_message then unmodified WgpuRenderer.render. Prepare/wire stages are existing production scopes; their sum may exclude small serializer overhead. Render CPU encoding ends at queue.submit. Submission through full RGBA readback includes GPU work, host waits, mapping/polling and generated-resource retirement; it is not GPU timestamp time. Total ends after PIL image construction. Construction/TeX compilation, camera updates, source checks and resource summaries are outside timing. No transport, browser/UI presentation or PNG writes are measured.",
        "aa": "Winding uses original camera.samples=0 plus production internal winding/stroke AA. Triangles uses 4x MSAA and actual uniform fill-border unions. Same output dimensions/full RGBA readback bytes, but AA algorithms differ; border/auto-join limitations remain explicit.",
        "memory_scope": "Post-render retained array/buffer counts, not peak process/GPU memory. Winding targets reported separately; output/depth/resolve, readback staging, driver/bind-group storage and native tessellator scratch excluded. Existing winding history retention behavior is retained rather than normalized away.",
        "source_files_sha256": {str(path.relative_to(root)): sha256(path.read_bytes()).hexdigest() for path in sources},
        "cases": {},
    }
    args.output.mkdir(parents=True, exist_ok=True)
    try:
        for case in ("b0_static", "tex_camera"):
            report["cases"][case] = run_case(case, args.samples, observer)
            (args.output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
            print(case, json.dumps({variant: data["timing_ms"]
                for variant, data in report["cases"][case]["variants"].items()}), flush=True)
    finally:
        geometry.performance = previous
    print("Report:", args.output / "report.json", flush=True)


if __name__ == "__main__":
    main()

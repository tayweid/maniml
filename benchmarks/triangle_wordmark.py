"""Reproduce B0's exact source/camera while comparing four A0 render variants.

Run with the optional Lyon helper and locked WebGPU dependencies available:
    python -m benchmarks.triangle_wordmark --output /private/tmp/maniml-wordmark-a0

All comparisons use the original 211-square wordmark at 2160x1080. No source
animation, browser transport, UI presentation or full-image readback is timed.
"""

import argparse
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
from time import perf_counter
from types import SimpleNamespace

import numpy as np

from benchmarks.ordered_output import OrderedOutputControl
from benchmarks.renderer_motion import UploadObserver, percentiles
from benchmarks.renderer_quality import difference_metrics
from benchmarks.renderer_timing import COMPLETION_SCOPE, completion_distribution
from benchmarks.triangle_renderer import TrianglePrototype, baseline_frame, environment_metadata
from benchmarks.triangle_scene import TriangleMeshCache, prepare_triangle_frame
from benchmarks.vector_fill import payload
from tests.winding_reference_geometry import parse_geometry_message, serialize_scene
from maniml.web.triangle_geometry import LyonFillTessellator
from tests.winding_reference_renderer import WgpuRenderer
from tests.renderer_quality_fixtures import _source_digest
from tests.test_fill_bounds import _wordmark


VARIANTS = ("current_webgpu", "ordered_output", "flat_samples1", "flat_msaa4")


def build_wordmark_scene():
    word = _wordmark().set_stroke(color="#212121")
    for index, square in enumerate(word):
        square.set_fill(("#3377AA", "#88BBEE", "#225588")[index % 3], opacity=1)
    source_digest = _source_digest([word])
    header, data = payload(word)
    camera = SimpleNamespace(uniforms=deepcopy(header["camera"]),
                             refresh_uniforms=lambda: None,
                             background_rgba=list(header["background"]),
                             samples=header["samples"],
                             fbo=SimpleNamespace(size=tuple(header["resolution"])),
                             draw_fbo=SimpleNamespace(size=tuple(header["resolution"])))
    scene = SimpleNamespace(mobjects=[word], render_groups=[word], camera=camera)
    rebuilt_header, rebuilt_data = parse_geometry_message(serialize_scene(scene))
    if rebuilt_header != header or rebuilt_data != data:
        raise RuntimeError("static-camera source reconstruction differs from vector_fill.payload")
    if len(word) != 211 or len(header["batches"]) != 135:
        raise RuntimeError("B0 source fixture count changed")
    if _source_digest([word]) != source_digest:
        raise RuntimeError("source construction/serialization changed authored geometry or style")
    # All B0 batches use one fill pass (two draws), a composite output pass,
    # and a stroke output pass. Validate that contract before recording counts.
    for batch in header["batches"]:
        if (batch["kind"] != "vmobject" or batch.get("fill_mode") == "triangulated"
                or not batch.get("fill_rect") or not all(batch["fill_rect"][2:])):
            raise RuntimeError("B0 pass/draw-count contract changed")
    return scene, header, data, source_digest


def _source_state(scene):
    return (_source_digest(scene.mobjects),
            tuple(id(mob) for mob in scene.render_groups[0].get_family()),
            json.dumps(scene.camera.uniforms, sort_keys=True),
            tuple(scene.camera.draw_fbo.size), scene.camera.samples)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("/private/tmp/maniml-wordmark-a0"))
    parser.add_argument("--samples", type=int, default=5)
    args = parser.parse_args()
    if args.samples < 1:
        parser.error("--samples must be positive")
    scene, original_header, original_data, source_digest = build_wordmark_scene()
    source_state = _source_state(scene)
    tessellator = LyonFillTessellator()
    current, ordered = WgpuRenderer(), OrderedOutputControl()
    flat = {"flat_samples1": TrianglePrototype(), "flat_msaa4": TrianglePrototype()}
    caches = {name: TriangleMeshCache() for name in flat}
    observers = {"current_webgpu": UploadObserver(current), "ordered_output": UploadObserver(ordered)}
    started = perf_counter()
    cold = prepare_triangle_frame(scene, tessellator, diagnostic=True, mesh_cache=TriangleMeshCache())
    cold_preparation_ms = 1000*(perf_counter()-started)

    def draw(name, *, image=False):
        observer = observers.get(name)
        if observer:
            observer.reset()
        started = perf_counter()
        if name in observers:
            header, data = parse_geometry_message(serialize_scene(scene))
            prepared = perf_counter()
            if name == "current_webgpu":
                measured = baseline_frame(current, header, data)
                picture = current.render(header, data) if image else None
                measured["passes"] = 3*len(header["batches"])+1
                measured["draws"] = 4*len(header["batches"])
            else:
                picture, measured = ordered.frame(header, data, image=image)
            completed = perf_counter()
            measured.update(observer.stats())
            measured.update({"serialized_vertex_bytes": len(data),
                             "retained_cpu_mesh_bytes": 0,
                             "nominal_target_bytes": int(np.prod(header["resolution"]))*8})
        else:
            frame = prepare_triangle_frame(scene, tessellator, diagnostic=True, mesh_cache=caches[name])
            frame.samples = 1 if name == "flat_samples1" else 4
            prepared = perf_counter()
            picture, measured = flat[name].frame(frame, image=image)
            completed = perf_counter()
            measured.update({"mesh_cache": frame.mesh_cache_stats,
                             "retained_cpu_mesh_bytes": frame.mesh_cache_stats["retained_bytes"],
                             "source_array_bytes": frame.source_bytes,
                             "limitations": frame.limitations})
        measured.update({"prepare_ms": 1000*(prepared-started),
                         "cpu_prepare_through_completion_ms": 1000*(completed-started)})
        if _source_state(scene) != source_state:
            raise RuntimeError(f"{name} changed the wordmark source/camera")
        return picture, measured

    measurements = {name: [] for name in VARIANTS}
    warmups = {name: [] for name in VARIANTS}
    for iteration in range(args.samples+3):
        order = VARIANTS[iteration % len(VARIANTS):] + VARIANTS[:iteration % len(VARIANTS)]
        for name in order:
            _, measurement = draw(name)
            (warmups if iteration < 3 else measurements)[name].append(measurement)
    args.output.mkdir(parents=True, exist_ok=True)
    pictures, resources = {}, {}
    for name in VARIANTS:
        pictures[name], resources[name] = draw(name, image=True)
        pictures[name].save(args.output/f"{name}_raw_rgba.png")
        pictures[name].convert("RGB").save(args.output/f"{name}_rgb.png")
    reference = np.asarray(pictures["current_webgpu"], dtype=int)
    comparisons = {}
    for name, picture in pictures.items():
        difference = abs(reference-np.asarray(picture, dtype=int))
        comparisons[name] = {
            **difference_metrics(pictures["current_webgpu"], picture),
            "exact_rgba_equal": not bool(difference.any()),
            "changed_rgba_pixels": int(np.any(difference != 0, axis=2).sum()),
            "changed_rgb_pixels": int(np.any(difference[..., :3] != 0, axis=2).sum()),
            "changed_alpha_pixels": int(np.count_nonzero(difference[..., 3])),
        }
    root = Path(__file__).resolve().parents[1]
    paths = [Path(__file__), root/"benchmarks/vector_fill.py", root/"tests/test_fill_bounds.py",
             root/"benchmarks/triangle_scene.py", root/"benchmarks/triangle_renderer.py",
             root/"benchmarks/ordered_output.py", root/"benchmarks/renderer_motion.py",
             root/"benchmarks/renderer_quality.py", root/"benchmarks/renderer_timing.py",
             root/"maniml/utils/space_ops.py"]
    report = {
        "status": "A0 B0 wordmark comparison; no production compatibility acceptance",
        "compatibility_accepted": False,
        "environment": environment_metadata(tessellator, current, flat["flat_samples1"]),
        "source_files_sha256": {str(path.relative_to(root)): sha256(path.read_bytes()).hexdigest() for path in paths},
        "source": {"builder": "benchmarks.vector_fill.main wordmark styling and payload camera",
                   "squares": 211, "groups": 1, "logical_batches": len(original_header["batches"]),
                   "resolution": original_header["resolution"], "camera": original_header["camera"],
                   "background": original_header["background"], "source_sha256": source_digest,
                   "serialized_vertex_bytes": len(original_data),
                   "reconstructed_source_matches_original_payload": True,
                   "all_source_validation_passed": True},
        "cold_triangle_preparation": {"ms": cold_preparation_ms, "mesh_cache": cold.mesh_cache_stats,
                                      "geometry_bytes": cold.geometry_bytes, "source_bytes": cold.source_bytes},
        "samples_per_variant": args.samples, "warmups_per_variant": 3,
        "completion_scope": COMPLETION_SCOPE,
        "timing": "Fresh devices and three rotated warmup frames followed by rotated measured order. Each current/ordered sample includes fresh serialize_scene plus parse_geometry_message; each triangle sample includes preparation with a warm retained mesh cache. CPU preparation through completion includes target allocation, upload, command preparation, one-pixel completion readback and post-completion retirement. Source construction, validation, observer summaries, full-image readback and PNG output are outside timings. Source animation, transport, browser/UI presentation absent. Completion is not a pure GPU timestamp. Other host activity was not controlled; do not transfer speed ratios to unrelated runs.",
        "aa": "Current/ordered retain production 2x winding textures with one-sample scene output. flat_samples1 uses one-sample triangle output as a sample-count control, not an equivalent AA treatment. flat_msaa4 uses four-sample triangle output. Existing stroke geometry/AA uniforms are reused; no zero-border/style override. The wordmark's class-default fill border is zero.",
        "pixels": "Full raw RGBA equality checked current vs ordered. Raw-attachment RGB and alpha differences are reported separately for triangles: direct current strokes use the known source-alpha output-alpha factor, triangles use premultiplied source-over. RGB preview PNGs preserve raw attachment RGB; raw RGBA PNGs are archival attachment bytes, not normalized straight-alpha previews.",
        "memory": "Reported retained CPU meshes and owned GPU buffers are post-completion state, not transient peaks. Nominal output color/depth bytes and winding targets are separately listed. Driver/pipeline/bind-group storage, source arrays unless stated, one-pixel/full-image staging and Lyon scratch excluded. Uniform upload counts for current/ordered omit composite UV-scale buffers. Current pass counts validated from B0's one fill/composite/stroke sequence per logical batch, not hardware counters.",
        "variants": {},
    }
    for name in VARIANTS:
        report["variants"][name] = {
            "completion_distribution": completion_distribution(
                [row["submit_through_completion_ms"] for row in measurements[name]]),
            "samples": measurements[name], "warmups": warmups[name],
            "timing_ms": {field: percentiles([row[field] for row in measurements[name]])
                          for field in ("prepare_ms", "encode_ms", "submit_through_completion_ms",
                                        "cpu_prepare_through_completion_ms")},
            "diagnostic_resources": resources[name], "vs_current": comparisons[name],
        }
    (args.output/"report.json").write_text(json.dumps(report, indent=2)+"\n")
    print(json.dumps({"report": str(args.output/"report.json"),
                      "median_prepare_through_completion_ms": {
                          name: report["variants"][name]["timing_ms"]["cpu_prepare_through_completion_ms"]["p50"]
                          for name in VARIANTS}, "comparisons": comparisons}, indent=2))


if __name__ == "__main__":
    main()

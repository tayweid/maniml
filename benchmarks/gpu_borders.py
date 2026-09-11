"""Retained GPU borders against CPU borders and both historical references.

python -m benchmarks.gpu_borders --output /private/tmp/maniml-gpu-borders
Use --cpu-only to validate sources, preparation and wire without a GPU.
Optional --transport measures a real uncompressed loopback WebSocket echo.
"""

import argparse
from contextlib import ExitStack
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import json
import math
from pathlib import Path
import platform
from time import perf_counter
from unittest.mock import patch

import numpy as np

from benchmarks.generated_output import QueueObserver, StageObserver, source_contract
from benchmarks.paint_retention import difference, stats, wire_metadata
from benchmarks.renderer_timing import completion_distribution
from benchmarks.triangle_wordmark import build_wordmark_scene
from maniml.constants import BLUE, RED
from maniml.mobject.geometry import Circle
from maniml.web import geometry, winding_geometry
from maniml.web.geometry import GeometryCache, parse_geometry_message, serialize_scene
from tests.renderer_fixtures import build_scene, concave_quad
from tests.renderer_quality_fixtures import _configure_camera, build_quality_frame


VARIANTS = ("gpu_border", "cpu_border", "original_2d", "native_gl")
CASES = ("b0_static", "tex_static", "tex_pan", "tex_zoom5", "tex_zoom4_cycle",
         "tex_tilt", "tex_resize", "changing_paths")
MOTIONS = {
    "tex_static": "static authored geometry and camera",
    "tex_pan": "camera displacement .125x/.0625y output pixels per measured frame",
    "tex_zoom5": "repeated5% frame-height reduction; magnification is1/.95**index",
    "tex_zoom4_cycle": "camera magnification1→4→1 with exact maximum4",
    "tex_tilt": "camera orientation0→(15deg,50deg,0deg), fixed source paths",
    "tex_resize": "960x540→1280x720→800x450 repeated; fixed logical camera/style",
}


def build_case(name):
    if name == "b0_static":
        scene, header, _, _ = build_wordmark_scene()
        return scene, {"source": "exact vector_fill.payload 211-square B0", "objects": 211,
                       "original_batches": len(header["batches"]), "resolution": header["resolution"],
                       "camera": header["camera"], "fill_border_width": 0}
    if name == "changing_paths":
        path = concave_quad(0).set_fill(RED, opacity=.55, border_width=4)
        circle = Circle(radius=.65, fill_color=BLUE, fill_opacity=1,
                        stroke_width=0, fill_border_width=2).shift([1.5, .5, 0])
        return build_scene(path, circle, resolution=(960, 540)), {
            "source": "concave quadrilateral morph plus changing curved path; stable VMobject identities",
            "objects": 2, "resolution": [960, 540]}
    quality = build_quality_frame("tex", border_policy="production_default")
    count = sum(mob.has_points() for group in quality.scene.mobjects for mob in group.get_family())
    if count != 101:
        raise RuntimeError(f"real TeX fixture expected 101 glyphs, found {count}")
    return quality.scene, dict(quality.metadata, objects=count, motion=MOTIONS[name],
                               rois=[{"name": roi.name, "box": roi.box} for roi in quality.rois])


def evaluate(scene, name, index, count, base_points):
    """Only source/camera evaluation; caller times this separately from rendering."""
    phase = index / max(1, count - 1)
    if name.startswith("tex"):
        zoom, offset = 1., (0., 0.)
        if name == "tex_pan":
            offset = (.125 * index, .0625 * index)
        elif name == "tex_zoom5":
            zoom = 1 / .95 ** index
        elif name == "tex_zoom4_cycle":
            up = (count + 1) // 2
            zoom = (1 + 3 * index / max(1, up - 1) if index < up
                    else 4 - 3 * (index - up + 1) / (count - up))
        _configure_camera(scene, zoom, offset)
        if name == "tex_tilt":
            scene.camera.frame.reorient(15 * phase, 50 * phase, 0)
        if name == "tex_resize":
            # Same aspect and authored camera; allocate different pixel targets.
            scene.camera.draw_fbo.size = ((960, 540), (1280, 720), (800, 450))[index % 3]
    elif name == "changing_paths":
        alpha = .5 * (1 - math.cos(2 * math.pi * phase))
        quad = base_points[0].copy()
        # Move the second polygon corner and its two adjacent midpoint controls.
        corner = np.array([2 - 3 * alpha, -2 + 3 * alpha, 0])
        quad[2] = corner
        quad[1], quad[3] = (quad[0] + corner) / 2, (corner + quad[4]) / 2
        scene.mobjects[0].set_points(quad)
        curved = base_points[1].copy()
        curved[:, 0] = 1.5 + (curved[:, 0] - 1.5) * (1 + .25 * math.sin(2 * math.pi * phase))
        scene.mobjects[1].set_points(curved)
    scene.camera.refresh_uniforms()
    return {"frame": index, "phase": phase,
            "resolution": list(scene.camera.draw_fbo.size),
            "camera": deepcopy(geometry._jsonable(scene.camera.uniforms))}


def resize_gl(camera, size):
    """Target-only harness adapter; NativeGLCamera has no public resize method."""
    if camera.get_pixel_shape() == tuple(size):
        return
    with camera.ctx:
        old = (camera.fbo_for_files, camera.draw_fbo)
        camera.default_pixel_shape = tuple(size)
        camera.init_fbo()
        for target in old:
            for attachment in (*target.color_attachments, target.depth_attachment):
                if attachment is not None:
                    attachment.release()
            target.release()


def resource_summary(renderer, cache, header):
    """Post-completion retained buffers, not peak allocations or process RSS."""
    result = {"batches": len(header["batches"]),
              "cached_batches": sum(bool(batch.get("cached")) for batch in header["batches"])}
    if cache.triangle_meshes is not None:
        meshes = cache.triangle_meshes
        result.update(mesh_cache=meshes.stats,
            gpu_border_source_updates=meshes.gpu_border_cache.source_updates,
            gpu_border_assemblies=meshes.gpu_border_cache.assemblies,
            retained_cpu_border_recipe_bytes=meshes.gpu_border_cache.nbytes)
    if header.get("renderer") == "triangles":
        coverage = sum(bool(batch.get("coverage")) for batch in header["batches"])
        result.update(scene_draws=sum(1 + bool(batch.get("coverage") and batch["pipeline"].endswith("_depth"))
                                     for batch in header["batches"]),
            scene_render_passes=1 + max(0, coverage - 1) // 255,
            resolve_draws=int(header.get("supersample", 1) > 1),
            source_curves=sum(batch.get("border", {}).get("num_curves", 0) for batch in header["batches"]),
            indexed_triangles_including_padded_degenerates=sum(batch.get("count", 0) // 3 for batch in header["batches"]),
            wire_index_bytes=sum(4 * batch.get("index_count", 0) for batch in header["batches"] if not batch.get("cached")))
    if renderer is None:
        return result
    generated = getattr(renderer, "_generated_geometry", {})
    result.update(
        retained_gpu_fill_or_cpu_border_vertex_bytes=sum(item["buffer"].size for item in generated.values()),
        retained_gpu_index_bytes=sum(item["index_buffer"].size for item in generated.values() if "index_buffer" in item)
        + sum(buffer.size for item in generated.values() for buffer in item.get("index_buffers", {}).values()),
        retained_gpu_border_source_bytes=sum(item["buffer"].size for item in getattr(renderer, "_border_sources", {}).values()),
        retained_gpu_border_output_bytes=sum(item["buffer"].size for item in getattr(renderer, "_border_outputs", {}).values()),
        retained_gpu_uniform_bytes=sum(item[0].size for item in getattr(renderer, "_generated_uniforms", {}).values()),
        retained_winding_target_bytes=sum(8 * item["size"][0] * item["size"][1]
                                         for item in getattr(renderer, "_fill_targets", {}).values()),
        retained_winding_batch_buffer_bytes=sum(value.size for item in getattr(renderer, "batch_cache", {}).values()
                                               for value in item.values() if hasattr(value, "size") and hasattr(value, "destroy")))
    return result


def sample(scene, name, cache, stages, renderer=None, queue=None, transport=None):
    stages.reset()
    if queue is not None:
        queue.reset()
    route = "winding" if name == "original_2d" else "triangles"
    with patch.dict("os.environ", MANIML_BORDER_GENERATOR="gpu" if name == "gpu_border" else "cpu"):
        started = perf_counter()
        message = serialize_scene(scene, cache, renderer=route)
        serialized = perf_counter()
    transfer_ms = None
    if transport is not None:
        received, transfer_ms = transport.transfer(message)
        if received != message:
            raise RuntimeError("transport changed frame bytes")
        message = received
    before_parse = perf_counter()
    header, payload = parse_geometry_message(message)
    parsed = perf_counter()
    image = renderer.render(header, payload) if renderer is not None else None
    completed = perf_counter()
    stage = stages.milliseconds
    row = dict(prepare_ms=stage["geometry.triangle_prepare"] if route == "triangles" else sum(
        stage[key] for key in ("geometry.camera_uniforms", "geometry.collect_shader_data", "geometry.merge_batches", "geometry.fill_bounds")),
        wire_encode_ms=stage["geometry.triangle_encode"] if route == "triangles" else sum(
            stage[key] for key in ("geometry.pack_and_hash", "geometry.json_and_join")),
        serialize_ms=1000 * (serialized - started), parse_ms=1000 * (parsed - before_parse),
        **wire_metadata(message, header, payload),
        border_definition_bytes=sum(ref["nbytes"] for ref in header.get("border_data", {}).values()))
    if transfer_ms is not None:
        row["websocket_echo_roundtrip_ms"] = transfer_ms
    if renderer is not None:
        if queue.submissions != 1 or queue.reads != 1 or queue.read_size != (*header["resolution"], 1):
            raise RuntimeError("renderer changed the one-submit/full-frame-readback contract")
        if image.mode != "RGBA" or image.size != tuple(header["resolution"]):
            raise RuntimeError("incomplete rendered frame")
        row.update(render_cpu_encode_ms=1000 * (queue.submitted_at - parsed),
            submit_through_full_readback_ms=1000 * (queue.read_completed_at - queue.submitted_at),
            post_readback_ms=1000 * (completed - queue.read_completed_at),
            serialize_through_rgba_image_ms=1000 * (completed - started),
            full_readback_bytes=image.width * image.height * 4)
    row.update(resource_summary(renderer, cache, header))
    return row, image, header


def run_case(name, count, warmups, stages, output, *, cpu_only=False, transport=None,
             variants=VARIANTS):
    """``variants`` selects which renderers alternate per frame. Rotating all
    four puts each renderer's readbacks after three others' work; two alone
    is the comparison to trust when one renderer's completion looks slow."""
    from maniml.camera.native_gl_camera import NativeGLCamera
    from maniml.web.wgpu_renderer import WgpuRenderer
    from tests.winding_reference_renderer import WgpuRenderer as WindingRenderer

    variants = tuple(variants)
    built = {variant: build_case(name) for variant in variants}
    scenes = {variant: item[0] for variant, item in built.items()}
    metadata = built[variants[0]][1]
    initial = {variant: source_contract(scene) for variant, scene in scenes.items()}
    if len({contract[0] for contract in initial.values()}) != 1:
        raise RuntimeError("variant source bytes differ")
    base_points = {variant: [mob.get_points().copy() for mob in scene.mobjects]
                   for variant, scene in scenes.items()}
    renderers, queues, caches, native = {}, {}, {}, None
    for variant in variants:
        if variant == "native_gl":
            continue
        caches[variant] = GeometryCache()
        if not cpu_only:
            renderers[variant] = WindingRenderer() if variant == "original_2d" else WgpuRenderer()
            queues[variant] = QueueObserver(renderers[variant])
    rows, cold, comparisons = {variant: [] for variant in variants}, {}, []
    adapters = {variant: dict(renderer.device.adapter_info) for variant, renderer in renderers.items()}
    if not cpu_only and "native_gl" in variants:
        native = NativeGLCamera(resolution=scenes["native_gl"].camera.draw_fbo.size, samples=0)
        source_camera = scenes["native_gl"].camera
        native.background_rgba = list(source_camera.background_rgba)
        # B0's original packet uses a special24x12 projection. Copy the complete
        # already-validated source packet instead of guessing CameraFrame aspect.
        def refresh_reference():
            native.uniforms.clear()
            native.uniforms.update(deepcopy(source_camera.uniforms))
        native.refresh_uniforms = refresh_reference
        adapters["native_gl"] = {key: native.ctx.info[key] for key in ("GL_VENDOR", "GL_RENDERER", "GL_VERSION")}
    try:
        for iteration in range(warmups + count):
            index = max(0, iteration - warmups)
            pose, evaluated = {}, {}
            for variant, scene in scenes.items():
                start = perf_counter()
                pose[variant] = evaluate(scene, name, index, count, base_points[variant])
                evaluated[variant] = 1000 * (perf_counter() - start)
            if any(value != pose[variants[0]] for value in pose.values()):
                raise RuntimeError("variant cameras differ")
            expected = {variant: source_contract(scene) for variant, scene in scenes.items()}
            if len({contract[0] for contract in expected.values()}) != 1:
                raise RuntimeError("source evaluation differs across variants")
            if name != "changing_paths" and any(expected[v] != initial[v] for v in variants):
                raise RuntimeError("camera sequence changed authored source")
            offset = iteration % len(variants)
            order = variants[offset:] + variants[:offset]
            if iteration // len(variants) % 2:
                order = order[::-1]
            pictures, headers = {}, {}
            for variant in order:
                scene = scenes[variant]
                if variant == "native_gl":
                    row = {}
                    if native is not None:
                        start = perf_counter()
                        resize_gl(native, scene.camera.draw_fbo.size)
                        resized = perf_counter()
                        native.capture(*scene.render_groups)
                        captured = perf_counter()
                        pictures[variant] = native.get_image()
                        completed = perf_counter()
                        row = {"target_resize_ms": 1000 * (resized - start),
                            "capture_api_ms": 1000 * (captured - resized),
                            "capture_through_rgba_image_ms": 1000 * (completed - start),
                            "capture_return_through_full_readback_ms": 1000 * (completed - captured),
                            "full_readback_bytes": pictures[variant].width * pictures[variant].height * 4}
                        if geometry._jsonable(native.uniforms) != pose[variant]["camera"]:
                            raise RuntimeError("native GL reference camera packet differs")
                else:
                    row, picture, headers[variant] = sample(scene, variant, caches[variant], stages,
                        renderers.get(variant), queues.get(variant), transport)
                    if picture is not None:
                        pictures[variant] = picture
                if source_contract(scene) != expected[variant]:
                    raise RuntimeError(f"{variant} modified authored source/style/order")
                if geometry._jsonable(scene.camera.uniforms) != pose[variant]["camera"]:
                    raise RuntimeError(f"{variant} modified camera packet")
                row.update(source_evaluation_ms=evaluated[variant], frame=index, order=list(order),
                           source_sha256=expected[variant][0], resolution=pose[variant]["resolution"])
                if iteration == 0:
                    cold[variant] = row
                if iteration >= warmups:
                    rows[variant].append(row)
            if pictures and iteration >= warmups and "gpu_border" in pictures:
                comparison = {"frame": index}
                for label, other in (("gpu_vs_cpu", "cpu_border"), ("gpu_vs_original", "original_2d"),
                                     ("gpu_vs_native_gl", "native_gl")):
                    if other in pictures:
                        comparison[label] = difference(pictures[other], pictures["gpu_border"])
                comparisons.append(comparison)
                if index in (0, (count - 1) // 2, count - 1):
                    for variant, image in pictures.items():
                        filename = f"{name}_{index:02}_{variant}"
                        image.save(output / f"{filename}.png")
                        crop = (image.width // 4, image.height // 4, image.width * 3 // 4, image.height * 3 // 4)
                        image.crop(crop).save(output / f"{filename}_center_crop.png")
        result = {"source": metadata, "source_contract_preserved": True, "adapters": adapters,
                  "variants_in_rotation": list(variants),
                  "first_cold_frames_excluded_from_warmed_statistics": cold,
                  "per_frame_image_diagnostics": comparisons, "variants": {}}
        for variant in variants:
            result["variants"][variant] = {"samples": rows[variant], "timing_ms": {
                key: stats([row[key] for row in rows[variant]]) for key in rows[variant][0] if key.endswith("_ms")}}
            key = ("capture_return_through_full_readback_ms" if variant == "native_gl"
                   else "submit_through_full_readback_ms")
            if key in rows[variant][0]:
                result["variants"][variant]["readback_distribution"] = completion_distribution([row[key] for row in rows[variant]])
        return result
    finally:
        if native is not None:
            native.release()
        for queue in queues.values():
            queue.close()
        for renderer in renderers.values():
            if hasattr(renderer, "close"):
                renderer.close()
            else:
                renderer.device.destroy()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--samples", type=int, default=12)
    parser.add_argument("--warmups", type=int, default=3)
    parser.add_argument("--cases", nargs="+", choices=CASES, default=CASES)
    parser.add_argument("--cpu-only", action="store_true")
    parser.add_argument("--transport", action="store_true")
    parser.add_argument("--variants", nargs="+", choices=VARIANTS, default=list(VARIANTS),
                        help="renderers to alternate per frame; two alone isolates one renderer's completion time")
    args = parser.parse_args()
    if args.samples < 3 or args.warmups < 1:
        parser.error("samples must be >=3 and warmups >=1")
    args.output.mkdir(parents=True, exist_ok=True)
    paths = [Path(__file__), *Path("maniml/web").glob("*.py"), *Path("maniml/web/static/wgsl").glob("*.wgsl"),
             *Path("maniml/rendering").rglob("*.py"), *Path("maniml/rendering/shaders").rglob("*.glsl"),
             *Path("tests/winding_reference_wgsl").glob("*.wgsl"),
             *[Path(name) for name in (
                 "maniml/camera/native_gl_camera.py", "tests/winding_reference_renderer.py",
                 "tests/winding_reference_geometry.py", "tests/renderer_fixtures.py",
                 "tests/renderer_quality_fixtures.py", "tests/test_fill_bounds.py",
                 "benchmarks/generated_output.py", "benchmarks/paint_retention.py",
                 "benchmarks/renderer_timing.py", "benchmarks/renderer_transport.py",
                 "benchmarks/triangle_wordmark.py", "benchmarks/vector_fill.py")]]
    hashes = {str(path): sha256(path.read_bytes()).hexdigest() for path in paths}
    report = {"recorded_utc": datetime.now(timezone.utc).isoformat(), "platform": platform.platform(),
        "python": platform.python_version(), "cpu_only": args.cpu_only, "transport": args.transport,
        "source_files_sha256": hashes, "samples": args.samples, "warmups": args.warmups,
        "aa": "GPU/CPU borders share production4MSAA+2x spatial resolve. Original2D uses the shipped winding serializer plus frozen native WebGPU mirror; native GL uses the packaged NativeGLCamera. Both historical references retain samples0 plus their historical internal AA.",
        "timing_scope": "Fresh sources/devices/caches per case/variant. Cold first frame archived separately, then excluded warmups. Rotated/reversed order, full RGBA readback/PIL image construction per measured frame. Source evaluation is separately timed and excluded from rendering total. Source checks, retained memory summaries, pixel comparisons and PNG writes are outside timings. WebGPU render CPU ends at queue.submit; completion includes GPU work/host waiting/polling/mapping and resource retirement, not GPU timestamps. GL capture may block; its capture-return/readback split is not the WebGPU submission split. Native GL has no wire. Component medians must not be added.",
        "transport_scope": "Optional real uncompressed localhost WebSocket echo roundtrip after serialization and before parse. Two wire traversals, not one-way delivery or browser presentation; byte equality checked. No stage for native GL.",
        "native_gl_camera_adapter": "All reference captures inject the exact source camera packet through refresh_uniforms, including original B0's24x12 projection. Resize case reallocates/retire only camera targets via existing allocation helpers inside measured time; keeps context and wrappers.",
        "memory_scope": "Post-completion retained arrays/buffers. GPU border output includes copied fill prefix; separate fill source buffer remains retained. Winding history/target retention follows frozen reference; generated active-frame retirement occurs before readback, winding target retirement after readback. No peak RSS, staging buffers, native helper scratch or driver allocation overhead. Native GL buffer byte counts unavailable.",
        "draw_counts": "Generated scene/resolve counts derived from the exact driver loop, excluding compute and readback commands. Indexed triangle counts include padded degenerate slots. Historical native draw counts unavailable here; B0 Original135logical batches confirmed by fixture.",
        "image_scope": "Every matching-pose frame compared outside timing; PNG endpoints/midpoint and center-half crops are diagnostics, no acceptance threshold implied. Historical reference alpha/paint/AA semantics may differ. Raw attachment RGBA preserved; opaque backgrounds keep displayed RGB straightforward.",
        "cases": {}}
    stages = StageObserver()
    with ExitStack() as stack:
        stack.enter_context(patch.object(geometry, "performance", stages))
        stack.enter_context(patch.object(winding_geometry, "performance", stages))
        transport = None
        if args.transport:
            from benchmarks.renderer_transport import LoopbackTransport
            transport = stack.enter_context(LoopbackTransport())
        for name in args.cases:
            report["cases"][name] = run_case(name, args.samples, args.warmups, stages, args.output,
                                            cpu_only=args.cpu_only, transport=transport,
                                            variants=args.variants)
            report["source_files_unchanged_during_run"] = all(sha256(Path(path).read_bytes()).hexdigest() == value for path, value in hashes.items())
            (args.output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
            print(name, "complete", flush=True)


if __name__ == "__main__":
    main()

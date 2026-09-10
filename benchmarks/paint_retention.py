"""Large static paint fields: wire retention, full readback cost, and appearance.

Run with ``python -m benchmarks.paint_retention --output /private/tmp/paint``.
The CPU-only mode checks source/paint retention without allocating a GPU.
This compares different documented interior paint semantics, not parity gates.
"""

import argparse
from contextlib import ExitStack
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import platform
import struct
from time import perf_counter
from unittest.mock import patch

import numpy as np

from benchmarks.generated_output import QueueObserver, StageObserver
from benchmarks.renderer_timing import completion_distribution
from maniml.constants import BLUE, GREEN, RED
from maniml.mobject.geometry import RegularPolygon
from maniml.web import geometry, triangle_scene, winding_geometry
from maniml.web.geometry import GeometryCache, parse_geometry_message, serialize_scene
from tests.renderer_fixtures import build_scene


VARIANTS = ("triangles", "winding", "native_gl")
RESOLUTION = (960, 540)
ROI = (336, 126, 624, 414)
SOURCE_FIELDS = ("point", "fill_rgba", "fill_border_width", "stroke_rgba", "stroke_width")


def source_scene(kind):
    shape = RegularPolygon(n=400, radius=2, stroke_width=0, fill_border_width=0)
    if kind == "nonaffine":
        shape.set_fill([RED, GREEN, BLUE], opacity=1)
    else:
        shape.set_fill(opacity=1)
        x, y = shape.get_points()[:, :2].T
        shape.data["fill_rgba"] = np.column_stack((
            .5 + .2 * x, .5 + .2 * y, .5 - .1 * x + .07 * y, np.ones(len(x))))
    scene = build_scene(shape, resolution=RESOLUTION, samples=0)
    scene.camera.refresh_uniforms()
    return scene


def source_digest(scene):
    identity = sha256()
    for shape in scene.mobjects:
        for name in SOURCE_FIELDS:
            array = np.ascontiguousarray(shape.data[name])
            identity.update(name.encode() + str(array.dtype).encode())
            identity.update(np.asarray(array.shape, dtype="<u4").tobytes())
            identity.update(array.tobytes())
        identity.update(json.dumps(shape.uniforms, sort_keys=True, default=geometry._jsonable).encode())
    return identity.hexdigest()


def field_metadata(cache):
    field = next(iter(cache.triangle_meshes._entries.values())).paint_field
    flat = field.data.reshape(-1)
    return {"mode": "inverse_distance" if flat[11] else "spline_or_affine",
            "node_count": int(flat[7]), "coefficient_floats": len(flat),
            "coefficient_bytes": flat.nbytes}


def wire_metadata(message, header, payload):
    return {"message_bytes": len(message), "header_bytes": struct.unpack_from("<I", message, 1)[0],
            "payload_bytes": len(payload), "batches": len(header["batches"]),
            "cached_batches": sum(bool(batch.get("cached")) for batch in header["batches"]),
            "inline_paint_json_bytes": sum(len(json.dumps(batch["paint"]).encode())
                                           for batch in header["batches"] if "paint" in batch),
            "paint_definition_bytes": sum(ref["nbytes"] for ref in header.get("paint_data", {}).values())}


def wire_sample(scene, variant, cache, stages):
    stages.reset()
    started = perf_counter()
    message = serialize_scene(scene, cache, renderer=variant)
    serialized = perf_counter()
    header, payload = parse_geometry_message(message)
    parsed = perf_counter()
    ms = stages.milliseconds
    prepare = ms["geometry.triangle_prepare"] if variant == "triangles" else sum(
        ms[key] for key in ("geometry.camera_uniforms", "geometry.collect_shader_data",
                           "geometry.merge_batches", "geometry.fill_bounds"))
    wire = ms["geometry.triangle_encode"] if variant == "triangles" else sum(
        ms[key] for key in ("geometry.pack_and_hash", "geometry.json_and_join"))
    return message, header, payload, {"prepare_ms": prepare, "wire_ms": wire,
        "serialize_ms": 1000 * (serialized - started), "parse_ms": 1000 * (parsed - serialized),
        **wire_metadata(message, header, payload)}, started, parsed


def cpu_control(kind, stages):
    scene, cache = source_scene(kind), GeometryCache()
    before = source_digest(scene)
    rows = []
    original = triangle_scene.build_paint
    with patch.object(triangle_scene, "build_paint", wraps=original) as builder:
        for _ in range(2):
            _, header, _, row, _, _ = wire_sample(scene, "triangles", cache, stages)
            rows.append({**row, "coefficient_build_calls_total": builder.call_count,
                         "frame_limitations": header.get("limitations", [])})
    assert source_digest(scene) == before
    return {"source_sha256": before, "source_point_count": len(scene.mobjects[0].get_points()),
            **field_metadata(cache), "first_and_second_frames": rows}


def stats(values):
    data = np.asarray(values, dtype=float)
    return {"min": float(data.min()), "p50": float(np.median(data)),
            "p95": float(np.percentile(data, 95)), "max": float(data.max())}


def difference(reference, image):
    delta = np.abs(np.asarray(reference, dtype=float) - np.asarray(image, dtype=float))
    return {"mean_rgb": float(delta[..., :3].mean()),
            "fraction_pixels_rgb_over24": float((delta[..., :3].max(axis=-1) > 24).mean()),
            "max_rgba": float(delta.max()), "mean_alpha": float(delta[..., 3].mean())}


def affine_interior_probe(pictures, scene):
    """Compare pixel centers with the authored XY formula, excluding boundaries."""
    width, height = RESOLUTION
    xs, ys = np.meshgrid(np.arange(width), np.arange(height))
    x = ((xs + .5) / width - .5) * scene.camera.frame.get_width()
    y = (.5 - (ys + .5) / height) * scene.camera.frame.get_height()
    selected = x * x + y * y < 1.7 ** 2
    expected = 255 * np.column_stack((.5 + .2 * x[selected], .5 + .2 * y[selected],
                                     .5 - .1 * x[selected] + .07 * y[selected]))
    variants = {}
    for name, picture in pictures.items():
        error = np.abs(np.asarray(picture, dtype=float)[selected, :3] - expected)
        variants[name] = {"mean_rgb_error_255": float(error.mean()),
                          "max_rgb_error_255": float(error.max())}
    return {"scope": "Pixel-center affine XY RGB within radius1.7; excludes boundary AA. "
                     "This tests the declared spatial field, not equivalence to winding-fan paint.",
            "pixels": int(selected.sum()), "variants": variants}


def gpu_control(kind, count, warmups, stages, output):
    from maniml.camera.native_gl_camera import NativeGLCamera
    from maniml.web.wgpu_renderer import WgpuRenderer
    from tests.winding_reference_renderer import WgpuRenderer as WindingRenderer

    scenes = {name: source_scene(kind) for name in VARIANTS}
    contracts = {name: source_digest(scene) for name, scene in scenes.items()}
    assert len(set(contracts.values())) == 1
    native = NativeGLCamera(resolution=RESOLUTION, samples=0)
    source_camera = scenes["native_gl"].camera
    native.frame = source_camera.frame.copy()
    native.background_rgba = source_camera.background_rgba.copy()
    native.light_source.move_to(source_camera.light_source.get_location())
    native.refresh_uniforms()
    assert geometry._jsonable(native.uniforms) == geometry._jsonable(source_camera.uniforms)
    renderers = {"triangles": WgpuRenderer(), "winding": WindingRenderer()}
    queues = {name: QueueObserver(renderer) for name, renderer in renderers.items()}
    caches = {name: GeometryCache() for name in renderers}
    rows, pictures = {name: [] for name in VARIANTS}, {}
    gl_info = {key: native.ctx.info[key] for key in ("GL_VENDOR", "GL_RENDERER", "GL_VERSION")}
    adapters = {name: dict(renderer.device.adapter_info) for name, renderer in renderers.items()}
    try:
        for iteration in range(warmups + count):
            offset = iteration % len(VARIANTS)
            order = VARIANTS[offset:] + VARIANTS[:offset]
            if iteration // len(VARIANTS) % 2:
                order = order[::-1]
            for name in order:
                scene = scenes[name]
                if name == "native_gl":
                    started = perf_counter()
                    native.capture(*scene.render_groups)
                    captured = perf_counter()
                    pictures[name] = native.get_image()
                    completed = perf_counter()
                    row = {"capture_api_ms": 1000 * (captured - started),
                           "completion_full_readback_ms": 1000 * (completed - captured),
                           "total_to_rgba_image_ms": 1000 * (completed - started)}
                else:
                    queue = queues[name]
                    queue.reset()
                    _, header, payload, row, started, parsed = wire_sample(scene, name, caches[name], stages)
                    pictures[name] = renderers[name].render(header, payload)
                    completed = perf_counter()
                    assert queue.submissions == queue.reads == 1
                    assert queue.read_size == (*RESOLUTION, 1)
                    row.update(render_cpu_encode_ms=1000 * (queue.submitted_at - parsed),
                               completion_full_readback_ms=1000 * (queue.read_completed_at - queue.submitted_at),
                               post_readback_ms=1000 * (completed - queue.read_completed_at),
                               total_to_rgba_image_ms=1000 * (completed - started))
                row.update(iteration=iteration, order=list(order), full_readback_bytes=4 * np.prod(RESOLUTION).item())
                assert source_digest(scene) == contracts[name]
                if iteration >= warmups:
                    rows[name].append(row)
        result = {"source_contract_preserved": True, "gl": gl_info, "adapters": adapters, "variants": {}}
        for name in VARIANTS:
            pictures[name].save(output / f"{kind}_{name}.png")
            pictures[name].crop(ROI).save(output / f"{kind}_{name}_crop.png")
            result["variants"][name] = {"samples": rows[name],
                "timing_ms": {key: stats([row[key] for row in rows[name]])
                              for key in rows[name][0] if key.endswith("_ms")},
                "completion_distribution": completion_distribution([row["completion_full_readback_ms"] for row in rows[name]])}
        result["appearance"] = {name: {
            "full_frame_vs_native_gl": difference(pictures["native_gl"], pictures[name]),
            "crop_vs_native_gl": difference(pictures["native_gl"].crop(ROI), pictures[name].crop(ROI)),
            "image": f"{kind}_{name}.png", "crop": f"{kind}_{name}_crop.png"}
            for name in VARIANTS}
        if kind == "affine":
            result["affine_interior_probe"] = affine_interior_probe(pictures, scenes["triangles"])
        return result
    finally:
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
    parser.add_argument("--cpu-only", action="store_true")
    args = parser.parse_args()
    if args.samples < 1 or args.warmups < 0:
        parser.error("samples must be positive and warmups nonnegative")
    args.output.mkdir(parents=True, exist_ok=True)
    stages = StageObserver()
    paths = ["benchmarks/paint_retention.py", "maniml/web/generated_geometry.py",
             "maniml/web/triangle_scene.py", "maniml/web/fill_paint.py", "maniml/web/wgpu_renderer.py",
             "maniml/web/winding_geometry.py", "maniml/camera/native_gl_camera.py",
             "maniml/rendering/shader_wrapper.py", "tests/winding_reference_renderer.py",
             "maniml/web/static/wgsl/paint.wgsl"]
    hashes = {name: sha256(Path(name).read_bytes()).hexdigest() for name in paths}
    report = {"recorded_utc": datetime.now(timezone.utc).isoformat(), "platform": platform.platform(),
        "python": platform.python_version(), "numpy": np.__version__, "source_files_sha256": hashes,
        "resolution": RESOLUTION, "roi_output_pixels": ROI, "samples": args.samples, "warmups": args.warmups,
        "source": "400-corner radius2 polygon; zero stroke/border, static source/camera, opaque background. Non-affine point colors RED→GREEN→BLUE; affine RGB is linear in source XY. Alpha1 for both.",
        "aa": "Original winding and native GL retain samples0 and historical shader AA. Phase A uses its public4MSAA+2x spatial resolve default.",
        "timing_scope": "WebGPU total: public serialization, parsing, render, full RGBA readback and PIL construction. Native GL total: public capture then get_image including blit/full RGBA readback. GL has no geometry wire. Completion intervals include GPU work, host waits/driver polling and mapping; not GPU timestamps. GL capture may itself block, so component intervals are not equivalent across APIs. Source construction, source verification, file writes and diagnostics are outside timing. No transport/browser/presentation measured. Per-renderer fresh sources/devices/caches;3 warmups by default; rotated/reversed variant order.",
        "appearance_scope": "Diagnostic differences only: source paint interior semantics differ. No parity acceptance label or threshold.",
        "cases": {}}
    with ExitStack() as stack:
        stack.enter_context(patch.object(geometry, "performance", stages))
        stack.enter_context(patch.object(winding_geometry, "performance", stages))
        for kind in ("nonaffine", "affine"):
            case = {"cpu": cpu_control(kind, stages)}
            if not args.cpu_only:
                case["gpu"] = gpu_control(kind, args.samples, args.warmups, stages, args.output)
            report["cases"][kind] = case
            print(kind, "complete", flush=True)
    report["source_files_unchanged_during_run"] = all(sha256(Path(name).read_bytes()).hexdigest() == value for name, value in hashes.items())
    (args.output / "report.json").write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()

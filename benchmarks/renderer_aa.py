"""Compare shared AA policies with preserved GL goldens and area references.

The convergence reference supersamples the same generated mesh, so it isolates
raster coverage; it does not independently validate curve tessellation/paint.
The small triangle control uses exact polygon/pixel intersection areas instead.
"""

import argparse
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
from time import perf_counter

import numpy as np
from PIL import Image

from benchmarks.renderer_quality import difference_metrics, read_native, source_contract
from maniml.web.generated_geometry import serialize_generated_frame
from maniml.web.geometry import SURFACE_DTYPE, parse_geometry_message
from maniml.web.triangle_geometry import LyonFillTessellator
from maniml.web.triangle_scene import TriangleDraw, TriangleFrame, TriangleMeshCache, prepare_triangle_frame
from maniml.web.wgpu_renderer import WgpuRenderer
from tests.renderer_quality_fixtures import quality_cases


POLICIES = (("msaa4", 1, 4), ("ss2", 2, 1), ("ss2_msaa4", 2, 4))


def exact_triangle_coverage(triangle, size):
    """Area of each unit pixel intersecting a triangle, via convex clipping."""
    output = np.zeros((size[1], size[0]))
    for y in range(size[1]):
        for x in range(size[0]):
            polygon = list(np.asarray(triangle, dtype=float))
            for axis, edge, sign in ((0, x, 1), (0, x + 1, -1), (1, y, 1), (1, y + 1, -1)):
                clipped = []
                if not polygon:
                    break
                for a, b in zip(polygon, [*polygon[1:], polygon[0]]):
                    da, db = sign * (a[axis] - edge), sign * (b[axis] - edge)
                    if da >= 0:
                        clipped.append(a)
                    if (da >= 0) != (db >= 0):
                        clipped.append(a + da / (da - db) * (b - a))
                polygon = clipped
            if polygon:
                points = np.asarray(polygon)
                following = np.roll(points, -1, axis=0)
                output[y, x] = abs(np.sum(points[:, 0] * following[:, 1]
                                          - points[:, 1] * following[:, 0])) / 2
    return output


def area_control(renderer):
    size = (64, 40)
    camera = {"view": np.eye(4).reshape(-1).tolist(), "frame_rescale_factors": [1, 1, 0],
              "camera_position": [0, 0, 10], "light_position": [0, 0, 10]}
    result = {name: [] for name, _, _ in POLICIES}
    for shift in (0., .17, .39, .71):
        pixels = np.array([[13.2, 7.15], [48.7, 15.43], [20.6, 30.81]]) + [shift, .31 * shift]
        vertices = np.zeros(3, dtype=SURFACE_DTYPE)
        vertices["point"][:, :2] = (pixels / size * 2 - 1) * [1, -1]
        vertices["d_normal_point"] = vertices["point"] + [0, 0, .001]
        vertices["rgba"] = 1
        # Match the actual float32 positions consumed by the rasterizer.
        pixels = (vertices["point"][:, :2].astype(float) * [1, -1] + 1) * size / 2
        coverage = exact_triangle_coverage(pixels, size)
        frame = TriangleFrame(size, (0, 0, 0, 0), 4,
                              [TriangleDraw("surface", vertices, camera, count=3)])
        header, raw = parse_geometry_message(serialize_generated_frame(frame, camera))
        for name, scale, samples in POLICIES:
            header.update(supersample=scale, samples=samples)
            alpha = np.asarray(renderer.render(header, raw), dtype=float)[..., 3] / 255
            error = abs(alpha - coverage)
            result[name].append({"shift_pixels": shift, "rms_coverage_error": float(np.sqrt(np.mean(error ** 2))),
                                 "mean_coverage_error": float(error.mean()), "max_coverage_error": float(error.max())})
    return result


def convergence_reference(renderer, header, raw, box, scale):
    x, y, right, bottom = box
    width, height = right - x, bottom - y
    frame_width, frame_height = header["resolution"]
    high = deepcopy(header)
    high.update(resolution=[width * scale, height * scale], samples=1, supersample=1)
    for batch in high["batches"]:
        uniforms = {**header["camera"], **batch["uniforms"]}
        batch["uniforms"] = {**batch["uniforms"],
            "pixel_size": uniforms.get("pixel_size", 1) / scale,
            "anti_alias_width": uniforms.get("anti_alias_width", 1.5) * scale,
            "clip_transform": [frame_width / width, frame_height / height,
                               (frame_width - 2 * x - width) / width,
                               (2 * y + height - frame_height) / height]}
    image = np.asarray(renderer.render(high, raw), dtype=float)
    return image.reshape(height, scale, width, scale, 4).mean(axis=(1, 3))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--samples", type=int, default=5)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    golden_dir = Path(__file__).parents[1] / "tests/goldens/triangle_renderer"
    manifest = json.loads((golden_dir / "manifest.json").read_text())
    renderer, tessellator = WgpuRenderer(), LyonFillTessellator()
    results = {}
    for case in quality_cases():
        quality = case.build()
        native = read_native(quality, golden_dir, manifest)
        contract = source_contract(quality)
        frame = prepare_triangle_frame(quality.scene, tessellator, mesh_cache=TriangleMeshCache(), fill_borders=True)
        header, raw = parse_geometry_message(serialize_generated_frame(frame, quality.scene.camera.uniforms))
        timings, pictures = {name: [] for name, _, _ in POLICIES}, {}
        for iteration in range(args.samples + 2):
            order = POLICIES[iteration % 3:] + POLICIES[:iteration % 3]
            for name, scale, samples in order:
                candidate = {**header, "samples": samples, "supersample": scale}
                started = perf_counter()
                pictures[name] = renderer.render(candidate, raw)
                if iteration >= 2:
                    timings[name].append(1000 * (perf_counter() - started))
        values = {name: {"vs_native": difference_metrics(native, picture),
                         "regions": {roi.name: difference_metrics(native.crop(roi.box), picture.crop(roi.box), scope="region")
                                     for roi in quality.rois}, "driver_full_readback_ms": timings[name]}
                  for name, picture in pictures.items()}
        for name, scale, samples in POLICIES:
            # depth24plus-stencil8 allocation is implementation-dependent; four bytes
            # per sample is the same nominal accounting used by the A0 report.
            layers = scale * scale * (2 * samples + int(samples > 1)) + int(scale > 1)
            values[name]["nominal_target_bytes"] = int(np.prod(frame.resolution)) * 4 * layers
        values["geometry"] = {"draws": len(frame.draws), "array_bytes": frame.geometry_bytes,
                              "retained_cpu_bytes": frame.mesh_cache_stats["retained_bytes"]}
        for name, picture in pictures.items():
            picture.save(args.output / f"{case.name}_{name}.png")
        if case.name.startswith("tex_") and case.border_policy == "zero_for_aa":
            box = next(roi.box for roi in quality.rois if roi.name == "paragraph")
            ref8 = convergence_reference(renderer, header, raw, box, 8)
            ref16 = convergence_reference(renderer, header, raw, box, 16)
            values["coverage_reference"] = {"region": list(box), "8x_vs_16x": difference_metrics(ref16, ref8, scope="region"),
                "policies_vs_16x": {name: difference_metrics(ref16, picture.crop(box), scope="region") for name, picture in pictures.items()},
                "native_vs_16x": difference_metrics(ref16, native.crop(box), scope="region")}
            Image.fromarray(np.rint(ref16).astype("u1")).save(args.output / f"{case.name}_paragraph_reference16.png")
        if source_contract(quality) != contract:
            raise RuntimeError("AA comparison mutated source arrays or camera metadata")
        results[case.name] = values
        print(case.name, {name: round(values[name]["vs_native"]["fraction_rgb_over_24"] * 100, 3)
                          for name, _, _ in POLICIES}, flush=True)
    report = {"timing_scope": "Driver encoding, submission, full RGBA readback and PIL creation; source preparation/serialization excluded; two warmups; policy order rotates",
              "coverage_scope": "16x paragraph reference reuses identical generated geometry/paint and only tests sampling convergence. Exact triangle control independently clips each unit pixel.",
              "quality": results, "exact_area_control": area_control(renderer),
              "code_sha256": {str(path): sha256(path.read_bytes()).hexdigest() for path in (
                  Path(__file__), Path(__file__).parents[1] / "maniml/web/wgpu_renderer.py",
                  Path(__file__).parents[1] / "maniml/web/static/wgsl/resolve2.wgsl")}}
    renderer.close()
    (args.output / "report.json").write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()

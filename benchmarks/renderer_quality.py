"""A0 native-GL goldens and local text/border antialiasing comparisons.

Run from the worktree with the optional Lyon and locked WebGPU dependencies:
    python -m benchmarks.renderer_quality --output /tmp/renderer-quality \
        --goldens tests/goldens/triangle_renderer --capture-native --samples 5

Capture is explicit. Subsequent runs check source/camera metadata against the
saved goldens; missing or changed references fail rather than silently update.
"""

import argparse
from contextlib import contextmanager
from hashlib import sha256
import json
from pathlib import Path
from statistics import median
import subprocess
from time import perf_counter
from types import SimpleNamespace

import numpy as np
from PIL import Image, ImageDraw

from benchmarks.ordered_output import OrderedOutputControl
from benchmarks.renderer_timing import COMPLETION_SCOPE, completion_distribution
from benchmarks.triangle_renderer import TrianglePrototype, baseline_frame, environment_metadata
from benchmarks.triangle_scene import TriangleMeshCache, UnsupportedPrototype, prepare_triangle_frame
from maniml.camera.camera import Camera
from maniml.mobject.types.vectorized_mobject import VMobject
from maniml.web.geometry import _jsonable, parse_geometry_message, serialize_scene
from maniml.web.triangle_geometry import LyonFillTessellator
from maniml.web.wgpu_renderer import WgpuRenderer
from tests.renderer_quality_fixtures import quality_cases


def source_contract(quality):
    quality.scene.camera.refresh_uniforms()
    live = sha256()
    for group in quality.scene.render_groups:
        live.update(b"render_group\0")
        for obj in sorted(group.family_members_with_points(), key=lambda obj: obj.z_index):
            if not isinstance(obj, VMobject):
                raise TypeError("quality golden contract currently covers VMobject sources only")
            live.update(json.dumps({
                "type": type(obj).__module__ + "." + type(obj).__qualname__,
                "uniforms": obj.uniforms, "depth_test": obj.depth_test,
                "stroke_behind": obj.stroke_behind, "z_index": obj.z_index,
                "contour_ends": obj.get_subpath_end_indices_from_points(obj.get_points()),
            }, sort_keys=True, default=_jsonable).encode())
            for name in ("point", "fill_rgba", "fill_border_width", "stroke_rgba", "stroke_width"):
                array = np.asarray(obj.data[name], dtype="<f4")
                live.update(name.encode() + np.asarray(array.shape, dtype="<u4").tobytes())
                live.update(array.tobytes())
    return json.loads(json.dumps({
        "fixture": quality.metadata, "camera": quality.scene.camera.uniforms,
        "output": {"resolution": quality.scene.camera.draw_fbo.size,
                   "samples": quality.scene.camera.samples,
                   "background_rgba": quality.scene.camera.background_rgba},
        "live_source_and_draw_sha256": live.hexdigest(),
        "rois": {roi.name: list(roi.box) for roi in quality.rois}}, default=_jsonable))


def capture_native(frames, directory):
    """Capture actual native GL before allocating any WebGPU devices."""
    directory.mkdir(parents=True, exist_ok=True)
    manifest_path = directory / "manifest.json"
    existing = json.loads(manifest_path.read_text()) if manifest_path.exists() else {"cases": {}}
    for quality in frames:
        name = quality.name
        if name in existing["cases"]:
            if existing["cases"][name]["source_contract"] != source_contract(quality):
                raise ValueError(f"native golden source changed: {name}; choose a new golden directory")
            continue
        source = quality.scene.camera
        camera = Camera(resolution=tuple(source.draw_fbo.size), samples=source.samples)
        camera.frame = source.frame.copy()
        camera.background_rgba = list(source.background_rgba)
        camera.light_source = source.light_source.copy()
        camera.capture(*quality.scene.render_groups)
        image = camera.get_image()
        filename = name + ".png"
        image.save(directory / filename)
        existing["cases"][name] = {
            "source_contract": source_contract(quality), "image": filename,
            "sha256": sha256((directory / filename).read_bytes()).hexdigest(),
            "gl": {key: camera.ctx.info[key] for key in
                   ("GL_VENDOR", "GL_RENDERER", "GL_VERSION")},
        }
        manifest_path.write_text(json.dumps(existing, indent=2) + "\n")
        print("native", name, flush=True)
    return existing


def read_native(quality, directory, manifest):
    record = manifest["cases"][quality.name]
    if record["source_contract"] != source_contract(quality):
        raise ValueError(f"native golden source changed: {quality.name}")
    path = directory / record["image"]
    if sha256(path.read_bytes()).hexdigest() != record["sha256"]:
        raise ValueError(f"native golden checksum changed: {quality.name}")
    return Image.open(path).convert("RGBA")


@contextmanager
def supersampled_scene(scene, scale=2):
    """Preserve authored widths and AA width in final-output pixels.

    Physical stroke width already uses scene/frame units. pixel_size shrinks
    with the larger target, so anti_alias_width scales to retain its final
    pixel footprint. The fill geometric budget is scaled separately by caller.
    """
    camera = scene.camera
    old_fbo, old_draw = camera.fbo, camera.draw_fbo
    old_samples = camera.samples
    changed = []
    try:
        camera.fbo = camera.draw_fbo = SimpleNamespace(
            size=tuple(scale * value for value in old_draw.size))
        camera.samples = 0
        seen = set()
        for group in scene.render_groups:
            for obj in group.get_family():
                if id(obj) in seen or "anti_alias_width" not in obj.uniforms:
                    continue
                seen.add(id(obj))
                value = obj.uniforms["anti_alias_width"]
                changed.append((obj, value))
                obj.uniforms["anti_alias_width"] = value * scale
        yield
    finally:
        camera.fbo, camera.draw_fbo, camera.samples = old_fbo, old_draw, old_samples
        for obj, value in changed:
            obj.uniforms["anti_alias_width"] = value
        camera.refresh_uniforms()


def difference_metrics(reference, candidate, *, scope="full_frame"):
    if scope not in ("full_frame", "region"):
        raise ValueError("metric scope must be full_frame or region")
    difference = np.abs(np.asarray(reference, dtype=float) - np.asarray(candidate, dtype=float))
    rgb = difference[..., :3]
    mean = float(rgb.mean())
    fraction = float((rgb.max(axis=-1) > 24).mean())
    metrics = {"mean_rgb_difference": mean, "fraction_rgb_over_24": fraction,
            "max_rgba_difference": float(difference.max()),
            "mean_alpha_difference": float(difference[..., 3].mean()),
            "scope": scope}
    if scope == "full_frame":
        metrics["existing_rgb_threshold_met"] = mean < 1.5 and fraction < 0.005
    return metrics


def _save_picture(directory, name, image):
    # These fixtures have opaque backgrounds. Compare/render attachment RGB
    # directly so the baseline's known alpha defect does not alter previews.
    image.convert("RGB").save(directory / (name + ".png"))


def save_comparison(quality, pictures, directory):
    case_dir = directory / quality.name
    case_dir.mkdir(parents=True, exist_ok=True)
    for name, picture in pictures.items():
        _save_picture(case_dir, name, picture)
    metrics = {}
    for name, picture in pictures.items():
        if name == "native_gl":
            continue
        metrics[name] = {"full_frame": difference_metrics(pictures["native_gl"], picture),
                         "rois": {roi.name: difference_metrics(
                             pictures["native_gl"].crop(roi.box), picture.crop(roi.box), scope="region")
                                  for roi in quality.rois}}
    # Every crop gets its own magnified comparison. Nearest-neighbor enlargement
    # shows the actual output pixels; no sharpening or interpolation is applied.
    for roi in quality.rois:
        crops = [(name, picture.crop(roi.box).convert("RGB")) for name, picture in pictures.items()]
        scale = max(1, min(4, 1400 // max(1, crops[0][1].width)))
        width, height = crops[0][1].size
        sheet = Image.new("RGB", (width * scale, len(crops) * (height * scale + 25)), "#17202a")
        painter = ImageDraw.Draw(sheet)
        for index, (name, crop) in enumerate(crops):
            y = index * (height * scale + 25)
            painter.text((4, y + 5), name, fill="white")
            sheet.paste(crop.resize((width * scale, height * scale), Image.Resampling.NEAREST), (0, y + 25))
        sheet.save(case_dir / (roi.name + "_comparison.png"))
    return metrics


class QualityRunner:
    def __init__(self, tessellator):
        self.tessellator = tessellator
        self.current = WgpuRenderer()
        self.ordered = OrderedOutputControl()
        self.flat = TrianglePrototype()
        self.supersampled = TrianglePrototype()
        self.analytic = TrianglePrototype()
        self.caches = {"flat_msaa4": TriangleMeshCache(), "flat_ss2": TriangleMeshCache()}
        from benchmarks.analytic_scene import AnalyticMeshCache
        self.analytic_cache = AnalyticMeshCache()
        self.names = ("current_webgpu", "ordered_output", "flat_msaa4", "flat_ss2", "analytic_msaa4")

    def frame(self, quality, name, *, image=False):
        scene = quality.scene
        started = perf_counter()
        if name in ("current_webgpu", "ordered_output"):
            header, data = parse_geometry_message(serialize_scene(scene))
            prepared = perf_counter()
            if header["unsupported"]:
                raise UnsupportedPrototype(str(header["unsupported"]))
            if name == "current_webgpu":
                measurement = baseline_frame(self.current, header, data)
                picture = self.current.render(header, data) if image else None
            else:
                picture, measurement = self.ordered.frame(header, data, image=image)
            limitations = []
        else:
            cache_stats = {}
            output_resolution = None
            if name == "flat_ss2":
                output_resolution = tuple(scene.camera.draw_fbo.size)
                with supersampled_scene(scene):
                    frame = prepare_triangle_frame(scene, self.tessellator, diagnostic=True,
                                                   pixel_tolerance=0.5, mesh_cache=self.caches[name])
                renderer = self.supersampled
            elif name == "flat_msaa4":
                frame = prepare_triangle_frame(scene, self.tessellator, diagnostic=True,
                                               mesh_cache=self.caches[name])
                frame.samples = 4
                renderer = self.flat
            else:
                from benchmarks.analytic_scene import prepare_analytic_frame
                frame = prepare_analytic_frame(scene, diagnostic=True, cache=self.analytic_cache)
                frame.samples = 4
                renderer = self.analytic
            cache_stats = frame.mesh_cache_stats
            prepared = perf_counter()
            picture, measurement = renderer.frame(frame, image=image, output_resolution=output_resolution)
            measurement["mesh_cache"] = cache_stats
            limitations = frame.limitations
        # Image-producing calls are diagnostics only; warm timings always use
        # image=False and include all preparation, allocation and retirement.
        measurement.update({"prepare_ms": 1000 * (prepared - started),
                            "cpu_prepare_through_completion_ms": 1000 * (perf_counter() - started),
                            "limitations": limitations})
        return picture, measurement


def compare_quality(quality, native, runner, samples, directory):
    from benchmarks.analytic_geometry import UnsupportedAnalyticGeometry
    measurements = {name: [] for name in runner.names}
    rejected = {}
    for iteration in range(samples + 2):
        names = list(runner.names)
        names = names[iteration % len(names):] + names[:iteration % len(names)]
        for name in names:
            if name in rejected:
                continue
            try:
                _, measurement = runner.frame(quality, name)
            except (UnsupportedPrototype, UnsupportedAnalyticGeometry) as exc:
                rejected[name] = str(exc)
                continue
            if iteration >= 2:
                measurements[name].append(measurement)
    pictures = {"native_gl": native}
    variants = {}
    for name in runner.names:
        if name in rejected:
            variants[name] = {"status": "rejected", "reason": rejected[name]}
            continue
        picture, resources = runner.frame(quality, name, image=True)
        pictures[name] = picture
        variants[name] = {"status": "diagnostic", "samples": measurements[name],
                          "completion_distribution": completion_distribution(
                              [row["submit_through_completion_ms"] for row in measurements[name]]),
                          "median_ms": {key: median(row[key] for row in measurements[name])
                                        for key in ("prepare_ms", "encode_ms", "submit_through_completion_ms",
                                                    "cpu_prepare_through_completion_ms")},
                          "resources": resources}
    metrics = save_comparison(quality, pictures, directory)
    for name, values in metrics.items():
        variants[name]["vs_native_gl"] = values
    if "ordered_output" in pictures:
        variants["ordered_output"]["vs_current_webgpu"] = difference_metrics(
            pictures["current_webgpu"], pictures["ordered_output"])
    return {"source_contract": source_contract(quality), "variants": variants,
            "compatibility_accepted": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--goldens", type=Path, required=True)
    parser.add_argument("--capture-native", action="store_true")
    parser.add_argument("--samples", type=int, default=5)
    parser.add_argument("--case", action="append", dest="cases")
    args = parser.parse_args()
    if args.samples < 1:
        parser.error("--samples must be positive")
    fixtures = {fixture.name: fixture for fixture in quality_cases()}
    frames = [fixtures[name].build() for name in (args.cases or fixtures)]
    manifest = (capture_native(frames, args.goldens) if args.capture_native else
                json.loads((args.goldens / "manifest.json").read_text()))
    natives = {quality.name: read_native(quality, args.goldens, manifest) for quality in frames}
    tessellator = LyonFillTessellator()
    runner = QualityRunner(tessellator)
    args.output.mkdir(parents=True, exist_ok=True)
    root = Path(__file__).resolve().parents[1]
    sources = [*root.glob("benchmarks/*triangle*.py"), *root.glob("benchmarks/*analytic*.py"),
               Path(__file__), root / "benchmarks/ordered_output.py",
               root / "tests/renderer_quality_fixtures.py", root / "benchmarks/renderer_timing.py",
               root / "maniml/utils/space_ops.py"]
    report = {
        "status": "A0 quality experiment; no automatic compatibility acceptance",
        "environment": environment_metadata(tessellator, runner.current, runner.flat),
        "source_files_sha256": {str(path.relative_to(root)): sha256(path.read_bytes()).hexdigest()
                                 for path in sources},
        "git_head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip(),
        "goldens": str(args.goldens.resolve()), "warmups": 2, "samples_per_variant": args.samples,
        "completion_scope": COMPLETION_SCOPE,
        "cpu_cost_scope": "prepare_ms includes exact source-array validation, shader-data copies and projected quality checks. Uniform color refresh avoids tessellation but still copies interleaved vertices; buffer hashes occur during encoding.",
        "retirement_timing": "Current retains batch geometry history; ordered/triangle variants retire unused buffers inside the timed window. Current avoids that cost. Static warmed cases normally have no obsolete geometry to retire.",
        "timing": "Warm static source frames, rotated variant order. CPU preparation through completion includes serialization/meshing, target allocation, upload, encoding, resolve, one-pixel readback and cache retirement. Excludes source animation, scene/TeX construction, pipeline/device startup, transport/browser presentation and full-image diagnostics; it is not interactive frame latency. Both mesh candidates use retained source/quality caches; cold construction is outside these warm medians.",
        "aa": "Current/native use production 2D samples=0 with the existing 2x winding fill. Flat MSAA uses 4 samples. Flat SS uses 1 sample at 2x each dimension and a GPU four-texel box resolve in unorm component space; stroke AA width remains fixed in final pixels. Analytic UV/clip evaluate at covered MSAA samples; no derivative fringe. All flattened variants request <=0.25 final-pixel geometric tolerance before float32 rounding/AA.",
        "pixels": "Raw RGBA for metrics and native goldens. Opaque-background preview PNGs show attachment RGB without unpremultiplication. Existing alpha/winding quirks are not an opacity specification. Crops use final-output coordinates and nearest-neighbor enlargement.",
        "memory": "Nominal target bytes assume four bytes per color/depth sample and include the resolve output. Cache/buffer counts are separately scoped; none includes driver storage, transient peak scratch, source-array ownership or readback staging.",
        "cases": {},
    }
    for quality in frames:
        report["cases"][quality.name] = compare_quality(quality, natives[quality.name], runner,
                                                       args.samples, args.output)
        (args.output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
        print("compared", quality.name, flush=True)


if __name__ == "__main__":
    main()

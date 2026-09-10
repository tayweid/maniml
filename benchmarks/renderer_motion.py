"""A0 animated CPU preparation through GPU completion, without browser transport.

The same source scene is evaluated once per frame and drawn by four variants
in rotating order. Geometry/style validation, metadata, crops and full-image
diagnostics are outside all timing samples. No compatibility gate is accepted.
"""

import argparse
from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
from time import perf_counter
from typing import Callable

import numpy as np
from scipy.spatial.transform import Rotation
from benchmarks.renderer_timing import COMPLETION_SCOPE, completion_distribution

from maniml.animation.creation import Write
from maniml.animation.transform import Transform
from maniml.mobject.types.vectorized_mobject import VMobject
from maniml.utils.rate_functions import linear
from tests.renderer_quality_fixtures import (
    QualityFrame, _rois, _source_digest, build_quality_frame, quality_sequence,
)


VARIANTS = ("current_webgpu", "ordered_output", "flat_msaa4", "flat_ss2")
SCENARIOS = ("tex_zoom", "tex_zoom_4x", "tex_fractional_translation", "perspective_zoom",
             "tex_transform", "tex_write", "tex_opacity")


@dataclass
class MotionSequence:
    name: str
    steps: int
    apply: Callable[[int], None]
    snapshot: Callable[[int], QualityFrame]
    setup_ms: float
    description: str
    finish: Callable[[], None] = lambda: None


def _source_state(quality):
    """Source-only proof; renderer-derived normals and joints are excluded."""
    scene = quality.scene
    return (_source_digest(scene.mobjects),
            tuple(id(mob) for obj in scene.mobjects for mob in obj.get_family()),
            tuple(scene.camera.frame.get_center()),
            tuple(scene.camera.frame.get_shape()),
            tuple(scene.camera.frame.get_orientation().as_quat()),
            tuple(scene.camera.draw_fbo.size), scene.camera.samples,
            tuple((id(mob), mob.uniforms.get("anti_alias_width"), mob.depth_test)
                  for obj in scene.mobjects for mob in obj.get_family()))


def build_motion_sequence(name, *, border_policy="production_default", camera_steps=33,
                          translation_steps=9, animation_steps=17):
    started = perf_counter()
    if name not in SCENARIOS:
        raise ValueError(f"unknown motion scenario: {name}")
    if min(camera_steps, translation_steps, animation_steps) < 3:
        raise ValueError("motion scenarios require at least three frames")
    if name in ("tex_zoom", "tex_zoom_4x", "perspective_zoom", "tex_fractional_translation"):
        content = "perspective" if name == "perspective_zoom" else "tex"
        motion = "fractional_translation" if name.endswith("translation") else "zoom"
        steps = translation_steps if motion == "fractional_translation" else camera_steps
        # Build and validate every camera/ROI description before frame timing.
        # quality_sequence preserves source identity; all records share its scene.
        records, poses = [], []
        max_zoom = 4.0 if name == "tex_zoom_4x" else 2.0
        for quality in quality_sequence(content, border_policy, motion, steps, max_zoom=max_zoom):
            camera = quality.scene.camera.frame
            records.append(quality)
            poses.append((camera.get_shape(), camera.get_center().copy(),
                          camera.get_orientation().as_quat().copy()))
        scene = records[0].scene

        def apply(index):
            shape, center, quaternion = poses[index]
            scene.camera.frame.set_shape(*shape).move_to(center)
            scene.camera.frame.set_orientation(Rotation.from_quat(quaternion))

        return MotionSequence(name, steps, apply, records.__getitem__,
                              1000*(perf_counter()-started),
                              f"Camera-only {motion}, maximum zoom {max_zoom}x; source points and styles remain fixed. The 4x case exceeds the cache's 2x geometric headroom; 2x exercises reuse within that headroom.")

    base = build_quality_frame("tex", border_policy=border_policy)
    moving = base.scene.mobjects[0]
    if name == "tex_opacity":
        def apply(index):
            phase = index / (animation_steps - 1)
            moving.set_fill(opacity=.2 + .8 * np.sin(np.pi * phase)**2)

        def snapshot(index):
            metadata = dict(base.metadata, sequence=name, frame_index=index,
                            frame_count=animation_steps, phase=index/(animation_steps-1),
                            source_sha256=_source_digest(base.scene.mobjects))
            return QualityFrame(f"{name}_{index:03d}", base.scene,
                                _rois(base._regions, base.scene.camera), metadata,
                                base.diagnostic_limitations)

        return MotionSequence(name, animation_steps, apply, snapshot,
                              1000*(perf_counter()-started),
                              "Isolated set_fill opacity animation of the first TeX line; source points remain exactly fixed and fills stay visible. Measures paint refresh without Write's source interpolation/visibility changes.")
    if name == "tex_transform":
        target = moving.copy()
        # A real Transform with only selected glyphs changing; other lines and
        # unchanged glyphs establish whether per-submobject reuse works.
        for index, glyph in enumerate(target.submobjects):
            if index % 5 == 0:
                glyph.rotate(.16).scale(1.15).shift([0, .08, 0])
        animation = Transform(moving, target, run_time=1, rate_func=linear)
        description = "Production Transform of the first TeX line; every fifth target glyph is rotated/scaled/shifted, remaining source geometry is unchanged."
    else:
        animation = Write(moving, run_time=1, rate_func=linear)
        description = "Production Write of the first TeX line: stroke reveal plus fill-opacity ramp. Source interpolation can change point bytes by float32 rounding even when glyph shape is mathematically fixed, so rebuilds are not necessarily paint-only. Mesh appearances/evictions and paint updates are counted separately. tex_transform supplies the morph control and tex_opacity the exact fixed-point paint control. Second line and mathematical expression remain present."
    animation.begin()

    def apply(index):
        animation.interpolate(index/(animation_steps-1))

    def snapshot(index):
        metadata = dict(base.metadata, sequence=name, frame_index=index,
                        frame_count=animation_steps, phase=index/(animation_steps-1),
                        source_sha256=_source_digest(base.scene.mobjects))
        return QualityFrame(f"{name}_{index:03d}", base.scene,
                            _rois(base._regions, base.scene.camera), metadata,
                            base.diagnostic_limitations)

    return MotionSequence(name, animation_steps, apply, snapshot,
                          1000*(perf_counter()-started), description, animation.finish)


def percentiles(values):
    array = np.asarray(values, dtype=float)
    if not len(array):
        return {"p50": None, "p95": None, "max": None}
    return {"p50": float(np.percentile(array, 50)),
            "p95": float(np.percentile(array, 95)), "max": float(array.max())}


class UploadObserver:
    """Count native batch-buffer allocations; never change cache decisions."""
    def __init__(self, renderer):
        self.renderer = renderer
        self.resources = renderer._resources
        self.uniform = renderer._uniform_bind_group
        self.reset()

        def resources(batch, builder):
            def observed_build():
                result = builder()
                self.geometry_bytes += sum(value.size for value in result.values()
                                           if hasattr(value, "size") and hasattr(value, "destroy"))
                return result
            return self.resources(batch, observed_build)

        def uniform(*args, **kwargs):
            from tests.winding_reference_renderer import UNIFORM_BYTES
            result = self.uniform(*args, **kwargs)
            self.uniform_bytes += UNIFORM_BYTES
            return result

        renderer._resources = resources
        renderer._uniform_bind_group = uniform

    def reset(self):
        self.geometry_bytes = self.uniform_bytes = 0

    def stats(self):
        renderer = self.renderer
        seen = {}
        for resources in renderer.batch_cache.values():
            for value in resources.values():
                if hasattr(value, "size") and hasattr(value, "destroy"):
                    seen[id(value)] = value.size
        return {"uploaded_geometry_bytes": self.geometry_bytes,
                "uploaded_uniform_bytes": self.uniform_bytes,
                "retained_gpu_geometry_bytes": sum(seen.values()),
                "retained_batch_count": len(renderer.batch_cache),
                "retained_fill_target_bytes": sum(8*target["size"][0]*target["size"][1]
                                                   for target in renderer._fill_targets.values()),
                "retained_uniform_bytes": None,
                "retained_cpu_mesh_bytes": 0}


def clear_scene_caches(runner):
    """Start each scene without geometry history; retain device/pipeline startup."""
    for renderer in (runner.current, runner.ordered):
        for resources in renderer.batch_cache.values():
            for value in resources.values():
                if hasattr(value, "destroy"):
                    value.destroy()
        renderer.batch_cache.clear()
        for target in renderer._fill_targets.values():
            target["texture"].destroy()
        renderer._fill_targets.clear()
    for renderer in (runner.flat, runner.supersampled):
        for buffer in renderer._geometry.values():
            buffer.destroy()
        renderer._geometry.clear()
        for buffer, _ in renderer._bindings.values():
            buffer.destroy()
        renderer._bindings.clear()
    for cache in runner.caches.values():
        cache.clear()


def summarize(rows):
    result = {"frames": len(rows)}
    result["completion_distribution"] = completion_distribution(
        [row["submit_through_completion_ms"] for row in rows])
    for field in ("source_evaluation_ms", "prepare_ms", "encode_ms",
                  "submit_through_completion_ms", "cpu_prepare_through_completion_ms",
                  "source_evaluation_plus_prepare_through_completion_ms"):
        result[field] = percentiles([row[field] for row in rows])
    for field in ("uploaded_geometry_bytes", "uploaded_uniform_bytes"):
        result[field+"_total"] = sum(row.get(field, 0) for row in rows)
    for field in ("retained_gpu_geometry_bytes", "retained_cpu_mesh_bytes",
                  "retained_fill_target_bytes", "nominal_target_bytes"):
        values = [row[field] for row in rows if row.get(field) is not None]
        result[field+"_max"] = max(values) if values else None
    result["mesh_cache"] = {field: sum(row.get("mesh_cache", {}).get(field, 0) for row in rows)
                            for field in ("hits", "regenerations", "evictions", "paint_updates")}
    return result


def run_sequence(sequence, runner, observers, directory, diagnostics=True):
    from benchmarks.renderer_quality import difference_metrics
    clear_scene_caches(runner)
    sequence.apply(0)
    initial = sequence.snapshot(0)
    warmups = []
    for _ in range(2):
        warmups.append({name: runner.frame(initial, name)[1] for name in VARIANTS})
    rows = {name: [] for name in VARIANTS}
    diagnostic_metrics = {}
    source_states = []
    directory.mkdir(parents=True, exist_ok=True)
    for index in range(sequence.steps):
        started = perf_counter()
        sequence.apply(index)
        source_ms = 1000*(perf_counter()-started)
        quality = sequence.snapshot(index)
        source_state = _source_state(quality)
        source_states.append(source_state[0])
        order = VARIANTS[index % len(VARIANTS):] + VARIANTS[:index % len(VARIANTS)]
        for name in order:
            observer = observers.get(name)
            if observer:
                observer.reset()
            _, measurement = runner.frame(quality, name, image=False)
            if _source_state(quality) != source_state:
                raise RuntimeError(f"{name} mutated source geometry/style/camera at {sequence.name}:{index}")
            if observer:
                measurement.update(observer.stats())
                width, height = quality.scene.camera.draw_fbo.size
                measurement["nominal_target_bytes"] = width*height*8
            else:
                measurement["retained_cpu_mesh_bytes"] = measurement.get("mesh_cache", {}).get("retained_bytes", 0)
            measurement.update({"frame_index": index, "phase": index/(sequence.steps-1),
                                "source_evaluation_ms": source_ms,
                                "source_evaluation_plus_prepare_through_completion_ms":
                                source_ms+measurement["cpu_prepare_through_completion_ms"]})
            rows[name].append(measurement)
        if diagnostics and index in (0, sequence.steps//2, sequence.steps-1):
            pictures = {name: runner.frame(quality, name, image=True)[0] for name in VARIANTS}
            if _source_state(quality) != source_state:
                raise RuntimeError("diagnostic rendering changed source state")
            metrics = {}
            for name, picture in pictures.items():
                picture.convert("RGB").save(directory/f"{index:03d}_{name}.png")
                metrics[name] = {"full_frame": difference_metrics(pictures["current_webgpu"], picture),
                                 "rois": {roi.name: difference_metrics(
                                     pictures["current_webgpu"].crop(roi.box), picture.crop(roi.box), scope="region")
                                          for roi in quality.rois}}
            diagnostic_metrics[str(index)] = {"metadata": quality.metadata, "vs_current_webgpu": metrics}
    sequence.finish()
    return {"setup_ms_excluded": sequence.setup_ms, "description": sequence.description,
            "initial_frame_preparation_samples_excluded": warmups,
            "source_frame_sha256": source_states, "source_validation_passed": True,
            "variants": {name: {"summary": summarize(samples), "frames": samples}
                         for name, samples in rows.items()},
            "diagnostics_outside_timing": diagnostic_metrics, "compatibility_accepted": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("/private/tmp/maniml-motion-a0"))
    parser.add_argument("--scenario", action="append", choices=SCENARIOS)
    parser.add_argument("--no-images", action="store_true")
    args = parser.parse_args()
    from benchmarks.renderer_quality import QualityRunner
    from benchmarks.triangle_renderer import environment_metadata
    from maniml.web.triangle_geometry import LyonFillTessellator
    tessellator = LyonFillTessellator()
    runner = QualityRunner(tessellator)
    # Fill and stroke pipelines, including those first reached during Write.
    prewarm = build_quality_frame("hairlines")
    for name in VARIANTS:
        runner.frame(prewarm, name)
    observers = {"current_webgpu": UploadObserver(runner.current),
                 "ordered_output": UploadObserver(runner.ordered)}
    root = Path(__file__).resolve().parents[1]
    source_paths = [Path(__file__), root/"benchmarks/renderer_quality.py",
                    root/"benchmarks/triangle_renderer.py", root/"benchmarks/triangle_scene.py",
                    root/"benchmarks/ordered_output.py", root/"tests/renderer_quality_fixtures.py",
                    root/"benchmarks/renderer_timing.py", root/"maniml/utils/space_ops.py"]
    report = {
        "status": "A0 motion experiment; compatibility not accepted", "compatibility_accepted": False,
        "environment": environment_metadata(tessellator, runner.current, runner.flat),
        "source_files_sha256": {str(path.relative_to(root)): sha256(path.read_bytes()).hexdigest()
                                 for path in source_paths},
        "variants": list(VARIANTS), "border_policy": "production_default",
        "completion_scope": COMPLETION_SCOPE,
        "cpu_cost_scope": "prepare_ms includes exact live-array cache validation, mesh generation or color refresh, shader data extraction/copies and projected quality checks. Buffer content hashes are in encoding. No revision-only shortcut is enabled.",
        "retirement_timing": "Current WebGPU retains batch geometry history; ordered output and triangles retire unused buffers inside the timed window. Current therefore avoids that retirement cost. This compares existing lifecycle policies, not equally bounded caches; fill targets are retired for all variants.",
        "timing": "Source evaluation once per logical frame, added to each variant's measured CPU preparation through one-pixel GPU completion. Rotating variant order; warm resident first frame after two recorded/excluded initial samples. Device/pipeline startup, source/TeX construction, animation begin/finish, metadata/ROI preparation, source validation, counters collected after rendering, full-image diagnostics, transport and browser presentation excluded. Observer callbacks add small CPU overhead for baseline upload accounting. No interactive-frame pacing claim.",
        "memory": "Scene caches cleared between scenarios, devices/pipelines/output targets retained. Current WebGPU intentionally retains batch geometry history during a scenario; ordered output and triangles retire unused buffers. Reported retained bytes are observed per-frame owned buffers/arrays and nominal color/depth targets, not peak process/driver memory. Current/ordered uniform retained bytes unavailable; uploaded uniform bytes count known uniform bindings. Winding composite UV-scale buffers, bind-group/driver storage, source arrays, transient tessellation scratch, and readback staging are excluded.",
        "semantics": "Production text fill borders remain requested, but flat candidates omit them and report limitations. Existing winding/alpha quirks remain in references. Image differences do not automatically establish coverage/AA correctness; no analytic candidate in this motion comparison.",
        "scenarios": {},
    }
    args.output.mkdir(parents=True, exist_ok=True)
    for name in args.scenario or SCENARIOS:
        sequence = build_motion_sequence(name)
        report["scenarios"][name] = run_sequence(sequence, runner, observers,
                                                args.output/name, not args.no_images)
        (args.output/"report.json").write_text(json.dumps(report, indent=2)+"\n")
        print(name, {variant: round(values["summary"]["source_evaluation_plus_prepare_through_completion_ms"]["p50"], 3)
                     for variant, values in report["scenarios"][name]["variants"].items()}, flush=True)


if __name__ == "__main__":
    main()

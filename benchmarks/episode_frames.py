"""Renderer variants on frames of a real course episode.

    python -m benchmarks.episode_frames \\
        --scene /abs/path/Blocks/B2_Supply/03_Code.py EpisodeB2 \\
        --output /private/tmp/episode-b2

The B1 gate (docs/phase_b_plan.md, "Decided before the start") is judged on
the fixture corpus and one course episode. gpu_borders.py covers the
fixtures; this puts the episode's own frames in front of the same renderers,
caches, stage timer and queue contract, through gpu_borders.sample. The scene
is loaded as the CLI loads it and its checkpoints are built as present mode
builds them; every pausepoint (or every --every-th checkpoint of a file
without pauses) is restored in turn and sampled by each variant in rotation.
Three kinds of row, because the live viewer draws three kinds of frame: the
static redraw of a pausepoint (always; a camera change, nothing
regenerated), the pausepoint with its updaters ticking (--tick-updaters,
what the idle loop does while any mobject has updaters) and the frames of
the play that leads into the pausepoint (--play-frames, replayed at frame
rate with the variants sampled mid-interpolation). The GPU pass columns
appear under --gpu-timestamps (MANIML_GPU_TIMESTAMPS=1), an attribution run;
the gate's completion totals come from a run without it.
"""

import argparse
from contextlib import ExitStack
from datetime import datetime, timezone
from hashlib import sha256
from itertools import count
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import traceback
from unittest.mock import patch

import numpy as np

from benchmarks.gpu_borders import GATE_SCOPE, GPU_CLOCK_CAVEAT, GPU_TIMING_SCOPE
from benchmarks.paint_retention import difference


VARIANTS = ("patch_fill", "gpu_border", "cpu_border", "original_2d")
DEFAULT_VARIANTS = ("patch_fill", "gpu_border", "original_2d")
# gpu_borders.run_case's comparisons: (name, image, reference), reported
# when both rendered the frame.
PIXEL_PAIRS = (("patch_vs_gpu_border", "patch_fill", "gpu_border"), ("patch_vs_cpu", "patch_fill", "cpu_border"),
               ("patch_vs_original", "patch_fill", "original_2d"), ("gpu_vs_cpu", "gpu_border", "cpu_border"),
               ("gpu_vs_original", "gpu_border", "original_2d"))
# The columns summary.json reduces, in this order; gpu_pass_* follow them.
TIMING_KEYS = ("serialize_through_rgba_image_ms", "submit_through_full_readback_ms", "post_readback_ms",
               "prepare_ms", "render_cpu_encode_ms", "gpu_total_ms", "gpu_sum_ms", "gpu_readback_ms")
ROOT = Path(__file__).resolve().parents[1]


def select_frames(checkpoints, every=1, max_frames=12):
    """Checkpoint indices to measure.

    A pause-anchored file's frames are its pausepoints (the dicts flagged
    ``stop``); any other file gives every ``every``-th checkpoint after the
    empty first one. Either list is thinned evenly to ``max_frames`` and
    always keeps its last entry, the state the episode ends on.
    """
    stops = [index for index, checkpoint in enumerate(checkpoints) if checkpoint.get("stop")]
    if stops:
        pool = stops
    else:
        last = len(checkpoints) - 1
        pool = list(range(1, last + 1, every))
        if pool and pool[-1] != last:
            pool.append(last)
    if not pool:
        return [0]
    if len(pool) <= max_frames:
        return pool
    if max_frames == 1:
        return [pool[-1]]
    step = (len(pool) - 1) / (max_frames - 1)
    return [pool[round(k * step)] for k in range(max_frames)]


def rotation(variants, iteration):
    """gpu_borders' order: one place round per iteration, reversed every
    full cycle, so no renderer always follows the same other's work."""
    offset = iteration % len(variants)
    order = tuple(variants[offset:]) + tuple(variants[:offset])
    return order[::-1] if iteration // len(variants) % 2 else order


def summarize(rows):
    """Median and minimum of the summary columns present in ``rows``. A
    column some rows lack (a pass that frame did not encode) is reduced
    over the rows that have it; ``n`` says how many."""
    keys = [key for key in TIMING_KEYS if any(key in row for row in rows)]
    keys += sorted({key for row in rows for key in row if key.startswith(("gpu_pass_", "gpu_exclusive_"))})
    result = {}
    for key in keys:
        values = [row[key] for row in rows if key in row]
        result[key] = {"p50": float(np.median(values)), "min": float(min(values)), "n": len(values)}
    return result


def pixel_pairs(pictures):
    """gpu_borders.run_case's pairs over the variants that rendered the
    frame: ``<a>_vs_<b>`` is difference(<b>, <a>), <b> the reference."""
    return {name: difference(pictures[reference], pictures[image])
            for name, image, reference in PIXEL_PAIRS if image in pictures and reference in pictures}


def _cell(stats, key):
    return f"{stats[key]['p50']:.2f}" if key in stats else "–"


def markdown_table(summary):
    """One line per frame and phase (the pausepoint, and its play when
    measured): each variant's median total, submit-through-readback and
    GPU total in ms, then the pixel pairs present; closing lines over
    every measured row of each phase."""
    variants = summary["variants_in_rotation"]
    frames = summary["frames"]
    pairs = [name for name, _, _ in PIXEL_PAIRS
             if any(name in frame.get("pixels", {}) or name in (frame.get("play") or {}).get("pixels", {})
                    for frame in frames)]
    head = ["frame", "checkpoint", "line", "name", "phase"]
    head += [f"{variant} {column}" for variant in variants for column in ("total", "readback", "gpu")]
    head += [f"{name} px>24" for name in pairs]
    lines = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]

    def line(cells, stats, pixels):
        for variant in variants:
            timing = stats.get(variant, {})
            cells += [_cell(timing, "serialize_through_rgba_image_ms"),
                      _cell(timing, "submit_through_full_readback_ms"), _cell(timing, "gpu_total_ms")]
        for name in pairs:
            pair = pixels.get(name)
            cells.append(f"{100 * pair['fraction_pixels_rgb_over24']:.3f}%" if pair else "–")
        lines.append("| " + " | ".join(cells) + " |")

    for frame in frames:
        cells = [str(frame["frame"]), str(frame["checkpoint"]), str(frame["line"]), frame.get("name") or ""]
        phase = "pausepoint" + (", updaters ticking" if frame.get("updaters_ticked") else "")
        line([*cells, phase], frame["variants"], frame.get("pixels", {}))
        play = frame.get("play")
        if play and play.get("variants"):
            alphas = play["measured_alphas"]
            line([*cells, f"play α {alphas[0]:.2f}–{alphas[-1]:.2f}"], play["variants"], play.get("pixels", {}))
    line(["all", "", "", "", "pausepoints"], summary["variants"], {})
    if summary.get("play_variants"):
        line(["all", "", "", "", "plays"], summary["play_variants"], {})
    return "\n".join(lines)


def load_episode(path, name):
    """Construct the scene as the CLI does and build every checkpoint as
    present mode does. An error inside the episode's own construct() comes
    back with the checkpoint it reached instead of being raised: the frames
    before it are still real frames."""
    from maniml.__main__ import load_scene_module

    module = load_scene_module(str(path))
    scene = getattr(module, name)(window=None)
    scene._scene_filepath = str(path)
    scene.skip_animations = True
    scene.auto_reload_enabled = False
    scene.setup()
    scene._create_checkpoint_zero()
    # Strict errors arrive here as the exception itself; the mixin has
    # already put the last good checkpoint back on screen.
    scene._propagate_animation_errors = True
    try:
        scene._run_all_units()
    except Exception as exc:
        return scene, {"checkpoint_reached": scene.current_animation_index,
                       "error": f"{type(exc).__name__}: {exc}", "traceback": traceback.format_exc()}
    return scene, None


def show_frame(scene, index):
    """Put checkpoint ``index`` on screen the way a navigation does:
    restore, then one dt=0 update so updaters read the restored objects.
    A ThreeDScene's ambient rotation turns the camera on every update
    call, dt or not, and its switch is scene state no checkpoint restores
    (it holds whatever the episode ended on), so it is off here: the frame
    shows the checkpoint's authored camera."""
    scene._restore_checkpoint_for_display(index)
    if hasattr(scene, "ambient_rotation_active"):
        scene.ambient_rotation_active = False
    scene.update_mobjects(0)
    scene.camera.refresh_uniforms()


def family(scene):
    for mob in scene.mobjects:
        yield from mob.get_family()


def source_contract(scene):
    """generated_output.source_contract taken over the authored mobject
    list: a real Scene's render_groups are _RenderBatch wrappers derived
    from it, not mobjects with families of their own."""
    from maniml.web import geometry
    from tests.renderer_quality_fixtures import _source_digest

    identities, style = [], []
    for mob in scene.mobjects:
        members = mob.get_family()
        identities.append(tuple(id(member) for member in members))
        style.append([(type(member).__name__, member.z_index, bool(member.depth_test),
                       bool(getattr(member, "stroke_behind", False)), member.uniforms)
                      for member in members])
    return (_source_digest(scene.mobjects), tuple(identities),
            json.dumps(style, sort_keys=True, default=geometry._jsonable))


def sample_round(scene, order, sampler, failed, errors, fields):
    """One rotation of the variants over the scene as it stands: each
    variant's row (with ``fields`` and the order it ran in) and picture,
    the source contract and camera packet checked after each. A variant
    that raises is recorded in ``errors``, joins ``failed`` and is skipped
    from then on: the episode's geometry, not the harness (an unsupported
    prototype, a singular camera)."""
    from maniml.web import geometry

    expected, pose = source_contract(scene), geometry._jsonable(scene.camera.uniforms)
    rows, pictures = {}, {}
    for variant in order:
        if variant in failed:
            continue
        try:
            row, picture, header = sampler(variant)
        except Exception as exc:
            failed.add(variant)
            errors[variant] = {"error": f"{type(exc).__name__}: {exc}", "traceback": traceback.format_exc()}
            print(f"checkpoint {fields['checkpoint']}: {variant} failed: {exc}", file=sys.stderr, flush=True)
            continue
        if source_contract(scene) != expected:
            raise RuntimeError(f"{variant} modified authored source/style/order")
        if geometry._jsonable(scene.camera.uniforms) != pose:
            raise RuntimeError(f"{variant} modified camera packet")
        row.update(fields, order=list(order), unsupported=list(header.get("unsupported", [])))
        rows[variant], pictures[variant] = row, picture
    return rows, pictures


def play_before(checkpoints, index):
    """The checkpoint of the last play at or before ``index``: the
    animation a viewer watches arriving there. A pause saves a checkpoint
    of its own with no run_time, so a pausepoint's play is usually the
    checkpoint before it; None when nothing played (checkpoint zero, or
    pauses only)."""
    for target in range(index, 0, -1):
        if checkpoints[target].get("run_time") is not None:
            return target
    return None


def play_frame_count(fps, run_time):
    """The frames progress_through_animations steps through: the arange of
    Scene.get_time_progression."""
    return len(np.arange(0, run_time, 1 / fps))


def replay_play(scene, target, on_frame):
    """Replay the play that saved checkpoint ``target`` at frame rate from
    the checkpoint before it, calling ``on_frame(k)`` at its k-th frame
    with the scene mid-interpolation: the retained replay a RIGHT press
    runs, with the camera's capture and the file writer's frame stood down
    as tests.test_checkpoint_reload stands them down. Ends with checkpoint
    ``target`` on screen."""
    frames, state = count(), {"failed": False}

    def capture(*render_groups):
        # update_frame reaches the capture once per visible frame, after
        # the updaters and the interpolation. Waits and the restore's
        # forced draw arrive here too, outside a play.
        if not getattr(scene, "_is_playing", False) or state["failed"]:
            return
        try:
            on_frame(next(frames))
        except BaseException:
            state["failed"] = True  # the error path forces one more draw
            raise

    scene._restore_checkpoint_for_display(target - 1)
    # Strict, so a harness error surfaces instead of landing the scene
    # back on the start with the rows missing.
    scene._propagate_animation_errors = True
    scene.skip_animations = False
    try:
        with patch.object(scene.camera, "capture", capture), patch.object(scene, "emit_frame"):
            scene._replay_retained_checkpoint(target)
    finally:
        scene.skip_animations = True


def measure_play(scene, index, variants, samples, warmups, sampler, counter, fields):
    """The play leading into checkpoint ``index`` on consecutive frames
    centred on its middle: ``warmups`` frames then ``samples`` measured
    ones (fewer when the play is shorter), each frame one rotation of the
    variants over the scene mid-interpolation. The scene changes between
    rows as it does on screen, so the rows carry regeneration rather than
    revision-cache hits. Returns the frame's play block and the measured
    rows per variant."""
    checkpoints = scene.animation_checkpoints
    target = play_before(checkpoints, index)
    play = {"checkpoint": target, "line": None, "run_time": None, "frames": 0, "measured_alphas": [],
            "errors": {}, "variants": {}, "pixels": {}}
    rows = {variant: [] for variant in variants}
    if target is None:
        return play, rows, {}
    run_time, fps = checkpoints[target]["run_time"], scene.camera.fps
    frames = play_frame_count(fps, run_time)
    play.update(line=checkpoints[target]["line_number"], run_time=run_time, frames=frames)
    window = min(frames, warmups + samples)
    first, warm = (frames - window) // 2, min(warmups, max(window - 1, 0))
    failed, pictures = set(), {}

    def on_frame(k):
        if not first <= k < first + window:
            return
        local = k - first
        scene.camera.refresh_uniforms()
        alpha = (k + 1) / fps / run_time
        round_rows, round_pictures = sample_round(
            scene, rotation(variants, next(counter)), sampler, failed, play["errors"],
            dict(fields, phase="play", play_checkpoint=target, play_frame=k, alpha=alpha,
                 iteration=local, warmup=local < warm))
        pictures.update(round_pictures)
        if local >= warm:
            play["measured_alphas"].append(alpha)
            for variant, row in round_rows.items():
                rows[variant].append(row)

    replay_play(scene, target, on_frame)
    play["variants"] = {variant: summarize(measured) for variant, measured in rows.items() if measured}
    play["pixels"] = pixel_pairs(pictures)
    return play, rows, pictures


def measure(scene, indices, variants, samples, warmups, sampler, output, report, *, images=False,
            tick_updaters=False, play_frames=False):
    """Sample every variant on every chosen frame; ``sampler(variant)``
    returns gpu_borders.sample's (row, image, header) for the scene as it
    stands. Per frame: the pausepoint's rounds (warmups then samples, one
    rotation of the variants each; under ``tick_updaters`` the scene's
    updaters tick 1/fps before every round on a frame that has any, as the
    idle loop ticks them), then under ``play_frames`` the rounds on
    consecutive frames of the play that leads into it. report.json is
    rewritten after each frame so an interrupted run keeps the frames it
    finished."""
    from maniml.web import geometry

    variants = tuple(variants)
    report["frames"] = []
    rows, play_rows, counter = {variant: [] for variant in variants}, {variant: [] for variant in variants}, count()
    for position, index in enumerate(indices):
        checkpoint = scene.animation_checkpoints[index]
        show_frame(scene, index)
        live = bool(scene.should_update_mobjects())
        fields = dict(frame=position, checkpoint=index, line=checkpoint["line_number"], name=checkpoint.get("name"))
        frame = {**fields, "stop": bool(checkpoint.get("stop")),
                 "resolution": list(scene.camera.draw_fbo.size),
                 "drawn_mobjects": sum(mob.has_points() for mob in family(scene)),
                 "source_sha256": source_contract(scene)[0],
                 "should_update_mobjects": live, "updaters_ticked": bool(tick_updaters and live),
                 "cold": {}, "errors": {}, "variants": {}, "pixels": {}}
        dt = 1 / scene.camera.fps if frame["updaters_ticked"] else None
        failed, pictures = set(), {}
        for local in range(warmups + samples):
            if dt is not None:
                # The idle loop's tick: the updaters regenerate what they
                # drive, so the round measures that rather than a
                # revision-cache hit on a frame the viewer never redraws.
                scene.update_mobjects(dt)
                scene.camera.refresh_uniforms()
            round_rows, round_pictures = sample_round(
                scene, rotation(variants, next(counter)), sampler, failed, frame["errors"],
                dict(fields, phase="pausepoint", iteration=local, warmup=local < warmups))
            pictures.update(round_pictures)
            for variant, row in round_rows.items():
                if local == 0:
                    frame["cold"][variant] = row
                if local >= warmups:
                    rows[variant].append(row)
        frame["variants"] = {variant: summarize([row for row in rows[variant] if row["checkpoint"] == index])
                             for variant in variants if any(row["checkpoint"] == index for row in rows[variant])}
        frame["pixels"] = pixel_pairs(pictures)
        if images:
            for variant, picture in pictures.items():
                picture.save(output / f"frame_{index:03}_{variant}.png")
        if play_frames:
            frame["play"], measured, play_pictures = measure_play(scene, index, variants, samples, warmups,
                                                                  sampler, counter, fields)
            for variant, measured_rows in measured.items():
                play_rows[variant].extend(measured_rows)
            if images:
                for variant, picture in play_pictures.items():
                    picture.save(output / f"frame_{index:03}_play_{variant}.png")
        report["frames"].append(frame)
        report["variants"] = {}
        for variant in variants:
            if rows[variant] or play_rows[variant]:
                data = {"timing_ms": summarize(rows[variant]) if rows[variant] else {},
                        "samples": rows[variant] + play_rows[variant]}
                if play_rows[variant]:
                    data["play_timing_ms"] = summarize(play_rows[variant])
                report["variants"][variant] = data
        (output / "report.json").write_text(json.dumps(report, indent=2, default=geometry._jsonable) + "\n")
        print(f"frame {position + 1}/{len(indices)} checkpoint {index} line {checkpoint['line_number']} complete",
              flush=True)
    return report


def run(scene, indices, variants, samples, warmups, stages, output, report, *, images=False,
        tick_updaters=False, play_frames=False):
    """gpu_borders' renderer, cache and queue construction, one set for the
    whole run as a viewer session keeps one: a frame's retained geometry
    carries into the next as it does on screen."""
    from benchmarks.generated_output import QueueObserver
    from benchmarks.gpu_borders import sample
    from maniml.web.geometry import GeometryCache
    from maniml.web.wgpu_renderer import WgpuRenderer
    from tests.winding_reference_renderer import WgpuRenderer as WindingRenderer

    variants = tuple(variants)
    caches = {variant: GeometryCache() for variant in variants}
    renderers = {variant: WindingRenderer() if variant == "original_2d" else WgpuRenderer()
                 for variant in variants}
    queues = {variant: QueueObserver(renderer) for variant, renderer in renderers.items()}
    report["adapters"] = {variant: dict(renderer.device.adapter_info) for variant, renderer in renderers.items()}

    def sampler(variant):
        try:
            # sample adds the gpu_ columns itself when the renderer has
            # the instrument, after its timers.
            return sample(scene, variant, caches[variant], stages, renderers[variant], queues[variant])
        except Exception:
            # A failed submission must not turn the next packet into a
            # cache-only one the renderer cannot honor (Camera.capture).
            caches[variant].reset()
            raise

    try:
        return measure(scene, indices, variants, samples, warmups, sampler, output, report, images=images,
                       tick_updaters=tick_updaters, play_frames=play_frames)
    finally:
        for queue in queues.values():
            queue.close()
        for renderer in renderers.values():
            if hasattr(renderer, "close"):
                renderer.close()
            else:
                renderer.device.destroy()


def git_state(root):
    def git(*args):
        try:
            return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True,
                                  check=True).stdout.strip()
        except (OSError, subprocess.CalledProcessError):
            return None
    return {"commit": git("rev-parse", "HEAD"), "branch": git("rev-parse", "--abbrev-ref", "HEAD"),
            "dirty": bool(git("status", "--porcelain"))}


def summary_of(report):
    """report.json without the per-sample rows, the cold rows and the full
    checkpoint list (the measured checkpoints stay, with each frame's line
    and name)."""
    summary = {key: value for key, value in report.items() if key not in ("variants", "frames")}
    if "scene" in summary:
        summary["scene"] = {key: value for key, value in summary["scene"].items() if key != "checkpoints"}
    variants = report.get("variants", {})
    summary["variants"] = {variant: data["timing_ms"] for variant, data in variants.items()}
    summary["play_variants"] = {variant: data["play_timing_ms"] for variant, data in variants.items()
                                if "play_timing_ms" in data}
    summary["frames"] = [{key: value for key, value in frame.items() if key != "cold"}
                         for frame in report.get("frames", [])]
    return summary


def scope(variants, tick_updaters, play_frames):
    """The report's own caveats, worded for the run's switches; the gpu_
    column and GPU clock notes come from gpu_borders."""
    result = {
        "frame_selection": (
            "Pausepoints of a pause-anchored file, else every --every-th checkpoint after the empty first one; "
            "thinned evenly to --max-frames keeping the last, with no weighting by on-screen time or heaviness "
            "(raise --max-frames when the heaviest beat must be in). Each frame is _restore_checkpoint_for_display "
            "plus one dt=0 updater pass, as a navigation shows it; the camera orientation is checkpoint state and "
            "comes back with it; a ThreeDScene's ambient rotation, which turns the camera per update call and whose "
            "switch no checkpoint restores, is switched off before the pass. "
            + ("With --play-frames the play leading into each pausepoint (the last checkpoint with a run_time at "
               "or before it) is replayed from the checkpoint before it through the scene's retained replay at "
               "camera.fps, and its middle frames are sampled."
               if play_frames else "No play frames (--play-frames): the archive holds no mid-animation state.")),
        "timing_scope": (
            "One renderer, cache and queue per variant for the whole run, as one viewer session keeps them. "
            "Pausepoint rows: warmups then samples, rotated/reversed order across variants; the first row after a "
            "restore is archived per frame as cold and excluded. "
            + ("Sources are static between rounds, so pausepoint rows are the steady-state redraw of a static "
               "frame (revision-cache hits, retained geometry: the cost of a camera change), not the live "
               "per-frame cost at a pausepoint whose mobjects have updaters, which the viewer ticks every idle "
               "frame and which regenerate what they drive (should_update_mobjects is recorded per frame; "
               "--tick-updaters measures that)."
               if not tick_updaters else
               "On a frame with updaters (should_update_mobjects) every round is preceded by "
               "scene.update_mobjects(1/fps), as the idle loop ticks it, so its rows carry the regeneration the "
               "updaters cause (updaters_ticked); frames without updaters are static redraws.")
            + (" Play rows: consecutive frames of the play leading into the pausepoint, warmups then samples "
               "centred on its middle, each one rotation of the variants over the scene mid-interpolation; the "
               "scene changes between rows as it does on screen." if play_frames else "")
            + " Full RGBA readback/PIL image per sample. Render CPU ends at queue.submit; submit-through-readback "
            "includes GPU work, host waiting and resource retirement and is mostly the full-frame readback the "
            "browser never does; post_readback_ms is the image construction after it. gpu_* columns exist only "
            "under --gpu-timestamps and are read after the row's timers stop, so no total contains the "
            "instrument's resolve (gpu_readback_ms, recorded); the stamping itself perturbs a frame in proportion "
            "to its pass count (gpu_timing_scope), so the gate's totals come from a run without the flag and "
            "flag-on and flag-off totals are not compared as equals; original_2d is never instrumented or charged. "
            "Source checks, pixel comparisons and PNG writes are outside timings. Component medians must not be "
            "added. A column some rows lack reduces over the rows that have it, with n."),
        "image_scope": (
            "Each frame's last measured render per variant, compared outside timing in gpu_borders.run_case's "
            "pairs: <a>_vs_<b>'s fraction_pixels_rgb_over24 is the share of <a>'s pixels more than 24/255 from "
            "<b>'s in some RGB channel, <b> the reference (patch_vs_gpu_border, patch_vs_cpu when cpu_border is "
            "in rotation, patch_vs_original, gpu_vs_cpu, gpu_vs_original). The B1 gate's pixel measure is "
            "patch_vs_cpu and patch_vs_original at most 0.5% (docs/phase_b_plan.md), reported, not enforced; a "
            "play's pixels are its last sampled frame."),
        "gate_scope": (
            "What this run answers for the B1 gate's one course episode: completion of the phases measured, in "
            "the rotation named in variants_in_rotation (the completion comparison is a two-variant run with the "
            "timestamp flag off), and the pixel pairs. Not measured: the browser driver (accepted, plan item 3); "
            "the cold/navigation rows, archived per frame and excluded though a seek is what they feel like (and "
            "under --gpu-timestamps they carry the stamping cost); pausepoints not selected. "
            + ("Static redraws only: no updater-ticked rows and no play frames."
               if not (tick_updaters or play_frames) else "")),
        "gpu_timing_scope": GPU_TIMING_SCOPE, "gpu_clock_caveat": GPU_CLOCK_CAVEAT,
        "fixture_gate_scope": GATE_SCOPE,
    }
    if len(variants) > 2:
        result["rotation_caveat"] = (
            f"{len(variants)} renderers in rotation: most generated readbacks follow another renderer's frame "
            "(original_2d's 15-17 ms one on a 2160x1080 episode frame), the alternation effect "
            "gpu_borders.run_case records. The gate's completion comparison is a two-variant run "
            "(--variants patch_fill gpu_border, then patch_fill original_2d); a rotation of three serves the pixel "
            "pairs.")
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--scene", nargs=2, metavar=("FILE", "SCENE"), required=True,
                        help="episode file and scene class")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--variants", nargs="+", choices=VARIANTS, default=list(DEFAULT_VARIANTS),
                        help="renderers to alternate per frame; two alone is the completion comparison to trust")
    parser.add_argument("--samples", type=int, default=12)
    parser.add_argument("--warmups", type=int, default=3)
    parser.add_argument("--every", type=int, default=1, help="checkpoint stride for a file without pausepoints")
    parser.add_argument("--max-frames", type=int, default=12)
    parser.add_argument("--images", action="store_true", help="save each frame's last render per variant")
    parser.add_argument("--tick-updaters", action="store_true",
                        help="tick a pausepoint's updaters 1/fps before every round, as the idle loop does")
    parser.add_argument("--play-frames", action="store_true",
                        help="also sample consecutive frames of the play leading into each pausepoint")
    parser.add_argument("--gpu-timestamps", action="store_true",
                        help="per-pass GPU timestamps on the generated renderers (MANIML_GPU_TIMESTAMPS=1): "
                             "an attribution run, not the gate's totals")
    args = parser.parse_args(argv)
    if min(args.samples, args.warmups, args.every, args.max_frames) < 1:
        parser.error("samples, warmups, every and max-frames must be positive")
    scene_path = Path(args.scene[0]).resolve()
    if not scene_path.is_file():
        parser.error(f"no scene file at {scene_path}")
    # The renderer reads the switch when it is constructed, in run().
    if args.gpu_timestamps:
        os.environ["MANIML_GPU_TIMESTAMPS"] = "1"
    args.output.mkdir(parents=True, exist_ok=True)

    import wgpu
    from benchmarks.generated_output import StageObserver
    from maniml.web import geometry, winding_geometry

    scene, error = load_episode(scene_path, args.scene[1])
    checkpoints = scene.animation_checkpoints
    indices = select_frames(checkpoints, args.every, args.max_frames)
    paths = [Path(__file__), ROOT / "benchmarks/gpu_borders.py", ROOT / "benchmarks/generated_output.py",
             ROOT / "benchmarks/paint_retention.py", ROOT / "tests/winding_reference_renderer.py",
             ROOT / "tests/winding_reference_geometry.py", *(ROOT / "maniml/web").glob("*.py"),
             *(ROOT / "maniml/web/static/wgsl").glob("*.wgsl"), *(ROOT / "tests/winding_reference_wgsl").glob("*.wgsl"),
             scene_path]
    hashes = {str(path.relative_to(ROOT) if path.is_relative_to(ROOT) else path): sha256(path.read_bytes()).hexdigest()
              for path in paths}
    report = {
        "recorded_utc": datetime.now(timezone.utc).isoformat(), "command": sys.argv,
        "scene": {"path": str(scene_path), "name": args.scene[1], "checkpoint_count": len(checkpoints),
                  "pause_anchored": any(checkpoint.get("stop") for checkpoint in checkpoints),
                  "checkpoints": [{"index": checkpoint["index"], "line": checkpoint["line_number"],
                                   "name": checkpoint.get("name"), "stop": bool(checkpoint.get("stop")),
                                   "run_time": checkpoint.get("run_time")}
                                  for checkpoint in checkpoints],
                  "measured_checkpoints": indices, "construct_error": error},
        "git": git_state(ROOT),
        "machine": {"platform": platform.platform(), "machine": platform.machine(), "node": platform.node()},
        "python": platform.python_version(), "wgpu": wgpu.__version__, "numpy": np.__version__,
        "samples": args.samples, "warmups": args.warmups, "every": args.every, "max_frames": args.max_frames,
        "variants_in_rotation": list(args.variants),
        "gpu_timestamps": os.environ.get("MANIML_GPU_TIMESTAMPS") == "1",
        "tick_updaters": args.tick_updaters, "play_frames": args.play_frames,
        "environment": {key: value for key, value in os.environ.items() if key.startswith("MANIML_")},
        "source_files_sha256": hashes,
        **scope(args.variants, args.tick_updaters, args.play_frames),
    }
    stages = StageObserver()
    with ExitStack() as stack:
        stack.enter_context(patch.object(geometry, "performance", stages))
        stack.enter_context(patch.object(winding_geometry, "performance", stages))
        run(scene, indices, args.variants, args.samples, args.warmups, stages, args.output, report,
            images=args.images, tick_updaters=args.tick_updaters, play_frames=args.play_frames)
    report["gpu_timestamps_present"] = {variant: any("gpu_total_ms" in row for row in data["samples"])
                                        for variant, data in report["variants"].items()}
    report["source_files_unchanged_during_run"] = all(
        sha256((ROOT / path if not Path(path).is_absolute() else Path(path)).read_bytes()).hexdigest() == value
        for path, value in hashes.items())
    (args.output / "report.json").write_text(json.dumps(report, indent=2, default=geometry._jsonable) + "\n")
    summary = summary_of(report)
    (args.output / "summary.json").write_text(json.dumps(summary, indent=2, default=geometry._jsonable) + "\n")
    table = markdown_table(summary)
    (args.output / "summary.md").write_text(table + "\n")
    print(table)
    if error is not None:
        print(f"construct() stopped at checkpoint {error['checkpoint_reached']}: {error['error']}", file=sys.stderr)


if __name__ == "__main__":
    main()

"""A default flip's browser-side complete frame against Phase A's, on the
frames of a course episode (docs/phase_b4_plan.md, "The flips", B5.4).

    python -m benchmarks.flip_gates serialize --flip patches \\
        --scene /abs/path/Blocks/B2_Supply/03_Code.py EpisodeB2 \\
        --tick-updaters --play-frames --camera-moves --output <dir>/serialize
    python -m benchmarks.flip_gates complete --flip patches --serialize <dir>/serialize \\
        --browser <dir>/browser --gpu <dir>/gpu --pixels <dir>/frames --limit 1.0 \\
        --output <dir>/complete
    python -m benchmarks.flip_gates fixtures --output <dir>/fixtures
    python -m benchmarks.flip_gates programs --plays <play_frames dirs> --render <play_frames --render dirs> \\
        --output <dir>/programs

The complete frame is the gate Taylor set for the patch fill (confirmed
2026-09-27): per frame, Python's serialize_ms, the page's JavaScript
(browser_frames' page_ms) and the GPU (gpu_total_ms from episode_frames'
attribution run), summed, then reduced per class (pausepoint, ticked,
camera, play) for the flip and for Phase A in each wire format. Each part
comes from the harness that measures it (benchmarks/README.md, "Flip
gates"), over the same frames: all three choose them with
episode_frames.select_frames and sample a play's middle window alike.

- serialize (this module's first command): the two stacks as
  browser_frames names them (phase_a, Phase A forced, and the flip's
  variant, the default renderer under its switches: FLIPS), each
  serialized as format 7 full frames and as a negotiated format 8 stream,
  each through a GeometryCache of its own: four serializers, the retained
  frame on (ENVIRONMENT). They take turns so that each is the first reader
  of what moved, as the viewer's one cache is (a read refreshes a path's
  derived columns, so a second reader of the same change pays less): on a
  still frame the four in rotated order round by round, on a ticked frame
  one serializer per tick, on a camera move the four in rotated order
  after each move, in a play one per replay, replay by replay. Before a
  frame's rounds each serializes the restored frame once (the seek), which
  is not a row.
- page_ms: browser_frames' report.json for the two variants, recorded with
  --deltas and replayed with --rounds N --realm main (each frame's median
  over the rounds); a format 8 frame the stream did not send is 0.
- GPU: the median gpu_total_ms of the frame's rows in the class, over the
  episode_frames attribution runs given (--gpu-timestamps, the flip's
  variant and gpu_border rotating frame by frame, --camera-moves for the
  camera class); in format 8 it is charged in proportion to the frame's
  messages that were sent, since a frame not sent draws nothing.

A class's complete frame is the median over its frames of serialize + page +
GPU: a still, ticked or camera frame is one value (its serialize and page
medians over the rounds, its GPU median), each measured play frame one (its
serialize median over the replays, its play's page and GPU medians). The
verdict reads flip / Phase A per class and format against --limit, and the
flip's pixels against Phase A (episode_frames' <flip>_vs_gpu_border, the
fraction of pixels more than 24/255 off in any channel, over every measured
pausepoint and every frame of the plays' windows strictly inside the play,
against 0.5%). Given the flag-off runs (--pixels), it also reads the same
frames with the GPU part their wall clock from the submit through the full
readback (flag_off_check): the stamps an attribution run takes cost each
pass ~30 µs, so where the flip changes the pass count (a net or a program
is a pass of its own) the attribution run's GPU overstates the stack with
more passes, while the readback in the wall clock dilutes every ratio;
the two bracket the flip. The nets flip's pixel gate also reads every
Surface fixture (tests/surface_fixtures.py): the third command draws each
from Phase A's grids and from nets natively and writes the pairs.

The programs flip reads other numbers (the plan's "The flips"): Python ms
per play frame under the candidate mode against programs off over every
play of an episode, and the pixels of every play frame against the CPU
path. benchmarks/play_frames.py measures both (--every-play, the modes
taking turns replay by replay and the mode that opens a play alternating
play by play; --render for the pixels); the fourth command reduces its
reports: per episode and format, each frame's serialize_ms plus scene_ms
(the scene's own Python since the frame before; a play's entry follows
none of its frames and counts its serialize alone), their total over every
frame of every play divided by the frames, and the ratio the gate reads,
order-balanced (``balanced``: the geometric mean of the ratio over the
plays each mode opened, with a 95% interval from resampling them), over
every play, over the plays where the candidate recorded a program and over
the rest; the plays where the candidate is dearer; every frame's pixels;
and the native complete frame of the render runs, grouped alike. A run
whose plays one mode opened throughout is refused.
"""

import argparse
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from hashlib import sha256
import io
import json
import os
from pathlib import Path
import platform
import sys
from time import perf_counter
from unittest.mock import patch

import numpy as np

from benchmarks.browser_frames import ENVIRONMENTS, RENDERERS, measured
from benchmarks.episode_frames import (ROOT, git_state, load_episode, move_camera, play_before, play_frame_count,
                                       replay_play, select_frames, show_frame)

# Each flip: browser_frames' variant, whose environment the flip is
# serialized under and whose page_ms it reads, and episode_frames' variant,
# whose GPU and pixel rows it reads. Phase A is the reference.
FLIPS = {"nets": ("phase_a_nets", "nets"), "patches": ("phase_a_patches", "patch_fill")}
PHASE_A = ("phase_a", "gpu_border")
CLASSES = ("pausepoint", "ticked", "camera", "play")
FORMATS = (7, 8)
# What every serializer runs under, its stack aside: the retained frame
# (the serializer's default), and animations that write no program (both
# stacks draw programs off, and an animation decides at its begin), stated
# so that neither a caller's environment nor a default can move them.
ENVIRONMENT = {"MANIML_RETAINED_FRAME": "1", "MANIML_PROGRAMS": "off"}
CLEARED = ("MANIML_VERIFY_LEDGER", "MANIML_RENDER_CACHE", "MANIML_GPU_TIMESTAMPS")
PIXEL_LIMIT = .005
# The flag-off check's GPU part (complete --pixels): episode_frames' wall
# clock from the submit through the full readback, in the runs without
# MANIML_GPU_TIMESTAMPS.
FLAG_OFF_GPU = "submit_through_full_readback_ms"
# The programs gate's interval: resamples of the plays of each opener, and
# the seed.
INTERVAL_RESAMPLES, INTERVAL_SEED = 2000, 20260928


def stacks(flip):
    """(browser_frames variant, renderer, environment) for Phase A and the flip."""
    return [(name, RENDERERS.get(name, "triangles"), ENVIRONMENTS[name]) for name in (PHASE_A[0], FLIPS[flip][0])]


def key_name(name, fmt):
    return f"{name}_f{fmt}"


def reduce_samples(samples):
    """Median, minimum, count and how many were sent, of (ms, sent) pairs."""
    values = [ms for ms, _ in samples]
    return {"p50": float(np.median(values)), "min": float(min(values)), "n": len(values),
            "sent": int(sum(sent for _, sent in samples))}


def measure_serialize(scene, indices, flip, *, samples=12, warmups=3, replays=4, tick_updaters=False,
                      play_frames=False, camera_moves=False, log=None):
    """serialize_ms per frame and class for the four serializers (the two
    stacks in both formats), taking turns as the module's docstring says.
    Returns one block per frame."""
    from maniml.web.geometry import GeometryCache, serialize_scene

    stack = {name: (renderer, environment) for name, renderer, environment in stacks(flip)}
    keys = [(name, fmt) for name in stack for fmt in FORMATS]
    caches = {key: GeometryCache() for key in keys}
    for (_, fmt), cache in caches.items():
        cache.negotiate(fmt == 8)

    def serialize(key):
        renderer, environment = stack[key[0]]
        with patch.dict(os.environ, environment):
            started = perf_counter()
            message = serialize_scene(scene, caches[key], renderer=renderer)
            return 1000 * (perf_counter() - started), message is not None

    def rotated(turn):
        shift = turn % len(keys)
        return keys[shift:] + keys[:shift]

    checkpoints, frames = scene.animation_checkpoints, []
    for position, index in enumerate(indices):
        checkpoint = checkpoints[index]
        show_frame(scene, index)
        live = bool(scene.should_update_mobjects())
        cls = "ticked" if tick_updaters and live else "pausepoint"
        for key in keys:
            serialize(key)
        rows = {key: [] for key in keys}
        if cls == "ticked":
            for turn in range(len(keys) * (warmups + samples)):
                scene.update_mobjects(1 / scene.camera.fps)
                scene.camera.refresh_uniforms()
                key = keys[turn % len(keys)]
                sample = serialize(key)
                if turn >= len(keys) * warmups:
                    rows[key].append(sample)
        else:
            for turn in range(warmups + samples):
                for key in rotated(turn):
                    sample = serialize(key)
                    if turn >= warmups:
                        rows[key].append(sample)
        frame = {"frame": position, "checkpoint": index, "line": checkpoint["line_number"],
                 "name": checkpoint.get("name"), "should_update_mobjects": live, "class": cls,
                 cls: {key_name(*key): reduce_samples(values) for key, values in rows.items()}}
        if camera_moves:
            moved = {key: [] for key in keys}
            for turn in range(warmups + samples):
                for _ in move_camera(scene):
                    for key in rotated(turn):
                        sample = serialize(key)
                        if turn >= warmups:
                            moved[key].append(sample)
            frame["camera"] = {key_name(*key): reduce_samples(values) for key, values in moved.items()}
        target = play_before(checkpoints, index) if play_frames else None
        if target is not None:
            frame["play"] = measure_play(scene, target, keys, serialize, samples, warmups, replays)
        frames.append(frame)
        if log is not None:
            log(frame)
    return frames


def measure_play(scene, target, keys, serialize, samples, warmups, replays):
    """The play into checkpoint ``target``: episode_frames' window (its
    middle ``warmups`` + ``samples`` frames, the warmups not rows), each
    replay serialized by one serializer, the serializers taking turns
    replay by replay; per serializer each frame's median over its replays."""
    checkpoint = scene.animation_checkpoints[target]
    count = play_frame_count(scene.camera.fps, checkpoint["run_time"])
    window = min(count, warmups + samples)
    first, warm = (count - window) // 2, min(warmups, max(window - 1, 0))
    per = {key: {} for key in keys}
    for replay in range(len(keys) * replays):
        key = keys[replay % len(keys)]

        def on_frame(k, key=key):
            if not first <= k < first + window:
                return
            scene.camera.refresh_uniforms()
            sample = serialize(key)
            if k >= first + warm:
                per[key].setdefault(k, []).append(sample)

        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            replay_play(scene, target, on_frame)
    return {"checkpoint": target, "line": checkpoint["line_number"], "frames": count,
            "measured_frames": sorted(per[keys[0]]),
            **{key_name(*key): {"per_frame_p50": [float(np.median([ms for ms, _ in values]))
                                                  for _, values in sorted(by_frame.items())],
                                "sent": int(sum(sent for values in by_frame.values() for _, sent in values)),
                                "n": int(sum(len(values) for values in by_frame.values()))}
               for key, by_frame in per.items()}}


def serialize_by_frame(frames, key):
    """{(checkpoint, class): [serialize ms, ...]} for one serializer: a
    still, ticked or camera frame's median, or each measured play frame's."""
    out = {}
    for frame in frames:
        for cls in ("pausepoint", "ticked", "camera"):
            if cls in frame and isinstance(frame[cls], dict):
                out[(frame["checkpoint"], cls)] = [frame[cls][key]["p50"]]
        play = frame.get("play")
        if play and play[key]["per_frame_p50"]:
            out[(frame["checkpoint"], "play")] = play[key]["per_frame_p50"]
    return out


def gpu_class(row, ticked):
    """An episode_frames row's class, as browser_frames classes the same frame."""
    if row["phase"] in ("play", "camera"):
        return row["phase"]
    return "ticked" if ticked[row["checkpoint"]] else "pausepoint"


def gpu_by_frame(reports, variant, column="gpu_total_ms"):
    """{(checkpoint, class): (median, minimum, n)} of ``column`` over the
    variant's rows in every report given (gpu_total_ms from attribution
    runs, or the flag-off check's FLAG_OFF_GPU), warmups left out."""
    values = {}
    for report in reports:
        ticked = {frame["checkpoint"]: bool(frame.get("updaters_ticked")) for frame in report["frames"]}
        for row in report["variants"][variant]["samples"]:
            if row.get("warmup") or column not in row:
                continue
            values.setdefault((row["checkpoint"], gpu_class(row, ticked)), []).append(row[column])
    return {key: (float(np.median(v)), float(min(v)), len(v)) for key, v in values.items()}


def page_by_frame(rows):
    """{(checkpoint, class): (page_ms median, share sent)} over a browser
    variant's measured rows."""
    out = {}
    for cls in CLASSES:
        by_frame = {}
        for row in measured(rows, cls):
            by_frame.setdefault(row["checkpoint"], []).append(row)
        for checkpoint, frame_rows in by_frame.items():
            out[(checkpoint, cls)] = (float(np.median([row["page_ms"] for row in frame_rows])),
                                      float(np.mean([row.get("sent", True) for row in frame_rows])))
    return out


def complete_frames(serialize, browser, gpu, flip, column="gpu_total_ms"):
    """Per format, per stack (Phase A, then the flip) and per class: the
    frames' serialize, page and GPU parts (``column`` of the ``gpu``
    reports), their complete frame, and the class's medians (the module's
    docstring)."""
    browser_variant, gpu_variant = FLIPS[flip]
    names = {PHASE_A[0]: PHASE_A[1], browser_variant: gpu_variant}
    missing = [(name, fmt) for name in names for fmt in FORMATS
               if (name if fmt == 7 else name + "_delta") not in browser["variants"]]
    if missing:
        raise ValueError(f"the browser report lacks {missing}: record both variants with --deltas")
    result = {}
    for fmt in FORMATS:
        result[str(fmt)] = {}
        for name, ef_variant in names.items():
            python = serialize_by_frame(serialize["frames"], key_name(name, fmt))
            page = page_by_frame(browser["variants"][name if fmt == 7 else name + "_delta"]["rows"])
            gpus = gpu_by_frame(gpu, ef_variant, column)
            classes = {}
            for cls in CLASSES:
                frames = []
                for (checkpoint, frame_cls), values in sorted(python.items()):
                    key = (checkpoint, cls)
                    if frame_cls != cls or key not in page or key not in gpus:
                        continue
                    page_ms, sent = page[key]
                    gpu_p50, gpu_min, n = gpus[key]
                    for ms in values:
                        frames.append({"checkpoint": checkpoint, "serialize_ms": ms, "page_ms": page_ms,
                                       "sent": sent, "gpu_ms": sent * gpu_p50, "gpu_min_ms": sent * gpu_min,
                                       "gpu_n": n, "complete_ms": ms + page_ms + sent * gpu_p50,
                                       "complete_gpu_min_ms": ms + page_ms + sent * gpu_min})
                if frames:
                    classes[cls] = {"frames": len(frames), "checkpoints": len({f["checkpoint"] for f in frames}),
                                    **{column: float(np.median([f[column] for f in frames]))
                                       for column in ("serialize_ms", "page_ms", "sent", "gpu_ms", "gpu_min_ms",
                                                      "complete_ms", "complete_gpu_min_ms")},
                                    "per_frame": frames}
            result[str(fmt)][name] = classes
    return result


def pixels_of(reports, flip):
    """The flip's worst pixel pair against Phase A over the flag-off
    episode_frames reports given: each measured pausepoint, and each frame
    of a play's window strictly inside the play (episode_frames'
    pixel_frames), every frame counted once however many pausepoints or
    reports share it."""
    pair = f"{'patch' if flip == 'patches' else 'nets'}_vs_gpu_border"
    worst, frames = None, set()
    for report in reports:
        for frame in report["frames"]:
            play = frame.get("play") or {}
            for block, phase in ((frame, "pausepoint"), (play, "play")):
                value = block.get("pixels", {}).get(pair)
                if value is None:
                    continue
                if phase == "pausepoint":
                    frames.add(("pausepoint", frame["checkpoint"]))
                else:
                    frames.update(("play", play["checkpoint"], k) for k in play["pixel_frames"])
                fraction = value["fraction_pixels_rgb_over24"]
                if worst is None or fraction > worst["fraction_pixels_rgb_over24"]:
                    worst = {"checkpoint": frame["checkpoint"], "phase": phase, **value}
    return {"pair": pair, "frames": len(frames),
            "pausepoints": sum(key[0] == "pausepoint" for key in frames),
            "play_frames": sum(key[0] == "play" for key in frames), "worst": worst,
            "passes": worst is not None and worst["fraction_pixels_rgb_over24"] <= PIXEL_LIMIT}


def verdict(complete, flip, limit):
    """Per format and class, the flip's complete frame over Phase A's (and
    the same with each frame's GPU minimum), and whether it is within the
    limit; a class the flip or Phase A lacks is not judged."""
    flip_name = FLIPS[flip][0]
    out = {}
    for fmt, per in complete.items():
        out[fmt] = {}
        for cls in CLASSES:
            if cls in per[PHASE_A[0]] and cls in per[flip_name]:
                a, b = per[PHASE_A[0]][cls], per[flip_name][cls]
                ratio = b["complete_ms"] / a["complete_ms"] if a["complete_ms"] else None
                out[fmt][cls] = {"phase_a_ms": a["complete_ms"], "flip_ms": b["complete_ms"], "ratio": ratio,
                                 "ratio_gpu_min": (b["complete_gpu_min_ms"] / a["complete_gpu_min_ms"]
                                                   if a["complete_gpu_min_ms"] else None),
                                 "within_limit": ratio is not None and ratio <= limit}
    return out


def markdown_table(summary):
    """Per format and class: each stack's complete frame as its parts'
    medians (serialize + page + GPU, the GPU minimum in brackets), the
    frames, the ratio and whether it is within the limit; with the
    flag-off check, its ratio beside them."""
    flip_name = FLIPS[summary["flip"]][0]
    checked = summary.get("flag_off_check")
    head = ["format", "class", "frames", "phase_a complete = serialize + page + gpu (gpu min)",
            f"{flip_name} complete = serialize + page + gpu (gpu min)", "ratio (gpu min)",
            f"≤ {summary['limit']}"] + (["ratio, GPU part flag off"] if checked else [])
    lines = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]

    def cell(stats):
        return (f"{stats['complete_ms']:.2f} = {stats['serialize_ms']:.2f} + {stats['page_ms']:.2f} + "
                f"{stats['gpu_ms']:.2f} ({stats['gpu_min_ms']:.2f})")

    for fmt, per in summary["complete"].items():
        for cls in CLASSES:
            judged = summary["verdict"][fmt].get(cls)
            if judged is None:
                continue
            a, b = per[PHASE_A[0]][cls], per[flip_name][cls]
            ratio_min = judged["ratio_gpu_min"]
            cells = [fmt, cls, f"{a['frames']} ({a['checkpoints']})", cell(a), cell(b),
                     f"{judged['ratio']:.3f} ({ratio_min:.3f})" if ratio_min is not None else f"{judged['ratio']:.3f}",
                     "yes" if judged["within_limit"] else "**no**"]
            if checked:
                check = checked[fmt].get(cls)
                cells.append("–" if check is None or check["ratio"] is None else f"{check['ratio']:.3f}")
            lines.append("| " + " | ".join(cells) + " |")
    pixels = summary.get("pixels")
    if pixels:
        worst = pixels["worst"]
        where = "none" if worst is None else (
            f"{100 * worst['fraction_pixels_rgb_over24']:.4f}% over 24/255 (checkpoint {worst['checkpoint']}, "
            f"{worst['phase']}" + (f" frame {worst['play_frame']}" if "play_frame" in worst else "")
            + f", largest channel {worst['max_rgba']:.0f})")
        lines.append("")
        lines.append(f"Pixels, {pixels['pair']} over {pixels['frames']} frames ({pixels['pausepoints']} "
                     f"pausepoints, {pixels['play_frames']} inside plays): worst {where}; "
                     f"≤ {100 * PIXEL_LIMIT}%: {'yes' if pixels['passes'] else '**no**'}")
    return "\n".join(lines)


def run_fixtures(args):
    """tests.surface_fixtures' nets against grids, every fixture, one
    native driver per stack for the whole run."""
    from maniml.web.wgpu_renderer import WgpuRenderer
    from tests.surface_fixtures import SURFACE_FIXTURES, nets_against_grids

    for key in CLEARED:
        os.environ.pop(key, None)
    grids, nets = WgpuRenderer(), WgpuRenderer()
    fixtures = {}
    try:
        for name in SURFACE_FIXTURES:
            fixtures[name] = result = nets_against_grids(name, grids, nets)
            print(f"{name}: {100 * result['fraction_pixels_rgb_over24']:.4f}% over 24/255, largest channel "
                  f"{result['max_rgba']:.0f} ({result['grid_batches']} grid batches, {result['net_batches']} nets)",
                  flush=True)
    finally:
        grids.close()
        nets.close()
    worst = max(fixtures, key=lambda name: fixtures[name]["fraction_pixels_rgb_over24"])
    report = {"recorded_utc": datetime.now(timezone.utc).isoformat(), "command": sys.argv, "git": git_state(ROOT),
              "machine": {"platform": platform.platform(), "machine": platform.machine(), "node": platform.node()},
              "source_files_sha256": source_hashes([Path(__file__), ROOT / "tests/surface_fixtures.py",
                                                    *(ROOT / "maniml/web").glob("*.py")]),
              "limit": PIXEL_LIMIT, "worst": worst,
              "passes": fixtures[worst]["fraction_pixels_rgb_over24"] <= PIXEL_LIMIT,
              "fixtures": fixtures}
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "summary.json").write_text(json.dumps(report, indent=2) + "\n")


def play_python(mode):
    """A play's Python ms per frame under one mode (play_frames' per-frame
    medians): serialize_ms plus scene_ms, the entry by its serialize."""
    serialize = mode["per_frame"]["serialize_ms"]
    scene = mode["per_frame"].get("scene_ms") or [None] * len(serialize)
    return [ms + (between or 0.) for ms, between in zip(serialize, scene)]


def recorded(mode):
    """Whether a mode's first replay of a play sent a program: a full
    frame's program batch, a delta's scalars op, or a program among the
    middle frame's movers."""
    return bool(any(row.get("program_batches") or row.get("scalars_ops") for row in mode["carried_first_replay"])
                or mode.get("middle", {}).get("programs"))


def balanced(rows):
    """The candidate's total over the reference's with the turn order
    cancelled. play_frames alternates the mode that opens a play, and the
    first replay of a play is the first to run it after the play before, so
    each opener's plays carry what that turn costs or saves, the one way
    and the other: the geometric mean of the ratio over the plays the
    reference opened and the ratio over those the candidate opened holds no
    constant share of it. With a 95% interval from resampling the plays of
    each opener (INTERVAL_RESAMPLES, seeded, so a report reduces to the
    same numbers every time) and each opener's own ratio. ``rows`` are
    (opened by the reference, reference total, candidate total) per play;
    None unless each mode opened a play."""
    groups = [np.array([(ref, cand) for first, ref, cand in rows if first is wanted], dtype=float).reshape(-1, 2)
              for wanted in (True, False)]
    if not all(len(group) for group in groups):
        return None

    def ratio(group):
        return group[:, 1].sum() / group[:, 0].sum()

    def mean(first, second):
        return float(np.sqrt(ratio(first) * ratio(second)))

    rng = np.random.default_rng(INTERVAL_SEED)
    draws = [mean(*(group[rng.integers(0, len(group), len(group))] for group in groups))
             for _ in range(INTERVAL_RESAMPLES)]
    return {"ratio": mean(*groups),
            "interval_95": [float(np.percentile(draws, 2.5)), float(np.percentile(draws, 97.5))],
            "reference_opened": {"plays": len(groups[0]), "ratio": float(ratio(groups[0]))},
            "candidate_opened": {"plays": len(groups[1]), "ratio": float(ratio(groups[1]))}}


# The programs gate's groups of plays: every play, the plays where the
# candidate recorded a program, and the rest (where it recorded none, but
# still decided at each animation's begin and noted revisions each frame).
GROUPS = (("every_play", lambda recorded: True), ("recorded", bool), ("same_path", lambda recorded: not recorded))


def grouped(plays, reference, candidate):
    """Per group of GROUPS: its plays and frames, each mode's total over
    its frames per frame, the plain ratio of the totals and the balanced
    one. ``plays`` carry recorded, opened_by, frames and each mode's
    total."""
    out = {}
    for name, keep in GROUPS:
        chosen = [play for play in plays if keep(play["recorded"])]
        frames = sum(play["frames"] for play in chosen)
        totals = {mode: sum(play["totals"][mode] for play in chosen) for mode in (reference, candidate)}
        out[name] = {"plays": len(chosen), "frames": frames,
                     "per_frame_ms": {mode: total / frames for mode, total in totals.items()} if frames else None,
                     "ratio": totals[candidate] / totals[reference] if totals[reference] else None,
                     "balanced": balanced([(play["opened_by"] == reference, play["totals"][reference],
                                            play["totals"][candidate]) for play in chosen])}
    return out


def programs_gate(reports, renders):
    """Per play_frames report (an episode in one format): the reference
    mode (its first) and the candidate (its second), Python ms per play
    frame over every frame of every play, and over the plays where the
    candidate recorded a program and the rest (``grouped``: the plain ratio
    and the order-balanced one, which the gate reads), the entries' total
    apart, and the plays where the candidate is dearer; over the render
    reports, every play frame's pixels against the reference and the native
    complete frame (serialize_scene plus render(), complete_ms) grouped
    alike."""
    episodes = {}
    for report in reports:
        reference, candidate = report["modes"][:2]
        plays, values, entries = [], {reference: [], candidate: []}, {reference: 0., candidate: 0.}
        for play in report["plays"]:
            python = {mode: play_python(play["modes"][mode]) for mode in (reference, candidate)}
            for mode, series in python.items():
                entries[mode] += series[0]
                values[mode] += series
            plays.append({"play": play["play"], "line": play["line"], "frames": len(python[reference]),
                          "opened_by": play["opened_by"], "recorded": recorded(play["modes"][candidate]),
                          "middle": play["modes"][candidate].get("middle", {}),
                          "totals": {mode: sum(series) for mode, series in python.items()},
                          **{f"{mode}_ms": float(np.mean(series)) for mode, series in python.items()}})
        groups = grouped(plays, reference, candidate)
        every = groups["every_play"]
        dearer = [play for play in plays if play[f"{candidate}_ms"] > play[f"{reference}_ms"]]
        episodes[f"{report['scene']['name']} format {report['format']}"] = {
            "scene": report["scene"]["name"], "format": report["format"], "reference": reference,
            "candidate": candidate, "plays": len(plays), "frames": every["frames"],
            "per_frame_ms": every["per_frame_ms"], "ratio": every["ratio"], "balanced": every["balanced"],
            "lower": every["balanced"] is not None and every["balanced"]["ratio"] < 1,
            "measurably_lower": every["balanced"] is not None and every["balanced"]["interval_95"][1] < 1,
            "median_frame_ms": {mode: float(np.median(series)) for mode, series in values.items()},
            "entries_ms": entries, "recorded": groups["recorded"], "same_path": groups["same_path"],
            "plays_with_programs": sum(bool(play["middle"].get("programs")) for play in plays),
            "dearer_plays": [{key: play[key] for key in ("play", "line", "frames", f"{reference}_ms",
                                                           f"{candidate}_ms")} for play in dearer],
            "per_play": plays}
    worst, pixel_frames, native = None, 0, {}
    for report in renders:
        reference, candidate = report["modes"][:2]
        plays = []
        for play in report["plays"]:
            pixels = play["modes"][candidate].get("pixels")
            if pixels is not None:
                pixel_frames += pixels["frames"]
                if worst is None or (pixels["max_fraction_over_24"], pixels["max_channel_diff"]) > (
                        worst["max_fraction_over_24"], worst["max_channel_diff"]):
                    worst = {"scene": report["scene"]["name"], "play": play["play"], "line": play["line"], **pixels}
            complete = {mode: play["modes"][mode]["per_frame"].get("complete_ms") for mode in (reference, candidate)}
            if all(complete.values()):
                plays.append({"frames": len(complete[reference]), "opened_by": play["opened_by"],
                              "recorded": recorded(play["modes"][candidate]),
                              "totals": {mode: sum(series) for mode, series in complete.items()}})
        if plays:
            native[report["scene"]["name"]] = {"reference": reference, "candidate": candidate,
                                               **grouped(plays, reference, candidate)}
    return {"episodes": episodes, "native_complete": native,
            "pixels": {"frames": pixel_frames, "worst": worst,
                       "passes": worst is not None and worst["max_fraction_over_24"] <= PIXEL_LIMIT}}


def percent(ratio):
    return "–" if ratio is None else f"{100 * (ratio - 1):+.2f}%"


def balanced_cell(group):
    """A group's order-balanced change with its interval, or its plain
    change marked unbalanced where one mode opened every play."""
    judged = group["balanced"]
    if not group["plays"]:
        return "–"
    if judged is None:
        return f"{percent(group['ratio'])} (unbalanced)"
    low, high = judged["interval_95"]
    return f"{percent(judged['ratio'])} ({percent(low)} to {percent(high)})"


def programs_table(gate):
    lines = ["| episode, format | plays (recording a program) | frames | Python ms per play frame | "
             "order-balanced (95%) | plays recording one | plays on the same path | median frame | "
             "entries' total | dearer plays | lower (measurably) |", "|---|---|---|---|---|---|---|---|---|---|---|"]
    for name, episode in gate["episodes"].items():
        reference, candidate = episode["reference"], episode["candidate"]

        def pair(values):
            return f"{values[reference]:.3f} → {values[candidate]:.3f}"

        def group(data):
            return "–" if data["ratio"] is None else f"{balanced_cell(data)}, {data['plays']} plays"

        lines.append("| " + " | ".join([
            name, f"{episode['plays']} ({episode['recorded']['plays']})", str(episode["frames"]),
            pair(episode["per_frame_ms"]) + f" ({percent(episode['ratio'])})", balanced_cell(episode),
            group(episode["recorded"]), group(episode["same_path"]), pair(episode["median_frame_ms"]),
            pair(episode["entries_ms"]), str(len(episode["dearer_plays"])),
            ("yes" if episode["lower"] else "**no**") + (" (yes)" if episode["measurably_lower"] else " (no)")]) + " |")
    if gate["native_complete"]:
        lines += ["", "| native complete frame, render runs | every play | plays recording one | "
                  "plays on the same path |", "|---|---|---|---|"]
        for name, native in gate["native_complete"].items():
            lines.append("| " + " | ".join([name] + [balanced_cell(native[group]) for group, _ in GROUPS]) + " |")
    pixels = gate["pixels"]
    worst = pixels["worst"]
    lines += ["", f"Pixels over {pixels['frames']} play frames: worst "
              + (f"{100 * worst['max_fraction_over_24']:.4f}% over 24/255, largest channel {worst['max_channel_diff']} "
                 f"({worst['scene']} play {worst['play']}, line {worst['line']})" if worst else "none")
              + f"; ≤ {100 * PIXEL_LIMIT}%: {'yes' if pixels['passes'] else '**no**'}"]
    return "\n".join(lines)


def run_programs(args):
    reports = [json.loads((Path(directory) / "report.json").read_text()) for directory in args.plays]
    renders = [json.loads((Path(directory) / "report.json").read_text()) for directory in args.render]
    for directory, report in zip(args.render, renders):
        if not report.get("render") or report.get("gpu_timestamps"):
            raise SystemExit(f"{directory} is not a --render run without MANIML_GPU_TIMESTAMPS")
    for directory, report in zip([*args.plays, *args.render], [*reports, *renders]):
        if any("opened_by" not in play for play in report["plays"]):
            raise SystemExit(f"{directory} opened every play with its first mode: re-run play_frames")
    gate = programs_gate(reports, renders)
    gate["inputs"] = {"plays": [str(path) for path in args.plays], "render": [str(path) for path in args.render]}
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "report.json").write_text(json.dumps(gate, indent=2) + "\n")
    summary = {**gate, "episodes": {name: {key: value for key, value in episode.items() if key != "per_play"}
                                    for name, episode in gate["episodes"].items()}}
    (args.output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    table = programs_table(gate)
    (args.output / "summary.md").write_text(table + "\n")
    print(table)


def source_hashes(paths):
    return {str(path.relative_to(ROOT) if path.is_relative_to(ROOT) else path): sha256(path.read_bytes()).hexdigest()
            for path in paths}


def run_serialize(args):
    scene_path = Path(os.path.abspath(args.scene[0]))
    if not scene_path.is_file():
        raise SystemExit(f"no scene file at {scene_path}")
    os.environ.update(ENVIRONMENT)
    for key in CLEARED:
        os.environ.pop(key, None)
    args.output.mkdir(parents=True, exist_ok=True)
    from maniml.web.geometry import _jsonable

    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
        scene, error = load_episode(scene_path, args.scene[1])
    checkpoints = scene.animation_checkpoints
    indices = select_frames(checkpoints, args.every, args.max_frames)
    hashes = source_hashes([Path(__file__), ROOT / "benchmarks/episode_frames.py",
                            ROOT / "benchmarks/browser_frames.py", *(ROOT / "maniml/web").glob("*.py"),
                            ROOT / "maniml/utils/programs.py", scene_path])
    report = {
        "recorded_utc": datetime.now(timezone.utc).isoformat(), "command": sys.argv, "flip": args.flip,
        "stacks": {name: {"renderer": renderer, "environment": environment}
                   for name, renderer, environment in stacks(args.flip)},
        "scene": {"path": str(scene_path), "name": args.scene[1], "checkpoint_count": len(checkpoints),
                  "measured_checkpoints": indices, "construct_error": error},
        "git": git_state(ROOT),
        "machine": {"platform": platform.platform(), "machine": platform.machine(), "node": platform.node()},
        "python": platform.python_version(), "numpy": np.__version__,
        "environment": {key: value for key, value in os.environ.items() if key.startswith("MANIML_")},
        "samples": args.samples, "warmups": args.warmups, "replays": args.replays, "every": args.every,
        "max_frames": args.max_frames, "tick_updaters": args.tick_updaters, "play_frames": args.play_frames,
        "camera_moves": args.camera_moves, "source_files_sha256": hashes,
    }

    def log(frame):
        print(json.dumps({key: value for key, value in frame.items() if key not in ("play", "camera")}), flush=True)

    report["frames"] = measure_serialize(scene, indices, args.flip, samples=args.samples, warmups=args.warmups,
                                         replays=args.replays, tick_updaters=args.tick_updaters,
                                         play_frames=args.play_frames, camera_moves=args.camera_moves, log=log)
    report["source_files_unchanged_during_run"] = source_hashes(
        [ROOT / path if not Path(path).is_absolute() else Path(path) for path in hashes]) == hashes
    (args.output / "report.json").write_text(json.dumps(report, indent=2, default=_jsonable) + "\n")


def run_complete(args):
    def load(directory):
        return json.loads((Path(directory) / "report.json").read_text())

    serialize, browser = load(args.serialize), load(args.browser)
    gpu, pixels = [load(directory) for directory in args.gpu], [load(directory) for directory in args.pixels]
    measured_frames = serialize["scene"]["measured_checkpoints"]
    for name, report in (("browser", browser), *((f"gpu {i}", r) for i, r in enumerate(gpu)),
                         *((f"pixels {i}", r) for i, r in enumerate(pixels))):
        if report["scene"]["measured_checkpoints"] != measured_frames:
            raise SystemExit(f"{name} measured other frames than the serialize run")
    for index, report in enumerate(gpu):
        if not report.get("gpu_timestamps"):
            raise SystemExit(f"gpu report {index} is not an attribution run (--gpu-timestamps)")
    for index, report in enumerate(pixels):
        if report.get("gpu_timestamps"):
            raise SystemExit(f"pixels report {index} is an attribution run; the pixel pairs come from a flag-off run")
        if any("pixel_frames" not in frame["play"] for frame in report["frames"] if frame.get("play")):
            raise SystemExit(f"pixels report {index} compares a play's last sampled frame, which may be its "
                             "landing: re-run episode_frames")
    complete = complete_frames(serialize, browser, gpu, args.flip)
    summary = {
        "flip": args.flip, "limit": args.limit, "scene": serialize["scene"],
        "inputs": {"serialize": str(args.serialize), "browser": str(args.browser),
                   "gpu": [str(path) for path in args.gpu], "pixels": [str(path) for path in args.pixels]},
        "input_commits": {"serialize": serialize["git"], "browser": browser.get("git"),
                          "gpu": [report.get("git") for report in gpu],
                          "pixels": [report.get("git") for report in pixels]},
        "verdict": verdict(complete, args.flip, args.limit),
        # The same frames with the GPU part the flag-off runs' wall clock:
        # the stamps cost each pass ~30 µs, so the attribution runs charge a
        # stack of more passes more (benchmarks/README.md, "Flip gates").
        "flag_off_check": (verdict(complete_frames(serialize, browser, pixels, args.flip, FLAG_OFF_GPU), args.flip,
                                   args.limit) if pixels else None),
        "pixels": pixels_of(pixels, args.flip) if pixels else None,
        "complete": {fmt: {name: {cls: {key: value for key, value in stats.items() if key != "per_frame"}
                                      for cls, stats in classes.items()}
                           for name, classes in per.items()} for fmt, per in complete.items()},
    }
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "report.json").write_text(json.dumps({**summary, "complete": complete}, indent=2) + "\n")
    (args.output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    table = markdown_table(summary)
    (args.output / "summary.md").write_text(table + "\n")
    print(table)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    serialize = commands.add_parser("serialize", help="serialize_ms per frame and class, the stacks taking turns")
    serialize.add_argument("--flip", choices=tuple(FLIPS), required=True)
    serialize.add_argument("--scene", nargs=2, metavar=("FILE", "SCENE"), required=True,
                           help="episode file and scene class")
    serialize.add_argument("--output", type=Path, required=True)
    serialize.add_argument("--samples", type=int, default=12)
    serialize.add_argument("--warmups", type=int, default=3)
    serialize.add_argument("--replays", type=int, default=4, help="replays of each play per serializer")
    serialize.add_argument("--every", type=int, default=1)
    serialize.add_argument("--max-frames", type=int, default=12)
    serialize.add_argument("--tick-updaters", action="store_true")
    serialize.add_argument("--play-frames", action="store_true")
    serialize.add_argument("--camera-moves", action="store_true")
    complete = commands.add_parser("complete", help="the complete frame per class, and the verdict")
    complete.add_argument("--flip", choices=tuple(FLIPS), required=True)
    complete.add_argument("--serialize", type=Path, required=True, help="this module's serialize output")
    complete.add_argument("--browser", type=Path, required=True,
                          help="browser_frames --variants phase_a <flip's> --deltas --rounds N --realm main")
    complete.add_argument("--gpu", type=Path, nargs="+", required=True,
                          help="episode_frames --variants <flip's> gpu_border --gpu-timestamps runs")
    complete.add_argument("--pixels", type=Path, nargs="*", default=[],
                          help="episode_frames --variants <flip's> gpu_border runs without the flag")
    complete.add_argument("--limit", type=float, required=True,
                          help="the flip's complete frame over Phase A's that passes, per class")
    complete.add_argument("--output", type=Path, required=True)
    fixtures = commands.add_parser("fixtures", help="every Surface fixture drawn from grids and from nets")
    fixtures.add_argument("--output", type=Path, required=True)
    gate = commands.add_parser("programs", help="Python ms per play frame and pixels, from play_frames reports")
    gate.add_argument("--plays", type=Path, nargs="+", required=True,
                      help="play_frames --every-play --modes off <candidate> runs, one per episode and format")
    gate.add_argument("--render", type=Path, nargs="*", default=[], help="play_frames --render runs")
    gate.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "serialize":
        if min(args.samples, args.warmups, args.replays, args.every, args.max_frames) < 1:
            parser.error("samples, warmups, replays, every and max-frames must be positive")
        run_serialize(args)
    elif args.command == "complete":
        run_complete(args)
    elif args.command == "programs":
        run_programs(args)
    else:
        run_fixtures(args)


if __name__ == "__main__":
    main()

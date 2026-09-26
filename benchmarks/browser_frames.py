"""The browser driver on frames of a real course episode, without a GPU.

    python -m benchmarks.browser_frames \\
        --scene /abs/path/Blocks/B2_Supply/03_Code.py EpisodeB2 \\
        --output /private/tmp/browser-b2 --tick-updaters --play-frames

episode_frames.py measures the native mirror of a frame; this measures the
other half of a live one, the JavaScript the browser runs on every geometry
message (docs/phase_b4_plan.md, B4.6). The episode is loaded and its frames
chosen as episode_frames chooses them (its pausepoints, each restored and
serialized warmups + samples times, with its updaters ticking before every
round under --tick-updaters, and under --play-frames the middle frames of
the play that leads into it), so the two harnesses describe the same
frames. Each round is one geometry message, serialized as the viewer sends
it, with one GeometryCache per variant so cached batches and retained
sources carry between messages as they do on a socket. The stream is
written in the export recorder's format (scene.json + scene.bin.gz, which
geometry_recording.js and the player read) and then played in order through
the real maniml/web/static/webgpu.js in Node on the counting fake device
(benchmarks/browser_frames.cjs on tests/webgpu_fake_device.cjs): per frame,
the JavaScript milliseconds around the driver's render and every WebGPU
call it made. The variants are streams of the same frames: phase_a from the
default renderer, phase_b from the whole Phase B stack (patch fills, net
surfaces, GPU programs) through the same driver.
"""

import argparse
from datetime import datetime, timezone
import gzip
from hashlib import sha256
from itertools import count
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
from time import perf_counter
from unittest.mock import patch

import numpy as np

from benchmarks.episode_frames import (ROOT, family, git_state, load_episode, play_before, play_frame_count,
                                       replay_play, select_frames, show_frame)


VARIANTS = ("phase_a", "phase_b")
# What the recording process sets for each stream; the serializer and the
# animations read these, so a stream is self-consistent whatever the
# caller's environment says.
ENVIRONMENTS = {
    "phase_a": {"MANIML_FILL": "meshes", "MANIML_SURFACE": "grids", "MANIML_PROGRAMS": "off",
                "MANIML_BORDER_GENERATOR": "gpu"},
    "phase_b": {"MANIML_FILL": "patches", "MANIML_SURFACE": "nets", "MANIML_PROGRAMS": "gpu",
                "MANIML_BORDER_GENERATOR": "gpu"},
}
# The kinds of row, as the viewer draws them: the still redraw of a
# pausepoint, the same with its updaters ticking, a frame of a play, and
# the first message after a restore, delta-encoded against the previous
# message of the stream as a seek is against the frame on screen (its
# cached_batches say how much the cache still held).
CLASSES = ("pausepoint", "ticked", "play", "cold")
# The columns summary.json reduces per class and per frame, in this order.
COLUMNS = ("js_ms", "serialize_ms", "wire_bytes", "batches", "cached_batches", "draws", "set_pipeline_calls",
           "pipeline_switches", "set_bind_group_calls", "bind_groups_created", "buffers_created", "buffers_destroyed",
           "uniform_writes", "compute_dispatches", "compute_passes", "render_passes", "bytes_uploaded")
HARNESS = Path(__file__).with_name("browser_frames.cjs")
FAKE_DEVICE = ROOT / "tests" / "webgpu_fake_device.cjs"


def frame_class(row):
    if row["phase"] == "play":
        return "play"
    if row["cold"]:
        return "cold"
    return "ticked" if row["updaters_ticked"] else "pausepoint"


def measured(rows, cls):
    """The rows a class reduces: warmups excluded, except that the cold row
    of a frame (its first round, a warmup) is the cold class."""
    return [row for row in rows if frame_class(row) == cls and (cls == "cold" or not row["warmup"])]


def summarize(rows):
    """Median and minimum of the summary columns present in ``rows``, with
    ``n``; the shape episode_frames.summarize writes."""
    result = {}
    for key in COLUMNS:
        values = [row[key] for row in rows if key in row]
        if values:
            result[key] = {"p50": float(np.median(values)), "min": float(min(values)), "n": len(values)}
    return result


def record_stream(scene, indices, samples, warmups, *, tick_updaters=False, play_frames=False):
    """Serialize the chosen frames as the viewer would send them: per frame
    the pausepoint's rounds (warmups then samples; under ``tick_updaters``
    the scene's updaters tick 1/fps before every round on a frame that has
    any), then under ``play_frames`` the middle frames of the play leading
    into it. Returns the messages, one stream entry per message (the
    export's ``len`` and ``segment`` plus what the frame is) and one block
    per frame. One cache for the whole stream, never reset, as one viewer
    session keeps one: every message is a delta against the one before it,
    so the first round after a restore re-sends what the cache no longer
    holds (as a seek does; the message before it is the last recorded
    frame of the previous frame's play) and the rest are cached."""
    from maniml.web.geometry import GeometryCache, serialize_scene

    cache = GeometryCache()
    checkpoints = scene.animation_checkpoints
    messages, entries, frames, segments = [], [], [], count()

    def take(fields, segment):
        started = perf_counter()
        message = serialize_scene(scene, cache, renderer="triangles")
        entries.append({"len": len(message), "segment": segment, **fields,
                        "serialize_ms": 1000 * (perf_counter() - started)})
        messages.append(message)

    for position, index in enumerate(indices):
        checkpoint = checkpoints[index]
        show_frame(scene, index)
        live = bool(scene.should_update_mobjects())
        ticked = bool(tick_updaters and live)
        fields = dict(frame=position, checkpoint=index)
        frame = {**fields, "line": checkpoint["line_number"], "name": checkpoint.get("name"),
                 "stop": bool(checkpoint.get("stop")),
                 "drawn_mobjects": sum(mob.has_points() for mob in family(scene)),
                 "should_update_mobjects": live, "updaters_ticked": ticked, "rounds": warmups + samples}
        segment = next(segments)
        for local in range(warmups + samples):
            if ticked:
                # The idle loop's tick: the updaters regenerate what they
                # drive, and the message carries the regeneration.
                scene.update_mobjects(1 / scene.camera.fps)
                scene.camera.refresh_uniforms()
            take(dict(fields, phase="pausepoint", iteration=local, warmup=local < warmups, cold=local == 0,
                      updaters_ticked=ticked), segment)
        if play_frames:
            frame["play"] = record_play(scene, index, samples, warmups, take, fields, segments)
        frames.append(frame)
    return messages, entries, frames


def record_play(scene, index, samples, warmups, take, fields, segments):
    """The play leading into checkpoint ``index`` on consecutive frames
    centred on its middle, ``warmups`` frames then ``samples`` recorded
    ones (fewer when the play is shorter), one message per frame with the
    scene mid-interpolation: episode_frames.measure_play's window. The
    play is the next segment of the stream; none is taken when nothing
    played."""
    checkpoints = scene.animation_checkpoints
    target = play_before(checkpoints, index)
    play = {"checkpoint": target, "line": None, "run_time": None, "frames": 0, "measured_alphas": []}
    if target is None:
        return play
    segment = next(segments)
    run_time, fps = checkpoints[target]["run_time"], scene.camera.fps
    frames = play_frame_count(fps, run_time)
    play.update(line=checkpoints[target]["line_number"], run_time=run_time, frames=frames)
    window = min(frames, warmups + samples)
    first, warm = (frames - window) // 2, min(warmups, max(window - 1, 0))

    def on_frame(k):
        if not first <= k < first + window:
            return
        local = k - first
        scene.camera.refresh_uniforms()
        alpha = (k + 1) / fps / run_time
        if local >= warm:
            play["measured_alphas"].append(alpha)
        take(dict(fields, phase="play", play_checkpoint=target, play_frame=k, alpha=alpha, iteration=local,
                  warmup=local < warm, cold=False, updaters_ticked=False), segment)

    replay_play(scene, target, on_frame)
    return play


def write_stream(directory, scene, messages, entries, **about):
    """The export recorder's folder (web/export.py _write_export), so the
    player and geometry_recording.js read it: scene.bin.gz is the messages
    end to end and scene.json's frames carry each one's length and
    segment. The export's segments are its plays, so its ``lines`` are the
    checkpoints'; here a segment is a recorded group, so each names its own
    line (the checkpoint's for a pausepoint group, the play's for a play
    group) and the player's chips name the frames. The entries' other keys
    and ``about`` say what the stream is."""
    from maniml.web.geometry import GEOMETRY_FORMAT_VERSION

    directory.mkdir(parents=True, exist_ok=True)
    with gzip.open(directory / "scene.bin.gz", "wb", compresslevel=6) as file:
        for message in messages:
            file.write(message)
    checkpoints = scene.animation_checkpoints
    first = {}
    for entry in entries:
        first.setdefault(entry["segment"], entry)
    lines = [checkpoints[entry["play_checkpoint"] if entry["phase"] == "play" else entry["checkpoint"]].get("line_number")
             for _, entry in sorted(first.items())]
    meta = {"format_version": GEOMETRY_FORMAT_VERSION, "scene": type(scene).__name__, "fps": int(scene.camera.fps),
            "frames": entries, "segments": len(lines), "lines": lines, "harness": "browser_frames", **about}
    (directory / "scene.json").write_text(json.dumps(meta) + "\n")
    return meta


def replay_stream(directory, timeout=1800):
    """browser_frames.cjs over the stream: Node's version, the driver's init
    time and one row per frame."""
    result = subprocess.run(["node", str(HARNESS), str(directory)], capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0:
        raise RuntimeError(f"browser_frames.cjs failed on {directory}:\n{result.stdout}\n{result.stderr}")
    return json.loads(result.stdout)


def join_rows(entries, replayed):
    """One row per frame: the stream entry's description and Python
    serialize time with the driver's time and counts. A cache miss means
    the stream referred to a batch it never sent, which the recorder
    cannot do, so it is an error rather than a column."""
    if len(replayed) != len(entries):
        raise RuntimeError(f"the replay returned {len(replayed)} rows for {len(entries)} frames")
    rows = []
    for entry, played in zip(entries, replayed):
        if played["cache_misses"]:
            raise RuntimeError(f"frame {played['index']} missed the browser cache")
        row = {key: value for key, value in entry.items() if key != "len"}
        row.update((key, value) for key, value in played.items() if key not in ("index", "cache_misses"))
        rows.append(row)
    return rows


def frame_stats(rows):
    """The classes reduced over one frame's rows; the cold row itself is
    kept beside them, the seek into the frame from the one recorded before
    it (its ``cached_batches`` say from how far)."""
    stats = {cls: summarize(measured(rows, cls)) for cls in CLASSES if measured(rows, cls)}
    cold = [row for row in rows if row["cold"]]
    if cold:
        stats["cold_row"] = cold[0]
    return stats


def assemble(report, variant, rows, frames, *, environment, stream):
    """Put a variant's rows into the report: its classes over every
    measured row, and on each frame block that frame's classes. The frame
    blocks are the first variant's (every variant records the same frames).
    Returns the variant's classes."""
    classes = {cls: summarize(measured(rows, cls)) for cls in CLASSES if measured(rows, cls)}
    report["variants"][variant] = {"environment": environment, "stream": stream, "classes": classes, "rows": rows}
    if not report["frames"]:
        report["frames"] = [{**frame, "variants": {}} for frame in frames]
    for frame in report["frames"]:
        frame["variants"][variant] = frame_stats([row for row in rows if row["frame"] == frame["frame"]])
    return classes


def _cell(stats, key, fmt="{:.2f}"):
    return fmt.format(stats[key]["p50"]) if key in stats else "–"


def markdown_table(summary):
    """One line per frame and class present, each variant's median
    JavaScript ms (with its minimum), batches (and the cached among them),
    draws, setPipeline calls, bind groups created, buffers
    created/destroyed, uniform writes and KB uploaded; closing lines over
    every measured row of each class."""
    variants = list(summary["variants"])
    head = ["frame", "checkpoint", "line", "name", "class"]
    head += [f"{variant} {column}" for variant in variants
             for column in ("js p50/min", "batches (cached)", "draws", "setPipeline", "bindGroups", "buffers +/-",
                            "uniform writes", "KB up")]
    lines = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]

    def line(cells, per_variant):
        for variant in variants:
            stats = per_variant.get(variant, {})
            js = f"{stats['js_ms']['p50']:.2f} / {stats['js_ms']['min']:.2f}" if "js_ms" in stats else "–"
            batches = (f"{stats['batches']['p50']:.0f} ({stats['cached_batches']['p50']:.0f})"
                       if "batches" in stats else "–")
            cells += [js, batches, _cell(stats, "draws", "{:.0f}"),
                      _cell(stats, "set_pipeline_calls", "{:.0f}"), _cell(stats, "bind_groups_created", "{:.0f}"),
                      (f"{stats['buffers_created']['p50']:.0f} / {stats['buffers_destroyed']['p50']:.0f}"
                       if "buffers_created" in stats else "–"),
                      _cell(stats, "uniform_writes", "{:.0f}"),
                      f"{stats['bytes_uploaded']['p50'] / 1024:.1f}" if "bytes_uploaded" in stats else "–"]
        lines.append("| " + " | ".join(cells) + " |")

    for frame in summary["frames"]:
        cells = [str(frame["frame"]), str(frame["checkpoint"]), str(frame["line"]), frame.get("name") or ""]
        for cls in CLASSES:
            per_variant = {variant: frame["variants"][variant][cls] for variant in variants
                           if cls in frame["variants"].get(variant, {})}
            if per_variant:
                label = cls
                if cls == "play":
                    alphas = frame["play"]["measured_alphas"]
                    label = f"play α {alphas[0]:.2f}–{alphas[-1]:.2f}"
                line([*cells, label], per_variant)
    for cls in CLASSES:
        per_variant = {variant: summary["variants"][variant]["classes"][cls] for variant in variants
                       if cls in summary["variants"][variant]["classes"]}
        if per_variant:
            line(["all", "", "", "", cls], per_variant)
    return "\n".join(lines)


def summary_of(report):
    """report.json without the per-frame rows."""
    summary = {key: value for key, value in report.items() if key != "variants"}
    if "scene" in summary:
        summary["scene"] = {key: value for key, value in summary["scene"].items() if key != "checkpoints"}
    summary["variants"] = {variant: {key: value for key, value in data.items() if key != "rows"}
                           for variant, data in report.get("variants", {}).items()}
    return summary


def scope(tick_updaters, play_frames):
    """The report's own caveats, worded for the run's switches."""
    return {
        "frame_selection": (
            "episode_frames.select_frames: pausepoints of a pause-anchored file, else every --every-th checkpoint "
            "after the empty first one, thinned evenly to --max-frames keeping the last; each restored with one "
            "dt=0 updater pass as a navigation shows it, so the two harnesses describe the same frames. "
            + ("With --play-frames the play leading into each pausepoint is replayed from the checkpoint before it "
               "at camera.fps and its middle frames are recorded, warmups then samples, as episode_frames samples "
               "them." if play_frames else "No play frames (--play-frames): the stream holds no mid-animation state.")),
        "stream_scope": (
            "Every round is one geometry message serialized as the viewer sends it (serialize_scene, renderer "
            "triangles, the variant's MANIML_* switches in the environment), one GeometryCache per stream and never "
            "reset, so every message is a delta against the one before it: the first message after a restore "
            "re-sends what the cache no longer holds (cached_batches says how much it still held) and the rest carry "
            "cached batches with the camera and uniforms. Per frame the stream is that first message, the stills, "
            "then the play into the same checkpoint, so the first message follows the last recorded frame of the "
            "previous measured frame's play (a seek from there; the viewer sees a play and then its landing) and "
            "the play's warmup frames follow the destination's stills. A repeated still frame is a message the "
            "viewer sends on a camera change or an updater tick; at rest without either it sends nothing, and that "
            "silence is not a row here. "
            + ("On a frame with updaters (should_update_mobjects) every round is preceded by "
               "scene.update_mobjects(1/fps), as the idle loop ticks it, so its messages carry the regeneration "
               "(updaters_ticked); frames without updaters repeat the still redraw."
               if tick_updaters else
               "Sources are static between rounds (--tick-updaters off): the pausepoint rows are the still redraw, "
               "not the live per-frame cost at a pausepoint whose mobjects have updaters.")),
        "timing_scope": (
            "js_ms is performance.now around ManimlWGPU.render in Node on the counting fake device "
            "(tests/webgpu_fake_device.cjs, validate: false): the header parse, preparePaints/Programs/Borders/Nets, "
            "the encode loop, the fake queue.submit and the retirement sweeps. Not in it: Dawn's validation and "
            "command encoding behind each call, the GPU, the canvas present, texture decoding (createImageBitmap "
            "is a stub) and the viewer's second header parse in renderer_selection.js; the live viewer's "
            "performance.measure('maniml:render') spans that parse and the queue wait as well. Node's garbage "
            "collector runs where it runs and V8 warms over the first frames of the stream: read medians with "
            "minima, and the warmup rounds are excluded. serialize_ms is Python's serialize_scene for the same "
            "message in the recording process, unpaced, cache warm after the first round; episode_frames.py owns "
            "the Python measurement. Component medians must not be added."),
        "count_scope": (
            "Counts are the fake device's tallies of the driver's calls per frame: draws (draw and drawIndexed), "
            "set_pipeline_calls and the pipeline_switches among them (a call naming a pipeline other than the "
            "pass's current one), set_bind_group_calls, bind_groups_created, buffers_created and buffers_destroyed "
            "(device.createBuffer and GPUBuffer.destroy, per-frame temporaries included), uniform_writes (uniform "
            "buffers created with their data plus queue.writeBuffer calls into one), compute_dispatches and "
            "compute_passes, render_passes, bytes_uploaded (mapped-at-creation bytes plus writeBuffer bytes); "
            "wire_bytes is the whole message and batches its header's batch count. A cache miss fails the run."),
        "class_scope": (
            "pausepoint: the still redraw rounds after the warmups; ticked: the same rounds on a frame whose "
            "updaters tick before each; play: the recorded middle frames of the play into the pausepoint; cold: "
            "the first message after each restore, delta-encoded against the previous message of the stream as a "
            "seek is against the frame on screen, so it uploads what the cache no longer held (cached_batches and "
            "bytes_uploaded say how much; only the stream's first message, or a frame whose objects all changed, "
            "uploads every batch), its own class and excluded from the others. Warmup rounds are excluded from "
            "every class but cold."),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--scene", nargs=2, metavar=("FILE", "SCENE"), required=True,
                        help="episode file and scene class")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--variants", nargs="+", choices=VARIANTS, default=list(VARIANTS),
                        help="the streams to record and play, each from the same frames")
    parser.add_argument("--samples", type=int, default=12)
    parser.add_argument("--warmups", type=int, default=3)
    parser.add_argument("--every", type=int, default=1, help="checkpoint stride for a file without pausepoints")
    parser.add_argument("--max-frames", type=int, default=12)
    parser.add_argument("--tick-updaters", action="store_true",
                        help="tick a pausepoint's updaters 1/fps before every round, as the idle loop does")
    parser.add_argument("--play-frames", action="store_true",
                        help="also record consecutive frames of the play leading into each pausepoint")
    args = parser.parse_args(argv)
    if min(args.samples, args.warmups, args.every, args.max_frames) < 1:
        parser.error("samples, warmups, every and max-frames must be positive")
    if shutil.which("node") is None:
        parser.error("node is needed to play the stream through the browser driver")
    scene_path = Path(args.scene[0]).resolve()
    if not scene_path.is_file():
        parser.error(f"no scene file at {scene_path}")
    args.output.mkdir(parents=True, exist_ok=True)

    from maniml.web.geometry import _jsonable, parse_geometry_message

    scene, error = load_episode(scene_path, args.scene[1])
    checkpoints = scene.animation_checkpoints
    indices = select_frames(checkpoints, args.every, args.max_frames)
    paths = [Path(__file__), HARNESS, FAKE_DEVICE, ROOT / "benchmarks/episode_frames.py",
             ROOT / "maniml/web/static/webgpu.js", ROOT / "maniml/web/static/renderer_selection.js",
             *(ROOT / "maniml/web").glob("*.py"), *(ROOT / "maniml/web/static/wgsl").glob("*.wgsl"), scene_path]
    hashes = {str(path.relative_to(ROOT) if path.is_relative_to(ROOT) else path): sha256(path.read_bytes()).hexdigest()
              for path in paths}
    selection = {"samples": args.samples, "warmups": args.warmups, "every": args.every, "max_frames": args.max_frames,
                 "tick_updaters": args.tick_updaters, "play_frames": args.play_frames}
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
        "python": platform.python_version(), "numpy": np.__version__, **selection,
        "variants_in_order": list(args.variants), "environments": {variant: ENVIRONMENTS[variant] for variant in args.variants},
        "source_files_sha256": hashes, **scope(args.tick_updaters, args.play_frames),
        "frames": [], "variants": {},
    }
    for variant in args.variants:
        environment = ENVIRONMENTS[variant]
        with patch.dict(os.environ, environment):
            messages, entries, frames = record_stream(scene, indices, args.samples, args.warmups,
                                                      tick_updaters=args.tick_updaters, play_frames=args.play_frames)
        directory = args.output / variant
        write_stream(directory, scene, messages, entries, variant=variant, environment=environment,
                     frame_selection=selection)
        header, _ = parse_geometry_message(messages[0])
        stream = {"directory": str(directory), "frames": len(messages), "bytes": sum(map(len, messages)),
                  "gzip_bytes": (directory / "scene.bin.gz").stat().st_size, "resolution": header["resolution"],
                  "samples": header["samples"], "supersample": header.get("supersample")}
        del messages
        print(f"{variant}: recorded {stream['frames']} frames, {stream['bytes'] / 1e6:.1f} MB", flush=True)
        replayed = replay_stream(directory)
        rows = join_rows(entries, replayed["frames"])
        report["node"] = replayed["node"]
        stream["init_ms"] = replayed["init_ms"]
        classes = assemble(report, variant, rows, frames, environment=environment, stream=stream)
        (args.output / "report.json").write_text(json.dumps(report, indent=2, default=_jsonable) + "\n")
        print(f"{variant}: played in {replayed['node']}; " + ", ".join(
            f"{cls} js p50 {stats['js_ms']['p50']:.2f} ms (n={stats['js_ms']['n']})" for cls, stats in classes.items()),
            flush=True)
    report["source_files_unchanged_during_run"] = all(
        sha256((ROOT / path if not Path(path).is_absolute() else Path(path)).read_bytes()).hexdigest() == value
        for path, value in hashes.items())
    (args.output / "report.json").write_text(json.dumps(report, indent=2, default=_jsonable) + "\n")
    summary = summary_of(report)
    (args.output / "summary.json").write_text(json.dumps(summary, indent=2, default=_jsonable) + "\n")
    table = markdown_table(summary)
    (args.output / "summary.md").write_text(table + "\n")
    print(table)
    if error is not None:
        print(f"construct() stopped at checkpoint {error['checkpoint_reached']}: {error['error']}", file=sys.stderr)


if __name__ == "__main__":
    main()

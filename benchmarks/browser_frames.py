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
(benchmarks/browser_frames.cjs on tests/webgpu_fake_device.cjs), through the
viewer's renderer selection as a page draws it: per frame, the JavaScript
milliseconds around the driver's render and around the page's (the
selection's routing included) and every WebGPU call the driver made. Under
--play-edges the stream then carries, per play, the frames the play window
leaves out: the play's first frame and its landing. The variants are
streams of the same frames: phase_a from the default renderer, phase_b from
the whole Phase B stack (patch fills, net surfaces, GPU programs) through
the same driver.
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
# caller's environment says. phase_b_rows is phase_b with the patch fill's
# records sent as rows (MANIML_PATCH_SOURCE=rows, docs/phase_b4_plan.md
# B5.1), and phase_a_strokes phase_a with its paths without fill animated
# as GPU programs (MANIML_PROGRAMS=strokes, B5.3), each recorded when
# --variants names it.
ENVIRONMENTS = {
    "phase_a": {"MANIML_FILL": "meshes", "MANIML_SURFACE": "grids", "MANIML_PROGRAMS": "off",
                "MANIML_BORDER_GENERATOR": "gpu"},
    "phase_b": {"MANIML_FILL": "patches", "MANIML_SURFACE": "nets", "MANIML_PROGRAMS": "gpu",
                "MANIML_BORDER_GENERATOR": "gpu", "MANIML_PATCH_SOURCE": "records"},
    "phase_b_rows": {"MANIML_FILL": "patches", "MANIML_SURFACE": "nets", "MANIML_PROGRAMS": "gpu",
                     "MANIML_BORDER_GENERATOR": "gpu", "MANIML_PATCH_SOURCE": "rows"},
    "phase_a_strokes": {"MANIML_FILL": "meshes", "MANIML_SURFACE": "grids", "MANIML_PROGRAMS": "strokes",
                        "MANIML_BORDER_GENERATOR": "gpu"},
}
# The kinds of row, as the viewer draws them: the still redraw of a
# pausepoint, the same with its updaters ticking, a frame of a play, and
# the first message after a restore, delta-encoded against the previous
# message of the stream as a seek is against the frame on screen (its
# cached_batches say how much the cache still held). Under --play-edges,
# per play, its first frame and its landing (the destination on screen
# after the play's last frame): where a retained frame is made and let go.
EDGE_CLASSES = ("play_entry", "landing")
# Under --camera-moves, per frame after its pausepoint rounds: a pan, a 2%
# zoom and the camera put back, one message each.
CLASSES = ("pausepoint", "ticked", "play", "cold", *EDGE_CLASSES, "camera")
# Under --deltas each variant's frames are also recorded as the format 8
# stream a viewer sends a page that announced it (docs/phase_b4_plan.md,
# B4.8), beside the format 7 one: a delta per message, or nothing (a
# stream entry of length 0, drawn as nothing) where the frame changed
# nothing. Its report variant is the variant's name with this suffix.
DELTA = "_delta"
# The columns summary.json reduces per class and per frame, in this order.
COLUMNS = ("js_ms", "page_ms", "serialize_ms", "wire_bytes", "batches", "cached_batches", "draws", "set_pipeline_calls",
           "pipeline_switches", "set_bind_group_calls", "bind_groups_created", "buffers_created", "buffers_destroyed",
           "uniform_writes", "compute_dispatches", "compute_passes", "render_passes", "bytes_uploaded")
HARNESS = Path(__file__).with_name("browser_frames.cjs")
FAKE_DEVICE = ROOT / "tests" / "webgpu_fake_device.cjs"


def frame_class(row):
    """A row's class: its phase, except that a pausepoint round is cold,
    ticked or a still. The play edges' source still and last play frame
    (play_source, play_last) are in no class: they are what the entry and
    the landing follow. A camera move's is ``camera``."""
    if row["phase"] != "pausepoint":
        return row["phase"]
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


def record_stream(scene, indices, samples, warmups, *, tick_updaters=False, play_frames=False, play_edges=False,
                  camera_moves=False, delta_stream=None):
    """Serialize the chosen frames as the viewer would send them: per frame
    the pausepoint's rounds (warmups then samples; under ``tick_updaters``
    the scene's updaters tick 1/fps before every round on a frame that has
    any), under ``camera_moves`` a pan, a 2% zoom and the camera put back,
    then under ``play_frames`` the middle frames of the play leading
    into it; under ``play_edges``, after every frame, each frame's play
    again from its first frame to its landing (record_edges). Returns the
    messages, one stream entry per message (the
    export's ``len`` and ``segment`` plus what the frame is) and one block
    per frame. One cache for the whole stream, never reset, as one viewer
    session keeps one: every message is a delta against the one before it,
    so the first round after a restore re-sends what the cache no longer
    holds (as a seek does; the message before it is the last recorded
    frame of the previous frame's play) and the rest are cached.

    A ``delta_stream`` list receives the same frames as the format 8 stream
    of a second cache, whose receivers negotiated it: per message, the
    stream's message (None where it sends nothing) and its serialize time,
    each serialized right after the format 7 one from the scene as that
    left it (delta_entries makes its stream entries)."""
    from maniml.web.geometry import GeometryCache, serialize_scene

    cache = GeometryCache()
    stream = GeometryCache()
    stream.negotiate(True)
    checkpoints = scene.animation_checkpoints
    messages, entries, frames, segments = [], [], [], count()

    def take(fields, segment):
        started = perf_counter()
        message = serialize_scene(scene, cache, renderer="triangles")
        entries.append({"len": len(message), "segment": segment, **fields,
                        "serialize_ms": 1000 * (perf_counter() - started)})
        messages.append(message)
        if delta_stream is not None:
            started = perf_counter()
            message = serialize_scene(scene, stream, renderer="triangles")
            delta_stream.append((message, 1000 * (perf_counter() - started)))

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
        if camera_moves:
            record_camera_moves(scene, take, fields, segment)
        if play_frames:
            frame["play"] = record_play(scene, index, samples, warmups, take, fields, segments)
        frames.append(frame)
    if play_edges:
        for position, (index, frame) in enumerate(zip(indices, frames)):
            frame["play_edges"] = record_edges(scene, index, take, dict(frame=position, checkpoint=index), segments)
    return messages, entries, frames


def record_camera_moves(scene, take, fields, segment):
    """A pan of 5% of the frame's width, a 2% zoom out, and the camera put
    back as it was, after a frame's pausepoint rounds, one message each
    (class ``camera``), as a viewer's drag and wheel move it."""
    frame = scene.camera.frame
    frame.save_state()
    pan = .05 * frame.get_width() * np.array([1., 0., 0.])
    for move, apply in (("pan", lambda: frame.shift(pan)), ("zoom", lambda: frame.scale(1.02)),
                        ("back", frame.restore)):
        apply()
        scene.camera.refresh_uniforms()
        take(dict(fields, phase="camera", move=move, iteration=0, warmup=False, cold=False,
                  updaters_ticked=False), segment)


def delta_entries(entries, delta_stream):
    """The format 8 stream's entries for ``delta_stream`` (record_stream's):
    each format 7 entry with the stream message's length (0 where it sent
    nothing) and serialize time."""
    return [dict(entry, len=0 if message is None else len(message), serialize_ms=ms, delta=True)
            for entry, (message, ms) in zip(entries, delta_stream)]


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


def record_edges(scene, index, take, fields, segments):
    """The frames of the play into checkpoint ``index`` that its window
    leaves out, as a viewer meets them, one message each: the checkpoint
    before the play restored (play_source, a seek from whatever the stream
    held before it), the play's first frame (play_entry), its last frame
    (play_last) and the destination on screen after it (landing). The
    entry is where most of a play's batches first differ from the frame on
    screen, and the landing where they return to the destination's: the
    frames a retained frame is made and let go on. Recorded after every
    frame's rows, so the rows before them are the stream without edges;
    the play's next segment. None when nothing played."""
    checkpoints = scene.animation_checkpoints
    target = play_before(checkpoints, index)
    if target is None:
        return None
    segment = next(segments)
    run_time, fps = checkpoints[target]["run_time"], scene.camera.fps
    frames = play_frame_count(fps, run_time)
    edge = dict(fields, play_checkpoint=target, iteration=0, warmup=False, cold=False, updaters_ticked=False)
    show_frame(scene, target - 1)
    take(dict(edge, phase="play_source"), segment)
    alphas = {}

    def on_frame(k):
        if k in (0, frames - 1):
            scene.camera.refresh_uniforms()
            alphas[k] = (k + 1) / fps / run_time
            take(dict(edge, phase="play_entry" if k == 0 else "play_last", play_frame=k, alpha=alphas[k]), segment)

    replay_play(scene, target, on_frame)
    scene.camera.refresh_uniforms()
    take(dict(edge, phase="landing"), segment)
    return {"checkpoint": target, "line": checkpoints[target]["line_number"], "frames": frames,
            "entry_alpha": alphas.get(0), "last_alpha": alphas.get(frames - 1)}


def write_stream(directory, scene, messages, entries, **about):
    """The export recorder's folder (web/export.py _write_export), so the
    player and geometry_recording.js read it: scene.bin.gz is the messages
    end to end and scene.json's frames carry each one's length and
    segment. The export's segments are its plays, so its ``lines`` are the
    checkpoints'; here a segment is a recorded group, so each names its own
    line (the checkpoint's for a pausepoint group, the play's for a play
    group) and the player's chips name the frames. The entries' other keys
    and ``about`` say what the stream is. A format 8 stream (``messages``
    holding None where it sent nothing, a length-0 entry) is format 8's
    folder, which browser_frames.cjs plays in order and the player does not
    read: a delta is no frame to seek to."""
    from maniml.web.geometry import FULL_FRAME_FORMAT_VERSION, GEOMETRY_FORMAT_VERSION

    delta = any(entry.get("delta") for entry in entries)
    directory.mkdir(parents=True, exist_ok=True)
    with gzip.open(directory / "scene.bin.gz", "wb", compresslevel=6) as file:
        for message in messages:
            if message is not None:
                file.write(message)
    checkpoints = scene.animation_checkpoints
    first = {}
    for entry in entries:
        first.setdefault(entry["segment"], entry)
    lines = [checkpoints[entry.get("play_checkpoint", entry["checkpoint"])].get("line_number")
             for _, entry in sorted(first.items())]
    meta = {"format_version": GEOMETRY_FORMAT_VERSION if delta else FULL_FRAME_FORMAT_VERSION,
            "scene": type(scene).__name__, "fps": int(scene.camera.fps),
            "frames": entries, "segments": len(lines), "lines": lines, "harness": "browser_frames", **about}
    (directory / "scene.json").write_text(json.dumps(meta) + "\n")
    return meta


def replay_stream(directory, timeout=1800, realm="sandbox"):
    """browser_frames.cjs over the stream: Node's version, the driver's init
    time and one row per frame. ``realm`` is where the driver runs: a vm
    sandbox of its own (the command tests' setting), or Node's own realm,
    where a global lookup costs what it does in a browser."""
    result = subprocess.run(["node", str(HARNESS), str(directory), "--realm", realm],
                            capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0:
        raise RuntimeError(f"browser_frames.cjs failed on {directory}:\n{result.stdout}\n{result.stderr}")
    return json.loads(result.stdout)


def replay_rounds(directories, rounds=1, realm="sandbox"):
    """replay_stream over each of ``directories``, ``rounds`` times, the
    streams taking turns within a round so a drift in the machine's load
    falls on each alike: per stream, each frame's median js_ms and page_ms
    over the rounds, and the rest of its row (sizes and call counts, the
    same every round, which is checked) from the first."""
    runs = {directory: [] for directory in directories}
    for _ in range(rounds):
        for directory in directories:
            runs[directory].append(replay_stream(directory, realm=realm))
    merged = {}
    for directory, replays in runs.items():
        frames = []
        for rows in zip(*(replay["frames"] for replay in replays)):
            untimed = [{key: value for key, value in row.items() if key not in ("js_ms", "page_ms")} for row in rows]
            if any(row != untimed[0] for row in untimed):
                raise RuntimeError(f"{directory}: frame {rows[0]['index']} made other calls in another round")
            frames.append({**rows[0], **{key: float(np.median([row[key] for row in rows]))
                                         for key in ("js_ms", "page_ms")}})
        merged[directory] = {**replays[0], "frames": frames, "rounds": rounds,
                             "init_ms": float(np.median([replay["init_ms"] for replay in replays]))}
    return merged


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
    JavaScript ms (with its minimum) and the page's median, batches (and the
    cached among them),
    draws, setPipeline calls, bind groups created, buffers
    created/destroyed, uniform writes and KB uploaded; closing lines over
    every measured row of each class."""
    variants = list(summary["variants"])
    head = ["frame", "checkpoint", "line", "name", "class"]
    head += [f"{variant} {column}" for variant in variants
             for column in ("js p50/min", "page p50", "batches (cached)", "draws", "setPipeline", "bindGroups",
                            "buffers +/-", "uniform writes", "KB up")]
    lines = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]

    def line(cells, per_variant):
        for variant in variants:
            stats = per_variant.get(variant, {})
            js = f"{stats['js_ms']['p50']:.2f} / {stats['js_ms']['min']:.2f}" if "js_ms" in stats else "–"
            batches = (f"{stats['batches']['p50']:.0f} ({stats['cached_batches']['p50']:.0f})"
                       if "batches" in stats else "–")
            cells += [js, _cell(stats, "page_ms"), batches, _cell(stats, "draws", "{:.0f}"),
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
                label = cls.replace("_", " ")
                if cls == "play":
                    alphas = frame["play"]["measured_alphas"]
                    label = f"play α {alphas[0]:.2f}–{alphas[-1]:.2f}"
                line([*cells, label], per_variant)
    for cls in CLASSES:
        per_variant = {variant: summary["variants"][variant]["classes"][cls] for variant in variants
                       if cls in summary["variants"][variant]["classes"]}
        if per_variant:
            line(["all", "", "", "", cls.replace("_", " ")], per_variant)
    return "\n".join(lines)


def summary_of(report):
    """report.json without the per-frame rows."""
    summary = {key: value for key, value in report.items() if key != "variants"}
    if "scene" in summary:
        summary["scene"] = {key: value for key, value in summary["scene"].items() if key != "checkpoints"}
    summary["variants"] = {variant: {key: value for key, value in data.items() if key != "rows"}
                           for variant, data in report.get("variants", {}).items()}
    return summary


def scope(tick_updaters, play_frames, realm="sandbox", play_edges=False, camera_moves=False, deltas=False,
          rounds=1):
    """The report's own caveats, worded for the run's switches."""
    return {
        "stream_format": (
            "With --deltas each variant's frames are also recorded as the format 8 stream (docs/phase_b4_plan.md, "
            "B4.8) of a second GeometryCache whose receivers negotiated it, each frame serialized right after the "
            "format 7 one from the scene as that serialization left it (the format 7 stream is byte-identical to one "
            "recorded alone): the variant named with '_delta', a full frame and then a delta per message, or no "
            "message where the frame changed nothing (wire_bytes 0, js_ms and page_ms 0, every count 0: the page "
            "runs nothing, and batches is the frame on screen). A delta row carries splices, spliced_batches and "
            "scalars_ops. The delta stream's serialize_ms follows the format 7 serialization of the same frame and "
            "is not Python's cost of the stream alone; episode_frames.py owns the Python measurement."
            if deltas else "Format 7 streams only (--deltas off)."),
        "rounds": (
            f"Each variant's streams were replayed {rounds} times, taking turns within a round; js_ms and page_ms "
            "are each frame's median over the rounds, every other column the same in every round (checked)."
            if rounds > 1 else "One replay per stream (--rounds 1)."),
        "frame_selection": (
            "episode_frames.select_frames: pausepoints of a pause-anchored file, else every --every-th checkpoint "
            "after the empty first one, thinned evenly to --max-frames keeping the last; each restored with one "
            "dt=0 updater pass as a navigation shows it, so the two harnesses describe the same frames. "
            + ("With --play-frames the play leading into each pausepoint is replayed from the checkpoint before it "
               "at camera.fps and its middle frames are recorded, warmups then samples, as episode_frames samples "
               "them." if play_frames else "No play frames (--play-frames): the stream holds no mid-animation state.")
            + (" With --play-edges, after every frame's rows, each frame's play is replayed once more and recorded "
               "at its edges: the checkpoint before it restored (play_source), its first frame (play_entry), its "
               "last frame (play_last) and the destination on screen after it (landing), one message each."
               if play_edges else " No play edges (--play-edges): a play's first frame and its landing are in no "
               "class.")),
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
            "(tests/webgpu_fake_device.cjs, validate: false): the header parse, the match against the retained "
            "slots (or, before B4.7, preparePaints/Programs/Borders/Nets), the compute stages, the encode loop, the "
            "fake queue.submit and the release of what the frame no longer holds. page_ms is performance.now "
            "around the viewer's entry point, ManimlRendererSelection.render (renderer_selection.js) over the "
            "same driver: js_ms plus the selection's routing, a parse of the whole header (or, for a message the "
            "same as the one before, a comparison) and a promise hop; it is what a page pays per message. "
            + ("The driver and the selection ran in Node's own realm (--realm main), where a global lookup costs "
               "what it does in a browser. " if realm == "main" else
               "The driver and the selection ran in a vm sandbox of their own (--realm sandbox, the command tests' "
               "setting), where every global lookup is an interceptor call: per-value loops that name a builtin "
               "per value pay that per value, so these rows overstate a browser's JavaScript; --realm main "
               "measures without it. ")
            + "Not in either: Dawn's validation and "
            "command encoding behind each call, the GPU, the canvas present, texture decoding (createImageBitmap "
            "is a stub), the socket and the viewer's queue; the live viewer's "
            "performance.measure('maniml:render') spans the queue wait as well. Node's garbage "
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
            "every class but cold. "
            + ("play_entry: a play's first frame, following the checkpoint before it (one row per play); landing: "
               "the destination after the play's last frame (one row per play). The source still and the last "
               "frame they follow (play_source, play_last) are rows of no class." if play_edges else
               "No play_entry or landing rows (--play-edges).")
            + (" camera: with --camera-moves, after each frame's pausepoint rounds, a pan of 5% of the frame's width, "
               "a 2% zoom out and the camera restored as it was (move pan, zoom, back), one message each."
               if camera_moves else " No camera rows (--camera-moves).")),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--scene", nargs=2, metavar=("FILE", "SCENE"), required=True,
                        help="episode file and scene class")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--variants", nargs="+", choices=tuple(ENVIRONMENTS), default=list(VARIANTS),
                        help="the streams to record and play, each from the same frames")
    parser.add_argument("--samples", type=int, default=12)
    parser.add_argument("--warmups", type=int, default=3)
    parser.add_argument("--every", type=int, default=1, help="checkpoint stride for a file without pausepoints")
    parser.add_argument("--max-frames", type=int, default=12)
    parser.add_argument("--tick-updaters", action="store_true",
                        help="tick a pausepoint's updaters 1/fps before every round, as the idle loop does")
    parser.add_argument("--play-frames", action="store_true",
                        help="also record consecutive frames of the play leading into each pausepoint")
    parser.add_argument("--play-edges", action="store_true",
                        help="after every frame, record each frame's play again at its edges: its first frame and "
                             "its landing, each after what a viewer shows before it")
    parser.add_argument("--realm", choices=("sandbox", "main"), default="sandbox",
                        help="replay with the driver in a vm sandbox (the command tests' setting) or in Node's "
                             "own realm, where a global lookup costs what it does in a browser")
    parser.add_argument("--deltas", action="store_true",
                        help="also record each variant's frames as the format 8 stream a page that announced it "
                             "is sent, and replay it beside the format 7 one (variant name + '_delta')")
    parser.add_argument("--camera-moves", action="store_true",
                        help="after each pausepoint's rounds, record a pan, a 2%% zoom and the camera put back")
    parser.add_argument("--rounds", type=int, default=1,
                        help="replay each variant's streams this many times, taking turns, and report each "
                             "frame's median milliseconds")
    args = parser.parse_args(argv)
    if min(args.samples, args.warmups, args.every, args.max_frames, args.rounds) < 1:
        parser.error("samples, warmups, every, max-frames and rounds must be positive")
    if shutil.which("node") is None:
        parser.error("node is needed to play the stream through the browser driver")
    # As given, as episode_frames takes it: an episode reached through a
    # tree of symbolic links imports its neighbours from where it is named.
    scene_path = Path(os.path.abspath(args.scene[0]))
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
                 "tick_updaters": args.tick_updaters, "play_frames": args.play_frames, "play_edges": args.play_edges,
                 "camera_moves": args.camera_moves, "deltas": args.deltas, "rounds": args.rounds, "realm": args.realm}
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
        "source_files_sha256": hashes, **scope(args.tick_updaters, args.play_frames, args.realm, args.play_edges,
                                               args.camera_moves, args.deltas, args.rounds),
        "frames": [], "variants": {},
    }
    for variant in args.variants:
        environment = ENVIRONMENTS[variant]
        delta_stream = [] if args.deltas else None
        with patch.dict(os.environ, environment):
            messages, entries, frames = record_stream(scene, indices, args.samples, args.warmups,
                                                      tick_updaters=args.tick_updaters, play_frames=args.play_frames,
                                                      play_edges=args.play_edges, camera_moves=args.camera_moves,
                                                      delta_stream=delta_stream)
        recorded = [(variant, messages, entries)]
        if delta_stream is not None:
            recorded.append((variant + DELTA, [message for message, _ in delta_stream],
                             delta_entries(entries, delta_stream)))
        streams, stream_entries = {}, {}
        for name, stream_messages, name_entries in recorded:
            directory = args.output / name
            write_stream(directory, scene, stream_messages, name_entries, variant=name, environment=environment,
                         frame_selection=selection)
            sent = [message for message in stream_messages if message is not None]
            header, _ = parse_geometry_message(sent[0])
            streams[name] = {"directory": str(directory), "frames": len(stream_messages), "sent": len(sent),
                             "bytes": sum(map(len, sent)), "gzip_bytes": (directory / "scene.bin.gz").stat().st_size,
                             "resolution": header["resolution"], "samples": header["samples"],
                             "supersample": header.get("supersample")}
            stream_entries[name] = name_entries
            print(f"{name}: recorded {len(stream_messages)} frames, {len(sent)} sent, "
                  f"{streams[name]['bytes'] / 1e6:.1f} MB", flush=True)
        del messages, recorded, delta_stream
        replayed = replay_rounds([Path(stream["directory"]) for stream in streams.values()], args.rounds, args.realm)
        for name, stream in streams.items():
            played = replayed[Path(stream["directory"])]
            rows = join_rows(stream_entries[name], played["frames"])
            report["node"] = played["node"]
            stream["init_ms"] = played["init_ms"]
            classes = assemble(report, name, rows, frames, environment=environment, stream=stream)
            (args.output / "report.json").write_text(json.dumps(report, indent=2, default=_jsonable) + "\n")
            print(f"{name}: played in {played['node']}; " + ", ".join(
                f"{cls} js p50 {stats['js_ms']['p50']:.2f} ms, page {stats['page_ms']['p50']:.2f} "
                f"(n={stats['js_ms']['n']})" for cls, stats in classes.items()), flush=True)
    report["variants_in_order"] = list(report["variants"])
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

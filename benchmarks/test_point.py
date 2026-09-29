"""The final test point: what a lecture frame costs, per class, today and
after, on the frames of a course episode (docs/phase_b4_plan.md, B6).

    S=(/abs/path/Blocks/B2_Supply/03_Code.py EpisodeB2)
    F=(--tick-updaters --play-frames)
    python -m benchmarks.test_point serialize --scene $S $F --output <d>/serialize
    python -m benchmarks.browser_frames --scene $S --variants phase_a default phase_b_forced $F \\
        --deltas --realm main --rounds 5 --output <d>/browser
    python -m benchmarks.test_point page --stream <d>/browser/phase_a --revision main --rounds 5 \\
        --output <d>/page
    python -m benchmarks.episode_frames --scene $S --variants gpu_border retained default phase_b_retained $F \\
        --gpu-timestamps --output <d>/gpu1            (and again, <d>/gpu2)
    python -m benchmarks.episode_frames --scene $S --variants phase_b_retained gpu_border $F --output <d>/frames_b
    python -m benchmarks.episode_frames --scene $S --variants retained default gpu_border $F --output <d>/frames_a
    python -m benchmarks.test_point python --scene $S $F --output <d>/python
    python -m benchmarks.test_point table --serialize <d>/serialize --browser <d>/browser --page <d>/page \\
        --gpu <d>/gpu1 <d>/gpu2 --pixels <d>/frames_b <d>/frames_a --python <d>/python --output <d>/table

Four stacks (STACKS), as a lecture meets them: ``today``, Phase A without
the retained frame (MANIML_RETAINED_FRAME=0) in format 7 full frames, drawn
by the page of the revision Taylor teaches from (``page``: its webgpu.js
and renderer_selection.js, which predate the retained slot list), the
state of the main checkout; ``phase_a``, Phase A forced with the retained
frame, in format 7 and in the format 8 stream the shipped page negotiates;
``default``, the default stack as the generators' defaults leave it, the
same two ways; and ``phase_b``, the forced Phase B (patches, nets, GPU
programs, its plays recording programs as the viewer's selection has them
record), the same two ways.

Per class (a still pausepoint, a pausepoint whose updaters tick, a frame of
the play into it) and per stack and format, the browser-side complete
frame Taylor's gates read (flip_gates.py): Python's serialize_ms (this
module's ``serialize``, the seven serializers taking turns as flip_gates
has two stacks take them), the page's JavaScript (browser_frames' page_ms,
main realm, each frame's median over the rounds; for ``today``, this
module's ``page``), the GPU (episode_frames' gpu_total_ms from the
attribution runs, charged as the share of a frame's messages the stream
sent), their sum, the wire bytes per message the page was sent, and the
pixels against Phase A without the retained frame (episode_frames' flag-off
runs: the worst frame of each class, a play's frames strictly inside it).
Beside the GPU part the flag-off check (the flag-off runs' wall clock from
the submit through the full readback in place of the stamped GPU), as
flip_gates quotes it.

``python`` is one instrumented run, for attribution and never for a total:
per serialization of ``today`` (format 7), ``default`` and ``phase_b``
(format 8), the preparation and the encode (the serializer's own stages),
Lyon's tessellations, the retained frame's comparisons of a moved revision
(the revision counter's over-signalling: a leaf whose revision moved over
the same rows is compared and kept), the stream's diff, the leaves kept,
compared and prepared, and the scene's own Python between frames (its
updaters on a ticked frame; the interpolation and the updaters in a play).
"""

import argparse
from collections import defaultdict
from contextlib import ExitStack, redirect_stderr, redirect_stdout
from dataclasses import dataclass
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
from time import perf_counter
from unittest.mock import patch

import numpy as np

from benchmarks.browser_frames import FAKE_DEVICE, HARNESS, join_rows, measured, merge_replays, replay_stream
from benchmarks.episode_frames import (ROOT, git_state, load_episode, play_before, play_frame_count, replay_play,
                                       select_frames, show_frame)
from benchmarks.flip_gates import (FLAG_OFF_GPU, PIXEL_LIMIT, gpu_by_frame, key_name, measure_serializers,
                                   page_by_frame, serialize_by_frame, source_hashes, stack_classes, stack_environment)


@dataclass(frozen=True)
class Stack:
    """A stack as the test point reads it: the renderer it serializes as;
    the environment its serializer runs under (a switch named None is taken
    out, so the defaults select it) and the one its plays replay under (the
    program mode they record under); the formats it is read in; and the
    variants the other harnesses measure it as: browser_frames' stream
    (its format 8 stream the same name with "_delta"), whether its page is
    the revision ``page`` plays the stream through, and episode_frames'
    variant for the GPU with the pixel pair against Phase A (None for the
    reference)."""
    renderer: str
    environment: dict
    play: dict
    formats: tuple
    browser: str
    frames: str
    pair: str | None
    revision_page: bool = False


# The default stack's switches, taken out so the generators' and the
# programs' defaults select them (geometry.DEFAULT_FILL, DEFAULT_SURFACE,
# programs.DEFAULT_MODE, the records packed), whatever the caller's
# environment says.
DEFAULTS = {"MANIML_FILL": None, "MANIML_SURFACE": None, "MANIML_PROGRAMS": None, "MANIML_PATCH_SOURCE": None}
STACKS = {
    "today": Stack("phase_a", {"MANIML_RETAINED_FRAME": "0"}, {}, (7,), "phase_a", "gpu_border", None,
                   revision_page=True),
    "phase_a": Stack("phase_a", {"MANIML_RETAINED_FRAME": "1"}, {}, (7, 8), "phase_a", "retained",
                     "retained_vs_gpu_border"),
    "default": Stack("triangles", {"MANIML_RETAINED_FRAME": "1", **DEFAULTS}, {"MANIML_PROGRAMS": None}, (7, 8),
                     "default", "default", "default_vs_gpu_border"),
    "phase_b": Stack("phase_b", {"MANIML_RETAINED_FRAME": "1", "MANIML_PATCH_SOURCE": "records"},
                     {"MANIML_PROGRAMS": "gpu"}, (7, 8), "phase_b_forced", "phase_b_retained",
                     "phase_b_vs_gpu_border"),
}
CLASSES = ("pausepoint", "ticked", "play")
# What every serializer runs under, its stack aside: animations that write
# no program unless a stack's plays say otherwise, and none of the switches
# that change what a frame costs and are not the run's to set.
ENVIRONMENT = {"MANIML_PROGRAMS": "off"}
CLEARED = ("MANIML_VERIFY_LEDGER", "MANIML_RENDER_CACHE", "MANIML_GPU_TIMESTAMPS", "MANIML_RETAINED_FRAME",
           "MANIML_FILL", "MANIML_SURFACE", "MANIML_PATCH_SOURCE", "MANIML_BORDER_GENERATOR")
# The instrumented run's serializers: the stacks whose costs differ (phase_a
# is the default's stack, its bytes the same), each in the format its page
# is sent.
INSTRUMENTED = (("today", 7), ("default", 8), ("phase_b", 8))
# The instrumented run's columns, reduced per stack and class in this order.
PYTHON_COLUMNS = ("scene_ms", "serialize_ms", "prepare_ms", "encode_ms", "lyon_ms", "lyon_calls", "compare_ms",
                  "compare_calls", "diff_ms", "leaves", "leaves_kept", "leaves_compared", "leaves_prepared",
                  "leaves_adopted", "batches_encoded", "batches_reused", "programs", "wire_bytes", "sent")
# The page's files a revision's page is made of, and this tree's replay
# harness and fake device beside them.
PAGE = "maniml/web/static"


def serializers():
    """{(stack, format): (renderer, environment, play environment)} for
    flip_gates.measure_serializers, in STACKS' order."""
    return {(name, fmt): (stack.renderer, stack.environment, stack.play)
            for name, stack in STACKS.items() for fmt in stack.formats}


def settle_environment():
    os.environ.update(ENVIRONMENT)
    for key in CLEARED:
        os.environ.pop(key, None)


def about(scene_path, scene_name, checkpoints, indices, error, paths):
    return {
        "recorded_utc": datetime.now(timezone.utc).isoformat(), "command": sys.argv,
        "scene": {"path": str(scene_path), "name": scene_name, "checkpoint_count": len(checkpoints),
                  "measured_checkpoints": indices, "construct_error": error},
        "git": git_state(ROOT),
        "machine": {"platform": platform.platform(), "machine": platform.machine(), "node": platform.node()},
        "python": platform.python_version(), "numpy": np.__version__,
        "environment": {key: value for key, value in os.environ.items() if key.startswith("MANIML_")},
        "stacks": {name: {"renderer": stack.renderer, "environment": stack.environment, "play": stack.play,
                          "formats": list(stack.formats)} for name, stack in STACKS.items()},
        "source_files_sha256": source_hashes(paths),
    }


def load(args):
    scene_path = Path(os.path.abspath(args.scene[0]))
    if not scene_path.is_file():
        raise SystemExit(f"no scene file at {scene_path}")
    settle_environment()
    args.output.mkdir(parents=True, exist_ok=True)
    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
        scene, error = load_episode(scene_path, args.scene[1])
    indices = select_frames(scene.animation_checkpoints, args.every, args.max_frames)
    paths = [Path(__file__), ROOT / "benchmarks/flip_gates.py", ROOT / "benchmarks/episode_frames.py",
             *(ROOT / "maniml/web").glob("*.py"), ROOT / "maniml/utils/programs.py", scene_path]
    return scene, indices, about(scene_path, args.scene[1], scene.animation_checkpoints, indices, error, paths), paths


def run_serialize(args):
    from maniml.web.geometry import _jsonable

    scene, indices, report, paths = load(args)

    def log(frame):
        print(json.dumps({key: value for key, value in frame.items() if key != "play"}), flush=True)

    report.update(samples=args.samples, warmups=args.warmups, replays=args.replays,
                  tick_updaters=args.tick_updaters, play_frames=args.play_frames,
                  serializers=[key_name(*key) for key in serializers()])
    report["frames"] = measure_serializers(scene, indices, serializers(), samples=args.samples,
                                           warmups=args.warmups, replays=args.replays,
                                           tick_updaters=args.tick_updaters, play_frames=args.play_frames, log=log)
    report["source_files_unchanged_during_run"] = source_hashes(paths) == report["source_files_sha256"]
    (args.output / "report.json").write_text(json.dumps(report, indent=2, default=_jsonable) + "\n")


class Instrument:
    """Per serialization, what its parts cost: the serializer's own stages
    (geometry.performance), Lyon's tessellations, the retained frame's
    comparisons of a moved revision (RetainedFrame._verdict) and the
    stream's diff (generated_geometry.diff_runs), each timed around the
    call and counted. Installed for the whole run, before any cache sees
    the tessellator, so the mesh cache's generator key never changes."""

    def __init__(self):
        from benchmarks.generated_output import StageObserver

        self.stages = StageObserver()
        self.reset()

    def reset(self):
        self.stages.reset()
        self.ms, self.calls = defaultdict(float), defaultdict(int)

    def timed(self, name, function):
        def timed(*args, **kwargs):
            started = perf_counter()
            try:
                return function(*args, **kwargs)
            finally:
                self.ms[name] += 1000 * (perf_counter() - started)
                self.calls[name] += 1
        return timed

    def patches(self):
        from maniml.web import generated_geometry, geometry
        from maniml.web.retained_frame import RetainedFrame
        from maniml.web.triangle_geometry import LyonFillTessellator

        return (patch.object(geometry, "performance", self.stages),
                patch.object(LyonFillTessellator, "tessellate", self.timed("lyon", LyonFillTessellator.tessellate)),
                patch.object(RetainedFrame, "_verdict", staticmethod(self.timed("compare", RetainedFrame._verdict))),
                patch.object(generated_geometry, "diff_runs", self.timed("diff", generated_geometry.diff_runs)))

    def row(self, cache, message, serialize_ms):
        retained = cache.retained_frame
        stats = retained.stats if retained is not None else {}
        return {"serialize_ms": serialize_ms, "prepare_ms": self.stages.milliseconds["geometry.triangle_prepare"],
                "encode_ms": self.stages.milliseconds["geometry.triangle_encode"],
                "lyon_ms": self.ms["lyon"], "lyon_calls": self.calls["lyon"], "compare_ms": self.ms["compare"],
                "compare_calls": self.calls["compare"], "diff_ms": self.ms["diff"],
                **({"leaves": len(retained.leaves), "leaves_kept": stats["leaves_kept"],
                    "leaves_compared": stats["leaves_compared"], "leaves_prepared": stats["leaves_prepared"],
                    "leaves_adopted": stats["leaves_adopted"], "batches_encoded": stats.get("batches_encoded", 0),
                    "batches_reused": stats.get("batches_reused", 0)} if retained is not None else {}),
                "wire_bytes": 0 if message is None else len(message), "sent": message is not None}


def measure_python(scene, indices, instrument, *, samples=12, warmups=3, replays=2, tick_updaters=False,
                   play_frames=False):
    """The instrumented run: per frame and serializer of INSTRUMENTED, a
    row per serialization (Instrument.row) with the scene's own Python
    before it (``scene_ms``: the updaters' tick on a ticked frame, nothing
    on a still one, and in a play the interpolation and the updaters since
    the frame before, as play_frames measures it). The serializers take
    turns as measure_serializers has them, so each is the first reader of
    what moved. Returns one block per frame."""
    from maniml.web.geometry import GeometryCache, serialize_scene

    keys = list(INSTRUMENTED)
    caches = {key: GeometryCache() for key in keys}
    for (_, fmt), cache in caches.items():
        cache.negotiate(fmt == 8)

    def serialize(key, scene_ms):
        stack = STACKS[key[0]]
        instrument.reset()
        with stack_environment(stack.environment):
            started = perf_counter()
            message = serialize_scene(scene, caches[key], renderer=stack.renderer)
            ms = 1000 * (perf_counter() - started)
        return {"scene_ms": scene_ms, **instrument.row(caches[key], message, ms)}

    checkpoints, frames = scene.animation_checkpoints, []
    for position, index in enumerate(indices):
        show_frame(scene, index)
        live = bool(scene.should_update_mobjects())
        cls = "ticked" if tick_updaters and live else "pausepoint"
        for key in keys:
            serialize(key, 0.)
        rows = {key: [] for key in keys}
        for turn in range(len(keys) * (warmups + samples)):
            key = keys[turn % len(keys)]
            scene_ms = 0.
            if cls == "ticked":
                started = perf_counter()
                scene.update_mobjects(1 / scene.camera.fps)
                scene_ms = 1000 * (perf_counter() - started)
                scene.camera.refresh_uniforms()
            row = serialize(key, scene_ms)
            if turn >= len(keys) * warmups:
                rows[key].append(row)
        frame = {"frame": position, "checkpoint": index, "line": checkpoints[index]["line_number"],
                 "name": checkpoints[index].get("name"), "class": cls,
                 cls: {key_name(*key): values for key, values in rows.items()}}
        target = play_before(checkpoints, index) if play_frames else None
        if target is not None:
            frame["play"] = {"checkpoint": target, "line": checkpoints[target]["line_number"],
                             **{key_name(*key): values
                                for key, values in python_play(scene, target, keys, serialize, samples, warmups,
                                                               replays).items()}}
        frames.append(frame)
        print(f"frame {position + 1}/{len(indices)} checkpoint {index} complete", flush=True)
    return frames


def python_play(scene, target, keys, serialize, samples, warmups, replays):
    """The play into ``target``, episode_frames' window, one serializer per
    replay under its stack's play environment, the serializers taking turns
    replay by replay: each serializer's rows, the warmups left out."""
    from maniml.web.triangle_scene import draw_order

    count = play_frame_count(scene.camera.fps, scene.animation_checkpoints[target]["run_time"])
    window = min(count, warmups + samples)
    first, warm = (count - window) // 2, min(warmups, max(window - 1, 0))
    rows = {key: [] for key in keys}
    for replay in range(len(keys) * replays):
        key = keys[replay % len(keys)]
        last = [None]

        def on_frame(k, key=key):
            entered = perf_counter()
            if first <= k < first + window:
                # Outside every timer: the leaves drawn from a program.
                programs = sum(leaf._program is not None for leaf in draw_order(scene))
                scene.camera.refresh_uniforms()
                row = serialize(key, None if last[0] is None else 1000 * (entered - last[0]))
                if k >= first + warm:
                    rows[key].append(dict(row, play_frame=k, programs=programs))
            last[0] = perf_counter()

        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()), \
                stack_environment(STACKS[key[0]].play):
            replay_play(scene, target, on_frame)
    return rows


def reduce_python(frames):
    """Per serializer and class, each column's median (the figure read: one
    collection pause among a class's rows moves its mean by tens of
    milliseconds) and its total over the class's rows divided by the rows
    (the mean, which adds across columns where medians do not), with n."""
    by = defaultdict(list)
    for frame in frames:
        for cls in ("pausepoint", "ticked"):
            for key, rows in frame.get(cls, {}).items():
                by[(key, cls)] += rows
        for key, rows in (frame.get("play") or {}).items():
            if isinstance(rows, list):
                by[(key, "play")] += rows
    out = {}
    for (key, cls), rows in sorted(by.items()):
        out.setdefault(key, {})[cls] = {
            column: {"p50": float(np.median(values)), "mean": float(np.mean(values)), "n": len(values)}
            for column in PYTHON_COLUMNS
            for values in [[float(row[column]) for row in rows if row.get(column) is not None]] if values}
    return out


def reduce_python_by_checkpoint(frames):
    """reduce_python per measured checkpoint: its own class (a still or a
    ticked pausepoint) and the play into it, per serializer."""
    return {str(frame["checkpoint"]): reduce_python([frame]) for frame in frames}


def run_python(args):
    from maniml.web.geometry import _jsonable

    instrument = Instrument()
    with ExitStack() as stack:
        for manager in instrument.patches():
            stack.enter_context(manager)
        scene, indices, report, paths = load(args)
        report.update(samples=args.samples, warmups=args.warmups, replays=args.replays,
                      tick_updaters=args.tick_updaters, play_frames=args.play_frames,
                      serializers=[key_name(*key) for key in INSTRUMENTED],
                      instrumented=("an attribution run: every serialization carries per-call timers around Lyon's "
                                    "tessellations, the retained frame's comparisons and the stream's diff, which "
                                    "its serialize_ms includes; read its parts against each other, and the "
                                    "serialize run for totals"))
        frames = measure_python(scene, indices, instrument, samples=args.samples, warmups=args.warmups,
                                replays=args.replays, tick_updaters=args.tick_updaters,
                                play_frames=args.play_frames)
    report["frames"] = frames
    report["reduced"] = reduce_python(frames)
    report["reduced_by_checkpoint"] = reduce_python_by_checkpoint(frames)
    report["source_files_unchanged_during_run"] = source_hashes(paths) == report["source_files_sha256"]
    (args.output / "report.json").write_text(json.dumps(report, indent=2, default=_jsonable) + "\n")
    summary = {key: value for key, value in report.items() if key != "frames"}
    (args.output / "summary.json").write_text(json.dumps(summary, indent=2, default=_jsonable) + "\n")


def page_tree(revision, into):
    """The page of ``revision`` (its maniml/web/static: webgpu.js, the WGSL
    and renderer_selection.js) with this tree's replay harness and fake
    device beside it, laid out as the harness expects, under ``into``.
    Returns the harness to run and the revision's commit."""
    commit = subprocess.run(["git", "rev-parse", revision], cwd=ROOT, capture_output=True, text=True,
                            check=True).stdout.strip()
    archive = subprocess.run(["git", "archive", commit, PAGE], cwd=ROOT, capture_output=True, check=True).stdout
    subprocess.run(["tar", "-x", "-C", str(into)], input=archive, check=True)
    for source in (HARNESS, FAKE_DEVICE):
        target = into / source.relative_to(ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    return into / HARNESS.relative_to(ROOT), commit


def run_page(args):
    meta = json.loads((args.stream / "scene.json").read_text())
    if meta.get("format_version") != 7:
        raise SystemExit(f"{args.stream} is not a format 7 stream: the page of another revision reads full frames")
    with tempfile.TemporaryDirectory() as tmp:
        harness, commit = page_tree(args.revision, Path(tmp))
        pages = {"revision": harness, "tree": HARNESS}
        replays = {name: [] for name in pages}
        # The two pages take turns within a round, so a drift in the
        # machine's load falls on each alike.
        for _ in range(args.rounds):
            for name, path in pages.items():
                replays[name].append(replay_stream(args.stream, realm=args.realm, harness=path))
        merged = {name: merge_replays(f"{args.stream} ({name})", runs) for name, runs in replays.items()}
    report = {"recorded_utc": datetime.now(timezone.utc).isoformat(), "command": sys.argv,
              "stream": str(args.stream), "scene": meta.get("scene"), "revision": args.revision,
              "revision_commit": commit, "git": git_state(ROOT), "realm": args.realm, "rounds": args.rounds,
              "node": merged["tree"]["node"],
              "machine": {"platform": platform.platform(), "machine": platform.machine(), "node": platform.node()},
              "source_files_sha256": source_hashes([Path(__file__), HARNESS, FAKE_DEVICE]),
              "pages": {name: {"init_ms": played["init_ms"], "rows": join_rows(meta["frames"], played["frames"])}
                        for name, played in merged.items()}}
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    for name, page in report["pages"].items():
        print(f"{name}: " + ", ".join(
            f"{cls} page p50 {np.median([row['page_ms'] for row in measured(page['rows'], cls)]):.2f} ms"
            for cls in CLASSES if measured(page["rows"], cls)), flush=True)


def wire_by_frame(rows):
    """{(checkpoint, class): {"wire_bytes": median}} over a browser
    stream's measured rows: what the page was sent a message, 0 where the
    stream sent nothing."""
    out = {}
    for cls in CLASSES:
        by_frame = defaultdict(list)
        for row in measured(rows, cls):
            by_frame[row["checkpoint"]].append(row["wire_bytes"])
        for checkpoint, values in by_frame.items():
            out[(checkpoint, cls)] = {"wire_bytes": float(np.median(values))}
    return out


def pixels_by_class(reports, pair):
    """The pair's worst frame per class over the flag-off episode_frames
    reports given (a pausepoint's last round, and a play's frames strictly
    inside it, each frame counted once), with the frames compared."""
    out = {}
    for report in reports:
        for frame in report["frames"]:
            play = frame.get("play") or {}
            cls = "ticked" if frame.get("updaters_ticked") else "pausepoint"
            for block, name, keys in ((frame, cls, [("still", frame["checkpoint"])]),
                                      (play, "play", [("play", play.get("checkpoint"), k)
                                                      for k in play.get("pixel_frames", [])])):
                value = block.get("pixels", {}).get(pair)
                if value is None:
                    continue
                held = out.setdefault(name, {"frames": set(), "worst": None})
                held["frames"].update(keys)
                if held["worst"] is None or ((value["fraction_pixels_rgb_over24"], value["max_rgba"])
                                             > (held["worst"]["fraction_pixels_rgb_over24"],
                                                held["worst"]["max_rgba"])):
                    held["worst"] = {"checkpoint": frame["checkpoint"], **value}
    return {cls: {"frames": len(held["frames"]), "worst": held["worst"],
                  "passes": held["worst"]["fraction_pixels_rgb_over24"] <= PIXEL_LIMIT}
            for cls, held in out.items()}


def test_point(serialize, browser, page, gpu, pixels):
    """Per stack and format, per class: stack_classes over the stack's
    serialize, page and GPU parts, the wire bytes riding along, and beside
    it the flag-off check (the GPU part the flag-off runs' wall clock) and
    the pixels against Phase A without the retained frame."""
    result = {}
    for name, stack in STACKS.items():
        with_variant = [report for report in pixels if stack.frames in report["variants"]]
        for fmt in stack.formats:
            stream = stack.browser if fmt == 7 else stack.browser + "_delta"
            rows = page["pages"]["revision"]["rows"] if stack.revision_page else browser["variants"][stream]["rows"]
            wire = wire_by_frame(browser["variants"][stream]["rows"])
            python = serialize_by_frame(serialize["frames"], key_name(name, fmt))
            classes = stack_classes(python, page_by_frame(rows), gpu_by_frame(gpu, stack.frames), wire)
            checked = stack_classes(python, page_by_frame(rows), gpu_by_frame(with_variant, stack.frames,
                                                                              FLAG_OFF_GPU), wire)
            result[key_name(name, fmt)] = {
                "stack": name, "format": fmt, "classes": classes,
                "flag_off_check": {cls: {"complete_ms": stats["complete_ms"], "gpu_ms": stats["gpu_ms"]}
                                   for cls, stats in checked.items()},
                "pixels": (pixels_by_class(with_variant, stack.pair) if stack.pair else "reference")}
    return result


def ratios(result, reference="today_f7"):
    """Each stack and format's complete frame over ``reference``'s, per
    class."""
    base = result[reference]["classes"]
    return {key: {cls: stats["complete_ms"] / base[cls]["complete_ms"]
                  for cls, stats in entry["classes"].items() if cls in base and base[cls]["complete_ms"]}
            for key, entry in result.items()}


def markdown_table(summary):
    """Per class, a line per stack and format: the complete frame and its
    parts (medians over the class's frames), the wire per message, the
    ratio to today, the flag-off check's complete frame and the pixels."""
    head = ["class", "stack", "format", "frames", "serialize", "page", "GPU", "complete", "× today",
            "complete, GPU flag off", "wire KB", "sent", "pixels > 24/255 (worst)"]
    lines = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    for cls in CLASSES:
        for key, entry in summary["stacks"].items():
            stats = entry["classes"].get(cls)
            if stats is None:
                continue
            pixels = entry["pixels"]
            if pixels == "reference":
                cell = "reference"
            elif cls in pixels:
                worst = pixels[cls]["worst"]
                cell = f"{100 * worst['fraction_pixels_rgb_over24']:.4f}% ({worst['max_rgba']:.0f})"
            else:
                cell = "–"
            check = entry["flag_off_check"].get(cls)
            lines.append("| " + " | ".join([
                cls, entry["stack"], str(entry["format"]), f"{stats['frames']} ({stats['checkpoints']})",
                f"{stats['serialize_ms']:.2f}", f"{stats['page_ms']:.2f}", f"{stats['gpu_ms']:.2f}",
                f"**{stats['complete_ms']:.2f}**", f"{summary['ratios'][key].get(cls, float('nan')):.3f}",
                "–" if check is None else f"{check['complete_ms']:.2f}", f"{stats['wire_bytes'] / 1024:.1f}",
                f"{stats['sent']:.2f}", cell]) + " |")
    return "\n".join(lines)


def python_table(reduced, by_checkpoint=None):
    """The instrumented run per serializer and class, and per checkpoint
    where ``by_checkpoint`` is given: medians per serialization (a part's
    median, so the parts do not add exactly; the means are in the JSON), in
    INSTRUMENTED's order. The whole-frame path has no retained frame, so
    no comparisons, no diff and no leaves ("–")."""
    head = ["serializer, class (n)", "scene's own", "serialize", "prepare", "Lyon (calls)", "compare (calls)",
            "encode", "diff", "kept / compared / prepared", "wire"]
    lines = ["| " + " | ".join(head) + " |", "| --- |" + " ---: |" * (len(head) - 1)]

    def ms(value, digits=2):
        return "0" if value == 0 else f"{value:.{digits}f}"

    def timed(p50, name):
        calls = p50[f"{name}_calls"]
        return "0" if calls == 0 else f"{p50[f'{name}_ms']:.2f} ({calls:.0f})"

    def rows(label, classes):
        for key in (key_name(*key) for key in INSTRUMENTED):
            for cls in CLASSES:
                stats = classes.get(key, {}).get(cls)
                if stats is None:
                    continue
                p50 = {column: values["p50"] for column, values in stats.items()}
                retained = "leaves_kept" in p50
                leaves = (f"{p50['leaves_kept']:.0f} / {p50['leaves_compared']:.0f} / {p50['leaves_prepared']:.0f}"
                          if retained else "–")
                lines.append("| " + " | ".join([
                    f"{label}{key}, {cls} ({stats['serialize_ms']['n']})", ms(p50["scene_ms"]),
                    ms(p50["serialize_ms"]), ms(p50["prepare_ms"]), timed(p50, "lyon"),
                    timed(p50, "compare") if retained else "–", ms(p50["encode_ms"]),
                    ms(p50["diff_ms"], 3) if retained else "–", leaves,
                    "0" if p50["wire_bytes"] == 0 else f"{p50['wire_bytes'] / 1024:.1f} KB"]) + " |")

    rows("", reduced)
    for checkpoint, classes in (by_checkpoint or {}).items():
        rows(f"{checkpoint}: ", classes)
    return "\n".join(lines)


def run_table(args):
    def read(directory):
        return json.loads((Path(directory) / "report.json").read_text())

    serialize, browser, page = read(args.serialize), read(args.browser), read(args.page)
    gpu, pixels = [read(directory) for directory in args.gpu], [read(directory) for directory in args.pixels]
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
    if Path(page["stream"]).resolve() != (Path(args.browser) / STACKS["today"].browser).resolve():
        raise SystemExit(f"the page report played {page['stream']}, not the browser run's "
                         f"{STACKS['today'].browser} stream")
    result = test_point(serialize, browser, page, gpu, pixels)
    summary = {
        "scene": serialize["scene"], "revision": page["revision"], "revision_commit": page["revision_commit"],
        "inputs": {"serialize": str(args.serialize), "browser": str(args.browser), "page": str(args.page),
                   "gpu": [str(path) for path in args.gpu], "pixels": [str(path) for path in args.pixels],
                   "python": str(args.python) if args.python else None},
        "input_commits": {"serialize": serialize["git"], "browser": browser.get("git"), "page": page["git"],
                          "gpu": [report.get("git") for report in gpu],
                          "pixels": [report.get("git") for report in pixels]},
        "stacks": {key: {**entry, "classes": {cls: {k: v for k, v in stats.items() if k != "per_frame"}
                                              for cls, stats in entry["classes"].items()}}
                   for key, entry in result.items()},
        "ratios": ratios(result),
    }
    if args.python:
        # Reduced here from the run's rows, so a run recorded before a
        # reduction was added still reads.
        frames = read(args.python)["frames"]
        summary["python"] = reduce_python(frames)
        summary["python_by_checkpoint"] = reduce_python_by_checkpoint(frames)
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "report.json").write_text(json.dumps({**summary, "stacks": result}, indent=2) + "\n")
    (args.output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    table = markdown_table(summary)
    if args.python:
        table += "\n\n" + python_table(summary["python"], summary["python_by_checkpoint"])
    (args.output / "summary.md").write_text(table + "\n")
    print(table)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    for name, help_text, replays in (("serialize", "serialize_ms per frame and class, the stacks taking turns", 4),
                                     ("python", "one instrumented run: where each stack's Python goes", 2)):
        command = commands.add_parser(name, help=help_text)
        command.add_argument("--scene", nargs=2, metavar=("FILE", "SCENE"), required=True,
                             help="episode file and scene class")
        command.add_argument("--output", type=Path, required=True)
        command.add_argument("--samples", type=int, default=12)
        command.add_argument("--warmups", type=int, default=3)
        command.add_argument("--replays", type=int, default=replays, help="replays of each play per serializer")
        command.add_argument("--every", type=int, default=1)
        command.add_argument("--max-frames", type=int, default=12)
        command.add_argument("--tick-updaters", action="store_true")
        command.add_argument("--play-frames", action="store_true")
    page = commands.add_parser("page", help="a format 7 stream through the page of another revision and this tree's")
    page.add_argument("--stream", type=Path, required=True, help="a browser_frames format 7 stream directory")
    page.add_argument("--revision", default="main", help="the revision whose page draws the stream")
    page.add_argument("--rounds", type=int, default=5)
    page.add_argument("--realm", choices=("sandbox", "main"), default="main")
    page.add_argument("--output", type=Path, required=True)
    table = commands.add_parser("table", help="the complete frame per stack, format and class")
    table.add_argument("--serialize", type=Path, required=True, help="this module's serialize output")
    table.add_argument("--browser", type=Path, required=True,
                       help="browser_frames --variants phase_a default phase_b_forced --deltas --rounds N --realm main")
    table.add_argument("--page", type=Path, required=True, help="this module's page output over the phase_a stream")
    table.add_argument("--gpu", type=Path, nargs="+", required=True,
                       help="episode_frames --variants gpu_border retained default phase_b_retained --gpu-timestamps")
    table.add_argument("--pixels", type=Path, nargs="+", required=True,
                       help="episode_frames runs without the flag, each stack's variant beside gpu_border")
    table.add_argument("--python", type=Path, help="this module's python output")
    table.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command in ("serialize", "python"):
        if min(args.samples, args.warmups, args.replays, args.every, args.max_frames) < 1:
            parser.error("samples, warmups, replays, every and max-frames must be positive")
        (run_serialize if args.command == "serialize" else run_python)(args)
    elif args.command == "page":
        if args.rounds < 1:
            parser.error("rounds must be positive")
        run_page(args)
    else:
        run_table(args)


if __name__ == "__main__":
    main()

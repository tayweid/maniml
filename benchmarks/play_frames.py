"""Chosen plays of a course episode under MANIML_PROGRAMS modes that take
turns replay by replay.

    python -m benchmarks.play_frames \\
        --scene /abs/path/Blocks/B2_Supply/03_Code.py EpisodeB2 --plays 1 14 15 22 279 \\
        --modes off strokes --replays 6 --format 8 --output /private/tmp/plays-b2

episode_frames.py and browser_frames.py sample the middle of the play into
a pausepoint, their variants rotating frame by frame. A MANIML_PROGRAMS
mode cannot rotate frame by frame: an animation decides at its begin
whether it records programs (maniml/utils/programs.py), so a play is drawn
under one mode from its first frame to its last. Here each replay of a
play runs under one mode, the modes taking turns replay by replay (off,
strokes, off, strokes, ...), each through a GeometryCache of its own kept
across its replays as a viewer's is, and every frame of the play is
measured (docs/phase_b4_plan.md, B5.3). Phase A, the retained frame on,
the patch fill's records packed: ENVIRONMENT, whatever the caller's
environment says of those switches.

Per frame: serialize_scene's milliseconds, the message's bytes and the
scene's own Python since the frame before (the interpolation and the
updaters); from each mode's first replay, what the message carries (its
batches and program batches, or a delta's splices and scalars ops) and, at
the play's middle frame, the drawn leaves whose revision moved since the
frame before (the movers) and how many of them are programs. --format
says which messages are serialized: 8, the stream a page that negotiated
format 8 is sent; 7, full frames. Under --render the native driver (a
WgpuRenderer per mode) draws each full frame through its readback
(render_ms, and complete_ms, serialize plus render), and each mode's
first replay is compared with the first mode's frame by frame (the largest
channel difference, the largest fraction of pixels over 24); run with
MANIML_GPU_TIMESTAMPS=1 in the environment it is an attribution run and
adds the GPU pass columns (benchmarks/README.md, "GPU pass timestamps":
gate numbers come from a run without it). Under --browser each mode's play
is recorded once more in both formats (the checkpoint before it, then each
frame), written as browser_frames writes a stream, and replayed through
benchmarks/browser_frames.cjs --rounds times in Node's own realm, the
streams taking turns.

Reduction: each frame's median over its replays, then the median over the
play's frames after its first (the entry, reported apart); the minimum
over every sample after the entry. report.json holds the per-frame
medians, summary.json the reductions with the scene, commit, machine and
source hashes, summary.md the table.
"""

import argparse
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
import gc
from hashlib import sha256
import io
import json
import os
from pathlib import Path
import platform
import sys
from time import perf_counter

import numpy as np

from benchmarks.browser_frames import HARNESS, replay_rounds, write_stream
from benchmarks.episode_frames import ROOT, git_state, load_episode, play_frame_count, replay_play, show_frame

# What every replay runs under, the mode aside: Phase A as the B5.3 gate
# measures it.
ENVIRONMENT = {"MANIML_FILL": "meshes", "MANIML_SURFACE": "grids", "MANIML_BORDER_GENERATOR": "gpu",
               "MANIML_PATCH_SOURCE": "records", "MANIML_RETAINED_FRAME": "1"}
# Switches that change what a frame costs and are not the run's to set.
CLEARED = ("MANIML_VERIFY_LEDGER", "MANIML_RENDER_CACHE")
# The columns reduced per mode, in the table's order.
COLUMNS = ("serialize_ms", "render_ms", "complete_ms", "gpu_total_ms", "scene_ms", "wire_bytes")
# The browser replay's columns reduced per stream.
BROWSER_COLUMNS = ("page_ms", "js_ms", "wire_bytes", "bytes_uploaded", "compute_passes", "compute_dispatches",
                   "buffers_created", "bind_groups_created", "uniform_writes", "draws")


def carried(header):
    """What a message carries: a full frame's batches and program batches,
    a delta's splices and scalars ops."""
    if "batches" in header:
        return {"batches": len(header["batches"]),
                "program_batches": sum("program" in batch for batch in header["batches"])}
    return {"splices": len(header.get("splices", ())), "scalars_ops": len(header.get("scalars", ()))}


def replay(scene, target, cache, renderer, *, first, images=None):
    """One replay of the play that saved checkpoint ``target``: the
    checkpoint before it drawn as a viewer shows it before the play, then
    one row per frame of the play. ``first`` adds what each message
    carries and the movers at the middle frame, outside every timer;
    ``images`` receives each frame's picture under --render."""
    from maniml.web.geometry import parse_geometry_message, serialize_scene
    from maniml.web.triangle_scene import draw_order

    middle = play_frame_count(scene.camera.fps, scene.animation_checkpoints[target]["run_time"]) // 2
    stamps = os.environ.get("MANIML_GPU_TIMESTAMPS") == "1"
    rows, last, before = [], [None], {}

    def draw(message):
        header, payload = parse_geometry_message(message)
        started = perf_counter()
        image = renderer.render(header, payload)
        return 1000 * (perf_counter() - started), image

    def on_frame(k):
        entered = perf_counter()
        row = {"frame": k}
        if last[0] is not None:
            row["scene_ms"] = 1000 * (entered - last[0])
        if first and k in (middle - 1, middle):
            leaves = [(leaf, leaf.revision) for leaf in draw_order(scene)]
            if k == middle - 1:
                before.update((id(leaf), revision) for leaf, revision in leaves)
            else:
                movers = [leaf for leaf, revision in leaves if before.get(id(leaf)) != revision]
                row.update(leaves=len(leaves), movers=len(movers),
                           programs=sum(leaf._program is not None for leaf in movers))
        scene.camera.refresh_uniforms()
        started = perf_counter()
        message = serialize_scene(scene, cache, renderer="triangles")
        row["serialize_ms"] = 1000 * (perf_counter() - started)
        row["wire_bytes"] = 0 if message is None else len(message)
        if renderer is not None:
            row["render_ms"], image = draw(message)
            row["complete_ms"] = row["serialize_ms"] + row["render_ms"]
            if images is not None:
                images.append(np.asarray(image))
            if stamps:
                timings = renderer.gpu_timings
                row["gpu_total_ms"] = timings["total_ms"]
                for stage in timings["passes"]:
                    for key, value in ((f"gpu_exclusive_{stage['label']}_ms", stage["exclusive_ms"]),
                                       (f"gpu_passes_{stage['label']}", 1)):
                        row[key] = row.get(key, 0) + value
        if first and message is not None:
            row.update(carried(parse_geometry_message(message)[0]))
        rows.append(row)
        last[0] = perf_counter()

    show_frame(scene, target - 1)
    source = serialize_scene(scene, cache, renderer="triangles")
    if renderer is not None:
        draw(source)
    gc.collect()
    replay_play(scene, target, on_frame)
    return rows


def reduce(replays):
    """Each frame's median over the replays, per column; the play's median
    after its entry, the entry, and the minimum after it."""
    columns = sorted({key for rows in replays for row in rows for key in row if key.endswith(("_ms", "_bytes"))
                      or key.startswith("gpu_")})
    per_frame, summary = {}, {}
    for key in columns:
        frames = [[rows[k][key] for rows in replays if key in rows[k]] for k in range(len(replays[0]))]
        medians = [float(np.median(values)) if values else None for values in frames]
        per_frame[key] = [None if value is None else round(value, 4) for value in medians]
        after = [value for value in medians[1:] if value is not None]
        if after:
            summary[key] = {"p50": float(np.median(after)), "min": min(v for values in frames[1:] for v in values),
                            "entry": medians[0], "n": len(after)}
    return per_frame, summary


def measure_play(scene, target, modes, replays, fmt, render):
    """The play into checkpoint ``target``, each mode ``replays`` times,
    the modes taking turns: per mode the reduction, the per-frame medians,
    the first replay's carried counts and the middle frame's movers."""
    from maniml.utils import programs
    from maniml.web.geometry import GeometryCache

    caches, renderers = {}, {}
    for mode in modes:
        caches[mode] = GeometryCache()
        caches[mode].negotiate(fmt == 8)
        if render:
            from maniml.web.wgpu_renderer import WgpuRenderer
            renderers[mode] = WgpuRenderer()
    runs = {mode: [] for mode in modes}
    pictures = {mode: [] for mode in modes} if render else {}
    try:
        for index in range(replays * len(modes)):
            mode = modes[index % len(modes)]
            os.environ["MANIML_PROGRAMS"] = mode
            assert programs.mode() == mode
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                runs[mode].append(replay(scene, target, caches[mode], renderers.get(mode), first=not runs[mode],
                                         images=pictures.get(mode) if not runs[mode] else None))
    finally:
        for renderer in renderers.values():
            renderer.close()
    result = {}
    for mode, rows_by_replay in runs.items():
        per_frame, summary = reduce(rows_by_replay)
        first = rows_by_replay[0]
        middle = next((row for row in first if "movers" in row), {})
        counts = [{key: row[key] for key in ("batches", "program_batches", "splices", "scalars_ops") if key in row}
                  for row in first]
        result[mode] = {"summary": summary, "per_frame": per_frame, "carried_first_replay": counts,
                        "middle": {key: middle[key] for key in ("frame", "leaves", "movers", "programs")
                                   if key in middle}}
        if pictures and mode != modes[0]:
            diffs = [np.abs(a.astype(np.int16) - b.astype(np.int16)).max(axis=2)
                     for a, b in zip(pictures[modes[0]], pictures[mode])]
            result[mode]["pixels"] = {"against": modes[0], "frames": len(diffs),
                                      "max_channel_diff": int(max(d.max() for d in diffs)),
                                      "max_fraction_over_24": float(max((d > 24).mean() for d in diffs))}
    return result


def record_browser(scene, target, modes, output):
    """Each mode's play as a page is sent it, format 7 full frames and the
    format 8 stream serialized in lockstep from the scene: the checkpoint
    before it, then every frame, one segment. Returns the stream folders
    by (mode, format)."""
    from maniml.web.geometry import GeometryCache, serialize_scene

    folders = {}
    for mode in modes:
        os.environ["MANIML_PROGRAMS"] = mode
        caches = {7: GeometryCache(), 8: GeometryCache()}
        caches[8].negotiate(True)
        messages = {fmt: [] for fmt in caches}

        def take():
            scene.camera.refresh_uniforms()
            for fmt, cache in caches.items():
                messages[fmt].append(serialize_scene(scene, cache, renderer="triangles"))

        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            show_frame(scene, target - 1)
            take()
            replay_play(scene, target, lambda k: take())
        for fmt, stream in messages.items():
            entries = [{"len": 0 if message is None else len(message), "segment": 0, "checkpoint": target,
                        "phase": "play_source" if index == 0 else "play", "play_frame": index - 1,
                        **({"delta": True} if fmt == 8 else {})}
                       for index, message in enumerate(stream)]
            folder = output / f"streams/{target}_{mode}_f{fmt}"
            write_stream(folder, scene, stream, entries, variant=f"{mode}_f{fmt}",
                         environment={**ENVIRONMENT, "MANIML_PROGRAMS": mode})
            folders[(mode, fmt)] = folder
    return folders


def browser_summary(frames):
    """A stream's replay reduced: row 0 is the checkpoint before the play,
    row 1 the play's entry; the medians and maximum over the rest."""
    rest = frames[2:]
    summary = {"entry_page_ms": frames[1]["page_ms"], "frames": len(frames) - 1,
               "page_ms_max": max(row["page_ms"] for row in rest)}
    for key in BROWSER_COLUMNS:
        if key in rest[0]:
            summary[key] = float(np.median([row[key] for row in rest]))
    return summary


def markdown_table(summary):
    modes = summary["modes"]
    lines = ["| play | line | frames | mode | serialize ms p50 (min) | entry | scene ms | wire KB | movers: programs |"
             + (" render ms | complete ms |" if summary["render"] else "")
             + (" page ms f7 / f8 |" if summary["browser"] else ""),
             "| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: |"
             + (" ---: | ---: |" if summary["render"] else "") + (" ---: |" if summary["browser"] else "")]
    for play in summary["plays"]:
        for mode in modes:
            data, stats = play["modes"][mode], play["modes"][mode]["summary"]
            middle = data["middle"]
            cells = [str(play["play"]), str(play["line"]), str(play["frames"]), mode,
                     f"{stats['serialize_ms']['p50']:.2f} ({stats['serialize_ms']['min']:.2f})",
                     f"{stats['serialize_ms']['entry']:.2f}",
                     f"{stats['scene_ms']['p50']:.2f}" if "scene_ms" in stats else "–",
                     f"{stats['wire_bytes']['p50'] / 1e3:.1f}",
                     f"{middle.get('movers', '–')}: {middle.get('programs', '–')}"]
            if summary["render"]:
                cells += [f"{stats[key]['p50']:.2f}" if key in stats else "–" for key in ("render_ms", "complete_ms")]
            if summary["browser"]:
                cells.append(" / ".join(f"{play['browser'][f'{mode}_f{fmt}']['page_ms']:.2f}" for fmt in (7, 8)))
            lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--scene", nargs=2, metavar=("FILE", "SCENE"), required=True,
                        help="episode file and scene class")
    parser.add_argument("--plays", nargs="+", type=int, required=True,
                        help="the checkpoints the plays saved (a checkpoint with a run_time)")
    parser.add_argument("--modes", nargs="+", default=["off", "strokes"], help="MANIML_PROGRAMS values, in turn")
    parser.add_argument("--replays", type=int, default=6, help="replays of each play under each mode")
    parser.add_argument("--format", type=int, choices=(7, 8), default=8,
                        help="serialize the format 8 stream a negotiated page is sent, or format 7 full frames")
    parser.add_argument("--render", action="store_true",
                        help="draw each full frame with the native driver through its readback (format 7)")
    parser.add_argument("--browser", action="store_true",
                        help="also replay each mode's play through the browser driver in Node, both formats")
    parser.add_argument("--rounds", type=int, default=5, help="browser replays of each stream, taking turns")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.render and args.format != 7:
        parser.error("--render draws full frames, as native capture does: pass --format 7")
    if min(args.replays, args.rounds) < 1:
        parser.error("replays and rounds must be positive")
    scene_path = Path(os.path.abspath(args.scene[0]))
    if not scene_path.is_file():
        parser.error(f"no scene file at {scene_path}")
    os.environ.update(ENVIRONMENT)
    for key in CLEARED:
        os.environ.pop(key, None)
    from maniml.utils import programs
    for mode in args.modes:
        if mode not in programs.MODES:
            parser.error(f"--modes: {mode} is not one of {programs.MODES}")
    args.output.mkdir(parents=True, exist_ok=True)

    from maniml.web.geometry import _jsonable

    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
        scene, error = load_episode(scene_path, args.scene[1])
    if error is not None:
        raise RuntimeError(f"construct() stopped at checkpoint {error['checkpoint_reached']}: {error['error']}")
    checkpoints = scene.animation_checkpoints
    for target in args.plays:
        if not 0 < target < len(checkpoints) or checkpoints[target].get("run_time") is None:
            parser.error(f"checkpoint {target} saved no play")
    paths = [Path(__file__), ROOT / "benchmarks/episode_frames.py", ROOT / "benchmarks/browser_frames.py",
             HARNESS, ROOT / "maniml/web/static/webgpu.js", *(ROOT / "maniml/web").glob("*.py"),
             *(ROOT / "maniml/animation").glob("*.py"), ROOT / "maniml/utils/programs.py",
             *(ROOT / "maniml/web/static/wgsl").glob("*.wgsl"), scene_path]
    hashes = {str(path.relative_to(ROOT) if path.is_relative_to(ROOT) else path): sha256(path.read_bytes()).hexdigest()
              for path in paths}
    report = {
        "recorded_utc": datetime.now(timezone.utc).isoformat(), "command": sys.argv,
        "scene": {"path": str(scene_path), "name": args.scene[1], "checkpoint_count": len(checkpoints)},
        "git": git_state(ROOT),
        "machine": {"platform": platform.platform(), "machine": platform.machine(), "node": platform.node()},
        "python": platform.python_version(), "numpy": np.__version__, "environment": ENVIRONMENT,
        "gpu_timestamps": os.environ.get("MANIML_GPU_TIMESTAMPS") == "1", "modes": args.modes,
        "replays": args.replays, "format": args.format, "render": args.render, "browser": args.browser,
        "rounds": args.rounds if args.browser else None, "source_files_sha256": hashes, "plays": [],
    }
    for target in args.plays:
        checkpoint = checkpoints[target]
        started = perf_counter()
        play = {"play": target, "line": checkpoint["line_number"], "name": checkpoint.get("name"),
                "run_time": checkpoint["run_time"],
                "frames": play_frame_count(scene.camera.fps, checkpoint["run_time"]),
                "modes": measure_play(scene, target, args.modes, args.replays, args.format, args.render)}
        if args.browser:
            folders = record_browser(scene, target, args.modes, args.output)
            replayed = replay_rounds(list(folders.values()), args.rounds, realm="main")
            play["browser"] = {f"{mode}_f{fmt}": browser_summary(replayed[folder]["frames"])
                               for (mode, fmt), folder in folders.items()}
        play["wall_seconds"] = round(perf_counter() - started, 1)
        report["plays"].append(play)
        print(json.dumps({"play": target, "line": play["line"], **{
            mode: {"serialize_ms": data["summary"]["serialize_ms"]["p50"], **data["middle"]}
            for mode, data in play["modes"].items()}}), flush=True)
        (args.output / "report.json").write_text(json.dumps(report, indent=2, default=_jsonable) + "\n")
    report["source_files_unchanged_during_run"] = all(
        sha256((ROOT / path if not Path(path).is_absolute() else Path(path)).read_bytes()).hexdigest() == value
        for path, value in hashes.items())
    (args.output / "report.json").write_text(json.dumps(report, indent=2, default=_jsonable) + "\n")
    summary = {**{key: value for key, value in report.items() if key != "plays"},
               "plays": [{**play, "modes": {mode: {key: value for key, value in data.items()
                                                   if key not in ("per_frame", "carried_first_replay")}
                                            for mode, data in play["modes"].items()}}
                         for play in report["plays"]]}
    (args.output / "summary.json").write_text(json.dumps(summary, indent=2, default=_jsonable) + "\n")
    table = markdown_table(summary)
    (args.output / "summary.md").write_text(table + "\n")
    print(table)


if __name__ == "__main__":
    main()

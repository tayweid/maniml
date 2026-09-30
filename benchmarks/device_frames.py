"""Recorded streams played on a real WebGPU device (docs/phase_b4_plan.md,
"Phase B as the default", B5.10).

    python -m benchmarks.device_frames prepare --serve <dir> --runs 3 \\
        --streams EpisodeB2=<serialize dir>/streams [...]
    python -m benchmarks.device_frames serve --serve <dir> --port 8741
    (in a WebGPU browser: http://127.0.0.1:8741/device_frames.html?campaign)
    python -m benchmarks.device_frames collect --serve <dir> --scene EpisodeB2 \\
        --serialize <serialize dir> --output <dir>/device

The browser-side complete frame's page and GPU parts, measured on the page's
own device (Chrome's Dawn on Metal) rather than the native driver's
(benchmarks/results/phase_b_test_point_20260927/README.md, "The GPU part is
the native driver's, not the page's"): benchmarks/device_frames.html plays
the streams `flip_gates serialize --record` wrote, the messages whose
Python that run timed, through the viewer's renderer selection into the
real webgpu.js, timing the page's JavaScript in plain rounds and stamping
the GPU in the rounds between (its opening comment says how).

A device reading does not repeat within itself: the GPU's clock follows
its load, and the same recorded messages played again read up to half
their GPU time otherwise (B5.10's review). So a scene is played in several
runs (``--runs``), each on a fresh page after the GPU reads quiet, the odd
runs with the streams in reverse order, and flip_gates reduces them with
an interval over the units, the rounds and the runs.

``prepare`` makes the folder the page is served from: this tree's
webgpu.js, renderer_selection.js and wgsl/ copied beside the page (their
hashes in sources.json), each scene's streams under streams/<scene>/, each
with its parts.json (the whole stream one part, or a stream too large for
one buffer in parts of whole messages), and campaign.json, the jobs (a
scene's streams, the rounds, the run) run by run. ``serve`` serves it on
loopback cross-origin isolated (COOP/COEP, so performance.now has 5 us
resolution): GET next says the campaign's first job without results,
POST quiet/<scene>__run<k> waits until the GPU reads quiet (quiet_gpu)
and stores the reading as results/<scene>__run<k>__quiet.json, and a POST
to save/<name> is stored as results/<name>.json. The page opened with
?campaign runs one job a load and reloads itself for the next. ``collect``
gathers a scene's runs into one report (every stream's per-message
samples run by run, each run's quiet reading and stream order, the device,
the adapter, the page's sources and the streams' digests, which
`flip_gates complete --device` checks against the serialize run).
"""

import argparse
from datetime import datetime, timezone
import gzip
from hashlib import sha256
import http.server
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import time

from benchmarks.episode_frames import ROOT, git_state

PAGE = Path(__file__).with_name("device_frames.html")
STATIC = ROOT / "maniml/web/static"
# The page's files, copied from this tree.
FILES = ("webgpu.js", "renderer_selection.js")


# The most bytes of messages the page holds at once (device_frames.html's
# loadStream reads a larger stream part by part).
PART_BYTES = 512 << 20


def stream_bytes(stream):
    """The bytes of a recorded stream's messages, from its scene.json."""
    return sum(frame["len"] for frame in json.loads((stream / "scene.json").read_text())["frames"])


def split_stream(stream, into):
    """``stream`` served from ``into``: its scene.json and its parts.json
    (first, end, file per part), which the page reads for every stream:
    one part, scene.bin.gz linked, or where its messages exceed PART_BYTES
    parts of consecutive whole messages in place of it. The messages are
    the recording's, byte for byte."""
    into.mkdir(parents=True)
    shutil.copyfile(stream / "scene.json", into / "scene.json")
    frames = json.loads((stream / "scene.json").read_text())["frames"]
    if sum(frame["len"] for frame in frames) <= PART_BYTES:
        (into / "scene.bin.gz").symlink_to((stream / "scene.bin.gz").resolve())
        (into / "parts.json").write_text(json.dumps([{"first": 0, "end": len(frames), "file": "scene.bin.gz"}]) + "\n")
        return
    parts, first, size, name = [], 0, 0, None
    with gzip.open(stream / "scene.bin.gz", "rb") as source:
        out = None
        for index, frame in enumerate(frames):
            if out is None or (size and size + frame["len"] > PART_BYTES):
                if out is not None:
                    out.close()
                    parts.append({"first": first, "end": index, "file": name})
                first, size, name = index, 0, f"part-{len(parts):03d}.bin.gz"
                out = gzip.open(into / name, "wb", compresslevel=1)
            out.write(source.read(frame["len"]))
            size += frame["len"]
        out.close()
        parts.append({"first": first, "end": len(frames), "file": name})
        if source.read(1):
            raise ValueError(f"{stream}: the stream holds more than its frames")
    (into / "parts.json").write_text(json.dumps(parts) + "\n")


def page_sources(directory):
    """sha256 of the page and the driver files a served folder holds."""
    paths = [directory / "device_frames.html", *(directory / name for name in FILES),
             *sorted((directory / "wgsl").glob("*.wgsl"))]
    return {str(path.relative_to(directory)): sha256(path.read_bytes()).hexdigest() for path in paths}


def prepare(serve, streams, runs=3, rounds=5):
    """The served folder (the module's docstring), its campaign ``runs``
    runs of every scene of ``streams`` ({scene: its serialize run's
    streams folder}) in the order given, ``rounds`` plain and as many
    stamped rounds a play."""
    serve.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(PAGE, serve / "device_frames.html")
    for name in FILES:
        shutil.copyfile(STATIC / name, serve / name)
    if (serve / "wgsl").exists():
        shutil.rmtree(serve / "wgsl")
    shutil.copytree(STATIC / "wgsl", serve / "wgsl")
    jobs = []
    for scene, directory in streams.items():
        link = serve / "streams" / scene
        link.parent.mkdir(exist_ok=True)
        if link.is_symlink():
            link.unlink()
        elif link.exists():
            shutil.rmtree(link)
        directory = Path(directory).resolve()
        names = sorted(path.name for path in directory.iterdir() if path.is_dir())
        link.mkdir()
        for name in names:
            split_stream(directory / name, link / name)
        jobs.append({"scene": scene, "streams": names, "rounds": rounds})
    (serve / "campaign.json").write_text(json.dumps(
        [{**job, "run": run} for run in range(runs) for job in jobs], indent=1) + "\n")
    sources = page_sources(serve)
    tree = {str(Path("maniml/web/static") / path): digest for path, digest in sources.items()
            if path != "device_frames.html"}
    tree["benchmarks/device_frames.html"] = sources["device_frames.html"]
    tree["benchmarks/device_frames.py"] = sha256(Path(__file__).read_bytes()).hexdigest()
    (serve / "sources.json").write_text(json.dumps({"served": sources, "tree": tree, "git": git_state(ROOT)},
                                                   indent=2) + "\n")
    return sources


# The GPU reads quiet (B5.10's recipe, before every device job): QUIET_SAMPLES
# ioreg readings a second apart at or below QUIET_PERCENT, waited for at
# most QUIET_LIMIT_S seconds.
QUIET_SAMPLES, QUIET_PERCENT, QUIET_LIMIT_S = 3, 10, 120


def gpu_utilization():
    """The GPU's "Device Utilization %" as ioreg reads it (None where it
    reads none)."""
    text = subprocess.run(["ioreg", "-r", "-d", "1", "-c", "IOAccelerator"], capture_output=True, text=True).stdout
    match = re.search(r'"Device Utilization %"=(\d+)', text)
    return int(match.group(1)) if match else None


def quiet_gpu(limit=QUIET_LIMIT_S, read=gpu_utilization, sleep=time.sleep, clock=time.monotonic):
    """Wait until QUIET_SAMPLES readings a second apart are all at or below
    QUIET_PERCENT, for at most ``limit`` seconds: whether it did, the
    seconds waited, the last readings and the load average."""
    started = clock()
    while True:
        samples = []
        for index in range(QUIET_SAMPLES):
            if index:
                sleep(1)
            samples.append(read())
        quiet = all(sample is not None and sample <= QUIET_PERCENT for sample in samples)
        waited = clock() - started
        if quiet or waited > limit:
            return {"quiet": quiet, "waited_s": round(waited, 1), "gpu_percent": samples,
                    "load": [round(value, 2) for value in os.getloadavg()],
                    "at": datetime.now(timezone.utc).isoformat()}
        sleep(5)


def next_job(root):
    """The campaign's first job some stream of which has no saved result,
    or None."""
    for job in json.loads((root / "campaign.json").read_text()):
        if not all((root / "results" / f"{result_name(job['scene'], job['run'], name)}.json").is_file()
                   for name in job["streams"]):
            return job
    return None


def result_name(scene, run, stream):
    return f"{scene}__run{run}__{stream}"


def handler(root):
    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(root), **kwargs)

        def end_headers(self):
            self.send_header("Cross-Origin-Opener-Policy", "same-origin")
            self.send_header("Cross-Origin-Embedder-Policy", "require-corp")
            self.send_header("Cross-Origin-Resource-Policy", "same-origin")
            self.send_header("Cache-Control", "no-store")
            super().end_headers()

        def reply(self, body):
            data = json.dumps(body).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.path == "/next":
                job = next_job(root)
                self.reply({"done": True} if job is None else {"done": False, "job": job})
                return
            super().do_GET()

        def do_POST(self):
            (root / "results").mkdir(exist_ok=True)
            if self.path.startswith("/quiet/"):
                name = Path(self.path[len("/quiet/"):]).name
                reading = quiet_gpu()
                (root / "results" / f"{name}__quiet.json").write_text(json.dumps(reading) + "\n")
                print(f"{name}: {reading}", flush=True)
                self.reply(reading)
                return
            if not self.path.startswith("/save/"):
                self.send_error(404)
                return
            name = Path(self.path[len("/save/"):]).name
            body = self.rfile.read(int(self.headers["Content-Length"]))
            (root / "results" / f"{name}.json").write_bytes(body)
            self.reply({"saved": name})

        def log_message(self, *args):
            pass
    return Handler


def collect(serve, scene, serialize, output):
    """One scene's device runs as flip_gates complete --device reads them:
    per stream its per-message samples run by run, beside each run's
    quiet reading and stream order and the conditions. Every run must have
    played every message each stream sent, without a device error, on the
    same browser, adapter and rounds."""
    serialize = Path(serialize)
    recorded = json.loads((serialize / "report.json").read_text())
    names = list(recorded["streams"])
    found = sorted({int(match.group(1)) for path in (serve / "results").glob(f"{scene}__run*__*.json")
                    if (match := re.match(re.escape(scene) + r"__run(\d+)__", path.name))})
    if not found:
        raise SystemExit(f"no device run of {scene} in {serve / 'results'}")
    streams, runs, about = {name: {"runs": []} for name in names}, [], None
    for run in found:
        results = {}
        for name in names:
            path = serve / "results" / f"{result_name(scene, run, name)}.json"
            if not path.is_file():
                raise SystemExit(f"run {run} has no device result for {scene} {name} ({path})")
            results[name] = json.loads(path.read_text())
        for name, result in results.items():
            entries = json.loads((serialize / "streams" / name / "scene.json").read_text())["frames"]
            sent = {entry["index"] for entry in entries if entry["len"]}
            played = {message["index"] for message in result["messages"]}
            if played != sent:
                raise SystemExit(f"run {run} {name}: the device played {len(played)} messages, "
                                 f"the stream sent {len(sent)}")
            if result["errors"]:
                raise SystemExit(f"run {run} {name}: device errors {result['errors'][:3]}")
            if about is not None and any(result.get(key) != about.get(key)
                                         for key in ("userAgent", "adapter", "rounds", "warmup_rounds", "stamps")):
                raise SystemExit(f"run {run} {name}: another browser, adapter or rounds than the runs before")
            about = result
            streams[name]["runs"].append({"run": run, "messages": result["messages"], "seconds": result["seconds"],
                                          "started": result["started"], "finished": result["finished"]})
        first = next(iter(results.values()))
        quiet = serve / "results" / f"{scene}__run{run}__quiet.json"
        runs.append({"run": run, "order": first.get("order"), "started": first["started"],
                     "finished": first["finished"], "seconds": first["seconds"],
                     "quiet": json.loads(quiet.read_text()) if quiet.is_file() else None})
    served = json.loads((serve / "sources.json").read_text())
    report = {
        "collected_utc": datetime.now(timezone.utc).isoformat(), "command": sys.argv, "scene": recorded["scene"],
        "git": git_state(ROOT),
        "machine": {"platform": platform.platform(), "machine": platform.machine(), "node": platform.node()},
        "user_agent": about["userAgent"], "adapter": about["adapter"], "timestamps": about["timestamps"],
        "cross_origin_isolated": about["crossOriginIsolated"], "visibility": about.get("visibility"),
        "rounds": about["rounds"], "warmup_rounds": about.get("warmup_rounds"), "modes": about["modes"],
        "stamps": about.get("stamps"),
        "overflow": max(json.loads((serve / "results" / f"{result_name(scene, run, name)}.json").read_text())["overflow"]
                        for run in found for name in names),
        "runs": runs,
        # The page's sources as served, and this tree's names for them, so
        # the gate holds the device run to the serialize run's tree.
        "page_sources": served["served"], "source_files_sha256": served["tree"],
        "streams_sha256": {name: sha256((serialize / "streams" / name / "scene.bin.gz").read_bytes()).hexdigest()
                           for name in streams},
        "streams": streams,
    }
    output.mkdir(parents=True, exist_ok=True)
    (output / "report.json").write_text(json.dumps(report) + "\n")
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    made = commands.add_parser("prepare", help="the folder the page is served from, and its campaign")
    made.add_argument("--serve", type=Path, required=True)
    made.add_argument("--streams", nargs="+", default=[], metavar="SCENE=DIR",
                      help="a scene's recorded streams (flip_gates serialize --record's <output>/streams)")
    made.add_argument("--runs", type=int, default=3, help="runs of every scene, each on a fresh page")
    made.add_argument("--rounds", type=int, default=5, help="plain rounds a run, and as many stamped")
    served = commands.add_parser("serve", help="serve the folder on loopback, cross-origin isolated")
    served.add_argument("--serve", type=Path, required=True)
    served.add_argument("--port", type=int, default=8741)
    gathered = commands.add_parser("collect", help="a scene's device runs as one report")
    gathered.add_argument("--serve", type=Path, required=True)
    gathered.add_argument("--scene", required=True)
    gathered.add_argument("--serialize", type=Path, required=True, help="the serialize run that recorded them")
    gathered.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "prepare":
        streams = dict(item.split("=", 1) for item in args.streams)
        print(json.dumps(prepare(args.serve, streams, args.runs, args.rounds), indent=2))
    elif args.command == "serve":
        server = http.server.ThreadingHTTPServer(("127.0.0.1", args.port), handler(args.serve.resolve()))
        print(f"http://127.0.0.1:{server.server_address[1]}/device_frames.html?campaign", flush=True)
        server.serve_forever()
    else:
        report = collect(args.serve, args.scene, args.serialize, args.output)
        print(f"{args.scene}: {len(report['runs'])} runs, " + ", ".join(
            f"{name} {len(stream['runs'][0]['messages'])} messages" for name, stream in report["streams"].items()))


if __name__ == "__main__":
    main()

"""B5.1's native side: the complete native frame (serialize_scene, then
WgpuRenderer.render() through its readback) over the play into a
pausepoint, Phase B, MANIML_PATCH_SOURCE=records against rows, retained
frame on. As gate.py: each replay of the play goes through one source only
(so each pays its own reads' refreshes), the sources alternating replay by
replay, each with its own GeometryCache and WgpuRenderer kept across its
replays. Reduction: each frame's median over its replays, then the median
over the frames (and the minimum over every sample). argv: path scene
checkpoint rounds stamps(0|1). stamps=1 is the attribution run
(MANIML_GPU_TIMESTAMPS=1): gpu_total and per-label exclusive ms, read after
the timers stop; its wall columns are not the gate's."""
import gc, io, json, os, sys, time
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
import numpy as np
path, name, gate, rounds, stamps = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4]), sys.argv[5] == "1"
os.environ.update(MANIML_FILL="patches", MANIML_SURFACE="nets", MANIML_PROGRAMS="gpu",
                  MANIML_BORDER_GENERATOR="gpu", MANIML_RETAINED_FRAME="1")
if stamps:
    os.environ["MANIML_GPU_TIMESTAMPS"] = "1"
else:
    os.environ.pop("MANIML_GPU_TIMESTAMPS", None)
from benchmarks.episode_frames import load_episode, play_before, replay_play, show_frame
from maniml.web.geometry import GeometryCache, serialize_scene, parse_geometry_message
from maniml.web.wgpu_renderer import WgpuRenderer
with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
    scene, error = load_episode(Path(path), name)
assert error is None, error
target = play_before(scene.animation_checkpoints, gate)
sources = ("records", "rows")
caches = {s: GeometryCache() for s in sources}
drivers = {s: WgpuRenderer() for s in sources}
replays = {s: [] for s in sources}


def draw(source, record):
    scene.camera.refresh_uniforms()
    started = time.perf_counter()
    message = serialize_scene(scene, caches[source], renderer="phase_b")
    serialized = time.perf_counter()
    header, payload = parse_geometry_message(message)
    header["renderer"] = "triangles"
    parsed = time.perf_counter()
    drivers[source].render(header, payload)
    rendered = time.perf_counter()
    row = {"serialize": 1000 * (serialized - started), "render": 1000 * (rendered - parsed)}
    row["complete"] = row["serialize"] + row["render"]
    if stamps:
        timings = drivers[source].gpu_timings
        row["gpu_total"] = timings["total_ms"]
        for p in timings["passes"]:
            key = "gpu_" + p["label"]
            row[key] = row.get(key, 0) + p["exclusive_ms"]
            row["passes_" + p["label"]] = row.get("passes_" + p["label"], 0) + 1
    if record is not None:
        record.append(row)


for index in range(2 * rounds):
    source = sources[index % 2]
    os.environ["MANIML_PATCH_SOURCE"] = source
    frames = []
    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
        show_frame(scene, target - 1)
        draw(source, None)
        gc.collect()
        replay_play(scene, target, lambda k: draw(source, frames))
    replays[source].append(frames)
report = {"scene": name, "gate": gate, "play": target, "rounds": rounds, "stamps": stamps,
          "frames": len(replays["records"][0])}
for s in sources:
    keys = sorted({k for replay in replays[s] for row in replay for k in row})
    report[s] = {}
    for k in keys:
        grid = np.array([[row.get(k, 0.0) for row in replay] for replay in replays[s]])
        per_frame = np.median(grid, axis=0)
        report[s][k] = [round(float(np.median(per_frame)), 2), round(float(grid.min()), 2)]
print(json.dumps(report))

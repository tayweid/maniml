"""B5.6 context: the complete native frame of a navigation, records against
rows, the forced Phase B. A round walks the episode's twelve measured
pausepoints (episode_frames.select_frames) in order, each restored as a
navigation restores it and drawn once (serialize_scene, then
WgpuRenderer.render() through its readback), then once more as a still.
Each round goes through one source only, the two alternating round by
round, each with its own GeometryCache and WgpuRenderer kept across its
rounds as a viewer's page is. Reduction: each frame's median over its
rounds, then the median over the frames (the minimum over every sample
beside it), for the seek frames and the still frames apart.
argv: path scene rounds."""
import gc
import io
import json
import os
import sys
import time
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import numpy as np

path, name, rounds = sys.argv[1], sys.argv[2], int(sys.argv[3])
os.environ.update(MANIML_BORDER_GENERATOR="gpu", MANIML_RETAINED_FRAME="1", MANIML_PROGRAMS="gpu")
os.environ.pop("MANIML_GPU_TIMESTAMPS", None)
from benchmarks.episode_frames import load_episode, select_frames, show_frame
from maniml.web.geometry import GeometryCache, parse_geometry_message, serialize_scene
from maniml.web.wgpu_renderer import WgpuRenderer

with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
    scene, error = load_episode(Path(path), name)
assert error is None, error
stops = select_frames(scene.animation_checkpoints)
sources = ("records", "rows")
caches = {s: GeometryCache() for s in sources}
drivers = {s: WgpuRenderer() for s in sources}
replays = {s: [] for s in sources}


def draw(source):
    scene.camera.refresh_uniforms()
    started = time.perf_counter()
    message = serialize_scene(scene, caches[source], renderer="phase_b")
    serialized = time.perf_counter()
    header, payload = parse_geometry_message(message)
    header["renderer"] = "triangles"
    parsed = time.perf_counter()
    drivers[source].render(header, payload)
    rendered = time.perf_counter()
    row = {"serialize": 1000 * (serialized - started), "render": 1000 * (rendered - parsed), "bytes": len(message)}
    row["complete"] = row["serialize"] + row["render"]
    return row


for index in range(2 * rounds):
    source = sources[index % 2]
    os.environ["MANIML_PATCH_SOURCE"] = source
    rows = []
    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
        gc.collect()
        for stop in stops:
            show_frame(scene, stop)
            rows.append(("seek", draw(source)))
            rows.append(("still", draw(source)))
    replays[source].append(rows)
report = {"scene": name, "rounds": rounds, "pausepoints": stops}
for s in sources:
    report[s] = {}
    for kind in ("seek", "still"):
        for key in ("serialize", "render", "complete", "bytes"):
            grid = np.array([[row[key] for k, row in replay if k == kind] for replay in replays[s]])
            per_frame = np.median(grid, axis=0)
            report[s][f"{kind}_{key}"] = [round(float(np.median(per_frame)), 2), round(float(grid.min()), 2)]
print(json.dumps(report))

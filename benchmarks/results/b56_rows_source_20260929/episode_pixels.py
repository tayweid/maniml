"""Rows against records, natively, on every pausepoint of an episode and on
the frames of its gate play: the Phase B stack (patches, nets, programs) with
MANIML_PATCH_SOURCE records then rows, one driver and one cache each, one
scene. Prints per frame the share of pixels off by more than 24/255 and the
largest channel difference; a JSON summary at the end."""
import io, json, os, sys, time
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
import numpy as np
os.environ.update(MANIML_FILL="patches", MANIML_SURFACE="nets", MANIML_PROGRAMS="gpu", MANIML_BORDER_GENERATOR="gpu")
from benchmarks.episode_frames import load_episode, play_before, replay_play, show_frame, select_frames
from maniml.web.geometry import GeometryCache, serialize_scene, parse_geometry_message
from maniml.web.wgpu_renderer import WgpuRenderer

path, name, gate = sys.argv[1], sys.argv[2], int(sys.argv[3])
with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
    scene, error = load_episode(Path(path), name)
assert error is None, error
drivers = {source: WgpuRenderer() for source in ("records", "rows")}
caches = {source: GeometryCache() for source in drivers}
rows_out = []

def compare(label):
    scene.camera.refresh_uniforms()
    images, sent = {}, {}
    for source in ("records", "rows"):
        os.environ["MANIML_PATCH_SOURCE"] = source
        header, payload = parse_geometry_message(serialize_scene(scene, caches[source], renderer="phase_b"))
        header["renderer"] = "triangles"
        images[source] = np.asarray(drivers[source].render(header, payload), dtype=int)
        sent[source] = sum("rows" in batch for batch in header["batches"])
    diff = np.abs(images["records"] - images["rows"])
    row = {"frame": label, "over_24": float((diff.max(axis=2) > 24).mean()), "max": int(diff.max()),
           "rows_batches": sent["rows"], "record_rows_batches": sent["records"]}
    rows_out.append(row)
    print(f"{label:28s} over24 {100 * row['over_24']:8.4f}%  max {row['max']:3d}  rows batches {sent['rows']}", flush=True)

checkpoints = scene.animation_checkpoints
stops = select_frames(checkpoints, max_frames=10 ** 6)
started = time.time()
with redirect_stderr(io.StringIO()):
    for index in stops:
        with redirect_stdout(io.StringIO()):
            show_frame(scene, index)
        compare(f"pausepoint {index} ({checkpoints[index].get('name')})")
    target = play_before(checkpoints, gate)
    with redirect_stdout(io.StringIO()):
        show_frame(scene, gate)
    replay_play(scene, target, lambda k: compare(f"play into {gate}, frame {k}"))
worst = max(rows_out, key=lambda row: (row["over_24"], row["max"]))
summary = {"scene": name, "frames": len(rows_out), "pausepoints": len(stops),
           "worst": worst, "max_over_24": max(r["over_24"] for r in rows_out),
           "max_channel": max(r["max"] for r in rows_out), "seconds": round(time.time() - started, 1)}
print(json.dumps(summary))

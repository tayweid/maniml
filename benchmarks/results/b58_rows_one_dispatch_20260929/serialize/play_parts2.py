"""The 8.a play's serialize under the forced Phase B (rows), with chosen
functions wrapped by timers (inclusive), per frame; median over frames of the
median over replays. argv: path scene gate replays"""
import gc, io, os, sys, time, functools, json
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
import numpy as np
os.environ.update(MANIML_BORDER_GENERATOR="gpu", MANIML_RETAINED_FRAME="1", MANIML_PROGRAMS="gpu", MANIML_PATCH_SOURCE="rows")
os.environ.pop("MANIML_GPU_TIMESTAMPS", None)
from benchmarks.episode_frames import load_episode, play_before, replay_play, show_frame
from maniml.web.geometry import GeometryCache, serialize_scene
import maniml.web.gpu_border_geometry as gb, maniml.web.generated_geometry as gg, maniml.web.triangle_scene as ts
import maniml.web.retained_frame as rf, maniml.web.gpu_program_geometry as gp
acc = {}
def wrap(owner, name, label):
    f = getattr(owner, name, None)
    if f is None: return
    @functools.wraps(f)
    def w(*a, **k):
        t = time.perf_counter()
        try: return f(*a, **k)
        finally: acc[label] = acc.get(label, 0.0) + time.perf_counter() - t
    setattr(owner, name, w)
wrap(gb.RowsSource, "read", "RowsSource.read")
if hasattr(gp, "split_rows"):
    wrap(gp, "split_rows", "split_rows")
wrap(gb.BorderRecipeCache, "rows", "BorderRecipeCache.rows")
wrap(gg, "_row_digests", "_row_digests")
wrap(rf, "encode_draw", "encode_draw")
wrap(rf, "prepare_leaf", "prepare_leaf")
wrap(rf, "combine_run", "combine_run"); wrap(rf, "finish_triangle_frame", "finish_triangle_frame"); wrap(rf, "_same_value", "_same_value"); wrap(rf, "assemble_message", "assemble_message"); wrap(rf, "stream_message", "stream_message")
wrap(gp, "rows_key", "rows_key")
wrap(json, "dumps", "json.dumps")
path, name, gate, replays = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4])
with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
    scene, error = load_episode(Path(path), name)
target = play_before(scene.animation_checkpoints, gate)
cache = GeometryCache(); cache.negotiate(True)
grid = []
def run(record):
    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
        show_frame(scene, target - 1)
        serialize_scene(scene, cache, renderer="phase_b")
        gc.collect()
        def one(k):
            scene.camera.refresh_uniforms()
            acc.clear()
            t = time.perf_counter(); serialize_scene(scene, cache, renderer="phase_b")
            record.append({"total": time.perf_counter() - t, **acc})
        replay_play(scene, target, one)
for r in range(replays):
    rec = []; run(rec); grid.append(rec)
keys = sorted({k for rec in grid for f in rec for k in f})
out = {}
for k in keys:
    g = np.array([[f.get(k, 0.0) for f in rec] for rec in grid]) * 1000
    out[k] = round(float(np.median(np.median(g, axis=0))), 2)
print(json.dumps(out))

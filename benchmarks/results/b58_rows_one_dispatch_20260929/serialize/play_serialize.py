"""Serialize the play into a checkpoint under the forced Phase B (rows), replays alternating nothing:
median serialize per frame over replays; optional cProfile of one replay. argv: path scene gate replays [prof]"""
import gc, io, os, sys, time, cProfile, pstats
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
import numpy as np
os.environ.update(MANIML_BORDER_GENERATOR="gpu", MANIML_RETAINED_FRAME="1", MANIML_PROGRAMS="gpu", MANIML_PATCH_SOURCE="rows")
os.environ.pop("MANIML_GPU_TIMESTAMPS", None)
from benchmarks.episode_frames import load_episode, play_before, replay_play, show_frame
from maniml.web.geometry import GeometryCache, serialize_scene
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
            t = time.perf_counter(); serialize_scene(scene, cache, renderer="phase_b"); record.append(1000 * (time.perf_counter() - t))
        replay_play(scene, target, one)
for r in range(replays):
    rec = []; run(rec); grid.append(rec)
g = np.array(grid)
print("serialize per frame median", round(float(np.median(np.median(g, axis=0))), 2), "min", round(float(g.min()), 2))
if len(sys.argv) > 5:
    prof = cProfile.Profile(); prof.enable(); run([]); prof.disable(); prof.dump_stats(sys.argv[5])

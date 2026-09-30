"""Ticked frames, Phase A forced against the forced Phase B (format 8), each tick
followed by one serializer, the two alternating with the phase swapped every round:
python tick_profile.py <scene file> <class> <checkpoint> [ticks] [profile]"""
import cProfile, io, os, pstats, sys
from contextlib import redirect_stderr, redirect_stdout
from time import perf_counter
os.environ.update({"MANIML_RETAINED_FRAME": "1", "MANIML_PROGRAMS": "off"})
for key in ("MANIML_VERIFY_LEDGER", "MANIML_RENDER_CACHE", "MANIML_GPU_TIMESTAMPS", "MANIML_NET_RUNS",
            "MANIML_PATCH_SOURCE", "MANIML_FILL", "MANIML_SURFACE"):
    os.environ.pop(key, None)
import numpy as np
from benchmarks.episode_frames import load_episode, show_frame
from benchmarks.flip_gates import stack_environment, stacks
from maniml.web.geometry import GeometryCache, serialize_scene
if os.environ.get("NOFAST"):
    from maniml.web import retained_frame, triangle_scene
    retained_frame.RetainedFrame._coalesce = lambda self, draws, **kw: triangle_scene.coalesce_draws(draws, **kw)
path, name, checkpoint = sys.argv[1], sys.argv[2], int(sys.argv[3])
ticks = int(sys.argv[4]) if len(sys.argv) > 4 else 200
profile = len(sys.argv) > 5
with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
    scene, error = load_episode(os.path.abspath(path), name)
show_frame(scene, checkpoint)
serializers = {n: (r, e) for n, r, e in stacks("phase_b")}
names = list(serializers)
caches = {n: GeometryCache() for n in serializers}
for c in caches.values():
    c.negotiate(True)
def serialize(n):
    r, e = serializers[n]
    with stack_environment(e):
        t = perf_counter(); m = serialize_scene(scene, caches[n], renderer=r); return 1000 * (perf_counter() - t), m
for n in names:
    serialize(n)
profiles = {n: cProfile.Profile() for n in names}
times = {n: [] for n in names}
for t in range(ticks):
    n = names[(t + t // 2) % 2]
    scene.update_mobjects(1 / scene.camera.fps); scene.camera.refresh_uniforms()
    if profile and t >= 20:
        profiles[n].enable()
    ms, m = serialize(n)
    if profile and t >= 20:
        profiles[n].disable()
    if t >= 20:
        times[n].append(ms)
    if t < 4:
        s = caches[n].retained_frame.stats
        print(n, round(ms, 2), m is not None, {k: s.get(k) for k in ("leaves_kept", "leaves_prepared", "leaves_compared", "batches_reused", "batches_encoded", "runs_kept", "runs_combined")})
for n, v in times.items():
    print(n, "median", round(float(np.median(v)), 3), "mean", round(float(np.mean(v)), 3), "min", round(min(v), 3), len(v))
if profile:
    for n, p in profiles.items():
        s = io.StringIO(); pstats.Stats(p, stream=s).sort_stats(os.environ.get("SORT", "tottime")).print_stats(int(os.environ.get("TOP", "25"))); print(n); print(s.getvalue()[:5500])

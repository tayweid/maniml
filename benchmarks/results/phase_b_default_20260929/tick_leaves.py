import io, os, sys
from collections import Counter
from contextlib import redirect_stderr, redirect_stdout
os.environ.update({"MANIML_RETAINED_FRAME": "1", "MANIML_PROGRAMS": "off"})
from benchmarks.episode_frames import load_episode, show_frame
from benchmarks.flip_gates import stack_environment, stacks
from maniml.web.geometry import GeometryCache, serialize_scene
from maniml.web.retained_frame import compare_rows
path, name, checkpoint = sys.argv[1], sys.argv[2], int(sys.argv[3])
with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
    scene, error = load_episode(os.path.abspath(path), name)
show_frame(scene, checkpoint)
(n, r, e) = stacks("phase_b")[1]
cache = GeometryCache(); cache.negotiate(True)
def ser():
    with stack_environment(e):
        return serialize_scene(scene, cache, renderer=r)
ser(); ser()
before = dict(cache.retained_frame.leaves)
revs = {k: v.revision for k, v in before.items()}
scene.update_mobjects(1 / scene.camera.fps); scene.camera.refresh_uniforms()
from maniml.web.triangle_scene import draw_order
leaves = draw_order(scene)
moved = [sm for sm in leaves if id(sm) in before and before[id(sm)].revision != sm.revision]
new = [sm for sm in leaves if id(sm) not in before]
print("leaves", len(leaves), "moved revision", len(moved), "new objects", len(new))
print("moved types", Counter(type(sm).__name__ for sm in moved).most_common(8))
verdicts = Counter()
for sm in moved:
    entry = before[id(sm)]
    v = compare_rows(sm, entry) if entry.rows is not None else "no rows"
    verdicts[str(v)] += 1
print("compare_rows verdicts", verdicts)
import numpy as np
for sm in moved[:40]:
    entry = before[id(sm)]
    if entry.rows is None or compare_rows(sm, entry) is not None:
        continue
    live = sm._data
    diff = [f for f in live.dtype.names if live[f].tobytes() != entry.rows[f].tobytes()] if live.shape == entry.rows.shape else ["shape"]
    print(type(sm).__name__, sm.revision, "columns that differ:", diff, "updaters", len(sm.get_updaters()) if hasattr(sm, 'get_updaters') else '?')
    break
m = ser(); print("message", m is not None, cache.retained_frame.stats)

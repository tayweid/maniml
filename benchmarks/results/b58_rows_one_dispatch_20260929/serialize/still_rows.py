"""Native WgpuRenderer on still frames of the forced Phase B (rows): each of
the given pausepoints restored, drawn once, then drawn N more times as
stills; per still, _prepare_rows' time and render()'s. Medians.
argv: path scene checkpoints N"""
import io, os, sys, time, json, statistics
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
os.environ.update(MANIML_BORDER_GENERATOR="gpu", MANIML_RETAINED_FRAME="1", MANIML_PROGRAMS="gpu", MANIML_PATCH_SOURCE="rows")
os.environ.pop("MANIML_GPU_TIMESTAMPS", None)
from benchmarks.episode_frames import load_episode, show_frame
from maniml.web.geometry import GeometryCache, parse_geometry_message, serialize_scene
from maniml.web.wgpu_renderer import WgpuRenderer
path, name, stops, n = sys.argv[1], sys.argv[2], [int(x) for x in sys.argv[3].split(",")], int(sys.argv[4])
with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
    scene, error = load_episode(Path(path), name)
driver, cache = WgpuRenderer(), GeometryCache()
spent = [0.0]
original = WgpuRenderer._prepare_rows
def timed(self, *a):
    t = time.perf_counter()
    try: return original(self, *a)
    finally: spent[0] += time.perf_counter() - t
WgpuRenderer._prepare_rows = timed
out = {}
for stop in stops:
    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
        show_frame(scene, stop)
    prep, render = [], []
    for k in range(n + 1):
        scene.camera.refresh_uniforms()
        header, payload = parse_geometry_message(serialize_scene(scene, cache, renderer="phase_b"))
        header["renderer"] = "triangles"
        spent[0] = 0.0
        t = time.perf_counter(); driver.render(header, payload); dt = time.perf_counter() - t
        if k:
            prep.append(1000 * spent[0]); render.append(1000 * dt)
    out[stop] = {"prepare_rows": round(statistics.median(prep), 3), "render": round(statistics.median(render), 2),
                 "batches": len(header["batches"])}
print(json.dumps(out))

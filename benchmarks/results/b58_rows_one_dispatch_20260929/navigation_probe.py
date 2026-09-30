"""B5.8: what a navigation sends and finalizes under the forced Phase B,
records against rows, format 7, one cache and one native driver per source,
walking the given checkpoints in order. Per message: the wire, the batches
and those held (cached), the definitions sent by kind (rows' geometry and
paint, border records, object tables) with their bytes, and, drawn by the
native driver, its compute dispatches of the row finalize, the members they
finalize, and the border stage's dispatches. argv: path scene checkpoints"""
import io, os, sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
os.environ.update(MANIML_BORDER_GENERATOR="gpu", MANIML_RETAINED_FRAME="1", MANIML_PROGRAMS="gpu")
for k in ("MANIML_FILL", "MANIML_SURFACE", "MANIML_PATCH_SOURCE", "MANIML_GPU_TIMESTAMPS", "MANIML_NET_RUNS"):
    os.environ.pop(k, None)
import maniml
print("maniml from", maniml.__file__, file=sys.stderr)
from benchmarks.episode_frames import load_episode, show_frame
from maniml.web.geometry import GeometryCache, parse_geometry_message, serialize_scene
from maniml.web.wgpu_renderer import WgpuRenderer
E = Path(sys.argv[1]); name = sys.argv[2]; seq = [int(x) for x in sys.argv[3].split(",")]
with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
    scene, err = load_episode(E, name)
assert err is None, err
sources = ("records", "rows")
caches = {s: GeometryCache() for s in sources}
drivers = {s: WgpuRenderer() for s in sources}
counted = {}
original = WgpuRenderer._finalize_rows
def counting(self, changed, *args):
    counted[id(self)] = counted.get(id(self), 0) + len(changed)
    return original(self, changed, *args)
WgpuRenderer._finalize_rows = counting
sent_geometry = {s: {} for s in sources}   # hash -> first stop it was sent at
for stop in seq:
    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
        show_frame(scene, stop)
    scene.camera.refresh_uniforms()
    for s in sources:
        os.environ["MANIML_PATCH_SOURCE"] = s
        msg = serialize_scene(scene, caches[s], renderer="phase_b")
        header, payload = parse_geometry_message(msg)
        b = header["batches"]
        pd = header.get("program_data", {})
        geometry = {k for x in b if "rows" in x for k in x["rows"]}
        paints = {k for x in b if "rows" in x for k in x.get("row_paints", ())}
        g_sent = [k for k in pd if k in geometry]
        p_sent = [k for k in pd if k in paints]
        again = sum(k in sent_geometry[s] for k in g_sent)
        for k in g_sent:
            sent_geometry[s].setdefault(k, stop)
        header["renderer"] = "triangles"
        driver = drivers[s]
        counted[id(driver)] = 0
        passes_before = None
        driver.render(header, payload)
        print(f"{stop:4d} {s:7s} wire {len(msg)/1024:8.1f} KB  batches {len(b):4d} held {sum(bool(x.get('cached')) for x in b):4d}  "
              f"rows geometry sent {len(g_sent):4d} ({sum(pd[k]['nbytes'] for k in g_sent)/1024:7.1f} KB, {again} sent before)  "
              f"paint sent {len(p_sent):3d} ({sum(pd[k]['nbytes'] for k in p_sent)/1024:5.1f} KB)  "
              f"border_data {len(header.get('border_data', {})):4d} ({sum(v['nbytes'] for v in header.get('border_data', {}).values())/1024:7.1f} KB)  "
              f"object_data {len(header.get('object_data', {})):3d}  finalized members {counted[id(driver)]:4d}", flush=True)
for d in drivers.values():
    d.close()

"""Navigation 258 -> 277 (and others) under the forced Phase B: batches
marked cached with records vs rows, one cache per source, format 7.
argv: path scene comma-separated checkpoints."""
import io, os, sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
os.environ.update(MANIML_BORDER_GENERATOR="gpu", MANIML_RETAINED_FRAME="1", MANIML_PROGRAMS="gpu")
for k in ("MANIML_FILL", "MANIML_SURFACE", "MANIML_PATCH_SOURCE", "MANIML_GPU_TIMESTAMPS"):
    os.environ.pop(k, None)
from benchmarks.episode_frames import load_episode, select_frames, show_frame
from maniml.web.geometry import GeometryCache, parse_geometry_message, serialize_scene
E = Path(sys.argv[1]); name = sys.argv[2]; seq = [int(x) for x in sys.argv[3].split(",")]
with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
    scene, err = load_episode(E, name)
assert err is None, err
caches = {s: GeometryCache() for s in ("records", "rows")}
for s in caches: caches[s].negotiate(False)
prev_rows = {}
for stop in seq:
    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
        show_frame(scene, stop)
    out = {}
    for s, cache in caches.items():
        os.environ["MANIML_PATCH_SOURCE"] = s
        msg = serialize_scene(scene, cache, renderer="phase_b")
        header, payload = parse_geometry_message(msg)
        b = header["batches"]
        out[s] = header
        cached = sum(bool(x.get("cached")) for x in b)
        rows_batches = [x for x in b if "rows" in x]
        print(stop, s, "batches", len(b), "cached", cached, "rows batches", len(rows_batches),
              "rows cached", sum(bool(x.get("cached")) for x in rows_batches),
              "bytes", len(msg), "program_data", len(header.get("program_data", {})), "border_data", len(header.get("border_data", {})))
    # pairwise: batches cached under records but not under rows (same index)
    rb, wb = out["records"]["batches"], out["rows"]["batches"]
    if len(rb) == len(wb):
        diff = [i for i in range(len(rb)) if rb[i].get("cached") and not wb[i].get("cached")]
        print("  cached in records, not rows:", len(diff))
        if diff:
            i = diff[0]
            print("  sample records batch keys", sorted(rb[i].keys()))
            print("  sample rows batch keys", sorted(wb[i].keys()))
            print("  pipelines", {rb[j]["pipeline"] for j in diff})

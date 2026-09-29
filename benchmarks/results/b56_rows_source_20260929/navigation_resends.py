"""A navigation under the forced Phase B with rows (EpisodeB2 258 -> 277):
how many rows batches were held, and, for each rows definition re-sent that
the receiver did not hold, which columns differ from a rows definition of
the same points sent at the frame before (the paint alone, stroke_rgba and
fill_rgba, on a dim). argv: path scene from to."""
import io, os, sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
import numpy as np
os.environ.update(MANIML_BORDER_GENERATOR="gpu", MANIML_RETAINED_FRAME="1", MANIML_PROGRAMS="gpu")
for k in ("MANIML_FILL", "MANIML_SURFACE", "MANIML_PATCH_SOURCE", "MANIML_GPU_TIMESTAMPS"):
    os.environ.pop(k, None)
from benchmarks.episode_frames import load_episode, show_frame
from maniml.web.geometry import GeometryCache, parse_geometry_message, serialize_scene
E = Path(sys.argv[1]); name = sys.argv[2]; a, b = int(sys.argv[3]), int(sys.argv[4])
with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
    scene, err = load_episode(E, name)
cache = GeometryCache()
os.environ["MANIML_PATCH_SOURCE"] = "rows"
frames = {}
for stop in (a, b):
    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
        show_frame(scene, stop)
    sent_before = set(cache.sent)
    msg = serialize_scene(scene, cache, renderer="phase_b")
    header, payload = parse_geometry_message(msg)
    frames[stop] = (header, payload, sent_before)
h, p, sent_before = frames[b]
ha, pa, _ = frames[a]
def rowdata(header, payload, key):
    ref = header["program_data"].get(key)
    if ref is None: return None
    return np.frombuffer(payload[ref["offset"]:ref["offset"] + ref["nbytes"]], dtype="<f4").reshape(-1, 17)
held_rows = sum(all(f"rows:{k}" in sent_before for k in x["rows"]) for x in h["batches"] if "rows" in x)
print("rows batches whose rows were all held:", held_rows, "of", sum("rows" in x for x in h["batches"]))
not_cached = [x for x in h["batches"] if "rows" in x and not x.get("cached")]
print("not cached", len(not_cached))
held_hash = sum(x["hash"] in sent_before for x in not_cached)
print("not cached but hash held:", held_hash)
# find for a non-cached batch whose rows not held, a batch in frame a with the same point columns
prev_rows = {}
for x in ha["batches"]:
    if "rows" in x:
        for k in x["rows"]:
            d = rowdata(ha, pa, k)
            if d is not None:
                prev_rows.setdefault((d.shape[0], d[:, :3].round(5).tobytes()), (k, d))
fields = {"point": slice(0, 3), "stroke_rgba": slice(3, 7), "stroke_width": slice(7, 8), "joint_angle": slice(8, 9),
          "fill_rgba": slice(9, 13), "base_normal": slice(13, 16), "border_width": slice(16, 17)}
shown = 0
from collections import Counter
counts = Counter()
for x in not_cached:
    for k in x["rows"]:
        if f"rows:{k}" in sent_before: continue
        d = rowdata(h, p, k)
        if d is None: continue
        m = prev_rows.get((d.shape[0], d[:, :3].round(5).tobytes()))
        if m is None:
            counts["no match by points"] += 1; continue
        pk, pd = m
        diffs = [f for f, s in fields.items() if not np.array_equal(d[:, s], pd[:, s])]
        counts[tuple(diffs)] += 1
        if shown < 3 and diffs:
            shown += 1
            for f in diffs:
                s = fields[f]
                idx = np.nonzero((d[:, s] != pd[:, s]).any(axis=1))[0][:3]
                print("  ", f, "rows", idx, "now", d[idx, s].tolist(), "before", pd[idx, s].tolist())
print(counts)

"""How much of a format 7 still message after a navigation the row_paints
lists are: EpisodeB2's twelve pausepoints, each restored, drawn, then drawn
again (the still), under the forced Phase B with rows."""
import io, json, os, sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
os.environ.update(MANIML_BORDER_GENERATOR="gpu", MANIML_RETAINED_FRAME="1", MANIML_PROGRAMS="gpu")
from benchmarks.episode_frames import load_episode, select_frames, show_frame
from maniml.web.geometry import GeometryCache, parse_geometry_message, serialize_scene
with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
    scene, error = load_episode(Path(sys.argv[1]), sys.argv[2])
assert error is None
cache = GeometryCache()
rows = []
for stop in select_frames(scene.animation_checkpoints):
    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
        show_frame(scene, stop)
        scene.camera.refresh_uniforms(); serialize_scene(scene, cache, renderer="phase_b")
        scene.camera.refresh_uniforms(); message = serialize_scene(scene, cache, renderer="phase_b")
    header, payload = parse_geometry_message(message)
    paints = sum(len(json.dumps(b["row_paints"])) + len('"row_paints": , ') for b in header["batches"] if "row_paints" in b)
    names = sum(len(b["row_paints"]) for b in header["batches"] if "row_paints" in b)
    rows.append((stop, len(message), paints, names))
import statistics
print("median message", statistics.median(r[1] for r in rows), "median row_paints bytes", statistics.median(r[2] for r in rows),
      "median paint names", statistics.median(r[3] for r in rows))
for r in rows: print(r)

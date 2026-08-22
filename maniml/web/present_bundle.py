"""The present bundle: the rendered mp4 plus its pausepoint table.

``media/<Scene>_present/`` holds ``scene.mp4`` (the ``--render`` output,
copied) and ``present.json`` — everything a video presenter needs to step
the recording by pausepoints. This is the t1-web model (a <video>, an array
of timestamps, stepped scrubbing both directions) with the inputs generated
instead of hand-marked: per-checkpoint timestamps come from the state each
checkpoint already stores (``SceneState.time``, the writer's own timebase),
stop/loop flags from ``pause()``, and the chip mapping from the same rule
the live rail uses (``chip_unit_for``), so the presenter's rail and the
live viewer's always agree.
"""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

from maniml.scene.source_map import chip_unit_for

FORMAT = 1
BUNDLE_MOVIE = "scene.mp4"
BUNDLE_META = "present.json"

_STATIC_DIR = Path(__file__).parent / "static"
# The standalone presenter: index.html opens from disk (file://), so the
# meta also ships as a script (present_meta.js) — fetch() does not exist
# there. present.json stays for the live viewer, which loads over HTTP.
BUNDLE_PAGES = ("present.html", "presentation.js")


def bundle_dir_for(scene) -> Path | None:
    """Where the scene's present bundle lives: media/<Scene>_present."""
    raw_source = getattr(scene, "_scene_filepath", None)
    if not raw_source:
        return None
    return Path(raw_source).parent / "media" / f"{type(scene).__name__}_present"


def source_fingerprint(source_path: Path) -> dict:
    """Identity of the scene file a bundle was baked from, for staleness."""
    return {
        "file": source_path.name,
        "mtime": source_path.stat().st_mtime,
        "hash": hashlib.blake2b(
            source_path.read_bytes(), digest_size=16).hexdigest(),
    }


def build_meta(scene) -> dict:
    """The pausepoint table, from the checkpoints the run already built.

    In a pause-anchored file the stops are the pause() checkpoints; in a
    plain file every checkpoint is a stop — normalized here so consumers
    never need the rule. Checkpoint 0 (the scene start) is always a stop.
    """
    pause_mode = scene._pause_anchored()
    units = scene._get_source_units() if pause_mode else None
    checkpoints = []
    for cp in scene.animation_checkpoints:
        unit = cp.get("unit_index")
        checkpoints.append({
            "index": cp["index"],
            "time": float(cp["state"].time),
            "line": cp.get("line_number") or None,
            "unit": unit,
            "chip_unit": chip_unit_for(unit, units, pause_mode),
            "name": cp.get("name"),
            "stop": bool(cp.get("stop")) or not pause_mode or cp["index"] == 0,
            "loop": bool(cp.get("loop")),
        })
    return {
        "format": FORMAT,
        "scene": type(scene).__name__,
        "fps": int(scene.camera.fps),
        "duration": float(scene.time),
        "resolution": list(scene.camera.get_pixel_shape()),
        "source": source_fingerprint(Path(scene._scene_filepath)),
        "pause_anchored": pause_mode,
        "checkpoints": checkpoints,
    }


def write_present_bundle(scene, movie_path: str | Path) -> Path:
    """Write media/<Scene>_present/ beside the rendered movie.

    Self-contained: the movie, the table (twice — json for the viewer,
    a .js for file://), and the standalone presenter page.
    """
    movie_path = Path(movie_path)
    dest = bundle_dir_for(scene)
    if dest is None:
        raise ValueError("scene has no source file path")
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copy2(movie_path, dest / BUNDLE_MOVIE)
    meta = build_meta(scene)
    meta_json = json.dumps(meta, indent=1)
    (dest / BUNDLE_META).write_text(meta_json)
    (dest / "present_meta.js").write_text(
        f"window.PRESENT_META = {meta_json};\n")
    for page in BUNDLE_PAGES:
        shutil.copy2(_STATIC_DIR / page,
                     dest / ("index.html" if page == "present.html" else page))
    return dest

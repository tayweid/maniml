"""The pausepoints table beside the rendered movie — nothing else.

``--render`` leaves what it always left, ``media/<Scene>.mp4``, plus one
file: ``media/<Scene>.pausepoints.json``. That pair is the presentation
cache. This is the t1-web model (a <video>, an array of timestamps,
stepped scrubbing both directions) with the inputs generated instead of
hand-marked: per-checkpoint timestamps come from the state each checkpoint
already stores (``SceneState.time``, the writer's own timebase), stop/loop
flags from ``pause()``, and the chip mapping from the same rule the live
rail uses (``chip_unit_for``), so the presenter's rail and the live
viewer's always agree. The no-engine fallback is the mp4 itself, in any
video player.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from maniml.scene.source_map import chip_unit_for

FORMAT = 1
PAUSEPOINTS_SUFFIX = ".pausepoints.json"


def media_dir_for(scene) -> Path | None:
    raw_source = getattr(scene, "_scene_filepath", None)
    if not raw_source:
        return None
    return Path(raw_source).parent / "media"


def movie_path_for(scene) -> Path | None:
    """Where --render puts the movie: media/<Scene>.mp4."""
    media = media_dir_for(scene)
    return media / f"{type(scene).__name__}.mp4" if media else None


def pausepoints_path_for(scene) -> Path | None:
    media = media_dir_for(scene)
    return (media / f"{type(scene).__name__}{PAUSEPOINTS_SUFFIX}"
            if media else None)


def source_fingerprint(source_path: Path) -> dict:
    """Identity of the scene file a table was baked from, for staleness."""
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


def write_pausepoints(scene) -> Path:
    """Write media/<Scene>.pausepoints.json beside the rendered movie."""
    dest = pausepoints_path_for(scene)
    if dest is None:
        raise ValueError("scene has no source file path")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(build_meta(scene), indent=1))
    return dest


# --- The standalone student bundle: `--export-present` ------------------
#
# A different artifact from the presentation cache above, for a different
# audience. The cache (mp4 + table) is what the live viewer's Present
# button plays; the bundle is a self-contained folder — index.html,
# presentation.js, present_meta.js, scene.mp4 — that a course site hosts
# so students can click through the episode with no engine anywhere.
# The table ships as a script because the page must open from file://,
# where fetch() does not exist.

PRESENT_DIR_SUFFIX = "_present"
PRESENT_PAGE_ASSETS = {"present.html": "index.html",
                       "presentation.js": "presentation.js",
                       "rail.js": "rail.js"}
STATIC_DIR = Path(__file__).parent / "static"


def present_dir_for(scene) -> Path | None:
    media = media_dir_for(scene)
    return (media / f"{type(scene).__name__}{PRESENT_DIR_SUFFIX}"
            if media else None)


def write_present_bundle(scene, movie_path: Path) -> Path:
    """Record the finished scene into media/<Scene>_present/, atomically:
    the previous bundle stays intact until a complete replacement is
    ready (same discipline as the geometry export's publish)."""
    import shutil
    import tempfile

    from maniml.web.export import _publish_export

    destination = present_dir_for(scene)
    if destination is None:
        raise ValueError("scene has no source file path")
    movie_path = Path(movie_path)
    if not movie_path.is_file():
        raise FileNotFoundError(f"no rendered movie at {movie_path}")

    destination.parent.mkdir(parents=True, exist_ok=True)
    transaction = Path(tempfile.mkdtemp(
        prefix=f".{destination.name}-export-", dir=destination.parent))
    staging = transaction / "new"
    backup = transaction / "previous"
    try:
        staging.mkdir(mode=0o755)
        for source_name, target_name in PRESENT_PAGE_ASSETS.items():
            shutil.copy(STATIC_DIR / source_name, staging / target_name)
        (staging / "present_meta.js").write_text(
            "window.MANIML_PRESENT = " + json.dumps(build_meta(scene)) + ";\n")
        shutil.copy2(movie_path, staging / "scene.mp4")
        _publish_export(staging, destination, backup)
    finally:
        shutil.rmtree(transaction, ignore_errors=True)
    return destination

"""The baked-scene web player: `maniml scene.py Scene --export`.

Runs the scene once headlessly, records the geometry stream (the same
0x03 messages the live viewer streams, delta-encoded), and writes a
self-contained static folder: the player page, both client renderers
with their shaders, and the recorded data. Drop the folder on any
static host (GitHub Pages) and anyone can scrub through the scene's
animations in the browser — no Python anywhere.

The recorder plugs into the same `_web_viewer` hook the live viewer
uses (`on_frame_rendered` after every capture, begin/end_animation
around plays), but with no window at all, so the run is unpaced and
as fast as the scene computes.
"""

from __future__ import annotations

import gzip
import json
import os
import shutil
import tempfile
from pathlib import Path

from maniml.web.geometry import GeometryCache, serialize_scene

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

PLAYER_ASSETS = ["player.html", "player.js", "gl.js", "webgpu.js"]
PLAYER_ASSET_DIRS = ["glsl", "wgsl"]


class GeometryRecorder:
    """Duck-typed for Scene's `_web_viewer` hooks; collects one
    geometry message per rendered frame, tagged with its segment (one
    segment per play()/wait() span)."""

    is_web_viewer = True

    def __init__(self, scene):
        self.scene = scene
        self.cache = GeometryCache()
        self.frames: list[tuple[bytes, int]] = []
        self.segment = -1
        self._counter = -1

    def begin_animation(self):
        self._counter += 1
        self.segment = self._counter

    def end_animation(self):
        pass  # tail frames stay with the finished segment

    def on_frame_rendered(self):
        message = serialize_scene(self.scene, self.cache)
        self.frames.append((message, self.segment))


def record_scene(scene) -> GeometryRecorder:
    """Drive the scene through all its units, recording every frame.
    Mirrors the relevant parts of Scene.run() without a window."""
    recorder = GeometryRecorder(scene)
    scene._web_viewer = recorder
    scene._reset_pacing_clocks()
    previous_error_mode = getattr(scene, "_propagate_animation_errors", False)
    scene._propagate_animation_errors = True
    try:
        scene.file_writer.begin()
        scene.setup()
        scene._create_checkpoint_zero()
        # Initial still frame (segment -1)
        scene.update_frame(dt=0, force_draw=True)
        scene._run_all_units()
        scene.stop_skipping()
        scene.file_writer.finish()
    except BaseException as error:
        try:
            scene.file_writer.abort()
        except BaseException as cleanup_error:
            error.add_note(f"Also failed while aborting export output: {cleanup_error}")
        raise
    finally:
        scene._propagate_animation_errors = previous_error_mode
    return recorder


def export_scene(scene, out_dir: str) -> str:
    """Record ``scene`` and atomically publish its player folder.

    The previous export remains untouched until a complete replacement is
    ready. Existing unrelated files are carried forward for compatibility
    with users who keep deployment metadata alongside the player assets.
    """
    destination = Path(out_dir).absolute()
    _validate_export_destination(destination)

    recorder = record_scene(scene)
    if not recorder.frames:
        raise RuntimeError("nothing recorded — scene has no content?")

    destination.parent.mkdir(parents=True, exist_ok=True)
    transaction = Path(
        tempfile.mkdtemp(
            prefix=f".{destination.name}-export-",
            dir=destination.parent,
        )
    )
    staging = transaction / "new"
    backup = transaction / "previous"
    try:
        if destination.exists():
            shutil.copytree(destination, staging, symlinks=True)
        else:
            staging.mkdir(mode=0o755)
        _write_export(scene, recorder, staging)
        _publish_export(staging, destination, backup)
    finally:
        shutil.rmtree(transaction, ignore_errors=True)
    return out_dir


def _validate_export_destination(destination: Path) -> None:
    if not destination.name:
        raise ValueError("export destination cannot be a filesystem root")
    if os.path.lexists(destination):
        if destination.is_symlink():
            raise ValueError(
                "export destination cannot be a symlink; pass its resolved "
                "directory instead"
            )
        if not destination.is_dir():
            raise NotADirectoryError(
                f"export destination is not a directory: {destination}"
            )


def _remove_staged_path(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)
    elif os.path.lexists(path):
        path.unlink()


def _write_export(scene, recorder: GeometryRecorder, staging: Path) -> None:
    for name in PLAYER_ASSETS:
        target_name = "index.html" if name == "player.html" else name
        target_path = staging / target_name
        _remove_staged_path(target_path)
        shutil.copy(Path(STATIC_DIR, name), target_path)
    for dirname in PLAYER_ASSET_DIRS:
        target_directory = staging / dirname
        _remove_staged_path(target_directory)
        shutil.copytree(Path(STATIC_DIR, dirname), target_directory)

    scene_data = staging / "scene.bin.gz"
    _remove_staged_path(scene_data)
    with gzip.open(scene_data, "wb", compresslevel=6) as file:
        for message, _ in recorder.frames:
            file.write(message)

    checkpoints = scene.animation_checkpoints
    meta = {
        "scene": type(scene).__name__,
        "fps": int(scene.camera.fps),
        "frames": [
            {"len": len(message), "segment": segment}
            for message, segment in recorder.frames
        ],
        "segments": recorder._counter + 1,
        "lines": [c.get("line_number") for c in checkpoints[1:]],
    }
    scene_metadata = staging / "scene.json"
    _remove_staged_path(scene_metadata)
    with scene_metadata.open("w", encoding="utf-8") as file:
        json.dump(meta, file)


def _publish_export(staging: Path, destination: Path, backup: Path) -> None:
    had_previous = destination.exists()
    if had_previous:
        os.replace(destination, backup)
    try:
        os.replace(staging, destination)
    except BaseException as error:
        if had_previous:
            try:
                os.replace(backup, destination)
            except BaseException as rollback_error:
                error.add_note(
                    "Also failed to restore the previous export from "
                    f"{backup}: {rollback_error}"
                )
        raise

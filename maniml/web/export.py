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

import json
import os
import shutil
import time

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
    scene.virtual_animation_start_time = 0
    scene.real_animation_start_time = time.time()
    scene.file_writer.begin()
    scene.setup()
    scene._create_checkpoint_zero()
    # Initial still frame (segment -1)
    scene.update_frame(dt=0, force_draw=True)
    scene._run_all_units()
    scene.stop_skipping()
    scene.file_writer.finish()
    return recorder


def export_scene(scene, out_dir: str) -> str:
    """Record `scene` and write the self-contained player folder."""
    recorder = record_scene(scene)
    if not recorder.frames:
        raise RuntimeError("nothing recorded — scene has no content?")

    os.makedirs(out_dir, exist_ok=True)
    for name in PLAYER_ASSETS:
        target = "index.html" if name == "player.html" else name
        shutil.copy(os.path.join(STATIC_DIR, name),
                    os.path.join(out_dir, target))
    for dirname in PLAYER_ASSET_DIRS:
        target = os.path.join(out_dir, dirname)
        shutil.rmtree(target, ignore_errors=True)
        shutil.copytree(os.path.join(STATIC_DIR, dirname), target)

    import gzip
    with gzip.open(os.path.join(out_dir, "scene.bin.gz"), "wb",
                   compresslevel=6) as f:
        for message, _ in recorder.frames:
            f.write(message)

    checkpoints = scene.animation_checkpoints
    meta = {
        "scene": type(scene).__name__,
        "fps": int(scene.camera.fps),
        "frames": [{"len": len(message), "segment": segment}
                   for message, segment in recorder.frames],
        "segments": recorder._counter + 1,
        "lines": [c.get("line_number") for c in checkpoints[1:]],
    }
    with open(os.path.join(out_dir, "scene.json"), "w") as f:
        json.dump(meta, f)
    return out_dir

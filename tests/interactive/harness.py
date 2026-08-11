"""Windowed test harness: drives a real OpenGL window programmatically.

Opens the scene like __main__.py does, then replaces interact() with a
scripted sequence that calls the actual key/mouse handlers and captures
frames from the framebuffer. Requires a display and GPU — these tests
are run explicitly (see tests/test_interactive.py), not as part of the
headless suite.
"""
from __future__ import annotations

import os
import time

import numpy as np

from manim.__main__ import load_scene_module
from manim.rendering.window import Window
from manim.camera.camera_frame import CameraFrame
from pyglet.window import key as KEY


class WindowDriver:
    def __init__(self, scene_file: str, scene_name: str, present: bool = False):
        module = load_scene_module(scene_file)
        self.window = Window()
        self.scene = getattr(module, scene_name)(window=self.window)
        self.scene._scene_filepath = os.path.abspath(scene_file)
        self.scene._present_mode = present
        self.scene_file = os.path.abspath(scene_file)
        self.failures: list[str] = []

    # Lifecycle

    def run(self, script) -> list[str]:
        """Run the scene; `script(self)` executes inside interact().
        Returns the list of failed check labels."""
        def interact():
            # Mirror the real interact() setup
            if self.scene.auto_reload_enabled:
                self.scene._setup_file_watcher()
            self.scene.skip_animations = False
            try:
                script(self)
            finally:
                self.scene.window.close()
        self.scene.interact = interact
        self.scene.run()
        return self.failures

    # Event injection (calls the real handlers)

    def pump(self, seconds: float) -> None:
        """The same frame loop interact() runs, for a bounded time."""
        end = time.time() + seconds
        scene = self.scene
        while time.time() < end and not scene.is_window_closing():
            if scene._file_changed_flag:
                scene._file_changed_flag = False
                scene._handle_file_change()
            scene.update_frame(1 / scene.camera.fps)

    def key(self, symbol: int, pump: float = 0.25) -> None:
        self.scene.on_key_press(symbol, 0)
        self.pump(pump)

    def right(self):
        self.key(KEY.RIGHT)

    def left(self):
        self.key(KEY.LEFT)

    def up(self):
        self.key(KEY.UP)

    def down(self):
        self.key(KEY.DOWN)

    def mouse_move(self, point) -> None:
        self.scene.on_mouse_motion(np.asarray(point, dtype=float), np.zeros(3))
        self.pump(0.2)

    def mouse_press(self, point) -> None:
        self.scene.on_mouse_press(np.asarray(point, dtype=float), 0, 0)
        self.pump(0.2)

    def bottom_edge_point(self, x: float = 0.0):
        frame = self.scene.camera.frame
        y = frame.get_bottom()[1] + 0.045 * frame.get_height()
        return np.array([x, y, 0.0])

    # Inspection

    def content_mobjects(self):
        return [
            m for m in self.scene.mobjects
            if not isinstance(m, CameraFrame)
            and m is not self.scene._timeline_group
        ]

    def edit_scene_file(self, old: str, new: str) -> None:
        """Edit the scene file on disk and wait for the watcher to flag it."""
        with open(self.scene_file) as f:
            source = f.read()
        assert old in source, f"edit target {old!r} not found in scene file"
        with open(self.scene_file, "w") as f:
            f.write(source.replace(old, new))
        deadline = time.time() + 8
        while time.time() < deadline and not self.scene._file_changed_flag:
            self.scene.update_frame(1 / self.scene.camera.fps)
        self.check("watcher flagged the edit", self.scene._file_changed_flag)
        self.pump(2.0)  # lets the pump loop replay the edited unit

    def shot(self, path: str) -> None:
        self.scene.get_image().save(path)

    # Assertions

    def check(self, label: str, condition: bool) -> None:
        print(f"[harness] {'PASS' if condition else 'FAIL'}: {label}")
        if not condition:
            self.failures.append(label)

    def check_index(self, label: str, expected: int) -> None:
        actual = self.scene.current_animation_index
        self.check(f"{label} (index {actual}, expected {expected})",
                   actual == expected)


def finish(failures: list[str]) -> int:
    if failures:
        print(f"[harness] FAILED: {len(failures)} check(s): {failures}")
        return 1
    print("[harness] all checks passed")
    return 0

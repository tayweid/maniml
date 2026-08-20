"""Browser-based viewer: a drop-in stand-in for the pyglet Window.

WebViewer duck-types the small interface Scene expects from its window
(`init_for_scene`, `destroy`, `is_closing`, `has_undrawn_event`,
`is_key_pressed`, `focus`, `_window.dispatch_events`), so the
InteractionMixin handlers and the checkpoint system run unmodified.
Rendering stays native: the camera runs on its standalone (windowless)
GL context — the same path --render uses — and the viewer reads the
finished FBO back and streams it to the browser.

Streaming policy: JPEG frames while an animation plays or input events
are arriving, then a single lossless PNG once things go quiet. Nothing
is read back or sent while idle with no clients.

Event flow: the browser sends key/pointer events over the WebSocket as
JSON; `_dispatch_events` (called from `on_frame_rendered`, i.e. from
inside the scene's own update loop, mirroring where pyglet dispatches)
maps them to pyglet key symbols / button masks and calls the scene's
existing on_* handlers. Pointer coordinates arrive normalized to the
frame ([0,1], y-up), so no window-size bookkeeping is needed.
"""

from __future__ import annotations

import io
import os
import subprocess
import sys
import threading
import time
import webbrowser
from collections import deque
from pathlib import Path

import numpy as np
from PIL import Image

from maniml.constants import FRAME_SHAPE
from maniml.event_constants import MouseButtons as PygletMouseButtons
from maniml.event_constants import WindowKeys as PygletWindowKeys
from maniml.logger import log
from maniml.web.library import find_scene_classes
from maniml.web.server import WebServer

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Optional
    from maniml.scene.scene import Scene

JS_KEY_TO_PYGLET = {
    "ArrowLeft": PygletWindowKeys.LEFT,
    "ArrowRight": PygletWindowKeys.RIGHT,
    "ArrowUp": PygletWindowKeys.UP,
    "ArrowDown": PygletWindowKeys.DOWN,
    "Enter": PygletWindowKeys.ENTER,
    "Escape": PygletWindowKeys.ESCAPE,
    "Backspace": PygletWindowKeys.BACKSPACE,
    "Tab": PygletWindowKeys.TAB,
    " ": PygletWindowKeys.SPACE,
}
JS_BUTTON_TO_PYGLET = {
    0: PygletMouseButtons.LEFT,
    1: PygletMouseButtons.MIDDLE,
    2: PygletMouseButtons.RIGHT,
}

# Scenes are flat colour with hard edges, which is the worst case for the
# 4:2:0 chroma subsampling a JPEG encoder reaches for by default: colour is
# stored at half resolution, so the boundary between two saturated blocks
# smears across several pixels and an animation reads as colours melting into
# each other rather than switching. Measured on a 1920x1080 frame of colour
# blocks, worst-case channel error against the source: 147 at 4:2:0, 28 at
# 4:4:4/90. The cost is 49 KB/frame against 84, i.e. 1.5 MB/s against 2.5 at
# the 30/s cap — over loopback, to a client on the same machine.
JPEG_QUALITY = 90
JPEG_SUBSAMPLING = 0  # 4:4:4, full-resolution colour
MIN_SEND_INTERVAL = 1 / 30  # global throttle, also caps fast-forward previews
PNG_AFTER_QUIET = 0.4  # seconds of quiet before the crisp idle frame


class OutputTap:
    """Mirror a text stream into a buffer without swallowing it.

    Everything a scene prints — its own output, tracebacks from a failed
    unit, rich's log records — goes to stdout or stderr, and in app mode that
    is a pipe into the app process where nobody ever sees it. Teeing here
    keeps the real stream working (the app still reads the launch line from
    it) while giving the viewer something to show.

    Writes arrive from the render thread and the file-watcher thread, so the
    buffer is guarded; partial writes are held until their newline, because
    `print` emits its text and its terminator separately.
    """

    def __init__(self, stream, name: str, sink: "LogBuffer"):
        self._stream = stream
        self._name = name
        self._sink = sink
        self._partial = ""

    def write(self, text: str) -> int:
        written = self._stream.write(text)
        try:
            self._partial += text
            while "\n" in self._partial:
                line, self._partial = self._partial.split("\n", 1)
                self._sink.add(self._name, line)
        except Exception:
            self._partial = ""  # never let logging break printing
        return written

    def flush(self) -> None:
        self._stream.flush()

    def isatty(self) -> bool:
        return False

    def __getattr__(self, attribute):
        return getattr(self._stream, attribute)


class LogBuffer:
    """The scene's recent output, and whatever has not been sent yet."""

    def __init__(self, limit: int = 500):
        self._lock = threading.Lock()
        self._history: deque[tuple[str, str]] = deque(maxlen=limit)
        self._pending: list[tuple[str, str]] = []

    def add(self, stream: str, text: str) -> None:
        with self._lock:
            self._history.append((stream, text))
            self._pending.append((stream, text))

    def take_pending(self) -> list[tuple[str, str]]:
        with self._lock:
            pending, self._pending = self._pending, []
            return pending

    def history(self) -> list[tuple[str, str]]:
        with self._lock:
            self._pending = []
            return list(self._history)


class WebViewer:
    is_web_viewer = True

    def __init__(self, open_browser: bool = True):
        self.scene: Optional[Scene] = None
        self.server = WebServer(capabilities=("export", "restart"))
        self.pressed_keys: set[int] = set()
        self._has_undrawn_event = True
        self._dirty = False  # input arrived since the last sent frame
        self._animating = False
        self._needs_refresh = True  # a client wants a full PNG + state
        self._dispatching = False
        self._last_send_time = 0.0
        self._last_send_lossy = False
        self._last_state = None
        self._last_move = None
        # Set when a client picks another scene from the same file. The run
        # loop in __main__ reads it after Scene.run() returns and builds the
        # next scene against this same viewer, so the server and the open
        # browser tab both survive.
        self._pending_scene: str | None = None
        self._scene_names_cache: tuple[tuple, list[str]] | None = None
        self._geometry_mode = False  # Stage 2: stream geometry alongside pixels
        self._pixel_mode = True  # off in solo-GL: geometry is the only stream
        self._export_lock = threading.Lock()
        self._export_process: subprocess.Popen | None = None
        from maniml.web.geometry import GeometryCache
        self._geometry_cache = GeometryCache()  # delta-encoding state
        self.logs = LogBuffer()
        sys.stdout = OutputTap(sys.stdout, "out", self.logs)
        sys.stderr = OutputTap(sys.stderr, "err", self.logs)
        log.info(f"maniml web viewer: {self.server.url}")
        print(f"maniml web viewer: {self.server.url}")
        if open_browser:
            webbrowser.open(self.server.url)

    # -- The Window interface Scene expects --

    def init_for_scene(self, scene: Scene):
        self.scene = scene
        self.pressed_keys.clear()
        self._has_undrawn_event = True
        self._needs_refresh = True

    def destroy(self):
        # A scene switch tears down the scene, not the session: keep the
        # servers up so the next scene reuses this viewer and the client
        # never has to reconnect or re-authenticate.
        if self._pending_scene is not None:
            return
        self.server.stop()

    @property
    def is_closing(self) -> bool:
        return self._pending_scene is not None

    def take_pending_scene(self) -> str | None:
        """Consume a requested scene switch, if any."""
        pending, self._pending_scene = self._pending_scene, None
        return pending

    def scene_names(self) -> list[str]:
        """Scene classes in the current file, by AST — no import.

        Cached on (path, mtime): this feeds the per-frame state comparison in
        on_frame_rendered, so it must not re-read and re-parse the file on
        every rendered frame. The mtime key keeps it correct across edits,
        which the file watcher applies live.
        """
        source = getattr(self.scene, "_scene_filepath", None)
        if not source:
            return []
        try:
            key = (source, os.stat(source).st_mtime_ns)
        except OSError:
            return []
        if self._scene_names_cache and self._scene_names_cache[0] == key:
            return self._scene_names_cache[1]
        names = find_scene_classes(source)
        self._scene_names_cache = (key, names)
        return names

    def has_clients(self) -> bool:
        return self.server.has_clients()

    def has_undrawn_event(self) -> bool:
        return self._has_undrawn_event

    def is_key_pressed(self, symbol: int) -> bool:
        return symbol in self.pressed_keys

    def focus(self):
        pass

    @property
    def _window(self):
        # scene.update_frame pumps `window._window.dispatch_events()`
        return self

    # -- Hooks called by Scene --

    def begin_animation(self):
        self._animating = True
        index = self.scene.current_animation_index
        # A reverse morph has already landed the index on its destination,
        # so both directions light the same stretch; only which end it grows
        # from differs.
        self._broadcast_move(
            index, index + 1, bool(getattr(self.scene, "_reversing", False)),
            getattr(self.scene, "_playing_unit", None))

    def end_animation(self):
        self._animating = False
        self._broadcast_move(None, None, False, None)

    def on_frame_rendered(self):
        """Called after every camera.capture(): pump input, stream output."""
        if not self._dispatching:
            self._dispatching = True
            try:
                self.dispatch_events()
            finally:
                self._dispatching = False

        if not self.server.has_clients():
            return
        self._broadcast_logs()
        now = time.monotonic()
        # A checkpoint-state change means the picture changed without any
        # input event (present-mode prep, watcher replays, programmatic
        # jumps) — those must trigger a send on their own
        state_changed = self._current_state() != self._last_state
        # Updater-driven mobjects animate in the idle loop, outside
        # play()/wait(); stream while any are live
        animating = self._animating or any(
            m.has_updaters() for m in self.scene.mobjects)
        kind = None
        if self._needs_refresh or state_changed:
            kind = "png"
        elif animating or self._dirty:
            if now - self._last_send_time >= MIN_SEND_INTERVAL:
                kind = "jpeg"
        elif self._last_send_lossy and now - self._last_send_time >= PNG_AFTER_QUIET:
            kind = "png"
        if kind is None:
            return

        if self._pixel_mode:
            camera = self.scene.camera
            raw = camera.get_raw_fbo_data()
            w, h = camera.draw_fbo.size
            channels = len(raw) // (w * h)
            image = Image.frombytes(
                "RGBA" if channels == 4 else "RGB", (w, h), raw)
            buf = io.BytesIO()
            if kind == "jpeg":
                image.convert("RGB").save(
                    buf, "JPEG", quality=JPEG_QUALITY,
                    subsampling=JPEG_SUBSAMPLING)
                self.server.broadcast(b"\x01" + buf.getvalue(), droppable=True)
            else:
                image.convert("RGB").save(buf, "PNG")
                self.server.broadcast(b"\x02" + buf.getvalue())
        self._last_send_time = now
        self._last_send_lossy = (kind == "jpeg")
        self._dirty = False
        self._needs_refresh = False
        self._has_undrawn_event = False
        if self._geometry_mode:
            # Mirror every pixel frame with a geometry payload so the
            # client's GL panel animates in lockstep with the stream.
            # Not droppable: it would always collide with the pixel send
            # queued a moment earlier, and the payload is small anyway.
            from maniml.web.geometry import serialize_scene
            self.server.broadcast(
                serialize_scene(self.scene, self._geometry_cache))
        self._broadcast_state()

    def _broadcast_logs(self, replace: bool = False) -> None:
        """Send whatever the scene has printed since the last frame.

        Deliberately ahead of the "has anything changed" test below: a scene
        can sit perfectly still and still be saying something.
        """
        lines = self.logs.history() if replace else self.logs.take_pending()
        if not lines and not replace:
            return
        self.server.broadcast_json({
            "type": "log",
            "replace": replace,
            "lines": [{"stream": stream, "text": text} for stream, text in lines],
        })

    # -- Inbound events --

    def dispatch_events(self):
        for event in self.server.pop_events():
            try:
                self._handle_event(event)
            except Exception as e:
                log.error(f"web viewer event failed: {event.get('type')}: {e}")

    def _handle_event(self, event: dict):
        kind = event.get("type")
        if kind == "_connect":
            self._needs_refresh = True
            self._last_state = None
            self._geometry_cache.reset()  # new client holds no batches
            # Hand the new client the whole backlog: output from before it
            # connected is usually the output that explains something.
            self._broadcast_logs(replace=True)
            return

        self._dirty = True
        self._has_undrawn_event = True
        scene = self.scene
        if scene is None:
            return

        if kind == "key":
            symbol = self._map_key(event.get("key", ""))
            if symbol is None:
                return
            mods = self._map_mods(event)
            if event.get("action") == "down":
                self.pressed_keys.add(symbol)
                scene.on_key_press(symbol, mods)
            else:
                self.pressed_keys.discard(symbol)
                scene.on_key_release(symbol, mods)

        elif kind == "pointer":
            action = event.get("action")
            point = self._norm_to_scene(event.get("x", 0.5), event.get("y", 0.5))
            mods = self._map_mods(event)
            if action == "move":
                d_point = self._norm_to_scene(
                    event.get("dx", 0), event.get("dy", 0), relative=True)
                buttons = event.get("buttons", 0)
                if buttons:
                    scene.on_mouse_drag(
                        point, d_point, self._map_buttons_mask(buttons), mods)
                else:
                    scene.on_mouse_motion(point, d_point)
            elif action == "down":
                button = JS_BUTTON_TO_PYGLET.get(event.get("button", 0))
                if button is not None:
                    scene.on_mouse_press(point, button, mods)
            elif action == "up":
                button = JS_BUTTON_TO_PYGLET.get(event.get("button", 0))
                if button is not None:
                    scene.on_mouse_release(point, button, mods)
            elif action == "wheel":
                x_off = event.get("wx", 0.0)
                y_off = event.get("wy", 0.0)
                offset = self._norm_to_scene(
                    x_off / 1000, y_off / 1000, relative=True)
                scene.on_mouse_scroll(point, offset, x_off, y_off)

        elif kind == "chip":
            self._jump_to_checkpoint(int(event.get("index", 0)))

        elif kind == "chip_future":
            self._advance_to_unit(int(event.get("unit", 0)))

        elif kind == "restart":
            if not getattr(scene, "_processing_key", False):
                scene._processing_key = True
                try:
                    scene._restart_from_source()
                finally:
                    scene._processing_key = False

        elif kind == "switch_scene":
            # Only a scene actually declared in this file: the name selects a
            # class to instantiate, so it must never come straight from the
            # wire.
            requested = event.get("scene")
            if isinstance(requested, str) and requested in self.scene_names():
                if requested != type(scene).__name__:
                    self._pending_scene = requested
                    scene.quit_interaction = True
            self._dirty = False

        elif kind == "export":
            export_format = event.get("format")
            if export_format in {"video", "web"}:
                self._start_export(export_format)
            self._dirty = False

        elif kind == "geometry_request":
            # One-shot snapshot (sent on toggle-on, before any frame flows)
            from maniml.web.geometry import serialize_scene
            self.server.broadcast(
                serialize_scene(self.scene, self._geometry_cache))
            self._dirty = False  # the request itself needs no pixel frame

        elif kind == "geometry_reset":
            # A client hit a cache miss (e.g. evicted a batch we still
            # reference): resend everything on the next payload
            self._geometry_cache.reset()
            self._dirty = True

        elif kind == "mode":
            # Stage-2 streaming opt-in: while on, every pixel frame is
            # mirrored with a geometry payload; with pixels off (solo-GL)
            # the geometry stream is the only one and the per-frame
            # readback+encode is skipped entirely. Reset deltas on enable
            # so a rejoining toggle always starts from a full payload.
            self._geometry_mode = bool(event.get("geometry"))
            self._pixel_mode = bool(event.get("pixels", True))
            if self._geometry_mode:
                self._geometry_cache.reset()
            # Leaving solo: the canvas needs a fresh pixel frame
            self._needs_refresh = self._pixel_mode
            self._dirty = False

    def _jump_to_checkpoint(self, index: int):
        """Timeline-chip click: same behavior as UP/DOWN checkpoint jumps."""
        scene = self.scene
        if scene is None or getattr(scene, "_processing_key", False):
            return
        if not (0 <= index < len(scene.animation_checkpoints)):
            return
        if index == scene.current_animation_index:
            return
        scene._restore_checkpoint_for_display(index)
        if scene._present_mode and scene._timeline_group is not None:
            scene._show_timeline()
        scene.update_frame(dt=0, force_draw=True)

    def _advance_to_unit(self, unit_index: int):
        """Future-chip click: fast-forward to that unit, playing it at
        real speed — the same replay path the file watcher uses."""
        scene = self.scene
        if scene is None or getattr(scene, "_processing_key", False):
            return
        scene._processing_key = True
        try:
            scene._replay_to_unit(unit_index)
        finally:
            scene._processing_key = False

    def _start_export(self, export_format: str) -> None:
        """Render a copy of the current scene in a separate process.

        The browser chooses only a fixed export format.  The source path and
        scene name always come from the already-running scene, and ``shell``
        is deliberately not involved.  Keeping export out of the live scene
        preserves its checkpoints and interaction state.
        """
        scene = self.scene
        raw_source = getattr(scene, "_scene_filepath", None)
        source = Path(raw_source) if raw_source else Path()
        scene_name = type(scene).__name__ if scene is not None else ""
        if not source.is_file() or not scene_name.isidentifier():
            self.server.broadcast_json(
                {
                    "type": "export_status",
                    "format": export_format,
                    "status": "failed",
                }
            )
            return

        with self._export_lock:
            if self._export_process is not None and self._export_process.poll() is None:
                self.server.broadcast_json(
                    {
                        "type": "export_status",
                        "format": export_format,
                        "status": "busy",
                    }
                )
                return
            mode = "--render" if export_format == "video" else "--export"
            try:
                process = subprocess.Popen(
                    [sys.executable, "-m", "maniml", str(source), scene_name, mode],
                    cwd=str(source.parent),
                    env=os.environ.copy(),
                )
            except OSError:
                self.server.broadcast_json(
                    {
                        "type": "export_status",
                        "format": export_format,
                        "status": "failed",
                    }
                )
                return
            self._export_process = process

        self.server.broadcast_json(
            {
                "type": "export_status",
                "format": export_format,
                "status": "running",
            }
        )
        threading.Thread(
            target=self._finish_export,
            args=(process, export_format),
            name=f"maniml-{export_format}-export",
            daemon=True,
        ).start()

    def _finish_export(
        self,
        process: subprocess.Popen,
        export_format: str,
    ) -> None:
        returncode = process.wait()
        with self._export_lock:
            if self._export_process is process:
                self._export_process = None
        status = "complete" if returncode == 0 else "failed"
        self.server.broadcast_json(
            {
                "type": "export_status",
                "format": export_format,
                "status": status,
            }
        )
        if returncode:
            log.error(f"maniml {export_format} export exited with {returncode}")

    # -- Mapping helpers --

    @staticmethod
    def _map_key(js_key: str) -> Optional[int]:
        if js_key in JS_KEY_TO_PYGLET:
            return JS_KEY_TO_PYGLET[js_key]
        if len(js_key) == 1:
            return ord(js_key.lower())
        return None

    @staticmethod
    def _map_mods(event: dict) -> int:
        mods = 0
        if event.get("shift"):
            mods |= PygletWindowKeys.MOD_SHIFT
        if event.get("ctrl"):
            mods |= PygletWindowKeys.MOD_CTRL
        if event.get("alt"):
            mods |= PygletWindowKeys.MOD_ALT
        if event.get("meta"):
            mods |= PygletWindowKeys.MOD_COMMAND
        return mods

    @staticmethod
    def _map_buttons_mask(js_buttons: int) -> int:
        # JS MouseEvent.buttons: 1=left, 2=right, 4=middle
        mask = 0
        if js_buttons & 1:
            mask |= PygletMouseButtons.LEFT
        if js_buttons & 2:
            mask |= PygletMouseButtons.RIGHT
        if js_buttons & 4:
            mask |= PygletMouseButtons.MIDDLE
        return mask

    def _norm_to_scene(self, nx: float, ny: float, relative: bool = False):
        """Client coords are normalized to the frame image, [0,1], y-up
        (same math as Window.pixel_coords_to_space_coords with the pixel
        shape normalized out)."""
        coords = np.zeros(3)
        coords[:2] = np.array(FRAME_SHAPE) * np.array([nx, ny])
        if not relative:
            coords[:2] -= 0.5 * np.array(FRAME_SHAPE)
        return self.scene.frame.from_fixed_frame_point(coords, relative)

    # -- Outbound state --

    def _current_state(self) -> dict:
        scene = self.scene
        checkpoints = scene.animation_checkpoints
        raw_source = getattr(scene, "_scene_filepath", None)
        return {
            "type": "state",
            "scene": type(scene).__name__,
            "scenes": self.scene_names(),
            "file": Path(raw_source).name if raw_source else "scene.py",
            "current": scene.current_animation_index,
            "count": len(checkpoints),
            "lines": [c.get("line_number") for c in checkpoints],
            # Which source statement each checkpoint came from, so the rail
            # can keep a loop's checkpoints collapsed into the one chip that
            # stood for them before it ran.
            "units": [c.get("unit_index") for c in checkpoints],
            "future": self._future_units(),
        }

    def _future_units(self) -> list[dict]:
        """Play-units not yet checkpointed, so the timeline can show the
        whole scene up front. One chip per unit — a loop's repeated plays
        only become individual chips once the unit runs, which is what
        ``many`` warns about: the chip stands for an unknown number of
        pausepoints rather than exactly one."""
        scene = self.scene
        units = scene._get_source_units()  # cached by (path, mtime)
        if not units:
            return []
        last_unit = -1
        for checkpoint in scene.animation_checkpoints:
            unit_index = checkpoint.get("unit_index")
            if unit_index is not None:
                last_unit = max(last_unit, unit_index)
        return [
            {"unit": u.index, "line": u.start_line, "many": u.indeterminate}
            for u in units if u.has_play and u.index > last_unit
        ]

    def _broadcast_move(self, frm, to, back: bool, unit) -> None:
        """Say which stretch of the timeline an animation is crossing.

        Its own message rather than a field on the state, for two reasons: a
        state change forces a lossless PNG (see ``on_frame_rendered``), and
        one per play would be a full-frame send at the worst moment; and this
        must reach the rail when the play *starts*, not on whatever frame the
        streaming policy sends next.

        ``unit`` is the source statement being played, which the destination
        checkpoint cannot supply because it does not exist yet: it is what
        tells the rail whether this play stays inside a collapsed stack or
        crosses to the next chip.

        Nothing is said about progress through the animation. The animation
        itself is on screen at full size, and any claim would have to hold up
        through reverse morphs and watcher replays as well as forward plays.
        """
        if not self.server.has_clients():
            return
        if getattr(self.scene, "skip_animations", False):
            # Present-mode prep and watcher replays fast-forward whole runs
            # of units; a lit rail flickering through them says nothing.
            return
        move = (frm, to, back, unit)
        if move == self._last_move:
            return
        self._last_move = move
        self.server.broadcast_json(
            {"type": "move", "from": frm, "to": to, "back": back,
             "unit": unit})

    def _broadcast_state(self):
        state = self._current_state()
        if state != self._last_state:
            self._last_state = state
            self.server.broadcast_json(state)

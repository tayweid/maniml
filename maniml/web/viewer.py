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
import time
import webbrowser

import numpy as np
from PIL import Image
from pyglet.window import key as PygletWindowKeys
from pyglet.window import mouse as PygletMouseButtons

from maniml.constants import FRAME_SHAPE
from maniml.logger import log
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

JPEG_QUALITY = 80
MIN_SEND_INTERVAL = 1 / 30  # global throttle, also caps fast-forward previews
PNG_AFTER_QUIET = 0.4  # seconds of quiet before the crisp idle frame


class WebViewer:
    is_web_viewer = True
    is_closing = False

    def __init__(self, open_browser: bool = True):
        self.scene: Optional[Scene] = None
        self.server = WebServer()
        self.pressed_keys: set[int] = set()
        self._has_undrawn_event = True
        self._dirty = False  # input arrived since the last sent frame
        self._animating = False
        self._needs_refresh = True  # a client wants a full PNG + state
        self._dispatching = False
        self._last_send_time = 0.0
        self._last_send_lossy = False
        self._last_state = None
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
        self.server.stop()

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

    def end_animation(self):
        self._animating = False

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

        camera = self.scene.camera
        raw = camera.get_raw_fbo_data()
        w, h = camera.draw_fbo.size
        channels = len(raw) // (w * h)
        image = Image.frombytes("RGBA" if channels == 4 else "RGB", (w, h), raw)
        buf = io.BytesIO()
        if kind == "jpeg":
            image.convert("RGB").save(buf, "JPEG", quality=JPEG_QUALITY)
            self.server.broadcast(b"\x01" + buf.getvalue(), droppable=True)
        else:
            image.convert("RGB").save(buf, "PNG")
            self.server.broadcast(b"\x02" + buf.getvalue())
        self._last_send_time = now
        self._last_send_lossy = (kind == "jpeg")
        self._dirty = False
        self._needs_refresh = False
        self._has_undrawn_event = False
        self._broadcast_state()

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
        return {
            "type": "state",
            "current": scene.current_animation_index,
            "count": len(checkpoints),
            "lines": [c.get("line_number") for c in checkpoints],
            "future": self._future_units(),
        }

    def _future_units(self) -> list[dict]:
        """Play-units not yet checkpointed, so the timeline can show the
        whole scene up front. One chip per unit — a loop's repeated plays
        only become individual chips once the unit runs."""
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
            {"unit": u.index, "line": u.start_line}
            for u in units if u.has_play and u.index > last_unit
        ]

    def _broadcast_state(self):
        state = self._current_state()
        if state != self._last_state:
            self._last_state = state
            self.server.broadcast_json(state)

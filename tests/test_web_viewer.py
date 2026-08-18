"""End-to-end test of the browser viewer (--web).

Launches a real scene subprocess in web mode, then acts as the browser:
fetches the client page over HTTP, connects to the WebSocket, and
asserts the full loop works — initial PNG frame + state on connect,
JPEG streaming after a RIGHT-arrow keypress, checkpoint state advancing,
and click-to-inspect printing the variable name to the terminal.

Headless (offscreen GL only), so it runs un-gated like the other
integration suites.
"""

import json
import os
import subprocess
import sys
import threading
import time
import unittest
import urllib.request
from urllib.parse import urlsplit

from websockets.sync.client import connect as ws_connect


SCENE_SOURCE = """
from manim import *

class WebDemo(Scene):
    def construct(self):
        label = Text("web viewer").move_to(UP * 2)
        self.play(FadeIn(label))

        dot = Dot().move_to(ORIGIN)
        self.play(dot.animate.shift(RIGHT * 2))

        self.play(dot.animate.shift(LEFT * 4))
"""

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STARTUP_TIMEOUT = 25
MESSAGE_TIMEOUT = 10


class _ViewerHarness:
    """Launch one scene subprocess and act as the browser against it.

    Deliberately not a TestCase: suites mix this in, so no suite inherits
    another's tests. Subclasses vary the fixture through the three class
    attributes below.
    """

    SOURCE = SCENE_SOURCE
    SCENE = "WebDemo"
    FILENAME = "web_scene.py"

    @classmethod
    def setUpClass(cls):
        import tempfile
        cls.tmpdir = tempfile.TemporaryDirectory()
        scene_path = os.path.join(cls.tmpdir.name, cls.FILENAME)
        with open(scene_path, "w") as f:
            f.write(cls.SOURCE)

        cls.proc = subprocess.Popen(
            [sys.executable, "-m", "maniml", scene_path, cls.SCENE,
             "--web", "--no-browser"],
            cwd=cls.tmpdir.name,
            env={**os.environ, "PYTHONPATH": REPO_ROOT,
                 "PYTHONUNBUFFERED": "1"},
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        )
        cls.stdout_lines = []
        cls._reader = threading.Thread(target=cls._read_stdout, daemon=True)
        cls._reader.start()

        def find_url():
            from maniml.web.app import parse_viewer_launch_line
            for line in cls.stdout_lines:
                url = parse_viewer_launch_line(line)
                if url:
                    return url
        cls.capability_url = cls._wait_for(
            find_url, STARTUP_TIMEOUT, "server URL in stdout")
        parsed = urlsplit(cls.capability_url)
        cls.url = f"{parsed.scheme}://{parsed.netloc}/"
        cls.token = parsed.fragment.removeprefix("token=")
        cls.origin = f"http://localhost:{parsed.port}"
        # Page and socket are the same origin: one port, nothing to derive.
        cls.ws_url = f"ws://localhost:{parsed.port}/"

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        try:
            cls.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            cls.proc.kill()
        cls.tmpdir.cleanup()

    @classmethod
    def _read_stdout(cls):
        for line in cls.proc.stdout:
            cls.stdout_lines.append(line)

    @classmethod
    def _wait_for(cls, get, timeout, what):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if cls.proc.poll() is not None:
                raise AssertionError(
                    "scene process died:\n" + "".join(cls.stdout_lines))
            value = get()
            if value:
                return value
            time.sleep(0.05)
        raise AssertionError("timed out waiting for %s:\n%s" % (
            what, "".join(cls.stdout_lines)))

    @staticmethod
    def _collect(ws, seconds):
        """Gather (binary_frames, states) arriving within `seconds`."""
        frames, states = [], []
        deadline = time.time() + seconds
        while time.time() < deadline:
            try:
                msg = ws.recv(timeout=max(0.05, deadline - time.time()))
            except TimeoutError:
                break
            if isinstance(msg, bytes):
                frames.append(msg)
            else:
                states.append(json.loads(msg))
        return frames, states

    def _connect(self):
        ws = ws_connect(
            self.ws_url, max_size=2**24, origin=self.origin)
        ws.send(json.dumps({"type": "authenticate", "token": self.token}))
        response = json.loads(ws.recv(timeout=5))
        self.assertEqual(response["type"], "authenticated")
        self.assertEqual(set(response["capabilities"]), {"export", "restart"})
        return ws


class WebViewerE2E(_ViewerHarness, unittest.TestCase):
    def test_full_loop(self):
        # The client page is served
        page = urllib.request.urlopen(self.url, timeout=5).read().decode()
        self.assertIn("<canvas", page)

        with self._connect() as ws:
            # On connect: a lossless PNG snapshot plus checkpoint state
            frames, states = self._collect(ws, 3)
            self.assertTrue(frames, "no frame after connect")
            self.assertEqual(frames[0][0], 0x02, "first frame should be PNG")
            self.assertTrue(frames[0][1:9].startswith(b"\x89PNG"), "PNG magic")
            self.assertTrue(states, "no state message after connect")
            start_state = states[-1]
            self.assertGreaterEqual(start_state["count"], 2)
            self.assertEqual(start_state["file"], "web_scene.py")

            # RIGHT arrow: the next unit runs and streams JPEG frames
            ws.send(json.dumps(
                {"type": "key", "action": "down", "key": "ArrowRight"}))
            frames, states = self._collect(ws, 4)
            jpegs = [f for f in frames if f[0] == 0x01]
            self.assertGreater(len(jpegs), 3, "expected streamed JPEG frames")
            self.assertTrue(jpegs[0][1:3] == b"\xff\xd8", "JPEG magic")
            # ...capped by a crisp PNG once the animation settles
            self.assertEqual(frames[-1][0], 0x02, "quiet-time PNG follow-up")
            self.assertTrue(states, "no state update after RIGHT")
            self.assertEqual(
                states[-1]["current"], start_state["current"] + 1)

            # Click on the label: inspect prints its variable name
            ws.send(json.dumps({"type": "pointer", "action": "down",
                                "button": 0, "x": 0.5, "y": 0.75}))
            ws.send(json.dumps({"type": "pointer", "action": "up",
                                "button": 0, "x": 0.5, "y": 0.75}))
            self._wait_for(
                lambda: any("label" in l for l in self.stdout_lines),
                MESSAGE_TIMEOUT, "click-to-inspect output")

            # UP arrow: jump back; state should retreat
            ws.send(json.dumps(
                {"type": "key", "action": "down", "key": "ArrowUp"}))
            frames, states = self._collect(ws, 3)
            self.assertTrue(states, "no state update after UP")
            self.assertEqual(
                states[-1]["current"], start_state["current"])

    def test_geometry_snapshot(self):
        from maniml.web.geometry import parse_geometry_message
        with self._connect() as ws:
            self._collect(ws, 2)  # drain connect frame/state
            ws.send(json.dumps({"type": "geometry_request"}))
            deadline = time.time() + 8
            message = None
            while time.time() < deadline and message is None:
                try:
                    msg = ws.recv(timeout=1)
                except TimeoutError:
                    continue
                if isinstance(msg, bytes) and msg[0] == 0x03:
                    message = msg
            self.assertIsNotNone(message, "no geometry message")
            header, vertex_bytes = parse_geometry_message(message)
            self.assertGreater(len(header["batches"]), 0)
            self.assertEqual(header["unsupported"], [])
            total = sum(
                b["num_verts"] * b.get("stride", 68)
                + (b["tri"]["vcount"] * 40 + b["tri"]["icount"] * 4
                   if "tri" in b else 0)
                for b in header["batches"] if not b.get("cached"))
            self.assertEqual(total, len(vertex_bytes))

            # Streaming: with geometry mode on, an animation (LEFT-arrow
            # reverse works even on a fully-run scene) mirrors every
            # pixel frame with a geometry payload
            ws.send(json.dumps({"type": "mode", "geometry": True}))
            ws.send(json.dumps(
                {"type": "key", "action": "down", "key": "ArrowLeft"}))
            frames, _ = self._collect(ws, 4)
            geometry_frames = [f for f in frames if f[0] == 0x03]
            jpeg_frames = [f for f in frames if f[0] == 0x01]
            self.assertGreater(
                len(geometry_frames), 3,
                f"expected streamed geometry, got {len(geometry_frames)} "
                f"(and {len(jpeg_frames)} JPEGs)")
            self.assertGreater(len(jpeg_frames), 3,
                               "pixel stream should continue alongside")

            # Solo-GL: geometry only, the pixel stream stops entirely
            ws.send(json.dumps(
                {"type": "mode", "geometry": True, "pixels": False}))
            self._collect(ws, 1)  # drain the mode-change transition
            ws.send(json.dumps(
                {"type": "key", "action": "down", "key": "ArrowLeft"}))
            frames, _ = self._collect(ws, 4)
            solo_geometry = [f for f in frames if f[0] == 0x03]
            solo_pixels = [f for f in frames if f[0] in (0x01, 0x02)]
            self.assertGreater(len(solo_geometry), 3,
                               "solo mode should stream geometry")
            self.assertEqual(len(solo_pixels), 0,
                             "solo mode must not stream pixels")
            ws.send(json.dumps({"type": "mode", "geometry": False}))

    def test_future_chips(self):
        with self._connect() as ws:
            frames, states = self._collect(ws, 3)
            self.assertTrue(states, "no state after connect")
            state = states[-1]
            # Un-run play-units appear as future chips with source lines
            if not state["future"]:
                self.skipTest("scene already fully run by test ordering")
            target = state["future"][-1]
            self.assertIn("unit", target)
            self.assertIn("line", target)

            # Clicking a future chip runs the scene forward to that unit
            ws.send(json.dumps({"type": "chip_future", "unit": target["unit"]}))
            frames, states = self._collect(ws, 5)
            self.assertTrue(states, "no state after future-chip click")
            self.assertGreater(states[-1]["count"], state["count"])
            self.assertEqual(states[-1]["future"], [])

    def test_untrusted_origin_is_rejected(self):
        with self.assertRaises(Exception):
            with ws_connect(
                    self.ws_url, origin="https://attacker.invalid",
                    open_timeout=3):
                pass

    def test_wrong_viewer_token_is_rejected(self):
        with ws_connect(
                self.ws_url, origin=self.origin, open_timeout=3) as ws:
            ws.send(json.dumps(
                {"type": "authenticate", "token": "wrong"}))
            with self.assertRaises(Exception):
                ws.recv(timeout=3)


MULTI_SCENE_SOURCE = """
from manim import *

class AlphaScene(Scene):
    def construct(self):
        self.play(FadeIn(Text("alpha")))

class BetaScene(Scene):
    def construct(self):
        self.play(FadeIn(Text("beta")))

class GammaScene(Scene):
    def construct(self):
        self.play(FadeIn(Text("gamma")))
"""


class SceneSwitchE2E(_ViewerHarness, unittest.TestCase):
    """Switching scenes reuses one viewer: same servers, same token, same
    connection. Its own subprocess, because switching changes which scene the
    process serves."""

    SOURCE = MULTI_SCENE_SOURCE
    SCENE = "AlphaScene"
    FILENAME = "multi_scene.py"

    def _state_after(self, ws, seconds):
        _, states = self._collect(ws, seconds)
        return states[-1] if states else None

    def test_state_lists_every_scene_in_the_file(self):
        with self._connect() as ws:
            state = self._state_after(ws, 4)
            self.assertIsNotNone(state, "no state after connect")
            self.assertEqual(state["scene"], "AlphaScene")
            self.assertEqual(
                state["scenes"], ["AlphaScene", "BetaScene", "GammaScene"])

    def test_switching_scene_keeps_the_same_connection(self):
        with self._connect() as ws:
            self.assertIsNotNone(self._state_after(ws, 4))

            ws.send(json.dumps(
                {"type": "switch_scene", "scene": "GammaScene"}))
            switched = self._state_after(ws, 20)
            self.assertIsNotNone(switched, "no state after switch")
            self.assertEqual(switched["scene"], "GammaScene")

            # And back again, on the very same socket.
            ws.send(json.dumps(
                {"type": "switch_scene", "scene": "AlphaScene"}))
            restored = self._state_after(ws, 20)
            self.assertIsNotNone(restored, "no state after second switch")
            self.assertEqual(restored["scene"], "AlphaScene")

    def test_unknown_scene_name_is_ignored(self):
        """The name selects a class to instantiate, so it must be checked
        against the file rather than trusted from the wire."""
        with self._connect() as ws:
            before = self._state_after(ws, 4)
            ws.send(json.dumps(
                {"type": "switch_scene", "scene": "NotAScene"}))
            after = self._state_after(ws, 4)
            current = (after or before)["scene"]
            self.assertEqual(current, before["scene"])
            self.assertTrue(self.proc.poll() is None, "process died")


if __name__ == "__main__":
    unittest.main()

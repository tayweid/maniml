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


class WebViewerE2E(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import tempfile
        cls.tmpdir = tempfile.TemporaryDirectory()
        scene_path = os.path.join(cls.tmpdir.name, "web_scene.py")
        with open(scene_path, "w") as f:
            f.write(SCENE_SOURCE)

        cls.proc = subprocess.Popen(
            [sys.executable, "-m", "maniml", scene_path, "WebDemo",
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
            import re
            for line in cls.stdout_lines:
                match = re.search(r"http://localhost:\d+/", line)
                if match:
                    return match.group(0)
        cls.url = cls._wait_for(find_url, STARTUP_TIMEOUT, "server URL in stdout")
        cls.ws_url = "ws://localhost:%d/" % (
            int(cls.url.rstrip("/").rsplit(":", 1)[1]) + 1)

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

    def test_full_loop(self):
        # The client page is served
        page = urllib.request.urlopen(self.url, timeout=5).read().decode()
        self.assertIn("<canvas", page)

        with ws_connect(self.ws_url, max_size=2**24) as ws:
            # On connect: a lossless PNG snapshot plus checkpoint state
            frames, states = self._collect(ws, 3)
            self.assertTrue(frames, "no frame after connect")
            self.assertEqual(frames[0][0], 0x02, "first frame should be PNG")
            self.assertTrue(frames[0][1:9].startswith(b"\x89PNG"), "PNG magic")
            self.assertTrue(states, "no state message after connect")
            start_state = states[-1]
            self.assertGreaterEqual(start_state["count"], 2)

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

    def test_future_chips(self):
        with ws_connect(self.ws_url, max_size=2**24) as ws:
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


if __name__ == "__main__":
    unittest.main()

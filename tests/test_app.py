"""End-to-end test of the maniml app shell.

Launches `maniml app` in a temp directory containing a scene file,
then acts as the browser: fetches the landing page, lists scene files
via the API, opens a scene (which spawns the scene subprocess), and
confirms the returned viewer URL serves the viewer and streams a frame
over its WebSocket.
"""

import json
import os
import re
import subprocess
import sys
import threading
import time
import unittest
import urllib.request

from websockets.sync.client import connect as ws_connect

SCENE_SOURCE = """
from manim import *

class AppDemo(Scene):
    def construct(self):
        self.play(FadeIn(Dot()))
"""

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class AppShellE2E(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import tempfile
        cls.tmpdir = tempfile.TemporaryDirectory()
        with open(os.path.join(cls.tmpdir.name, "app_scene.py"), "w") as f:
            f.write(SCENE_SOURCE)

        cls.proc = subprocess.Popen(
            [sys.executable, "-m", "maniml", "app", cls.tmpdir.name,
             "--no-browser"],
            env={**os.environ, "PYTHONPATH": REPO_ROOT,
                 "PYTHONUNBUFFERED": "1"},
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        cls.lines = []
        threading.Thread(
            target=lambda: [cls.lines.append(l) for l in cls.proc.stdout],
            daemon=True).start()

        deadline = time.time() + 15
        cls.url = None
        while time.time() < deadline and cls.url is None:
            if cls.proc.poll() is not None:
                raise AssertionError(
                    "app died:\n" + "".join(cls.lines))
            for line in cls.lines:
                match = re.search(r"http://localhost:\d+/", line)
                if match:
                    cls.url = match.group(0)
                    break
            time.sleep(0.05)
        assert cls.url, "no app URL:\n" + "".join(cls.lines)

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        try:
            cls.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            cls.proc.kill()
        cls.tmpdir.cleanup()

    def test_open_scene_from_landing(self):
        page = urllib.request.urlopen(self.url, timeout=5).read().decode()
        self.assertIn("maniml", page)

        files = json.loads(urllib.request.urlopen(
            self.url + "api/files", timeout=5).read())
        entry = next(f for f in files["files"]
                     if f["rel"] == "app_scene.py")
        self.assertEqual(entry["scenes"], ["AppDemo"])

        request = urllib.request.Request(
            self.url + "api/open",
            data=json.dumps(
                {"path": entry["path"], "scene": "AppDemo"}).encode(),
            headers={"Content-Type": "application/json"})
        opened = json.loads(
            urllib.request.urlopen(request, timeout=40).read())
        self.assertIn("url", opened, opened.get("error"))

        # The viewer serves its page, and its WebSocket streams a frame
        viewer = urllib.request.urlopen(
            opened["url"], timeout=5).read().decode()
        self.assertIn("<canvas", viewer)
        ws_port = int(opened["url"].rstrip("/").rsplit(":", 1)[1]) + 1
        with ws_connect(f"ws://localhost:{ws_port}/", max_size=2**24) as ws:
            deadline = time.time() + 10
            got_frame = False
            while time.time() < deadline and not got_frame:
                try:
                    message = ws.recv(timeout=1)
                except TimeoutError:
                    continue
                got_frame = isinstance(message, bytes)
            self.assertTrue(got_frame, "no frame from opened scene")

        # Re-opening the same scene reuses the live process (same URL)
        reopened = json.loads(
            urllib.request.urlopen(request, timeout=40).read())
        self.assertEqual(reopened["url"], opened["url"])

    def test_missing_module_hint(self):
        broken = os.path.join(self.tmpdir.name, "broken_scene.py")
        with open(broken, "w") as f:
            f.write("import not_a_real_module_xyz\n"
                    "from manim import *\n"
                    "class Broken(Scene):\n"
                    "    def construct(self): pass\n")
        request = urllib.request.Request(
            self.url + "api/open",
            data=json.dumps({"path": broken, "scene": "Broken"}).encode(),
            headers={"Content-Type": "application/json"})
        try:
            body = urllib.request.urlopen(request, timeout=40).read()
        except urllib.error.HTTPError as err:
            body = err.read()
        data = json.loads(body)
        self.assertIn("error", data)
        hint = data.get("hint") or ""
        self.assertIn("not_a_real_module_xyz", hint,
                      f"hint missing; log tail: {data.get('log', '')[-500:]}")
        self.assertIn(sys.executable, hint)


if __name__ == "__main__":
    unittest.main()

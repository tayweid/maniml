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
from urllib.parse import urlsplit

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
        cls.outside_tmpdir = tempfile.TemporaryDirectory()
        with open(os.path.join(cls.tmpdir.name, "app_scene.py"), "w") as f:
            f.write(SCENE_SOURCE)

        cls.proc = subprocess.Popen(
            [sys.executable, "-m", "maniml", "app", cls.tmpdir.name,
             "--no-browser"],
            env={**os.environ, "PYTHONPATH": REPO_ROOT,
                 "PYTHONUNBUFFERED": "1",
                 "MANIML_RECENTS_PATH": os.path.join(
                     cls.tmpdir.name, "recents.json")},
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        cls.lines = []
        threading.Thread(
            target=lambda: [cls.lines.append(l) for l in cls.proc.stdout],
            daemon=True).start()

        deadline = time.time() + 15
        cls.url = None
        cls.token = None
        while time.time() < deadline and cls.url is None:
            if cls.proc.poll() is not None:
                raise AssertionError(
                    "app died:\n" + "".join(cls.lines))
            for line in cls.lines:
                match = re.search(
                    r"(http://localhost:\d+/)#token=([A-Za-z0-9_-]+)",
                    line)
                if match:
                    cls.url = match.group(1)
                    cls.token = match.group(2)
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
        cls.outside_tmpdir.cleanup()

    @classmethod
    def _request(cls, path, data=None, headers=None):
        request_headers = {"Authorization": f"Bearer {cls.token}"}
        request_headers.update(headers or {})
        return urllib.request.Request(
            cls.url + path, data=data, headers=request_headers)

    @classmethod
    def _open_request(cls, path, scene):
        return cls._request(
            "api/open",
            data=json.dumps({"path": path, "scene": scene}).encode(),
            headers={"Content-Type": "application/json"})

    def test_open_scene_from_landing(self):
        page = urllib.request.urlopen(self.url, timeout=5).read().decode()
        self.assertIn("maniml", page)

        files = json.loads(urllib.request.urlopen(
            self._request("api/files"), timeout=5).read())
        entry = next(f for f in files["files"]
                     if f["rel"] == "app_scene.py")
        self.assertEqual(entry["scenes"], ["AppDemo"])

        request = self._open_request(entry["path"], "AppDemo")
        opened = json.loads(
            urllib.request.urlopen(request, timeout=40).read())
        self.assertIn("url", opened, opened.get("error"))

        # The viewer serves its page, and its WebSocket streams a frame
        viewer = urllib.request.urlopen(
            opened["url"], timeout=5).read().decode()
        self.assertIn("<canvas", viewer)
        parsed = urlsplit(opened["url"])
        ws_port = parsed.port + 1
        viewer_token = parsed.fragment.removeprefix("token=")
        with ws_connect(
                f"ws://localhost:{ws_port}/", max_size=2**24,
                origin=f"http://localhost:{parsed.port}") as ws:
            ws.send(json.dumps(
                {"type": "authenticate", "token": viewer_token}))
            self.assertEqual(
                json.loads(ws.recv(timeout=5))["type"], "authenticated")
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

    def test_control_websocket(self):
        # The fixed-port control channel the hosted PWA uses
        with ws_connect(
                "ws://127.0.0.1:8686/", origin=self.url.rstrip("/")) as ws:
            ws.send(json.dumps(
                {"type": "authenticate", "token": self.token}))
            self.assertEqual(
                json.loads(ws.recv(timeout=5))["type"], "authenticated")
            ws.send(json.dumps({"op": "files", "id": 1}))
            data = json.loads(ws.recv(timeout=10))
            self.assertEqual(data["id"], 1)
            entry = next(f for f in data["files"]
                         if f["rel"] == "app_scene.py")
            ws.send(json.dumps({"op": "open", "id": 2,
                                "path": entry["path"], "scene": "AppDemo"}))
            opened = json.loads(ws.recv(timeout=60))
            self.assertEqual(opened["id"], 2)
            self.assertIn("ws_port", opened, opened.get("error"))
        # The app server serves the viewer page for the hosted-style
        # navigation (viewer.html?ws=PORT)
        page = urllib.request.urlopen(
            self.url + "viewer.html", timeout=5).read().decode()
        self.assertIn("<canvas", page)
        manifest = urllib.request.urlopen(
            self.url + "manifest.webmanifest", timeout=5).read().decode()
        self.assertIn("maniml", manifest)

    def test_missing_module_hint(self):
        broken = os.path.join(self.tmpdir.name, "broken_scene.py")
        with open(broken, "w") as f:
            f.write("import not_a_real_module_xyz\n"
                    "from manim import *\n"
                    "class Broken(Scene):\n"
                    "    def construct(self): pass\n")
        request = self._open_request(broken, "Broken")
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

    def test_unauthorized_requests_cannot_start_scenes(self):
        marker = os.path.join(self.tmpdir.name, "unauthorized-marker")
        scene_path = os.path.join(self.tmpdir.name, "unauthorized_scene.py")
        with open(scene_path, "w") as f:
            f.write(
                f"from pathlib import Path\nPath({marker!r}).touch()\n"
                "from manim import *\nclass Unauthorized(Scene): pass\n")
        request = urllib.request.Request(
            self.url + "api/open",
            data=json.dumps(
                {"path": scene_path, "scene": "Unauthorized"}).encode(),
            headers={"Content-Type": "application/json"})
        with self.assertRaises(urllib.error.HTTPError) as raised:
            urllib.request.urlopen(request, timeout=5)
        self.assertEqual(raised.exception.code, 401)
        self.assertFalse(os.path.exists(marker))

    def test_outside_root_and_unknown_scene_are_rejected_before_import(self):
        outside_marker = os.path.join(
            self.outside_tmpdir.name, "outside-marker")
        outside_scene = os.path.join(
            self.outside_tmpdir.name, "outside_scene.py")
        with open(outside_scene, "w") as f:
            f.write(
                f"from pathlib import Path\nPath({outside_marker!r}).touch()\n"
                "from manim import *\nclass Outside(Scene): pass\n")
        with self.assertRaises(urllib.error.HTTPError) as raised:
            urllib.request.urlopen(
                self._open_request(outside_scene, "Outside"), timeout=5)
        self.assertEqual(raised.exception.code, 400)
        self.assertFalse(os.path.exists(outside_marker))

        inside_marker = os.path.join(self.tmpdir.name, "unknown-marker")
        inside_scene = os.path.join(self.tmpdir.name, "unknown_scene.py")
        with open(inside_scene, "w") as f:
            f.write(
                f"from pathlib import Path\nPath({inside_marker!r}).touch()\n"
                "from manim import *\nclass Known(Scene): pass\n")
        with self.assertRaises(urllib.error.HTTPError) as raised:
            urllib.request.urlopen(
                self._open_request(inside_scene, "NotDiscovered"), timeout=5)
        self.assertEqual(raised.exception.code, 400)
        self.assertFalse(os.path.exists(inside_marker))

    def test_control_websocket_rejects_untrusted_origin(self):
        with self.assertRaises(Exception):
            with ws_connect(
                    "ws://127.0.0.1:8686/",
                    origin="https://attacker.invalid", open_timeout=3):
                pass

    def test_control_websocket_rejects_wrong_token(self):
        with ws_connect(
                "ws://127.0.0.1:8686/", origin=self.url.rstrip("/"),
                open_timeout=3) as ws:
            ws.send(json.dumps(
                {"type": "authenticate", "token": "wrong"}))
            with self.assertRaises(Exception):
                ws.recv(timeout=3)


if __name__ == "__main__":
    unittest.main()

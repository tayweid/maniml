"""End-to-end test of the maniml app shell.

Launches `maniml app` in a temp directory containing a scene file, then acts
as the browser: fetches the landing page over HTTP, drives the control
WebSocket *on the same port* to list and open scenes, and confirms the scene
process serves its own viewer and streams a frame — one origin per process,
page and socket together.
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
from contextlib import contextmanager
from pathlib import Path

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
        while time.time() < deadline and cls.url is None:
            if cls.proc.poll() is not None:
                raise AssertionError(
                    "app died:\n" + "".join(cls.lines))
            for line in cls.lines:
                match = re.search(r"maniml app: (http://localhost:(\d+)/)", line)
                if match:
                    cls.url = match.group(1)
                    cls.port = int(match.group(2))
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
    def _control_url(cls):
        # The page's own address: one port serves the page and its socket.
        return f"ws://localhost:{cls.port}/"

    @classmethod
    @contextmanager
    def _control(cls, origin=None):
        """A control socket, opened exactly as the page opens one."""
        with ws_connect(
                cls._control_url(),
                origin=origin or cls.url.rstrip("/"),
                open_timeout=5) as ws:
            yield ws

    @classmethod
    def _request(cls, ws, op, timeout=40, **extra):
        ws.send(json.dumps({"op": op, "id": 1, **extra}))
        deadline = time.time() + timeout
        while time.time() < deadline:
            message = json.loads(ws.recv(timeout=timeout))
            if message.get("type") == "ready":
                continue
            return message
        raise AssertionError(f"no response to {op}")

    def test_open_scene_from_landing(self):
        # The landing page comes off the same port the socket listens on.
        page = urllib.request.urlopen(self.url, timeout=5).read().decode()
        self.assertIn("maniml", page)

        scene_path = os.path.join(self.tmpdir.name, "app_scene.py")
        with self._control() as ws:
            opened = self._request(ws, "open", path=scene_path, scene="AppDemo")
            self.assertIn("url", opened, opened.get("error"))
            # The page is never sent to another port: the port is the
            # installed app's identity, so a scene opens inside it.
            self.assertEqual(
                opened["viewer_url"], f"viewer.html?scene={opened['scene_id']}")

            # Re-opening the same scene reuses the live process (same URL)
            reopened = self._request(ws, "open", path=scene_path, scene="AppDemo")
            self.assertEqual(reopened["url"], opened["url"])

        # Everything the browser touches is this one origin: the viewer page,
        # and a socket the app relays to the process running the scene.
        viewer = urllib.request.urlopen(
            self.url + opened["viewer_url"], timeout=5).read().decode()
        self.assertIn("<canvas", viewer)
        with ws_connect(
                f"{self._control_url()}scene/{opened['scene_id']}",
                max_size=2**24, origin=self.url.rstrip("/")) as ws:
            ready = json.loads(ws.recv(timeout=10))
            self.assertEqual(ready["type"], "ready")
            deadline = time.time() + 10
            got_frame = False
            while time.time() < deadline and not got_frame:
                try:
                    message = ws.recv(timeout=1)
                except TimeoutError:
                    continue
                got_frame = isinstance(message, bytes)
            self.assertTrue(got_frame, "no frame relayed from opened scene")

    def test_relay_refuses_a_scene_it_is_not_running(self):
        with ws_connect(
                f"{self._control_url()}scene/not-a-scene",
                origin=self.url.rstrip("/")) as ws:
            with self.assertRaises(Exception):
                ws.recv(timeout=5)

    def test_viewer_page_is_served_by_the_app_too(self):
        # The app serves the whole static directory, so a viewer opened from
        # a bookmark on this origin still finds its assets.
        page = urllib.request.urlopen(
            self.url + "viewer.html", timeout=5).read().decode()
        self.assertIn("<canvas", page)

    def test_served_pages_restrict_themselves_to_this_origin(self):
        with urllib.request.urlopen(self.url, timeout=5) as response:
            policy = response.headers["Content-Security-Policy"]
        self.assertIn("connect-src 'self'", policy)
        self.assertIn("default-src 'self'", policy)

    def test_missing_module_hint(self):
        broken = os.path.join(self.tmpdir.name, "broken_scene.py")
        with open(broken, "w") as f:
            f.write("import not_a_real_module_xyz\n"
                    "from manim import *\n"
                    "class Broken(Scene):\n"
                    "    def construct(self): pass\n")
        with self._control() as ws:
            data = self._request(ws, "open", path=broken, scene="Broken")
        self.assertIn("error", data)
        hint = data.get("hint") or ""
        self.assertIn("not_a_real_module_xyz", hint,
                      f"hint missing; log tail: {data.get('log', '')[-500:]}")
        self.assertIn(sys.executable, hint)

    def test_a_foreign_origin_cannot_start_scenes(self):
        """The Origin check is the boundary: a page on any other origin —
        which is every website — is refused before it can say anything."""
        marker = os.path.join(self.tmpdir.name, "unauthorized-marker")
        scene_path = os.path.join(self.tmpdir.name, "unauthorized_scene.py")
        with open(scene_path, "w") as f:
            f.write(
                f"from pathlib import Path\nPath({marker!r}).touch()\n"
                "from manim import *\nclass Unauthorized(Scene): pass\n")
        with self.assertRaises(Exception):
            with ws_connect(
                    self._control_url(), origin="https://attacker.invalid",
                    open_timeout=3) as ws:
                ws.send(json.dumps(
                    {"op": "open", "id": 1,
                     "path": scene_path, "scene": "Unauthorized"}))
                ws.recv(timeout=3)
        time.sleep(0.5)
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

        inside_marker = os.path.join(self.tmpdir.name, "unknown-marker")
        inside_scene = os.path.join(self.tmpdir.name, "unknown_scene.py")
        with open(inside_scene, "w") as f:
            f.write(
                f"from pathlib import Path\nPath({inside_marker!r}).touch()\n"
                "from manim import *\nclass Known(Scene): pass\n")

        with self._control() as ws:
            outside = self._request(
                ws, "open", path=outside_scene, scene="Outside", timeout=10)
            self.assertIn("error", outside)
            unknown = self._request(
                ws, "open", path=inside_scene, scene="NotDiscovered",
                timeout=10)
            self.assertIn("error", unknown)

        self.assertFalse(os.path.exists(outside_marker))
        self.assertFalse(os.path.exists(inside_marker))

    def test_control_websocket_rejects_untrusted_origin(self):
        with self.assertRaises(Exception):
            with ws_connect(
                    self._control_url(),
                    origin="https://attacker.invalid", open_timeout=3):
                pass

    def test_control_websocket_rejects_a_missing_origin(self):
        """A non-browser client sends no Origin at all; the handshake must
        refuse that rather than treat it as same-origin."""
        with self.assertRaises(Exception):
            with ws_connect(self._control_url(), open_timeout=3):
                pass


class RunningEngineTests(unittest.TestCase):
    """`maniml app` should use an engine that is already up, not compete with
    it: the port is the installed app's identity, so a second engine on
    another port serves a page the installed app will never open."""

    def test_it_reports_what_a_running_engine_serves(self):
        from maniml.web.app import AppServer, running_engine
        from maniml.web.assets import _package_version

        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            server = AppServer(tmpdir, port=0)
            self.addCleanup(server.shutdown)
            self.assertEqual(running_engine(server.port), _package_version())

    def test_nothing_listening_is_not_an_engine(self):
        from maniml.web.app import running_engine
        # Port 9 (discard) is reserved and never serves HTML.
        self.assertIsNone(running_engine(9, timeout=0.5))


class PortFallbackTests(unittest.TestCase):
    """A background agent owns the default port for the whole login session,
    so a foreground app must still come up on a working one of its own."""

    def test_a_taken_port_falls_back_to_an_assigned_one(self):
        import tempfile
        from maniml.web.app import DEFAULT_APP_PORT, AppServer

        with tempfile.TemporaryDirectory() as tmpdir:
            holder = AppServer(tmpdir, port=0)
            self.addCleanup(holder.shutdown)
            occupied = holder.port
            self.assertNotEqual(occupied, 0)

            second = AppServer(tmpdir, port=occupied)
            self.addCleanup(second.shutdown)
            self.assertNotEqual(
                second.port, occupied,
                "second server bound a port already in use")
            self.assertGreater(second.port, 0)
            # Each server's page is confined to its own origin.
            self.assertEqual(second.allowed_origins, {second.origin})

        self.assertEqual(DEFAULT_APP_PORT, 8685)


class NativeDialogGrantTests(unittest.TestCase):
    """The Open action hands over a file the user picked in the native
    dialog. A file with several scenes cannot be opened directly, so it
    must still be reachable from the landing page as a granted recent."""

    def setUp(self):
        import tempfile
        from maniml.web.app import AppServer

        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.outside = tempfile.TemporaryDirectory()
        self.addCleanup(self.outside.cleanup)
        recents = os.path.join(self.tmpdir.name, "recents.json")
        previous = os.environ.get("MANIML_RECENTS_PATH")
        os.environ["MANIML_RECENTS_PATH"] = recents
        self.addCleanup(
            lambda: os.environ.__setitem__("MANIML_RECENTS_PATH", previous)
            if previous is not None
            else os.environ.pop("MANIML_RECENTS_PATH", None)
        )
        # grant_file resolves; macOS hands out /var paths that resolve to
        # /private/var, so compare against the resolved form.
        self.multi = str(
            Path(os.path.join(self.tmpdir.name, "two_scenes.py")).resolve()
        )
        with open(self.multi, "w") as f:
            f.write(
                "from manim import *\n"
                "class AlphaScene(Scene): pass\n"
                "class BetaScene(Scene): pass\n"
            )
        self.server = AppServer(self.tmpdir.name, port=0)
        self.addCleanup(self.server.shutdown)

    def test_multi_scene_file_opens_at_its_first_scene(self):
        """Most course files hold a dozen scenes. Refusing to open them meant
        an extra click for nothing, since the viewer's own picker switches
        scenes in the same process."""
        result = self.server.open_payload({"path": self.multi})
        self.assertIn("viewer_url", result, result.get("error"))
        self.assertIn((self.multi, "AlphaScene"), self.server.processes)

    def test_a_file_with_no_scenes_still_says_so(self):
        empty = os.path.join(self.tmpdir.name, "no_scenes.py")
        with open(empty, "w") as f:
            f.write("value = 1\n")
        result = self.server.open_payload({"path": empty})
        self.assertIn("no Manim scene classes", result.get("error", ""))
        self.assertNotIn("viewer_url", result)

    def test_a_granted_file_is_listed_as_recent(self):
        self.assertEqual(self.server.grant_file(self.multi), self.multi)
        listed = {
            entry["path"]: entry["name"]
            for entry in self.server.recents_payload()["recents"]
        }
        self.assertEqual(listed.get(self.multi), "two_scenes.py")

    def test_a_recent_stays_openable_in_a_later_session(self):
        """Recents are the landing page's only discovery surface, so a file
        picked through the OS dialog has to survive a restart. A fresh server
        on the same recents file seeds its grants from it."""
        from maniml.web.app import AppServer

        outside = Path(self.outside.name) / "elsewhere.py"
        outside.write_text("from manim import *\nclass Far(Scene): pass\n")
        self.assertEqual(
            self.server.grant_file(str(outside)), str(outside.resolve()))

        later = AppServer(self.tmpdir.name, port=0)
        self.addCleanup(later.shutdown)
        self.assertIn(str(outside.resolve()), later._granted_files)
        listed = [e["path"] for e in later.recents_payload()["recents"]]
        self.assertIn(str(outside.resolve()), listed)

    def test_grant_file_refuses_a_path_that_is_not_a_python_file(self):
        other = os.path.join(self.tmpdir.name, "notes.txt")
        with open(other, "w") as f:
            f.write("not a scene\n")
        self.assertIsNone(self.server.grant_file(other))
        self.assertIsNone(self.server.grant_file(
            os.path.join(self.tmpdir.name, "missing.py")))


if __name__ == "__main__":
    unittest.main()

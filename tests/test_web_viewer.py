"""End-to-end test of the browser viewer (--web).

Launches a real scene subprocess in web mode, then acts as the browser:
fetches the client page over HTTP, connects to the WebSocket, and
asserts the full loop works — initial PNG frame + state on connect,
JPEG streaming after a RIGHT-arrow keypress, checkpoint state advancing,
and click-to-inspect printing the variable name to the terminal.

Headless (offscreen GL only), so it runs un-gated like the other
integration suites.
"""

import inspect
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
    def _collect(ws, seconds, logs=None):
        """Gather (binary_frames, states) arriving within `seconds`.

        Console output shares this socket, so log messages are separated out
        rather than left to masquerade as the last state.
        """
        frames, states = [], []
        deadline = time.time() + seconds
        while time.time() < deadline:
            try:
                msg = ws.recv(timeout=max(0.05, deadline - time.time()))
            except TimeoutError:
                break
            if isinstance(msg, bytes):
                frames.append(msg)
                continue
            message = json.loads(msg)
            if message.get("type") == "log":
                if logs is not None:
                    logs.extend(message["lines"])
            else:
                states.append(message)
        return frames, states

    def _connect(self):
        ws = ws_connect(
            self.ws_url, max_size=2**24, origin=self.origin)
        response = json.loads(ws.recv(timeout=5))
        self.assertEqual(response["type"], "ready")
        self.assertEqual(set(response["capabilities"]), {"export", "restart"})
        return ws


class RailAnchorTests(unittest.TestCase):
    """While a stretch is crossed, the rail stands at the last stop
    checkpoint — interior play saves must not walk the position ring."""

    @staticmethod
    def anchor_fn(pause_anchored, checkpoints):
        from types import SimpleNamespace
        from maniml.web.viewer import WebViewer
        viewer = SimpleNamespace(scene=SimpleNamespace(
            _pause_anchored=lambda: pause_anchored,
            animation_checkpoints=checkpoints))
        return lambda i: WebViewer._rail_anchor(viewer, i)

    def test_holds_at_the_last_stop(self):
        anchor = self.anchor_fn(True, [
            {}, {}, {"stop": True}, {}, {}, {"stop": True}])
        self.assertEqual(anchor(4), 2)   # mid-stretch -> the stop it left
        self.assertEqual(anchor(5), 5)   # parked on a stop
        self.assertEqual(anchor(1), 0)   # before the first stop -> Start
        self.assertEqual(anchor(0), 0)

    def test_plain_files_anchor_everywhere(self):
        anchor = self.anchor_fn(False, [{}, {}, {}])
        self.assertEqual(anchor(2), 2)


class WebViewerE2E(_ViewerHarness, unittest.TestCase):
    def test_present_toggle_prebuilds_and_stops_the_watcher(self):
        """The Present button flips the running scene into present mode:
        every unit pre-run, rewound to the start, watcher off — and back."""
        with self._connect() as ws:
            self._collect(ws, 2)
            ws.send(json.dumps({"type": "present"}))
            deadline = time.time() + 20
            on_state = None
            while time.time() < deadline and on_state is None:
                _, states = self._collect(ws, 2)
                for s in states:
                    if s.get("type") == "state" and s.get("present"):
                        on_state = s
            self.assertIsNotNone(on_state, "present mode never engaged")
            self.assertEqual(on_state["current"], 0, "did not rewind to start")
            self.assertGreaterEqual(on_state["count"], 4,
                                    "checkpoints were not all pre-built")
            ws.send(json.dumps({"type": "present"}))   # toggle back off
            deadline = time.time() + 10
            off = False
            while time.time() < deadline and not off:
                _, states = self._collect(ws, 2)
                off = any(s.get("type") == "state" and not s.get("present")
                          for s in states)
            self.assertTrue(off, "present mode never disengaged")

    def test_present_bundle_serving_freshness_and_ranges(self):
        """media/<Scene>_present is mounted at /present/ with single-range
        support (video seeking), and the state reports whether the bundle
        matches the scene file as it is now."""
        import hashlib
        from urllib.request import Request, urlopen

        scene_file = os.path.join(self.tmpdir.name, self.FILENAME)
        with open(scene_file, "rb") as f:
            good_hash = hashlib.blake2b(f.read(), digest_size=16).hexdigest()
        bundle = os.path.join(self.tmpdir.name, "media", f"{self.SCENE}_present")
        os.makedirs(bundle, exist_ok=True)
        with open(os.path.join(bundle, "scene.mp4"), "wb") as f:
            f.write(b"0123456789abcdef")
        meta = {"format": 1, "source": {"hash": good_hash}, "checkpoints": []}
        with open(os.path.join(bundle, "present.json"), "w") as f:
            json.dump(meta, f)

        def latest(states, field):
            values = [s.get(field) for s in states if s.get("type") == "state"]
            return values[-1] if values else None

        with self._connect() as ws:
            _, states = self._collect(ws, 3)
            self.assertTrue(latest(states, "present_bundle"),
                            "state never advertised the bundle")
            self.assertTrue(latest(states, "present_fresh"),
                            "matching hash reported stale")

            request = Request(self.url + "present/scene.mp4",
                              headers={"Range": "bytes=4-7"})
            with urlopen(request, timeout=5) as response:
                self.assertEqual(response.status, 206)
                self.assertEqual(response.read(), b"4567")
                self.assertEqual(response.headers["Content-Range"],
                                 "bytes 4-7/16")

            # a bundle baked from different source reports stale
            meta["source"]["hash"] = "0" * 32
            with open(os.path.join(bundle, "present.json"), "w") as f:
                json.dump(meta, f)
            deadline = time.time() + 10
            stale = None
            while time.time() < deadline and stale is not False:
                _, states = self._collect(ws, 2)
                value = latest(states, "present_fresh")
                if value is not None:
                    stale = value
            self.assertFalse(stale, "hash mismatch still reported fresh")

    def test_app_relay_answers_scene_output_folders(self):
        """Through the app, the page lives on the app's origin and fetches
        /scene/<id>/present|baked/* — the app must answer those from the
        scene process backing the id, Range included, or Present cannot
        find the bundle it is standing next to."""
        from types import SimpleNamespace
        from maniml.web.app import AppServer

        bundle = os.path.join(self.tmpdir.name, "media", f"{self.SCENE}_present")
        os.makedirs(bundle, exist_ok=True)
        with open(os.path.join(bundle, "present.json"), "w") as f:
            json.dump({"format": 1, "checkpoints": []}, f)
        with open(os.path.join(bundle, "scene.mp4"), "wb") as f:
            f.write(b"0123456789")
        with self._connect() as ws:
            self._collect(ws, 3)   # a state broadcast mounts present_dir

        from websockets.datastructures import Headers
        stub = SimpleNamespace(
            _scenes_by_id={"abc": SimpleNamespace(
                url=self.url, alive=lambda: True)},
            _SCENE_ASSET=AppServer._SCENE_ASSET,
        )

        def relay(path, headers=()):
            request = SimpleNamespace(
                method="GET", path=path, headers=Headers(list(headers)))
            return AppServer._relay_scene_asset(stub, request)

        answer = relay("/scene/abc/present/present.json")
        self.assertEqual(answer.status_code, 200)
        self.assertEqual(json.loads(answer.body)["format"], 1)

        partial = relay("/scene/abc/present/scene.mp4",
                        [("Range", "bytes=2-5")])
        self.assertEqual(partial.status_code, 206)
        self.assertEqual(partial.body, b"2345")

        missing = relay("/scene/nope/present/present.json")
        self.assertEqual(missing.status_code, 404)
        self.assertIsNone(relay("/other/path"))

    def test_baked_export_is_served_on_the_same_origin(self):
        """media/<Scene>_web is mounted read-only at /baked/ on the one
        port; escaping the folder is contained."""
        from urllib.request import urlopen
        from urllib.error import HTTPError

        baked = os.path.join(self.tmpdir.name, "media", f"{self.SCENE}_web")
        os.makedirs(baked, exist_ok=True)
        with open(os.path.join(baked, "index.html"), "w") as f:
            f.write("<title>baked</title>")
        with self._connect() as ws:
            # a state broadcast sets server.baked_dir and carries the flag
            _, states = self._collect(ws, 3)
            with urlopen(self.url + "baked/", timeout=5) as response:
                self.assertIn(b"baked", response.read())
            with self.assertRaises(HTTPError) as caught:
                urlopen(self.url + "baked/../" + self.FILENAME, timeout=5)
            self.assertEqual(caught.exception.code, 404)
            self.assertTrue(
                any(s.get("baked") for s in states if s.get("type") == "state"),
                "state never advertised the baked export")

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
            # Nothing has run: the scene waits at checkpoint 0 until asked.
            self.assertEqual(start_state["count"], 1)
            self.assertEqual(start_state["current"], 0)
            self.assertTrue(start_state["future"], "no units left to run")
            self.assertEqual(start_state["file"], "web_scene.py")

            # RIGHT arrow: the next unit runs and streams JPEG frames
            ws.send(json.dumps(
                {"type": "key", "action": "down", "key": "ArrowRight"}))
            printed = []
            frames, states = self._collect(ws, 4, logs=printed)
            # Whatever the scene said on the way reaches the console. In app
            # mode this socket is the only place it can be seen at all: the
            # child's stdout is a pipe into the app process.
            self.assertTrue(printed, "no console output from a running unit")
            self.assertTrue(
                any("animation" in line["text"].lower() for line in printed),
                printed)
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

            # Streaming: with geometry mode on, an animation mirrors every
            # pixel frame with a geometry payload. LEFT is an instant jump
            # (no frames), so jump back and re-run the unit with RIGHT.
            ws.send(json.dumps({"type": "mode", "geometry": True}))
            ws.send(json.dumps(
                {"type": "key", "action": "down", "key": "ArrowLeft"}))
            ws.send(json.dumps(
                {"type": "key", "action": "down", "key": "ArrowRight"}))
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
            ws.send(json.dumps(
                {"type": "key", "action": "down", "key": "ArrowRight"}))
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

    def test_a_client_that_sends_no_origin_is_rejected(self):
        """Browsers always send one; anything that does not is not the page
        this viewer served, and the handshake is where that is decided."""
        with self.assertRaises(Exception):
            with ws_connect(self.ws_url, open_timeout=3):
                pass


class StreamPolicyTests(unittest.TestCase):
    """The streaming policy's one timing invariant, checked by arithmetic
    rather than by watching a clock — a rate assertion against a real process
    would be exactly the flaky test nobody trusts."""

    def test_the_throttle_does_not_alias_with_the_frame_rate(self):
        """A throttle equal to the frame period sits exactly on the boundary
        each rendered frame arrives at, so jitter decides whether each one
        passes: about half are skipped and the survivors land one or two
        frame-periods apart. Constant-velocity motion visibly wobbles and a
        transition shows its intermediate shapes instead of moving. Measured
        at 1/30 against a 30fps scene: 16.5fps delivered, gaps averaging
        62ms with a 12ms deviation; with a margin, 30.6fps and 1.7ms.
        """
        from maniml.camera.camera import Camera
        from maniml.web.viewer import MIN_SEND_INTERVAL

        frame_period = 1 / inspect.signature(Camera).parameters["fps"].default
        self.assertLess(
            MIN_SEND_INTERVAL, frame_period,
            "the throttle would drop rendered frames outright")
        self.assertLessEqual(
            MIN_SEND_INTERVAL, frame_period * 0.9,
            "the throttle is close enough to the frame period to alias "
            "against it once real timing jitter is involved")


RAIL_SOURCE = """
from manim import *

class RailDemo(Scene):
    def construct(self):
        dot = Dot()
        self.play(FadeIn(dot))

        for _ in range(3):
            self.play(dot.animate.shift(RIGHT * 0.5), run_time=0.2)

        self.play(FadeOut(dot))
"""


class TimelineRailE2E(_ViewerHarness, unittest.TestCase):
    """What the rail is told, over the real socket.

    Two things the timeline needs and used to lack: which stretch an
    animation is crossing while it crosses it, and an honest answer about
    units whose pausepoint count is not knowable before they run.
    """

    SOURCE = RAIL_SOURCE
    SCENE = "RailDemo"
    FILENAME = "rail_scene.py"

    @staticmethod
    def _moves(states):
        return [m for m in states if m.get("type") == "move"]

    @staticmethod
    def _press(ws, key):
        ws.send(json.dumps({"type": "key", "action": "down", "key": key}))
        ws.send(json.dumps({"type": "key", "action": "up", "key": key}))

    def test_a_loop_unit_says_it_holds_an_unknown_number(self):
        with self._connect() as ws:
            _, states = self._collect(ws, 3)
            future = [s for s in states if s.get("type") == "state"][-1]["future"]
            if not future:
                self.skipTest("scene already fully run by test ordering")
            # Keyed by unit index, so the assertion survives whatever the
            # tests sharing this scene process have already run.
            many = {u["unit"]: u["many"] for u in future}
            self.assertTrue(any(many.values()), "the loop unit is missing")
            for unit, unknown in many.items():
                self.assertEqual(unknown, unit == 1,
                                 f"unit {unit} claims the wrong certainty")

    def test_a_forward_play_lights_the_stretch_it_crosses(self):
        """The rail must hear about the move when the play starts, not when
        the checkpoint lands — waiting for the checkpoint is what made
        stepping read as a jump."""
        with self._connect() as ws:
            self._collect(ws, 2)
            self._press(ws, "ArrowRight")
            _, states = self._collect(ws, 6)
            moves = self._moves(states)
            self.assertTrue(moves, "no move message for a forward play")
            self.assertEqual(moves[0]["from"], 0)
            self.assertEqual(moves[0]["to"], 1)
            self.assertFalse(moves[0]["back"])
            self.assertIsNone(moves[-1]["from"], "the move was never cleared")
            # The stretch is all it says: an animation's progress is on
            # screen already, and a claim would have to survive reverse
            # morphs and fast-forwards too.
            self.assertEqual(set(moves[0]),
                             {"type", "from", "to", "back", "unit"})

    def test_state_says_which_statement_each_checkpoint_came_from(self):
        """Without it the rail cannot keep a loop's checkpoints in the one
        chip that stood for them before it ran — it would only see a run of
        new checkpoints and draw a chip each."""
        with self._connect() as ws:
            # State is sent only when it changes, so keep the latest one seen
            # rather than expecting the last collect to carry it.
            latest = None

            def drive(seconds):
                nonlocal latest
                _, messages = self._collect(ws, seconds)
                for message in messages:
                    if message.get("type") == "state":
                        latest = message

            drive(2)
            # Run forward until the loop unit has been through, wherever the
            # tests sharing this scene process left it.
            for _ in range(4):
                self._press(ws, "ArrowRight")
                drive(8)
            state = latest
            self.assertIsNotNone(state, "no state seen")
            self.assertEqual(len(state["units"]), state["count"])
            runs = [u for u in state["units"] if u is not None]
            self.assertNotEqual(len(runs), len(set(runs)),
                                "the loop's checkpoints must share a unit")

    def test_sitting_still_is_not_moving(self):
        """wait() runs through the same pre_play/post_play hooks a play does,
        but a pause is not a crossing to the next pausepoint: lighting the
        rail for it would say a move was under way through every wait."""
        with self._connect() as ws:
            self._collect(ws, 2)
            self._press(ws, "ArrowRight")
            _, states = self._collect(ws, 8)
            starts = [m for m in self._moves(states) if m["from"] is not None]
            # The fixture's first unit is one play; its wait is a separate
            # unit, and neither may report more than that play's own move.
            self.assertLessEqual(len(starts), 1, "a wait reported a move")

    def test_left_is_an_instant_jump_and_announces_no_move(self):
        """Backward navigation is a jump (DECISIONS.md, "Backward
        navigation is a jump"): the state lands directly on the target and
        no move message fires — `back` stays reserved for the
        recorded-playback layer."""
        def latest_current(states, fallback):
            currents = [s.get("current") for s in states
                        if s.get("type") == "state"]
            return currents[-1] if currents else fallback

        with self._connect() as ws:
            _, states = self._collect(ws, 2)
            current = latest_current(states, 0)
            if current == 0:
                # a fresh scene: move off the start so there is somewhere
                # to jump back to (tests share this scene process, so it
                # may already be mid-scene)
                self._press(ws, "ArrowRight")
                _, states = self._collect(ws, 8)
                current = latest_current(states, 1)
            self._press(ws, "ArrowLeft")
            _, states = self._collect(ws, 8)
            moves = [m for m in self._moves(states) if m["from"] is not None]
            self.assertFalse(moves, "a jump must not announce a move")
            self.assertEqual(latest_current(states, None), current - 1,
                             "LEFT did not land one checkpoint back")


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
    """Switching scenes reuses one viewer: same server, same
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

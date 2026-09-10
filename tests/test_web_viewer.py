"""End-to-end test of the browser viewer (--web).

Launches a real scene subprocess in web mode, then acts as the browser:
fetches the client page over HTTP, connects to the WebSocket, and
asserts the full loop works — state on connect, a geometry payload once
the client reports its renderer, geometry streaming after a RIGHT-arrow
keypress, checkpoint state advancing, and click-to-inspect printing the
variable name to the terminal.

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

UNSUPPORTED_GEOMETRY_SOURCE = """
from manim import *

class CustomCloud(PMobject):
    shader_folder = "true_dot"
    render_primitive = 0
    data_dtype = DotCloud.data_dtype

    def init_uniforms(self):
        super().init_uniforms()
        self.uniforms["glow_factor"] = 0.0
        self.uniforms["anti_alias_width"] = 2.0

    def init_points(self):
        self.set_points([[0, 0, 0]])

class UnsupportedDemo(Scene):
    def construct(self):
        self.add(CustomCloud())
        self.wait(.1)
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
            cls.proc.wait(timeout=5)
        cls._reader.join(timeout=5)
        cls.proc.stdout.close()
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


class StaleKeyTests(unittest.TestCase):
    """Animation-overlap input has an explicit bounded-intent policy.

    The drain only runs between animations, so every key event carries an
    arrival stamp. At settle, the latest queued arrow survives and older
    arrows are coalesced; stale non-navigation keys still die.
    """

    @staticmethod
    def make_viewer():
        from types import SimpleNamespace
        from maniml.web.viewer import WebViewer
        pressed = []
        viewer = SimpleNamespace(
            scene=SimpleNamespace(
                on_key_press=lambda s, m: pressed.append(s),
                on_key_release=lambda s, m: None,
            ),
            pressed_keys=set(), _keys_settled_at=0.0,
            _dirty=False, _has_undrawn_event=False,
            _map_key=WebViewer._map_key, _map_mods=WebViewer._map_mods,
        )
        return viewer, (lambda e: WebViewer._handle_event(viewer, e)), pressed

    @staticmethod
    def dispatch(events, *, advance_settle_on_press=False):
        from types import SimpleNamespace
        from maniml.web.viewer import WebViewer
        pressed = []
        holder = {}

        def on_press(symbol, mods):
            pressed.append(symbol)
            if advance_settle_on_press:
                holder["viewer"]._keys_settled_at = 200.0

        viewer = SimpleNamespace(
            scene=SimpleNamespace(
                on_key_press=on_press,
                on_key_release=lambda s, m: None,
            ),
            server=SimpleNamespace(pop_events=lambda: list(events)),
            pressed_keys=set(), _keys_settled_at=100.0,
            _coalesced_navigation_events=0,
            _dirty=False, _has_undrawn_event=False,
            _map_key=WebViewer._map_key, _map_mods=WebViewer._map_mods,
            _is_stale_navigation_press=lambda event:
                WebViewer._is_stale_navigation_press(viewer, event),
            _handle_event=lambda event: WebViewer._handle_event(viewer, event),
        )
        holder["viewer"] = viewer
        viewer._dispatch_events = lambda: WebViewer._dispatch_events(viewer)
        WebViewer.dispatch_events(viewer)
        return viewer, pressed

    def test_latest_stale_arrow_is_retained_and_older_arrows_coalesce(self):
        viewer, pressed = self.dispatch([
            {"type": "key", "action": "down", "key": "ArrowRight",
             "_received": 90.0},
            {"type": "key", "action": "down", "key": "ArrowLeft",
             "_received": 91.0},
            {"type": "key", "action": "down", "key": "ArrowUp",
             "_received": 92.0},
        ])

        self.assertEqual(pressed, [viewer._map_key("ArrowUp")])
        self.assertEqual(viewer._coalesced_navigation_events, 2)

    def test_settle_change_during_dispatch_does_not_reclassify_batch(self):
        viewer, pressed = self.dispatch([
            {"type": "key", "action": "down", "key": "ArrowRight",
             "_received": 101.0},
            {"type": "key", "action": "down", "key": "ArrowLeft",
             "_received": 102.0},
        ], advance_settle_on_press=True)

        self.assertEqual(pressed, [
            viewer._map_key("ArrowRight"), viewer._map_key("ArrowLeft")])
        self.assertEqual(viewer._coalesced_navigation_events, 0)

    def test_a_press_stamped_before_the_settle_dies(self):
        viewer, handle, pressed = self.make_viewer()
        viewer._keys_settled_at = 100.0
        handle({"type": "key", "action": "down",
                "key": "ArrowRight", "_received": 99.0})
        self.assertEqual(pressed, [], "a stale press fired after the settle")
        handle({"type": "key", "action": "down",
                "key": "ArrowRight", "_received": 101.0})
        self.assertEqual(len(pressed), 1, "a fresh press must still fire")

    def test_a_stale_release_still_clears_the_key(self):
        """Down before the animation, up during it: dropping the release
        would wedge pressed_keys with a key that is no longer held."""
        viewer, handle, pressed = self.make_viewer()
        handle({"type": "key", "action": "down",
                "key": "ArrowRight", "_received": 99.0})
        viewer._keys_settled_at = 100.0
        handle({"type": "key", "action": "up",
                "key": "ArrowRight", "_received": 99.5})
        self.assertEqual(viewer.pressed_keys, set())

    def test_an_unstamped_event_passes(self):
        """Events without an arrival stamp (tests, other frontends) keep
        the old behavior rather than being silently swallowed."""
        viewer, handle, pressed = self.make_viewer()
        viewer._keys_settled_at = 100.0
        handle({"type": "key", "action": "down", "key": "ArrowRight"})
        self.assertEqual(len(pressed), 1)


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
                    if (s.get("type") == "state" and s.get("present")
                            and s.get("presentation_ready")):
                        on_state = s
            self.assertIsNotNone(on_state, "present mode never engaged")
            self.assertEqual(on_state["current"], 0, "did not rewind to start")
            self.assertGreaterEqual(on_state["count"], 4,
                                    "checkpoints were not all pre-built")
            ws.send(json.dumps({"type": "present"}))   # toggle back off
            deadline = time.time() + 10
            off_state = None
            while time.time() < deadline and off_state is None:
                _, states = self._collect(ws, 2)
                off_state = next((
                    s for s in states
                    if s.get("type") == "state" and not s.get("present")
                ), None)
            self.assertIsNotNone(off_state, "present mode never disengaged")
            self.assertFalse(off_state.get("presentation_ready"))

    def test_present_bundle_serving_freshness_and_ranges(self):
        """media/<Scene>_present is mounted at /present/ with single-range
        support (video seeking), and the state reports whether the bundle
        matches the scene file as it is now."""
        import hashlib
        from urllib.request import Request, urlopen

        scene_file = os.path.join(self.tmpdir.name, self.FILENAME)
        with open(scene_file, "rb") as f:
            good_hash = hashlib.blake2b(f.read(), digest_size=16).hexdigest()
        media = os.path.join(self.tmpdir.name, "media")
        os.makedirs(media, exist_ok=True)
        with open(os.path.join(media, f"{self.SCENE}.mp4"), "wb") as f:
            f.write(b"0123456789abcdef")
        table = os.path.join(media, f"{self.SCENE}.pausepoints.json")
        meta = {"format": 1, "source": {"hash": good_hash}, "checkpoints": []}
        with open(table, "w") as f:
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

            # a table baked from different source reports stale
            meta["source"]["hash"] = "0" * 32
            with open(table, "w") as f:
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

        media = os.path.join(self.tmpdir.name, "media")
        os.makedirs(media, exist_ok=True)
        with open(os.path.join(media, f"{self.SCENE}.pausepoints.json"), "w") as f:
            json.dump({"format": 1, "checkpoints": []}, f)
        with open(os.path.join(media, f"{self.SCENE}.mp4"), "wb") as f:
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
            # On connect: checkpoint state, and nothing to look at until the
            # client says it has a renderer
            frames, states = self._collect(ws, 2)
            self.assertEqual(frames, [], "a picture was sent before any "
                             "client renderer existed to draw it")
            self.assertTrue(states, "no state message after connect")
            # The browser's WebGPU is up: one full geometry payload follows
            ws.send(json.dumps({"type": "mode", "geometry": True}))
            frames, more = self._collect(ws, 2)
            states += more
            self.assertTrue(frames, "no payload after the renderer came up")
            self.assertEqual(frames[0][0], 0x03, "first frame should be geometry")
            start_state = states[-1]
            # Nothing has run: the scene waits at checkpoint 0 until asked.
            self.assertEqual(start_state["count"], 1)
            self.assertEqual(start_state["current"], 0)
            self.assertTrue(start_state["future"], "no units left to run")
            self.assertEqual(start_state["file"], "web_scene.py")

            # RIGHT arrow: the next unit runs and streams geometry frames
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
            geometry = [f for f in frames if f[0] == 0x03]
            self.assertGreater(len(geometry), 3, "expected streamed geometry")
            self.assertEqual(set(f[0] for f in frames), {0x03},
                             "only geometry payloads travel this socket")
            # The move-close trails the landing state on the wire, so take
            # the last STATE message, not the last JSON message.
            landed = [s for s in states if s.get("type") == "state"]
            self.assertTrue(landed, "no state update after RIGHT")
            self.assertEqual(
                landed[-1]["current"], start_state["current"] + 1)

            # Click on the label: inspect prints its variable name
            ws.send(json.dumps({"type": "pointer", "action": "down",
                                "button": 0, "x": 0.5, "y": 0.75}))
            ws.send(json.dumps({"type": "pointer", "action": "up",
                                "button": 0, "x": 0.5, "y": 0.75}))
            self._wait_for(
                lambda: any("label" in l for l in self.stdout_lines),
                MESSAGE_TIMEOUT, "click-to-inspect output")

            # DOWN arrow: jump back; state should retreat
            ws.send(json.dumps(
                {"type": "key", "action": "down", "key": "ArrowDown"}))
            frames, states = self._collect(ws, 3)
            retreated = [s for s in states if s.get("type") == "state"]
            self.assertTrue(retreated, "no state update after DOWN")
            self.assertEqual(
                retreated[-1]["current"], start_state["current"])

    def test_geometry_snapshot(self):
        from maniml.web.geometry import parse_geometry_message
        with self._connect() as ws:
            self._collect(ws, 2)  # drain connect frame/state
            # Make the test self-contained: when run alone this executes the
            # first frontier unit; after test_full_loop it replays that
            # already-visited animation.
            ws.send(json.dumps(
                {"type": "key", "action": "down", "key": "ArrowRight"}))
            self._collect(ws, 3)
            ws.send(json.dumps(
                {"type": "mode", "geometry": True}))
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
                + (b["index_count"] * 4 if b.get("indexed") else 0)
                for b in header["batches"] if not b.get("cached"))
            total += sum(info["nbytes"] for info in header.get("texture_data", {}).values())
            self.assertEqual(total, len(vertex_bytes))

    def test_future_chips(self):
        with self._connect() as ws:
            def wait_for_state(predicate, description):
                deadline = time.monotonic() + MESSAGE_TIMEOUT
                observed = []
                while time.monotonic() < deadline:
                    try:
                        message = ws.recv(timeout=max(0.05, deadline - time.monotonic()))
                    except TimeoutError:
                        break
                    if isinstance(message, bytes):
                        continue
                    update = json.loads(message)
                    if update.get("type") != "state":
                        continue
                    observed.append(update)
                    if predicate(update):
                        return update
                self.fail(f"no {description}; observed states: {observed}")

            state = wait_for_state(lambda update: True, "state after connect")
            # Un-run play-units appear as future chips with source lines
            if not state["future"]:
                self.skipTest("scene already fully run by test ordering")
            target = state["future"][-1]
            self.assertIn("unit", target)
            self.assertIn("line", target)

            # Clicking a future chip runs the scene forward to that unit
            ws.send(json.dumps({"type": "chip_future", "unit": target["unit"]}))
            landed = wait_for_state(
                lambda update: update["count"] > state["count"]
                and update["current"] > state["current"] and not update["future"],
                "completed navigation after future-chip click")
            self.assertGreater(landed["count"], state["count"])
            self.assertGreater(landed["current"], state["current"])
            self.assertEqual(landed["future"], [])

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


class GeometryStreamingE2E(_ViewerHarness, unittest.TestCase):
    """Geometry streaming needs fresh frontier animations.

    Keep it in its own process: WebViewerE2E intentionally shares scene
    history across tests, and its future-chip test advances to the end.
    These checks should exercise first execution independently of replay.
    """

    def test_frontier_animations_stream_geometry(self):
        with self._connect() as ws:
            self._collect(ws, 2)

            ws.send(json.dumps({"type": "mode", "geometry": True}))
            ws.send(json.dumps(
                {"type": "key", "action": "down", "key": "ArrowRight"}))
            frames, _ = self._collect(ws, 4)
            geometry_frames = [f for f in frames if f[0] == 0x03]
            self.assertGreater(
                len(geometry_frames), 3,
                f"expected streamed geometry, got {len(geometry_frames)}")
            self.assertEqual(len(frames), len(geometry_frames),
                             "nothing but geometry travels this socket")

            # A client without a renderer (or one asleep behind recorded
            # playback) gets state, not pictures.
            ws.send(json.dumps({"type": "mode", "geometry": False}))
            self._collect(ws, 1)
            ws.send(json.dumps(
                {"type": "key", "action": "down", "key": "ArrowRight"}))
            frames, states = self._collect(ws, 4)
            self.assertEqual(frames, [], "frames sent with no renderer")
            self.assertTrue(any(s.get("type") == "state" for s in states),
                            "state must still flow without a renderer")


class RightReplayE2E(_ViewerHarness, unittest.TestCase):
    """RIGHT replays visited animations; UP/DOWN keep instant navigation."""

    SOURCE = """
from manim import *

class RightReplayDemo(Scene):
    def construct(self):
        dot = Dot()
        self.add(dot)
        self.play(dot.animate.shift(RIGHT), run_time=0.4)
        for _ in range(2):
            self.play(dot.animate.shift(UP), run_time=0.4)
"""
    SCENE = "RightReplayDemo"
    FILENAME = "right_replay_scene.py"

    def test_visited_right_streams_but_up_and_down_jump(self):
        logs = []

        def press(ws, key, current, count, seconds, animated=False):
            ws.send(json.dumps({"type": "key", "action": "down", "key": key}))
            ws.send(json.dumps({"type": "key", "action": "up", "key": key}))
            frames, messages = self._collect(ws, seconds, logs=logs)
            states = [m for m in messages if m.get("type") == "state"]
            self.assertTrue(states, f"no checkpoint state after {key}")
            self.assertEqual(states[-1]["current"], current)
            self.assertEqual(states[-1]["count"], count)
            starts = [m for m in messages
                      if m.get("type") == "move" and m["from"] is not None]
            if animated:
                geometry = [frame for frame in frames if frame[0] == 0x03]
                self.assertGreater(len(geometry), 3,
                                   "RIGHT restored an endpoint without streaming")
                self.assertTrue(starts, "RIGHT did not announce an animation")
                self.assertTrue(all(not m["back"] for m in starts))
            else:
                # A forced geometry snapshot is fine; a jump must not open
                # the rail's animation indicator.
                self.assertEqual(starts, [], f"{key} unexpectedly animated")
            return starts

        with self._connect() as ws:
            self._collect(ws, 0.5, logs=logs)
            ws.send(json.dumps({"type": "mode", "geometry": True}))
            self._collect(ws, 0.2, logs=logs)

            press(ws, "ArrowRight", 1, 2, 1, animated=True)
            press(ws, "ArrowLeft", 0, 2, 0.3)
            replay = press(ws, "ArrowRight", 1, 2, 1, animated=True)
            self.assertEqual([(m["from"], m["to"]) for m in replay], [(0, 1)])

            # First execution reaches both checkpoints within the loop.
            press(ws, "ArrowRight", 3, 4, 1.4, animated=True)
            press(ws, "ArrowLeft", 2, 4, 0.3)
            replay = press(ws, "ArrowRight", 3, 4, 1, animated=True)
            self.assertEqual([(m["from"], m["to"]) for m in replay], [(2, 3)],
                             "replaying inside a loop animated an earlier play")

            press(ws, "ArrowDown", 2, 4, 0.3)
            press(ws, "ArrowUp", 3, 4, 0.3)
            self.assertNotRegex(
                "\n".join(line["text"] for line in logs),
                r"(?i)\b(?:traceback|error|exception|ledgerstale)\b",
            )


class CurveRedrawStreamingE2E(_ViewerHarness, unittest.TestCase):
    """Dense, scalar-callback plots redraw through the live scene protocol."""

    SOURCE = """
from manim import *

class CurveRedrawDemo(Scene):
    def construct(self):
        axes = Axes(
            x_range=(0, 100, 100), y_range=(0, 100, 100),
            width=7, height=7,
        ).scale(0.7)
        alpha = ValueTracker(1)

        def bowed(x):
            a = alpha.get_value()
            return (100**a - x**a)**(1 / a)

        curves = always_redraw(lambda: VGroup(
            axes.plot(lambda x: 100 - x, x_range=(0, 100)),
            axes.plot(bowed, x_range=(0, 100, 0.1)),
        ))
        self.add(axes, curves)
        self.play(alpha.animate.set_value(1.5), run_time=0.5)
        self.play(alpha.animate.set_value(1.2), run_time=0.5)
"""
    SCENE = "CurveRedrawDemo"
    FILENAME = "curve_redraw_scene.py"

    def test_two_redraw_animations_stream_and_save_checkpoints(self):
        from maniml.web.geometry import parse_geometry_message

        with self._connect() as ws:
            logs = []
            _, messages = self._collect(ws, 0.5, logs=logs)
            initial = [m for m in messages if m.get("type") == "state"]
            self.assertTrue(initial, "no initial checkpoint state")
            self.assertEqual(initial[-1]["current"], 0)

            ws.send(json.dumps({"type": "mode", "geometry": True}))
            for checkpoint in (1, 2):
                ws.send(json.dumps(
                    {"type": "key", "action": "down", "key": "ArrowRight"}))
                ws.send(json.dumps(
                    {"type": "key", "action": "up", "key": "ArrowRight"}))
                frames, messages = self._collect(ws, 2, logs=logs)
                geometry = [frame for frame in frames if frame[0] == 0x03]
                self.assertGreater(
                    len(geometry), 3,
                    f"redraw animation {checkpoint} did not stream geometry")
                self.assertEqual(len(frames), len(geometry))
                headers = [parse_geometry_message(frame)[0] for frame in geometry]
                self.assertTrue(any(
                    sum(batch["num_verts"] for batch in header["batches"]) >= 2000
                    for header in headers
                ), "streamed frames did not contain the densely sampled curves")
                self.assertTrue(all(not header["unsupported"] for header in headers))
                landed = [m for m in messages if m.get("type") == "state"]
                self.assertTrue(landed, "redraw animation did not publish its checkpoint")
                self.assertEqual(landed[-1]["current"], checkpoint)
                self.assertEqual(landed[-1]["count"], checkpoint + 1)
            self.assertEqual(landed[-1]["future"], [])
            self.assertNotRegex(
                "\n".join(line["text"] for line in logs),
                r"(?i)\b(?:traceback|error|exception|ledgerstale)\b",
            )


class UnsupportedGeometryE2E(_ViewerHarness, unittest.TestCase):
    """Rejected frames remain explicit while navigation and recovery stay live."""

    SOURCE = UNSUPPORTED_GEOMETRY_SOURCE
    SCENE = "UnsupportedDemo"
    FILENAME = "unsupported_scene.py"

    def test_unsupported_frame_reports_error_and_valid_checkpoint_recovers(self):
        from maniml.web.geometry import parse_geometry_message

        with self._connect() as ws:
            self._collect(ws, .5)
            ws.send(json.dumps({"type": "mode", "geometry": True}))
            self._collect(ws, .3)
            ws.send(json.dumps({"type": "key", "action": "down", "key": "ArrowRight"}))
            ws.send(json.dumps({"type": "key", "action": "up", "key": "ArrowRight"}))
            frames, messages = self._collect(ws, 1)
            failures = [m["error"] for m in messages if m.get("type") == "render_error" and m.get("error")]
            self.assertTrue(failures, "no explicit error for unsupported scene")
            self.assertIn("CustomCloud", failures[-1]["message"])
            self.assertEqual(failures[-1]["renderer"], "triangles")
            self.assertFalse(frames, "rejected frame must not publish a partial picture")
            states = [m for m in messages if m.get("type") == "state"]
            self.assertTrue(states)
            self.assertIsNotNone(states[-1]["render_error"])
            self.assertIsNone(self.proc.poll(), "render error killed the viewer")
            # Going back to the valid empty checkpoint must clear the error and
            # produce a full frame, without restarting the scene or renderer.
            ws.send(json.dumps({"type": "key", "action": "down", "key": "ArrowLeft"}))
            ws.send(json.dumps({"type": "key", "action": "up", "key": "ArrowLeft"}))
            frames, messages = self._collect(ws, 1)
            self.assertTrue(frames, "valid checkpoint did not resume rendering")
            self.assertEqual(parse_geometry_message(frames[-1])[0]["unsupported"], [])
            self.assertTrue(any(m.get("type") == "render_error" and m.get("error") is None
                                for m in messages))
            states = [m for m in messages if m.get("type") == "state"]
            self.assertEqual(states[-1]["current"], 0)
            self.assertIsNone(states[-1]["render_error"])


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

    def test_live_browser_skips_native_before_connect_and_without_gpu(self):
        from types import SimpleNamespace
        from maniml.web.viewer import WebViewer

        writer = SimpleNamespace(write_to_movie=False, save_last_frame=False)
        viewer = SimpleNamespace(scene=SimpleNamespace(file_writer=writer))
        self.assertTrue(WebViewer.can_skip_native_capture(viewer))
        writer.write_to_movie = True
        self.assertFalse(WebViewer.can_skip_native_capture(viewer))
        writer.write_to_movie = False
        writer.save_last_frame = True
        self.assertFalse(WebViewer.can_skip_native_capture(viewer))
        viewer.scene = None
        self.assertFalse(WebViewer.can_skip_native_capture(viewer))


class ExportRoutingTests(unittest.TestCase):
    """Each export format runs its own CLI mode in its own subprocess.

    The checkpoint stills are the point of the split: one full-size PNG
    per checkpoint is far more disk than the movie beside it, so they are
    written only when their own button asks for them.
    """

    def _mode_for(self, export_format):
        import tempfile
        import threading
        from types import SimpleNamespace
        from unittest.mock import patch
        from maniml.web.viewer import WebViewer

        class Tiny:
            pass

        with tempfile.TemporaryDirectory() as tmp:
            source = os.path.join(tmp, "tiny_scene.py")
            with open(source, "w") as f:
                f.write("# scene\n")
            scene = Tiny()
            scene._scene_filepath = source
            viewer = SimpleNamespace(
                scene=scene,
                _export_lock=threading.Lock(),
                _export_process=None,
                server=SimpleNamespace(broadcast_json=lambda payload: None),
            )
            viewer._relay_export_progress = lambda *args: None
            viewer._finish_export = lambda *args: None
            with patch("subprocess.Popen") as popen:
                WebViewer._start_export(viewer, export_format)
            if not popen.called:
                return None
            return popen.call_args[0][0]

    def test_each_format_runs_its_own_mode(self):
        self.assertIn("--export-present", self._mode_for("video"))
        self.assertIn("--export", self._mode_for("web"))
        self.assertIn("--export-checkpoints", self._mode_for("checkpoints"))

    def test_the_video_export_writes_no_checkpoint_stills(self):
        self.assertNotIn("--export-checkpoints", self._mode_for("video"))

    def test_only_the_three_known_formats_reach_an_export(self):
        """The wire picks a format, never a command line."""
        from types import SimpleNamespace
        from maniml.web.viewer import WebViewer

        started = []
        viewer = SimpleNamespace(
            scene=object(),
            _dirty=True,
            _has_undrawn_event=True,
            _start_export=started.append,
        )
        for fmt in ("video", "web", "checkpoints", "--render", None):
            WebViewer._handle_event(viewer, {"type": "export", "format": fmt})
        self.assertEqual(started, ["video", "web", "checkpoints"])


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
            # The landing state must be on the wire BEFORE the close: the
            # client pends states while the move is open and lands the last
            # one when the close arrives. A close that outruns the landing
            # sends the ring back to the chip being left, which then
            # visibly hops dot-to-dot instead of the dash handing off to
            # the new pausepoint's dot.
            close_at = max(i for i, m in enumerate(states)
                           if m.get("type") == "move" and m["from"] is None)
            landed_at = [i for i, m in enumerate(states)
                         if m.get("type") == "state" and m.get("current", 0) > 0]
            self.assertTrue(landed_at, "no landing state seen")
            self.assertLess(min(landed_at), close_at,
                            "the move closed before the landing state")

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


class RendererSwitchE2E(_ViewerHarness, unittest.TestCase):
    SOURCE = """
from manim import *
class RendererDemo(Scene):
    def setup(self):
        self.add(Square(fill_opacity=1, stroke_width=2))
    def construct(self):
        self.wait(.1)
"""
    SCENE = "RendererDemo"

    def test_rejoining_tab_adopts_server_selection_even_with_geometry_off(self):
        from maniml.web.geometry import parse_geometry_message

        def receive(ws, predicate):
            deadline = time.monotonic() + MESSAGE_TIMEOUT
            while time.monotonic() < deadline:
                try:
                    message = ws.recv(timeout=max(.01, deadline - time.monotonic()))
                except TimeoutError:
                    break
                if isinstance(message, bytes):
                    value, _ = parse_geometry_message(message)
                    value = {**value, "type": "geometry"}
                else:
                    value = json.loads(message)
                if predicate(value):
                    return value
            self.fail("no matching renderer handshake message")

        def state(ws, mode):
            result = receive(ws, lambda message: message.get("type") == "state"
                             and message.get("renderer") == mode)
            self.assertEqual(result["current"], 0)
            self.assertEqual(result["scene"], "RendererDemo")
            return result

        def ready_frame(ws, mode):
            # This is readiness, not a renderer selection. A reloaded page
            # must receive authoritative state before sending it.
            ws.send(json.dumps({"type": "mode", "geometry": True}))
            frame = receive(ws, lambda message: message.get("type") == "geometry"
                            and message.get("renderer") == mode)
            self.assertTrue(frame["batches"])
            self.assertFalse(any(batch.get("cached") for batch in frame["batches"]))
            return [batch["hash"] for batch in frame["batches"]]

        with self._connect() as first:
            first.send(json.dumps({"type": "mode", "geometry": False, "renderer": "winding",
                                   "renderer_origin": "first-tab", "renderer_request": 1}))
            receive(first, lambda message: message.get("type") == "renderer"
                    and message.get("origin") == "first-tab" and message.get("request") == 1)
            state(first, "winding")
            with self._connect() as reloaded:
                # The server emits state without waiting for geometry=True.
                state(reloaded, "winding")
                before = ready_frame(reloaded, "winding")
                state(first, "winding")
                first.send(json.dumps({"type": "mode", "geometry": True, "renderer": "winding",
                                       "renderer_origin": "first-tab", "renderer_request": 2}))
                same_mode = receive(first, lambda message: message.get("type") == "renderer"
                                    and message.get("request") == 2)
                self.assertEqual(same_mode["renderer"], "winding")
            with self._connect() as reconnected:
                state(reconnected, "winding")
                self.assertEqual(ready_frame(reconnected, "winding"), before)
                first.send(json.dumps({"type": "mode", "geometry": False, "renderer": "triangles"}))
                state(first, "triangles")
                state(reconnected, "triangles")
                ready_frame(reconnected, "triangles")

    def test_renderer_switch_returns_full_geometry_at_the_same_checkpoint(self):
        from maniml.web.geometry import parse_geometry_message

        with self._connect() as ws:
            self._collect(ws, .2)
            for mode in ("triangles", "winding", "triangles"):
                ws.send(json.dumps({"type": "mode", "geometry": True, "renderer": mode}))
                header, state = None, None
                deadline = time.monotonic() + MESSAGE_TIMEOUT
                while time.monotonic() < deadline and (header is None or state is None):
                    try:
                        message = ws.recv(timeout=max(.01, deadline - time.monotonic()))
                    except TimeoutError:
                        break
                    if isinstance(message, bytes):
                        candidate, _ = parse_geometry_message(message)
                        if candidate["renderer"] == mode and header is None:
                            header = candidate
                    else:
                        candidate = json.loads(message)
                        if candidate.get("type") == "state" and candidate.get("renderer") == mode:
                            state = candidate
                self.assertIsNotNone(header, "no frame for " + mode)
                self.assertTrue(header["batches"], "fixture must draw a shape")
                self.assertFalse(any(batch.get("cached") for batch in header["batches"]))
                self.assertIsNotNone(state, "no state for " + mode)
                self.assertEqual(state["current"], 0)
                self.assertEqual(state["scene"], "RendererDemo")


if __name__ == "__main__":
    unittest.main()

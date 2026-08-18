"""Contract tests for the pages the engine serves.

These files ship inside the package and are served by the same process that
runs the scenes, so there is no deployment step and no version negotiation —
which is exactly what these tests are here to keep true.
"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path
from types import SimpleNamespace

from maniml.web import assets

STATIC = Path(__file__).resolve().parent.parent / "maniml" / "web" / "static"


class LocalOnlyTests(unittest.TestCase):
    def test_no_page_reaches_for_a_public_origin_or_a_native_bridge(self):
        """The whole class of bug that came with hosting the UI elsewhere:
        custom URL schemes, a separate deploy, and a protocol to negotiate
        between two independently-versioned halves."""
        for name in ("app.html", "viewer.html"):
            page = (STATIC / name).read_text()
            for forbidden in (
                "maniml://",              # native launcher bridge
                "tayweid.github.io",      # hosted origins
                "maniml.tayweid.io",
                "WEB_PROTOCOL_VERSION",   # engine/frontend skew negotiation
                "launchQueue",            # see test_no_file_handlers_yet
            ):
                self.assertNotIn(forbidden, page, f"{name}: {forbidden}")

    def test_the_landing_page_is_not_a_file_browser(self):
        """It offers one action and the files you have opened before. Listing
        every scene class under the launch directory was noise in front of the
        one file you actually wanted."""
        page = (STATIC / "app.html").read_text()
        self.assertIn('id="open-hero"', page)
        self.assertIn('id="recents"', page)
        # The directory listing and its per-scene chips are gone.
        for absent in ("fileCard", 'id="files"', 'id="picked"', "No scene files"):
            self.assertNotIn(absent, page, absent)

    def test_the_installable_app_is_the_local_one(self):
        """The manifest and worker are served by the engine, so the app you
        install is the one that can run a scene. The hosted preview must have
        neither — tests/check_site.py holds that end."""
        manifest = json.loads((STATIC / "manifest.webmanifest").read_text())
        self.assertEqual(manifest["scope"], "/")
        self.assertEqual(manifest["start_url"], "/")
        self.assertEqual(manifest["display"], "standalone")
        self.assertTrue((STATIC / "sw.js").is_file())
        self.assertIn('rel="manifest"', (STATIC / "app.html").read_text())
        # index.html was the hosted build's redirect stub; the engine serves
        # app.html at its root directly.
        self.assertFalse((STATIC / "index.html").exists())

    def test_no_file_handlers_yet(self):
        """A `.py` double-click would arrive through launchQueue as a browser
        file handle, which has no filesystem path — and the watcher and the
        scene's own __file__-relative imports both need a real one. That is
        why the engine shows the native dialog instead. Registering handlers
        before that is solved would claim every .py on the machine and then
        fail to open them."""
        manifest = json.loads((STATIC / "manifest.webmanifest").read_text())
        self.assertNotIn("file_handlers", manifest)

    def test_the_worker_is_versioned_by_the_engine_that_serves_it(self):
        """A browser installs a new worker only when the bytes differ, and the
        cache is keyed the same way, so an upgraded engine cannot be handed a
        shell its predecessor cached."""
        worker = (STATIC / "sw.js").read_text()
        self.assertIn(assets.VERSION_PLACEHOLDER, worker)
        self.assertIn(f"maniml-shell-${{VERSION}}", worker)
        request = SimpleNamespace(method="GET", path="/sw.js", headers={})
        served = assets.static_response(request, index="app.html").body.decode()
        self.assertNotIn(assets.VERSION_PLACEHOLDER, served)
        self.assertIn(assets._package_version(), served)

    def test_app_page_talks_only_to_its_own_origin(self):
        page = (STATIC / "app.html").read_text()
        # Same origin as the page: no port to configure, nothing to be told
        # at launch, and connect-src 'self' actually constrains it.
        self.assertIn("const CONTROL_URL = `ws://${location.host}/`;", page)
        self.assertNotIn("127.0.0.1", page)
        self.assertIn('request("choose")', page)
        self.assertIn('request("open"', page)
        self.assertIn('request("recents")', page)
        # Nothing to carry, nothing to store, nothing to lose: the engine
        # accepts the socket because of where the page came from.
        for absent in ("token", "sessionStorage", "localStorage"):
            self.assertNotIn(absent, page, absent)


class ViewerTests(unittest.TestCase):
    def test_viewer_carries_no_credential(self):
        """No secret reaches the page, so none can be stored or lost. Browser
        storage itself is fine — the console toggle is remembered per tab —
        the point is that nothing in there is an authorization."""
        viewer = (STATIC / "viewer.html").read_text()
        for absent in ("token", "localStorage"):
            self.assertNotIn(absent, viewer, absent)
        stored_keys = re.findall(r'sessionStorage\.\w+\((\w+)', viewer)
        self.assertEqual(set(stored_keys), {"CONSOLE_KEY"}, stored_keys)

    def test_viewer_reaches_its_engine_at_its_own_origin(self):
        """Through the app a scene is /scene/<id> on the app's port; run on
        its own, a scene process answers at the root. Never another port."""
        viewer = (STATIC / "viewer.html").read_text()
        self.assertIn('"ws://" + location.host', viewer)
        self.assertIn('"/scene/" + encodeURIComponent(sceneParam)', viewer)

    def test_viewer_keeps_its_transport_seam_explicit(self):
        """The client renderers are the basis of any future browser-only
        build, so the WebSocket must stay a replaceable transport rather than
        leak through the rest of the viewer."""
        viewer = (STATIC / "viewer.html").read_text()
        self.assertIn('const wsUrl = "ws://" + location.host', viewer)
        self.assertNotIn("127.0.0.1", viewer)
        self.assertIn("function send(obj)", viewer)
        self.assertIn("Pyodide", viewer)

    def test_the_console_only_ever_opens_because_you_asked(self):
        """Stepping a scene prints on every arrow key, so a panel that opened
        on output would open constantly — and never at a worse moment than
        mid-presentation. Nothing may open it but the toggle."""
        viewer = (STATIC / "viewer.html").read_text()
        self.assertIn('id="console-toggle"', viewer)
        self.assertIn("body.console #console { display: flex; }", viewer)
        # Presenting gets the whole window back.
        self.assertIn("body.fullscreen #console { display: none; }", viewer)
        # setConsole(true) is reachable only from the toggle, the shortcut, and
        # the remembered per-tab preference — never from a log arriving.
        opens = viewer.count("setConsole(true)")
        self.assertEqual(opens, 1, "an extra path opens the console")
        appended = viewer.index("function appendLog")
        block = viewer[appended:viewer.index("consoleToggle.onclick", appended)]
        self.assertNotIn("setConsole", block, "appendLog must not open the panel")

    def test_full_screen_never_leaks_its_key_to_the_scene(self):
        """Every single-character key is forwarded to the engine, so the
        shortcut is claimed inside the forwarder itself — the one place keys
        reach the scene — rather than by a second listener that might not win."""
        viewer = (STATIC / "viewer.html").read_text()
        self.assertIn("requestFullscreen", viewer)
        # Scope to the forwarder specifically: the toolbar's pulseKey() also
        # sends key events, and the scene menu registers its own earlier
        # keydown listener — neither is the path a real keypress takes.
        start = viewer.index("// -- Keyboard --")
        handler = viewer[start:viewer.index('document.addEventListener("keyup"', start)]
        self.assertLess(
            handler.index("toggleFullscreen();"),
            handler.index('send({ type: "key"'),
            "the key is forwarded before it is claimed")
        # A claimed keydown must not leave a dangling keyup for the engine.
        self.assertIn("claimed.delete(e.key)", viewer)

    def test_full_screen_hides_the_chrome_without_leaving_it_clickable(self):
        viewer = (STATIC / "viewer.html").read_text()
        self.assertIn("body.fullscreen #stage { padding: 0; }", viewer)
        # opacity alone would leave invisible pods eating canvas clicks.
        self.assertIn("opacity: 0; visibility: hidden;", viewer)
        self.assertIn("body.fullscreen.chrome #toolbar", viewer)
        self.assertIn("body.fullscreen.chrome #timeline-shell", viewer)

    def test_viewer_controls_are_present(self):
        viewer = (STATIC / "viewer.html").read_text()
        for element in (
            'id="open-file"', 'id="file-menu"', 'id="previous"', 'id="next"',
            'id="export-video"', 'id="export-web"', 'id="export-frame"',
            'id="connection-overlay"', 'id="retry-connection"',
            'aria-label="Scene pausepoints"',
        ):
            self.assertIn(element, viewer, element)

    def test_scene_picker_switches_within_a_file(self):
        viewer = (STATIC / "viewer.html").read_text()
        self.assertIn('id="scene-menu"', viewer)
        self.assertIn('class="scene-picker"', viewer)
        self.assertIn('{ type: "switch_scene", scene: name }', viewer)
        self.assertIn("sceneButton.disabled = sceneNames.length < 2;", viewer)

    def test_open_returns_to_the_app_rather_than_a_native_bridge(self):
        viewer = (STATIC / "viewer.html").read_text()
        self.assertIn("window.location = appUrl;", viewer)

    def test_live_viewer_uses_webgpu_first_with_visible_pixel_fallback(self):
        viewer = (STATIC / "viewer.html").read_text()
        self.assertIn('const DEFAULT_RENDERER = "gpu";', viewer)
        self.assertIn("let renderer = DEFAULT_RENDERER;", viewer)
        self.assertIn("void selectRenderer(renderer, segment);", viewer)
        self.assertIn('renderer = "pixel";', viewer)
        self.assertIn("WebGPU unavailable; using Pixel:", viewer)

    def test_client_render_assets_are_intact(self):
        """Kept deliberately: these are what a zero-install browser build
        would render with."""
        for name in ("gl.js", "webgpu.js", "player.html", "player.js"):
            self.assertTrue((STATIC / name).is_file(), name)
        self.assertTrue(list((STATIC / "glsl").glob("*.glsl")))
        self.assertTrue(list((STATIC / "wgsl").glob("*.wgsl")))


if __name__ == "__main__":
    unittest.main()

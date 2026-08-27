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
        # The toggle is a fixed corner pill above the panel it opens — the way
        # in and the way out are the same spot — and it sits outside the
        # toolbar so it cannot recede with the chrome in full screen.
        self.assertIn("#console-toggle {\n    position: fixed; top: 14px; right: 12px;", viewer)
        self.assertIn("body.console #console { display: flex; }", viewer)
        # In full screen it rides with the rest of the chrome rather than
        # being suppressed: presenting is when a scene's own output matters
        # most, and it recedes with the toolbar when the pointer settles.
        self.assertIn("body.fullscreen.chrome #console", viewer)
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
        self.assertIn("body.fullscreen.chrome #navbar", viewer)

    def test_the_position_slug_and_stale_dot_are_styled(self):
        """The word tag ("Pausepoint") is gone from the transport pod, so the
        total half of the slug is pinned on its own color; the stale badge
        became a corner dot on the Present button."""
        viewer = (STATIC / "viewer.html").read_text()
        self.assertIn('#position-total { color: var(--dim); }', viewer)
        self.assertIn('#present.stale::after', viewer)

    def test_viewer_controls_are_present(self):
        viewer = (STATIC / "viewer.html").read_text()
        for element in (
            'id="open-file"', 'id="file-menu"', 'id="previous"', 'id="next"',
            'id="export-video"',
            'id="connection-overlay"', 'id="retry-connection"',
            'aria-label="Scene pausepoints"',
        ):
            self.assertIn(element, viewer, element)

    def test_presenter_controls_share_one_bar_with_the_rail(self):
        """Everything touched while showing a scene is on the bottom bar, and
        the rail it moves along is part of the same run of pods."""
        viewer = (STATIC / "viewer.html").read_text()
        navbar = viewer[viewer.index('<div id="navbar"'):viewer.index("<script src=")]
        for control in ('id="previous"', 'id="next"', 'id="position"',
                        'id="rail"', 'id="fullscreen"'):
            self.assertIn(control, navbar, control)
        # The top bar keeps the file and the tools, and nothing else.
        toolbar = viewer[viewer.index('<header id="toolbar"'):viewer.index('<aside id="console"')]
        for moved in ('id="previous"', 'id="next"', 'id="fullscreen"'):
            self.assertNotIn(moved, toolbar, moved)

    def test_chrome_is_a_run_of_pods(self):
        """The seams and stadium ends come from shell.css, so both bars and
        the landing page's header stay one visual family."""
        shell = (STATIC / "shell.css").read_text()
        self.assertIn(".pod-run > .pod:first-child", shell)
        self.assertIn(".pod-run > .pod:last-child", shell)
        for name in ("viewer.html", "app.html"):
            self.assertIn('class="pod-run"', (STATIC / name).read_text(), name)

    def test_the_rail_can_light_a_single_stretch(self):
        """A link between two chips is a real element precisely so one of
        them can light while its animation plays; a line drawn behind the
        whole rail could only ever be lit end to end."""
        viewer = (STATIC / "viewer.html").read_text()
        self.assertIn("function makeLink(", (STATIC / "rail.js").read_text())
        self.assertIn(".link.lit .fill", viewer)
        self.assertIn(".link.lit.back .fill", viewer)
        # The ring must leave the chip being departed, or the rail keeps
        # claiming a position it is on its way out of — the lag that made
        # stepping feel like a jump.
        self.assertIn("body.moving .chip.current", viewer)

    def test_a_move_says_which_stretch_and_not_how_far(self):
        """Progress through an animation is on screen at full size already,
        and any claim would have to hold through reverse morphs and
        fast-forwards too."""
        viewer = (STATIC / "viewer.html").read_text()
        self.assertIn('data.type === "move"', viewer)
        rail = (STATIC / "rail.js").read_text()
        move = rail[rail.index("function handleMove("):]
        for absent in ("alpha", "progress", "run_time"):
            self.assertNotIn(absent, move, absent)
        # A short play must stay lit long enough to be seen.
        self.assertIn("MIN_LIT_MS", rail)

    def test_an_unknowable_pausepoint_count_is_drawn_as_one(self):
        """A loop or a branch does not have a chip per play until it runs, so
        the rail draws a stack rather than implying a count it lacks."""
        viewer = (STATIC / "viewer.html").read_text()
        self.assertIn(".chip.many", viewer)
        self.assertIn("group.many", (STATIC / "rail.js").read_text())

    def test_a_statement_keeps_one_chip_after_it_runs(self):
        """A chip is a source statement, not a checkpoint: a loop that turns
        into four checkpoints must not become four chips, or the rail swells
        as you step through it and every chip you were aiming at moves."""
        rail = (STATIC / "rail.js").read_text()
        self.assertIn("function buildGroups(", rail)
        # Consecutive checkpoints from the same unit merge into one chip.
        self.assertIn("last.unit === unit", rail)
        # And the move can still find its destination while that chip's next
        # checkpoint does not exist yet.
        self.assertIn("function destinationGroup(", rail)

    def test_the_two_pages_share_their_controls(self):
        """The landing page is the same bar as the viewer's, so the slug and
        the icon button are defined once rather than resembling each other."""
        shell = (STATIC / "shell.css").read_text()
        for shared in (".document-slug", ".slug-separator", ".icon-button",
                       ".control-label"):
            self.assertIn(shared, shell, shared)
        app = (STATIC / "app.html").read_text()
        self.assertIn('class="document-slug"', app)
        self.assertIn('id="openbtn" class="icon-button"', app)

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
        self.assertIn('data.type === "renderer_fallback"', viewer)
        self.assertIn("Using Pixel for this scene.", viewer)
        self.assertIn("dataset.rendererBackend", viewer)
        self.assertIn("dataset.rendererAdapter", viewer)
        webgpu = (STATIC / "webgpu.js").read_text()
        self.assertIn('backend: "webgpu"', webgpu)
        self.assertIn("adapterInfo", webgpu)

    def test_client_render_assets_are_intact(self):
        """Kept deliberately: these are what a zero-install browser build
        would render with."""
        for name in ("gl.js", "webgpu.js", "player.html", "player.js"):
            self.assertTrue((STATIC / name).is_file(), name)
        self.assertTrue(list((STATIC / "glsl").glob("*.glsl")))
        self.assertTrue(list((STATIC / "wgsl").glob("*.wgsl")))

    def test_presentation_playback_is_wired(self):
        """Present-from-video: the standalone presenter ships whole, and
        the viewer's playback branch claims its keys before anything is
        forwarded to the engine."""
        for name in ("presentation.js", "rail.js"):
            self.assertTrue((STATIC / name).is_file(), name)
        viewer = (STATIC / "viewer.html").read_text()
        self.assertIn('<script src="presentation.js"></script>', viewer)
        self.assertIn('<script src="rail.js"></script>', viewer)
        self.assertIn('stageSource === "playback"', viewer)
        # the playback key branch claims-and-returns BEFORE the forwarder
        keyboard = viewer[viewer.index("// -- Keyboard --"):]
        playback_claim = keyboard.index('stageSource === "playback"')
        forward = keyboard.index('send({ type: "key"')
        self.assertLess(playback_claim, forward,
                        "playback must intercept keys before the engine")
        # The presentation cache stays exactly the rendered movie plus
        # its pausepoints table. The standalone page exists again as a
        # separate artifact — the `--export-present` student bundle —
        # copied into media/<Scene>_present/ as index.html, never part
        # of the cache the viewer plays.
        present = (STATIC / "present.html").read_text()
        self.assertIn('<script src="presentation.js"></script>', present)
        self.assertIn('<script src="rail.js"></script>', present)
        self.assertIn('<script src="present_meta.js"></script>', present)
        self.assertIn('src="scene.mp4"', present)
        # The bundle page carries the viewer's presenter bar: the same
        # rail library and markup, with the pod/rail styles copied in —
        # never linked, so the folder stays self-contained
        self.assertIn('id="rail"', present)
        self.assertIn("ManimlRail.create", present)
        self.assertNotIn("shell.css", present)
        self.assertNotIn("WebSocket", present)


if __name__ == "__main__":
    unittest.main()

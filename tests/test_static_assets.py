"""Contract tests for the pages the engine serves.

These files ship inside the package and are served by the same process that
runs the scenes, so there is no deployment step and no version negotiation —
which is exactly what these tests are here to keep true.
"""

from __future__ import annotations

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
                "launchQueue",            # OS file delivery: the shell hands ?open=<path> instead
            ):
                self.assertNotIn(forbidden, page, f"{name}: {forbidden}")

    def test_the_landing_page_opens_the_document_it_was_given(self):
        """A Finder double-click (through the Claerbout shell) or an Open
        panel arrives as ?open=<path>; the page opens it once the engine is
        there, and the engine, not the page, decides whether the path may
        open."""
        page = (STATIC / "app.html").read_text()
        self.assertIn('.get("open")', page)
        self.assertIn("openRequested()", page)

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

    def test_the_page_is_not_installable(self):
        """Until 2026-10-01 a manifest, an Install button and a caching
        worker made http://localhost:8685 an installable app. ManimLive.app
        on the Claerbout shell is the installed app now, with a window, an
        icon, a port and an engine lifetime of its own, so the page offers
        nothing a browser could install. The hosted preview never could —
        tests/check_site.py holds that end."""
        self.assertFalse((STATIC / "manifest.webmanifest").exists())
        page = (STATIC / "app.html").read_text()
        for absent in ('rel="manifest"', "installbtn", "beforeinstallprompt",
                       "appinstalled", "serviceWorker"):
            self.assertNotIn(absent, page, absent)
        # index.html was the hosted build's redirect stub; the engine serves
        # app.html at its root directly.
        self.assertFalse((STATIC / "index.html").exists())

    def test_the_worker_is_a_kill_switch(self):
        """A browser that installed the old worker keeps running it until a
        worker at the same URL retires it, so sw.js must keep existing, be
        served as before, and unregister its predecessor rather than serve
        anything (the shape of site/sw.js)."""
        worker = (STATIC / "sw.js").read_text()
        self.assertIn("registration.unregister()", worker)
        self.assertIn("caches.delete(", worker)
        self.assertIn("client.navigate(client.url)", worker)
        for serving in ('addEventListener("fetch"', "addEventListener('fetch'",
                        "onfetch", "respondWith", assets.VERSION_PLACEHOLDER):
            self.assertNotIn(serving, worker, serving)
        request = SimpleNamespace(method="GET", path="/sw.js", headers={})
        served = assets.static_response(request, index="app.html")
        self.assertEqual(served.status_code, 200)
        self.assertIn("javascript", served.headers["Content-Type"])
        self.assertEqual(served.body.decode(), worker)

    def test_the_page_says_what_the_engine_serves(self):
        """An install replaces files without restarting processes, so the
        page is stamped with the version of the engine that served it."""
        page = (STATIC / "app.html").read_text()
        self.assertIn(f'<meta name="maniml" content="{assets.VERSION_PLACEHOLDER}">', page)
        request = SimpleNamespace(method="GET", path="/", headers={})
        served = assets.static_response(request, index="app.html").body.decode()
        self.assertNotIn(assets.VERSION_PLACEHOLDER, served)
        self.assertIn(f'<meta name="maniml" content="{assets._package_version()}">', served)

    def test_app_page_talks_only_to_its_own_origin(self):
        page = (STATIC / "app.html").read_text()
        # Same origin as the page: no port to configure, nothing to be told
        # at launch, and connect-src 'self' actually constrains it.
        self.assertIn("const CONTROL_URL = `ws://${location.host}/`;", page)
        self.assertNotIn("127.0.0.1", page)
        self.assertIn('request("choose")', page)
        # An open and an install both go through startScene, one request each.
        self.assertIn('startScene("open"', page)
        self.assertIn('startScene("install"', page)
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
        """The client renderer is the basis of any future browser-only
        build, so the WebSocket must stay a replaceable transport rather than
        leak through the rest of the viewer."""
        viewer = (STATIC / "viewer.html").read_text()
        self.assertIn('const wsUrl = "ws://" + location.host', viewer)
        self.assertNotIn("127.0.0.1", viewer)
        self.assertIn("function send(obj)", viewer)
        self.assertIn("Pyodide", viewer)

    def test_the_console_opens_because_you_asked_or_the_scene_raised(self):
        """Stepping a scene prints on every arrow key, so a panel that opened
        on output would open constantly. Nothing opens it but the toggle
        and an error: the engine's state says the last unit raised (or the
        file did not load), the toggle shows a red dot with the error in
        its title, and the console opens once for it (Taylor, 2026-10-04)
        — never mid-presentation: not in present mode, recorded playback
        or full screen, where the dot alone says."""
        viewer = (STATIC / "viewer.html").read_text()
        self.assertIn('id="console-toggle"', viewer)
        # The toggle is the bar's last tile, fixed over the corner its panel
        # opens under — the way in and the way out are the same spot — and
        # it sits outside the bar so it stays in full screen, where the bar
        # never shows.
        self.assertIn("#console-toggle {\n    position: fixed; top: calc((var(--topbar) - 32px) / 2); "
                      "right: var(--edge);", viewer)
        toolbar = viewer[viewer.index('<header id="toolbar"'):viewer.index("</header>")]
        self.assertNotIn('id="console-toggle"', toolbar)
        self.assertIn("body.console #console { display: flex; opacity: 1; transform: none; }", viewer)
        self.assertIn("@starting-style {", viewer)
        # Opened, the panel stays in full screen rather than receding with
        # the presenter's bar: a panel you asked for must not vanish.
        self.assertIn("body.fullscreen #console { top: 56px; right: 12px; bottom: 52px; }", viewer)
        self.assertNotIn("body.fullscreen.chrome #console", viewer)
        # setConsole(true) is reachable from the toggle, the shortcut, the
        # remembered per-tab preference and a new error — never from a log
        # arriving.
        opens = viewer.count("setConsole(true)")
        self.assertEqual(opens, 2, "an extra path opens the console")
        error = viewer[viewer.index("function setSceneError"):viewer.index("function setRenderError")]
        self.assertIn("setConsole(true)", error)
        for guard in ("arrived", '!document.body.classList.contains("console")',
                      "!document.fullscreenElement", 'stageSource !== "playback"',
                      "lastLiveState.present"):
            self.assertIn(guard, error, guard)
        self.assertIn("body.scene-error #console-toggle::after {", viewer)
        self.assertIn("setSceneError(data.unit_error || data.load_error || null);", viewer)
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

    def test_full_screen_shows_the_rail_and_the_toggle_and_never_the_bar(self):
        """In full screen only the presenter's bar (receding, back when the
        pointer nears an edge) and the console's toggle are there; the bar
        across the top never shows (Taylor, 2026-10-04)."""
        viewer = (STATIC / "viewer.html").read_text()
        self.assertIn("body.fullscreen #stage-area { inset: 0; background: #000; }", viewer)
        self.assertIn("body.fullscreen #toolbar { display: none; }", viewer)
        self.assertNotIn("body.fullscreen.chrome #toolbar", viewer)
        # opacity alone would leave invisible pods eating canvas clicks.
        self.assertIn("opacity: 0; visibility: hidden; transform: translateY(14px);", viewer)
        self.assertIn("body.fullscreen.chrome #navbar { opacity: 1; visibility: visible; transform: none; }",
                      viewer)
        self.assertIn("top: 12px; right: 12px; background: var(--glass);", viewer)

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
            'id="export-video"', 'id="export-checkpoints"',
            'id="connection-overlay"', 'id="retry-connection"',
            'aria-label="Scene pausepoints"',
        ):
            self.assertIn(element, viewer, element)

    def test_presenter_controls_share_one_bar_with_the_rail(self):
        """Everything touched while showing a scene is on the bottom bar, and
        the rail it moves along is part of the same run of pods."""
        viewer = (STATIC / "viewer.html").read_text()
        navbar = viewer[viewer.index('<div id="navbar"'):viewer.index("<script src=")]
        for control in ('id="start"', 'id="previous"', 'id="next"', 'id="position"',
                        'id="rail"', 'id="fullscreen"'):
            self.assertIn(control, navbar, control)
        # Start is the transport pod's first control, before Back.
        self.assertLess(navbar.index('id="start"'), navbar.index('id="previous"'))
        # The top bar keeps the file and the tools, and nothing else.
        toolbar = viewer[viewer.index('<header id="toolbar"'):viewer.index('<aside id="console"')]
        for moved in ('id="start"', 'id="previous"', 'id="next"', 'id="fullscreen"'):
            self.assertNotIn(moved, toolbar, moved)

    def test_home_reaches_the_engine_live_and_the_recording_in_playback(self):
        """Home is the Start control's key. Live it is forwarded to the
        engine like the arrows (the engine's own stale-key coalescing and
        loop-hold guard then apply); in playback the page claims it and
        seeks the recording to its first pausepoint, so no press leaks to
        the engine behind a playing video. The student bundle's page has
        the same control and key."""
        viewer = (STATIC / "viewer.html").read_text()
        keyboard = viewer[viewer.index("// -- Keyboard --"):]
        self.assertIn('"Home"', keyboard[:keyboard.index("const claimed")],
                      "Home is not a forwarded key")
        playback = keyboard[keyboard.index('stageSource === "playback"'):
                            keyboard.index('send({ type: "key"')]
        self.assertIn('e.key === "Home") ManimlPresentation.seekCheckpoint(0)', playback)
        rail = (STATIC / "rail.js").read_text()
        self.assertIn('get("start").disabled = current <= 0;', rail)
        present = (STATIC / "present.html").read_text()
        self.assertIn('id="start"', present)
        self.assertIn('document.getElementById("start").onclick', present)

    def test_the_presenters_bar_is_a_run_of_pods(self):
        """The seams and stadium ends come from shell.css. Since the frame
        (2026-10-02) the presenter's bar is the one run of pods: the bar at
        the top is the frame's, as Knuth's and Plass's are."""
        shell = (STATIC / "shell.css").read_text()
        self.assertIn(".pod-run > .pod:first-child", shell)
        self.assertIn(".pod-run > .pod:last-child", shell)
        viewer = (STATIC / "viewer.html").read_text()
        self.assertIn('<div id="navbar" class="pod-run"', viewer)
        self.assertNotIn('<header id="toolbar" class="pod-run"', viewer)

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
        self.assertIn("body.moving #rail .chip.current", viewer)

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
        """The landing page is the same bar as the viewer's, so the bar, the
        pill, the slug, the tiles and the menus are defined once (shell.css)
        and behave once (bar.js) rather than resembling each other."""
        shell = (STATIC / "shell.css").read_text()
        for shared in ("#toolbar {", ".doc-pod {", ".document-slug {", ".doc-mark",
                       ".icon-button", ".control-label", ".tb-end {", ".bar-pill {",
                       ".bar-menu {", ".bar-menu-item {"):
            self.assertIn(shared, shell, shared)
        for name in ("viewer.html", "app.html"):
            page = (STATIC / name).read_text()
            for control in ('<header id="toolbar"', 'id="file-menu" class="icon-button"',
                            'class="bar-menu"', 'class="doc-pod"', 'class="document-slug"',
                            'class="tb-end"', 'id="updatebtn" class="icon-button"',
                            '<script src="bar.js"></script>', "ManimlBar.menu(",
                            "ManimlBar.updates("):
                self.assertIn(control, page, f"{name}: {control}")
            # The update's handling is bar.js's alone now.
            self.assertNotIn('shell.request({ type: "update"', page, name)
        app = (STATIC / "app.html").read_text()
        self.assertIn('id="openbtn" class="bar-menu-item"', app)

    def test_scene_picker_switches_within_a_file(self):
        viewer = (STATIC / "viewer.html").read_text()
        self.assertIn('id="scene-menu"', viewer)
        self.assertIn('class="scene-picker"', viewer)
        self.assertIn('{ type: "switch_scene", scene: name }', viewer)
        self.assertIn("sceneButton.disabled = sceneNames.length < 2;", viewer)

    def test_open_returns_to_the_app_rather_than_a_native_bridge(self):
        viewer = (STATIC / "viewer.html").read_text()
        self.assertIn("window.location = appUrl;", viewer)

    def test_live_viewer_is_webgpu_only(self):
        """The browser is the renderer. There is no server pixel stream to
        fall back to or compare against, so the page must not offer one: a
        browser without WebGPU gets the notice on the stage instead."""
        viewer = (STATIC / "viewer.html").read_text()
        self.assertIn("new ManimlRendererSelection(canvas,", viewer)
        self.assertIn("void startRenderer(data.renderer, false);", viewer)
        self.assertIn('id="gpu-unsupported"', viewer)
        self.assertIn('document.body.classList.add("nogpu");', viewer)
        self.assertIn("if (!rendererNegotiated) return;", viewer)
        for gone in ('data-renderer="pixel"', 'id="split"', 'id="gpuview"',
                     "renderer_fallback", "createImageBitmap",
                     'getContext("2d")', "pixels:"):
            self.assertNotIn(gone, viewer)

    def test_client_render_assets_are_intact(self):
        """Kept deliberately: these are what a zero-install browser build
        would render with."""
        for name in ("webgpu.js", "player.html", "player.js"):
            self.assertTrue((STATIC / name).is_file(), name)
        self.assertTrue(list((STATIC / "wgsl").glob("*.wgsl")))
        self.assertFalse((STATIC / "gl.js").exists())
        self.assertFalse(list((STATIC / "glsl").glob("*")))

    def test_baked_player_is_webgpu_only_with_a_clear_fallback_message(self):
        html = (STATIC / "player.html").read_text()
        source = (STATIC / "player.js").read_text()
        self.assertIn('<script src="webgpu.js"></script>', html)
        self.assertNotIn("gl.js", html)
        self.assertNotIn("ManimlGL", source)
        from maniml.web.geometry import GEOMETRY_FORMAT_VERSION
        self.assertIn(f"const EXPORT_FORMAT_VERSION = {GEOMETRY_FORMAT_VERSION};", source)
        self.assertIn("Re-export this scene", source)
        self.assertIn("This browser doesn't support WebGPU.", source)

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
        self.assertIn("data.presentation_ready", viewer)
        self.assertIn('send({ type: "present" });', viewer)
        self.assertIn("endpointsMatch", viewer)
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


class FrameTests(unittest.TestCase):
    """Zen's shape, as Knuth and Plass have it (docs/ZEN-DRAFT.md): the
    frame, the bar across its top beside the traffic lights, the room. The
    numbers are theirs so the three apps measure the same."""

    def test_the_frame_has_knuths_and_plasss_numbers(self):
        shell = (STATIC / "shell.css").read_text()
        for value in ("--frame: #18181a;", "--pill: #232326;", "--tile: #2e2e32;",
                      "--topbar: env(titlebar-area-height, 44px);", "--edge: 8px;",
                      "--serif: 'STIX Two Text', 'Charter', 'Georgia', serif;"):
            self.assertIn(value, shell, value)
        bar = shell[shell.index("#toolbar {"):]
        bar = bar[:bar.index("}")]
        self.assertIn("height: var(--topbar);", bar)
        self.assertIn("gap: 6px;", bar)
        # Beside the lights' room in the app; 8 px in, over the room's
        # left edge, in a tab (no rail to centre over).
        self.assertIn("padding-inline: calc(12px + env(titlebar-area-x, -4px)) var(--edge);", bar)
        # The window moves by the bar, and by nothing in it.
        self.assertIn("-webkit-app-region: drag;", bar)
        self.assertIn("#toolbar > *, .bar-menu { -webkit-app-region: no-drag; }", shell)
        pill = shell[shell.index(".doc-pod {"):]
        pill = pill[:pill.index("}")]
        for value in ("height: 30px;", "padding: 0 10px;", "gap: 9px;",
                      "max-width: min(560px, 50vw);", "border-radius: 9px;",
                      "background: var(--pill);"):
            self.assertIn(value, pill, value)
        tile = shell[shell.index("#toolbar .icon-button {"):]
        tile = tile[:tile.index("}")]
        for value in ("width: 32px;", "height: 32px;", "border-radius: 9px;"):
            self.assertIn(value, tile, value)
        self.assertIn("#toolbar .icon-button svg { width: 18px; height: 18px; }", shell)
        self.assertIn("font: 15px/1.5 var(--serif); letter-spacing: 0.09em;", shell)

    def test_the_engines_status_keeps_its_width(self):
        """In class the status pill is the one place that says whether the
        engine is still answering, so the bar's right end never shrinks: the
        name pill's folder gives way first, then the name. Shrinkable, it
        was cut to a dot, or pushed under the console tile, at projector
        widths (1024 with the update showing)."""
        shell = (STATIC / "shell.css").read_text()
        end = shell[shell.index(".tb-end {"):]
        end = end[:end.index("}")]
        self.assertIn("flex: none;", end)
        self.assertNotIn("min-width: 0", end)
        pill = shell[shell.index(".doc-pod {"):]
        pill = pill[:pill.index("}")]
        self.assertIn("flex: 0 1 auto; min-width: 0;", pill)

    def test_the_bars_quiet_text_stays_in_the_bar(self):
        """A render's status and the renderer's warning are one line each,
        as the old bar's pods kept them: wrapped, they ran down out of the
        bar over the room. The render's status is the bar's own item, so it
        gives way with the name pill rather than pushing the right end; the
        warning, inside the right end, keeps to 95 px when the bar is short."""
        viewer = (STATIC / "viewer.html").read_text()
        style = viewer[:viewer.index("</style>")]
        job = style[style.index("  #job-status {"):]
        job = job[:job.index("}")]
        for value in ("flex: 0 1 auto; min-width: 0;", "white-space: nowrap;", "text-overflow: ellipsis;"):
            self.assertIn(value, job, value)
        warn = style[style.index("  #glwarn {"):]
        warn = warn[:warn.index("}")]
        self.assertIn("white-space: nowrap;", warn)
        self.assertIn("#export-pod.active + #job-status { display: block; }", style)
        self.assertIn("@media (max-width: 859px) {\n    #glwarn { max-width: 95px; }", style)
        # From 1024 up the status keeps its width and the name pill gives
        # way, folder first; below, the two share the shortfall as before.
        self.assertIn(
            "@media (min-width: 1024px) {\n    #doc-pod { flex-shrink: 1000; min-width: 120px; }\n    #job-status { flex-shrink: 0; }",
            style,
        )
        # A sibling after the group, not inside it: a group's text could
        # not shrink without its tiles.
        self.assertIn('</span>\n  <span id="job-status" role="status" aria-live="polite"></span>', viewer)

    def test_the_landing_page_holds_no_document(self):
        """The viewer tells the shell which scene its window holds; File →
        Open another scene… comes back to the landing page in the same
        window, so the landing page tells it none, or the Window menu and an
        update's relaunch would name the scene just left."""
        page = (STATIC / "app.html").read_text()
        self.assertIn("ManimlBar.setDocument(null);", page)
        bar = (STATIC / "bar.js").read_text()
        self.assertIn("if (!folder) return;", bar)

    def test_the_room_is_the_picture(self):
        """The scene fills Zen's rounded panel to its corners: the room is
        the largest box of the picture's shape in the frame's opening (under
        the bar, the edge in from the window's sides, above the presenter's
        bar's band on the frame's foot), fitted by CSS alone; the canvas and
        the recording fill it; full screen has no frame and is black beyond
        the picture (docs/ROOM-DRAFT.md)."""
        viewer = (STATIC / "viewer.html").read_text()
        self.assertIn('<div id="stage-area">\n<div id="stage">', viewer)
        self.assertIn("#stage-area {\n    position: absolute; inset: var(--topbar) var(--edge) calc(var(--edge) * 2 + 28px);",
                      viewer)
        self.assertIn("container-type: size;", viewer)
        self.assertIn("width: min(100cqw, calc(100cqh * var(--aspect)));", viewer)
        self.assertIn("aspect-ratio: var(--aspect);", viewer)
        self.assertIn("border-radius: 12px; background: #000;", viewer)
        self.assertIn("box-shadow: 0 0 0 1px rgba(255, 255, 255, 0.05), 0 18px 55px rgba(0, 0, 0, 0.32);", viewer)
        self.assertIn("display: block; width: 100%; height: 100%;", viewer)
        self.assertIn("#playback-video { display: none; width: 100%; height: 100%; background: #000; }", viewer)
        self.assertNotIn("#stage canvas {", viewer)
        self.assertIn("background: var(--frame); color: var(--text);", viewer)
        self.assertIn("body.fullscreen { --edge: 0px; }", viewer)
        self.assertIn("body.fullscreen #stage { border-radius: 0; box-shadow: none; }", viewer)
        # The picture's shape follows what is drawn: the engine's frame as
        # the driver sizes the canvas, the recording's while one plays.
        self.assertIn('stage.style.setProperty("--aspect", aspect);', viewer)
        self.assertIn("fitStage(canvas.width, canvas.height);\n    setRenderError(null);", viewer)
        self.assertIn("fitStage(playbackVideo.videoWidth, playbackVideo.videoHeight);", viewer)
        # The presenter's bar stands on the frame's foot: 12 px above the
        # frame's edge, in the band the room stops above.
        self.assertIn("left: 0; right: 0; bottom: var(--edge);", viewer)
        # The console is a column of the opening beside the room, which
        # gives up its width and the 12 px between them.
        self.assertIn("body.console #console { display: flex; opacity: 1; transform: none; }", viewer)
        self.assertNotIn("body.console #stage-area", viewer)
        self.assertNotIn("body.console #navbar", viewer)

    def test_the_presenters_bar_is_thin_and_the_rail_is_bars(self):
        """The pods are 28 px (Plass's old 42, cut down; Taylor, 2026-10-04),
        their buttons 24 with 16 px glyphs, the run's ends 14 px stadiums;
        the bar runs the room's width and the rail takes what the pods
        leave; the nodes are 2 px ticks (white loaded, grey not yet run,
        the accent at the position) joined by 1 px links that stop 3 px
        short of the ticks, 32 px at most and packing to 2 px except the
        links round the current tick, which keep their room; a rail with
        more than fits scrolls
        and fades its cut edges; the rail pads 8 px either side so the end
        ticks' glow is whole; the opening and the console stop 52 px above
        the frame's edge above the window's bottom (the edge, the pods,
        the edge)."""
        viewer_ = (STATIC / "viewer.html").read_text()
        self.assertIn("gap: 5px; padding: 0 var(--edge); pointer-events: none;", viewer_)
        self.assertIn("body.fullscreen #navbar { bottom: 12px; padding: 0 12px; }", viewer_)
        self.assertIn(".rail-pod { flex: 0 1 auto; min-width: 0; gap: 8px; padding: 0 6px; }", viewer_)
        self.assertIn("position: relative; flex: none; width: 32px; height: 1px;\n    margin: 0 3px;", viewer_)
        self.assertIn("position: relative; z-index: 1; width: 2px; height: var(--tall); padding: 0;", viewer_)
        self.assertIn("justify-content: safe center;", viewer_)
        self.assertIn('aria-label="Jump to the start" disabled hidden>', viewer_)
        self.assertIn("railObserver.disconnect();", viewer_)
        self.assertIn(".chip.future { --ink: rgba(150, 145, 153, 0.32); }", viewer_)
        self.assertIn("#rail .chip.current { --ink: var(--accent); --tall: 16px;", viewer_)
        self.assertIn("#rail .chip:first-child, #rail .chip:last-child {\n    --tall: 12px; --ink: rgba(235, 231, 225, 0.7); opacity: 1; transform: none;", viewer_)
        self.assertIn("height: calc(var(--tall) * (1 + var(--near, 0) * 0.5));", viewer_)
        self.assertIn("--ink: rgba(235, 231, 225, 0.55); --tall: 9px;", viewer_)
        self.assertIn("#rail.cut-left.cut-right {", viewer_)
        self.assertIn("function markRailEdges()", viewer_)
        # The links are seen between every pair; the ticks grow near the
        # pointer over a wider hit zone, and beside the current one.
        self.assertIn(".link.past { background: rgba(235, 231, 225, 0.3); }", viewer_)
        self.assertIn("transform: scale(calc(1 + var(--near, 0) * 1.5), calc(1 + var(--near, 0) * 0.5));", viewer_)
        self.assertIn('.chip::before { content: ""; position: absolute; top: -7px; bottom: -7px;', viewer_)
        self.assertIn("function magnifyRail(x)", viewer_)
        # The start and the end are brackets and always there: the middle
        # folds into dotted gaps round a window on the current tick.
        self.assertIn("#rail .chip:first-child::after, #rail .chip:last-child::after {", viewer_)
        self.assertIn(".chip.hidden { width: 0; margin: 0; opacity: 0; pointer-events: none; box-shadow: none; }", viewer_)
        self.assertIn("function packLinks(chips, links, current, room)", viewer_)
        self.assertIn("function foldRail()", viewer_)
        self.assertIn('gap.classList.toggle("elided", true);', viewer_)
        self.assertIn("function layoutRail() {\n  railObserver.disconnect();", viewer_)
        self.assertIn("function railRoom()", viewer_)
        self.assertIn("new ResizeObserver(layoutRail).observe(navbarEl);", viewer_)
        # A landed move draws its lit fill into the chip it reached, not
        # back into the one it left.
        self.assertIn("transform: scaleX(0); transform-origin: right center;", viewer_)
        self.assertIn(".link.lit .fill { transform: scaleX(1); opacity: 1; transform-origin: left center; }", viewer_)
        self.assertIn('attributeFilter: ["class"]', viewer_)
        self.assertEqual(viewer_.count('const railEl = document.getElementById("rail");'), 1)
        shell = (STATIC / "shell.css").read_text()
        self.assertIn(".pod {\n  height: 28px;", shell)
        self.assertIn(".pod-run > .pod:first-child { border-radius: 14px 8px 8px 14px; }", shell)
        self.assertIn("width: 24px; height: 24px; padding: 0; border: 0; border-radius: 6px;", shell)
        self.assertIn("width: 16px; height: 16px; fill: none;", shell)
        viewer = (STATIC / "viewer.html").read_text()
        self.assertIn("height: 26px;\n    display: flex; align-items: center; justify-content: safe center; overflow-x: auto;\n    padding: 0 8px;",
                      viewer)
        self.assertNotIn("flex-shrink: 0.5", viewer_)
        # The links taper and the row fades toward a fold, from distances
        # the page writes.
        self.assertNotIn("flex-shrink: var(", viewer_)
        self.assertIn("transition: width 280ms ease, margin 280ms ease, opacity 200ms ease;", viewer_)
        self.assertIn("opacity: clamp(0, calc((var(--edge, 99) - 1) / 8), 1);", viewer_)
        self.assertIn(".link.elided { opacity: 0; }", viewer_)
        self.assertIn('chips.forEach((c, i) => put(c, "--edge", edge(i)));', viewer_)
        self.assertIn("right: calc(var(--edge) + 12px); bottom: calc(var(--edge) * 2 + 28px + 12px);", viewer)
        # The bar's tiles keep their 32 px: the pods' size is the pods'.
        self.assertIn("#toolbar .icon-button {\n  flex: none; width: 32px; height: 32px;", shell)

    def test_the_engines_status_is_the_mark_beside_the_name(self):
        """Knuth's and Plass's save dot, 6 px after the name, is on the
        viewer the engine's status: green while it answers, red while it
        does not, its words in the mark's title and behind it for a reader
        without a screen; no status pill at the right end (Taylor,
        2026-10-04)."""
        shell = (STATIC / "shell.css").read_text()
        self.assertIn(".doc-mark {\n  flex: none; align-self: center; width: 6px; height: 6px;", shell)
        viewer = (STATIC / "viewer.html").read_text()
        self.assertIn('<span id="file-name">scene.py</span><span id="connection-pod" class="doc-mark"', viewer)
        self.assertIn('<span id="conn" class="sr-only">Connecting</span>', viewer)
        self.assertIn("body.disconnected #connection-pod { background: rgba(205, 100, 82, 0.95); }", viewer)
        end = viewer[viewer.index('<div class="tb-end">'):viewer.index("</header>")]
        self.assertNotIn("bar-pill", end)
        self.assertNotIn("slug-separator", viewer)
        self.assertIn("function setConnection(text)", viewer)
        self.assertNotIn('document.getElementById("conn").textContent = "', viewer)
        # The renderer's pill is there for the pointer and for a warning,
        # unseen otherwise: a comparison control still being tested.
        self.assertIn("#renderer-pod { opacity: 0; transition: opacity .16s ease; }", viewer)
        self.assertIn("#renderer-pod:has(#glwarn.on) { opacity: 1; }", viewer)

    def test_the_window_takes_the_pictures_shape(self):
        """In the app the window keeps the picture's shape (the shell's
        `shape` request, claerbout 0.2.7): the viewer tells the shell the
        ratio and the chrome round the opening, measured, once per change
        and again when the console or full screen changes it; the landing
        page lifts it. A tab has no shell and fits the room by CSS."""
        bar = (STATIC / "bar.js").read_text()
        self.assertIn('const message = { type: "shape", ratio: null };', bar)
        self.assertIn("width: window.innerWidth - opening.clientWidth,", bar)
        self.assertIn("height: window.innerHeight - opening.clientHeight,", bar)
        self.assertIn("if (!shell) return;", bar[bar.index("function setShape"):])
        viewer = (STATIC / "viewer.html").read_text()
        self.assertIn("ManimlBar.setShape(stageRatio, stageArea);", viewer)
        self.assertIn("if (document.fullscreenElement) return;", viewer)
        console = viewer[viewer.index("function setConsole(open) {"):]
        self.assertIn("shapeWindow();", console[:console.index("\n}\n")])
        page = (STATIC / "app.html").read_text()
        self.assertIn("ManimlBar.setShape(null);", page)

    def test_the_name_is_exactly_the_files_name(self):
        """The shell's smoke waits for #file-name to read the document's
        name exactly (app/maniml.json `smoke.ready`), so the folder and the
        scene are siblings beside it, never inside it."""
        viewer = (STATIC / "viewer.html").read_text()
        self.assertIn('<span id="file-name">scene.py</span>', viewer)
        self.assertIn('id="doc-folder" class="doc-folder" hidden><span dir="ltr"></span></span>', viewer)
        self.assertIn('if ("path" in state) ManimlBar.setDocument(state.path, docFolder);', viewer)

    def test_an_open_menu_keeps_its_keys_from_the_scene(self):
        """The viewer forwards every key it hears to the engine, so a menu in
        the bar takes the keys it is given in the capture phase, before the
        forwarder, and their releases with them."""
        bar = (STATIC / "bar.js").read_text()
        keydown = bar[bar.index('document.addEventListener("keydown"'):]
        keydown = keydown[:keydown.index("}, true);")]
        self.assertIn("event.stopPropagation();", keydown)
        self.assertIn("swallowed.add(key);", keydown)
        self.assertIn('if (swallowed.delete(event.key)) event.stopPropagation();', bar)
        # The folder is the shell's answer, never a path it refused.
        self.assertIn('shell.request({ type: "document", path: wanted })', bar)
        for forbidden in ("maniml://", "WebSocket", "fetch("):
            self.assertNotIn(forbidden, bar, forbidden)

    def test_the_setup_page_moves_the_window_by_the_lights_band(self):
        setup = (STATIC / "setup.css").read_text()
        self.assertIn("height: env(titlebar-area-height, 0px);\n  -webkit-app-region: drag;", setup)
        self.assertIn("padding: calc(24px + env(titlebar-area-height, 0px)) 0 40px;", setup)


if __name__ == "__main__":
    unittest.main()

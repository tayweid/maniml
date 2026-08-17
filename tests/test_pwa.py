"""Static contract tests for the installable hosted app shell."""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

from maniml.web.security import WEB_PROTOCOL_VERSION

STATIC = Path(__file__).resolve().parent.parent / "maniml" / "web" / "static"


class PWAAssetsTests(unittest.TestCase):
    def test_manifest_registers_the_app_as_a_python_file_handler(self):
        """The PWA itself handles .py from Finder, so the desktop bridge is
        not the only way in. Its consumer must exist, or the OS would hand
        files to a page that ignores them."""
        manifest = json.loads((STATIC / "manifest.webmanifest").read_text())
        handler = manifest["file_handlers"][0]
        self.assertEqual(handler["action"], "./app.html")
        self.assertEqual(handler["accept"]["text/x-python"], [".py"])
        # Reuse the open window instead of stacking up a second one.
        self.assertEqual(manifest["launch_handler"]["client_mode"],
                         "navigate-existing")

        page = (STATIC / "app.html").read_text()
        self.assertIn("window.launchQueue.setConsumer", page)
        self.assertIn('request("resolve"', page)
        self.assertIn('crypto.subtle.digest("SHA-256", bytes)', page)
        # A launch can beat the handshake; it must not be dropped.
        self.assertIn("pendingLaunch = file;", page)
        self.assertIn("void drainPendingLaunch();", page)

    def test_manifest_has_installable_identity_and_icons(self):
        manifest = json.loads((STATIC / "manifest.webmanifest").read_text())
        self.assertEqual(manifest["name"], "ManimLive")
        self.assertEqual(manifest["id"], "./")
        self.assertEqual(manifest["start_url"], "./app.html")
        self.assertEqual(manifest["scope"], "./")
        self.assertEqual(manifest["display"], "standalone")
        sizes = {icon["sizes"] for icon in manifest["icons"]}
        self.assertTrue({"192x192", "512x512"}.issubset(sizes))
        for icon in manifest["icons"]:
            self.assertTrue((STATIC / icon["src"]).is_file())

    def test_onboarding_is_explicit_and_copyable(self):
        page = (STATIC / "app.html").read_text()
        self.assertIn("beforeinstallprompt", page)
        self.assertIn("navigator.clipboard.writeText", page)
        self.assertIn('data-copy="install-command"', page)
        self.assertIn("python -m pip install --upgrade", page)
        self.assertIn("--force-reinstall --no-cache-dir", page)
        self.assertIn("python -m maniml install-desktop --replace", page)
        self.assertNotIn("&& maniml install-desktop", page)
        self.assertIn("clientPlatform", page)
        self.assertIn("Windows and Linux packaging is still in progress", page)
        self.assertIn('id="openbtn"', page)
        self.assertIn('request("choose")', page)
        self.assertIn('window.location.href = "maniml://open"', page)
        self.assertNotIn('placeholder="/path/to/scene.py"', page)
        self.assertIn("DEFAULT_CONTROL_PORT", page)
        self.assertIn('serviceWorker.register("./sw.js")', page)
        self.assertIn(
            f"const WEB_PROTOCOL_VERSION = {WEB_PROTOCOL_VERSION};",
            page,
        )

    def test_open_button_reports_a_missing_desktop_bridge(self):
        """A maniml:// navigation with no handler is silent, so the page must
        detect the dead click itself rather than sit on 'connecting'."""
        page = (STATIC / "app.html").read_text()
        self.assertIn("const BRIDGE_TIMEOUT = 6000;", page)
        self.assertIn("function requestDesktopBridge()", page)
        self.assertIn("function reportSilentBridge()", page)
        self.assertIn('setConnectionState(\n    "bridge-missing"', page)
        self.assertIn('body[data-connection="bridge-missing"] #status-dot', page)
        self.assertIn("cancelBridgeWatchdog()", page)

    def test_bridge_watchdog_keys_on_focus_not_visibility(self):
        """A launcher coming to the front takes focus but leaves the page
        visible, so a visibility test reported a working bridge as missing."""
        for name in ("app.html", "viewer.html"):
            page = (STATIC / name).read_text()
            watchdog = page.split("function requestDesktopBridge()", 1)[1].split(
                "\n}\n", 1
            )[0]
            self.assertIn("!document.hasFocus()", watchdog, name)
            self.assertNotIn("visibilityState", watchdog, name)
            self.assertIn(
                'window.addEventListener("blur", cancelBridgeWatchdog);', page, name
            )

    def test_connection_message_is_visible_whenever_it_has_text(self):
        """The detail passed to setConnectionState used to be display:none for
        every state except expired/incompatible, hiding the Open button's
        only feedback."""
        page = (STATIC / "app.html").read_text()
        self.assertIn("#connection-message:empty { display: none; }", page)
        self.assertNotIn(
            'body[data-connection="expired"] #connection-message', page
        )

    def test_only_a_default_port_pairing_is_persisted(self):
        """An agent's capability outlives its process and should survive a
        reload; a transient session's ephemeral port never returns, so
        persisting that token would strand a dead capability."""
        page = (STATIC / "app.html").read_text()
        self.assertIn(
            "const persistToken = controlPort === DEFAULT_CONTROL_PORT;", page)
        self.assertIn(
            "const tokenStore = persistToken ? localStorage : sessionStorage;",
            page,
        )
        # A rejected pairing must not linger in either store.
        self.assertIn("function forgetControlToken()", page)
        self.assertIn("localStorage.removeItem(controlTokenKey);", page)
        self.assertIn("sessionStorage.removeItem(controlTokenKey);", page)
        close = page.split("control.onclose", 1)[1].split("control.onerror", 1)[0]
        self.assertIn("forgetControlToken();", close)

    def test_hosted_root_forwards_the_pairing_fragment(self):
        """run_app pairs via HOSTED_APP_URL#token=...; a bare meta refresh to
        app.html would drop the fragment and the capability with it."""
        index = (STATIC / "index.html").read_text()
        self.assertIn(
            'location.replace("app.html" + location.search + location.hash);',
            index,
        )
        # The no-JS fallback must not pre-empt the fragment-preserving script.
        self.assertIn("<noscript>", index)
        self.assertLess(index.index("location.replace"), index.index("<noscript>"))

    def test_viewer_open_button_reports_a_missing_desktop_bridge(self):
        viewer = (STATIC / "viewer.html").read_text()
        self.assertIn("function requestDesktopBridge()", viewer)
        self.assertIn("const BRIDGE_TIMEOUT = 6000;", viewer)
        self.assertIn('id="dismiss-overlay"', viewer)
        # A missing launcher says nothing about this scene's own socket, so
        # it must not flip the viewer into its disconnected presentation.
        bridge = viewer.split("function requestDesktopBridge()", 1)[1].split(
            "window.addEventListener", 1
        )[0]
        self.assertIn("showOverlay(", bridge)
        self.assertNotIn("showConnectionIssue(", bridge)
        self.assertNotIn("classList.add(\"disconnected\")", bridge)

    def test_viewer_and_engine_share_protocol_version(self):
        viewer = (STATIC / "viewer.html").read_text()
        self.assertIn(
            f"const WEB_PROTOCOL_VERSION = {WEB_PROTOCOL_VERSION};",
            viewer,
        )
        self.assertIn("engine update required", viewer)
        self.assertIn('id="open-file"', viewer)
        self.assertIn('window.location.href = "maniml://open"', viewer)
        self.assertIn('id="file-menu"', viewer)
        self.assertIn('id="previous"', viewer)
        self.assertIn('id="next"', viewer)
        self.assertIn('id="export-video"', viewer)
        self.assertIn('id="export-web"', viewer)
        self.assertIn('id="export-frame"', viewer)
        self.assertIn('aria-label="Scene pausepoints"', viewer)
        self.assertIn('{ type: "export", format: "video" }', viewer)
        self.assertIn("applyCapabilities(data.capabilities || [])", viewer)
        self.assertIn('id="connection-overlay"', viewer)
        self.assertIn('id="retry-connection"', viewer)
        self.assertIn('targetAddressSpace: "loopback"', viewer)
        self.assertIn("const MAX_RECONNECTS = 3", viewer)
        self.assertIn("Local network access", viewer)
        probe = viewer.split("function primeLoopbackPermission", 1)[1].split(
            "function scheduleReconnect", 1
        )[0]
        self.assertNotIn("token: viewerToken", probe)

    def test_viewer_has_a_scene_picker(self):
        viewer = (STATIC / "viewer.html").read_text()
        self.assertIn('id="scene-menu"', viewer)
        self.assertIn('class="scene-picker"', viewer)
        self.assertIn('aria-haspopup="menu"', viewer)
        self.assertIn('{ type: "switch_scene", scene: name }', viewer)
        self.assertIn("function renderSceneMenu(current)", viewer)
        # The list is engine-supplied; a file with one scene offers no switch.
        self.assertIn("if (Array.isArray(state.scenes)) sceneNames = state.scenes;", viewer)
        self.assertIn("sceneButton.disabled = sceneNames.length < 2;", viewer)

    def test_live_viewer_uses_webgpu_first_with_visible_pixel_fallback(self):
        viewer = (STATIC / "viewer.html").read_text()
        self.assertIn('const DEFAULT_RENDERER = "gpu";', viewer)
        self.assertIn('let renderer = DEFAULT_RENDERER;', viewer)
        self.assertIn('void selectRenderer(renderer, segment);', viewer)
        self.assertIn('renderer = "pixel";', viewer)
        self.assertIn('WebGPU unavailable; using Pixel:', viewer)

    def test_service_worker_caches_only_same_origin_static_shell(self):
        worker = (STATIC / "sw.js").read_text()
        self.assertIn('const CACHE_NAME = "maniml-app-shell-v6";', worker)
        self.assertIn("url.origin !== self.location.origin", worker)
        self.assertIn('event.request.method !== "GET"', worker)
        self.assertLess(
            worker.index("fetch(event.request)"),
            worker.index("caches.match(event.request)"),
        )
        self.assertNotIn("127.0.0.1", worker)
        self.assertNotIn("Authorization", worker)

        shell_match = re.search(
            r"const APP_SHELL = \[(.*?)\];", worker, flags=re.DOTALL
        )
        self.assertIsNotNone(shell_match)
        entries = re.findall(r'"(\./[^\"]*|\./)"', shell_match.group(1))
        for entry in entries:
            if entry == "./":
                continue
            self.assertTrue((STATIC / entry.removeprefix("./")).is_file(), entry)


if __name__ == "__main__":
    unittest.main()

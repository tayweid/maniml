"""Static contract tests for the installable hosted app shell."""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

from maniml.web.security import WEB_PROTOCOL_VERSION

STATIC = Path(__file__).resolve().parent.parent / "maniml" / "web" / "static"


class PWAAssetsTests(unittest.TestCase):
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
        self.assertIn("python -m pip install", page)
        self.assertIn("maniml install-desktop", page)
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

    def test_service_worker_caches_only_same_origin_static_shell(self):
        worker = (STATIC / "sw.js").read_text()
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

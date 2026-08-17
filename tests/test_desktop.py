"""Desktop-launcher and user-authorized file-picker contracts."""

from __future__ import annotations

import plistlib
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from maniml.desktop import install_desktop_launcher
from maniml.web.app import AppServer, _is_maniml_chrome_pwa, open_hosted_url

SCENE_SOURCE = """\
from manim import *

class First(Scene):
    pass

class Second(Scene):
    pass
"""


class FilePickerTests(unittest.TestCase):
    def test_native_picker_grants_only_the_selected_external_file(self):
        with (
            tempfile.TemporaryDirectory() as root_dir,
            tempfile.TemporaryDirectory() as outside_dir,
        ):
            selected = Path(outside_dir) / "picked.py"
            selected.write_text(SCENE_SOURCE)
            other = Path(outside_dir) / "other.py"
            other.write_text(SCENE_SOURCE)

            # Exercise the picker/open authorization logic without starting
            # either of AppServer's network listeners.
            server = object.__new__(AppServer)
            server.root = str(Path(root_dir).resolve())
            server._root_path = Path(server.root)
            server.allow_outside_root = False
            server._granted_files = set()
            server.processes = {}

            with mock.patch(
                "maniml.web.app.choose_python_file", return_value=str(selected)
            ):
                payload = server.choose_payload()
            self.assertEqual(payload["file"]["path"], str(selected.resolve()))
            self.assertEqual(payload["file"]["scenes"], ["First", "Second"])
            self.assertIn(str(selected.resolve()), server._granted_files)

            with mock.patch.object(server, "open_scene", return_value=None):
                # The selected file reaches scene validation/startup; a sibling
                # that the user did not select is still blocked by root policy.
                selected_result = server.open_payload(
                    {"path": str(selected), "scene": "First"}
                )
                other_result = server.open_payload(
                    {"path": str(other), "scene": "First"}
                )
            self.assertEqual(selected_result["error"], "scene failed to start")
            self.assertEqual(other_result["error"], "path is outside the app root")

    def test_picker_cancellation_does_not_grant_access(self):
        server = object.__new__(AppServer)
        server.root = tempfile.gettempdir()
        server._root_path = Path(server.root)
        server.allow_outside_root = False
        server._granted_files = set()
        server.processes = {}
        with mock.patch("maniml.web.app.choose_python_file", return_value=None):
            self.assertEqual(server.choose_payload(), {"cancelled": True})
        self.assertEqual(server._granted_files, set())


class HostedBrowserLaunchTests(unittest.TestCase):
    @staticmethod
    def _write_pwa_info(application: Path, url: str) -> None:
        contents = application / "Contents"
        contents.mkdir(parents=True)
        with (contents / "Info.plist").open("wb") as file:
            plistlib.dump(
                {
                    "CFBundleExecutable": "app_mode_loader",
                    "CrBundleIdentifier": "com.google.Chrome",
                    "CrAppModeShortcutName": "ManimLive",
                    "CrAppModeShortcutURL": url,
                },
                file,
            )

    def test_macos_prefers_installed_pwa_without_a_shell(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            pwa = home / "Applications/Chrome Apps.localized/ManimLive.app"
            self._write_pwa_info(pwa, "https://maniml.tayweid.io/")
            url = "https://maniml.tayweid.io/viewer.html?ws=1234#token=secret"
            with (
                mock.patch("maniml.web.app.sys.platform", "darwin"),
                mock.patch("maniml.web.app.Path.home", return_value=home),
                mock.patch("maniml.web.app._macos_chrome_app", return_value=None),
                mock.patch("maniml.web.app.subprocess.Popen") as popen,
                mock.patch("maniml.web.app.webbrowser.open") as fallback,
            ):
                self.assertTrue(open_hosted_url(url))
            args, kwargs = popen.call_args
            self.assertEqual(
                args[0],
                [
                    "/usr/bin/open",
                    "-a",
                    str(pwa),
                    url,
                ],
            )
            self.assertNotIn("shell", kwargs)
            fallback.assert_not_called()

    def test_same_named_bundle_with_wrong_origin_is_not_trusted(self):
        with tempfile.TemporaryDirectory() as directory:
            pwa = Path(directory) / "ManimLive.app"
            self._write_pwa_info(pwa, "https://example.test/")
            self.assertFalse(_is_maniml_chrome_pwa(pwa))

    def test_macos_skips_unverified_pwa_and_uses_system_chrome(self):
        with tempfile.TemporaryDirectory() as directory:
            pwa = Path(directory) / "ManimLive.app"
            pwa.mkdir()
            chrome = Path("/Applications/Google Chrome.app")
            url = "https://maniml.tayweid.io/viewer.html"
            with (
                mock.patch("maniml.web.app.sys.platform", "darwin"),
                mock.patch(
                    "maniml.web.app._macos_maniml_pwa_candidates",
                    return_value=(pwa,),
                ),
                mock.patch("maniml.web.app._macos_chrome_app", return_value=chrome),
                mock.patch("maniml.web.app.subprocess.Popen") as popen,
            ):
                self.assertTrue(open_hosted_url(url))
            self.assertEqual(
                popen.call_args.args[0],
                ["/usr/bin/open", "-a", str(chrome), url],
            )

    def test_non_macos_uses_default_browser(self):
        with (
            mock.patch("maniml.web.app.sys.platform", "linux"),
            mock.patch("maniml.web.app.webbrowser.open", return_value=True) as open_,
        ):
            self.assertTrue(open_hosted_url("https://maniml.test/session"))
        open_.assert_called_once_with("https://maniml.test/session")


@unittest.skipUnless(sys.platform == "darwin", "macOS launcher")
class MacDesktopLauncherTests(unittest.TestCase):
    def test_installed_bundle_registers_python_open_with(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "ManimLive.app"
            log_directory = Path(directory) / "logs"
            installed = install_desktop_launcher(
                destination, log_directory=log_directory, register=False
            )
            self.assertEqual(installed, destination)
            with (installed / "Contents" / "Info.plist").open("rb") as file:
                info = plistlib.load(file)
            self.assertEqual(info["CFBundleIdentifier"], "io.tayweid.maniml")
            document = info["CFBundleDocumentTypes"][0]
            self.assertEqual(document["CFBundleTypeExtensions"], ["py"])
            self.assertEqual(document["LSHandlerRank"], "Alternate")
            self.assertEqual(
                info["CFBundleURLTypes"][0]["CFBundleURLSchemes"],
                ["maniml"],
            )
            self.assertFalse(any(key.endswith("UsageDescription") for key in info))
            source = subprocess.run(
                ["/usr/bin/osadecompile", str(installed)],
                capture_output=True,
                text=True,
                check=True,
            ).stdout
            self.assertIn(str(Path(sys.executable).absolute()), source)
            self.assertIn("-m maniml open", source)
            self.assertIn("maniml://open", source)

            with self.assertRaises(FileExistsError):
                install_desktop_launcher(
                    destination,
                    log_directory=log_directory,
                    register=False,
                )
            install_desktop_launcher(
                destination,
                replace=True,
                log_directory=log_directory,
                register=False,
            )
            subprocess.run(
                [
                    "/usr/bin/codesign",
                    "--verify",
                    "--deep",
                    "--strict",
                    str(destination),
                ],
                capture_output=True,
                text=True,
                check=True,
            )


if __name__ == "__main__":
    unittest.main()

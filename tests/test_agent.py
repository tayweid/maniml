"""The background engine agent and its persisted pairing capability."""

from __future__ import annotations

import os
import plistlib
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from maniml import agent
from maniml.web import security


class CapabilityTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.config = Path(self.tmpdir.name) / ".maniml"
        patcher = patch.object(security, "CONFIG_DIR", self.config)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_capability_is_stable_and_private(self):
        first = security.load_or_create_capability()
        self.assertTrue(first)
        # Stable: a restarted agent must not strand every paired browser.
        self.assertEqual(first, security.load_or_create_capability())

        path = security.capability_path()
        self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(os.stat(path.parent).st_mode), 0o700)

    def test_rotation_replaces_the_capability(self):
        first = security.load_or_create_capability()
        rotated = security.rotate_capability()
        self.assertNotEqual(first, rotated)
        self.assertEqual(rotated, security.load_or_create_capability())
        self.assertEqual(
            stat.S_IMODE(os.stat(security.capability_path()).st_mode), 0o600)
        # No temporary files left behind by the atomic replace.
        self.assertEqual(
            [p.name for p in self.config.iterdir()], [security.CAPABILITY_FILE])

    def test_a_blank_capability_file_is_rejected(self):
        self.config.mkdir(mode=0o700, parents=True)
        security.capability_path().write_text("   \n")
        with self.assertRaises(ValueError):
            security.load_or_create_capability()


class AgentPlistTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        root = Path(self.tmpdir.name)
        self.plist = root / "agent.plist"
        self.config = root / ".maniml"
        self.calls = []

        for target, value in (
            (patch.object(agent, "PLIST", self.plist), None),
            (patch.object(agent, "LOG", root / "agent.log"), None),
            (patch.object(security, "CONFIG_DIR", self.config), None),
        ):
            target.start()
            self.addCleanup(target.stop)

        def fake_launchctl(*args):
            self.calls.append(args)
            return type("R", (), {"returncode": 0, "stderr": "", "stdout": ""})()

        patcher = patch.object(agent, "_launchctl", fake_launchctl)
        patcher.start()
        self.addCleanup(patcher.stop)

    @unittest.skipUnless(os.uname().sysname == "Darwin", "launchd is macOS-only")
    def test_install_writes_a_login_agent_for_this_interpreter(self):
        scenes = Path(self.tmpdir.name) / "scenes"
        scenes.mkdir()
        self.assertEqual(agent.install(scenes, port=8686), 0)

        plist = plistlib.loads(self.plist.read_bytes())
        self.assertEqual(plist["Label"], agent.LABEL)
        self.assertTrue(plist["RunAtLoad"])
        self.assertTrue(plist["KeepAlive"])

        arguments = plist["ProgramArguments"]
        self.assertEqual(arguments[1:5], ["-m", "maniml", "agent", "serve"])
        self.assertEqual(arguments[5], str(scenes.resolve()))
        # One argv entry: the CLI reads any leading-dash token as a flag, so a
        # separated value would be swallowed as a positional argument.
        self.assertEqual(arguments[6], "--port=8686")
        self.assertNotIn("--port", arguments)

        self.assertIn("bootstrap", [call[0] for call in self.calls])
        self.assertIn("kickstart", [call[0] for call in self.calls])

    @unittest.skipUnless(os.uname().sysname == "Darwin", "launchd is macOS-only")
    def test_install_rejects_a_root_that_is_not_a_directory(self):
        missing = Path(self.tmpdir.name) / "nope"
        self.assertEqual(agent.install(missing), 1)
        self.assertFalse(self.plist.exists())

    def test_pairing_url_carries_the_persisted_capability(self):
        url = agent.pairing_url()
        self.assertTrue(url.startswith(security.HOSTED_APP_URL))
        self.assertIn(f"#token={security.load_or_create_capability()}", url)


if __name__ == "__main__":
    unittest.main()

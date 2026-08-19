"""The background engine agent."""

from __future__ import annotations

import os
import plistlib
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from maniml import agent
from maniml.web import security


class ConfigDirTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.config = Path(self.tmpdir.name) / ".maniml"
        patcher = patch.object(security, "CONFIG_DIR", self.config)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_config_dir_is_private(self):
        """The agent publishes where it landed here; nothing secret lives in
        it any more, but it is still the user's own directory."""
        created = security.prepare_config_dir()
        self.assertEqual(created, self.config)
        self.assertEqual(stat.S_IMODE(os.stat(self.config).st_mode), 0o700)

    def test_a_symlinked_config_path_is_refused(self):
        target = Path(self.tmpdir.name) / "elsewhere"
        target.mkdir()
        try:
            self.config.symlink_to(target)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks unavailable")
        with self.assertRaises(RuntimeError):
            security.prepare_config_dir()


class FirstRunOfferTests(unittest.TestCase):
    """`maniml app` asks once. Never twice, and never when nobody can answer."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.config = Path(self.tmpdir.name) / ".maniml"
        for target, value in (("CONFIG_DIR", self.config),
                              ("OFFERED_PATH", self.config / "agent-offered")):
            patcher = patch.object(agent, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        security_patcher = patch.object(security, "CONFIG_DIR", self.config)
        security_patcher.start()
        self.addCleanup(security_patcher.stop)

    def test_a_run_nobody_is_watching_is_never_asked(self):
        """The launchd agent runs `maniml agent serve`, and a blocked input()
        there would hang the engine on every login."""
        with patch.object(agent.sys, "stdin", None), \
                patch.object(agent, "is_installed", return_value=False):
            self.assertFalse(agent.offer_at_first_run(self.tmpdir.name))
        self.assertFalse(agent.OFFERED_PATH.exists())

    @unittest.skipUnless(os.uname().sysname == "Darwin", "launchd is macOS-only")
    def test_declining_is_remembered_so_it_asks_only_once(self):
        stdin = MagicMock()
        stdin.isatty.return_value = True
        with patch.object(agent.sys, "stdin", stdin), \
                patch.object(agent, "is_installed", return_value=False), \
                patch("builtins.input", return_value="n"):
            self.assertFalse(agent.offer_at_first_run(self.tmpdir.name))
        self.assertTrue(agent.OFFERED_PATH.exists())

        # Asked already: no prompt, and nothing installed behind your back.
        with patch("builtins.input", side_effect=AssertionError("asked twice")):
            self.assertFalse(agent.offer_at_first_run(self.tmpdir.name))

    @unittest.skipUnless(os.uname().sysname == "Darwin", "launchd is macOS-only")
    def test_an_already_installed_agent_is_not_offered(self):
        stdin = MagicMock()
        stdin.isatty.return_value = True
        with patch.object(agent.sys, "stdin", stdin), \
                patch.object(agent, "is_installed", return_value=True), \
                patch("builtins.input", side_effect=AssertionError("asked anyway")):
            self.assertFalse(agent.offer_at_first_run(self.tmpdir.name))
        self.assertTrue(agent.OFFERED_PATH.exists())


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

    def test_app_url_is_a_plain_local_address(self):
        """Nothing to carry: the address is the whole thing, so it survives
        being bookmarked, and an agent restart does not invalidate it."""
        url = agent.app_url()
        self.assertTrue(url.startswith("http://localhost:"))
        self.assertNotIn("#", url)

    def test_app_url_follows_the_port_the_agent_actually_got(self):
        """The default port may already be taken, in which case the app server
        falls back and this is the only record of where it landed."""
        state = Path(self.tmpdir.name) / "agent.json"
        with patch.object(agent, "STATE_PATH", state):
            state.write_text('{"url": "http://localhost:51234/"}')
            self.assertEqual(agent.app_url(), "http://localhost:51234/")

            # A stale or corrupt file must not produce a nonsense address.
            state.write_text("{ not json")
            self.assertTrue(
                agent.app_url().startswith(f"http://localhost:{agent.DEFAULT_APP_PORT}/"))
            state.write_text('{"url": "https://example.invalid/"}')
            self.assertTrue(
                agent.app_url().startswith(f"http://localhost:{agent.DEFAULT_APP_PORT}/"))


if __name__ == "__main__":
    unittest.main()

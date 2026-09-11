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
    def test_the_agent_can_find_the_tools_a_scene_shells_out_to(self):
        """launchd hands a login agent PATH=/usr/bin:/bin:/usr/sbin:/sbin and
        nothing else, so latex, dvisvgm and ffmpeg are all invisible to a
        scene run through the app — while the same scene from a terminal
        works, which makes it read as a maniml bug rather than a search
        path."""
        scenes = Path(self.tmpdir.name) / "scenes"
        scenes.mkdir()
        self.assertEqual(agent.install(scenes, port=8686), 0)

        plist = plistlib.loads(self.plist.read_bytes())
        path = plist["EnvironmentVariables"]["PATH"]
        self.assertIn(os.pathsep, path, "the agent got a single-entry PATH")
        for directory in os.environ.get("PATH", "").split(os.pathsep):
            if directory:
                self.assertIn(directory, path.split(os.pathsep), directory)

    def test_search_path_only_ever_adds_somewhere_to_look(self):
        """Appended, never reordered or removed: an entry already present
        keeps the priority it had, so this cannot shadow a chosen toolchain."""
        base = "/usr/bin:/bin"
        result = agent.search_path(base).split(os.pathsep)
        self.assertEqual(result[:2], ["/usr/bin", "/bin"])
        self.assertEqual(len(result), len(set(result)), "duplicated entries")
        for directory in result[2:]:
            self.assertIn(directory, agent.TOOL_DIRS)
            self.assertTrue(os.path.isdir(directory), directory)

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


class AgentCommandTests(unittest.TestCase):
    """status, restart, uninstall and serve against a mocked launchctl."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        root = Path(self.tmpdir.name)
        self.plist = root / "agent.plist"
        self.calls = []
        self.results = {}
        for target in (patch.object(agent, "PLIST", self.plist),
                       patch.object(agent, "LOG", root / "agent.log"),
                       patch.object(security, "CONFIG_DIR", root / ".maniml")):
            target.start()
            self.addCleanup(target.stop)

        def fake_launchctl(*args):
            self.calls.append(args)
            returncode, stdout, stderr = self.results.get(args[0], (0, "", ""))
            return type("R", (), {"returncode": returncode, "stdout": stdout, "stderr": stderr})()

        patcher = patch.object(agent, "_launchctl", fake_launchctl)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.printed = []
        printer = patch("builtins.print", lambda *parts, **_: self.printed.append(" ".join(map(str, parts))))
        printer.start()
        self.addCleanup(printer.stop)

    @unittest.skipUnless(os.uname().sysname == "Darwin", "launchd is macOS-only")
    def test_status_reports_not_installed_and_the_running_state(self):
        self.results["print"] = (113, "", "Could not find service")
        self.assertEqual(agent.status(), 1)
        self.assertTrue(any("not installed" in line for line in self.printed))
        self.results["print"] = (0, "\tstate = running\n\tpid = 42\n", "")
        self.assertEqual(agent.status(), 0)
        self.assertTrue(any("installed, state = running" in line for line in self.printed))
        self.assertEqual([call[0] for call in self.calls], ["print", "print"])

    @unittest.skipUnless(os.uname().sysname == "Darwin", "launchd is macOS-only")
    def test_restart_kickstarts_with_kill_and_reports_a_refusal(self):
        self.assertEqual(agent.restart(), 0)
        self.assertEqual(self.calls[-1][:2], ("kickstart", "-k"))
        self.assertTrue(any("Restarted" in line for line in self.printed))
        self.results["kickstart"] = (1, "", "Boot-out failed")
        self.assertEqual(agent.restart(), 1)
        self.assertTrue(any("Could not restart" in line and "Boot-out failed" in line for line in self.printed))

    @unittest.skipUnless(os.uname().sysname == "Darwin", "launchd is macOS-only")
    def test_uninstall_boots_out_and_removes_the_plist_whether_or_not_it_existed(self):
        self.plist.write_bytes(b"<plist/>")
        self.assertEqual(agent.uninstall(), 0)
        self.assertFalse(self.plist.exists())
        self.assertEqual(self.calls[-1][0], "bootout")
        self.assertTrue(any(line.startswith("Removed") for line in self.printed))
        self.assertEqual(agent.uninstall(quiet=True), 0)
        self.assertFalse(any("was not installed" in line for line in self.printed), "quiet prints nothing")
        self.assertEqual(agent.uninstall(), 0)
        self.assertTrue(any("was not installed" in line for line in self.printed))

    def test_serve_runs_the_app_in_the_foreground_with_the_tool_path(self):
        from maniml.web import cli
        seen = {}

        def fake_run_app(**kwargs):
            seen.update(kwargs)
            seen["path"] = os.environ["PATH"]
            return 0

        with patch.object(cli, "run_app", fake_run_app), \
                patch.dict(os.environ, {"PATH": "/only/this"}), \
                patch.object(agent, "TOOL_DIRS", (self.tmpdir.name,)):
            agent.serve(self.tmpdir.name, port=8686)
        self.assertEqual(seen["root"], self.tmpdir.name)
        self.assertEqual(seen["port"], 8686)
        self.assertFalse(seen["open_browser"])
        self.assertEqual(seen["path"].split(os.pathsep), ["/only/this", self.tmpdir.name])

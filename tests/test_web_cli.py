"""`maniml app` hands off to an engine that is already up.

The port is the installed app's identity, so a second engine on another
port would serve a page the installed app never opens; and pip replaces
files without restarting processes, so an engine serving pre-upgrade code
must be restarted rather than competed with.
"""

import unittest
from unittest.mock import patch

from maniml import agent
from maniml.web import cli


class HandOffTests(unittest.TestCase):
    def setUp(self):
        self.printed = []
        self.opened = []
        for target, value in (
            (patch.object(cli, "_package_version", lambda: "2.0"), None),
            (patch("builtins.print", lambda *parts, **_: self.printed.append(" ".join(map(str, parts)))), None),
            (patch.object(cli.webbrowser, "open", lambda url: self.opened.append(url)), None),
            (patch.object(agent, "restart", lambda: self.printed.append("<restart>") or 0), None),
        ):
            target.start()
            self.addCleanup(target.stop)

    def hand_off(self, *, serving, installed_agent=False, offer=False, open_browser=True):
        with patch.object(cli, "running_engine", lambda: serving), \
                patch.object(agent, "is_installed", lambda: installed_agent), \
                patch.object(agent, "offer_at_first_run", lambda root: offer):
            return cli.hand_off_to_a_running_engine("/tmp/scenes", open_browser)

    def test_a_current_engine_is_used_and_the_browser_opened(self):
        self.assertTrue(self.hand_off(serving="2.0"))
        self.assertEqual(self.opened, [f"http://localhost:{cli.DEFAULT_APP_PORT}/"])
        self.assertTrue(any("already running" in line for line in self.printed))
        self.assertNotIn("<restart>", self.printed)

    def test_no_browser_means_no_browser(self):
        self.assertTrue(self.hand_off(serving="2.0", open_browser=False))
        self.assertEqual(self.opened, [])

    def test_a_stale_installed_agent_is_restarted(self):
        self.assertTrue(self.hand_off(serving="1.9", installed_agent=True))
        self.assertIn("<restart>", self.printed)
        self.assertTrue(any("serving 1.9" in line and "2.0" in line for line in self.printed))

    def test_a_stale_foreground_engine_gets_a_note_not_a_restart(self):
        self.assertTrue(self.hand_off(serving="1.9", installed_agent=False))
        self.assertNotIn("<restart>", self.printed)
        self.assertTrue(any(line.startswith("Note:") and "1.9" in line for line in self.printed))

    def test_no_engine_and_a_declined_offer_leaves_this_command_to_serve(self):
        self.assertFalse(self.hand_off(serving=None, offer=False))
        self.assertEqual(self.opened, [])

    def test_no_engine_and_an_accepted_offer_hands_off_to_the_agent(self):
        self.assertTrue(self.hand_off(serving=None, offer=True))
        self.assertEqual(self.opened, [f"http://localhost:{cli.DEFAULT_APP_PORT}/"])
        self.assertTrue(any("running in the background" in line for line in self.printed))


if __name__ == "__main__":
    unittest.main()

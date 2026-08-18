"""The published preview must stay a preview.

`tests/check_site.py` states the rules and CI runs it before publishing; this
carries them into the normal test run so a change is caught while it is being
made rather than at deploy time.
"""

from __future__ import annotations

import unittest

from tests.check_site import SITE, problems


class HostedSiteTests(unittest.TestCase):
    def test_the_preview_reaches_nothing_and_installs_nothing(self):
        self.assertEqual(problems(), [])

    def test_the_preview_says_where_the_app_actually_runs(self):
        page = (SITE / "index.html").read_text()
        self.assertIn("preview", page.lower())
        # The two commands are the whole point of the page.
        self.assertIn("pip install", page)
        self.assertIn("maniml app", page)

    def test_an_old_installed_shell_lands_somewhere_useful(self):
        """The hosted PWA's start_url was app.html. One may still be installed,
        so that path redirects to the preview instead of returning a 404."""
        self.assertIn('location.replace("./")', (SITE / "app.html").read_text())


if __name__ == "__main__":
    unittest.main()

"""Display-independent tests for the app/scene subprocess handshake."""

import unittest

from maniml.web.app import parse_viewer_launch_line

TOKEN = "NEoPxsQMRSQbR0OjdaE2QBzm6cKFpSNNOV_aYF8KiHU"
URL = f"http://localhost:8689/#token={TOKEN}"


class ViewerLaunchProtocolTests(unittest.TestCase):
    def test_accepts_dedicated_launch_line(self):
        self.assertEqual(
            parse_viewer_launch_line(f"maniml web viewer: {URL}\n"),
            URL,
        )

    def test_rejects_rich_log_line_and_wrapped_token(self):
        wrapped_url = (
            "                    http://localhost:8689/#token="
            + TOKEN[:22]
            + "\n"
        )
        self.assertIsNone(
            parse_viewer_launch_line(
                "[12:56:17] INFO maniml web viewer: viewer.py:86\n"
            )
        )
        self.assertIsNone(parse_viewer_launch_line(wrapped_url))
        self.assertIsNone(
            parse_viewer_launch_line(f"                    {TOKEN[22:]}\n")
        )

    def test_rejects_prefixed_or_suffixed_output(self):
        self.assertIsNone(parse_viewer_launch_line(f"log: {URL}\n"))
        self.assertIsNone(parse_viewer_launch_line(f"maniml web viewer: {URL} extra\n"))


if __name__ == "__main__":
    unittest.main()

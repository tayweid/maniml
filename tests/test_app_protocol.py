"""Display-independent tests for the app/scene subprocess handshake."""

import subprocess
import unittest
from unittest.mock import MagicMock

from maniml.web.app import SceneProcess, parse_viewer_launch_line

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


class SceneProcessLifecycleTests(unittest.TestCase):
    def test_stop_escalates_and_reaps_process_then_closes_pipe(self):
        scene_process = SceneProcess.__new__(SceneProcess)
        scene_process.proc = MagicMock()
        scene_process.proc.poll.return_value = None
        scene_process.proc.wait.side_effect = [
            subprocess.TimeoutExpired("maniml", 3),
            0,
        ]
        scene_process._reader = MagicMock()

        scene_process.stop()

        scene_process.proc.terminate.assert_called_once_with()
        scene_process.proc.kill.assert_called_once_with()
        self.assertEqual(scene_process.proc.wait.call_count, 2)
        scene_process._reader.join.assert_called_once_with(timeout=2)
        scene_process.proc.stdout.close.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()

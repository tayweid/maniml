"""Focused tests for viewer-initiated exports.

The browser is intentionally allowed to choose only a fixed format.  It must
never be able to supply a source path, scene name, command, or shell fragment.
"""

from __future__ import annotations

import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from maniml.web.viewer import WebViewer


class ExportDemo:
    pass


class _ImmediateThread:
    def __init__(self, *, target, args, **_kwargs):
        self.target = target
        self.args = args

    def start(self):
        self.target(*self.args)


class ViewerExportTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.source = Path(self.tempdir.name, "scene.py")
        self.source.write_text("# test scene\n")
        scene = ExportDemo()
        scene._scene_filepath = str(self.source)

        self.viewer = WebViewer.__new__(WebViewer)
        self.viewer.scene = scene
        self.viewer.server = Mock()
        self.viewer._export_lock = threading.Lock()
        self.viewer._export_process = None

    def tearDown(self):
        self.tempdir.cleanup()

    def test_video_export_uses_fixed_argv_without_a_shell(self):
        process = Mock()
        process.wait.return_value = 0

        with (
            patch("maniml.web.viewer.subprocess.Popen", return_value=process) as popen,
            patch("maniml.web.viewer.threading.Thread", _ImmediateThread),
        ):
            self.viewer._start_export("video")

        args, kwargs = popen.call_args
        self.assertEqual(
            args[0][-4:],
            ["maniml", str(self.source), "ExportDemo", "--render"],
        )
        self.assertNotIn("shell", kwargs)
        self.assertEqual(kwargs["cwd"], self.tempdir.name)
        self.viewer.server.broadcast_json.assert_any_call(
            {"type": "export_status", "format": "video", "status": "running"}
        )
        self.viewer.server.broadcast_json.assert_any_call(
            {"type": "export_status", "format": "video", "status": "complete"}
        )

    def test_second_export_is_rejected_while_one_is_running(self):
        running = Mock()
        running.poll.return_value = None
        self.viewer._export_process = running

        with patch("maniml.web.viewer.subprocess.Popen") as popen:
            self.viewer._start_export("web")

        popen.assert_not_called()
        self.viewer.server.broadcast_json.assert_called_once_with(
            {"type": "export_status", "format": "web", "status": "busy"}
        )


if __name__ == "__main__":
    unittest.main()

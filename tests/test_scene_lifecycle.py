"""Failure-path tests for scene-owned resources and recording output."""

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

from maniml.scene.scene import Scene
from maniml.web.export import record_scene


class SceneRunLifecycleTests(unittest.TestCase):
    @patch("maniml.scene.scene.time.sleep")
    def test_web_interaction_pauses_without_clients(self, sleep):
        scene = Scene.__new__(Scene)
        scene.window = object()
        scene.camera = SimpleNamespace(fps=30)
        scene.auto_reload_enabled = False
        scene._file_changed_flag = False
        scene.skip_animations = True
        scene._web_viewer = MagicMock()
        scene._web_viewer.has_clients.return_value = False
        scene.is_window_closing = MagicMock(side_effect=[False, True])
        scene.update_frame = MagicMock()

        scene.interact()

        scene.update_frame.assert_not_called()
        sleep.assert_called_once_with(1 / 30)

    def test_setup_error_aborts_output_and_preserves_original_error(self):
        scene = Scene.__new__(Scene)
        scene.file_writer = MagicMock()
        scene.setup = MagicMock(side_effect=ValueError("scene failed"))
        scene._tear_down_resources = MagicMock()

        with self.assertRaisesRegex(ValueError, "scene failed"):
            scene.run()

        scene.file_writer.begin.assert_called_once_with()
        scene._tear_down_resources.assert_called_once_with(abort=True)

    @patch("maniml.scene.scene.log.exception")
    def test_cleanup_error_does_not_mask_scene_error(self, log_exception):
        scene = Scene.__new__(Scene)
        scene.file_writer = MagicMock()
        scene.setup = MagicMock(side_effect=ValueError("scene failed"))
        scene._tear_down_resources = MagicMock(
            side_effect=RuntimeError("cleanup failed")
        )

        with self.assertRaisesRegex(ValueError, "scene failed"):
            scene.run()

        log_exception.assert_called_once()

    def test_teardown_releases_watcher_and_window_after_encode_failure(self):
        scene = Scene.__new__(Scene)
        scene.stop_skipping = MagicMock()
        scene.file_writer = MagicMock()
        scene.file_writer.finish.side_effect = RuntimeError("encode failed")
        watcher = MagicMock()
        window = MagicMock()
        scene._file_watcher = watcher
        scene.window = window

        with self.assertRaisesRegex(RuntimeError, "encode failed"):
            scene.tear_down()

        watcher.stop.assert_called_once_with()
        window.destroy.assert_called_once_with()
        self.assertIsNone(scene._file_watcher)
        self.assertIsNone(scene.window)

    @patch("maniml.scene.checkpoints.traceback.print_exc")
    def test_render_mode_propagates_animation_error(self, _print_exc):
        scene = self.scene_for_animation_error()
        scene._render_mode = True

        with self.assertRaisesRegex(ValueError, "animation failed"):
            scene.run_next_animation()

    @patch("maniml.scene.checkpoints.traceback.print_exc")
    def test_interactive_mode_keeps_last_checkpoint_after_error(self, _print_exc):
        scene = self.scene_for_animation_error()

        scene.run_next_animation()

        scene.update_frame.assert_called_once_with(dt=0, force_draw=True)

    def test_render_mode_rejects_unparseable_scene(self):
        scene = Scene.__new__(Scene)
        scene._scene_filepath = "scene.py"
        scene._render_mode = True
        scene._present_mode = False
        scene._propagate_animation_errors = False
        scene._get_source_units = MagicMock(return_value=None)

        with self.assertRaisesRegex(RuntimeError, "Cannot parse scene file"):
            scene.run_next_animation()

    @staticmethod
    def scene_for_animation_error():
        scene = Scene.__new__(Scene)
        scene._scene_filepath = "scene.py"
        scene._render_mode = False
        scene._present_mode = False
        scene._propagate_animation_errors = False
        scene.current_animation_index = 0
        scene.animation_checkpoints = [
            {
                "unit_index": None,
                "line_number": 0,
                "state": {},
                "namespace": {},
            }
        ]
        unit = SimpleNamespace(
            index=0,
            end_line=1,
            has_play=True,
            source="raise ValueError('animation failed')",
        )
        scene._get_source_units = MagicMock(return_value=[unit])
        scene.clear = MagicMock()
        scene.restore_state = MagicMock()
        scene.update_frame = MagicMock()
        scene.skip_animations = False
        return scene


class RecordingLifecycleTests(unittest.TestCase):
    def test_export_setup_error_aborts_file_writer(self):
        scene = MagicMock()
        scene.setup.side_effect = ValueError("export failed")

        with self.assertRaisesRegex(ValueError, "export failed"):
            record_scene(scene)

        scene.file_writer.begin.assert_called_once_with()
        scene.file_writer.abort.assert_called_once_with()

    def test_temp_record_error_aborts_insert_and_restores_framebuffer(self):
        scene = Scene.__new__(Scene)
        scene.camera = MagicMock()
        scene.camera.window = object()
        scene.file_writer = MagicMock()

        with self.assertRaisesRegex(ValueError, "record failed"):
            with scene.temp_record():
                raise ValueError("record failed")

        scene.file_writer.begin_insert.assert_called_once_with()
        scene.file_writer.abort.assert_called_once_with()
        self.assertFalse(scene.file_writer.write_to_movie)
        self.assertEqual(
            scene.camera.use_window_fbo.call_args_list,
            [call(False), call(True)],
        )


if __name__ == "__main__":
    unittest.main()

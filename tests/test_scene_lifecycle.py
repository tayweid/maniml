"""Failure-path tests for scene-owned resources and recording output."""

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

from maniml.scene.scene import Scene
from maniml.web.export import record_scene


class PacingClockTests(unittest.TestCase):
    @patch("maniml.scene.scene.time.monotonic", return_value=250.0)
    def test_restore_rebases_pacing_on_restored_scene_time(self, monotonic):
        """A restore can move scene time backward or forward; neither
        direction may leak into the next wall-clock sleep deadline."""
        scene = Scene.__new__(Scene)
        scene.time = 100.0
        scene.virtual_animation_start_time = 20.0
        scene.real_animation_start_time = 40.0
        scene._timeline_group = None
        scene.assemble_render_groups = MagicMock()

        state = MagicMock()
        state.restore_scene.side_effect = lambda target: setattr(target, "time", 7.0)

        scene.restore_state(state)

        self.assertEqual(scene.virtual_animation_start_time, 7.0)
        self.assertEqual(scene.real_animation_start_time, 250.0)
        monotonic.assert_called_once_with()


class WebGpuNativeBypassTests(unittest.TestCase):
    @staticmethod
    def scene(can_skip_native_capture):
        scene = Scene.__new__(Scene)
        scene.time = 0.0
        scene.mobjects = []
        scene.render_groups = []
        scene.window = None
        scene.skip_animations = True
        scene.camera = MagicMock()
        scene._web_viewer = MagicMock()
        scene._web_viewer.can_skip_native_capture.return_value = (
            can_skip_native_capture)
        return scene

    def test_supported_solo_webgpu_skips_native_capture(self):
        scene = self.scene(True)

        scene.update_frame(dt=0, force_draw=True)

        scene.camera.capture.assert_not_called()
        scene._web_viewer.on_frame_rendered.assert_called_once_with()

    def test_pixel_or_unsupported_content_keeps_native_capture(self):
        scene = self.scene(False)

        scene.update_frame(dt=0, force_draw=True)

        scene.camera.capture.assert_called_once_with()
        scene._web_viewer.on_frame_rendered.assert_called_once_with()


class MobjectListTransactionTests(unittest.TestCase):
    def test_related_membership_changes_assemble_once(self):
        scene = Scene.__new__(Scene)
        scene._mobject_list_mutation_depth = 0
        scene.mobjects = [object()]
        scene.assemble_render_groups = MagicMock()

        with scene.mobject_list_transaction():
            scene.clear()
            scene.clear()

        self.assertEqual(scene.mobjects, [])
        scene.assemble_render_groups.assert_called_once_with()

    def test_entrance_animation_is_batched_before_its_first_frame(self):
        """An entrance mobject is added by animation.begin(), after play starts.

        Rebatching around play() used to run too early and omitted that mobject
        from every animation frame. The transaction must commit inside
        begin_animations(), after the entrance mobject joins the scene.
        """
        scene = Scene.__new__(Scene)
        scene._mobject_list_mutation_depth = 0
        scene._mobject_list_mutation_dirty = False
        scene.mobjects = []
        scene.id_to_mobject_map = {}
        scene.assemble_render_groups = MagicMock()
        mobject = MagicMock()
        mobject.get_family.return_value = [mobject]
        animation = MagicMock(mobject=mobject)

        scene.begin_animations([animation])

        animation.begin.assert_called_once_with()
        self.assertEqual(scene.mobjects, [mobject])
        scene.assemble_render_groups.assert_called_once_with()


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
            has_stop=True,
            source="raise ValueError('animation failed')",
        )
        scene._get_source_units = MagicMock(return_value=[unit])
        scene.clear = MagicMock()
        scene.restore_state = MagicMock()
        scene.assemble_render_groups = MagicMock()
        scene._mobject_list_mutation_depth = 0
        scene.update_frame = MagicMock()
        scene.skip_animations = False
        return scene


class LiveSoundTests(unittest.TestCase):
    """add_sound() plays through the system player exactly when there is a
    live audience: a pyglet window, or a web viewer with a client. Render,
    export (whose recorder stands in as _web_viewer without has_clients),
    and headless runs stay silent."""

    @staticmethod
    def sounding_scene():
        scene = Scene.__new__(Scene)
        scene.skip_animations = False
        scene.get_time = MagicMock(return_value=0.0)
        scene.file_writer = MagicMock()
        scene.window = None
        scene._web_viewer = None
        return scene

    @patch("maniml.scene.scene.play_sound")
    def test_window_mode_plays_live(self, play_sound):
        scene = self.sounding_scene()
        scene.window = object()
        scene.add_sound("click.wav")
        play_sound.assert_called_once_with("click.wav")
        scene.file_writer.add_sound.assert_called_once()

    @patch("maniml.scene.scene.play_sound")
    def test_web_viewer_plays_only_with_a_client(self, play_sound):
        scene = self.sounding_scene()
        scene.window = scene._web_viewer = MagicMock()
        scene._web_viewer.has_clients.return_value = True
        scene.add_sound("click.wav")
        play_sound.assert_called_once_with("click.wav")

        play_sound.reset_mock()
        scene._web_viewer.has_clients.return_value = False
        scene.add_sound("click.wav")
        play_sound.assert_not_called()

    @patch("maniml.scene.scene.play_sound")
    def test_export_recorder_and_headless_stay_silent(self, play_sound):
        scene = self.sounding_scene()
        scene.window = scene._web_viewer = SimpleNamespace()  # no has_clients
        scene.add_sound("click.wav")
        play_sound.assert_not_called()

        scene = self.sounding_scene()  # headless: no window, no viewer
        scene.add_sound("click.wav")
        play_sound.assert_not_called()
        scene.file_writer.add_sound.assert_called_once()

    @patch("maniml.scene.scene.play_sound")
    def test_fast_forwards_stay_silent(self, play_sound):
        scene = self.sounding_scene()
        scene.window = object()
        scene.skip_animations = True
        scene.add_sound("click.wav")
        play_sound.assert_not_called()
        scene.file_writer.add_sound.assert_not_called()


class LoopPauseTests(unittest.TestCase):
    """pause(loop=True) makes the live viewer replay the whole stretch —
    from the previous pausepoint — while parked on it; everywhere else it
    is an ordinary pausepoint."""

    @staticmethod
    def parked_scene(index=4, loop=True, with_earlier_stop=True):
        scene = Scene.__new__(Scene)
        scene.skip_animations = False
        scene._is_playing = False
        scene.current_animation_index = index
        scene.animation_checkpoints = [
            {"unit_index": -1},
            {"unit_index": 0},
            {"unit_index": 1, "stop": with_earlier_stop},
            {"unit_index": 2},
            {"unit_index": 3, "stop": True, "loop": loop},
        ]

        def advance():
            scene.current_animation_index += 1
        scene.run_next_animation = MagicMock(side_effect=advance)
        return scene

    def test_parked_on_a_loop_pause_replays_its_stretch(self):
        scene = self.parked_scene()
        scene._maybe_replay_loop_pause()
        # rewound to the previous stop (2), then run back up to the loop
        # pausepoint: two units re-run, parked at 4 again for the next lap
        self.assertEqual(scene.run_next_animation.call_count, 2)
        self.assertEqual(scene.current_animation_index, 4)

    def test_without_an_earlier_stop_the_lap_starts_at_the_beginning(self):
        scene = self.parked_scene(with_earlier_stop=False)
        scene._maybe_replay_loop_pause()
        self.assertEqual(scene.run_next_animation.call_count, 4)
        self.assertEqual(scene.current_animation_index, 4)

    def test_an_ordinary_pausepoint_stays_parked(self):
        scene = self.parked_scene(loop=False)
        scene._maybe_replay_loop_pause()
        self.assertEqual(scene.current_animation_index, 4)
        scene.run_next_animation.assert_not_called()

    def test_no_replay_while_playing_or_fast_forwarding(self):
        scene = self.parked_scene()
        scene._is_playing = True
        scene._maybe_replay_loop_pause()
        scene.run_next_animation.assert_not_called()

        scene = self.parked_scene()
        scene.skip_animations = True
        scene._maybe_replay_loop_pause()
        scene.run_next_animation.assert_not_called()

    def test_checkpoint_zero_never_loops(self):
        scene = self.parked_scene(index=0)
        scene._maybe_replay_loop_pause()
        scene.run_next_animation.assert_not_called()

    def test_a_stalled_replay_gives_up_instead_of_spinning(self):
        scene = self.parked_scene()
        scene.run_next_animation = MagicMock()   # no progress (error path)
        scene._maybe_replay_loop_pause()
        scene.run_next_animation.assert_called_once_with()

    def test_interact_only_replays_with_a_client_attached(self):
        """The loop is a live-viewer behavior: the interact loop consults the
        driver only on passes where a browser client is connected."""
        scene = Scene.__new__(Scene)
        scene.window = object()
        scene.camera = SimpleNamespace(fps=30)
        scene.auto_reload_enabled = False
        scene._file_changed_flag = False
        scene.skip_animations = True
        scene._web_viewer = MagicMock()
        scene._web_viewer.has_clients.return_value = True
        scene.is_window_closing = MagicMock(side_effect=[False, True])
        scene.update_frame = MagicMock()
        scene._maybe_replay_loop_pause = MagicMock()

        scene.interact()

        scene._maybe_replay_loop_pause.assert_called_once_with()


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

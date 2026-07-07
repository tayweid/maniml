"""Integration tests for the checkpoint system and auto-reload handling.

Runs a real Scene headlessly (window=None, skip_animations=True) against
a temp scene file, then simulates file saves the way the watcher thread
reports them.
"""

import os
import tempfile
import textwrap
import unittest

from manim.__main__ import load_scene_module

BASE = textwrap.dedent('''\
    from manim import *

    HELPER_SHIFT = 0.5

    class EditScene(Scene):
        def construct(self):
            circle = Circle()
            self.play(Create(circle), run_time=0.05)
            for i in range(2):
                circle.shift(RIGHT * HELPER_SHIFT)
                self.play(circle.animate.scale(1.1), run_time=0.05)
            square = Square()
            self.play(Transform(circle, square), run_time=0.05)
            self.wait(0.05)
''')


class CheckpointSceneTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.scene_file = os.path.join(self.tmpdir.name, 'edit_scene.py')
        self.write_scene(BASE)
        module = load_scene_module(self.scene_file)
        self.scene = module.EditScene(window=None)
        self.scene._scene_filepath = self.scene_file
        self.scene.skip_animations = True
        self.scene.setup()
        self.scene._create_checkpoint_zero()

    def tearDown(self):
        self.tmpdir.cleanup()

    def write_scene(self, content):
        with open(self.scene_file, 'w') as f:
            f.write(content)

    def save(self, content, earliest_changed_line):
        """Simulate the watcher reporting a file save."""
        self.write_scene(content)
        self.scene._on_file_changed({'earliest_changed_line': earliest_changed_line})
        self.scene._file_changed_flag = False
        self.scene._handle_file_change()

    def run_all(self):
        # unit 0, loop unit (2 plays), transform, tail wait -> index 5
        for _ in range(5):
            self.scene.run_next_animation()


class TestForwardExecution(CheckpointSceneTest):
    def test_full_run_produces_expected_checkpoints(self):
        self.run_all()
        scene = self.scene
        self.assertEqual(scene.current_animation_index, 5)
        self.assertEqual(
            [cp['unit_index'] for cp in scene.animation_checkpoints],
            [-1, 0, 1, 1, 2, 3],
        )
        self.assertIn('HELPER_SHIFT', scene.animation_checkpoints[0]['namespace'])
        self.assertIn('circle', scene.animation_checkpoints[1]['namespace'])

    def test_right_arrow_past_end_is_noop(self):
        self.run_all()
        n = len(self.scene.animation_checkpoints)
        self.scene.run_next_animation()
        self.assertEqual(self.scene.current_animation_index, 5)
        self.assertEqual(len(self.scene.animation_checkpoints), n)

    def test_rerun_after_jump_back_replaces_checkpoints(self):
        self.run_all()
        scene = self.scene
        scene.current_animation_index = 1
        scene.restore_state(scene.animation_checkpoints[1]['state'])
        scene.run_next_animation()  # re-runs the loop unit
        self.assertEqual(scene.current_animation_index, 3)
        self.assertEqual(len(scene.animation_checkpoints), 6)


class TestFileChange(CheckpointSceneTest):
    def test_edit_inside_construct_truncates_and_replays(self):
        self.run_all()
        edited = BASE.replace(
            "        square = Square()\n",
            "        marker = 123\n        square = Square()\n",
        )
        line = edited.splitlines().index('        marker = 123') + 1
        self.save(edited, line)

        scene = self.scene
        # replayed through the edited (transform) unit, not the tail
        self.assertEqual(scene.current_animation_index, 4)
        cp = scene.animation_checkpoints[4]
        self.assertEqual(cp['unit_index'], 2)
        self.assertEqual(cp['namespace'].get('marker'), 123)

    def test_edit_module_constant_restarts_from_reloaded_module(self):
        self.run_all()
        edited = BASE.replace("HELPER_SHIFT = 0.5", "HELPER_SHIFT = 2.0")
        self.save(edited, 3)

        scene = self.scene
        self.assertEqual(
            scene.animation_checkpoints[0]['namespace'].get('HELPER_SHIFT'), 2.0)
        # position restored to the unit the user was on (the tail)
        final = scene.animation_checkpoints[scene.current_animation_index]
        self.assertEqual(final['unit_index'], 3)
        self.assertEqual(final['namespace'].get('HELPER_SHIFT'), 2.0)

    def test_syntax_error_save_leaves_state_untouched(self):
        self.run_all()
        n = len(self.scene.animation_checkpoints)
        idx = self.scene.current_animation_index
        self.save(BASE + "\ndef broken(:\n", 16)
        self.assertEqual(len(self.scene.animation_checkpoints), n)
        self.assertEqual(self.scene.current_animation_index, idx)

    def test_runtime_error_in_edited_unit_rolls_back(self):
        self.run_all()
        edited = BASE.replace(
            "        square = Square()\n",
            "        raise ValueError('boom')\n        square = Square()\n",
        )
        line = edited.splitlines().index("        raise ValueError('boom')") + 1
        self.save(edited, line)
        scene = self.scene
        # rolled back to the last checkpoint before the broken unit
        self.assertEqual(scene.current_animation_index, 3)
        self.assertEqual(
            scene.animation_checkpoints[scene.current_animation_index]['unit_index'], 1)


if __name__ == '__main__':
    unittest.main()

"""Integration tests for the checkpoint system and auto-reload handling.

Runs a real Scene headlessly (window=None, skip_animations=True) against
a temp scene file, then simulates file saves the way the watcher thread
reports them.
"""

import os
import tempfile
import textwrap
import unittest

import numpy as np

from maniml.__main__ import load_scene_module
from maniml.event_constants import WindowKeys as PygletWindowKeys

BASE = textwrap.dedent('''\
    from maniml import *

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
        # Each headless scene owns a standalone GL context; macOS caps
        # them per process, so a suite that leaks one per test starves
        # the GPU tests that run after it.
        self.scene.camera.ctx.release()
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


class TestNavigation(CheckpointSceneTest):
    def test_jump_back_restores_copies_not_history(self):
        self.run_all()
        scene = self.scene
        checkpoint = scene.animation_checkpoints[4]
        stored = [m.get_center().copy() for m in checkpoint['state'].mobjects]

        scene.on_key_press(PygletWindowKeys.UP, 0)  # index 5 -> 4
        self.assertEqual(scene.current_animation_index, 4)
        # the on-screen mobjects must be copies, not the stored ones
        for live in scene.mobjects:
            self.assertNotIn(live, checkpoint['state'].mobjects)

        # mutating the live scene must not touch the stored history
        for live in scene.mobjects:
            live.shift(np.array([5.0, 5.0, 0.0]))
        for mob, pos in zip(checkpoint['state'].mobjects, stored):
            self.assertTrue(np.allclose(mob.get_center(), pos),
                            "stored checkpoint mobject moved with the live scene")

    def test_left_arrow_reverses_one_checkpoint(self):
        self.run_all()
        scene = self.scene
        n = len(scene.animation_checkpoints)
        scene.on_key_press(PygletWindowKeys.LEFT, 0)
        self.assertEqual(scene.current_animation_index, 4)
        # the reverse transition itself must not create checkpoints
        self.assertEqual(len(scene.animation_checkpoints), n)
        # display landed exactly on (a copy of) the target state
        target = scene.animation_checkpoints[4]['state']
        self.assertEqual(len(scene.mobjects), len(target.mobjects))
        for live in scene.mobjects:
            self.assertNotIn(live, target.mobjects)

    def test_undo_actually_restores(self):
        self.run_all()
        scene = self.scene
        mob = scene.mobjects[-1]
        before = mob.get_center().copy()
        scene.save_state()
        mob.shift(np.array([3.0, 0.0, 0.0]))
        scene.undo()
        restored = scene.mobjects[-1]
        self.assertTrue(np.allclose(restored.get_center(), before),
                        "undo did not restore the pre-mutation state")


class TestReverseTiming(CheckpointSceneTest):
    """Stepping back should take as long as the step forward took. It cannot
    be worked out at the time — the animation object is gone — so the forward
    play records its own run_time on the checkpoint it saves."""

    def test_a_checkpoint_records_what_it_took_to_reach(self):
        self.run_all()
        recorded = [c.get('run_time') for c in self.scene.animation_checkpoints]
        # Checkpoint 0 was never played into, and the tail unit is a wait()
        # rather than a play, so neither has a span to record.
        self.assertIsNone(recorded[0])
        self.assertIsNone(recorded[-1], "a wait() recorded a play's span")
        self.assertEqual(len(recorded[1:-1]), 4, recorded)
        for run_time in recorded[1:-1]:
            self.assertAlmostEqual(run_time, 0.05, places=6)

    def test_stepping_back_takes_the_span_it_took_to_get_there(self):
        self.run_all()
        # Undoing the step that landed on index 1 means replaying its 0.05s.
        self.assertAlmostEqual(self.scene._reverse_run_time(0), 0.05, places=6)

    def test_a_checkpoint_with_no_recorded_span_falls_back(self):
        """Checkpoint 0 was never played into, and a scene saved before this
        was recorded has None there."""
        from maniml.scene.interaction import DEFAULT_REVERSE_RUN_TIME

        self.run_all()
        self.scene.animation_checkpoints[1]['run_time'] = None
        self.assertEqual(self.scene._reverse_run_time(0), DEFAULT_REVERSE_RUN_TIME)

    def test_a_long_build_is_not_replayed_in_full_every_time(self):
        """LEFT is also how you move around a scene."""
        from maniml.scene.interaction import MAX_REVERSE_RUN_TIME

        self.run_all()
        self.scene.animation_checkpoints[1]['run_time'] = 30.0
        self.assertEqual(self.scene._reverse_run_time(0), MAX_REVERSE_RUN_TIME)


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

    def test_adding_the_first_pause_rebuilds_pause_anchored(self):
        """The first authored pause moves every unit boundary at once, so
        the save rebuilds the scene rather than re-anchoring surgically."""
        self.run_all()
        edited = BASE.replace(
            "        square = Square()\n",
            "        self.pause()\n        square = Square()\n",
        )
        line = edited.splitlines().index('        self.pause()') + 1
        self.save(edited, line)
        scene = self.scene
        self.assertTrue(scene._pause_anchored_mode)
        # One pause unit (everything through the pause), one tail
        self.assertEqual(
            [cp['unit_index'] for cp in scene.animation_checkpoints],
            [-1, 0, 1],
        )


PAUSE_BASE = textwrap.dedent('''\
    from maniml import *

    class PauseScene(Scene):
        def construct(self):
            circle = Circle()
            self.play(Create(circle), run_time=0.05)
            self.play(circle.animate.shift(RIGHT), run_time=0.05)
            self.pause()
            square = Square()
            self.play(Transform(circle, square), run_time=0.05)
            self.pause()
            self.wait(0.05)
''')


class PauseAnchoredSceneTest(unittest.TestCase):
    """The checkpoint system in a pause-anchored file: plays extend the
    current stretch, only self.pause() saves."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.scene_file = os.path.join(self.tmpdir.name, 'pause_scene.py')
        self.write_scene(PAUSE_BASE)
        module = load_scene_module(self.scene_file)
        self.scene = module.PauseScene(window=None)
        self.scene._scene_filepath = self.scene_file
        self.scene.skip_animations = True
        self.scene.setup()
        self.scene._create_checkpoint_zero()

    def tearDown(self):
        self.scene.camera.ctx.release()
        self.tmpdir.cleanup()

    def write_scene(self, content):
        with open(self.scene_file, 'w') as f:
            f.write(content)

    def save(self, content, earliest_changed_line):
        self.write_scene(content)
        self.scene._on_file_changed({'earliest_changed_line': earliest_changed_line})
        self.scene._file_changed_flag = False
        self.scene._handle_file_change()

    def run_all(self):
        # pause unit (2 plays), pause unit, tail wait -> index 3
        for _ in range(3):
            self.scene.run_next_animation()

    def test_checkpoints_save_only_at_pauses(self):
        self.run_all()
        scene = self.scene
        self.assertEqual(scene.current_animation_index, 3)
        self.assertEqual(
            [cp['unit_index'] for cp in scene.animation_checkpoints],
            [-1, 0, 1, 2],
        )
        self.assertIn('circle', scene.animation_checkpoints[1]['namespace'])
        # past the end is a no-op
        scene.run_next_animation()
        self.assertEqual(scene.current_animation_index, 3)

    def test_a_stretch_records_its_accumulated_span(self):
        self.run_all()
        recorded = [c.get('run_time') for c in self.scene.animation_checkpoints]
        self.assertIsNone(recorded[0])
        self.assertAlmostEqual(recorded[1], 0.10, places=6)  # both plays
        self.assertAlmostEqual(recorded[2], 0.05, places=6)
        self.assertIsNone(recorded[3], "a wait-only tail recorded a span")

    def test_edit_replays_from_the_previous_pause(self):
        self.run_all()
        edited = PAUSE_BASE.replace(
            "        square = Square()\n",
            "        marker = 123\n        square = Square()\n",
        )
        line = edited.splitlines().index('        marker = 123') + 1
        self.save(edited, line)
        scene = self.scene
        # checkpoint 1 (first pause) survived; the edited stretch replayed
        self.assertEqual(scene.current_animation_index, 2)
        cp = scene.animation_checkpoints[2]
        self.assertEqual(cp['unit_index'], 1)
        self.assertEqual(cp['namespace'].get('marker'), 123)


if __name__ == '__main__':
    unittest.main()


TRACKER = textwrap.dedent('''\
    from maniml import *

    class TrackerScene(Scene):
        def construct(self):
            t = ValueTracker(0)
            dot = always_redraw(lambda: Dot([t.get_value(), 0, 0]))
            def reader(tr=t):                      # captured by default arg
                return Dot([tr.get_value(), 1, 0])
            dot2 = always_redraw(reader)
            self.add(dot, dot2)
            counter = [0]
            def bump():                            # writes a namespace variable
                counter[0] += 1
                t.set_value(t.get_value() + 1)
            self.play(FadeIn(Square()), run_time=0.05)
            self.play(t.animate.set_value(3), run_time=0.05)
            bump()
            self.play(FadeIn(Circle()), run_time=0.05)
            self.wait(0.05)
''')


class TestTrackerAcrossUnits(unittest.TestCase):
    """A ValueTracker read by always_redraw callbacks defined in an earlier
    unit must still drive the drawing after a checkpoint snapshot: the
    snapshot copies the tracker, so the callbacks have to read the copy."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.scene_file = os.path.join(self.tmpdir.name, 'tracker_scene.py')
        with open(self.scene_file, 'w') as f:
            f.write(TRACKER)
        module = load_scene_module(self.scene_file)
        self.scene = module.TrackerScene(window=None)
        self.scene._scene_filepath = self.scene_file
        self.scene.skip_animations = True
        self.scene.setup()
        self.scene._create_checkpoint_zero()

    def tearDown(self):
        self.scene.camera.ctx.release()
        self.tmpdir.cleanup()

    def assert_follows(self, x):
        ns = self.scene._live_namespace
        self.assertAlmostEqual(ns['t'].get_value(), x)
        for name in ('dot', 'dot2'):
            mob = ns[name]
            mob.update(0)                    # run the updater once more
            self.assertAlmostEqual(mob.get_center()[0], x, places=3, msg=name)
            # and it is the on-screen one, not a detached original
            self.assertTrue(any(m is mob for m in self.scene.mobjects), name)

    def test_redraw_follows_the_copied_tracker(self):
        self.scene.run_next_animation()      # unit 0: build + FadeIn(Square)
        self.scene.run_next_animation()      # unit 1: t -> 3 across a snapshot
        self.assert_follows(3.0)

    def test_helper_writes_reach_the_live_namespace(self):
        for _ in range(3):                   # through the unit with bump()
            self.scene.run_next_animation()
        ns = self.scene._live_namespace
        self.assertEqual(ns['counter'], [1])
        self.assert_follows(4.0)

    def test_two_generations_back_and_forward(self):
        # forward, jump back, forward again: the rebinding must chain across
        # save (live -> stored) and replay (stored -> fresh) generations
        self.scene.run_next_animation()
        self.scene.run_next_animation()
        self.assert_follows(3.0)
        self.scene.current_animation_index = 1
        self.scene.restore_state(self.scene.animation_checkpoints[1]['state'])
        self.scene.run_next_animation()      # re-run unit 1 from the stored copy
        self.assert_follows(3.0)
        self.scene.run_next_animation()      # and on through bump()
        self.assert_follows(4.0)


class TestReverseMorphWithUpdaters(unittest.TestCase):
    """The LEFT-arrow morph is a display-only interpolation between two
    frozen states: updaters must be suspended on both sides while it plays
    (an always_redraw otherwise rebuilds itself at full opacity every frame,
    fighting the fade and glitching the geometry once its point count
    shifts under the Transform), and whatever lands on screen must wake up
    again."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.scene_file = os.path.join(self.tmpdir.name, 'tracker_scene.py')
        with open(self.scene_file, 'w') as f:
            f.write(TRACKER)
        module = load_scene_module(self.scene_file)
        self.scene = module.TrackerScene(window=None)
        self.scene._scene_filepath = self.scene_file
        self.scene.skip_animations = True
        self.scene.setup()
        self.scene._create_checkpoint_zero()

    def tearDown(self):
        self.scene.camera.ctx.release()
        self.tmpdir.cleanup()

    def test_morph_suspends_both_sides_and_landing_resumes(self):
        scene = self.scene
        scene.run_next_animation()           # dots + square on screen
        scene.run_next_animation()           # t -> 3, redraws following it

        seen = {}

        def spy_play(*anims, **kwargs):
            seen['anims'] = [a.mobject.updating_suspended for a in anims]
            seen['screen'] = [
                m.updating_suspended for m in scene.mobjects if m.has_updaters()
            ]

        scene.play = spy_play
        scene.current_animation_index = 1
        scene._play_reverse_to(1)

        self.assertTrue(seen['anims'], "morph built no animations")
        self.assertTrue(all(seen['anims']),
                        "a morphing mobject still had updaters running")
        self.assertTrue(all(seen['screen']),
                        "an on-screen updater survived into the morph")
        # the landed state's updaters are awake again
        landed = [m for m in scene.mobjects if m.has_updaters()]
        self.assertTrue(landed, "restore lost the updaters entirely")
        self.assertFalse(any(m.updating_suspended for m in landed),
                         "landed mobjects stayed suspended")

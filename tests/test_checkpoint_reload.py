"""Integration tests for the checkpoint system and auto-reload handling.

Runs a real Scene headlessly (window=None, skip_animations=True) against
a temp scene file, then simulates file saves the way the watcher thread
reports them.
"""

import os
import random
import tempfile
import textwrap
import unittest
from unittest.mock import MagicMock

import numpy as np

from maniml.__main__ import load_scene_module
from maniml.event_constants import WindowKeys

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

    def test_right_after_jump_restores_retained_checkpoint(self):
        self.run_all()
        scene = self.scene
        original_units = [cp['unit_index'] for cp in scene.animation_checkpoints]
        original_checkpoints = list(scene.animation_checkpoints)
        scene._restore_checkpoint_for_display(1)
        scene.run_next_animation = MagicMock(
            wraps=scene.run_next_animation)

        scene.advance_to_next_pausepoint()

        self.assertEqual(scene.current_animation_index, 2)
        self.assertEqual(len(scene.animation_checkpoints), 6)
        self.assertEqual(
            [cp['unit_index'] for cp in scene.animation_checkpoints],
            original_units,
        )
        for retained, original in zip(scene.animation_checkpoints, original_checkpoints):
            self.assertIs(retained, original)
        self.assertEqual(scene.frontier_index, 5)
        scene.run_next_animation.assert_not_called()


class TestNavigation(CheckpointSceneTest):
    def test_render_batches_are_not_checkpoint_parents(self):
        self.run_all()

        for checkpoint in self.scene.animation_checkpoints[1:]:
            # BASE keeps one top-level content mobject throughout.  It has no
            # semantic parent; ephemeral render aggregation must not add one.
            content = checkpoint['state'].mobjects[-1]
            self.assertEqual(content.parents, [])

    def test_restore_assembles_render_batches_once(self):
        self.scene.run_next_animation()
        self.scene.assemble_render_groups = MagicMock(
            wraps=self.scene.assemble_render_groups)

        self.scene._restore_checkpoint_for_display(0)

        self.scene.assemble_render_groups.assert_called_once_with()

    def test_checkpoint_restores_python_and_numpy_rng_for_execution(self):
        checkpoint = self.scene.animation_checkpoints[0]

        python_rng = random.Random()
        python_rng.setstate(checkpoint['python_random_state'])
        expected_python = python_rng.random()

        live_numpy_state = np.random.get_state()
        try:
            np.random.set_state(checkpoint['numpy_random_state'])
            expected_numpy = np.random.random()
        finally:
            np.random.set_state(live_numpy_state)

        random.random()
        np.random.random()
        self.scene._restore_checkpoint_random_state(checkpoint)

        self.assertEqual(random.random(), expected_python)
        self.assertEqual(np.random.random(), expected_numpy)

    def test_jump_back_restores_copies_not_history(self):
        self.run_all()
        scene = self.scene
        checkpoint = scene.animation_checkpoints[4]
        stored = [m.get_center().copy() for m in checkpoint['state'].mobjects]

        scene.on_key_press(WindowKeys.DOWN, 0)  # index 5 -> 4
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

    def test_left_arrow_jumps_back_one_checkpoint(self):
        """LEFT is an instant jump, deliberately unanimated: a state morph
        cannot truly reverse an animation, so navigation does not pretend
        to (see DECISIONS.md, "Backward navigation is a jump")."""
        self.run_all()
        scene = self.scene
        n = len(scene.animation_checkpoints)
        scene.on_key_press(WindowKeys.LEFT, 0)
        self.assertEqual(scene.current_animation_index, 4)
        # navigating back must not create checkpoints
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

    def test_replay_to_unit_starts_at_the_frontier(self):
        # A future-chip click replays source. Parked behind the frontier —
        # on the loop's interior checkpoint — the replay must first return
        # to the frontier: executing from the interior cannot resume the
        # loop mid-statement, so it would overwrite the loop's second
        # checkpoint with a wrong-lineage endpoint (missing that
        # iteration's shift).
        self.scene.run_next_animation()  # unit 0: Create
        self.scene.run_next_animation()  # unit 1: the whole loop, 2 saves
        self.scene._restore_checkpoint_for_display(2)

        self.scene._replay_to_unit(2)  # the future-chip path

        units = [c.get('unit_index') for c in self.scene.animation_checkpoints]
        self.assertEqual(units, [-1, 0, 1, 1, 2],
                         "replay from an interior checkpoint rewrote history")
        loop_end = self.scene.animation_checkpoints[3]['namespace']['circle']
        self.assertAlmostEqual(
            float(loop_end.get_center()[0]), 1.0, places=6,
            msg="loop endpoint lost its second iteration's shift")
        self.assertEqual(self.scene.current_animation_index, 4)
        self.assertEqual(self.scene.frontier_index, 4)


class TestRecordedSpans(CheckpointSceneTest):
    """Every play records its run_time on the checkpoint it saves. Nothing
    else can supply it later — the animation object is gone by then — and
    the recorded-stream playback layer (TODO.md) will need the spans."""

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
        """The first authored pause inserts a unit boundary and flips the
        anchoring mode, so the save rebuilds the scene rather than
        re-anchoring surgically."""
        self.run_all()
        edited = BASE.replace(
            "        square = Square()\n",
            "        self.pause()\n        square = Square()\n",
        )
        line = edited.splitlines().index('        self.pause()') + 1
        self.save(edited, line)
        scene = self.scene
        self.assertTrue(scene._pause_anchored_mode)
        # Units: create-play, loop (two plays), the pause, transform-play,
        # wait tail. The rebuild replays back to the transform the user
        # was on; the pause's checkpoint is the one flagged as a stop.
        self.assertEqual(
            [cp['unit_index'] for cp in scene.animation_checkpoints],
            [-1, 0, 1, 1, 2, 3],
        )
        self.assertEqual(
            [bool(cp.get('stop')) for cp in scene.animation_checkpoints],
            [False, False, False, False, True, False],
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
        # play, play, pause, play, pause, tail wait -> index 6
        for _ in range(6):
            self.scene.run_next_animation()

    def test_every_play_checkpoints_and_pauses_mark_the_stops(self):
        self.run_all()
        scene = self.scene
        self.assertEqual(scene.current_animation_index, 6)
        self.assertEqual(
            [cp['unit_index'] for cp in scene.animation_checkpoints],
            [-1, 0, 1, 2, 3, 4, 5],
        )
        self.assertEqual(
            [bool(cp.get('stop')) for cp in scene.animation_checkpoints],
            [False, False, False, True, False, True, False],
        )
        self.assertIn('circle', scene.animation_checkpoints[1]['namespace'])
        # past the end is a no-op
        scene.run_next_animation()
        self.assertEqual(scene.current_animation_index, 6)

    def test_right_runs_a_stretch_and_rests_at_the_pause(self):
        scene = self.scene
        scene.advance_to_next_pausepoint()   # both plays + the pause
        self.assertEqual(scene.current_animation_index, 3)
        self.assertTrue(scene.animation_checkpoints[3].get('stop'))
        scene.advance_to_next_pausepoint()   # the transform + its pause
        self.assertEqual(scene.current_animation_index, 5)
        scene.advance_to_next_pausepoint()   # tail runs, then end
        self.assertEqual(scene.current_animation_index, 6)
        scene.advance_to_next_pausepoint()   # no-op at the end
        self.assertEqual(scene.current_animation_index, 6)

    def test_right_before_frontier_restores_the_next_pause(self):
        self.run_all()
        scene = self.scene
        scene._restore_checkpoint_for_display(0)
        scene.run_next_animation = MagicMock(
            wraps=scene.run_next_animation)

        scene.advance_to_next_pausepoint()

        self.assertEqual(scene.current_animation_index, 3)
        self.assertEqual(scene.frontier_index, 6)
        scene.run_next_animation.assert_not_called()

    def test_plays_record_their_spans_and_pauses_record_none(self):
        self.run_all()
        recorded = [c.get('run_time') for c in self.scene.animation_checkpoints]
        self.assertIsNone(recorded[0])
        for play_index in (1, 2, 4):
            self.assertAlmostEqual(recorded[play_index], 0.05, places=6)
        for other in (3, 5, 6):   # pauses and the wait-only tail
            self.assertIsNone(recorded[other])

    def test_left_jumps_to_the_previous_pausepoint(self):
        self.run_all()
        scene = self.scene
        scene.current_animation_index = 5    # parked at the second pause
        scene._reverse_to_previous_pausepoint()
        # one instant jump over the interior play, landing on the exact
        # state of the previous stop
        self.assertEqual(scene.current_animation_index, 3)
        self.assertTrue(scene.animation_checkpoints[3].get('stop'))
        self.assertIn('circle', scene._live_namespace)
        # and from a play checkpoint in a pause-less spot of history,
        # LEFT still rests at the previous stop, not one play back
        scene.current_animation_index = 6    # the tail checkpoint
        scene._reverse_to_previous_pausepoint()
        self.assertEqual(scene.current_animation_index, 5)

    def test_edit_replays_from_the_previous_pause(self):
        self.run_all()
        edited = PAUSE_BASE.replace(
            "        square = Square()\n",
            "        marker = 123\n        square = Square()\n",
        )
        line = edited.splitlines().index('        marker = 123') + 1
        self.save(edited, line)
        scene = self.scene
        # checkpoints through the first pause survived; the edited unit
        # (the transform play) replayed
        self.assertEqual(scene.current_animation_index, 4)
        cp = scene.animation_checkpoints[4]
        self.assertEqual(cp['unit_index'], 3)
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


GHOST = textwrap.dedent('''\
    from maniml import *

    class GhostScene(Scene):
        def construct(self):
            squares = [Square(side_length=0.5).shift(RIGHT * i) for i in range(3)]
            group = VGroup(*squares)
            self.add(group)
            for i in range(2):
                # Storing the builders in a variable puts them in the
                # checkpoint namespace; this once broke deepcopy identity
                update_squares = [s.animate.set_fill(BLUE, 1) for s in squares]
                self.play(*update_squares, run_time=0.1)
            self.play(group.animate.to_edge(UP))
            self.wait()
''')


class TestGhostMobjects(unittest.TestCase):
    """Ported from the retired windowed scenario tests/interactive/
    ghost_regression.py (2026-09-02): animating a group whose .animate
    builders were stored in a namespace variable must not leave a stale
    duplicate behind, and RIGHT over a retained checkpoint must restore
    it rather than re-run the source beside the old copy."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.scene_file = os.path.join(self.tmpdir.name, 'ghost_scene.py')
        with open(self.scene_file, 'w') as f:
            f.write(GHOST)
        module = load_scene_module(self.scene_file)
        self.scene = module.GhostScene(window=None)
        self.scene._scene_filepath = self.scene_file
        self.scene.skip_animations = True
        self.scene.setup()
        self.scene._create_checkpoint_zero()

    def tearDown(self):
        self.scene.camera.ctx.release()
        self.tmpdir.cleanup()

    def content(self):
        from maniml.camera.camera_frame import CameraFrame
        return [m for m in self.scene.mobjects
                if not isinstance(m, CameraFrame)]

    def test_group_animation_leaves_no_ghost_across_navigation(self):
        scene = self.scene
        scene.on_key_press(WindowKeys.RIGHT, 0)  # flash loop: one unit
        self.assertEqual(len(self.content()), 1)

        scene.on_key_press(WindowKeys.RIGHT, 0)  # group.animate.to_edge(UP)
        mobs = self.content()
        self.assertEqual(len(mobs), 1, "ghost left beside the moved group")
        ns = scene._live_namespace
        group = ns.get("group")
        self.assertTrue(any(group is m for m in mobs),
                        "namespace group is not the on-screen group")
        self.assertTrue(any(ns["squares"][0] is c for c in group.get_family()))
        self.assertGreater(group.get_center()[1], 1, "group did not move up")

        # The reported failure needed a step back and forward over the
        # retained checkpoint: RIGHT must restore it, not re-run source.
        scene.on_key_press(WindowKeys.LEFT, 0)
        self.assertEqual(len(self.content()), 1)
        scene.on_key_press(WindowKeys.RIGHT, 0)
        mobs = self.content()
        self.assertEqual(len(mobs), 1, "ghost after retained forward step")
        group = scene._live_namespace.get("group")
        self.assertIsNotNone(group)
        self.assertGreater(group.get_center()[1], 1)

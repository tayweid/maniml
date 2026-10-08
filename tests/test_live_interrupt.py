"""Interrupting a live forward move (scene._interruptibly; Taylor, 2026-10-08).

RIGHT while a move plays finishes it at once: the rest of the stretch runs
every step with nothing drawn, so it lands on the pausepoint a played run
would have saved. Any other jump unwinds the move to the pausepoint it
left, taking back whatever the interrupted run added past the frontier.
Driven headlessly: a stand-in for the viewer's frame hook acts on a chosen
frame, as the viewer's _check_interrupt does when a press is waiting.
"""

import os
import tempfile
import textwrap
import time
import unittest
from unittest.mock import patch

import numpy as np

from maniml.__main__ import load_scene_module
from maniml.scene.checkpoints import NavigationInterrupt
from maniml.web import viewer as viewer_module

SCENE = textwrap.dedent('''\
    from maniml import *

    class Stretches(Scene):
        def construct(self):
            dot = Dot()
            self.add(dot)
            self.play(dot.animate.shift(RIGHT), run_time=0.5)
            self.play(dot.animate.shift(UP), run_time=0.5)
            self.pause("One")
            self.play(dot.animate.shift(LEFT * 2), run_time=0.5)
            self.pause("Two")
''')


class FrameHook:
    """The viewer as play() sees it, acting on the n-th rendered frame:
    'finish' as a RIGHT does (fast-forward), 'back' as LEFT does."""

    def __init__(self, scene, at=None, action=None):
        self.scene, self.at, self.action = scene, at, action
        self.frames = 0

    def begin_animation(self):
        pass

    def end_animation(self):
        pass

    def can_skip_native_capture(self):
        return True

    def on_frame_rendered(self):
        self.frames += 1
        if self.frames == self.at and getattr(self.scene, "_interruptible", False):
            if self.action == "finish":
                self.scene._fast_forwarding = True
            else:
                raise NavigationInterrupt()


class LiveInterruptTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        path = os.path.join(self.tmpdir.name, "stretches.py")
        with open(path, "w") as f:
            f.write(SCENE)
        self.path = path

    def tearDown(self):
        self.tmpdir.cleanup()

    def make(self):
        module = load_scene_module(self.path)
        scene = module.Stretches(window=None)
        scene._scene_filepath = self.path
        scene.skip_animations = True
        scene.setup()
        scene._create_checkpoint_zero()
        scene.skip_animations = False
        self.addCleanup(scene.camera.release)
        return scene

    def advance(self, scene, at=None, action=None):
        hook = FrameHook(scene, at, action)
        scene._web_viewer = hook
        with patch.object(scene, "emit_frame"):
            scene._interruptibly(scene.advance_to_next_pausepoint)
        scene._web_viewer = None
        return hook

    @staticmethod
    def dot_at(scene, index):
        return scene.animation_checkpoints[index]["namespace"]["dot"].get_center()

    def test_right_mid_move_at_the_frontier_lands_where_a_played_run_would(self):
        played = self.make()
        self.advance(played)
        scene = self.make()
        hook = self.advance(scene, at=3, action="finish")
        self.assertEqual(scene.current_animation_index, 3)
        self.assertTrue(scene.animation_checkpoints[3].get("stop"))
        np.testing.assert_allclose(self.dot_at(scene, 3), self.dot_at(played, 3))
        self.assertEqual(scene.time, played.time)
        # Nothing drawn after the press but the landing frame.
        self.assertEqual(hook.frames, 4)
        self.assertFalse(scene._fast_forwarding)
        # The next RIGHT plays normally.
        self.advance(scene)
        self.assertEqual(scene.current_animation_index, 5)

    def test_left_mid_move_at_the_frontier_returns_and_takes_back_the_run(self):
        scene = self.make()
        # Frame 20 is in the second play: the first has saved checkpoint 1.
        self.advance(scene, at=20, action="back")
        self.assertEqual(scene.current_animation_index, 0)
        self.assertEqual(len(scene.animation_checkpoints), 1)
        self.assertEqual(scene.frontier_index, 0)
        self.assertNotIn("dot", scene._live_namespace)   # the scene's start
        self.assertFalse(scene._is_playing)
        # The stretch runs again from the start, whole.
        self.advance(scene)
        self.assertEqual(scene.current_animation_index, 3)
        np.testing.assert_allclose(self.dot_at(scene, 3), [1, 1, 0])

    def test_right_mid_move_through_history_lands_and_keeps_it(self):
        scene = self.make()
        self.advance(scene)
        self.advance(scene)
        saved = len(scene.animation_checkpoints)
        scene._restore_checkpoint_for_display(3)
        hook = self.advance(scene, at=4, action="finish")
        self.assertEqual(scene.current_animation_index, 5)
        self.assertEqual(len(scene.animation_checkpoints), saved)
        np.testing.assert_allclose(scene._live_namespace["dot"].get_center(), [-1, 1, 0])
        # Nothing drawn after the press but the landing (the replay draws
        # its landing too).
        self.assertLessEqual(hook.frames, 6)

    def test_left_mid_move_through_history_returns_and_keeps_it(self):
        scene = self.make()
        self.advance(scene)
        self.advance(scene)
        saved = len(scene.animation_checkpoints)
        scene._restore_checkpoint_for_display(3)
        self.advance(scene, at=4, action="back")
        self.assertEqual(scene.current_animation_index, 3)
        self.assertEqual(len(scene.animation_checkpoints), saved)
        np.testing.assert_allclose(scene._live_namespace["dot"].get_center(), [1, 1, 0])


class FakeServer:
    def __init__(self, events):
        self.events = list(events)

    def take_events(self, wanted):
        taken = [e for e in self.events if wanted(e)]
        self.events = [e for e in self.events if not wanted(e)]
        return taken

    def requeue_front(self, event):
        self.events.insert(0, event)


class FakeScene:
    _interruptible = True
    _fast_forwarding = False
    _is_playing = True
    _advancing = True


def viewer_with(events):
    viewer = object.__new__(viewer_module.WebViewer)
    viewer.server = FakeServer(events)
    viewer.scene = FakeScene()
    viewer._interrupted = False
    viewer._interrupt_event = None
    return viewer


def press(key):
    return {"type": "key", "action": "down", "key": key, "_received": time.monotonic()}


class ViewerInterruptTest(unittest.TestCase):
    def test_right_finishes_and_later_arrows_are_dropped(self):
        viewer = viewer_with([press("ArrowRight"), {"type": "pointer", "action": "move"}])
        viewer._check_interrupt()
        self.assertTrue(viewer.scene._fast_forwarding)
        # Pressed while it finished: dropped on landing, the pointer kept.
        viewer.server.events.append(press("ArrowRight"))
        viewer._settle_interrupt()
        self.assertEqual(viewer.server.events, [{"type": "pointer", "action": "move"}])

    def test_left_unwinds_and_is_not_applied_again(self):
        viewer = viewer_with([press("ArrowLeft")])
        with self.assertRaises(NavigationInterrupt):
            viewer._check_interrupt()
        viewer._settle_interrupt()
        self.assertEqual(viewer.server.events, [])

    def test_a_chip_unwinds_and_is_applied_once_landed(self):
        viewer = viewer_with([{"type": "chip", "index": 7, "_received": 0.0}])
        with self.assertRaises(NavigationInterrupt):
            viewer._check_interrupt()
        viewer._settle_interrupt()
        self.assertEqual(len(viewer.server.events), 1)
        requeued = viewer.server.events[0]
        self.assertEqual((requeued["type"], requeued["index"]), ("chip", 7))
        self.assertGreater(requeued["_received"], 0.0)   # fresh, not stale

    def test_nothing_waiting_changes_nothing(self):
        viewer = viewer_with([{"type": "pointer", "action": "move"}])
        viewer._check_interrupt()
        self.assertFalse(viewer.scene._fast_forwarding)
        self.assertFalse(viewer._interrupted)


if __name__ == "__main__":
    unittest.main()

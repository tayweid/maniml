"""The camera frame is animated and updated but is never one of the scene's
mobjects, as in CE (2026-09-11; the A2/A3 field report's item 6). Checkpoints
carry its whole state (points, orientation, field of view) and keep the
frame itself by reference (2026-09-16; the econ-0100 PriceDiscovery zoom)."""

import os
import tempfile
import textwrap
import unittest
from unittest.mock import patch

import numpy as np

from maniml import DEGREES, ORIGIN, RIGHT, Scene, Square, VGroup
from maniml.__main__ import load_scene_module
from maniml.camera.camera_frame import CameraFrame
from maniml.scene.checkpoints import deepcopy_namespace

FRAME_SCENE = textwrap.dedent('''\
    from maniml import *

    class FrameScene(Scene):
        def construct(self):
            box = Square()
            self.add(box)
            self.play(self.camera.frame.animate.shift(RIGHT * 2), run_time=0.05)  # checkpoint 1
            self.play(box.animate.shift(UP), run_time=0.05)                       # checkpoint 2
''')


def _has_frame(scene):
    return any(isinstance(m, CameraFrame) for m in scene.mobjects)


class CameraFrameStaysOutOfTheSceneList(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.scene_file = os.path.join(self.tmpdir.name, 'frame_scene.py')
        with open(self.scene_file, 'w') as f:
            f.write(FRAME_SCENE)
        module = load_scene_module(self.scene_file)
        self.scene = module.FrameScene(window=None)
        self.scene._scene_filepath = self.scene_file
        self.scene.skip_animations = True
        self.scene.setup()
        self.scene._create_checkpoint_zero()

    def tearDown(self):
        self.scene.camera.release()
        self.tmpdir.cleanup()

    def run_to(self, index):
        while self.scene.current_animation_index < index:
            before = self.scene.current_animation_index
            self.scene.run_next_animation()
            if self.scene.current_animation_index == before:
                break

    def test_a_fresh_scene_draws_nothing(self):
        self.assertEqual(self.scene.mobjects, [])
        self.assertIs(self.scene.frame, self.scene.camera.frame)

    def test_animating_the_frame_moves_it_without_adding_it(self):
        self.run_to(1)
        self.assertFalse(_has_frame(self.scene))
        np.testing.assert_allclose(self.scene.camera.frame.get_center(), RIGHT * 2, atol=1e-6)
        # The course's exercise_card() idiom: every drawn mobject is a VMobject
        VGroup(*self.scene.mobjects)

    def test_navigation_restores_the_frame_and_never_duplicates_it(self):
        self.run_to(2)
        self.scene._restore_checkpoint_for_display(0)
        np.testing.assert_allclose(self.scene.camera.frame.get_center(), ORIGIN, atol=1e-6)
        self.scene._restore_checkpoint_for_display(2)
        np.testing.assert_allclose(self.scene.camera.frame.get_center(), RIGHT * 2, atol=1e-6)
        self.assertIs(self.scene.frame, self.scene.camera.frame)
        self.assertFalse(_has_frame(self.scene))
        self.assertEqual(len(self.scene.mobjects), 1)


ORBIT_SCENE = textwrap.dedent('''\
    from maniml import *

    class OrbitScene(ThreeDScene):
        def construct(self):
            self.set_camera_orientation(phi=55 * DEGREES, theta=-8 * DEGREES, focal_distance=50)
            box = Square()
            self.add(box)
            self.play(box.animate.shift(UP), run_time=0.05)
            self.pause('home')
            self.play(self.frame.animate.set_theta(40 * DEGREES).set_phi(70 * DEGREES), run_time=0.05)
            self.play(self.frame.animate.set_focal_distance(20), run_time=0.05)
            self.pause('orbited')
            self.play(self.frame.animate.set_theta(-8 * DEGREES).set_phi(55 * DEGREES), run_time=0.05)
            self.pause('back')
''')

# The econ-0100 PriceDiscovery beat: the frame bound to a variable before a
# pausepoint and restored through that variable after it
ZOOM_SCENE = textwrap.dedent('''\
    from maniml import *

    class ZoomScene(ThreeDScene):
        def construct(self):
            self.set_camera_orientation(phi=55 * DEGREES, theta=-8 * DEGREES, focal_distance=50)
            box = Square()
            self.add(box)
            self.play(box.animate.shift(UP), run_time=0.05)
            self.pause('wide')
            frame = self.camera.frame
            frame.save_state()
            self.play(frame.animate.scale(0.55).move_to([1, 1, 0]), run_time=0.5)
            self.pause('zoomed')
            self.play(Restore(frame), run_time=0.5)
            self.pause('wide again')
''')


class PausepointSceneTest(unittest.TestCase):
    scene_source = ''
    scene_name = ''

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.scene_file = os.path.join(self.tmpdir.name, 'scene.py')
        with open(self.scene_file, 'w') as f:
            f.write(self.scene_source)
        module = load_scene_module(self.scene_file)
        self.scene = getattr(module, self.scene_name)(window=None)
        self.scene._scene_filepath = self.scene_file
        self.scene.skip_animations = True
        self.scene.setup()
        self.scene._create_checkpoint_zero()

    def tearDown(self):
        self.scene.camera.release()
        self.tmpdir.cleanup()

    def at(self):
        return self.scene.animation_checkpoints[self.scene.current_animation_index].get('name')

    def angles(self):
        frame = self.scene.camera.frame
        return (
            round(frame.get_phi() / DEGREES, 3),
            round(frame.get_theta() / DEGREES, 3),
            round(frame.get_focal_distance(), 3),
        )

    def play_visibly(self):
        """RIGHT with animations running; every frame's camera center and
        height, so a beat that snaps is told apart from one that animates."""
        samples = []

        def capture(*args, **kwargs):
            frame = self.scene.camera.frame
            samples.append((round(float(frame.get_center()[0]), 3), round(frame.get_height(), 3)))

        self.scene.skip_animations = False
        try:
            with patch.object(self.scene.camera, 'capture', side_effect=capture), \
                    patch.object(self.scene, 'emit_frame'):
                self.scene.advance_to_next_pausepoint()
        finally:
            self.scene.skip_animations = True
        return samples


class OrientationSurvivesNavigation(PausepointSceneTest):
    scene_source = ORBIT_SCENE
    scene_name = 'OrbitScene'

    def test_backward_seek_restores_orientation_and_focal_distance(self):
        for _ in range(3):
            self.scene.advance_to_next_pausepoint()
        self.assertEqual(self.at(), 'back')
        self.assertEqual(self.angles(), (55.0, -8.0, 20.0))

        self.scene._reverse_to_previous_pausepoint()
        self.assertEqual(self.at(), 'orbited')
        self.assertEqual(self.angles(), (70.0, 40.0, 20.0))

        self.scene._reverse_to_previous_pausepoint()
        self.assertEqual(self.at(), 'home')
        self.assertEqual(self.angles(), (55.0, -8.0, 50.0))

    def test_forward_replay_and_frontier_agree_with_the_checkpoints(self):
        for _ in range(3):
            self.scene.advance_to_next_pausepoint()
        for _ in range(2):
            self.scene._reverse_to_previous_pausepoint()
        self.scene.advance_to_next_pausepoint()
        self.assertEqual(self.at(), 'orbited')
        self.assertEqual(self.angles(), (70.0, 40.0, 20.0))
        self.scene.advance_to_next_pausepoint()
        self.assertEqual(self.at(), 'back')
        self.assertEqual(self.angles(), (55.0, -8.0, 20.0))


class FrameVariableStaysLive(PausepointSceneTest):
    scene_source = ZOOM_SCENE
    scene_name = 'ZoomScene'

    def test_thawed_namespace_binds_the_live_frame(self):
        for _ in range(3):
            self.scene.advance_to_next_pausepoint()
        self.scene._reverse_to_previous_pausepoint()
        self.assertEqual(self.at(), 'zoomed')
        self.assertIs(self.scene._live_namespace['frame'], self.scene.camera.frame)
        self.assertFalse(_has_frame(self.scene))

    def test_restore_through_the_variable_animates_the_live_camera(self):
        for _ in range(3):
            self.scene.advance_to_next_pausepoint()
        self.scene._reverse_to_previous_pausepoint()
        np.testing.assert_allclose(self.scene.camera.frame.get_center()[:2], [1, 1], atol=1e-6)

        samples = self.play_visibly()
        self.assertEqual(self.at(), 'wide again')
        # Before the fix the copy animated and the live camera snapped home
        # at the end: two distinct states over the whole beat
        self.assertGreater(len(set(samples)), 3, samples)
        np.testing.assert_allclose(self.scene.camera.frame.get_center(), ORIGIN, atol=1e-6)
        self.assertAlmostEqual(self.scene.camera.frame.get_height(), 8.0)


class CheckpointCopiesKeepTheFrameByReference(unittest.TestCase):
    def test_freeze_and_thaw_hand_back_the_frame_itself(self):
        scene = Scene(window=None)
        try:
            frame = scene.camera.frame
            box = Square()
            for mode in ('freeze', 'thaw'):
                copied = deepcopy_namespace({'frame': frame, 'box': box, 'both': [frame, box]}, mode=mode)
                self.assertIs(copied['frame'], frame)
                self.assertIs(copied['both'][0], frame)
                self.assertIsNot(copied['box'], box)
                self.assertIs(copied['both'][1], copied['box'])
        finally:
            scene.camera.release()

    def test_a_plain_copy_still_copies_the_frame(self):
        scene = Scene(window=None)
        try:
            frame = scene.camera.frame
            self.assertIsNot(frame.copy(), frame)
            self.assertIsNot(deepcopy_namespace({'frame': frame})['frame'], frame)
            frame.save_state()
            self.assertIsNot(frame.saved_state, frame)
        finally:
            scene.camera.release()

    def test_checkpoint_state_round_trips_orientation(self):
        scene = Scene(window=None)
        try:
            frame = scene.camera.frame
            frame.reorient(30, 60).scale(0.5).shift(RIGHT).set_focal_distance(12)
            state = frame.get_checkpoint_state()
            frame.to_default_state().set_focal_distance(50)
            frame.set_checkpoint_state(state)
            self.assertAlmostEqual(frame.get_theta() / DEGREES, 30.0)
            self.assertAlmostEqual(frame.get_phi() / DEGREES, 60.0)
            self.assertAlmostEqual(frame.get_focal_distance(), 12.0)
            np.testing.assert_allclose(frame.get_center(), RIGHT, atol=1e-6)
        finally:
            scene.camera.release()


class CameraFrameUpdaters(unittest.TestCase):
    def test_frame_updaters_run_in_the_scene_loop(self):
        scene = Scene(window=None)
        scene.skip_animations = True
        try:
            self.assertFalse(scene.should_update_mobjects())
            scene.camera.frame.add_updater(lambda m, dt: m.shift(RIGHT * dt))
            self.assertTrue(scene.should_update_mobjects())
            scene.update_frame(0.5)
            np.testing.assert_allclose(scene.camera.frame.get_center(), RIGHT * 0.5, atol=1e-6)
        finally:
            scene.camera.release()


if __name__ == '__main__':
    unittest.main()

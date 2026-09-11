"""The camera frame is animated and updated but is never one of the scene's
mobjects, as in CE (2026-09-11; the A2/A3 field report's item 6)."""

import os
import tempfile
import textwrap
import unittest

import numpy as np

from maniml import ORIGIN, RIGHT, Scene, VGroup
from maniml.__main__ import load_scene_module
from maniml.camera.camera_frame import CameraFrame

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

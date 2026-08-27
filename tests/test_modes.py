"""Headless tests for present mode, render mode, the presentation
timeline, and click-to-inspect."""

import glob
import os
import tempfile
import textwrap
import unittest

import numpy as np

from maniml.__main__ import load_scene_module

SCENE_SRC = textwrap.dedent('''\
    from maniml import *

    class ModeScene(Scene):
        def construct(self):
            circle = Circle()
            group = VGroup(Square().shift(LEFT * 2), Square().shift(RIGHT * 2))
            self.play(Create(circle), run_time=0.05)
            self.play(FadeIn(group), run_time=0.05)
            self.play(circle.animate.shift(UP), run_time=0.05)
            self.wait(0.05)
''')


class ModeSceneTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.scene_file = os.path.join(self.tmpdir.name, 'mode_scene.py')
        with open(self.scene_file, 'w') as f:
            f.write(SCENE_SRC)
        self.module = load_scene_module(self.scene_file)

    def tearDown(self):
        self.tmpdir.cleanup()

    def make_scene(self, **kwargs):
        scene = self.module.ModeScene(window=None, **kwargs)
        scene._scene_filepath = self.scene_file
        scene.skip_animations = True
        scene.setup()
        scene._create_checkpoint_zero()
        return scene


class TestPresentMode(ModeSceneTest):
    def test_prepare_builds_all_checkpoints_and_rewinds(self):
        scene = self.make_scene()
        scene._present_mode = True
        scene._prepare_presentation()
        # 3 plays + tail wait = checkpoints 0..4, rewound to the start
        self.assertEqual(len(scene.animation_checkpoints), 5)
        self.assertEqual(scene.current_animation_index, 0)
        self.assertFalse(scene.auto_reload_enabled)
        self.assertTrue(scene._presentation_ready)
        # live namespace tracks the displayed checkpoint
        self.assertIn('self', scene._live_namespace)

    def test_timeline_click_jumps(self):
        scene = self.make_scene()
        scene._present_mode = True
        scene._prepare_presentation()
        scene._show_timeline()
        self.assertIsNotNone(scene._timeline_group)

        # click near the last dot's x, inside the bottom zone
        x = scene._timeline_xs[-1]
        y = scene.camera.frame.get_bottom()[1] + 0.01
        handled = scene._handle_timeline_click(np.array([x, y, 0.0]))
        self.assertTrue(handled)
        self.assertEqual(scene.current_animation_index, 4)

        # a click in the middle of the frame is not a timeline click
        handled = scene._handle_timeline_click(np.array([0.0, 0.0, 0.0]))
        self.assertFalse(handled)

    def test_timeline_never_leaks_into_checkpoints(self):
        scene = self.make_scene()
        scene._present_mode = True
        scene._prepare_presentation()
        scene._show_timeline()
        state = scene.get_state()
        self.assertNotIn(scene._timeline_group, state.mobjects)


class TestRenderMode(ModeSceneTest):
    def test_render_all_writes_checkpoint_pngs(self):
        media = os.path.join(self.tmpdir.name, 'media')
        scene = self.make_scene(file_writer_config=dict(
            write_to_movie=False,  # PNGs only; video needs ffmpeg
            output_directory=media,
            file_name='ModeScene',
        ))
        scene._render_mode = True
        scene._render_all()
        pngs = sorted(glob.glob(os.path.join(media, 'ModeScene_checkpoints', '*.png')))
        self.assertEqual(len(pngs), 5, pngs)
        self.assertTrue(pngs[0].endswith('000.png'))
        self.assertTrue(pngs[-1].endswith('004.png'))
        self.assertGreater(os.path.getsize(pngs[-1]), 0)


class TestInspect(ModeSceneTest):
    def test_find_and_name_mobject(self):
        scene = self.make_scene()
        scene.run_next_animation()  # circle created at origin
        mob = scene._find_mobject_at(np.array([0.0, 0.0, 0.0]))
        self.assertIsNotNone(mob)
        self.assertEqual(scene._name_of(mob), 'circle')

    def test_name_of_group_member_reports_container(self):
        scene = self.make_scene()
        scene.run_next_animation()
        scene.run_next_animation()  # group faded in
        mob = scene._find_mobject_at(np.array([2.0, 0.0, 0.0]))
        self.assertIsNotNone(mob)
        self.assertEqual(scene._name_of(mob), 'group')

    def test_names_survive_jump_navigation(self):
        scene = self.make_scene()
        scene.run_next_animation()
        scene.run_next_animation()
        scene._restore_checkpoint_for_display(1)  # back to just the circle
        mob = scene._find_mobject_at(np.array([0.0, 0.0, 0.0]))
        self.assertIsNotNone(mob)
        self.assertEqual(scene._name_of(mob), 'circle')

    def test_grab_moves_and_reports(self):
        scene = self.make_scene()
        scene.run_next_animation()
        mob = scene._find_mobject_at(np.array([0.0, 0.0, 0.0]))
        scene._begin_grab(mob, np.array([0.2, 0.0, 0.0]))
        self.assertIs(scene._grabbed_mobject, mob)
        # simulate a drag: mobject follows point minus grab offset
        target_point = np.array([1.2, 1.0, 0.0])
        mob.move_to(target_point - scene._grab_offset)
        scene._end_grab()
        self.assertIsNone(scene._grabbed_mobject)
        self.assertTrue(np.allclose(mob.get_center(), [1.0, 1.0, 0.0]))

    def test_empty_click_hits_nothing(self):
        scene = self.make_scene()
        scene.run_next_animation()
        mob = scene._find_mobject_at(np.array([5.0, 3.0, 0.0]))
        self.assertIsNone(mob)


if __name__ == '__main__':
    unittest.main()

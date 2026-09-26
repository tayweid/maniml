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


class TestRenderMode(ModeSceneTest):
    def _render_scene(self, media):
        return self.make_scene(file_writer_config=dict(
            write_to_movie=False,  # PNGs only; video needs ffmpeg
            output_directory=media,
            file_name='ModeScene',
        ))

    def test_render_all_writes_checkpoint_pngs_when_asked(self):
        media = os.path.join(self.tmpdir.name, 'media')
        scene = self._render_scene(media)
        scene._render_mode = True
        scene._render_checkpoints = True
        scene._render_all()
        pngs = sorted(glob.glob(os.path.join(media, 'ModeScene_checkpoints', '*.png')))
        self.assertEqual(len(pngs), 5, pngs)
        self.assertTrue(pngs[0].endswith('000.png'))
        self.assertTrue(pngs[-1].endswith('004.png'))
        self.assertGreater(os.path.getsize(pngs[-1]), 0)

    def test_a_plain_render_writes_no_checkpoint_pngs(self):
        """The stills are their own export: a render that was not asked
        for them leaves no directory behind (they dwarf the movie)."""
        media = os.path.join(self.tmpdir.name, 'plain-media')
        scene = self._render_scene(media)
        scene._render_mode = True
        scene._render_all()
        self.assertFalse(
            os.path.exists(os.path.join(media, 'ModeScene_checkpoints')))
        # ...and every unit still ran
        self.assertEqual(scene.current_animation_index, 4)


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

    def test_name_of_list_entry(self):
        scene = self.make_scene()
        scene.run_next_animation()
        circle = scene._live_namespace['circle']
        scene._live_namespace['dots'] = [None, circle]
        scene._live_namespace['by_key'] = {'c': circle}
        del scene._live_namespace['circle']
        self.assertEqual(scene._name_of(circle), 'dots[1]')
        del scene._live_namespace['dots']
        self.assertEqual(scene._name_of(circle), "by_key['c']")

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


HANDLE_SRC = textwrap.dedent('''\
    from maniml import *

    class HandleScene(Scene):
        def construct(self):
            rail = Line(LEFT * 3, RIGHT * 3)
            reading = ValueTracker(0.0)
            knob = Dot(ORIGIN, radius=0.2).set_draggable(
                along=rail, on_drag=lambda m: reading.set_value(m.get_center()[0]))
            cover = Square(side_length=4)          # over the knob, added after it
            corner = Dot(UP * 3 + RIGHT * 5, radius=0.2).set_draggable(along=UP)
            self.play(FadeIn(knob), FadeIn(cover), FadeIn(corner), run_time=0.05)
            self.play(cover.animate.shift(LEFT * 0.1), run_time=0.05)
''')


class FakeHoverViewer:
    is_web_viewer = True

    def __init__(self):
        self.labels = []

    def set_hover(self, label):
        self.labels.append(label)

    def is_key_pressed(self, symbol):
        return False


class TestHandles(ModeSceneTest):
    """set_draggable: handles are grabbed first, in every mode, obey their
    constraint, report through on_drag, and are named on hover."""

    def make_handle_scene(self):
        from maniml.event_constants import MouseButtons
        path = os.path.join(self.tmpdir.name, 'handle_scene.py')
        with open(path, 'w') as f:
            f.write(HANDLE_SRC)
        scene = load_scene_module(path).HandleScene(window=None)
        scene._scene_filepath = path
        scene.skip_animations = True
        scene.setup()
        scene._create_checkpoint_zero()
        scene.run_next_animation()
        self.LEFT = MouseButtons.LEFT
        return scene

    def press(self, scene, point, mods=0):
        scene.on_mouse_press(np.array(point, dtype=float), self.LEFT, mods)

    def drag_to(self, scene, point):
        scene.on_mouse_drag(np.array(point, dtype=float), np.zeros(3), self.LEFT, 0)

    def test_handle_is_grabbed_under_a_later_mobject(self):
        scene = self.make_handle_scene()
        self.press(scene, [0, 0, 0])
        self.assertEqual(scene._grabbed_name, 'knob')
        scene.on_mouse_release(np.zeros(3), self.LEFT, 0)
        # Off the handle, development still grabs whatever is there
        self.press(scene, [1.5, 1.5, 0])
        self.assertEqual(scene._grabbed_name, 'cover')

    def test_presentation_grabs_handles_and_nothing_else(self):
        scene = self.make_handle_scene()
        scene._present_mode = True
        self.press(scene, [1.5, 1.5, 0])
        self.assertIsNone(scene._grabbed_mobject)
        self.press(scene, [0, 0, 0])
        self.assertEqual(scene._grabbed_name, 'knob')

    def test_drag_stays_on_the_curve_and_reports(self):
        scene = self.make_handle_scene()
        knob = scene._live_namespace['knob']
        reading = scene._live_namespace['reading']
        self.press(scene, [0, 0, 0])
        self.drag_to(scene, [2.0, 1.7, 0])
        self.assertTrue(np.allclose(knob.get_center(), [2.0, 0.0, 0.0], atol=0.02))
        self.assertAlmostEqual(reading.get_value(), 2.0, places=1)
        self.drag_to(scene, [9.0, -4.0, 0])            # past the end: clamps
        self.assertTrue(np.allclose(knob.get_center(), [3.0, 0.0, 0.0], atol=0.02))

    def test_drag_along_a_direction_keeps_the_grab_line(self):
        scene = self.make_handle_scene()
        corner = scene._live_namespace['corner']
        self.press(scene, [5, 3, 0])
        self.drag_to(scene, [2.0, 1.0, 0])
        self.assertTrue(np.allclose(corner.get_center(), [5.0, 1.0, 0.0]))

    def test_flag_survives_navigation(self):
        scene = self.make_handle_scene()
        scene.run_next_animation()
        scene._restore_checkpoint_for_display(1)
        self.assertEqual([scene._name_of(m) for m in scene._draggable_mobjects()],
                         ['knob', 'corner'])
        self.press(scene, [0, 0, 0])
        self.assertEqual(scene._grabbed_name, 'knob')

    def test_drag_after_a_seek_reaches_the_displayed_tracker(self):
        """Every seek puts copies on screen. The on_drag callback must set
        the tracker those copies read (the displayed namespace's), not the
        one of the namespace it was written in — in a presentation that is
        the frontier's, and nothing would follow the handle."""
        scene = self.make_handle_scene()
        scene.run_next_animation()
        scene._present_mode = True
        scene._restore_checkpoint_for_display(1)
        shown = scene._live_namespace['reading']
        knob = scene._live_namespace['knob']
        self.press(scene, [0, 0, 0])
        self.assertIs(scene._grabbed_mobject, knob)
        self.drag_to(scene, [-1.5, 0.3, 0])
        self.assertAlmostEqual(shown.get_value(), -1.5, places=1)
        self.assertTrue(np.allclose(knob.get_center(), [-1.5, 0, 0], atol=0.02))

    def test_hover_names_the_handle_once_per_change(self):
        scene = self.make_handle_scene()
        viewer = FakeHoverViewer()
        scene._web_viewer = viewer
        scene.window = viewer
        for point in ([0, 0, 0], [0.1, 0, 0], [1.5, 1.5, 0], [5, 3, 0]):
            scene.on_mouse_motion(np.array(point, dtype=float), np.zeros(3))
        self.assertEqual(viewer.labels, ['knob', 'knob', None, 'corner'])

    def test_history_knows_its_handles_from_the_empty_start(self):
        scene = self.make_handle_scene()
        scene._restore_checkpoint_for_display(0)
        self.assertEqual(scene._draggable_mobjects(), [])
        self.assertTrue(scene._scene_has_handles())
        self.assertFalse(self.make_scene()._scene_has_handles())

    def test_a_flat_scene_has_no_handles(self):
        scene = self.make_scene()
        scene.run_next_animation()
        self.assertEqual(scene._draggable_mobjects(), [])


ORBIT_SRC = textwrap.dedent('''\
    from maniml import *

    class OrbitScene(ThreeDScene):
        def construct(self):
            cube = Cube()
            self.play(FadeIn(cube), run_time=0.05)
            self.play(cube.animate.shift(OUT), run_time=0.05)
''')


class TestOrbitGesture(ModeSceneTest):
    def make_orbit_scene(self):
        path = os.path.join(self.tmpdir.name, 'orbit_scene.py')
        with open(path, 'w') as f:
            f.write(ORBIT_SRC)
        scene = load_scene_module(path).OrbitScene(window=None)
        scene._scene_filepath = path
        scene.skip_animations = True
        scene.setup()
        scene._create_checkpoint_zero()
        return scene

    def drag(self, scene, d_point, modifiers=0):
        from maniml.event_constants import MouseButtons
        scene.on_mouse_drag(
            np.zeros(3), np.array(d_point, dtype=float),
            MouseButtons.LEFT, modifiers)

    def test_drag_turns_the_camera_about_its_centre(self):
        scene = self.make_orbit_scene()
        frame = scene.frame
        theta, phi, _ = frame.get_euler_angles()
        centre = frame.get_center().copy()
        self.drag(scene, frame.from_fixed_frame_point(
            np.array([0.4, -0.2, 0.0]), relative=True))
        new_theta, new_phi, _ = frame.get_euler_angles()
        # The world follows the hand: right lowers theta, down lowers phi
        self.assertAlmostEqual(new_theta, theta - 0.2)
        self.assertAlmostEqual(new_phi, phi - 0.1)
        self.assertTrue(np.allclose(frame.get_center(), centre))

    def test_shift_drag_pans_instead(self):
        from maniml.event_constants import WindowKeys
        scene = self.make_orbit_scene()
        frame = scene.frame
        angles = frame.get_euler_angles().copy()
        self.drag(scene, [0.5, 0.0, 0.0], WindowKeys.MOD_SHIFT)
        self.assertTrue(np.allclose(frame.get_euler_angles(), angles))
        self.assertTrue(np.allclose(frame.get_center(), [-0.5, 0.0, 0.0]))

    def test_flat_scene_still_pans(self):
        scene = self.make_scene()
        angles = scene.frame.get_euler_angles().copy()
        self.drag(scene, [0.5, 0.0, 0.0])
        self.assertTrue(np.allclose(scene.frame.get_euler_angles(), angles))
        self.assertTrue(np.allclose(scene.frame.get_center(), [-0.5, 0.0, 0.0]))

    def test_plain_press_leaves_mobjects_alone_and_alt_grabs(self):
        from maniml.event_constants import MouseButtons, WindowKeys
        scene = self.make_orbit_scene()
        scene.run_next_animation()
        scene.on_mouse_press(np.zeros(3), MouseButtons.LEFT, 0)
        self.assertIsNone(scene._grabbed_mobject)
        scene.on_mouse_press(np.zeros(3), MouseButtons.LEFT, WindowKeys.MOD_ALT)
        self.assertIsNotNone(scene._grabbed_mobject)
        scene.on_mouse_release(np.zeros(3), MouseButtons.LEFT, 0)

    def test_navigation_puts_the_authored_camera_back(self):
        scene = self.make_orbit_scene()
        scene.run_next_animation()
        authored = scene.frame.get_euler_angles().copy()
        self.drag(scene, [1.0, 0.5, 0.0])
        self.assertFalse(np.allclose(scene.frame.get_euler_angles(), authored))
        # Forward from the frontier, and a jump back, both restore it
        scene.run_next_animation()
        self.assertTrue(np.allclose(scene.frame.get_euler_angles(), authored))
        self.drag(scene, [1.0, 0.5, 0.0])
        scene._restore_checkpoint_for_display(1)
        self.assertTrue(np.allclose(scene.frame.get_euler_angles(), authored))


if __name__ == '__main__':
    unittest.main()

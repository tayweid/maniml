"""Function scenes: a scene written as a function under a scene class used
as its decorator (maniml/scene/function_scene.py).

The source map reads the function's body as it reads construct()'s, the
verbs reach the running scene, and the checkpoint engine runs the body
exactly as it runs a class's: the headless runs below hold a function
scene to the class scene of test_checkpoint_reload, unit for unit.
"""

import os
import tempfile
import textwrap
import unittest

import numpy as np

import maniml
from maniml import Scene, ThreeDScene
from maniml.__main__ import load_scene_module
from maniml.scene import function_scene
from maniml.scene.source_map import build_units, pause_anchored
from maniml.web.library import find_scene_classes


CLASS_BODY = textwrap.dedent('''\
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

FUNCTION_BODY = textwrap.dedent('''\
    from maniml import *

    HELPER_SHIFT = 0.5

    @Scene
    def EditScene(s):
        circle = Circle()
        play(Create(circle), run_time=0.05)
        for i in range(2):
            circle.shift(RIGHT * HELPER_SHIFT)
            play(circle.animate.scale(1.1), run_time=0.05)
        square = Square()
        play(Transform(circle, square), run_time=0.05)
        s.wait(0.05)
''')

PAUSED = textwrap.dedent('''\
    from maniml import *

    @Scene
    def PauseScene():
        circle = Circle()
        play(Create(circle), run_time=0.05)
        play(circle.animate.shift(RIGHT), run_time=0.05)
        pause()
        square = Square()
        play(Transform(circle, square), run_time=0.05)
        pause()
        wait(0.05)
''')


def _shape(units):
    return [(u.has_stop, u.stops, u.loops, u.is_pause, u.end_line - u.start_line)
            for u in units]


class TestSourceMap(unittest.TestCase):
    def test_a_function_body_maps_as_construct_does(self):
        self.assertEqual(_shape(build_units(FUNCTION_BODY, 'EditScene')),
                         _shape(build_units(CLASS_BODY, 'EditScene')))

    def test_bare_pause_anchors_the_file(self):
        self.assertTrue(pause_anchored(PAUSED))
        units = build_units(PAUSED, 'PauseScene')
        self.assertEqual([u.is_pause for u in units], [False, False, True, False, True, False])

    def test_a_pause_on_the_scene_parameter_anchors_the_file(self):
        src = textwrap.dedent('''\
            @Scene
            def Intro(s):
                play(Create(Circle()))
                s.pause()
        ''')
        self.assertTrue(pause_anchored(src))
        self.assertTrue(build_units(src, 'Intro')[-1].is_pause)

    def test_a_pause_on_anything_else_does_not(self):
        src = textwrap.dedent('''\
            @Scene
            def Intro(s):
                player.pause()
                play(Create(Circle()))
        ''')
        self.assertFalse(pause_anchored(src))

    def test_the_named_scene_is_found_among_classes_and_functions(self):
        src = textwrap.dedent('''\
            class First(Scene):
                def construct(self):
                    self.play(Create(Circle()))

            def helper():
                play(Create(Square()))

            @ThreeDScene
            def Second():
                x = 1
                play(Create(Sphere()))
        ''')
        units = build_units(src, 'Second')
        self.assertEqual(len(units), 1)
        self.assertIn('Sphere', units[0].source)
        self.assertNotIn('Square', units[0].source)
        # No name: the first scene in the file, as for classes
        self.assertIn('Circle', build_units(src)[0].source)

    def test_a_play_in_a_helper_defined_in_the_body_is_not_a_boundary(self):
        src = textwrap.dedent('''\
            @Scene
            def Intro():
                def flash(m):
                    play(Indicate(m))
                c = Circle()
                play(Create(c))
        ''')
        units = build_units(src, 'Intro')
        self.assertEqual(len(units), 1)
        self.assertEqual(units[0].stops, 1)


class TestDiscovery(unittest.TestCase):
    def test_the_library_scan_lists_function_scenes_in_file_order(self):
        src = textwrap.dedent('''\
            import maniml
            from maniml import *

            @Scene
            def A():
                pass

            class B(Scene):
                def construct(self):
                    pass

            def not_a_scene():
                pass

            @functools.cache
            def also_not():
                pass

            @maniml.ThreeDScene
            def C(s):
                pass
        ''')
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'scenes.py')
            with open(path, 'w') as f:
                f.write(src)
            self.assertEqual(find_scene_classes(path), ['A', 'B', 'C'])


class TestDecorator(unittest.TestCase):
    def test_the_decorator_returns_a_subclass_named_for_the_function(self):
        def Intro():
            """The intro."""
        cls = Scene(Intro)
        self.assertTrue(issubclass(cls, Scene))
        self.assertEqual(cls.__name__, 'Intro')
        self.assertEqual(cls.__module__, __name__)
        self.assertEqual(cls.__doc__, 'The intro.')
        self.assertIs(cls.scene_function, Intro)
        self.assertIsNone(cls._scene_handle)

    def test_a_subclass_decorates_as_itself(self):
        def Orbit(s):
            pass
        cls = ThreeDScene(Orbit)
        self.assertTrue(issubclass(cls, ThreeDScene))
        self.assertEqual(cls._scene_handle, 's')

    def test_more_than_one_parameter_is_refused(self):
        def Bad(a, b):
            pass
        with self.assertRaises(TypeError):
            Scene(Bad)

    def test_the_verbs_are_exported_and_need_a_running_scene(self):
        for name in function_scene.VERBS:
            self.assertIn(name, maniml.__all__)
        function_scene._active = None
        with self.assertRaisesRegex(RuntimeError, 'no scene is running'):
            maniml.play()


class HeadlessScene:
    """A scene file loaded and run headlessly, as test_checkpoint_reload
    runs one."""

    def __init__(self, source, name):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmpdir.name, 'scene_file.py')
        self.write(source)
        module = load_scene_module(self.path)
        self.scene = getattr(module, name)(window=None)
        self.scene._scene_filepath = self.path
        self.scene.skip_animations = True
        self.scene.setup()
        self.scene._create_checkpoint_zero()

    def write(self, source):
        with open(self.path, 'w') as f:
            f.write(source)

    def save(self, source, earliest_changed_line):
        self.write(source)
        self.scene._on_file_changed({'earliest_changed_line': earliest_changed_line})
        self.scene._file_changed_flag = False
        self.scene._handle_file_change()

    def run_all(self):
        self.scene._run_all_units()

    def close(self):
        # As test_checkpoint_reload: release the camera rather than tear the
        # scene down, which would finish a file writer that never began
        function_scene.deactivate(self.scene)
        self.scene.camera.release()
        self.tmpdir.cleanup()


class TestHeadlessRun(unittest.TestCase):
    def setUp(self):
        self.run = HeadlessScene(FUNCTION_BODY, 'EditScene')
        self.scene = self.run.scene

    def tearDown(self):
        self.run.close()

    def test_it_checkpoints_as_the_class_scene_does(self):
        reference = HeadlessScene(CLASS_BODY, 'EditScene')
        try:
            reference.run_all()
            self.run.run_all()
            self.assertEqual(
                [cp['unit_index'] for cp in self.scene.animation_checkpoints],
                [cp['unit_index'] for cp in reference.scene.animation_checkpoints],
            )
            self.assertEqual(
                [cp['unit_index'] for cp in self.scene.animation_checkpoints],
                [-1, 0, 1, 1, 2, 3],
            )
            ours = self.scene._live_namespace['circle'].get_points()
            theirs = reference.scene._live_namespace['circle'].get_points()
            np.testing.assert_allclose(ours, theirs)
        finally:
            reference.close()

    def test_the_parameter_is_the_scene_and_is_never_copied(self):
        self.run.run_all()
        self.assertIs(self.scene._live_namespace['s'], self.scene)
        for checkpoint in self.scene.animation_checkpoints:
            self.assertIs(checkpoint['namespace'].get('s', self.scene), self.scene)
        # A jump back thaws a checkpoint; the name still reaches the scene
        self.scene._restore_checkpoint_for_display(1)
        self.assertIs(self.scene._live_namespace['s'], self.scene)
        self.scene.run_next_animation()
        self.assertIs(self.scene._live_namespace['s'], self.scene)

    def test_the_verbs_reach_the_scene_that_last_ran_a_unit(self):
        other = HeadlessScene(FUNCTION_BODY, 'EditScene')
        try:
            other.scene.run_next_animation()
            self.assertIs(function_scene.active_scene(), other.scene)
            self.scene.run_next_animation()
            self.assertIs(function_scene.active_scene(), self.scene)
            self.assertEqual(len(self.scene.animation_checkpoints), 2)
            self.assertEqual(len(other.scene.animation_checkpoints), 2)
        finally:
            other.close()

    def test_an_edit_in_the_body_replays_from_the_unit_it_touched(self):
        self.run.run_all()
        edited = FUNCTION_BODY.replace(
            "    square = Square()\n",
            "    marker = 123\n    square = Square()\n",
        )
        line = edited.splitlines().index('    marker = 123') + 1
        self.run.save(edited, line)
        self.assertEqual(self.scene.current_animation_index, 4)
        self.assertEqual(self.scene.animation_checkpoints[4]['unit_index'], 2)
        self.assertEqual(self.scene.animation_checkpoints[4]['namespace'].get('marker'), 123)

    def test_renaming_the_parameter_rebuilds_with_the_new_name(self):
        self.run.run_all()
        edited = (FUNCTION_BODY
                  .replace("def EditScene(s):", "def EditScene(scene):")
                  .replace("    s.wait(0.05)", "    scene.wait(0.05)"))
        line = edited.splitlines().index('def EditScene(scene):') + 1
        self.run.save(edited, line)
        self.assertIsNone(self.scene._unit_error)
        self.assertEqual(self.scene.animation_checkpoints[self.scene.current_animation_index]['unit_index'], 3)
        self.assertIs(self.scene._live_namespace['scene'], self.scene)

    def test_construct_called_directly_runs_the_body(self):
        self.scene.construct()
        self.assertEqual(
            [cp['unit_index'] for cp in self.scene.animation_checkpoints],
            [-1, 0, 1, 1, 2],
        )
        self.assertIn('circle', self.scene.animation_checkpoints[1]['namespace'])


class TestHelpers(unittest.TestCase):
    """A helper written in the body is defined in a unit, so it reads the
    body's names (one defined after it included) across checkpoint copies;
    one written at module level reaches the scene through the verbs."""

    SOURCE = textwrap.dedent('''\
        from maniml import *

        def fade_in(mob):
            play(FadeIn(mob), run_time=0.05)

        @Scene
        def Helpers():
            def nudge():
                step = RIGHT * 0.5
                play(dot.animate.shift(step), run_time=0.05)

            dot = Dot()
            fade_in(dot)
            pause()
            nudge()
            pause()
            nudge()
            pause()
    ''')

    def setUp(self):
        self.run = HeadlessScene(self.SOURCE, 'Helpers')
        self.scene = self.run.scene

    def tearDown(self):
        self.run.close()

    def test_helpers_play_and_read_a_name_defined_after_them(self):
        self.run.run_all()
        self.assertIn(self.scene._live_namespace['dot'], self.scene.mobjects)
        self.assertAlmostEqual(self.scene._live_namespace['dot'].get_center()[0], 1.0)

    def test_a_replayed_helper_moves_the_restored_object(self):
        self.run.run_all()
        pauses = [cp['index'] for cp in self.scene.animation_checkpoints if cp.get('stop')]
        self.scene._restore_checkpoint_for_display(pauses[1])
        self.assertAlmostEqual(self.scene._live_namespace['dot'].get_center()[0], 0.5)
        self.scene.advance_to_next_pausepoint()
        self.assertAlmostEqual(self.scene._live_namespace['dot'].get_center()[0], 1.0)

    def test_a_helpers_locals_stay_out_of_the_checkpoint(self):
        self.run.run_all()
        for checkpoint in self.scene.animation_checkpoints:
            self.assertNotIn('step', checkpoint['namespace'])
            self.assertNotIn('mob', checkpoint['namespace'])


class TestPauseAnchoredRun(unittest.TestCase):
    def setUp(self):
        self.run = HeadlessScene(PAUSED, 'PauseScene')
        self.scene = self.run.scene

    def tearDown(self):
        self.run.close()

    def test_bare_pauses_mark_the_stops(self):
        self.run.run_all()
        self.assertEqual(
            [bool(cp.get('stop')) for cp in self.scene.animation_checkpoints],
            [False, False, False, True, False, True, False],
        )

    def test_right_runs_a_stretch_and_rests_at_the_pause(self):
        self.scene.advance_to_next_pausepoint()
        self.assertEqual(self.scene.current_animation_index, 3)
        self.assertTrue(self.scene.animation_checkpoints[3].get('stop'))


if __name__ == '__main__':
    unittest.main()

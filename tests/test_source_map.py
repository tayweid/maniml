"""Unit tests for the AST-based animation source map."""

import textwrap
import unittest

from maniml.scene.source_map import (
    SourceMapError,
    build_units,
    next_stop_unit,
    pause_anchored,
    unit_for_line,
)


def scene_source(body: str) -> str:
    """Wrap a construct() body (4-space indented lines) in a scene class."""
    indented = textwrap.indent(textwrap.dedent(body), ' ' * 8)
    return f"from maniml import *\n\n\nclass MyScene(Scene):\n    def construct(self):\n{indented}"


class TestBuildUnits(unittest.TestCase):
    def test_simple_plays(self):
        src = scene_source("""\
            circle = Circle()
            self.play(Create(circle))
            square = Square()
            self.play(Transform(circle, square))
        """)
        units = build_units(src, 'MyScene')
        self.assertEqual(len(units), 2)
        self.assertTrue(all(u.has_stop for u in units))
        # First unit spans the setup line and the play line
        self.assertIn('circle = Circle()', units[0].source)
        self.assertIn('self.play(Create(circle))', units[0].source)
        # Second unit starts after the first play
        self.assertNotIn('Create(circle)', units[1].source)
        self.assertIn('Transform(circle, square)', units[1].source)

    def test_play_inside_nested_def_is_not_a_boundary(self):
        # A helper defined in construct() with a play in its body: the def
        # statement runs no animation, so it must fold into the unit of the
        # call that does. Otherwise the def becomes a unit that saves no
        # checkpoint and the stepper stalls on it.
        src = scene_source("""\
            def fly_in(pieces):
                row = VGroup()
                for t in pieces:
                    self.play(FadeIn(Tex(t)))
                return row
            cakes = fly_in(['a', 'b'])
            self.play(FadeOut(cakes))
            f = lambda m: self.play(FadeIn(m))
            self.play(Create(Circle()))
        """)
        units = build_units(src, 'MyScene')
        self.assertEqual(len(units), 2)
        self.assertIn('def fly_in', units[0].source)
        self.assertIn('cakes = fly_in', units[0].source)
        self.assertIn('FadeOut(cakes)', units[0].source)
        self.assertEqual(units[0].stops, 1)      # the def's plays don't count
        self.assertIn('lambda', units[1].source)
        self.assertEqual(units[1].stops, 1)

    def test_multiline_play_call(self):
        src = scene_source("""\
            circle = Circle()
            self.play(
                Create(circle),
                run_time=2,
            )
            self.play(FadeOut(circle))
        """)
        units = build_units(src, 'MyScene')
        self.assertEqual(len(units), 2)
        self.assertIn('run_time=2', units[0].source)
        # end_line covers the closing parenthesis
        compiled = compile(units[0].source, '<test>', 'exec')
        self.assertIsNotNone(compiled)

    def test_play_inside_for_loop_keeps_whole_loop(self):
        src = scene_source("""\
            dots = [Dot() for _ in range(3)]
            for dot in dots:
                dot.shift(RIGHT)
                self.play(Create(dot))
                self.wait(0.1)
            self.play(FadeOut(dots[0]))
        """)
        units = build_units(src, 'MyScene')
        self.assertEqual(len(units), 2)
        # The whole loop (including code after play) is one unit
        self.assertIn('for dot in dots:', units[0].source)
        self.assertIn('self.wait(0.1)', units[0].source)
        compile(units[0].source, '<test>', 'exec')

    def test_play_inside_if_block(self):
        src = scene_source("""\
            flag = True
            if flag:
                self.play(Create(Circle()))
            else:
                self.play(Create(Square()))
        """)
        units = build_units(src, 'MyScene')
        self.assertEqual(len(units), 1)
        self.assertIn('else:', units[0].source)
        compile(units[0].source, '<test>', 'exec')

    def test_trailing_statements_form_tail_unit(self):
        src = scene_source("""\
            self.play(Create(Circle()))
            self.wait(2)
        """)
        units = build_units(src, 'MyScene')
        self.assertEqual(len(units), 2)
        self.assertTrue(units[0].has_stop)
        self.assertFalse(units[1].has_stop)
        self.assertIn('self.wait(2)', units[1].source)

    def test_strings_and_comments_do_not_confuse_parser(self):
        src = scene_source("""\
            # self.play(this is a comment)
            label = Text("call self.play(x) to animate (:")
            self.play(Write(label))
        """)
        units = build_units(src, 'MyScene')
        self.assertEqual(len(units), 1)
        compile(units[0].source, '<test>', 'exec')

    def test_multiple_scene_classes_selects_by_name(self):
        src = (
            "class OtherScene(Scene):\n"
            "    def construct(self):\n"
            "        self.play(Create(Square()))\n"
            "\n"
            "class MyScene(Scene):\n"
            "    def construct(self):\n"
            "        self.play(Create(Circle()))\n"
        )
        units = build_units(src, 'MyScene')
        self.assertEqual(len(units), 1)
        self.assertIn('Circle', units[0].source)

    def test_missing_construct_raises(self):
        with self.assertRaises(SourceMapError):
            build_units("x = 1\n", 'MyScene')

    def test_syntax_error_propagates(self):
        with self.assertRaises(SyntaxError):
            build_units("def broken(:\n", 'MyScene')

    def test_unit_sources_reproduce_execution(self):
        """Executing all units in order == executing construct()."""
        src = scene_source("""\
            values = []
            self.play(values.append(1))
            for i in range(3):
                self.play(values.append(i))
            values.append('tail')
        """)
        units = build_units(src, 'MyScene')

        class FakeSelf:
            def play(self, *a, **k):
                pass

        namespace = {'self': FakeSelf()}
        for unit in units:
            exec(compile(unit.source, '<test>', 'exec'), namespace)
        self.assertEqual(namespace['values'], [1, 0, 1, 2, 'tail'])


class TestLookups(unittest.TestCase):
    def setUp(self):
        src = scene_source("""\
            a = 1
            self.play(a)
            b = 2
            self.play(b)
            self.wait()
        """)
        self.units = build_units(src, 'MyScene')

    def test_next_by_unit_index(self):
        self.assertEqual(next_stop_unit(self.units, after_unit_index=-1).index, 0)
        self.assertEqual(next_stop_unit(self.units, after_unit_index=0).index, 1)
        self.assertIsNone(next_stop_unit(self.units, after_unit_index=1))

    def test_next_by_line_fallback(self):
        first = next_stop_unit(self.units, after_line=0)
        self.assertEqual(first.index, 0)
        second = next_stop_unit(self.units, after_line=first.end_line)
        self.assertEqual(second.index, 1)
        self.assertIsNone(next_stop_unit(self.units, after_line=second.end_line))

    def test_unit_for_line(self):
        unit = unit_for_line(self.units, self.units[1].start_line)
        self.assertEqual(unit.index, 1)
        self.assertIsNone(unit_for_line(self.units, 999))


class TracebackLineTests(unittest.TestCase):
    """A unit is compiled with the real filename, so its line numbers have to
    be the file's. Otherwise Python reports a line counted from the top of the
    unit and prints the source found at that line in the file — blaming an
    unrelated statement, usually an import near the top."""

    SOURCE = textwrap.dedent("""
        from manim import *

        class Demo(Scene):
            def construct(self):
                dot = Dot()
                self.play(FadeIn(dot))
                boom = 1 / 0
                self.play(FadeOut(dot))
    """)

    def test_an_error_reports_the_line_it_is_on(self):
        import traceback

        unit = build_units(self.SOURCE, 'Demo')[1]
        # Caught by hand: assertRaises strips the traceback off the exception
        # it stores, and the traceback is the whole point here.
        try:
            exec(compile(unit.source, 'scene.py', 'exec'), {})
        except ZeroDivisionError as error:
            frames = traceback.extract_tb(error.__traceback__)
        else:
            self.fail("the unit did not raise")
        self.assertEqual(frames[-1].lineno, unit.start_line)
        # And the line it names really is the failing statement.
        lines = self.SOURCE.splitlines()
        self.assertIn('1 / 0', lines[unit.start_line - 1])


class IndeterminateUnitTests(unittest.TestCase):
    """A unit's play calls are not always a count of the pausepoints it will
    produce, and a timeline that draws one chip per play would be lying about
    scenes that loop."""

    SOURCE = textwrap.dedent("""
        from manim import *

        class Demo(Scene):
            def construct(self):
                dot = Dot()
                self.play(FadeIn(dot))
                for _ in range(4):
                    self.play(dot.animate.shift(RIGHT))
                if dot.get_x() > 0:
                    self.play(FadeOut(dot))
                else:
                    self.play(dot.animate.scale(2))
                self.wait()
    """)

    def setUp(self):
        self.units = build_units(self.SOURCE, 'Demo')

    def test_a_lone_play_is_exactly_one_pausepoint(self):
        self.assertEqual(self.units[0].stops, 1)
        self.assertFalse(self.units[0].loops)
        self.assertFalse(self.units[0].indeterminate)

    def test_a_loop_of_plays_has_no_knowable_count(self):
        """The trip count is a runtime value, so the unit can only say that
        it holds more than it shows."""
        self.assertTrue(self.units[1].loops)
        self.assertTrue(self.units[1].indeterminate)

    def test_branches_do_not_add_up(self):
        """Two written plays, one of which runs — a count of 2 would be as
        wrong as a count of 1."""
        self.assertEqual(self.units[2].stops, 2)
        self.assertFalse(self.units[2].loops)
        self.assertTrue(self.units[2].indeterminate)

    def test_a_tail_unit_plays_nothing(self):
        self.assertFalse(self.units[3].has_stop)
        self.assertEqual(self.units[3].stops, 0)
        self.assertFalse(self.units[3].indeterminate)


class PauseAnchoredUnitTests(unittest.TestCase):
    """A file that calls self.pause() anywhere authors its own pausepoints:
    every play is still a checkpoint boundary (that is what per-play
    navigation and the reverse morph run on), and pause statements are
    boundaries too, marked ``is_pause`` — the stops the viewer and the
    arrow keys move between."""

    def test_plays_and_pauses_are_both_boundaries(self):
        src = scene_source("""\
            circle = Circle()
            self.play(Create(circle))
            self.play(circle.animate.shift(RIGHT))
            self.pause()
            self.play(FadeOut(circle))
            self.pause()
        """)
        self.assertTrue(pause_anchored(src))
        units = build_units(src, 'MyScene')
        self.assertEqual(len(units), 5)
        self.assertTrue(all(u.has_stop for u in units))
        self.assertEqual([u.is_pause for u in units],
                         [False, False, True, False, True])
        # the setup line folds into its play's unit, as always
        self.assertIn('circle = Circle()', units[0].source)
        self.assertIn('Create(circle)', units[0].source)

    def test_a_file_without_pauses_stays_play_anchored(self):
        src = scene_source("""\
            self.play(Create(Circle()))
            self.play(Create(Square()))
        """)
        self.assertFalse(pause_anchored(src))
        units = build_units(src, 'MyScene')
        self.assertEqual(len(units), 2)
        self.assertFalse(any(u.is_pause for u in units))

    def test_next_section_is_a_pause(self):
        src = scene_source("""\
            self.play(Create(Circle()))
            self.next_section("shapes")
            self.play(Create(Square()))
            self.next_section()
        """)
        self.assertTrue(pause_anchored(src))
        units = build_units(src, 'MyScene')
        self.assertEqual(len(units), 4)
        self.assertEqual([u.is_pause for u in units],
                         [False, True, False, True])

    def test_pause_on_another_object_does_not_flip_the_mode(self):
        # A scene about a media player must not become pause-anchored
        # because its subject happens to have a pause() method.
        src = scene_source("""\
            player.pause()
            self.play(Create(Circle()))
            self.play(Create(Square()))
        """)
        self.assertFalse(pause_anchored(src))
        self.assertEqual(len(build_units(src, 'MyScene')), 2)

    def test_pause_in_helper_flips_mode_without_adding_a_boundary(self):
        # The pause fires at runtime inside the helper, so the file is
        # pause-anchored, but construct() shows no textual pause: units
        # still split at the plays, and the runtime pause's checkpoint
        # anchors to the unit that called the helper.
        src = scene_source("""\
            def beat(self):
                self.pause()
            self.play(Create(Circle()))
            beat(self)
            self.play(Create(Square()))
        """)
        self.assertTrue(pause_anchored(src))
        units = build_units(src, 'MyScene')
        self.assertEqual(len(units), 2)
        self.assertFalse(any(u.is_pause for u in units))
        self.assertIn('beat(self)', units[1].source)

    def test_pause_in_loop_is_indeterminate(self):
        src = scene_source("""\
            for i in range(3):
                self.play(Create(Circle()))
                self.pause()
        """)
        units = build_units(src, 'MyScene')
        self.assertEqual(len(units), 1)
        self.assertTrue(units[0].loops)
        self.assertTrue(units[0].indeterminate)
        self.assertTrue(units[0].is_pause)
        self.assertEqual(units[0].stops, 2)   # one play + one pause written

    def test_statements_after_the_last_boundary_form_the_tail(self):
        src = scene_source("""\
            self.play(Create(Circle()))
            self.pause()
            self.play(Create(Square()))
            self.wait(0.1)
        """)
        units = build_units(src, 'MyScene')
        self.assertEqual(len(units), 4)
        self.assertFalse(units[3].has_stop)
        self.assertFalse(units[3].is_pause)
        self.assertIn('wait', units[3].source)


if __name__ == '__main__':
    unittest.main()

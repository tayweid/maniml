"""Unit tests for the AST-based animation source map."""

import textwrap
import unittest

from maniml.scene.source_map import (
    SourceMapError,
    build_units,
    next_play_unit,
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
        self.assertTrue(all(u.has_play for u in units))
        # First unit spans the setup line and the play line
        self.assertIn('circle = Circle()', units[0].source)
        self.assertIn('self.play(Create(circle))', units[0].source)
        # Second unit starts after the first play
        self.assertNotIn('Create(circle)', units[1].source)
        self.assertIn('Transform(circle, square)', units[1].source)

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
        self.assertTrue(units[0].has_play)
        self.assertFalse(units[1].has_play)
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
        self.assertEqual(next_play_unit(self.units, after_unit_index=-1).index, 0)
        self.assertEqual(next_play_unit(self.units, after_unit_index=0).index, 1)
        self.assertIsNone(next_play_unit(self.units, after_unit_index=1))

    def test_next_by_line_fallback(self):
        first = next_play_unit(self.units, after_line=0)
        self.assertEqual(first.index, 0)
        second = next_play_unit(self.units, after_line=first.end_line)
        self.assertEqual(second.index, 1)
        self.assertIsNone(next_play_unit(self.units, after_line=second.end_line))

    def test_unit_for_line(self):
        unit = unit_for_line(self.units, self.units[1].start_line)
        self.assertEqual(unit.index, 1)
        self.assertIsNone(unit_for_line(self.units, 999))


if __name__ == '__main__':
    unittest.main()

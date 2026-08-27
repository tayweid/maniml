"""Synthetic complements to the real course-scene dogfood corpus."""
from manim import *
import os


class LargeStatic(Scene):
    """Many mergeable siblings, followed by a one-object change."""

    def construct(self):
        count = int(os.environ.get("MANIML_BENCH_OBJECTS", "500"))
        columns = 50
        squares = VGroup(*[
            Square(side_length=0.08, stroke_width=1)
            .move_to(((index % columns) - columns / 2) * 0.12 * RIGHT
                     + ((index // columns) - count / columns / 2) * 0.12 * UP)
            for index in range(count)
        ])
        self.add(squares)
        self.play(squares[0].animate.shift(RIGHT * 0.05), run_time=0.1)


class ParkedAlwaysRedraw(Scene):
    """A common course pattern whose updater remains after motion stops."""

    def construct(self):
        tracker = ValueTracker(0)
        dot = always_redraw(lambda: Dot().shift(tracker.get_value() * RIGHT))
        label = always_redraw(
            lambda: DecimalNumber(tracker.get_value()).next_to(dot, UP))
        self.add(dot, label)
        self.play(tracker.animate.set_value(1), run_time=0.1)

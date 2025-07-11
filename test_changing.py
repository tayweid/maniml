#!/usr/bin/env python3
"""Test AnimatedBoundary and TracedPath."""

from manim import *

class TestAnimatedBoundary(Scene):
    def construct(self):
        # Test with text
        text = Text("So shiny!", font_size=72)
        boundary = AnimatedBoundary(
            text, 
            colors=[RED, GREEN, BLUE, YELLOW],
            cycle_rate=3,
            max_stroke_width=5
        )
        self.add(text, boundary)
        self.wait(3)
        
        # Move to show it follows
        self.play(text.animate.shift(RIGHT * 2))
        self.wait(2)

class TestTracedPath(Scene):
    def construct(self):
        # Rolling circle example
        circ = Circle(color=RED).shift(4*LEFT)
        dot = Dot(color=RED).move_to(circ.get_start())
        rolling_circle = VGroup(circ, dot)
        trace = TracedPath(circ.get_start)
        rolling_circle.add_updater(lambda m: m.rotate(-0.3))
        self.add(trace, rolling_circle)
        self.play(rolling_circle.animate.shift(8*RIGHT), run_time=4, rate_func=linear)
        self.wait()

class TestDissipatingPath(Scene):
    def construct(self):
        # Dissipating path example
        a = Dot(RIGHT * 2, color=YELLOW)
        b = TracedPath(
            a.get_center, 
            dissipating_time=0.5, 
            stroke_color=YELLOW,
            stroke_width=6
        )
        self.add(a, b)
        self.play(a.animate(path_arc=PI / 4).shift(LEFT * 2))
        self.play(a.animate(path_arc=-PI / 4).shift(LEFT * 2))
        self.play(a.animate.shift(UP * 2))
        self.play(a.animate.shift(DOWN * 2))
        self.wait()

if __name__ == "__main__":
    from manim.renderer.opengl.window import Window
    window = Window()
    scene = TestAnimatedBoundary(window=window)
    scene.run()
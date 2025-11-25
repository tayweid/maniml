from manim import *
from manim.mobject.svg.text_mobject import MarkupText

class TestTextNoApprox(Scene):
    def construct(self):
        # Test with MarkupText directly, without the simple quadratic approx
        text = MarkupText("Hello World", font_size=72)
        self.play(FadeIn(text))

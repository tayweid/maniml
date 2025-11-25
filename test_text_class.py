from manim import *

class TestTextClass(Scene):
    def construct(self):
        text = Text("Hello World", font_size=72)
        self.play(FadeIn(text))

from manim import *

class TestText3D(ThreeDScene):
    def construct(self):
        text = Text("Hello World", font_size=72)
        self.play(FadeIn(text))

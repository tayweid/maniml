from manim import *

class TestTextSimple(Scene):
    def construct(self):
        # Simple 2D text test
        text = Text("Hello World", font_size=72)
        self.add(text)
        self.wait()

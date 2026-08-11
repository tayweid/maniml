from manim import *

class TestCircle(Scene):
    def construct(self):
        # Test circle with explicit fill
        circle = Circle(radius=2, fill_opacity=1, fill_color=BLUE, stroke_color=RED, stroke_width=4)
        self.add(circle)
        self.wait()

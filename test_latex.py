from manim import *

class TestLatex(Scene):
    def construct(self):
        # Test basic LaTeX text
        text = Tex("Hello World", font_size=72)
        text.set_color(YELLOW)
        self.play(Write(text))
        self.wait(2)

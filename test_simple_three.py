from manim import *

class TestSimpleThree(Scene):
    def construct(self):
        # First
        c = Circle()
        self.play(Create(c))
        
        # Second
        self.play(c.animate.shift(RIGHT))
        
        # Third
        self.play(c.animate.shift(LEFT))
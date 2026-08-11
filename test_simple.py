from manim import *

class TestSimple(Scene):
    def construct(self):
        # Animation 1
        c = Circle()
        self.play(Create(c))
        
        # Animation 2  
        self.play(c.animate.shift(RIGHT))
        
        # Animation 3
        self.play(c.animate.shift(LEFT * 2))
        
        self.wait(1)
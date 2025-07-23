from manim import *

class TestSimpleCircle(Scene):  # Not ThreeDScene - regular 2D
    def construct(self):
        # Circle in 2D scene - should work normally
        circle = Circle(
            radius=2, 
            fill_opacity=0.8, 
            fill_color=RED, 
            stroke_color=WHITE,
            stroke_width=10
        )
        
        self.play(Create(circle))
        self.wait(1)
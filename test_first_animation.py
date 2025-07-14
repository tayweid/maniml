"""Test script to verify that only the first animation plays."""

from manim import *

class TestFirstAnimation(Scene):
    def construct(self):
        # First animation - this should play
        circle = Circle(color=BLUE)
        self.play(Create(circle))
        
        # Second animation - this should be skipped
        square = Square(color=RED)
        self.play(Transform(circle, square))
        
        # Third animation - this should also be skipped
        self.play(circle.animate.shift(RIGHT * 2))
        
        # Wait - this should also be skipped
        self.wait(2)
        
        print("Construct method finished - only first animation should have played")
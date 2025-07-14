"""Test script for file watcher functionality."""

from manim import *

class TestFileWatcher(Scene):
    def construct(self):
        # Create a circle
        circle = Circle(color=BLUE, radius=1)
        self.play(Create(circle))
        
        # Create a square
        square = Square(color=RED, side_length=2)
        self.play(Create(square))
        
        # Move them around
        self.play(
            circle.animate.shift(LEFT * 2),
            square.animate.shift(RIGHT * 2)
        )
        
        # Transform circle to triangle
        triangle = Triangle(color=GREEN)
        self.play(Transform(circle, triangle))
        
        # Final wait
        self.wait(1)
        
        # Enable interactive mode to keep window open
        self.interactive_embed(terminal=False)
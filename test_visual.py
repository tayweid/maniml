"""Visual test to confirm only first animation plays."""

from manim import *

class VisualTest(Scene):
    def construct(self):
        # Create three distinct objects
        circle = Circle(color=BLUE, radius=1).shift(LEFT * 3)
        square = Square(color=RED, side_length=2)
        triangle = Triangle(color=GREEN).shift(RIGHT * 3)
        
        # First animation - should play
        print("Playing first animation: Create circle")
        self.play(Create(circle))
        
        # Second animation - should be skipped
        print("Playing second animation: Create square (should be skipped)")
        self.play(Create(square))
        
        # Third animation - should be skipped
        print("Playing third animation: Create triangle (should be skipped)")
        self.play(Create(triangle))
        
        # Wait - should also be skipped
        print("Waiting (should be skipped)")
        self.wait(2)
        
        print("\nIf only the blue circle appears, first-animation-only is working!")
        print("Press arrow keys to navigate between animations")
        
        # Keep window open
        self.interactive_embed(terminal=False)
from manim import *

class WatcherTest(Scene):
    def construct(self):
        # Animation 1
        circle = Circle(color=BLUE, radius=1)
        self.play(Create(circle))
        
        # Animation 2
        square = Square(color=RED, side_length=2)
        self.play(Create(square))
        
        # Animation 3
        triangle = Triangle(color=GREEN)
        self.play(Create(triangle))
        
        # Keep window open for testing
        self.interactive_embed(terminal=False)
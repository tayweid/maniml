from manim import *

class TestFirstAnimation(Scene):
    def construct(self):
        print("In user's construct method")
        
        # First animation
        circle = Circle()
        self.add(circle)
        self.play(Create(circle))
        print("First animation done")
        
        # Second animation
        square = Square()
        square.shift(RIGHT * 2)
        self.play(Create(square))
        print("Second animation done")
        
        # Third animation
        self.play(circle.animate.shift(LEFT * 2))
        print("Third animation done")
        
        # Enter interactive mode
        self.interactive_embed(terminal=False)
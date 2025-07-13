from manim import *

class TestEmptyStart(Scene):
    def construct(self):
        # First animation - red circle
        print("Creating red circle...")
        circle = Circle(color=RED, radius=1)
        self.add(circle)
        self.play(Create(circle))
        print("First animation complete!")
        
        # Second animation - blue square
        print("Creating blue square...")
        square = Square(color=BLUE, side_length=2)
        square.shift(RIGHT * 3)
        self.play(Create(square))
        print("Second animation complete!")
        
        # Third animation - move both
        print("Moving objects...")
        self.play(
            circle.animate.shift(LEFT * 2),
            square.animate.shift(LEFT * 2)
        )
        print("Third animation complete!")
        
        print("All animations done - entering interactive mode")
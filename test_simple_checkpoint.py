from manim import *

class TestSimpleCheckpoint(Scene):
    def construct(self):
        # Create circle
        circle = Circle(color=RED).shift(LEFT)
        self.add(circle)
        self.play(Create(circle))
        
        # Create square - circle should still be visible
        square = Square(color=BLUE).shift(RIGHT)
        self.play(Create(square))
        
        print("\nTo test: Jump back with ← then forward with →")
        print("Both shapes should be visible, with no duplicates")
        
        self.interactive_embed(terminal=False)
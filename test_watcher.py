from manim import *

class TestWatcher(Scene):
    def construct(self):
        # Create a circle
        circle = Circle(color=BLUE)
        self.play(Create(circle))
        
        # Transform to square
        square = Square(color=RED)
        self.play(Transform(circle, square))
        
        # Move it
        self.play(circle.animate.shift(RIGHT * 2))
        
        # Scale it
        self.play(circle.animate.scale(2))
        
        # Add some text
        text = Text("File Watcher Test")
        self.play(Write(text))
        
        self.wait()
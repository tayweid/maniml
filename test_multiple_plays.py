from manim import *

class TestMultiplePlays(Scene):
    def construct(self):
        # First animation
        circle = Circle(color=BLUE)
        self.play(Create(circle))
        
        # Second animation
        square = Square(color=RED)
        self.play(FadeIn(square))
        
        # Third animation
        self.play(circle.animate.shift(LEFT * 3))
        
        # Fourth animation
        self.play(
            square.animate.shift(RIGHT * 3)
        )
        
        # Fifth animation
        self.play(circle.animate.scale(0.6), square.animate.scale(1.6))
        
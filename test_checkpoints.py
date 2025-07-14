from manim import *

class TestCheckpoints(Scene):
    def construct(self):
        # First animation
        circle = Circle()
        self.add(circle)
        self.play(Create(circle))
        
        # Second animation
        square = Square()
        square.shift(RIGHT * 2)
        self.play(Create(square))
        
        # Third animation
        self.play(circle.animate.shift(LEFT * 2))
        
        # Fourth animation
        self.play(
            circle.animate.set_color(RED),
            square.animate.set_color(BLUE)
        )
        
        # Fifth animation with wait (should not create checkpoint)
        self.wait(0.5)
        triangle = Triangle()
        triangle.shift(UP * 2)
        self.play(Create(triangle))
        
        # Interactive embed to test navigation
        self.interactive_embed(terminal=False)
from manim import *

class TestCheckpointVisibility(Scene):
    def construct(self):
        # Create and show circle
        circle = Circle(color=RED)
        circle.shift(LEFT * 2)
        self.add(circle)
        self.play(Create(circle))
        
        # Create and show square - circle should still be visible
        square = Square(color=BLUE)
        square.shift(RIGHT * 2)
        self.play(Create(square))
        
        # Animate both - both should be visible
        self.play(
            circle.animate.shift(UP),
            square.animate.shift(UP)
        )
        
        # Create triangle - circle and square should still be visible
        triangle = Triangle(color=GREEN)
        triangle.shift(DOWN * 2)
        self.play(Create(triangle))
        
        # Animate all three - all should be visible
        self.play(
            circle.animate.scale(0.5),
            square.animate.scale(0.5),
            triangle.animate.scale(0.5)
        )
        
        print("\nTest complete! Use arrow keys to navigate:")
        print("- After jumping back, press RIGHT to play forward")
        print("- All shapes should remain visible throughout")
        
        # Interactive embed to test navigation
        self.interactive_embed(terminal=False)
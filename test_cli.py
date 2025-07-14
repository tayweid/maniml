from manim import *

class TestCLI(Scene):
    def construct(self):
        print("\n=== TestCLI Starting ===")
        print(f"_animations_to_play: {self._animations_to_play}")
        print(f"_animations_played: {self._animations_played}")
        
        # First animation
        circle = Circle(color=BLUE, radius=1)
        print("\nAnimation 1: Creating blue circle")
        self.play(Create(circle))
        
        # Second animation  
        square = Square(color=RED, side_length=2)
        print("\nAnimation 2: Creating red square (should skip)")
        self.play(Create(square))
        
        # Third animation
        triangle = Triangle(color=GREEN)
        print("\nAnimation 3: Creating green triangle (should skip)")
        self.play(Create(triangle))
        
        print("\n=== TestCLI Complete ===")
        print("If only blue circle is visible, it worked!")
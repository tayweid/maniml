from manim import *

class TestDebug(Scene):
    def construct(self):
        # Add debug output
        print(f"Starting scene, current_animation_index: {self.current_animation_index}")
        print(f"Number of checkpoints: {len(self.animation_checkpoints)}")
        
        # First animation
        circle = Circle(color=BLUE)
        print("About to play animation 1")
        self.play(Create(circle))
        print(f"After animation 1: index={self.current_animation_index}, checkpoints={len(self.animation_checkpoints)}")
        
        # Second animation
        square = Square(color=RED)
        print("About to play animation 2")
        self.play(Create(square))
        print(f"After animation 2: index={self.current_animation_index}, checkpoints={len(self.animation_checkpoints)}")
        
        # Third animation
        print("About to play animation 3")
        self.play(circle.animate.shift(LEFT * 2))
        print(f"After animation 3: index={self.current_animation_index}, checkpoints={len(self.animation_checkpoints)}")
        
        self.wait(1)
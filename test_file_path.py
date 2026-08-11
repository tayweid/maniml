from manim import *

class TestFilePath(Scene):
    def construct(self):
        # Check if file path is tracked
        print(f"Scene file path: {getattr(self, '_scene_filepath', 'NOT SET')}")
        
        # First animation
        circle = Circle(color=BLUE)
        self.play(Create(circle))
        
        # Check checkpoints
        for i, cp in enumerate(self.animation_checkpoints):
            print(f"Checkpoint {i}: line {cp.get('line_number', 'N/A')}")
        
        # Second animation
        self.play(circle.animate.shift(RIGHT))
        
        print("Ready for navigation")
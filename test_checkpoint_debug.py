from manim import *
import time

class TestCheckpointDebug(Scene):
    def construct(self):
        # Override run_next_animation to add more debugging
        original_run_next = self.run_next_animation
        
        def debug_run_next():
            print("\n=== DEBUG: run_next_animation called ===")
            print(f"Current animation index: {self.current_animation_index}")
            print(f"Total checkpoints: {len(self.animation_checkpoints)}")
            for i, cp in enumerate(self.animation_checkpoints):
                print(f"  Checkpoint {i}: line {cp.get('line_number', 'N/A')}")
            return original_run_next()
        
        self.run_next_animation = debug_run_next
        
        # Animation 1
        c = Circle()
        self.play(Create(c))
        
        # Animation 2
        self.play(c.animate.shift(RIGHT))
        
        # Animation 3
        self.play(c.animate.shift(LEFT))
        
        print("\nScene complete. Press arrow keys to navigate.")
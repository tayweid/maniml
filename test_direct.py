"""Direct test without running through manim module."""

import sys
sys.path.insert(0, '.')

from manim import *

class DirectTest(Scene):
    def __init__(self, *args, **kwargs):
        print("[DirectTest __init__]")
        super().__init__(*args, **kwargs)
        
    def play(self, *args, **kwargs):
        print(f"[DirectTest.play] called, delegating to super")
        return super().play(*args, **kwargs)
        
    def construct(self):
        print(f"\n[CONSTRUCT CALLED]")
        print(f"Scene class: {self.__class__}")
        print(f"_animations_to_play: {getattr(self, '_animations_to_play', 'NOT SET')}")
        print(f"_animations_played: {getattr(self, '_animations_played', 'NOT SET')}")
        
        # First animation
        circle = Circle(color=BLUE)
        print("About to call play...")
        self.play(Create(circle))
        print(f"After first play - _animations_played: {self._animations_played}")
        
        # Second animation - should be skipped
        print("About to call play again...")
        self.play(circle.animate.shift(RIGHT * 2))
        print(f"After second play - _animations_played: {self._animations_played}")
        
        print("[CONSTRUCT DONE]")

if __name__ == "__main__":
    from manim.renderer.opengl.window import Window
    window = Window()
    scene = DirectTest(window=window)
    scene.run()
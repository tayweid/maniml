"""Simple test to verify first animation only."""

from manim import *

print(f"[DEBUG] Scene class: {Scene}")
print(f"[DEBUG] Scene module: {Scene.__module__}")

class SimpleTest(Scene):
    def play(self, *args, **kwargs):
        print("[TEST PLAY CALLED]")
        return super().play(*args, **kwargs)
        
    def construct(self):
        print(f"[DEBUG] SimpleTest.play method: {self.play}")
        print(f"[DEBUG] SimpleTest base classes: {self.__class__.__bases__}")
        print("Starting construct - animations played:", self._animations_played)
        
        # First animation
        circle = Circle(color=BLUE)
        print("Before first play - animations played:", self._animations_played)
        self.play(FadeIn(circle))
        print("After first play - animations played:", self._animations_played)
        
        # Second animation - should be skipped
        print("Before second play - animations played:", self._animations_played)
        self.play(circle.animate.shift(RIGHT * 2))
        print("After second play - animations played:", self._animations_played)
        
        print("Finished construct")
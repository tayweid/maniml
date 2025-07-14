#!/usr/bin/env python
"""Minimal test."""

import sys
import os

# Add current directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Now import
from manim.scene.scene import Scene
from manim.mobject.geometry import Circle
from manim.animation.creation import Create

print(f"Scene module: {Scene.__module__}")
print(f"Scene file: {Scene.__module__.__file__ if hasattr(Scene.__module__, '__file__') else 'N/A'}")

class MinimalTest(Scene):
    def construct(self):
        print(f"\nIn construct:")
        print(f"  self.__class__: {self.__class__}")
        print(f"  self.play: {self.play}")
        print(f"  _animations_to_play: {self._animations_to_play}")
        print(f"  _animations_played: {self._animations_played}")
        
        # Test
        circle = Circle()
        self.play(Create(circle))
        print(f"  After play: _animations_played = {self._animations_played}")

# Run directly
if __name__ == "__main__":
    from manim.renderer.opengl.window import Window
    scene = MinimalTest(window=Window())
    scene.run()
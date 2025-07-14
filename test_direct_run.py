#!/usr/bin/env python
"""Test running scene directly."""

import sys
import os

# Add maniml to path
sys.path.insert(0, os.path.dirname(__file__))

from manim import *

class DirectTest(Scene):
    def construct(self):
        print("\n=== DirectTest Starting ===")
        print(f"Has _animations_to_play: {hasattr(self, '_animations_to_play')}")
        print(f"Has _animations_played: {hasattr(self, '_animations_played')}")
        if hasattr(self, '_animations_to_play'):
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
        
        print("\n=== DirectTest Complete ===")

if __name__ == "__main__":
    # Create scene directly
    from manim.renderer.opengl.window import Window
    window = Window()
    scene = DirectTest(window=window)
    scene.run()
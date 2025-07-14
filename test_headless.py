#!/usr/bin/env python
"""Test in headless mode."""

import sys
import os

# Add maniml to path
sys.path.insert(0, os.path.dirname(__file__))

# Set headless mode before importing
os.environ['MANIMGL_HEADLESS'] = '1'

from manim import *

class HeadlessTest(Scene):
    def construct(self):
        print("\n=== HeadlessTest Starting ===")
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
        
        # Check what's in scene
        print(f"\nMobjects in scene: {len(self.mobjects)}")
        for mob in self.mobjects:
            print(f"  - {type(mob).__name__}")
        
        print("\n=== HeadlessTest Complete ===")
        
        # Exit without waiting
        self.quit_early = True

if __name__ == "__main__":
    # Create scene directly
    scene = HeadlessTest()
    scene.run()
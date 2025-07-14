#!/usr/bin/env python
"""Test improved skip implementation."""

import os
os.environ['MANIMGL_HEADLESS'] = '1'

from manim import *

class SkipImprovedTest(Scene):
    def construct(self):
        print("\n=== SkipImprovedTest Starting ===")
        print(f"_animations_to_play: {self._animations_to_play}")
        print(f"_animations_played: {self._animations_played}")
        print(f"skip_animations: {self.skip_animations}")
        
        # First animation - should play
        circle = Circle(color=BLUE, radius=1).shift(LEFT * 3)
        print("\nAnimation 1: Creating blue circle")
        self.play(Create(circle))
        print(f"After animation 1: skip_animations = {self.skip_animations}")
        
        # Second animation - should be skipped
        square = Square(color=RED, side_length=2)
        print("\nAnimation 2: Creating red square (should skip)")
        self.play(Create(square))
        print(f"After animation 2: skip_animations = {self.skip_animations}")
        
        # Third animation - should be skipped
        triangle = Triangle(color=GREEN).shift(RIGHT * 3)
        print("\nAnimation 3: Creating green triangle (should skip)")
        self.play(Create(triangle))
        
        # Wait - should also be skipped
        print("\nWait (should skip)")
        self.wait(2)
        
        # Check what's in scene
        print(f"\nMobjects in scene: {len(self.mobjects)}")
        for mob in self.mobjects:
            print(f"  - {type(mob).__name__}")
        
        print("\n=== SkipImprovedTest Complete ===")
        self.quit_early = True

if __name__ == "__main__":
    scene = SkipImprovedTest()
    scene.run()
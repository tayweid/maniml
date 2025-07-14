#!/usr/bin/env python
"""Debug skip logic."""

from manim import *

class DebugSkip(Scene):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        print(f"\nAfter __init__:")
        print(f"  _animations_to_play: {self._animations_to_play}")
        print(f"  _animations_played: {self._animations_played}")
    
    def construct(self):
        print("\nIn construct():")
        print(f"  _animations_to_play: {self._animations_to_play}")
        print(f"  _animations_played: {self._animations_played}")
        
        # First animation
        circle = Circle(color=BLUE)
        print("\nBefore first play():")
        print(f"  _animations_played: {self._animations_played}")
        
        self.play(Create(circle))
        
        print("\nAfter first play():")
        print(f"  _animations_played: {self._animations_played}")
        print(f"  Should skip next? {self._animations_played >= self._animations_to_play}")
        
        # Second animation
        square = Square(color=RED)
        print("\nBefore second play():")
        print(f"  _animations_played: {self._animations_played}")
        
        self.play(Create(square))
        
        print("\nAfter second play():")
        print(f"  _animations_played: {self._animations_played}")
        
        # Check what's in scene
        print(f"\nMobjects in scene: {len(self.mobjects)}")
        for mob in self.mobjects:
            print(f"  - {type(mob).__name__}")
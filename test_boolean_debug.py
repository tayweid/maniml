#!/usr/bin/env python3
"""Debug boolean operations."""

from manim import *

class TestBooleanDebug(Scene):
    def construct(self):
        # Create very simple shapes
        c1 = Circle(radius=1, color=RED, fill_opacity=0.5)
        c2 = Circle(radius=1, color=BLUE, fill_opacity=0.5)
        
        c1.shift(LEFT * 0.5)
        c2.shift(RIGHT * 0.5)
        
        # Add original shapes
        self.add(c1, c2)
        
        # Debug info
        print(f"c1 points: {len(c1.get_points())}")
        print(f"c2 points: {len(c2.get_points())}")
        print(f"c1 subpaths: {len(list(c1.get_subpaths()))}")
        print(f"c2 subpaths: {len(list(c2.get_subpaths()))}")
        
        # Try intersection
        try:
            inter = Intersection(c1, c2, color=GREEN, fill_opacity=0.8)
            self.add(inter)
            print(f"Intersection created successfully")
            print(f"Intersection points: {len(inter.get_points())}")
        except Exception as e:
            print(f"Error creating intersection: {e}")
            import traceback
            traceback.print_exc()
        
        self.wait(2)

if __name__ == "__main__":
    from manim.renderer.opengl.window import Window
    window = Window()
    scene = TestBooleanDebug(window=window)
    scene.run()
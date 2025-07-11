#!/usr/bin/env python3
"""Minimal test of pathops."""

import pathops
from manim import *

# Test basic pathops functionality
path1 = pathops.Path()
path1.moveTo(0, 0)
path1.lineTo(1, 0)
path1.lineTo(1, 1)
path1.lineTo(0, 1)
path1.close()

path2 = pathops.Path()
path2.moveTo(0.5, 0.5)
path2.lineTo(1.5, 0.5)
path2.lineTo(1.5, 1.5)
path2.lineTo(0.5, 1.5)
path2.close()

# Try intersection
result = pathops.Path()
try:
    pathops.intersection([path1], [path2], result.getPen())
    print("Basic pathops intersection works!")
except Exception as e:
    print(f"Error with basic pathops: {e}")

# Now test with manim shapes
class TestPathopsMinimal(Scene):
    def construct(self):
        # Create a simple square
        square = Square(side_length=2)
        print(f"Square points: {square.get_points()}")
        print(f"Square subpaths: {list(square.get_subpaths())}")
        
        # Try to convert to pathops
        try:
            path = pathops.Path()
            for subpath in square.get_subpaths():
                if len(subpath) >= 3:
                    path.moveTo(float(subpath[0][0]), float(subpath[0][1]))
                    # Try simpler approach - just line segments
                    for i in range(2, len(subpath), 2):
                        if i < len(subpath):
                            path.lineTo(float(subpath[i][0]), float(subpath[i][1]))
                    path.close()
            print("Successfully created pathops path from square")
        except Exception as e:
            print(f"Error converting square to pathops: {e}")
            import traceback
            traceback.print_exc()
        
        self.add(square)
        self.wait(1)

if __name__ == "__main__":
    # Run pathops test first
    print("Testing basic pathops...")
    
    # Then run manim test
    from manim.renderer.opengl.window import Window
    window = Window()
    scene = TestPathopsMinimal(window=window)
    scene.run()
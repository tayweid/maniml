from manim import *

class SimpleDepthTest(ThreeDScene):
    def construct(self):
        print("\n=== SimpleDepthTest Starting ===")
        
        # Set camera
        self.set_camera_orientation(phi=70 * DEGREES, theta=-45 * DEGREES)
        
        # Create a plane
        plane = Square3D(side_length=4, color=GREY_D, opacity=0.8)
        print(f"Created plane: {type(plane).__name__}")
        
        # Create text
        text = Text("Test", color=WHITE)
        text.shift(OUT * 0.5)
        print(f"Created text: {type(text).__name__}")
        
        # Add them
        print("\nAdding plane...")
        self.play(Create(plane))
        
        print("\nAdding text...")
        self.play(Create(text))
        
        print("\n=== SimpleDepthTest Complete ===")
        self.wait(3)
from manim import *

class SimpleTextDepth(ThreeDScene):
    """Simple test of text depth."""
    
    def construct(self):
        self.set_camera_orientation(phi=70 * DEGREES, theta=-45 * DEGREES)
        
        # Plane
        plane = Square3D(side_length=4, color=GREY_D, opacity=0.8)
        
        # Text in front
        text = Text("TEXT", color=WHITE, font_size=50)
        text.shift(OUT * 1)
        
        # Add with play
        self.play(Create(plane))
        self.play(Write(text))
        
        # Print debug info
        print(f"\nText depth_test: {text.depth_test}")
        print(f"Text has {len(text.submobjects)} submobjects")
        for i, sub in enumerate(text.submobjects):
            print(f"  Submob {i}: depth_test={sub.depth_test}")
        
        # Rotate camera
        self.begin_ambient_camera_rotation(rate=0.15)
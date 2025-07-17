from manim import *

class TestSimpleDepth(ThreeDScene):
    """Simple test to verify text depth works."""
    
    def construct(self):
        self.set_camera_orientation(phi=70 * DEGREES, theta=-45 * DEGREES)
        
        # Plane in the middle
        plane = Square3D(side_length=3, color=GREY_D, opacity=0.8)
        
        # Text in front
        text_front = Text("Front", color=GREEN, font_size=30)
        text_front.shift(OUT * 1)
        
        # Text behind
        text_behind = Text("Behind", color=RED, font_size=30)
        text_behind.shift(IN * 1)
        
        # Text intersecting
        text_middle = Text("Middle", color=BLUE, font_size=30)
        text_middle.shift(OUT * 0.01)  # Just barely in front
        
        # Add all
        self.add(plane)
        self.add(text_front, text_behind, text_middle)
        
        # Rotate to see depth
        self.begin_ambient_camera_rotation(rate=0.15)
        self.wait(10)
        self.stop_ambient_camera_rotation()
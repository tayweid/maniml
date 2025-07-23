from manim import *

class TestStrokeOffset(ThreeDScene):
    def construct(self):
        # Set up 3D view
        self.set_camera_orientation(phi=70 * DEGREES, theta=-45 * DEGREES)
        
        # Create a circle with stroke slightly offset towards camera
        circle = Circle(
            radius=2, 
            fill_opacity=0.8, 
            fill_color=RED, 
            stroke_color=WHITE,
            stroke_width=10
        )
        
        # Workaround: Create separate objects for fill and stroke
        fill_circle = Circle(radius=2, fill_opacity=0.8, fill_color=RED, stroke_width=0)
        stroke_circle = Circle(radius=2, fill_opacity=0, stroke_color=WHITE, stroke_width=10)
        
        # Offset stroke slightly towards camera
        stroke_circle.shift(OUT * 0.001)
        
        # Group them together
        circle_group = VGroup(fill_circle, stroke_circle)
        
        self.add(circle_group)
        
        # Test with rotation
        self.begin_ambient_camera_rotation(rate=0.3)
        self.wait(5)
        self.stop_ambient_camera_rotation()
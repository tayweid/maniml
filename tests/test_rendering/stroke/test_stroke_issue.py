from manim import *

class TestStrokeIssue(ThreeDScene):
    def construct(self):
        # Set up 3D view
        self.set_camera_orientation(phi=0 * DEGREES, theta=-90 * DEGREES)
        
        # Test without animation to avoid repeated triangulation
        circle1 = Circle(
            radius=1, 
            fill_opacity=0.8, 
            fill_color=RED, 
            stroke_color=WHITE,
            stroke_width=10
        )
        circle1.shift(LEFT * 2)
        
        # Try with separate set_stroke call
        circle2 = Circle(radius=1, fill_opacity=0.8, fill_color=BLUE)
        circle2.set_stroke(color=YELLOW, width=10)
        circle2.shift(RIGHT * 2)
        
        self.add(circle1, circle2)
        self.wait(1)
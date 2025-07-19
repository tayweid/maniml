from manim import *

class TestCircleStroke(ThreeDScene):
    def construct(self):
        # Set up 3D view
        self.set_camera_orientation(phi=70 * DEGREES, theta=-45 * DEGREES)
        
        # Circle with white stroke
        circle = Circle(
            radius=2, 
            fill_opacity=0.8, 
            fill_color=RED, 
            stroke_color=WHITE,
            stroke_width=5
        )
        
        # Square for comparison
        square = Square(
            side_length=3,
            fill_opacity=0.8,
            fill_color=BLUE,
            stroke_color=YELLOW,
            stroke_width=5
        )
        square.shift(RIGHT * 4)
        
        self.add(circle, square)
        self.wait(2)
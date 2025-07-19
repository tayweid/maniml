from manim import *

class TestDepthOrder(ThreeDScene):
    def construct(self):
        # Set up 3D view
        self.set_camera_orientation(phi=70 * DEGREES, theta=-45 * DEGREES)
        
        # Circle with no fill - just stroke
        circle_stroke_only = Circle(
            radius=1,
            fill_opacity=0,  # No fill
            stroke_color=GREEN,
            stroke_width=10
        )
        circle_stroke_only.shift(LEFT * 4)
        
        # Circle with fill and stroke
        circle_both = Circle(
            radius=1, 
            fill_opacity=0.8, 
            fill_color=RED, 
            stroke_color=WHITE,
            stroke_width=10
        )
        
        # Square for comparison
        square = Square(
            side_length=2,
            fill_opacity=0.8,
            fill_color=BLUE,
            stroke_color=YELLOW,
            stroke_width=10
        )
        square.shift(RIGHT * 4)
        
        self.play(
            FadeIn(circle_stroke_only),
            FadeIn(circle_both),
            FadeIn(square)
        )
        
        # Rotate to see depth
        self.begin_ambient_camera_rotation(rate=0.2)
        self.wait(5)
        self.stop_ambient_camera_rotation()
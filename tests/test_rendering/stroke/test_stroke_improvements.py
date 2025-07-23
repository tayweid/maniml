from manim import *

class TestStrokeImprovements(ThreeDScene):
    def construct(self):
        # Set up 3D view
        self.set_camera_orientation(phi=70 * DEGREES, theta=-45 * DEGREES)
        
        # Create two circles to show the improvements
        circle1 = Circle(
            radius=2, 
            fill_opacity=0.8, 
            fill_color=RED, 
            stroke_color=WHITE,
            stroke_width=10
        )
        circle1.shift(LEFT * 3)
        
        circle2 = Circle(
            radius=2,
            fill_opacity=0.8,
            fill_color=BLUE,
            stroke_color=YELLOW,
            stroke_width=10
        )
        circle2.shift(RIGHT * 3)
        
        # Add text
        text = Text("Improved stroke rendering", font_size=24)
        text.to_edge(DOWN)
        text.fix_in_frame()
        
        self.add(circle1, circle2, text)
        
        # Test zoom (stroke should maintain size)
        self.wait(1)
        self.play(self.camera.frame.animate.scale(0.5), run_time=2)
        self.wait(1)
        self.play(self.camera.frame.animate.scale(2), run_time=2)
        
        # Test rotation (no z-fighting)
        self.begin_ambient_camera_rotation(rate=0.3)
        self.wait(5)
        self.stop_ambient_camera_rotation()
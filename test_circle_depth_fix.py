from manim import *

class TestCircleDepthFix(ThreeDScene):
    """Compare regular circles (with depth issues) vs Circle3D (fixed depth)"""
    
    def construct(self):
        # Set up camera
        self.set_camera_orientation(phi=45 * DEGREES, theta=-45 * DEGREES)
        
        # Left side: Regular circles (VMobject) - should show depth issues
        text_left = Text3D("Regular Circles\n(Depth Issues)", font_size=20)
        text_left.shift(LEFT * 4 + UP * 3)
        self.add(text_left)
        
        circle1_regular = Circle(radius=1, color=RED, fill_opacity=0.8)
        circle1_regular.shift(LEFT * 4 + LEFT * 0.5 + OUT * 0.5)
        
        circle2_regular = Circle(radius=1, color=GREEN, fill_opacity=0.8)
        circle2_regular.shift(LEFT * 4)
        
        circle3_regular = Circle(radius=1, color=BLUE, fill_opacity=0.8)
        circle3_regular.shift(LEFT * 4 + RIGHT * 0.5 + OUT * -0.5)
        
        self.add(circle1_regular, circle2_regular, circle3_regular)
        
        # Right side: Circle3D (Surface) - should have correct depth
        text_right = Text("Circle3D\n(Fixed Depth)", font_size=20)
        text_right.shift(RIGHT * 4 + UP * 3)
        self.add(text_right)
        
        circle1_3d = Circle3D(radius=1, color=RED, opacity=0.8)
        circle1_3d.shift(RIGHT * 4 + LEFT * 0.5 + OUT * 0.5)
        
        circle2_3d = Circle3D(radius=1, color=GREEN, opacity=0.8)
        circle2_3d.shift(RIGHT * 4)
        
        circle3_3d = Circle3D(radius=1, color=BLUE, opacity=0.8)
        circle3_3d.shift(RIGHT * 4 + RIGHT * 0.5 + OUT * -0.5)
        
        self.add(circle1_3d, circle2_3d, circle3_3d)
        
        # Add a dividing line
        divider = Line(UP * 3, DOWN * 3, color=GREY)
        self.add(divider)
        
        # Slowly rotate camera to show depth behavior
        # Use the frame's animate property
        self.play(
            self.frame.animate.set_theta(-135 * DEGREES),
            run_time=6
        )
        self.play(
            self.frame.animate.set_theta(45 * DEGREES),
            run_time=6
        )
        
        self.wait(2)
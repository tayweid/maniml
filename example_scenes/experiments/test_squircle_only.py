from manim import *

class TestSquircleOnly(ThreeDScene):
    def construct(self):
        # Set up 3D view with better angle
        self.set_camera_orientation(phi=75 * DEGREES, theta=-45 * DEGREES)
        
        # Add axes for reference
        axes = ThreeDAxes()
        self.add(axes)
        
        # Our squircle 3D
        squircle = Squircle3D(side_length=2, height=2, squareness=4, color=GREEN, opacity=0.8)
        
        # Add the squircle
        self.play(FadeIn(squircle))
        
        # Rotate camera to show 3D
        self.begin_ambient_camera_rotation(rate=0.3)
        self.wait(5)
        self.stop_ambient_camera_rotation()
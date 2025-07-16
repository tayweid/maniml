from manim import *

class TestRotate(ThreeDScene):
    def construct(self):
        # Set up camera
        self.set_camera_orientation(phi=75 * DEGREES, theta=30 * DEGREES)
        
        # Create a cube
        cube = Cube(side_length=2, color=BLUE)
        self.play(FadeIn(cube))
        
        # Test rotation around different axes
        self.play(Rotate(cube, angle=PI/2, axis=UP))  # Around Y-axis
        self.wait()
        
        self.play(Rotate(cube, angle=PI/2, axis=RIGHT))  # Around X-axis
        self.wait()
        
        self.play(Rotate(cube, angle=PI/2, axis=OUT))  # Around Z-axis
        self.wait()
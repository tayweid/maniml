from manim import *

class Test3DSimple(ThreeDScene):
    def construct(self):
        # Test 1: Create axes
        axes = ThreeDAxes()
        self.set_camera_orientation(phi=75 * DEGREES, theta=30 * DEGREES)
        self.add(axes)
        self.wait()
        
        # Test 2: Create a cube
        cube = Cube(side_length=2, opacity=0.8, color=BLUE)
        self.add(cube)
        self.wait()
        
        # Test 3: Create a sphere
        sphere = Sphere(radius=1, color=RED)
        sphere.shift(RIGHT * 3)
        self.add(sphere)
        self.wait()
from manim import *

class TestVMobject3D(ThreeDScene):
    def construct(self):
        # Set up camera
        self.set_camera_orientation(phi=45 * DEGREES, theta=-45 * DEGREES)
        
        # Create three overlapping Circle3D objects at different depths
        # Red circle in front (z=1)
        circle_red = Circle3D(radius=1.5, color=RED, opacity=0.8)
        circle_red.shift(LEFT * 1 + UP * 0.5 + OUT * 1)
        
        # Green circle in middle (z=0)
        circle_green = Circle3D(radius=1.5, color=GREEN, opacity=0.8)
        circle_green.shift(ORIGIN)
        
        # Blue circle behind (z=-1)
        circle_blue = Circle3D(radius=1.5, color=BLUE, opacity=0.8)
        circle_blue.shift(RIGHT * 1 + DOWN * 0.5 + OUT * -1)
        
        # Add objects
        self.add(circle_red)
        self.add(circle_green)
        self.add(circle_blue)
        
        # Add labels using Text3D
        self.add(Text3D("Red (front)", color=RED).shift(UP * 3))
        self.add(Text3D("Green (middle)", color=GREEN).shift(UP * 2.5))
        self.add(Text3D("Blue (back)", color=BLUE).shift(UP * 2))
        
        # Rotate slowly to test depth ordering
        # Note: Can't use VGroup with Surface objects, so rotate individually
        self.play(
            Rotate(circle_red, angle=2*PI, axis=UP),
            Rotate(circle_green, angle=2*PI, axis=UP),
            Rotate(circle_blue, angle=2*PI, axis=UP),
            run_time=8
        )
        self.wait()


class CompareApproaches(ThreeDScene):
    def construct(self):
        # Set up camera
        self.set_camera_orientation(phi=30 * DEGREES, theta=-45 * DEGREES)
        
        # Left side: Regular Circle (VMobject)
        circle_regular = Circle(radius=1, color=YELLOW, fill_opacity=0.8)
        circle_regular.shift(LEFT * 3)
        text_regular = Text("Regular Circle").next_to(circle_regular, DOWN)
        
        # Right side: Circle3D (Surface-based)
        circle_3d = Circle3D(radius=1, color=YELLOW, opacity=0.8)
        circle_3d.shift(RIGHT * 3)
        text_3d = Text3D("Circle3D").shift(RIGHT * 3 + DOWN * 2)
        
        # Add a plane behind both for depth testing
        plane = Square(side_length=6, color=BLUE, fill_opacity=0.5)
        plane.shift(OUT * -0.5)
        
        # Add all objects
        self.add(plane)
        self.add(circle_regular, text_regular)
        self.add(circle_3d, text_3d)
        
        # Rotate to show depth behavior
        self.play(
            Rotate(plane, angle=PI/2, axis=UP, run_time=4)
        )
        self.wait()
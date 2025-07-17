from manim import *

class Test3DDepthSimple(ThreeDScene):
    def construct(self):
        # Set up camera from the side
        self.set_camera_orientation(phi=0, theta=-90 * DEGREES)
        
        # Create plane in the middle
        plane = Square(side_length=4, color=BLUE, fill_opacity=0.5)
        
        # Regular Circle on the left (VMobject approach)
        circle_regular = Circle(radius=1, color=RED, fill_opacity=0.8)
        circle_regular.shift(LEFT * 2 + OUT * 0.5)
        label_regular = Text("Regular Circle", font_size=24).next_to(circle_regular, DOWN)
        
        # Circle3D on the right (Surface approach)
        circle_3d = Circle3D(radius=1, color=GREEN, opacity=0.8)
        circle_3d.shift(RIGHT * 2 + OUT * 0.5)
        label_3d = Text3D("Circle3D").next_to(circle_3d, DOWN)
        
        # Add all objects
        self.add(plane)
        self.add(circle_regular, label_regular)
        self.add(circle_3d, label_3d)
        
        # Animate camera to show depth
        self.play(
            self.camera.phi_tracker.animate.set_value(60 * DEGREES),
            self.camera.theta_tracker.animate.set_value(-45 * DEGREES),
            run_time=3
        )
        
        # Move circles through the plane
        self.play(
            circle_regular.animate.shift(IN * 2),
            circle_3d.animate.shift(IN * 2),
            run_time=4
        )
        
        self.wait(2)
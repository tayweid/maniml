from manim import *

class TestSquircle3D(ThreeDScene):
    def construct(self):
        # Set up 3D view with better angle
        self.set_camera_orientation(phi=75 * DEGREES, theta=-45 * DEGREES)
        
        # Add axes for reference
        axes = ThreeDAxes()
        self.add(axes)
        
        # Compare with a regular cube to see the difference
        cube = Cube(side_length=2, color=YELLOW, opacity=0.8)
        cube.shift(LEFT * 3)
        
        # Our squircle 3D
        squircle = Squircle3D(side_length=2, height=2, squareness=4, color=GREEN)
        squircle.shift(RIGHT * 3)
        
        # Add labels
        cube_label = Text("Cube", font_size=24).next_to(cube, DOWN)
        squircle_label = Text("Squircle3D", font_size=24).next_to(squircle, DOWN)
        
        self.play(
            FadeIn(cube),
            FadeIn(squircle),
            Write(cube_label),
            Write(squircle_label)
        )
        
        # Rotate camera to show 3D
        self.begin_ambient_camera_rotation(rate=0.3)
        self.wait(5)
        self.stop_ambient_camera_rotation()
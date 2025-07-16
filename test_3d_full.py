from manim import *

class Test3DFull(ThreeDScene):
    def construct(self):
        # Set up 3D axes
        axes = ThreeDAxes()
        self.set_camera_orientation(phi=75 * DEGREES, theta=30 * DEGREES)
        self.play(Create(axes))
        print("Animation 1: Created axes")
        
        # Create a cube
        cube = Cube(side_length=2, opacity=0.8, color=BLUE)
        self.play(FadeIn(cube))
        print("Animation 2: Added cube")
        
        # Rotate the cube
        self.play(Rotate(cube, angle=PI/2, axis=UP))
        print("Animation 3: Rotated cube")
        
        # Create a sphere
        sphere = Sphere(radius=1, color=RED)
        sphere.shift(RIGHT * 3)
        self.play(Create(sphere))
        print("Animation 4: Created sphere")
        
        # Move camera around
        self.begin_ambient_camera_rotation(rate=0.1)
        self.wait(2)
        self.stop_ambient_camera_rotation()
        print("Animation 5: Camera rotation")
        
        # Transform cube to torus
        torus = Torus(r1=1.5, r2=0.5, color=GREEN)
        self.play(Transform(cube, torus))
        print("Animation 6: Transformed cube to torus")
        
        # Scale everything
        self.play(
            cube.animate.scale(0.5),
            sphere.animate.scale(1.5).shift(LEFT * 2)
        )
        print("Animation 7: Scaled objects")
        
        # Final rotation
        self.play(Rotate(axes, angle=PI/4, axis=RIGHT))
        print("Animation 8: Rotated axes")
        
        self.wait()
        print("Scene complete!")
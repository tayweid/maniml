from manim import *

class Test3DShapes(ThreeDScene):
    def construct(self):
        # Set up 3D view
        self.set_camera_orientation(phi=70 * DEGREES, theta=-45 * DEGREES)
        
        # Create axes for reference
        axes = ThreeDAxes()
        self.add(axes)
        
        # Test various 2D shapes with fill
        square = Square(side_length=2, fill_opacity=0.8, fill_color=BLUE, color=RED, stroke_width=3)
        square.shift(LEFT * 3)
        
        circle = Circle(radius=1, fill_opacity=0.8, fill_color=WHITE, color=RED, stroke_width=10)
        circle.shift(RIGHT * 3)
        
        text = Text3D("3D")
        text.shift(UP * 2)
        
        # Add a 3D object for depth comparison
        cube = Cube(side_length=1, color=YELLOW, opacity=0.5)
        cube.shift(DOWN * 2)
        
        # Add all objects
        self.play(
            FadeIn(square),
            FadeIn(circle),
            FadeIn(text),
            FadeIn(cube)
        )
        
        # Rotate camera to see depth
        self.begin_ambient_camera_rotation(rate=0.1)
        self.wait(5)
        self.stop_ambient_camera_rotation()
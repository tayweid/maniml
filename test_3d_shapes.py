from manim import *

class Test3DShapes(ThreeDScene):
    def construct(self):
        # Set up 3D view
        self.set_camera_orientation(phi=70 * DEGREES, theta=-45 * DEGREES)
        
        # Create axes for reference
        axes = ThreeDAxes()
        self.add(axes)
        
        # Test various 2D shapes with fill
        square = Square(side_length=2, fill_opacity=0.8, fill_color=BLUE, color=RED, stroke_width=1)
        square.shift(LEFT * 3)
        
        circle = Circle(radius=1, fill_opacity=0.8, fill_color=WHITE, color=RED, stroke_width=10)
        circle.shift(RIGHT * 3)
        
        # Add a 3D squircle with rectangular base
        squircle = Squircle3D(width=2.5, height=1.5, depth=1, squareness=4, color=GREEN, shading=(0.1, 0.5, 0.1))
        squircle.shift(UP * 2)
        
        text = Text("Roboto Slab 3D", font_size=48).fix_in_frame()
        text.to_corner(UL)
        subtext = Text("Subtitle", color=GREY, font_size=24, slant=ITALIC).fix_in_frame()
        subtext.to_corner(UL).shift(DOWN/2)
        
        # Add a 3D object for depth comparison
        cube = Cube(side_length=1, color=YELLOW, opacity=0.5)
        cube.shift(DOWN * 2)
        
        # Add all objects
        self.play(
            FadeIn(square),
            FadeIn(circle),
            FadeIn(squircle),
            FadeIn(text),
            FadeIn(subtext),
            FadeIn(cube),
            self.camera.frame.animate.set_phi(0 * DEGREES).set_theta(0 * DEGREES)
        )
        
        # Add a 2D graph fixed to the frame
        # Create a simple coordinate system with lines
        x_axis = Line(LEFT * 2, RIGHT * 2, color=WHITE)
        y_axis = Line(DOWN * 1.5, UP * 1.5, color=WHITE)
        
        # Create axes marks
        x_marks = VGroup(*[
            Line(UP * 0.1, DOWN * 0.1, color=WHITE).shift(RIGHT * i)
            for i in range(-2, 3)
        ])
        y_marks = VGroup(*[
            Line(LEFT * 0.1, RIGHT * 0.1, color=WHITE).shift(UP * i * 0.75)
            for i in range(-2, 3)
        ])
        
        # Create a sine curve manually
        x_vals = np.linspace(-2, 2, 100)
        y_vals = np.sin(x_vals * PI / 2)  # Adjust frequency for display
        points = [np.array([x, y * 0.75, 0]) for x, y in zip(x_vals, y_vals)]
        func = VMobject(color=YELLOW)
        func.set_points_smoothly(points)
        
        # Add a 2D rectangular squircle
        rect_squircle = Squircle(width=10, height=0.5, squareness=4, fill_opacity=0.8, fill_color=ORANGE)
        rect_squircle.shift(DOWN * 0.8)
        
        # Group the graph components
        graph_group = VGroup(x_axis, y_axis, x_marks, y_marks, func, rect_squircle)
        
        # Position it in the bottom-right corner
        graph_group.scale(0.4)
        graph_group.to_corner(DR)
        
        # Fix the graph to the frame so it doesn't move with camera
        graph_group.fix_in_frame()
        
        # Add label
        label = Text("sin(x)", font_size=16)
        label.next_to(graph_group, UP, buff=0.1)
        label.fix_in_frame()
        
        # Fade in the graph
        self.play(FadeIn(graph_group), FadeIn(label))

        self.play(graph_group.animate.scale(2))

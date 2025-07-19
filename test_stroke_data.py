from manim import *

class TestStrokeData(ThreeDScene):
    def construct(self):
        # Set up 3D view
        self.set_camera_orientation(phi=70 * DEGREES, theta=-45 * DEGREES)
        
        # Create shapes
        circle = Circle(radius=1, fill_opacity=0.8, fill_color=RED, stroke_color=WHITE, stroke_width=10)
        square = Square(side_length=2, fill_opacity=0.8, fill_color=BLUE, stroke_color=YELLOW, stroke_width=10)
        
        circle.shift(LEFT * 3)
        square.shift(RIGHT * 3)
        
        # Check stroke data
        print(f"Circle stroke color: {circle.get_stroke_color()}")
        print(f"Circle stroke width: {circle.get_stroke_width()}")
        print(f"Circle stroke opacity: {circle.get_stroke_opacity()}")
        print(f"Circle has points: {circle.has_points()}")
        print(f"Circle z_index: {circle.z_index}")
        
        print(f"\nSquare stroke color: {square.get_stroke_color()}")
        print(f"Square stroke width: {square.get_stroke_width()}")
        print(f"Square stroke opacity: {square.get_stroke_opacity()}")
        print(f"Square has points: {square.has_points()}")
        print(f"Square z_index: {square.z_index}")
        
        self.play(FadeIn(circle), FadeIn(square))
        self.wait(2)
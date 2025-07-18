from manim import *

class TestRectangle3D(ThreeDScene):
    def construct(self):
        # Set up 3D view
        self.set_camera_orientation(phi=70 * DEGREES, theta=-45 * DEGREES)
        
        # Create axes for reference
        axes = ThreeDAxes()
        self.add(axes)
        
        # Test Rectangle3D with different dimensions
        rect1 = Rectangle3D(width=4, height=2, color=BLUE, opacity=0.7)
        rect1.shift(LEFT * 3)
        
        rect2 = Rectangle3D(width=2, height=3, color=RED, opacity=0.7)
        rect2.shift(RIGHT * 3)
        
        rect3 = Rectangle3D(width=1, height=1, color=GREEN, opacity=0.7)
        rect3.shift(UP * 2)
        
        # Add labels
        label1 = Text("4x2", font_size=24).move_to(rect1.get_center() + OUT * 0.5)
        label2 = Text("2x3", font_size=24).move_to(rect2.get_center() + OUT * 0.5)
        label3 = Text("1x1", font_size=24).move_to(rect3.get_center() + OUT * 0.5)
        
        # Animate creation
        self.play(
            Create(rect1),
            Create(rect2),
            Create(rect3),
            Write(label1),
            Write(label2),
            Write(label3)
        )
        
        # Rotate to show they're flat
        self.begin_ambient_camera_rotation(rate=0.2)
        self.wait(5)
        self.stop_ambient_camera_rotation()
        
        # Test depth ordering with overlapping rectangles
        self.play(
            FadeOut(label1),
            FadeOut(label2),
            FadeOut(label3)
        )
        
        # Create overlapping rectangles
        back_rect = Rectangle3D(width=5, height=3, color=PURPLE, opacity=0.8)
        back_rect.shift(IN * 1)
        
        front_rect = Rectangle3D(width=3, height=2, color=YELLOW, opacity=0.8)
        front_rect.shift(OUT * 1)
        
        self.play(
            Create(back_rect),
            Create(front_rect)
        )
        
        self.wait(2)


class CompareSquareVsRectangle(ThreeDScene):
    def construct(self):
        self.set_camera_orientation(phi=70 * DEGREES, theta=-45 * DEGREES)
        
        # Compare Square3D stretched vs Rectangle3D
        square = Square3D(side_length=2, color=BLUE, opacity=0.7)
        square.stretch(2, 0)  # Make it 4x2
        square.shift(LEFT * 3)
        
        rect = Rectangle3D(width=4, height=2, color=RED, opacity=0.7)
        rect.shift(RIGHT * 3)
        
        label1 = Text("Square3D stretched", font_size=20).shift(LEFT * 3 + DOWN * 2)
        label2 = Text("Rectangle3D", font_size=20).shift(RIGHT * 3 + DOWN * 2)
        
        self.add_fixed_in_frame_mobjects(label1, label2)
        self.play(Create(square), Create(rect))
        
        # Show they're identical in geometry
        self.begin_ambient_camera_rotation(rate=0.1)
        self.wait(5)
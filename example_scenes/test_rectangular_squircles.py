from manim import *

class TestRectangularSquircles(ThreeDScene):
    def construct(self):
        # Set up 3D view
        self.set_camera_orientation(phi=70 * DEGREES, theta=-45 * DEGREES)
        
        # Create axes for reference
        axes = ThreeDAxes()
        self.add(axes)
        
        # Create various rectangular squircles (2D)
        # Square for comparison
        square_2d = Squircle(side_length=2, squareness=10, fill_opacity=0.8, fill_color=RED)
        square_2d.shift(LEFT * 4 + UP * 2)
        
        # Wide rectangle
        wide_rect = Squircle(width=3, height=1.5, squareness=4, fill_opacity=0.8, fill_color=BLUE)
        wide_rect.shift(UP * 2)
        
        # Tall rectangle
        tall_rect = Squircle(width=1.5, height=3, squareness=4, fill_opacity=0.8, fill_color=GREEN)
        tall_rect.shift(RIGHT * 4 + UP * 2)
        
        # Labels
        square_label = Text("Square\n2x2", font_size=24).fix_in_frame()
        square_label.next_to(square_2d, DOWN, buff=0.5)
        
        wide_label = Text("Wide\n3x1.5", font_size=24).fix_in_frame()
        wide_label.next_to(wide_rect, DOWN, buff=0.5)
        
        tall_label = Text("Tall\n1.5x3", font_size=24).fix_in_frame()
        tall_label.next_to(tall_rect, DOWN, buff=0.5)
        
        # Create 3D rectangular squircles
        # Square base (backwards compatibility test)
        square_3d = Squircle3D(side_length=2, depth=1.5, squareness=4, color=RED, opacity=0.8)
        square_3d.shift(LEFT * 4 + DOWN * 2)
        
        # Wide base
        wide_3d = Squircle3D(width=3, height=1.5, depth=2, squareness=4, color=BLUE, opacity=0.8)
        wide_3d.shift(DOWN * 2)
        
        # Tall base
        tall_3d = Squircle3D(width=1.5, height=3, depth=1, squareness=4, color=GREEN, opacity=0.8)
        tall_3d.shift(RIGHT * 4 + DOWN * 2)
        
        # Add all 2D objects
        self.play(
            FadeIn(square_2d),
            FadeIn(wide_rect),
            FadeIn(tall_rect),
            FadeIn(square_label),
            FadeIn(wide_label),
            FadeIn(tall_label),
        )
        
        # Add 3D objects
        self.play(
            FadeIn(square_3d),
            FadeIn(wide_3d),
            FadeIn(tall_3d),
        )
        
        # Rotate camera to show 3D
        self.begin_ambient_camera_rotation(rate=0.2)
        self.wait(8)
        self.stop_ambient_camera_rotation()
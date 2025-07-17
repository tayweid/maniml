from manim import *

class TestTextDetail(ThreeDScene):
    def construct(self):
        # Set up camera
        self.set_camera_orientation(phi=30 * DEGREES, theta=-45 * DEGREES)
        
        # Create white circles as backgrounds
        bg_regular = Circle(radius=2, color=BLUE, fill_opacity=1)
        bg_regular.shift(LEFT * 3)
        
        bg_3d = Circle(radius=2, color=BLUE, fill_opacity=1)
        bg_3d.shift(RIGHT * 3)
        
        # Add backgrounds first
        self.add(bg_regular, bg_3d)
        
        # Regular Text (VMobject) on the left
        text_regular = Text("Hello", font_size=72, color=BLACK)
        text_regular.shift(LEFT * 3 + OUT * 0.1)  # Slightly in front
        
        # Text3D (Surface) on the right
        text_3d = Text3D("Hello", color=BLACK, opacity=1)
        text_3d.shift(RIGHT * 3 + OUT * 0.1)  # Slightly in front
        
        # Add the texts
        self.add(text_regular, text_3d)
        
        # Add labels
        label_regular = Text("Regular Text", font_size=24, color=BLUE).shift(LEFT * 3 + DOWN * 2.5)
        label_3d = Text("Text3D", font_size=24, color=BLUE).shift(RIGHT * 3 + DOWN * 2.5)
        self.add(label_regular, label_3d)
        
        # Wait a moment
        self.wait(2)
        
        # Zoom in to see detail
        self.play(
            self.frame.animate.scale(0.5).shift(LEFT * 1.5),
            run_time=3
        )
        self.wait(2)
        
        # Pan to Text3D
        self.play(
            self.frame.animate.shift(RIGHT * 3),
            run_time=3
        )
        self.wait(2)
        
        # Zoom back out
        self.play(
            self.frame.animate.scale(2).shift(LEFT * 1.5),
            run_time=3
        )
        
        # Rotate to see 3D nature
        self.play(
            self.frame.animate.set_phi(60 * DEGREES),
            run_time=3
        )
        
        self.wait(2)
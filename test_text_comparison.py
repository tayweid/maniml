from manim import *

class TestTextComparison(ThreeDScene):
    def construct(self):
        # Set up camera
        self.set_camera_orientation(phi=45 * DEGREES, theta=-45 * DEGREES)
        
        # Create a semi-transparent plane in the middle
        plane = Square(side_length=8, color=BLUE, fill_opacity=0.5)
        self.add(plane)
        
        # Regular Text (VMobject) on the left
        text_regular = Text("Regular Text", font_size=48, color=YELLOW)
        text_regular.shift(LEFT * 3 + OUT * 2)
        
        # Text3D (Surface) on the right
        text_3d = Text3D("Text3D", color=YELLOW, opacity=0.9)
        text_3d.shift(RIGHT * 3 + OUT * 2)
        
        # Add labels
        label_regular = Text("VMobject", font_size=20, color=WHITE).shift(LEFT * 3 + DOWN * 3)
        label_3d = Text("Triangulated", color=WHITE).shift(RIGHT * 3 + DOWN * 3)
        
        self.add(text_regular, text_3d)
        self.add(label_regular, label_3d)
        
        # Move both texts through the plane
        self.play(
            text_regular.animate.shift(IN * 4),
            text_3d.animate.shift(IN * 3),
            run_time=4
        )
                
        # Move back
        self.play(
            text_regular.animate.shift(OUT * 4),
            text_3d.animate.shift(OUT * 4),
            run_time=4
        )
                
        # Rotate camera to see from the side
        self.play(
            self.frame.animate.set_theta(-90 * DEGREES),
            run_time=3
        )
        
        # Move through again from side view
        self.play(
            text_regular.animate.shift(IN * 4),
            text_3d.animate.shift(IN * 4),
            run_time=4
        )
from manim import *

class TestTextComparison(ThreeDScene):
    def construct(self):
        # Set up camerad
        self.set_camera_orientation(phi=45 * DEGREES, theta=-45 * DEGREES)
        
        # Create a semi-transparent plane in the middle
        plane = Prism(width=2, height=2, depth=0.1, color=BLUE, opacity=0.8)
        self.add(plane)
        
        # Regular Text (VMobject) on the left
        text_regular = Text3D("Text3D\nSurface", color=YELLOW, font="Times New Roman", slant=ITALIC, weight=300)
        text_regular.shift(LEFT + OUT * 2)
        
        # Text3D (Surface) on the rightd
        text_3d = Text3D("Text3D\nSurface", color=YELLOW, font="Times New Roman", slant=ITALIC, weight=200)
        text_3d.shift(RIGHT + OUT * 2)
        
        self.add(text_regular, text_3d)
        
        # Move both texts through the plane
        self.play(
            text_regular.animate.shift(IN),
            text_3d.animate.shift(IN),
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
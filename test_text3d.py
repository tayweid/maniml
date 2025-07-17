from manim import *

class TestText3D(ThreeDScene):
    def construct(self):
        # Set up camera
        self.set_camera_orientation(phi=60 * DEGREES, theta=-45 * DEGREES)
        
        # Create a plane in the middle
        plane = Square(side_length=6, color=BLUE, fill_opacity=0.5)
        
        # Regular Text (VMobject) on the left
        text_regular = Text("Regular\nText", font_size=36, color=YELLOW)
        text_regular.shift(LEFT * 3 + OUT * 0.5)
        
        # Text3D (Surface) on the right
        text_3d = Text3D("Text3D\nSurface", color=YELLOW, opacity=0.8)
        text_3d.shift(RIGHT * 3 + OUT * 0.5)
        
        # Add labels
        label_regular = Text("VMobject Text", font_size=20).shift(LEFT * 3 + DOWN * 2.5)
        label_3d = Text("Triangulated Text3D", font_size=20).shift(RIGHT * 3 + DOWN * 2.5)
        
        # Add all objects
        self.add(plane)
        self.add(text_regular)
        self.add(text_3d)
        self.add(label_regular, label_3d)
        
        # Animate to show depth - move texts through the plane
        self.play(
            text_regular.animate.shift(IN * 1.5),
            text_3d.animate.shift(IN * 1.5),
            run_time=3
        )
        
        # Rotate camera to see from different angles
        self.play(
            self.frame.animate.set_theta(-90 * DEGREES),
            run_time=3
        )
        
        self.wait(1)
        
        # Rotate back
        self.play(
            self.frame.animate.set_theta(-45 * DEGREES),
            run_time=3
        )
        
        self.wait(2)


class TestText3DDepth(ThreeDScene):
    """Test multiple overlapping Text3D objects"""
    
    def construct(self):
        # Set up camera
        self.set_camera_orientation(phi=45 * DEGREES, theta=-45 * DEGREES)
        
        # Create three Text3D objects at different depths
        text_front = Text3D("Front", color=RED, opacity=0.8)
        text_front.shift(LEFT * 1 + UP * 0.5 + OUT * 1)
        
        text_middle = Text3D("Middle", color=GREEN, opacity=0.8)
        text_middle.shift(ORIGIN)
        
        text_back = Text3D("Back", color=BLUE, opacity=0.8)
        text_back.shift(RIGHT * 1 + DOWN * 0.5 + OUT * -1)
        
        # Add all text objects
        self.add(text_front, text_middle, text_back)
        
        # Rotate slowly to show depth ordering
        self.play(
            Rotate(text_front, angle=TAU, axis=UP),
            Rotate(text_middle, angle=TAU, axis=UP),
            Rotate(text_back, angle=TAU, axis=UP),
            run_time=8
        )
        
        self.wait(2)


class TestText3DQuality(ThreeDScene):
    """Compare text quality at different resolutions"""
    
    def construct(self):
        # Set up camera
        self.set_camera_orientation(phi=30 * DEGREES, theta=-45 * DEGREES)
        
        # Different resolution Text3D objects
        text_low = Text3D("Low Res", resolution=20, color=RED, opacity=0.8)
        text_low.shift(LEFT * 4)
        
        text_med = Text3D("Med Res", resolution=50, color=GREEN, opacity=0.8)
        text_med.shift(ORIGIN)
        
        text_high = Text3D("High Res", resolution=100, color=BLUE, opacity=0.8)
        text_high.shift(RIGHT * 4)
        
        # Add labels
        label_low = Text("res=20", font_size=16).next_to(text_low, DOWN)
        label_med = Text("res=50", font_size=16).next_to(text_med, DOWN)
        label_high = Text("res=100", font_size=16).next_to(text_high, DOWN)
        
        # Add all objects
        self.add(text_low, text_med, text_high)
        self.add(label_low, label_med, label_high)
        
        # Zoom in to see quality differences
        self.play(
            self.frame.animate.scale(0.5),
            run_time=3
        )
        
        self.wait(3)
        
        # Zoom back out
        self.play(
            self.frame.animate.scale(2),
            run_time=3
        )
        
        self.wait(2)
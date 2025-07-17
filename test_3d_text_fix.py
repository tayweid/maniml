from manim import *

class Test3DTextFix(ThreeDScene):
    def construct(self):
        self.set_camera_orientation(phi=70 * DEGREES, theta=-45 * DEGREES)
        
        # Create grey plane
        plane = Square3D(side_length=4, color=GREY_D)
        self.add(plane)
        
        # Test different text methods
        
        # Method 1: Fixed in frame (recommended)
        text1 = Text("Fixed in Frame", font_size=24, color=WHITE)
        text1.shift(UP * 1.5)
        text1.fix_in_frame()
        
        # Method 2: With stroke
        text2 = Text("With Stroke", font_size=24, color=WHITE,
                    stroke_width=3, stroke_color=BLACK)
        text2.shift(UP * 0.5)
        text2.fix_in_frame()
        
        # Method 3: With background
        bg = Rectangle(width=2.5, height=0.5, color=BLACK, fill_opacity=0.8)
        bg.shift(DOWN * 0.5)
        bg.fix_in_frame()
        
        text3 = Text("With Background", font_size=24, color=WHITE)
        text3.move_to(bg)
        text3.fix_in_frame()
        
        # Add all text
        self.play(Write(text1), Write(text2), FadeIn(bg), Write(text3))
        
        # Rotate to see the effect
        self.begin_ambient_camera_rotation(rate=0.1)
        self.wait(5)
        self.stop_ambient_camera_rotation()
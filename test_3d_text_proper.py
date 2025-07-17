from manim import *

class Test3DTextProper(ThreeDScene):
    def construct(self):
        self.set_camera_orientation(phi=70 * DEGREES, theta=-45 * DEGREES)
        
        # Create grey plane
        plane = Square3D(side_length=5, color=GREY_D, opacity=0.9)
        self.add(plane)
        
        # Test 1: Default text (problematic)
        text1 = Text("Default (Bad)", font_size=20, color=WHITE)
        text1.rotate(PI/2, RIGHT)
        text1.shift(LEFT * 2 + OUT * 0.1)
        
        # Test 2: With depth test and no anti-aliasing (good)
        text2 = Text("Depth Test (Good)", font_size=20, color=WHITE,
                    stroke_width=3, stroke_color=BLACK)
        text2.rotate(PI/2, RIGHT)
        text2.shift(OUT * 0.1)
        text2.apply_depth_test(anti_alias_width=0)  # KEY FIX
        
        # Test 3: With z_index and better colors (best)
        text3 = Text("Optimal", font_size=20, color=YELLOW,
                    stroke_width=4, stroke_color=BLACK)
        text3.rotate(PI/2, RIGHT)
        text3.shift(RIGHT * 2 + OUT * 0.15)
        text3.apply_depth_test(anti_alias_width=0)
        text3.z_index = 1
        
        # Add all text
        self.play(Write(text1), Write(text2), Write(text3))
        
        # Add labels below to show which is which
        label1 = Text("BAD", font_size=14, color=RED)
        label1.shift(LEFT * 2 + DOWN * 1.5)
        label1.fix_in_frame()  # Labels use fix_in_frame for clarity
        
        label2 = Text("GOOD", font_size=14, color=GREEN)
        label2.shift(DOWN * 1.5)
        label2.fix_in_frame()
        
        label3 = Text("BEST", font_size=14, color=GREEN)
        label3.shift(RIGHT * 2 + DOWN * 1.5)
        label3.fix_in_frame()
        
        self.play(Write(label1), Write(label2), Write(label3))
        
        # Rotate to see the difference
        self.begin_ambient_camera_rotation(rate=0.1)
        self.wait(8)
        self.stop_ambient_camera_rotation()
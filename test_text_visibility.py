from manim import *

class TestTextVisibility(ThreeDScene):
    def construct(self):
        self.set_camera_orientation(phi=70 * DEGREES, theta=-45 * DEGREES)
        
        # Grey plane
        plane = Square3D(side_length=5, color=GREY_D, opacity=0.9)
        self.add(plane)
        
        # Test 1: Default behavior (invisible)
        text1 = Text("Invisible", font_size=20, color=WHITE,
                    stroke_width=3, stroke_color=RED)
        text1.rotate(PI/2, RIGHT)
        text1.shift(LEFT * 2 + OUT * 0.1)
        self.add(text1)  # This makes it invisible
        
        # Test 2: With deactivate_depth_test (visible)
        text2 = Text("Visible!", font_size=20, color=WHITE,
                    stroke_width=3, stroke_color=BLACK)
        text2.rotate(PI/2, RIGHT)
        text2.shift(OUT * 0.1)
        self.add(text2)
        text2.deactivate_depth_test()  # This fixes it
        
        # Test 3: With set_depth_test=False (visible)
        text3 = Text("Also Visible!", font_size=20, color=WHITE,
                    stroke_width=3, stroke_color=BLACK)
        text3.rotate(PI/2, RIGHT)
        text3.shift(RIGHT * 2 + OUT * 0.1)
        self.add(text3, set_depth_test=False)  # This prevents the issue
        
        # Wait and rotate
        self.wait(2)
        self.begin_ambient_camera_rotation(rate=0.1)
        self.wait(5)
        self.stop_ambient_camera_rotation()
from manim import *

class TestDepthFix(ThreeDScene):
    """Test if our fix for depth testing works."""
    
    def construct(self):
        # Set up 3D view
        self.set_camera_orientation(phi=70 * DEGREES, theta=-45 * DEGREES)
        
        # Create a semi-transparent plane
        plane = Square3D(side_length=5, color=GREY_D, opacity=0.8)
        plane.shift(IN * 0.5)
        
        # Create text that should appear in front
        text = Text("Front Text", color=WHITE, font_size=40)
        text.shift(OUT * 1)  # In front of plane
        
        # Create a circle that should be behind
        circle = Circle(radius=1, fill_opacity=1, fill_color=BLUE)
        circle.shift(IN * 1.5)  # Behind plane
        
        # Add everything
        self.play(Create(plane), Create(text), Create(circle))
        
        # Also test with explicit depth test
        text2 = Text("Manual Depth", color=GREEN, font_size=30)
        text2.shift(LEFT * 3 + OUT * 0.5)
        text2.apply_depth_test()  # Manually apply
        self.play(Create(text2))
        
        # Animate rotation to see depth issues
        self.begin_ambient_camera_rotation(rate=0.1)
        self.wait(8)
        self.stop_ambient_camera_rotation()


class CompareDepthTest(ThreeDScene):
    """Compare objects with and without depth test."""
    
    def construct(self):
        self.set_camera_orientation(phi=70 * DEGREES, theta=-45 * DEGREES)
        
        # Create plane
        plane = Square3D(side_length=6, color=GREY_D, opacity=0.7)
        self.add(plane)
        
        # Left side - normal Text (should have depth issues)
        text_normal = Text("Normal", color=RED)
        text_normal.shift(LEFT * 2 + OUT * 0.5)
        self.remove(text_normal)  # Remove to re-add without depth test
        Scene.add(self, text_normal)  # Use Scene.add to bypass ThreeDScene
        
        # Right side - Text with depth test (should work properly)
        text_depth = Text("Depth Test", color=GREEN) 
        text_depth.shift(RIGHT * 2 + OUT * 0.5)
        self.add(text_depth)  # This will apply depth test
        
        # Labels
        self.add_fixed_in_frame_mobjects(
            Text("Without Depth Test", font_size=20, color=RED).shift(LEFT * 2 + UP * 3),
            Text("With Depth Test", font_size=20, color=GREEN).shift(RIGHT * 2 + UP * 3)
        )
        
        self.wait(5)
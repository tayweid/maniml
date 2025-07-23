from manim import *

class TestStrokeZFighting(ThreeDScene):
    def construct(self):
        # Set up 3D view
        self.set_camera_orientation(phi=70 * DEGREES, theta=-45 * DEGREES)
        
        # Test different stroke configurations
        
        # Default settings
        circle1 = Circle(
            radius=1.5, 
            fill_opacity=0.8, 
            fill_color=RED, 
            stroke_color=WHITE,
            stroke_width=10
        )
        circle1.shift(LEFT * 4)
        
        # Try stroke not behind (stroke on top)
        circle2 = Circle(
            radius=1.5, 
            fill_opacity=0.8, 
            fill_color=BLUE, 
            stroke_color=YELLOW,
            stroke_width=10,
            stroke_behind=False  # Ensure stroke is on top
        )
        
        # Try with scale_stroke_with_zoom
        circle3 = Circle(
            radius=1.5, 
            fill_opacity=0.8, 
            fill_color=GREEN, 
            stroke_color=WHITE,
            stroke_width=10,
            scale_stroke_with_zoom=True
        )
        circle3.shift(RIGHT * 4)
        
        self.add(circle1, circle2, circle3)
        
        # Add labels
        label1 = Text("Default", font_size=20).next_to(circle1, DOWN)
        label2 = Text("stroke_behind=False", font_size=20).next_to(circle2, DOWN)
        label3 = Text("scale_stroke_with_zoom=True", font_size=20).next_to(circle3, DOWN)
        
        for label in [label1, label2, label3]:
            label.fix_in_frame()
        
        self.add(label1, label2, label3)
        self.wait(2)
from manim import *

class TestText3DDebug(ThreeDScene):
    def construct(self):
        # Set up camera
        self.set_camera_orientation(phi=45 * DEGREES, theta=-45 * DEGREES)
        
        # Try to create a simple Text3D
        print("\n=== Creating Text3D ===")
        text_3d = Text3D("Hello", color=BLUE, opacity=0.9)
        print(f"Text3D created: {text_3d}")
        print(f"Number of points: {len(text_3d.get_points())}")
        print(f"Has triangle indices: {hasattr(text_3d, 'triangle_indices')}")
        if hasattr(text_3d, 'triangle_indices'):
            print(f"Number of triangles: {len(text_3d.triangle_indices) // 3}")
        
        # Add it to scene
        self.add(text_3d)
        
        # Also add a regular Circle3D to compare
        circle_3d = Circle3D(radius=1, color=GREEN, opacity=0.8)
        circle_3d.shift(RIGHT * 3)
        self.add(circle_3d)
        
        # Add regular text for comparison
        text_regular = Text("Regular", color=BLUE)
        text_regular.shift(LEFT * 3)
        self.add(text_regular)
        
        # Add labels
        self.add(Text("Text3D", font_size=20).shift(DOWN * 2))
        self.add(Text("Circle3D", font_size=20).shift(RIGHT * 3 + DOWN * 2))
        self.add(Text("Regular Text", font_size=20).shift(LEFT * 3 + DOWN * 2))
        
        # Rotate to see better
        self.play(
            self.frame.animate.set_theta(-60 * DEGREES),
            run_time=3
        )
        
        self.wait(2)
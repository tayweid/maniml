from manim import *
import numpy as np

class DepthTestDiagnostic(ThreeDScene):
    """Diagnostic test to understand depth testing issues with 2D objects in 3D scenes."""
    
    def construct(self):
        # Set up 3D view
        self.set_camera_orientation(phi=70 * DEGREES, theta=-45 * DEGREES)
        
        # Create a semi-transparent plane as reference
        plane = Square3D(side_length=6, color=GREY_D, opacity=0.7)
        plane.shift(IN * 0.5)  # Slightly behind origin
        
        # Test 1: Text at various depths
        text_behind = Text("Behind", color=RED)
        text_behind.shift(LEFT * 3 + IN * 1)  # Behind the plane
        
        text_front = Text("Front", color=GREEN)
        text_front.shift(LEFT * 3 + OUT * 1)  # In front of plane
        
        text_intersect = Text("Intersect", color=BLUE)
        text_intersect.shift(LEFT * 3 + IN * 0.5)  # Same depth as plane
        
        # Test 2: Circle at various depths
        circle_behind = Circle(color=RED)
        circle_behind.shift(IN * 1)  # Behind the plane
        
        circle_front = Circle(color=GREEN)
        circle_front.shift(OUT * 1)  # In front of plane
        
        circle_intersect = Circle(color=BLUE)
        circle_intersect.shift(IN * 0.5)  # Same depth as plane
        
        # Test 3: VMobject with explicit depth test
        square_test = Square(color=YELLOW)
        square_test.shift(RIGHT * 3 + IN * 0.5)
        # Manually apply depth test
        square_test.apply_depth_test()
        
        # Debug info
        print("\n=== DEPTH TEST DIAGNOSTIC ===")
        
        # Add objects and check their depth_test status
        objects = [
            ("Plane", plane),
            ("Text Behind", text_behind),
            ("Text Front", text_front),
            ("Text Intersect", text_intersect),
            ("Circle Behind", circle_behind),
            ("Circle Front", circle_front),
            ("Circle Intersect", circle_intersect),
            ("Square (manual depth)", square_test)
        ]
        
        for name, obj in objects:
            self.add(obj)
            # Check depth_test attribute
            depth_test = getattr(obj, 'depth_test', None)
            print(f"{name}: depth_test = {depth_test}")
            
            # Check if shader_wrapper exists
            if hasattr(obj, 'shader_wrapper') and obj.shader_wrapper:
                print(f"  - shader_wrapper.depth_test = {obj.shader_wrapper.depth_test}")
        
        # Add labels
        self.add_fixed_in_frame_mobjects(
            Text("Red = Behind, Green = Front, Blue = Intersect", font_size=20).to_edge(UP)
        )
        
        # Test rotation to see depth issues
        self.begin_ambient_camera_rotation(rate=0.1)
        self.wait(10)
        self.stop_ambient_camera_rotation()


class ManualDepthTestFix(ThreeDScene):
    """Test if manually applying depth test fixes the issue."""
    
    def construct(self):
        self.set_camera_orientation(phi=70 * DEGREES, theta=-45 * DEGREES)
        
        # Create plane
        plane = Square3D(side_length=5, color=GREY_D, opacity=0.8)
        self.add(plane)
        
        # Test with manual depth test application
        text = Text("Manual Depth Test", color=WHITE)
        text.shift(OUT * 0.5)
        
        # Print before
        print(f"\nBefore apply_depth_test: depth_test = {getattr(text, 'depth_test', None)}")
        
        # Apply depth test manually
        text.apply_depth_test()
        
        # Print after
        print(f"After apply_depth_test: depth_test = {getattr(text, 'depth_test', None)}")
        
        self.add(text)
        
        # Also test with a circle
        circle = Circle(color=YELLOW)
        circle.shift(RIGHT * 2 + IN * 0.3)
        circle.apply_depth_test()
        self.add(circle)
        
        self.wait(5)


class DebugThreeDSceneAdd(ThreeDScene):
    """Override add() to see what's happening."""
    
    def add(self, *mobjects, **kwargs):
        print(f"\n=== ThreeDScene.add() called ===")
        print(f"always_depth_test = {self.always_depth_test}")
        
        for mob in mobjects:
            print(f"\nAdding {type(mob).__name__}:")
            print(f"  - is_fixed_in_frame: {mob.is_fixed_in_frame()}")
            print(f"  - depth_test before: {getattr(mob, 'depth_test', None)}")
            
        # Call parent add
        super().add(*mobjects, **kwargs)
        
        # Check after
        for mob in mobjects:
            print(f"\n{type(mob).__name__} after add:")
            print(f"  - depth_test after: {getattr(mob, 'depth_test', None)}")
    
    def construct(self):
        self.set_camera_orientation(phi=70 * DEGREES, theta=-45 * DEGREES)
        
        plane = Square3D(side_length=4, color=GREY_D, opacity=0.8)
        text = Text("Debug Test", color=WHITE).shift(OUT * 0.5)
        
        self.add(plane)
        self.add(text)
        
        self.wait(3)


if __name__ == "__main__":
    # Run the diagnostic tests
    from manim import config
    config.quality = "l"  # Low quality for faster testing
    
    print("\n" + "="*50)
    print("RUNNING DEPTH TEST DIAGNOSTICS")
    print("="*50)
    
    # You can run these individually with:
    # maniml test_depth_diagnostic.py DepthTestDiagnostic
    # maniml test_depth_diagnostic.py ManualDepthTestFix
    # maniml test_depth_diagnostic.py DebugThreeDSceneAdd
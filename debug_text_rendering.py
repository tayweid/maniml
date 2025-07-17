from manim import *

class DebugTextRendering(ThreeDScene):
    """Debug text rendering to understand the issue."""
    
    def construct(self):
        self.set_camera_orientation(phi=70 * DEGREES, theta=-45 * DEGREES)
        
        # Create simple objects for comparison
        plane = Square3D(side_length=4, color=GREY_D, opacity=0.8)
        circle = Circle(color=GREEN, radius=0.5)
        circle.shift(LEFT * 2 + OUT * 1)
        text = Text("TEST", color=WHITE, font_size=40)
        text.shift(RIGHT * 2 + OUT * 1)
        
        # Debug output BEFORE adding
        print("\n=== DEBUGGING TEXT RENDERING ===")
        
        # Add everything
        self.play(Create(plane))
        self.add(circle, text)
        print(f"Circle family size: {len(circle.get_family())}")
        print(f"Text family size: {len(text.get_family())}")
        
        # Check shader wrappers
        print("\n--- Circle Shader Wrappers ---")
        for i, mob in enumerate(circle.get_family()):
            if hasattr(mob, 'shader_wrapper') and mob.shader_wrapper is not None:
                print(f"Circle family {i}: has shader_wrapper, depth_test={mob.shader_wrapper.depth_test}")
            else:
                print(f"Circle family {i}: NO shader_wrapper")
                
        print("\n--- Text Shader Wrappers ---")
        for i, mob in enumerate(text.get_family()):
            if hasattr(mob, 'shader_wrapper') and mob.shader_wrapper is not None:
                print(f"Text family {i}: has shader_wrapper, depth_test={mob.shader_wrapper.depth_test}")
            else:
                print(f"Text family {i}: NO shader_wrapper")
                
        # Check if text has points
        print("\n--- Text Points ---")
        for i, mob in enumerate(text.get_family()):
            has_points = hasattr(mob, 'points') and len(mob.points) > 0
            print(f"Text family {i}: has_points={has_points}")
            
        # Force shader wrapper creation
        print("\n--- Forcing shader wrapper refresh ---")
        text.refresh_shader_wrapper_id()
        
        # Check again
        print("\n--- After refresh ---")
        for i, mob in enumerate(text.get_family()):
            if hasattr(mob, 'shader_wrapper') and mob.shader_wrapper is not None:
                print(f"Text family {i}: shader_wrapper.depth_test={mob.shader_wrapper.depth_test}")
        
        # Rotate to see depth issues
        self.begin_ambient_camera_rotation(rate=0.15)
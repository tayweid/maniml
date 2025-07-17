from manim import *

class DebugTextAdd(ThreeDScene):
    """Debug the add process for text."""
    
    def construct(self):
        self.set_camera_orientation(phi=70 * DEGREES, theta=-45 * DEGREES)
        
        # Plane
        plane = Square3D(side_length=4, color=GREY_D, opacity=0.8)
        self.play(Create(plane))
        
        # Create text
        text = Text("TEST", color=WHITE, font_size=40)
        text.shift(OUT * 1)
        
        # Print before
        print("\n=== BEFORE ADD ===")
        print(f"Text depth_test: {text.depth_test}")
        for i, sub in enumerate(text.get_family()):
            print(f"  Family {i}: {type(sub).__name__}, depth_test={sub.depth_test}")
        
        # Manually call apply_depth_test to see what happens
        print("\n=== CALLING apply_depth_test() ===")
        text.apply_depth_test()
        
        # Print after apply_depth_test
        print("\n=== AFTER apply_depth_test() ===")
        print(f"Text depth_test: {text.depth_test}")
        for i, sub in enumerate(text.get_family()):
            print(f"  Family {i}: {type(sub).__name__}, depth_test={sub.depth_test}")
        
        # Now add to scene
        print("\n=== ADDING TO SCENE ===")
        self.add(text)
        
        # Print final state
        print("\n=== FINAL STATE ===")
        print(f"Text depth_test: {text.depth_test}")
        for i, sub in enumerate(text.get_family()):
            print(f"  Family {i}: {type(sub).__name__}, depth_test={sub.depth_test}")
        
        # Check shader wrappers
        print("\n=== SHADER WRAPPERS ===")
        for i, sub in enumerate(text.get_family()):
            has_wrapper = hasattr(sub, 'shader_wrapper') and sub.shader_wrapper is not None
            if has_wrapper:
                print(f"  Family {i}: has shader_wrapper, depth_test={sub.shader_wrapper.depth_test}")
            else:
                print(f"  Family {i}: NO shader_wrapper")
        
        self.wait(2)
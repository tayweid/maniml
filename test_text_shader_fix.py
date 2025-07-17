from manim import *

class TextShaderFix(ThreeDScene):
    """Fix text by ensuring shader wrappers are updated for all submobjects."""
    
    def construct(self):
        self.set_camera_orientation(phi=70 * DEGREES, theta=-45 * DEGREES)
        
        # Plane
        plane = Square3D(side_length=5, color=GREY_D, opacity=0.8)
        
        # Text in front
        text_front = Text("Front", color=GREEN, font_size=40)
        text_front.shift(OUT * 1)
        
        # Text behind  
        text_behind = Text("Behind", color=RED, font_size=40)
        text_behind.shift(IN * 1)
        
        # Function to properly fix depth for text
        def fix_text_depth(text_mob):
            """Apply depth test and ensure shader wrappers are updated."""
            # First apply depth test to all family members
            text_mob.apply_depth_test()
            
            # Then ensure each submobject refreshes its shader wrapper
            for submob in text_mob.get_family():
                if hasattr(submob, 'refresh_shader_wrapper_id'):
                    submob.refresh_shader_wrapper_id()
                    
                # Also check if we need to create shader wrapper
                if hasattr(submob, 'shader_wrapper'):
                    if submob.shader_wrapper is not None:
                        submob.shader_wrapper.depth_test = True
            
            return text_mob
        
        # Fix both texts
        fix_text_depth(text_front)
        fix_text_depth(text_behind)
        
        # Add everything
        self.play(
            Create(plane),
            Write(text_front),
            Write(text_behind)
        )
        
        # Rotate to verify depth
        self.begin_ambient_camera_rotation(rate=0.15)
        self.wait(8)
        self.stop_ambient_camera_rotation()


class CompareTextVsCircle(ThreeDScene):
    """Compare how text and circle behave differently."""
    
    def construct(self):
        self.set_camera_orientation(phi=70 * DEGREES, theta=-45 * DEGREES)
        
        # Plane
        plane = Square3D(side_length=6, color=GREY_D, opacity=0.8)
        
        # Circle (works)
        circle = Circle(color=GREEN, radius=0.5)
        circle.shift(LEFT * 2 + OUT * 1)
        
        # Text (broken)
        text = Text("Text", color=GREEN, font_size=40)
        text.shift(RIGHT * 2 + OUT * 1)
        
        # Add labels
        self.add_fixed_in_frame_mobjects(
            Text("Circle (works)", font_size=20).shift(LEFT * 2 + UP * 3),
            Text("Text (broken)", font_size=20).shift(RIGHT * 2 + UP * 3)
        )
        
        # Add everything
        self.play(
            Create(plane),
            Create(circle),
            Write(text)
        )
        
        # Check family sizes
        print(f"\nCircle family size: {len(circle.get_family())}")
        print(f"Text family size: {len(text.get_family())}")
        
        # Print depth test values
        print("\nCircle family depth_test:")
        for i, mob in enumerate(circle.get_family()):
            print(f"  {i}: {mob.depth_test}")
            
        print("\nText family depth_test:")
        for i, mob in enumerate(text.get_family()):
            print(f"  {i}: {mob.depth_test}")
        
        self.wait(5)
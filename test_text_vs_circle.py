from manim import *

class TextVsCircleDebug(ThreeDScene):
    """Debug why circles work but text doesn't."""
    
    def construct(self):
        self.set_camera_orientation(phi=70 * DEGREES, theta=-45 * DEGREES)
        
        # Plane in the middle
        plane = Square3D(side_length=6, color=GREY_D, opacity=0.8)
        
        # Circle that works
        circle = Circle(color=GREEN, radius=0.5)
        circle.shift(LEFT * 2 + OUT * 1)
        
        # Text that doesn't work
        text = Text("Text", color=GREEN, font_size=30)
        text.shift(RIGHT * 2 + OUT * 1)
        
        # Add labels
        self.add_fixed_in_frame_mobjects(
            Text("Circle (works)", font_size=20).shift(LEFT * 2 + UP * 3),
            Text("Text (broken)", font_size=20).shift(RIGHT * 2 + UP * 3)
        )
        
        # Add all
        self.add(plane)
        self.add(circle, text)
        
        # Debug properties
        print("\n=== COMPARING PROPERTIES ===")
        print(f"Circle depth_test: {circle.depth_test}")
        print(f"Text depth_test: {text.depth_test}")
        print(f"Circle has shader_wrapper: {hasattr(circle, 'shader_wrapper') and circle.shader_wrapper is not None}")
        print(f"Text has shader_wrapper: {hasattr(text, 'shader_wrapper') and text.shader_wrapper is not None}")
        
        # Check stroke properties
        print(f"\nCircle stroke_width: {circle.stroke_width}")
        print(f"Text stroke_width: {text.stroke_width}")
        print(f"Circle fill_opacity: {circle.fill_opacity}")
        print(f"Text fill_opacity: {text.fill_opacity}")
        
        # Check if text is made of submobjects
        print(f"\nCircle submobjects: {len(circle.submobjects)}")
        print(f"Text submobjects: {len(text.submobjects)}")
        
        # Rotate to see depth
        self.begin_ambient_camera_rotation(rate=0.15)
        self.wait(10)
        self.stop_ambient_camera_rotation()


class TextAsVGroup(ThreeDScene):
    """Text might be a VGroup of individual letters."""
    
    def construct(self):
        self.set_camera_orientation(phi=70 * DEGREES, theta=-45 * DEGREES)
        
        # Plane in the middle
        plane = Square3D(side_length=5, color=GREY_D, opacity=0.8)
        
        # Create text
        text = Text("ABC", color=GREEN, font_size=40)
        text.shift(OUT * 1)
        
        # Check structure
        print(f"\nText type: {type(text)}")
        print(f"Text submobjects: {len(text.submobjects)}")
        if len(text.submobjects) > 0:
            print("Text has submobjects!")
            for i, submob in enumerate(text.submobjects):
                print(f"  Submob {i}: type={type(submob)}, depth_test={submob.depth_test}")
        
        # Add everything
        self.add(plane)
        self.add(text)
        
        # Try applying depth test to all submobjects manually
        for submob in text.family_members_with_points():
            submob.depth_test = True
            if hasattr(submob, 'shader_wrapper') and submob.shader_wrapper:
                submob.shader_wrapper.depth_test = True
        
        self.wait(5)


class ManualTextFix(ThreeDScene):
    """Try to manually fix text depth."""
    
    def construct(self):
        self.set_camera_orientation(phi=70 * DEGREES, theta=-45 * DEGREES)
        
        # Plane
        plane = Square3D(side_length=4, color=GREY_D, opacity=0.8)
        
        # Text
        text = Text("Fixed?", color=WHITE, font_size=40)
        text.shift(OUT * 1)
        
        # Manually ensure depth test is applied to all parts
        def force_depth_test(mob):
            mob.depth_test = True
            if hasattr(mob, 'shader_wrapper') and mob.shader_wrapper:
                mob.shader_wrapper.depth_test = True
                # Force refresh
                mob.shader_wrapper.refresh_id()
            for submob in mob.submobjects:
                force_depth_test(submob)
        
        # Apply before adding
        force_depth_test(text)
        
        # Add
        self.add(plane)
        self.add(text)
        
        # Force refresh again
        text.refresh_shader_wrapper_id()
        
        self.wait(5)
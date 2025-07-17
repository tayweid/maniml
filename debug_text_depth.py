from manim import *

class DebugTextDepth(ThreeDScene):
    """Debug why text depth test isn't working."""
    
    def construct(self):
        self.set_camera_orientation(phi=70 * DEGREES, theta=-45 * DEGREES)
        
        # Plane
        plane = Square3D(side_length=4, color=GREY_D, opacity=0.8)
        
        # Text in front
        text = Text("ABC", color=WHITE, font_size=40)
        text.shift(OUT * 1)
        
        # Print initial state
        print("\n=== TEXT STRUCTURE ===")
        print(f"Text type: {type(text)}")
        print(f"Text.depth_test: {text.depth_test}")
        print(f"Text has {len(text.submobjects)} submobjects")
        print(f"Text family size: {len(text.get_family())}")
        
        # Check submobjects
        if len(text.submobjects) > 0:
            print("\nSubmobject details:")
            for i, sub in enumerate(text.submobjects):
                print(f"  Submob {i}: type={type(sub).__name__}, depth_test={sub.depth_test}")
        
        # Add to scene (should apply depth test)
        self.play(Create(plane))
        self.add(text)
        
        # Check after adding
        print("\n=== AFTER ADDING TO SCENE ===")
        print(f"Text.depth_test: {text.depth_test}")
        
        # Check submobjects again
        if len(text.submobjects) > 0:
            print("\nSubmobject depth_test after adding:")
            for i, sub in enumerate(text.submobjects):
                print(f"  Submob {i}: depth_test={sub.depth_test}")
        
        # Check all family members
        print("\nAll family members:")
        for i, mob in enumerate(text.get_family()):
            print(f"  Family member {i}: type={type(mob).__name__}, depth_test={mob.depth_test}")
        
        # Manually apply depth test to ALL family members
        print("\n=== MANUALLY APPLYING DEPTH TEST TO ALL ===")
        for mob in text.get_family():
            mob.depth_test = True
            # Also refresh shader wrapper
            if hasattr(mob, 'refresh_shader_wrapper_id'):
                mob.refresh_shader_wrapper_id()
        
        # Check again
        print("\nAfter manual application:")
        for i, mob in enumerate(text.get_family()):
            print(f"  Family member {i}: depth_test={mob.depth_test}")
        
        self.wait(5)


class FixTextDepth(ThreeDScene):
    """Try to fix text depth by applying to all family members."""
    
    def construct(self):
        self.set_camera_orientation(phi=70 * DEGREES, theta=-45 * DEGREES)
        
        # Plane
        plane = Square3D(side_length=5, color=GREY_D, opacity=0.8)
        
        # Text that should be in front
        text_front = Text("Front", color=GREEN, font_size=40)
        text_front.shift(OUT * 1)
        
        # Text that should be behind
        text_behind = Text("Behind", color=RED, font_size=40)
        text_behind.shift(IN * 1)
        
        # Function to fix depth test
        def fix_depth_test(mob):
            """Apply depth test to all family members."""
            for m in mob.get_family():
                m.depth_test = True
                if hasattr(m, 'refresh_shader_wrapper_id'):
                    m.refresh_shader_wrapper_id()
        
        # Fix both texts
        fix_depth_test(text_front)
        fix_depth_test(text_behind)
        
        # Add everything
        self.add(plane)
        self.add(text_front, text_behind)
        
        # Rotate to see depth
        self.begin_ambient_camera_rotation(rate=0.15)
        self.wait(8)
        self.stop_ambient_camera_rotation()
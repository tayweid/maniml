from manim import *

class DebugTextSubmobjects(ThreeDScene):
    """Debug text submobject structure and depth test application."""
    
    def construct(self):
        self.set_camera_orientation(phi=70 * DEGREES, theta=-45 * DEGREES)
        
        # Plane
        plane = Square3D(side_length=5, color=GREY_D, opacity=0.8)
        self.add(plane)
        
        # Create text and circle
        text = Text("ABC", color=GREEN, font_size=40)
        text.shift(LEFT * 2 + OUT * 1)
        
        circle = Circle(color=GREEN, radius=0.5)
        circle.shift(RIGHT * 2 + OUT * 1)
        
        # Print structure before adding
        print("\n=== BEFORE ADDING TO SCENE ===")
        print(f"Text family: {len(text.get_family())} members")
        print(f"Circle family: {len(circle.get_family())} members")
        
        # Check text submobjects
        if len(text.submobjects) > 0:
            print(f"\nText has {len(text.submobjects)} submobjects")
            for i, sub in enumerate(text.submobjects):
                print(f"  Submob {i}: depth_test={getattr(sub, 'depth_test', 'None')}")
        
        # Add to scene (this should apply depth test)
        self.add(text, circle)
        
        # Print structure after adding
        print("\n=== AFTER ADDING TO SCENE ===")
        print(f"Text depth_test: {text.depth_test}")
        print(f"Circle depth_test: {circle.depth_test}")
        
        # Check submobjects again
        if len(text.submobjects) > 0:
            print(f"\nText submobjects after add:")
            for i, sub in enumerate(text.submobjects):
                print(f"  Submob {i}: depth_test={getattr(sub, 'depth_test', 'None')}")
        
        # Check all family members
        print(f"\nText family depth_test values:")
        for i, mob in enumerate(text.get_family()):
            print(f"  Member {i}: depth_test={getattr(mob, 'depth_test', 'None')}")
        
        self.wait(5)


class ForceDepthOnSubmobjects(ThreeDScene):
    """Manually apply depth test to all submobjects."""
    
    def construct(self):
        self.set_camera_orientation(phi=70 * DEGREES, theta=-45 * DEGREES)
        
        # Plane
        plane = Square3D(side_length=5, color=GREY_D, opacity=0.8)
        self.add(plane)
        
        # Create text
        text = Text("TEST", color=WHITE, font_size=50)
        text.shift(OUT * 1)
        
        # First add normally to see the issue
        self.add(text)
        self.wait(2)
        
        # Remove and re-add with forced depth test
        self.remove(text)
        
        # Force depth test on ALL family members
        print("\n=== FORCING DEPTH TEST ===")
        for mob in text.get_family():
            mob.depth_test = True
            print(f"Set depth_test=True on {type(mob).__name__}")
            
            # Also refresh shader wrapper if it exists
            if hasattr(mob, 'refresh_shader_wrapper_id'):
                mob.refresh_shader_wrapper_id()
        
        # Re-add
        self.add(text)
        
        # Add label
        self.add_fixed_in_frame_mobjects(
            Text("Forced depth test on all submobjects", font_size=20).to_edge(UP)
        )
        
        self.wait(5)


class TextLetterByLetter(ThreeDScene):
    """Add text letters individually to see if that works."""
    
    def construct(self):
        self.set_camera_orientation(phi=70 * DEGREES, theta=-45 * DEGREES)
        
        # Plane
        plane = Square3D(side_length=5, color=GREY_D, opacity=0.8)
        self.add(plane)
        
        # Create text
        full_text = Text("ABC", color=WHITE, font_size=50)
        full_text.shift(UP * 1.5 + OUT * 1)
        
        # Add full text (broken)
        self.add(full_text)
        
        # Now add individual letters
        if len(full_text.submobjects) > 0:
            # Position individual letters below
            for i, letter in enumerate(full_text.submobjects):
                letter_copy = letter.copy()
                letter_copy.shift(DOWN * 3 + RIGHT * (i - 1))
                # Add each letter individually (this might trigger depth test)
                self.add(letter_copy)
        
        # Labels
        self.add_fixed_in_frame_mobjects(
            Text("Full text (broken)", font_size=15).shift(UP * 2.5),
            Text("Individual letters", font_size=15).shift(DOWN * 1.5)
        )
        
        self.wait(5)
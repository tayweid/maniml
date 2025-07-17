from manim import *

class ManualTextFix(ThreeDScene):
    """Override ThreeDScene.add to fix text depth issue."""
    
    def add(self, *mobjects, **kwargs):
        """Override add to properly handle text depth."""
        for mob in mobjects:
            # Check if this is a Text-like object (has submobjects that are VMobjectFromSVGPath)
            if (hasattr(mob, 'submobjects') and 
                len(mob.submobjects) > 0 and
                any('VMobjectFromSVGPath' in str(type(sub)) for sub in mob.submobjects)):
                # This looks like text - apply depth test to ALL family members
                for family_member in mob.get_family():
                    family_member.depth_test = True
                    if hasattr(family_member, 'refresh_shader_wrapper_id'):
                        family_member.refresh_shader_wrapper_id()
        
        # Call parent add
        super().add(*mobjects, **kwargs)
    
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
        
        # Circle for comparison
        circle = Circle(color=BLUE, radius=0.5)
        circle.shift(LEFT * 3 + OUT * 0.5)
        
        # Add everything (our custom add should fix text)
        self.play(
            Create(plane),
            Write(text_front),
            Write(text_behind),
            Create(circle)
        )
        
        # Add labels
        self.add_fixed_in_frame_mobjects(
            Text("Should see depth working", font_size=20).to_edge(UP)
        )
        
        # Rotate to verify
        self.begin_ambient_camera_rotation(rate=0.15)
        self.wait(8)
        self.stop_ambient_camera_rotation()


class TextAsVGroup(ThreeDScene):
    """Test if creating text as a VGroup of circles works."""
    
    def construct(self):
        self.set_camera_orientation(phi=70 * DEGREES, theta=-45 * DEGREES)
        
        # Plane
        plane = Square3D(side_length=5, color=GREY_D, opacity=0.8)
        
        # Regular text (broken)
        text_broken = Text("Broken", color=RED, font_size=30)
        text_broken.shift(UP * 1.5 + OUT * 1)
        
        # Simulate text with circles (should work)
        fake_text = VGroup()
        for i, letter in enumerate("Works"):
            # Create a circle for each letter position
            circle = Circle(radius=0.2, color=GREEN)
            circle.shift(RIGHT * (i - 2) * 0.5 + DOWN * 1.5 + OUT * 1)
            fake_text.add(circle)
        
        # Add everything
        self.play(Create(plane))
        self.play(Write(text_broken), Create(fake_text))
        
        # Labels
        self.add_fixed_in_frame_mobjects(
            Text("Real Text", font_size=15).shift(UP * 2.5),
            Text("Circles as Letters", font_size=15).shift(DOWN * 0.5)
        )
        
        self.wait(5)
from manim import *

class ThreeDSceneFixed(ThreeDScene):
    """
    Fixed ThreeDScene that properly handles text rendering in 3D.
    
    The key issue is that text (VMobjects) need special handling for anti-aliasing
    when depth testing is enabled. This class overrides the add() method to
    automatically configure text objects for proper 3D rendering.
    """
    
    def add(self, *mobjects: Mobject, set_depth_test: bool = True, perp_stroke: bool = True):
        for mob in mobjects:
            if set_depth_test and not mob.is_fixed_in_frame() and self.always_depth_test:
                # Special handling for VMobjects (includes Text)
                if isinstance(mob, VMobject):
                    # Check if this is likely a text object
                    # Text objects typically have fill but minimal/no initial stroke
                    is_text_like = (
                        mob.has_fill() and 
                        mob.get_fill_opacity() > 0 and
                        (not mob.has_stroke() or mob.get_stroke_width() < 1)
                    )
                    
                    if is_text_like:
                        # For text-like objects, use higher anti-alias width for better quality
                        # This preserves text quality while still enabling depth testing
                        mob.apply_depth_test(anti_alias_width=1.0)
                    else:
                        # For other VMobjects, use default (0) for sharp edges in 3D
                        mob.apply_depth_test(anti_alias_width=0)
                else:
                    # Non-VMobjects just get regular depth test
                    mob.apply_depth_test()
                    
            if isinstance(mob, VMobject) and mob.has_stroke() and perp_stroke:
                mob.set_flat_stroke(False)
                
        super(ThreeDScene, self).add(*mobjects)


class ConsumerSurplusProperlyFixed(ThreeDSceneFixed):
    """Example using the fixed ThreeDScene"""
    def construct(self):
        # Set camera angle
        self.set_camera_orientation(phi=70 * DEGREES, theta=-45 * DEGREES)
        
        # Dark grey plane
        plane = Square3D(side_length=5, color=GREY_D, opacity=0.9)
        self.add(plane)
        
        # Person (Maxine) - small blue disk
        person = Disk3D(radius=0.25, color=BLUE_B)
        person.shift(OUT * 0.02)
        
        # Text with proper settings for 3D
        # The key is to use good contrast and positioning
        name = Text("Maxine", 
                   font_size=24,
                   color=WHITE,  # White with black stroke works well
                   stroke_width=4,
                   stroke_color=BLACK,
                   fill_opacity=1.0)
        name.rotate(PI/2, RIGHT)  # Face upward
        name.next_to(person, DOWN * 0.6)
        name.shift(OUT * 0.15)  # Lift above plane
        
        # Consumer surplus bar
        bar = Cube(color=GREEN_A, opacity=0.9)
        bar.scale([2, 0.35, 0.12])
        bar.shift(OUT * 1.2)
        
        # Surplus label
        bar_label = Text("Consumer Surplus", 
                        font_size=20,
                        color=WHITE,
                        stroke_width=4,
                        stroke_color=BLACK,
                        fill_opacity=1.0)
        bar_label.rotate(PI/2, RIGHT)
        bar_label.move_to(bar.get_center() + OUT * 0.5)
        
        # Add everything - the fixed add() method handles depth testing properly
        self.play(FadeIn(person), Write(name))
        self.play(FadeIn(bar, shift=OUT * 0.3), Write(bar_label))
        
        # Subtle animation
        self.play(
            bar.animate.shift(OUT * 0.05).set_color(GREEN_B),
            rate_func=there_and_back,
            run_time=1.5
        )
        
        # Camera rotation
        self.begin_ambient_camera_rotation(rate=0.08)
        self.wait(8)
        self.stop_ambient_camera_rotation()
        self.wait(2)


class TextRenderingComparison(ThreeDScene):
    """Compare different text rendering approaches"""
    def construct(self):
        self.set_camera_orientation(phi=70 * DEGREES, theta=-45 * DEGREES)
        
        # Create grey plane
        plane = Square3D(side_length=6, color=GREY_D, opacity=0.9)
        self.add(plane)
        
        # Method 1: Default (problematic)
        text1 = Text("Default", font_size=20, color=WHITE)
        text1.rotate(PI/2, RIGHT)
        text1.shift(LEFT * 2 + OUT * 0.1)
        # Just add normally - will get depth test with anti_alias_width=0
        
        # Method 2: Manual fix with anti-aliasing
        text2 = Text("Manual Fix", font_size=20, color=WHITE,
                    stroke_width=3, stroke_color=BLACK)
        text2.rotate(PI/2, RIGHT)
        text2.shift(OUT * 0.1)
        # Manually apply depth test before adding
        text2.apply_depth_test(anti_alias_width=1.0)
        
        # Method 3: High contrast colors
        text3 = Text("High Contrast", font_size=20, color=YELLOW,
                    stroke_width=4, stroke_color=BLACK)
        text3.rotate(PI/2, RIGHT)
        text3.shift(RIGHT * 2 + OUT * 0.15)
        
        # Add all text
        self.add(text1, text2, text3)
        self.wait()
        
        # Add labels to identify each
        for i, (text, label_text, color) in enumerate([
            (text1, "BAD", RED),
            (text2, "BETTER", YELLOW),
            (text3, "BEST", GREEN)
        ]):
            label = Text(label_text, font_size=16, color=color)
            label.next_to(text, DOWN * 2)
            label.fix_in_frame()  # Labels fixed for clarity
            self.add(label)
        
        # Rotate to see differences
        self.begin_ambient_camera_rotation(rate=0.1)
        self.wait(8)
        self.stop_ambient_camera_rotation()


# Alternative approach: Monkey-patch the existing ThreeDScene
def fixed_add(self, *mobjects: Mobject, set_depth_test: bool = True, perp_stroke: bool = True):
    """Fixed add method that handles text properly in 3D"""
    for mob in mobjects:
        if set_depth_test and not mob.is_fixed_in_frame() and self.always_depth_test:
            if isinstance(mob, VMobject) and hasattr(mob, 'text'):
                # This is likely a Text object
                mob.apply_depth_test(anti_alias_width=1.0)
            else:
                mob.apply_depth_test()
                
        if isinstance(mob, VMobject) and mob.has_stroke() and perp_stroke:
            mob.set_flat_stroke(False)
            
    # Call Scene.add() directly to avoid recursion
    Scene.add(self, *mobjects)

# You can apply this fix to all ThreeDScenes like this:
# ThreeDScene.add = fixed_add
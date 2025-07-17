from manim import *

class ConsumerSurplusProperSolution(ThreeDScene):
    """
    The proper solution based on how manimgl handles text in 3D scenes.
    
    The issue: When ThreeDScene.add() applies depth test to VMobjects (including Text),
    it sets anti_alias_width to 0, which makes the text invisible.
    """
    
    def construct(self):
        # Set camera angle
        self.set_camera_orientation(phi=70 * DEGREES, theta=-45 * DEGREES)
        
        # Dark grey plane
        plane = Square3D(side_length=4, color=GREY_D, opacity=0.9)
        self.add(plane)
        
        # Person (Maxine) - small blue disk
        person = Disk3D(radius=0.2, color=BLUE)
        person.shift(OUT * 0.01)
        self.add(person)
        
        # SOLUTION 1: Add text without depth testing
        name = Text("Maxine", font_size=20, color=WHITE,
                   stroke_width=3, stroke_color=BLACK)
        name.rotate(PI/2, RIGHT)
        name.next_to(person, DOWN * 0.5)
        name.shift(OUT * 0.1)
        # Add with set_depth_test=False to prevent anti_alias_width being set to 0
        self.add(name, set_depth_test=False)
        
        # Consumer surplus bar
        bar = Cube(color=GREEN)
        bar.scale([1.5, 0.3, 0.1])
        bar.shift(OUT * 1.0)
        self.add(bar)
        
        # SOLUTION 2: Deactivate depth test after adding
        bar_label = Text("Consumer Surplus", font_size=18, color=WHITE,
                        stroke_width=3, stroke_color=BLACK)
        bar_label.rotate(PI/2, RIGHT)
        bar_label.move_to(bar.get_center() + OUT * 0.5)
        self.add(bar_label)  # This sets anti_alias_width to 0
        bar_label.deactivate_depth_test()  # This restores anti_alias_width to 1.0
        
        # Animate
        self.play(
            bar.animate.shift(OUT * 0.05).set_color(GREEN_B),
            rate_func=there_and_back,
            run_time=1.5
        )
        
        # Rotate the scene
        self.begin_ambient_camera_rotation(rate=0.1)
        self.wait(8)
        self.stop_ambient_camera_rotation()
        self.wait()


class ConsumerSurplusAllSolutions(ThreeDScene):
    """Demonstrates all proper solutions for text in 3D scenes"""
    
    def construct(self):
        self.set_camera_orientation(phi=70 * DEGREES, theta=-45 * DEGREES)
        
        # Grey plane
        plane = Square3D(side_length=6, color=GREY_D, opacity=0.9)
        self.add(plane)
        
        # Solution 1: set_depth_test=False
        text1 = Text("set_depth_test=False", font_size=16, color=WHITE,
                    stroke_width=3, stroke_color=BLACK)
        text1.rotate(PI/2, RIGHT)
        text1.shift(LEFT * 2 + OUT * 0.1)
        self.add(text1, set_depth_test=False)
        
        # Solution 2: deactivate_depth_test() after adding
        text2 = Text("deactivate_depth_test()", font_size=16, color=WHITE,
                    stroke_width=3, stroke_color=BLACK)
        text2.rotate(PI/2, RIGHT)
        text2.shift(OUT * 0.1)
        self.add(text2)
        text2.deactivate_depth_test()
        
        # Solution 3: fix_in_frame() for UI elements
        text3 = Text("fix_in_frame()", font_size=16, color=WHITE,
                    stroke_width=3, stroke_color=BLACK)
        text3.shift(RIGHT * 2)
        text3.fix_in_frame()
        self.add(text3)
        
        # Labels
        for i, (pos, color) in enumerate([(LEFT * 2, GREEN), (ORIGIN, GREEN), (RIGHT * 2, YELLOW)]):
            label = Text(f"Solution {i+1}", font_size=14, color=color)
            label.shift(pos + DOWN * 2)
            label.fix_in_frame()
            self.add(label)
        
        self.begin_ambient_camera_rotation(rate=0.1)
        self.wait(8)
        self.stop_ambient_camera_rotation()


# The best fix: Override ThreeDScene to handle text properly
class ThreeDSceneProper(ThreeDScene):
    """
    A fixed ThreeDScene that handles text rendering properly.
    
    This matches the behavior users expect: text should be visible
    in 3D scenes without special configuration.
    """
    
    def add(self, *mobjects: Mobject, set_depth_test: bool = True, perp_stroke: bool = True):
        for mob in mobjects:
            if set_depth_test and not mob.is_fixed_in_frame() and self.always_depth_test:
                mob.apply_depth_test()
                # Fix for VMobjects: restore anti_alias_width if it's a VMobject
                if isinstance(mob, VMobject):
                    # Check if this looks like text (has fill but minimal stroke initially)
                    is_text_like = (
                        hasattr(mob, '__class__') and 
                        'Text' in mob.__class__.__name__
                    )
                    if is_text_like:
                        # For text, restore anti-aliasing for visibility
                        mob.set_anti_alias_width(1.0)
                
            if isinstance(mob, VMobject) and mob.has_stroke() and perp_stroke:
                mob.set_flat_stroke(False)
                
        super(ThreeDScene, self).add(*mobjects)


class ConsumerSurplusBestPractice(ThreeDSceneProper):
    """Using the fixed ThreeDScene class"""
    
    def construct(self):
        self.set_camera_orientation(phi=70 * DEGREES, theta=-45 * DEGREES)
        
        # Dark grey plane
        plane = Square3D(side_length=4, color=GREY_D, opacity=0.9)
        self.add(plane)
        
        # Person (Maxine) - small blue disk
        person = Disk3D(radius=0.2, color=BLUE)
        person.shift(OUT * 0.01)
        
        # With ThreeDSceneProper, text just works!
        name = Text("Maxine", font_size=20, color=WHITE,
                   stroke_width=3, stroke_color=BLACK)
        name.rotate(PI/2, RIGHT)
        name.next_to(person, DOWN * 0.5)
        name.shift(OUT * 0.1)
        
        # Consumer surplus bar
        bar = Cube(color=GREEN)
        bar.scale([1.5, 0.3, 0.1])
        bar.shift(OUT * 1.0)
        
        bar_label = Text("Consumer Surplus", font_size=18, color=WHITE,
                        stroke_width=3, stroke_color=BLACK)
        bar_label.rotate(PI/2, RIGHT)
        bar_label.move_to(bar.get_center() + OUT * 0.5)
        
        # Just add normally - ThreeDSceneProper handles it correctly
        self.play(FadeIn(person), Write(name))
        self.play(FadeIn(bar, shift=OUT * 0.3), Write(bar_label))
        
        self.begin_ambient_camera_rotation(rate=0.1)
        self.wait(8)
        self.stop_ambient_camera_rotation()
        self.wait()
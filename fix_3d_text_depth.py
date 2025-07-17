from manim import *

class Fix3DTextDepth(ThreeDScene):
    """Demonstrates the text depth issue and solutions"""
    
    def construct(self):
        self.set_camera_orientation(phi=70 * DEGREES, theta=-45 * DEGREES)
        
        # Create grey plane
        plane = Square3D(side_length=4, color=GREY_D, opacity=0.9)
        self.add(plane)
        
        # SOLUTION 1: Use stroke_behind=True to render stroke first
        text1 = Text("Stroke Behind", font_size=20, 
                    color=WHITE,
                    stroke_width=3, 
                    stroke_color=BLACK,
                    stroke_behind=True)  # This might help!
        text1.rotate(PI/2, RIGHT)
        text1.shift(LEFT * 1.5 + OUT * 0.1)
        self.add(text1)
        
        # SOLUTION 2: Position text well above the plane
        text2 = Text("Higher Position", font_size=20,
                    color=WHITE,
                    stroke_width=3,
                    stroke_color=BLACK)
        text2.rotate(PI/2, RIGHT)
        text2.shift(RIGHT * 1.5 + OUT * 0.5)  # Much higher
        self.add(text2)
        
        # SOLUTION 3: Use fill_opacity=1 and ensure proper depth test
        text3 = Text("Full Opacity", font_size=20,
                    color=WHITE,
                    fill_opacity=1.0,  # Ensure full opacity
                    stroke_width=3,
                    stroke_color=BLACK)
        text3.rotate(PI/2, RIGHT)
        text3.shift(DOWN * 1.5 + OUT * 0.2)
        # Manually apply depth test with specific settings
        text3.apply_depth_test(anti_alias_width=0)
        text3.z_index = 5  # Higher z-index
        self.add(text3)
        
        # SOLUTION 4: Create a background object for the text
        # This is a workaround but effective
        text_bg = Rectangle(width=2, height=0.4, 
                          color=BLACK, 
                          fill_opacity=0.9,
                          stroke_width=0)
        text_bg.rotate(PI/2, RIGHT)
        text_bg.shift(UP * 1.5 + OUT * 0.15)
        
        text4 = Text("With Background", font_size=20, color=WHITE)
        text4.rotate(PI/2, RIGHT)
        text4.move_to(text_bg.get_center() + OUT * 0.01)
        
        self.add(text_bg, text4)
        
        # Labels
        labels = [
            ("stroke_behind=True", LEFT * 1.5),
            ("Higher position", RIGHT * 1.5),
            ("Full opacity + depth", DOWN * 1.5),
            ("Background object", UP * 1.5)
        ]
        
        for label_text, pos in labels:
            label = Text(label_text, font_size=14, color=YELLOW)
            label.shift(pos + DOWN * 2)
            label.fix_in_frame()
            self.add(label)
        
        self.begin_ambient_camera_rotation(rate=0.1)
        self.wait(10)
        self.stop_ambient_camera_rotation()


class TextDepthWorkaround(ThreeDScene):
    """A practical workaround for the text depth issue"""
    
    def construct(self):
        self.set_camera_orientation(phi=70 * DEGREES, theta=-45 * DEGREES)
        
        # Grey plane
        plane = Square3D(side_length=5, color=GREY_D, opacity=0.9)
        self.add(plane)
        
        # The issue: fill renders behind plane
        problem_text = Text("Problem", color=WHITE)
        problem_text.rotate(PI/2, RIGHT)
        problem_text.shift(LEFT * 2 + OUT * 0.05)
        self.add(problem_text)
        
        # WORKAROUND 1: Use a 3D object as text background
        # Create a thin black rectangle behind text
        text_plate = Cube(color=BLACK, opacity=0.95)
        text_plate.scale([1.5, 0.3, 0.01])  # Very thin
        text_plate.shift(OUT * 0.1)
        
        good_text = Text("Solution", color=WHITE)
        good_text.rotate(PI/2, RIGHT)
        good_text.move_to(text_plate.get_center() + OUT * 0.01)
        
        self.add(text_plate, good_text)
        
        # WORKAROUND 2: Use contrasting colors that work even with partial visibility
        contrast_text = Text("High Contrast", 
                           color=YELLOW,  # Bright color
                           stroke_width=5,  # Thick stroke
                           stroke_color=BLACK)
        contrast_text.rotate(PI/2, RIGHT)
        contrast_text.shift(RIGHT * 2 + OUT * 0.1)
        self.add(contrast_text)
        
        self.begin_ambient_camera_rotation(rate=0.1)
        self.wait(8)
        self.stop_ambient_camera_rotation()


class ConsumerSurplusDepthFixed(ThreeDScene):
    """Fixed consumer surplus example addressing the depth issue"""
    
    def construct(self):
        self.set_camera_orientation(phi=70 * DEGREES, theta=-45 * DEGREES)
        
        # Dark grey plane
        plane = Square3D(side_length=4, color=GREY_D, opacity=0.9)
        self.add(plane)
        
        # Person (Maxine) - small blue disk
        person = Disk3D(radius=0.2, color=BLUE)
        person.shift(OUT * 0.02)  # Slightly above plane
        
        # SOLUTION: Create a small dark platform for the text
        # This ensures the text is always visible
        name_platform = Cylinder(
            radius=0.5,
            height=0.02,
            color=BLACK,
            opacity=0.9
        )
        name_platform.rotate(PI/2, RIGHT)
        name_platform.next_to(person, DOWN * 0.5)
        name_platform.shift(OUT * 0.05)
        
        name = Text("Maxine", 
                   font_size=20, 
                   color=WHITE)
        name.rotate(PI/2, RIGHT)
        name.move_to(name_platform.get_center() + OUT * 0.02)
        
        # Consumer surplus bar
        bar = Cube(color=GREEN)
        bar.scale([1.5, 0.3, 0.1])
        bar.shift(OUT * 1.0)
        
        # Create platform for bar label too
        label_platform = Cube(color=BLACK, opacity=0.9)
        label_platform.scale([2.2, 0.4, 0.02])
        label_platform.move_to(bar.get_center() + OUT * 0.5)
        
        bar_label = Text("Consumer Surplus", 
                        font_size=18,
                        color=WHITE)
        bar_label.rotate(PI/2, RIGHT)
        bar_label.move_to(label_platform.get_center() + OUT * 0.02)
        
        # Animate with platforms
        self.play(FadeIn(person), FadeIn(name_platform), Write(name))
        self.play(
            FadeIn(bar, shift=OUT * 0.3),
            FadeIn(label_platform),
            Write(bar_label)
        )
        
        # Rotation
        self.begin_ambient_camera_rotation(rate=0.1)
        self.wait(8)
        self.stop_ambient_camera_rotation()
        self.wait()
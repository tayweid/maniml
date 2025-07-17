from manim import *

class ConsumerSurplus3DProper(ThreeDScene):
    """Proper 3D text rendering without fix_in_frame"""
    def construct(self):
        # Set camera angle
        self.set_camera_orientation(phi=70 * DEGREES, theta=-45 * DEGREES)
        
        # Dark grey plane
        plane = Square3D(side_length=4, color=GREY_D, opacity=0.9)
        self.add(plane)
        
        # Person (Maxine) - small blue disk
        person = Disk3D(radius=0.2, color=BLUE)
        person.shift(OUT * 0.01)
        
        # SOLUTION 1: Enable depth testing with proper settings
        name = Text("Maxine", font_size=20, color=WHITE,
                   stroke_width=3, stroke_color=BLACK)
        name.rotate(PI/2, RIGHT)  # Face upward
        name.next_to(person, DOWN * 0.5)
        name.shift(OUT * 0.1)  # Position above plane
        
        # Key fix: Apply depth test with anti-aliasing disabled
        name.apply_depth_test(anti_alias_width=0)
        
        # Consumer surplus bar
        bar = Cube(color=GREEN)
        bar.scale([1.5, 0.3, 0.1])
        bar.shift(OUT * 1.0)
        
        # SOLUTION 2: Create text with specific rendering order
        bar_label = Text("Consumer Surplus", font_size=18, 
                        color=WHITE,
                        stroke_width=4,
                        stroke_color=BLACK,
                        fill_opacity=1.0)  # Ensure full opacity
        bar_label.rotate(PI/2, RIGHT)
        bar_label.move_to(bar.get_center() + OUT * 0.6)
        bar_label.apply_depth_test(anti_alias_width=0)
        bar_label.z_index = 1  # Render after other objects
        
        # Animate
        self.play(FadeIn(person), Write(name))
        self.play(FadeIn(bar, shift=OUT * 0.3), Write(bar_label))
        
        # Rotate the scene
        self.begin_ambient_camera_rotation(rate=0.1)
        self.wait(8)
        self.stop_ambient_camera_rotation()
        self.wait()


class ConsumerSurplus3DAlternative(ThreeDScene):
    """Alternative approach using stroke_behind and other settings"""
    def construct(self):
        # Set camera angle
        self.set_camera_orientation(phi=70 * DEGREES, theta=-45 * DEGREES)
        
        # Dark grey plane
        plane = Square3D(side_length=4, color=GREY_D, opacity=0.9)
        self.add(plane)
        
        # Person (Maxine) - small blue disk
        person = Disk3D(radius=0.2, color=BLUE)
        person.shift(OUT * 0.01)
        
        # SOLUTION 3: Initialize text with stroke_behind=True
        # This requires creating text differently
        name = Text("Maxine", font_size=20)
        name.set_fill(WHITE, opacity=1)
        name.set_stroke(BLACK, width=5, background=True)  # background=True similar to stroke_behind
        name.rotate(PI/2, RIGHT)
        name.next_to(person, DOWN * 0.5)
        name.shift(OUT * 0.15)
        name.apply_depth_test(anti_alias_width=0)
        
        # Consumer surplus bar
        bar = Cube(color=GREEN)
        bar.scale([1.5, 0.3, 0.1])
        bar.shift(OUT * 1.0)
        
        # SOLUTION 4: Use a 3D background for text
        # Create a thin 3D rectangle as background
        text_bg_3d = Cube(color=BLACK, opacity=0.9)
        text_bg_3d.scale([2, 0.4, 0.02])  # Very thin
        text_bg_3d.shift(OUT * 1.7)
        
        bar_label = Text("Consumer Surplus", font_size=18, color=WHITE)
        bar_label.rotate(PI/2, RIGHT)
        bar_label.move_to(text_bg_3d.get_center() + OUT * 0.02)
        bar_label.apply_depth_test(anti_alias_width=0)
        
        # Animate
        self.play(FadeIn(person), Write(name))
        self.play(
            FadeIn(bar, shift=OUT * 0.3),
            FadeIn(text_bg_3d),
            Write(bar_label)
        )
        
        # Rotate the scene
        self.begin_ambient_camera_rotation(rate=0.1)
        self.wait(8)
        self.stop_ambient_camera_rotation()
        self.wait()


class ConsumerSurplus3DOptimal(ThreeDScene):
    """Optimal solution combining best practices"""
    def construct(self):
        # Set camera angle
        self.set_camera_orientation(phi=70 * DEGREES, theta=-45 * DEGREES)
        
        # Create everything first, then configure rendering
        
        # Dark grey plane with slight transparency
        plane = Square3D(side_length=4.5, color=GREY_D, opacity=0.85)
        
        # Person (Maxine) - small blue disk
        person = Disk3D(radius=0.22, color=BLUE_B)
        person.shift(OUT * 0.02)
        
        # Create text with optimal settings for 3D
        name = Text("Maxine", 
                   font_size=22,
                   # Use high contrast colors
                   color=YELLOW,  # Better contrast than white
                   stroke_width=6,
                   stroke_color=BLACK,
                   fill_opacity=1.0)
        name.rotate(PI/2, RIGHT)
        name.next_to(person, DOWN * 0.5)
        name.shift(OUT * 0.2)  # Well above plane
        
        # Apply depth test with no anti-aliasing for sharp edges
        name.apply_depth_test(anti_alias_width=0)
        # Set higher z_index to render after plane
        name.z_index = 2
        
        # Consumer surplus bar with better contrast
        bar = Cube(color=GREEN_A, shading=(0.1, 0.8, 0.2))
        bar.scale([1.8, 0.35, 0.12])
        bar.shift(OUT * 1.1)
        
        # Create 3D text platform (optional but helps visibility)
        text_platform = Cylinder(
            radius=0.9,
            height=0.05,
            color=GREY_E,
            opacity=0.8
        )
        text_platform.rotate(PI/2, RIGHT)
        text_platform.shift(OUT * 1.65)
        
        # Surplus label with optimal settings
        bar_label = Text("Consumer Surplus", 
                        font_size=20,
                        color=YELLOW,
                        stroke_width=5,
                        stroke_color=GREY_E,
                        fill_opacity=1.0)
        bar_label.rotate(PI/2, RIGHT)
        bar_label.move_to(text_platform.get_center() + OUT * 0.03)
        bar_label.apply_depth_test(anti_alias_width=0)
        bar_label.z_index = 3
        
        # Add all objects with proper order
        self.add(plane)
        self.play(FadeIn(person), Write(name))
        self.play(
            FadeIn(bar, shift=OUT * 0.3),
            FadeIn(text_platform),
            Write(bar_label),
            run_time=2
        )
        
        # Subtle animation
        self.play(
            bar.animate.shift(OUT * 0.05).set_color(GREEN_B),
            rate_func=there_and_back,
            run_time=1.5
        )
        
        # Camera rotation
        self.begin_ambient_camera_rotation(rate=0.08)
        self.wait(10)
        self.stop_ambient_camera_rotation()
        
        # Final view
        self.set_camera_orientation(phi=60 * DEGREES, theta=-30 * DEGREES)
        self.wait(2)
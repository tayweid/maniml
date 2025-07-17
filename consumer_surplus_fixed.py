from manim import *

class ConsumerSurplusFixed(ThreeDScene):
    def construct(self):
        # Set camera angle
        self.set_camera_orientation(phi=70 * DEGREES, theta=-45 * DEGREES)
        
        # Dark grey plane
        plane = Square3D(side_length=4, color=GREY_D, opacity=0.9)
        self.add(plane)
        
        # Person (Maxine) - small blue disk
        person = Disk3D(radius=0.2, color=BLUE)
        person.shift(OUT * 0.01)
        
        # Method 1: Fix text in frame (always faces camera, renders on top)
        name = Text("Maxine", font_size=20, color=WHITE)
        name.next_to(person, DOWN * 0.5)
        name.fix_in_frame()  # This makes text always face camera and render properly
        
        # Consumer surplus bar - green floating bar
        bar = Cube(color=GREEN)
        bar.scale([1.5, 0.3, 0.1])  # Make it bar-shaped
        bar.shift(OUT * 1.0)  # Float above
        
        # Method 2: Create text with stroke for better visibility
        bar_label = Text("Consumer Surplus", font_size=18, 
                        color=WHITE,
                        stroke_width=3,
                        stroke_color=BLACK)
        bar_label.move_to(bar.get_center() + OUT * 0.5)
        bar_label.fix_in_frame()
        
        # Animate appearance
        self.play(FadeIn(person), Write(name))
        self.play(FadeIn(bar, shift=OUT * 0.3), Write(bar_label))
        
        # Rotate the scene
        self.begin_ambient_camera_rotation(rate=0.1)
        self.wait(8)
        self.stop_ambient_camera_rotation()
        self.wait()


class ConsumerSurplus3DText(ThreeDScene):
    """Alternative approach using 3D text positioning"""
    def construct(self):
        # Set camera angle
        self.set_camera_orientation(phi=70 * DEGREES, theta=-45 * DEGREES)
        
        # Dark grey plane
        plane = Square3D(side_length=4, color=GREY_D, opacity=0.9)
        self.add(plane)
        
        # Person (Maxine) - small blue disk
        person = Disk3D(radius=0.2, color=BLUE)
        person.shift(OUT * 0.01)
        
        # Method 3: Position text in 3D space with proper depth
        name = Text("Maxine", font_size=20, color=WHITE, 
                   stroke_width=2, stroke_color=GREY_E)
        name.rotate(PI/2, RIGHT)  # Face upward
        name.next_to(person, DOWN * 0.5)
        name.shift(OUT * 0.1)  # Lift text above plane more
        name.apply_depth_test()  # Enable 3D depth testing
        
        # Consumer surplus bar
        bar = Cube(color=GREEN)
        bar.scale([1.5, 0.3, 0.1])
        bar.shift(OUT * 1.0)
        
        # Method 4: Use contrasting background for text
        # Create a small dark rectangle behind the text
        text_bg = Rectangle(width=2, height=0.3, 
                          color=BLACK, 
                          fill_opacity=0.8)
        text_bg.rotate(PI/2, RIGHT)
        text_bg.move_to(bar.get_center() + OUT * 0.5)
        
        bar_label = Text("Consumer Surplus", font_size=18, color=WHITE)
        bar_label.rotate(PI/2, RIGHT)
        bar_label.move_to(text_bg.get_center() + OUT * 0.01)
        
        # Group background and text
        text_group = VGroup(text_bg, bar_label)
        text_group.apply_depth_test()
        
        # Animate
        self.play(FadeIn(person), Write(name))
        self.play(FadeIn(bar, shift=OUT * 0.3), FadeIn(text_group))
        
        # Rotate the scene
        self.begin_ambient_camera_rotation(rate=0.1)
        self.wait(8)
        self.stop_ambient_camera_rotation()
        self.wait()


class ConsumerSurplusBest(ThreeDScene):
    """Best practices version combining multiple techniques"""
    def construct(self):
        # Set camera angle
        self.set_camera_orientation(phi=70 * DEGREES, theta=-45 * DEGREES)
        
        # Dark grey plane with slight gradient
        plane = Square3D(side_length=5, color=GREY_D, opacity=0.95)
        self.play(Create(plane))
        
        # Person (Maxine) - small blue disk with glow
        person = Disk3D(radius=0.25, color=BLUE_B)
        person.shift(OUT * 0.02)
        
        # Create a subtle glow effect around person
        glow = Disk3D(radius=0.35, color=BLUE_E, opacity=0.3)
        glow.shift(OUT * 0.01)
        
        # Name with enhanced visibility
        name = Text("Maxine", 
                   font_size=24, 
                   color=WHITE,
                   stroke_width=4,
                   stroke_color=BLACK,
                   weight=BOLD)
        name.next_to(person, DOWN * 0.6)
        name.shift(LEFT * 0.1)  # Slight offset for visual interest
        name.fix_in_frame()  # Always face camera
        
        # Consumer surplus bar with gradient effect
        bar = Cube(color=GREEN_A, shading=(0.1, 0.7, 0.2))
        bar.scale([2, 0.35, 0.12])
        bar.shift(OUT * 1.2)
        
        # Surplus label with background for contrast
        label_bg = Rectangle(
            width=2.2, height=0.4,
            color=GREY_E,
            fill_opacity=0.9,
            stroke_width=0
        )
        label_bg.shift(OUT * 1.8)
        label_bg.fix_in_frame()
        
        bar_label = Text("Consumer Surplus", 
                        font_size=20,
                        color=BLACK,
                        weight=BOLD)
        bar_label.move_to(label_bg)
        bar_label.fix_in_frame()
        
        # Animate with style
        self.play(
            FadeIn(glow),
            FadeIn(person),
            Write(name),
            run_time=1.5
        )
        
        self.play(
            FadeIn(bar, shift=OUT * 0.5),
            FadeIn(label_bg),
            Write(bar_label),
            run_time=2
        )
        
        # Subtle animation on the bar
        self.play(
            bar.animate.shift(OUT * 0.1).set_color(GREEN_B),
            rate_func=there_and_back,
            run_time=1.5
        )
        
        # Add coordinate reference (subtle)
        axes = ThreeDAxes(
            x_range=(-3, 3, 1),
            y_range=(-3, 3, 1),
            z_range=(0, 2, 0.5),
            axis_config={
                "stroke_width": 1,
                "stroke_opacity": 0.5,
                "include_ticks": False,
            }
        )
        self.play(Create(axes), run_time=1.5)
        
        # Camera rotation
        self.begin_ambient_camera_rotation(rate=0.08)
        self.wait(10)
        self.stop_ambient_camera_rotation()
        
        # Final positioning
        self.set_camera_orientation(phi=60 * DEGREES, theta=-30 * DEGREES)
        self.wait(2)
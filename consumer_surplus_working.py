from manim import *

class ConsumerSurplusWorking(ThreeDScene):
    def construct(self):
        # Set up camera orientation
        self.set_camera_orientation(phi=70 * DEGREES, theta=-45 * DEGREES)
        
        # Create a dark grey square plane at the origin
        plane = Square3D(
            side_length=5,
            color=GREY_D,
            opacity=0.9
        )
        self.play(Create(plane))
        
        # Create a small disk representing a person
        person = Disk3D(
            radius=0.25,
            color=BLUE_B,
            opacity=1.0
        )
        person.shift(OUT * 0.02)  # Position slightly above the plane
        
        # Create label for the person - Method 1: deactivate_depth_test after adding
        person_label = Text("Maxine", font_size=22, color=WHITE, 
                           stroke_width=3, stroke_color=BLACK)
        person_label.rotate(PI/2, RIGHT)  # Rotate to face up
        person_label.next_to(person, DOWN * 0.6)
        person_label.shift(OUT * 0.1)  # Position above plane
        
        # Animate person and label
        self.play(
            FadeIn(person),
            Write(person_label)
        )
        
        # Fix visibility AFTER adding to scene
        person_label.deactivate_depth_test()
        
        # Create a bar representing consumer surplus
        surplus_bar = Cube(
            side_length=1,
            color=GREEN_A,
            opacity=0.9,
            shading=(0.2, 0.5, 0.2)
        )
        # Scale to make it bar-shaped
        surplus_bar.scale([2, 0.3, 0.1])
        surplus_bar.shift(OUT * 1.2)  # Float above the plane
        
        # Add a label for the surplus bar - Method 2: set_depth_test=False
        surplus_label = Text("Consumer Surplus", font_size=18, color=WHITE, 
                           stroke_width=3, stroke_color=BLACK)
        surplus_label.rotate(PI/2, RIGHT)
        surplus_label.move_to(surplus_bar.get_center() + OUT * 0.5)
        
        # Animate the surplus bar and label
        self.play(FadeIn(surplus_bar))
        # Add label without depth test
        self.add(surplus_label, set_depth_test=False)
        self.play(Write(surplus_label))
        
        # Add some visual interest - make the bar pulse slightly
        self.play(
            surplus_bar.animate.scale(1.05).set_color(GREEN_B),
            rate_func=there_and_back,
            run_time=1.5
        )
        
        # Start slow camera rotation around the scene
        self.begin_ambient_camera_rotation(rate=0.1)
        self.wait(8)
        
        # Stop rotation and hold final view
        self.stop_ambient_camera_rotation()
        self.wait(2)
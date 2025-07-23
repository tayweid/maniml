from manim import *

class ConsumerSurplusDemo(ThreeDScene):
    def construct(self):
        # Set up camera orientation for a nice view
        self.set_camera_orientation(phi=65 * DEGREES, theta=-45 * DEGREES)
        
        # Create a dark grey square plane at the origin
        plane = Square3D(
            side_length=5,
            color=GREY_D,
            opacity=0.9,
            shading=(0.1, 0.4, 0.1)
        )
        
        # Create a small disk representing Maxine
        person = Disk3D(
            radius=0.25,
            color=BLUE_B,
            opacity=1.0
        )
        person.shift(OUT * 0.01)  # Slightly above plane to avoid z-fighting
        
        # Create label for Maxine
        name_label = Text("Maxine", font_size=22, color=WHITE)
        name_label.rotate(PI/2, RIGHT)  # Face upward
        name_label.next_to(person, DOWN, buff=0.3)
        name_label.shift(OUT * 0.02)
        
        # Create the consumer surplus bar
        surplus_bar = Cube(
            side_length=1,
            color=GREEN_A,
            opacity=0.85,
            shading=(0.2, 0.6, 0.2)
        )
        # Make it bar-shaped: wide, medium height, thin
        surplus_bar.stretch(2.5, 0)   # Stretch along x-axis
        surplus_bar.stretch(0.4, 1)   # Compress along y-axis  
        surplus_bar.stretch(0.15, 2)  # Make thin along z-axis
        surplus_bar.shift(OUT * 1.2)  # Float above person
        
        # Create surplus label
        surplus_label = Text("Consumer\nSurplus", font_size=18, color=WHITE)
        surplus_label.rotate(PI/2, RIGHT)  # Face upward
        surplus_label.move_to(surplus_bar)
        surplus_label.shift(OUT * 0.5)
        
        # Animate everything appearing
        self.play(Create(plane))
        self.play(
            FadeIn(person),
            Write(name_label),
            run_time=1.5
        )
        self.play(
            FadeIn(surplus_bar, shift=OUT * 0.5),
            Write(surplus_label),
            run_time=2
        )
        
        # Add a subtle pulse to the surplus bar
        self.play(
            surplus_bar.animate.scale(1.05).set_color(GREEN_B),
            rate_func=there_and_back,
            run_time=1.5
        )
        
        # Start ambient camera rotation
        self.begin_ambient_camera_rotation(rate=0.08)
        
        # Let the scene rotate for a good viewing experience
        self.wait(10)
        
        # Optional: Add coordinate axes for reference (subtle)
        axes = ThreeDAxes(
            x_range=(-3, 3, 1),
            y_range=(-3, 3, 1), 
            z_range=(0, 2, 0.5),
            axis_config={
                "stroke_width": 1.5,
                "include_ticks": False,
                "include_tip": True,
                "tip_length": 0.2
            }
        )
        axes.set_opacity(0.4)
        self.play(Create(axes), run_time=2)
        
        # Continue rotation with axes
        self.wait(5)
        
        # Stop rotation for final static view
        self.stop_ambient_camera_rotation()
        
        # Move to a nice final viewing angle
        self.set_camera_orientation(phi=60 * DEGREES, theta=-30 * DEGREES)
        self.wait(2)
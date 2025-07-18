from manim import *

class ConsumerSurplus3D(ThreeDScene):
    def construct(self):
        # Set up camera orientation
        self.set_camera_orientation(phi=70 * DEGREES, theta=-45 * DEGREES)
        
        # Create a dark grey square plane at the origin
        plane = Square3D(
            side_length=10,
            color=GREY_D,
            opacity=1,
            shading=(0.1, 0.3, 0.1)
        )
        self.play(Create(plane))
        
        # Create a small disk representing a person
        person = Disk3D(
            radius=0.3,
            color=BLUE_C,
            opacity=1.0
        )
        # Position slightly above the plane to avoid z-fighting
        person.shift(OUT * 0.01)
        
        # Create label for the person
        person_label = Text3D("Maxine", font_size=20, color=YELLOW)
        person_label.rotate(PI/2, RIGHT)  # Rotate to face up
        person_label.next_to(person, OUT)

        circle = Circle()
        
        # Add person first
        self.play(FadeIn(person), FadeIn(circle))
        
        # Add person label without depth test to maintain visibility
        self.play(Write(person_label))
        
        # Create a bar representing consumer surplus
        # Using a thin rectangular prism (flattened cube)
        surplus_bar = Cube(
            side_length=1,
            color=GREEN_B,
            opacity=0.9,
            shading=(0.2, 0.5, 0.2)
        )
        # Scale to make it bar-shaped
        surplus_bar.scale([0.1, 0.1, 1])  # Wide, short height, thin depth
        # Position above the person with some margin
        surplus_bar.shift(OUT)  # Float 1.5 units above the plane
        

        # Animate the surplus bar appearing
        self.play(
            FadeIn(surplus_bar),
            person_label.animate.move_to(surplus_bar.get_center() + OUT)  # Position above the bar
            )

        # zoom to Maxine
        
        
        # Add some visual interest - make the bar pulse slightly
        self.play(
            surplus_bar.animate.scale(1.1).set_color(GREEN_A),
            rate_func=there_and_back,
            run_time=1
        )
        
        # Start slow camera rotation around the scene
        self.begin_ambient_camera_rotation(rate=1)
        
        # Optional: Add axes for reference
        axes = ThreeDAxes(
            x_range=(-4, 4, 1),
            y_range=(-4, 4, 1),
            z_range=(-1, 3, 1),
            axis_config={"stroke_width": 2}
        )
        axes.set_opacity(0.3)
        self.play(Create(axes), run_time=2)
        
        # Stop rotation and hold final view
        self.stop_ambient_camera_rotation()
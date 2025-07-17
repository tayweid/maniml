from manim import *

class TestTextFinal(ThreeDScene):
    """Final test of text depth rendering."""
    
    def construct(self):
        self.set_camera_orientation(phi=70 * DEGREES, theta=-45 * DEGREES)
        
        # Plane in the middle
        plane = Square3D(side_length=6, color=GREY_D, opacity=0.8)
        
        # Text that should be in front
        text_front = Text("In Front", color=GREEN, font_size=35)
        text_front.shift(OUT * 1.5)
        
        # Text that should be behind
        text_behind = Text("Behind", color=RED, font_size=35)
        text_behind.shift(IN * 1.5)
        
        # Text that intersects the plane
        text_middle = Text("Intersect", color=BLUE, font_size=35)
        text_middle.shift(OUT * 0.01)  # Just barely in front
        
        # Add everything
        self.play(
            Create(plane),
            Write(text_front),
            Write(text_behind),
            Write(text_middle)
        )
        
        # Add informative labels
        label = Text("Green: In Front | Blue: Intersecting | Red: Behind", font_size=18)
        label.to_edge(UP)
        self.add(label)
        
        # Rotate to observe depth behavior
        self.begin_ambient_camera_rotation(rate=0.1)
        self.wait(10)
        self.stop_ambient_camera_rotation()
        
        # Move camera to see from different angle
        self.play(
            self.frame.animate.set_phi(45 * DEGREES).set_theta(-90 * DEGREES)
        )
        self.wait(3)
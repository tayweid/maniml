from manim import *

class ConsumerSurplusFixed(ThreeDScene):
    """Test the consumer surplus example with our depth test fix."""
    
    def construct(self):
        # Set up 3D view
        self.set_camera_orientation(phi=70 * DEGREES, theta=-45 * DEGREES)
        
        # Create a dark grey plane
        plane = Square3D(side_length=4, color=GREY_D, opacity=0.9)
        self.add(plane)
        
        # Person (Maxine) - small blue disk
        person = Disk3D(radius=0.2, color=BLUE)
        person.shift(OUT * 0.02)  # Slightly above plane
        
        # Name text - should now render properly with depth
        name = Text("Maxine", font_size=20, color=WHITE)
        name.rotate(PI/2, RIGHT)
        name.next_to(person, DOWN * 0.5)
        name.shift(OUT * 0.1)  # Position above plane
        
        # Consumer surplus bar
        bar = Cube(color=GREEN)
        bar.scale([1.5, 0.3, 0.1])
        bar.shift(OUT * 1.0)
        
        # Bar label
        bar_label = Text("Consumer Surplus", font_size=18, color=WHITE)
        bar_label.rotate(PI/2, RIGHT)
        bar_label.move_to(bar.get_center() + OUT * 0.5)
        
        # Animate everything
        self.play(FadeIn(person), Write(name))
        self.play(
            FadeIn(bar, shift=OUT * 0.3),
            Write(bar_label)
        )
        
        # Rotation to verify depth works
        self.begin_ambient_camera_rotation(rate=0.1)
        self.wait(8)
        self.stop_ambient_camera_rotation()
        self.wait()


class SimpleTextDepthTest(ThreeDScene):
    """Simple test to verify text depth works."""
    
    def construct(self):
        self.set_camera_orientation(phi=70 * DEGREES, theta=-45 * DEGREES)
        
        # Plane in the middle
        plane = Square3D(side_length=3, color=GREY_D, opacity=0.8)
        
        # Text in front
        text_front = Text("Front", color=GREEN, font_size=30)
        text_front.shift(OUT * 1)
        
        # Text behind
        text_behind = Text("Behind", color=RED, font_size=30)
        text_behind.shift(IN * 1)
        
        # Text intersecting
        text_middle = Text("Middle", color=BLUE, font_size=30)
        text_middle.shift(OUT * 0.01)  # Just barely in front
        
        # Add all
        self.add(plane)
        self.add(text_front, text_behind, text_middle)
        
        # Rotate to see depth
        self.begin_ambient_camera_rotation(rate=0.15)
        self.wait(10)
        self.stop_ambient_camera_rotation()


if __name__ == "__main__":
    # Run with:
    # python -m manim test_consumer_surplus_fixed.py ConsumerSurplusFixed -ql
    # python -m manim test_consumer_surplus_fixed.py SimpleTextDepthTest -ql
    pass
from manim import *

class TestCircleOverlap(ThreeDScene):
    def construct(self):
        # Set up camera
        self.set_camera_orientation(phi=45 * DEGREES, theta=-45 * DEGREES)
        
        # Create three overlapping circles at different depths
        # They overlap in a chain: red overlaps green, green overlaps blue
        
        # Red circle in front (z=1)
        circle_red = Circle(radius=1.5, color=RED, fill_opacity=0.8)
        circle_red.shift(LEFT * 1 + UP * 0.5 + OUT * 1)
        
        # Green circle in middle (z=0)
        circle_green = Circle(radius=1.5, color=GREEN, fill_opacity=0.8)
        circle_green.shift(ORIGIN)
        
        # Blue circle behind (z=-1)
        circle_blue = Circle(radius=1.5, color=BLUE, fill_opacity=0.8)
        circle_blue.shift(RIGHT * 1 + DOWN * 0.5 + OUT * -1)
        
        # Add objects
        self.add(circle_red)
        self.add(circle_green)
        self.add(circle_blue)
        
        # Add labels to identify them
        self.add(Text("Red (front)", color=RED).shift(UP * 3))
        self.add(Text("Green (middle)", color=GREEN).shift(UP * 2.5))
        self.add(Text("Blue (back)", color=BLUE).shift(UP * 2))
        
        # Rotate slowly to show depth issues
        self.play(
            Rotate(VGroup(circle_red, circle_green, circle_blue), 
                   angle=2*PI, 
                   axis=UP,
                   run_time=8)
        )
        self.wait()
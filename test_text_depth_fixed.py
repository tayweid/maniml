from manim import *

class TestTextDepthFixed(ThreeDScene):
    """Test if text depth rendering is fixed."""
    
    def construct(self):
        self.set_camera_orientation(phi=70 * DEGREES, theta=-45 * DEGREES)
        
        # Plane in the middle
        plane = Square3D(side_length=6, color=GREY_D, opacity=0.8)
        
        # Text in front (should be fully visible)
        text_front = Text("Front", color=GREEN, font_size=40)
        text_front.shift(OUT * 1.5)
        
        # Text behind (should be hidden by plane)
        text_behind = Text("Behind", color=RED, font_size=40)
        text_behind.shift(IN * 1.5)
        
        # Text partially intersecting
        text_middle = Text("Middle", color=BLUE, font_size=40)
        text_middle.shift(OUT * 0.1)
        
        # Add circle for comparison
        circle = Circle(color=YELLOW, radius=0.5)
        circle.shift(RIGHT * 3 + OUT * 1)
        
        # Add everything with animations
        self.play(
            Create(plane),
            Write(text_front),
            Write(text_behind),
            Write(text_middle),
            Create(circle)
        )
        
        # Label
        label = Text("Testing Text Depth - Green:Front, Blue:Middle, Red:Behind", font_size=16)
        label.to_edge(UP)
        self.add(label)
        
        # Rotate to verify depth
        self.begin_ambient_camera_rotation(rate=0.1)
        self.wait(8)
        self.stop_ambient_camera_rotation()
        
        # Move camera for different perspective
        self.play(
            self.frame.animate.set_phi(30 * DEGREES).set_theta(-135 * DEGREES)
        )
        self.wait(3)


class DebugTextDepthFixed(ThreeDScene):
    """Debug to see if depth test is being applied."""
    
    def construct(self):
        self.set_camera_orientation(phi=70 * DEGREES, theta=-45 * DEGREES)
        
        # Add plane first
        plane = Square3D(side_length=4, color=GREY_D, opacity=0.8)
        self.play(Create(plane))
        
        # Create text
        text = Text("TEST", color=WHITE, font_size=50)
        text.shift(OUT * 1)
        
        # Print depth test status before adding
        print("\n=== BEFORE ADDING TO SCENE ===")
        print(f"Text depth_test: {text.depth_test}")
        for i, mob in enumerate(text.get_family()):
            print(f"  Family {i}: {type(mob).__name__}, depth_test={mob.depth_test}")
        
        # Add to scene (should apply depth test)
        self.add(text)
        
        # Print after adding
        print("\n=== AFTER ADDING TO SCENE ===")
        print(f"Text depth_test: {text.depth_test}")
        for i, mob in enumerate(text.get_family()):
            print(f"  Family {i}: {type(mob).__name__}, depth_test={mob.depth_test}")
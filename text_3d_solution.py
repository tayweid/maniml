from manim import *

class Text3DSolution(ThreeDScene):
    """
    The definitive solution to text rendering in 3D scenes.
    
    The core issue: VMobject fill is rendered to a separate framebuffer
    and composited back, which can cause depth ordering issues with 3D objects.
    """
    
    def construct(self):
        self.set_camera_orientation(phi=70 * DEGREES, theta=-45 * DEGREES)
        
        # Create grey plane
        plane = Square3D(side_length=5, color=GREY_D, opacity=0.9)
        self.add(plane)
        
        # PROBLEM: Standard text - fill renders behind plane
        problem_text = Text("PROBLEM: Fill Behind", font_size=18, color=WHITE)
        problem_text.rotate(PI/2, RIGHT)
        problem_text.shift(LEFT * 2 + OUT * 0.05)
        self.add(problem_text)
        
        # SOLUTION 1: Initialize with stroke_behind=True
        # This doesn't fix the depth issue but can help with visibility
        solution1 = Text("Solution 1:\nstroke_behind", 
                        font_size=16, 
                        color=WHITE,
                        stroke_width=4,
                        stroke_color=BLACK)
        # Manually set stroke_behind after creation
        solution1.stroke_behind = True
        solution1.rotate(PI/2, RIGHT)
        solution1.shift(LEFT * 0.5 + OUT * 0.1)
        self.add(solution1)
        
        # SOLUTION 2: Position text significantly above plane
        solution2 = Text("Solution 2:\nHigher Position", 
                        font_size=16, 
                        color=WHITE,
                        stroke_width=3,
                        stroke_color=BLACK)
        solution2.rotate(PI/2, RIGHT)
        solution2.shift(RIGHT * 0.5 + OUT * 0.5)  # Much higher
        self.add(solution2)
        
        # SOLUTION 3: Use a 3D background object
        # This is the most reliable solution
        text_bg = Cube(color=BLACK, opacity=0.95)
        text_bg.scale([1.5, 0.5, 0.02])  # Thin plate
        text_bg.shift(RIGHT * 2 + OUT * 0.1)
        
        solution3 = Text("Solution 3:\n3D Background", 
                        font_size=16, 
                        color=WHITE)
        solution3.rotate(PI/2, RIGHT)
        solution3.move_to(text_bg.get_center() + OUT * 0.015)
        
        self.add(text_bg, solution3)
        
        # Add evaluation labels
        labels = [
            ("BAD", LEFT * 2, RED),
            ("OKAY", LEFT * 0.5, YELLOW),
            ("BETTER", RIGHT * 0.5, YELLOW),
            ("BEST", RIGHT * 2, GREEN)
        ]
        
        for text, pos, color in labels:
            label = Text(text, font_size=14, color=color)
            label.shift(pos + DOWN * 2)
            label.fix_in_frame()
            self.add(label)
        
        self.begin_ambient_camera_rotation(rate=0.1)
        self.wait(10)
        self.stop_ambient_camera_rotation()


# Create a convenient Text3D class that automatically handles the depth issue
class Text3D(VGroup):
    """
    A Text object designed for 3D scenes that automatically creates
    a background to ensure visibility.
    """
    def __init__(
        self,
        text: str,
        font_size: int = 20,
        color: ManimColor = WHITE,
        bg_color: ManimColor = BLACK,
        bg_opacity: float = 0.9,
        bg_buff: float = 0.1,
        **kwargs
    ):
        # Extract position if provided
        position = kwargs.pop('position', None)
        
        # Create the text
        self.text = Text(text, font_size=font_size, color=color, **kwargs)
        
        # Create background slightly larger than text
        width = self.text.width + bg_buff * 2
        height = self.text.height + bg_buff * 2
        
        # Use a thin 3D rectangle as background
        self.background = Cube(color=bg_color, opacity=bg_opacity)
        self.background.scale([width, height, 0.02])
        
        # Position text slightly in front of background
        self.text.move_to(self.background.get_center())
        self.text.shift(OUT * 0.015)
        
        # Initialize VGroup with both elements
        super().__init__(self.background, self.text)
        
        # Apply position if provided
        if position is not None:
            self.move_to(position)
    
    def rotate(self, angle, axis=OUT, **kwargs):
        """Override rotate to handle both background and text"""
        super().rotate(angle, axis, **kwargs)
        return self


class ConsumerSurplusFinal(ThreeDScene):
    """Final solution using the Text3D class"""
    
    def construct(self):
        self.set_camera_orientation(phi=70 * DEGREES, theta=-45 * DEGREES)
        
        # Dark grey plane
        plane = Square3D(side_length=4, color=GREY_D, opacity=0.9)
        self.add(plane)
        
        # Person (Maxine) - small blue disk
        person = Disk3D(radius=0.2, color=BLUE)
        person.shift(OUT * 0.02)
        
        # Use Text3D for automatic depth handling
        name = Text3D("Maxine", font_size=20)
        name.rotate(PI/2, RIGHT)
        name.next_to(person, DOWN * 0.5)
        name.shift(OUT * 0.1)
        
        # Consumer surplus bar
        bar = Cube(color=GREEN)
        bar.scale([1.5, 0.3, 0.1])
        bar.shift(OUT * 1.0)
        
        # Bar label using Text3D
        bar_label = Text3D("Consumer Surplus", font_size=18)
        bar_label.rotate(PI/2, RIGHT)
        bar_label.move_to(bar.get_center() + OUT * 0.5)
        
        # Animate
        self.play(FadeIn(person), FadeIn(name))
        self.play(FadeIn(bar, shift=OUT * 0.3), FadeIn(bar_label))
        
        # Rotation
        self.begin_ambient_camera_rotation(rate=0.1)
        self.wait(8)
        self.stop_ambient_camera_rotation()
        self.wait()


class MinimalFix(ThreeDScene):
    """The absolute minimal fix for your existing code"""
    
    def construct(self):
        self.set_camera_orientation(phi=70 * DEGREES, theta=-45 * DEGREES)
        
        plane = Square3D(side_length=4, color=GREY_D, opacity=0.9)
        self.add(plane)
        
        # The key fix: Position text much higher above the plane
        # Change from OUT * 0.1 to OUT * 0.5 or more
        text = Text("Maxine", color=WHITE)
        text.rotate(PI/2, RIGHT)
        text.shift(OUT * 0.5)  # This is the key - needs to be much higher!
        
        self.add(text)
        self.wait()
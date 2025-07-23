from manim import *

class TestFinalStroke(ThreeDScene):
    def construct(self):
        # Set up 3D view
        self.set_camera_orientation(phi=70 * DEGREES, theta=-45 * DEGREES)
        
        # Create various shapes with default settings
        # All should now have flat_stroke=True and scale_stroke_with_zoom=True by default
        
        circle = Circle(
            radius=1.5, 
            fill_opacity=0.8, 
            fill_color=RED, 
            stroke_color=WHITE,
            stroke_width=8
        )
        circle.shift(LEFT * 3)
        
        square = Square(
            side_length=2,
            fill_opacity=0.8,
            fill_color=BLUE,
            stroke_color=YELLOW,
            stroke_width=8
        )
        
        triangle = RegularPolygon(n=3,
            fill_opacity=0.8,
            fill_color=GREEN,
            stroke_color=WHITE,
            stroke_width=8
        )
        triangle.scale(1.5)
        triangle.shift(RIGHT * 3)
        
        # Add labels
        label = Text("With improved defaults:\n- flat_stroke=True\n- scale_stroke_with_zoom=True\n- depth offset in shader", 
                    font_size=20)
        label.to_edge(DOWN)
        label.fix_in_frame()
        
        self.add(circle, square, triangle, label)
        
        # Animate to show no z-fighting and proper stroke scaling
        self.wait(1)
        
        # Zoom in to test stroke scaling
        self.play(
            self.camera.frame.animate.scale(0.5).move_to(square),
            run_time=2
        )
        self.wait(1)
        
        # Rotate to test z-fighting
        self.begin_ambient_camera_rotation(rate=0.3)
        self.wait(4)
        self.stop_ambient_camera_rotation()
        
        # Zoom back out
        self.play(
            self.camera.frame.animate.scale(2).move_to(ORIGIN),
            run_time=2
        )
        self.wait(1)
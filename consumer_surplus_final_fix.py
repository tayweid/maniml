from manim import *

class ConsumerSurplusFinalFix(ThreeDScene):
    """The actual fix for text rendering in 3D scenes"""
    def construct(self):
        # Set camera angle
        self.set_camera_orientation(phi=70 * DEGREES, theta=-45 * DEGREES)
        
        # Dark grey plane
        plane = Square3D(side_length=4, color=GREY_D, opacity=0.9)
        self.add(plane)
        
        # Person (Maxine) - small blue disk
        person = Disk3D(radius=0.2, color=BLUE)
        person.shift(OUT * 0.01)
        
        # THE REAL FIX: Text needs stroke for visibility against grey backgrounds
        # This is not a depth testing issue - it's a contrast issue!
        name = Text("Maxine", 
                   font_size=20, 
                   color=WHITE,
                   stroke_width=3,  # This is the key!
                   stroke_color=BLACK)  # Black stroke provides contrast
        name.rotate(PI/2, RIGHT)  # Face upward
        name.next_to(person, DOWN * 0.5)
        name.shift(OUT * 0.1)  # Position above plane
        
        # Consumer surplus bar
        bar = Cube(color=GREEN)
        bar.scale([1.5, 0.3, 0.1])  # Bar shape
        bar.shift(OUT * 1.0)
        
        # Bar label with proper contrast
        bar_label = Text("Consumer Surplus", 
                        font_size=18,
                        color=WHITE,
                        stroke_width=3,
                        stroke_color=BLACK)
        bar_label.rotate(PI/2, RIGHT)
        bar_label.move_to(bar.get_center() + OUT * 0.5)
        
        # Animate
        self.play(FadeIn(person), Write(name))
        self.play(FadeIn(bar, shift=OUT * 0.3), Write(bar_label))
        
        # Rotate the scene
        self.begin_ambient_camera_rotation(rate=0.1)
        self.wait(8)
        self.stop_ambient_camera_rotation()
        self.wait()


class TextRenderingSolution(Scene):
    """Explanation of the text rendering issue and solution"""
    def construct(self):
        title = Text("Text Rendering in 3D Scenes", font_size=32)
        title.to_edge(UP)
        self.play(Write(title))
        
        # The problem
        problem = Text("Problem: White text on grey background has poor contrast",
                      font_size=20, color=RED)
        problem.next_to(title, DOWN, buff=0.5)
        self.play(Write(problem))
        
        # Show the issue
        grey_bg = Rectangle(width=4, height=1, color=GREY_D, fill_opacity=0.9)
        grey_bg.next_to(problem, DOWN, buff=0.5)
        
        bad_text = Text("Hard to see", color=WHITE, font_size=18)
        bad_text.move_to(grey_bg)
        
        self.play(FadeIn(grey_bg), Write(bad_text))
        self.wait()
        
        # The solution
        solution = Text("Solution: Add stroke (outline) to text",
                       font_size=20, color=GREEN)
        solution.next_to(grey_bg, DOWN, buff=0.5)
        self.play(Write(solution))
        
        # Show the fix
        good_bg = Rectangle(width=4, height=1, color=GREY_D, fill_opacity=0.9)
        good_bg.next_to(solution, DOWN, buff=0.5)
        
        good_text = Text("Easy to see", color=WHITE, font_size=18,
                        stroke_width=3, stroke_color=BLACK)
        good_text.move_to(good_bg)
        
        self.play(FadeIn(good_bg), Write(good_text))
        
        # Code example
        code = Text("stroke_width=3, stroke_color=BLACK", 
                   font_size=16, font="monospace", color=YELLOW)
        code.next_to(good_bg, DOWN, buff=0.5)
        self.play(Write(code))
        
        self.wait(2)
from manim import *

class ConsumerSurplusSimple(ThreeDScene):
    def construct(self):
        # Set camera angle
        self.set_camera_orientation(phi=70 * DEGREES, theta=-45 * DEGREES)
        
        # Dark grey plane
        plane = Square3D(side_length=4, color=GREY_D, opacity=0.9)
        self.add(plane)
        
        # Person (Maxine) - small blue disk
        person = Disk3D(radius=0.2, color=BLUE)
        person.shift(OUT * 0.01)
        
        # Name label - proper 3D text rendering
        name = Text("Maxine", font_size=20, color=WHITE,
                   stroke_width=3, stroke_color=BLACK)
        name.rotate(PI/2, RIGHT)  # Face upward
        name.next_to(person, DOWN * 0.5)
        name.shift(OUT * 0.1)  # Position above plane
        # Apply depth test with anti-aliasing disabled for sharp rendering
        name.apply_depth_test(anti_alias_width=0)
        name.z_index = 1  # Render after plane
        
        # Consumer surplus bar - green floating bar
        bar = Cube(color=GREEN)
        bar.scale([1.5, 0.3, 0.1])  # Make it bar-shaped
        bar.shift(OUT * 1.0)  # Float above
        
        # Animate appearance
        self.play(FadeIn(person), Write(name))
        self.play(FadeIn(bar, shift=OUT * 0.3))
        
        # FIX: Deactivate depth test on text after adding to restore visibility
        name.deactivate_depth_test()
        
        # Rotate the scene
        self.begin_ambient_camera_rotation(rate=0.1)
        self.wait(8)
        self.stop_ambient_camera_rotation()
        self.wait()
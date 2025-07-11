#!/usr/bin/env python3
"""Test Broadcast animation."""

from manim import *

class TestBroadcast(Scene):
    def construct(self):
        # Test with circle (stroke only)
        mob = Circle(radius=2, color=TEAL_A, stroke_width=8)
        self.play(Broadcast(mob))
        self.wait()
        
        # Test with filled square
        square = Square(side_length=3, color=RED, fill_opacity=0.7)
        self.play(Broadcast(square, focal_point=RIGHT*2))
        self.wait()
        
        # Test with text
        text = Text("PING!", font_size=72, color=YELLOW)
        self.play(Broadcast(
            text, 
            n_mobs=8, 
            lag_ratio=0.1,
            run_time=2
        ))
        self.wait()

class TestBroadcastVariations(Scene):
    def construct(self):
        # Multiple broadcasts from different points
        dot1 = Dot(LEFT * 3, color=BLUE)
        dot2 = Dot(RIGHT * 3, color=GREEN)
        dot3 = Dot(UP * 2, color=RED)
        
        self.add(dot1, dot2, dot3)
        
        # Create rings from each dot
        ring = Circle(radius=1, stroke_width=4)
        
        self.play(
            Broadcast(ring.copy().set_color(BLUE), focal_point=dot1.get_center(), n_mobs=3),
            Broadcast(ring.copy().set_color(GREEN), focal_point=dot2.get_center(), n_mobs=3),
            Broadcast(ring.copy().set_color(RED), focal_point=dot3.get_center(), n_mobs=3),
            run_time=2
        )
        self.wait()

class TestBroadcastWithInitialWidth(Scene):
    def construct(self):
        # Test with initial width
        star = Star(outer_radius=2, color=PURPLE_A, fill_opacity=0.8)
        
        self.play(Broadcast(
            star,
            initial_width=0.5,  # Start from small size instead of 0
            n_mobs=6,
            run_time=3
        ))
        self.wait()

if __name__ == "__main__":
    from manim.renderer.opengl.window import Window
    window = Window()
    scene = TestBroadcast(window=window)
    scene.run()
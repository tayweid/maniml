#!/usr/bin/env python3
"""Test showing only intersection of two shapes."""

from manim import *

class TestIntersectionOnly(Scene):
    def construct(self):
        # Create two overlapping circles
        c1 = Circle(radius=1.5, color=RED, fill_opacity=0.3, stroke_width=3)
        c1.shift(LEFT * 0.8)
        
        c2 = Circle(radius=1.5, color=BLUE, fill_opacity=0.3, stroke_width=3)
        c2.shift(RIGHT * 0.8)
        
        # Show the original circles with low opacity
        self.add(c1, c2)
        self.add(Text("Two Overlapping Circles", font_size=24).shift(UP * 3))
        
        # Create and show ONLY the intersection
        intersection = Intersection(c1, c2, color=PURPLE, fill_opacity=0.9, stroke_width=2)
        self.add(intersection)
        self.add(Text("Intersection Only", font_size=20, color=PURPLE).shift(DOWN * 3))
        
        self.wait(3)

class TestIntersectionAnimated(Scene):
    def construct(self):
        # Start with two separate circles
        c1 = Circle(radius=1.2, color=RED, fill_opacity=0.5, stroke_width=4)
        c2 = Circle(radius=1.2, color=BLUE, fill_opacity=0.5, stroke_width=4)
        
        c1.shift(LEFT * 3)
        c2.shift(RIGHT * 3)
        
        self.play(Create(c1), Create(c2))
        self.wait()
        
        # Move them together
        self.play(
            c1.animate.shift(RIGHT * 2.2),
            c2.animate.shift(LEFT * 2.2)
        )
        self.wait()
        
        # Show ONLY the intersection area
        intersection = Intersection(c1, c2, color=GREEN, fill_opacity=1, stroke_width=0)
        
        # Fade the original circles and show intersection
        self.play(
            c1.animate.set_opacity(0.2),
            c2.animate.set_opacity(0.2),
            FadeIn(intersection)
        )
        
        label = Text("Intersection Area", font_size=24, color=GREEN)
        label.next_to(intersection, DOWN, buff=0.5)
        self.play(Write(label))
        
        self.wait(3)

class TestNoIntersection(Scene):
    def construct(self):
        # Test case where shapes don't overlap
        c1 = Circle(radius=1, color=RED, fill_opacity=0.5)
        c2 = Circle(radius=1, color=BLUE, fill_opacity=0.5)
        
        c1.shift(LEFT * 3)
        c2.shift(RIGHT * 3)
        
        self.add(c1, c2)
        self.add(Text("Non-overlapping Circles", font_size=24).shift(UP * 3))
        
        # Intersection should be empty
        intersection = Intersection(c1, c2, color=PURPLE, fill_opacity=0.9)
        self.add(intersection)  # Should show nothing
        
        self.add(Text("Empty Intersection", font_size=20, color=GRAY).shift(DOWN * 3))
        
        self.wait(2)

class TestVariousIntersections(Scene):
    def construct(self):
        # Different amounts of overlap
        examples = [
            ("Large Overlap", LEFT * 0.3, RIGHT * 0.3),
            ("Medium Overlap", LEFT * 0.8, RIGHT * 0.8),
            ("Small Overlap", LEFT * 1.3, RIGHT * 1.3),
        ]
        
        for i, (title, shift1, shift2) in enumerate(examples):
            y_pos = 2 - i * 2
            
            # Create circles
            c1 = Circle(radius=0.8, color=RED, fill_opacity=0.3, stroke_width=2)
            c2 = Circle(radius=0.8, color=BLUE, fill_opacity=0.3, stroke_width=2)
            
            c1.shift(shift1 + y_pos * UP)
            c2.shift(shift2 + y_pos * UP)
            
            # Add circles
            self.add(c1, c2)
            
            # Add intersection
            intersection = Intersection(c1, c2, color=PURPLE, fill_opacity=0.8)
            self.add(intersection)
            
            # Add label
            self.add(Text(title, font_size=18).shift((y_pos * UP) + LEFT * 3))
        
        self.wait(3)

if __name__ == "__main__":
    from manim.renderer.opengl.window import Window
    window = Window()
    scene = TestIntersectionOnly(window=window)
    scene.run()
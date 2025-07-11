#!/usr/bin/env python3
"""Test boolean operations."""

from manim import *

class TestBooleanOps(Scene):
    def construct(self):
        # Create two shapes to combine
        sq = Square(side_length=2, color=RED, fill_opacity=0.8)
        sq.shift(LEFT * 0.5)
        
        cr = Circle(radius=1.2, color=BLUE, fill_opacity=0.8)
        cr.shift(RIGHT * 0.5)
        
        # Show original shapes
        self.add(sq.copy().shift(UP * 3), cr.copy().shift(UP * 3))
        self.add(Text("Original shapes", font_size=20).shift(UP * 4))
        
        # Union (combined region)
        union = Union(sq, cr, color=GREEN, fill_opacity=1)
        union.shift(LEFT * 4)
        self.add(union)
        self.add(Text("Union", font_size=20).next_to(union, DOWN))
        
        # Intersection (overlap region)
        intersection = Intersection(sq, cr, color=PURPLE, fill_opacity=1)
        intersection.shift(LEFT * 1.5 + DOWN * 0.5)
        self.add(intersection)
        self.add(Text("Intersection", font_size=20).next_to(intersection, DOWN))
        
        # Difference (sq minus cr)
        difference = Difference(sq, cr, color=ORANGE, fill_opacity=1)
        difference.shift(RIGHT * 1.5)
        self.add(difference)
        self.add(Text("Difference", font_size=20).next_to(difference, DOWN))
        
        # Exclusion (XOR - symmetric difference)
        exclusion = Exclusion(sq, cr, color=TEAL, fill_opacity=1)
        exclusion.shift(RIGHT * 4)
        self.add(exclusion)
        self.add(Text("Exclusion", font_size=20).next_to(exclusion, DOWN))
        
        self.wait(2)

class TestUnionMultiple(Scene):
    def construct(self):
        # Test union with multiple shapes
        shapes = [
            Circle(radius=1, color=RED).shift(LEFT),
            Square(side_length=1.5, color=BLUE).shift(RIGHT),
            Triangle(color=GREEN).shift(UP)
        ]
        
        # Show original shapes
        for shape in shapes:
            self.add(shape.copy().set_fill(opacity=0.5).shift(UP * 2))
        
        # Create union of all three
        union = Union(*shapes, color=PURPLE, fill_opacity=0.8)
        union.shift(DOWN * 1.5)
        self.add(union)
        self.add(Text("Union of 3 shapes", font_size=24).next_to(union, DOWN))
        
        self.wait(2)

class TestAnimatedBoolean(Scene):
    def construct(self):
        # Animate the creation of boolean operations
        sq = Square(side_length=2, color=RED, fill_opacity=0.7)
        cr = Circle(radius=1.2, color=BLUE, fill_opacity=0.7)
        
        # Start with shapes apart
        sq.shift(LEFT * 2)
        cr.shift(RIGHT * 2)
        
        self.play(Create(sq), Create(cr))
        self.wait()
        
        # Move them together
        self.play(
            sq.animate.shift(RIGHT * 1.5),
            cr.animate.shift(LEFT * 1.5)
        )
        self.wait()
        
        # Show intersection
        intersection = Intersection(sq, cr, color=GREEN, fill_opacity=1)
        self.play(FadeIn(intersection))
        self.wait()
        
        # Transform to union
        union = Union(sq, cr, color=YELLOW, fill_opacity=1)
        self.play(Transform(intersection, union))
        self.wait()

if __name__ == "__main__":
    from manim.renderer.opengl.window import Window
    window = Window()
    scene = TestBooleanOps(window=window)
    scene.run()
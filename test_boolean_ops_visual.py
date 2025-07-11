#!/usr/bin/env python3
"""Visual test of boolean operations with overlapping shapes."""

from manim import *

class TestBooleanOpsVisual(Scene):
    def construct(self):
        # Create overlapping shapes
        sq = Square(side_length=2, color=RED, fill_opacity=0.5, stroke_width=3)
        sq.shift(LEFT * 0.7)
        
        cr = Circle(radius=1.2, color=BLUE, fill_opacity=0.5, stroke_width=3)
        cr.shift(RIGHT * 0.7)
        
        # Show original overlapping shapes at the top
        orig_sq = sq.copy().shift(UP * 2.5)
        orig_cr = cr.copy().shift(UP * 2.5)
        self.add(orig_sq, orig_cr)
        self.add(Text("Original Overlapping Shapes", font_size=24).shift(UP * 3.5))
        
        # Union - should show combined area
        union = Union(sq, cr, color=GREEN, fill_opacity=0.8, stroke_width=0)
        union.shift(LEFT * 4 + DOWN * 0.5)
        self.add(union)
        self.add(Text("Union", font_size=20).next_to(union, DOWN))
        
        # Intersection - should show only overlap
        intersection = Intersection(sq, cr, color=PURPLE, fill_opacity=0.8, stroke_width=0)
        intersection.shift(LEFT * 1.5 + DOWN * 0.5)
        self.add(intersection)
        self.add(Text("Intersection", font_size=20).next_to(intersection, DOWN))
        
        # Difference - square minus circle
        difference = Difference(sq, cr, color=ORANGE, fill_opacity=0.8, stroke_width=0)
        difference.shift(RIGHT * 1.5 + DOWN * 0.5)
        self.add(difference)
        self.add(Text("Difference (A-B)", font_size=20).next_to(difference, DOWN))
        
        # Exclusion - XOR
        exclusion = Exclusion(sq, cr, color=TEAL, fill_opacity=0.8, stroke_width=0)
        exclusion.shift(RIGHT * 4 + DOWN * 0.5)
        self.add(exclusion)
        self.add(Text("Exclusion (XOR)", font_size=20).next_to(exclusion, DOWN))
        
        self.wait(3)

class TestBooleanOpsAnimated(Scene):
    def construct(self):
        # Title
        title = Text("Boolean Operations Demo", font_size=36)
        title.to_edge(UP)
        self.play(Write(title))
        
        # Create shapes that will overlap
        sq = Square(side_length=2, color=RED, fill_opacity=0.7, stroke_width=4)
        cr = Circle(radius=1.2, color=BLUE, fill_opacity=0.7, stroke_width=4)
        
        # Start with shapes separated
        sq.shift(LEFT * 3)
        cr.shift(RIGHT * 3)
        
        self.play(Create(sq), Create(cr))
        self.wait()
        
        # Label them
        label_a = Text("A", font_size=24).next_to(sq, DOWN)
        label_b = Text("B", font_size=24).next_to(cr, DOWN)
        self.play(Write(label_a), Write(label_b))
        
        # Move them together to overlap
        self.play(
            sq.animate.shift(RIGHT * 2.3),
            cr.animate.shift(LEFT * 2.3),
            label_a.animate.shift(RIGHT * 2.3),
            label_b.animate.shift(LEFT * 2.3),
        )
        self.wait()
        
        # Show each boolean operation
        operations = [
            ("Union (A ∪ B)", Union, GREEN),
            ("Intersection (A ∩ B)", Intersection, PURPLE),
            ("Difference (A - B)", Difference, ORANGE),
            ("Exclusion (A ⊕ B)", Exclusion, TEAL),
        ]
        
        for i, (name, op_class, color) in enumerate(operations):
            # Create operation result
            if op_class in [Union, Intersection]:
                result = op_class(sq, cr, color=color, fill_opacity=0.9, stroke_width=0)
            else:
                result = op_class(sq, cr, color=color, fill_opacity=0.9, stroke_width=0)
            
            # Position it below
            result.shift(DOWN * 2.5)
            
            # Show operation name
            op_label = Text(name, font_size=28, color=color)
            op_label.next_to(result, DOWN)
            
            # Animate
            self.play(
                FadeIn(result),
                Write(op_label),
            )
            self.wait(2)
            
            # Fade out before next
            if i < len(operations) - 1:
                self.play(FadeOut(result), FadeOut(op_label))
        
        self.wait(2)

class TestBooleanOpsComplex(Scene):
    def construct(self):
        # Test with more complex overlapping shapes
        shapes = []
        
        # Create three overlapping circles
        c1 = Circle(radius=1, color=RED, fill_opacity=0.6).shift(UP * 0.5)
        c2 = Circle(radius=1, color=GREEN, fill_opacity=0.6).shift(DL * 0.5)
        c3 = Circle(radius=1, color=BLUE, fill_opacity=0.6).shift(DR * 0.5)
        
        shapes = [c1, c2, c3]
        
        # Show original
        for shape in shapes:
            self.add(shape.copy().shift(UP * 2.5))
        self.add(Text("Three Overlapping Circles", font_size=24).shift(UP * 3.5))
        
        # Multiple unions
        union_all = Union(c1, c2, c3, color=PURPLE, fill_opacity=0.8)
        union_all.shift(DOWN * 2)
        self.add(union_all)
        self.add(Text("Union of All Three", font_size=20).next_to(union_all, DOWN))
        
        # Test with different shape types
        rect = Rectangle(width=3, height=1.5, color=YELLOW, fill_opacity=0.6)
        ellipse = Ellipse(width=2.5, height=1, color=PINK, fill_opacity=0.6)
        rect.shift(LEFT * 3)
        ellipse.shift(LEFT * 3)
        
        self.add(rect.copy().shift(LEFT * 0.3))
        self.add(ellipse.copy().shift(RIGHT * 0.3))
        self.add(Text("Rectangle + Ellipse", font_size=20).shift(LEFT * 3 + UP))
        
        # Their intersection
        inter = Intersection(rect, ellipse, color=ORANGE, fill_opacity=0.8)
        inter.shift(LEFT * 3 + DOWN * 2)
        self.add(inter)
        self.add(Text("Intersection", font_size=18).next_to(inter, DOWN))
        
        self.wait(3)

if __name__ == "__main__":
    from manim.renderer.opengl.window import Window
    window = Window()
    scene = TestBooleanOpsVisual(window=window)
    scene.run()
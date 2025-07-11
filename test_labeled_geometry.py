#!/usr/bin/env python3
"""Test labeled geometry objects."""

from manim import *

class TestLabeledGeometry(Scene):
    def construct(self):
        # Test LabeledLine
        line1 = LabeledLine(
            label="Length",
            start=3*LEFT + 2*UP,
            end=3*RIGHT + 2*UP,
            color=BLUE,
        )
        
        # LabeledLine with math label
        line2 = LabeledLine(
            label="d = \\sqrt{x^2 + y^2}",
            label_constructor=MathTex,
            start=3*LEFT + UP,
            end=3*RIGHT + UP,
            label_position=0.7,
            color=GREEN,
        )
        
        # LabeledLine with frame
        line3 = LabeledLine(
            label="10 cm",
            label_frame=True,
            start=3*LEFT,
            end=3*RIGHT,
            label_position=0.3,
            color=RED,
        )
        
        # Test LabeledArrow
        arrow1 = LabeledArrow(
            label="\\vec{v}",
            label_constructor=MathTex,
            start=ORIGIN + DOWN,
            end=2*RIGHT + DOWN,
            color=YELLOW,
        )
        
        arrow2 = LabeledArrow(
            label="Force",
            start=ORIGIN + 2*DOWN,
            end=2*UL + 2*DOWN,
            label_position=0.8,
            color=PURPLE,
        )
        
        # Test LabeledDot
        dot1 = LabeledDot("A", point=3*LEFT + 3*DOWN)
        dot2 = LabeledDot("B", point=ORIGIN + 3*DOWN, label_dir=UR, color=BLUE)
        dot3 = LabeledDot("C", point=3*RIGHT + 3*DOWN, label_dir=DOWN, color=RED)
        
        # Add all elements
        self.add(line1, line2, line3, arrow1, arrow2, dot1, dot2, dot3)
        self.wait(2)

class TestLabeledAnimation(Scene):
    def construct(self):
        # Create labeled points for a triangle
        A = LabeledDot("A", point=2*LEFT + DOWN, color=RED)
        B = LabeledDot("B", point=2*RIGHT + DOWN, color=GREEN)
        C = LabeledDot("C", point=UP, color=BLUE)
        
        # Create labeled sides
        side_AB = LabeledLine(
            label="c",
            start=A.get_center(),
            end=B.get_center(),
            label_constructor=MathTex,
            color=YELLOW,
        )
        
        side_BC = LabeledLine(
            label="a",
            start=B.get_center(),
            end=C.get_center(),
            label_constructor=MathTex,
            color=YELLOW,
        )
        
        side_CA = LabeledLine(
            label="b",
            start=C.get_center(),
            end=A.get_center(),
            label_constructor=MathTex,
            color=YELLOW,
        )
        
        # Animate construction
        self.play(Create(A), Create(B), Create(C))
        self.wait()
        self.play(Create(side_AB), Create(side_BC), Create(side_CA))
        self.wait()
        
        # Add area label
        area_label = MathTex("A = \\frac{1}{2}bh", font_size=36)
        area_label.move_to(ORIGIN)
        self.play(Write(area_label))
        self.wait(2)

class TestPhysicsExample(Scene):
    def construct(self):
        # Create a physics diagram with labeled vectors
        origin = LabeledDot("O", point=ORIGIN, label_dir=DL)
        
        # Velocity vector
        velocity = LabeledArrow(
            label="\\vec{v} = 5\\text{ m/s}",
            label_constructor=MathTex,
            start=ORIGIN,
            end=3*RIGHT,
            color=GREEN,
            label_position=0.5,
        )
        
        # Acceleration vector
        acceleration = LabeledArrow(
            label="\\vec{a} = 2\\text{ m/s}^2",
            label_constructor=MathTex,
            start=ORIGIN,
            end=2*DOWN,
            color=RED,
            label_position=0.6,
        )
        
        # Force vectors
        force1 = LabeledArrow(
            label="F_1 = 10\\text{ N}",
            label_constructor=MathTex,
            start=ORIGIN,
            end=2*UR,
            color=BLUE,
        )
        
        force2 = LabeledArrow(
            label="F_2 = 15\\text{ N}",
            label_constructor=MathTex,
            start=ORIGIN,
            end=3*UL,
            color=PURPLE,
        )
        
        # Title
        title = Text("Free Body Diagram", font_size=36)
        title.shift(3*UP)
        
        # Animate the diagram
        self.play(Write(title))
        self.play(Create(origin))
        self.wait()
        self.play(
            GrowArrow(velocity),
            GrowArrow(acceleration),
            GrowArrow(force1),
            GrowArrow(force2),
            lag_ratio=0.2
        )
        self.wait(2)

if __name__ == "__main__":
    from manim.renderer.opengl.window import Window
    window = Window()
    scene = TestLabeledGeometry(window=window)
    scene.run()
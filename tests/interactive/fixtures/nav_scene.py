from manim import *


class NavScene(Scene):
    def construct(self):
        circle = Circle(color=BLUE).shift(LEFT * 2)
        square = Square(color=RED).shift(RIGHT * 2)
        self.play(Create(circle))
        self.play(Create(square))
        label = Text("checkpoint 3", font_size=36).to_edge(UP)
        self.play(Write(label))
        self.play(circle.animate.shift(RIGHT * 4), square.animate.shift(LEFT * 4))
        self.wait()

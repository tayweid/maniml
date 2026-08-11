from manim import *


class GhostScene(Scene):
    def construct(self):
        squares = [Square(side_length=0.5).shift(RIGHT * i) for i in range(3)]
        group = VGroup(*squares)
        self.add(group)
        for i in range(2):
            # Storing the builders in a variable puts them in the
            # checkpoint namespace; this once broke deepcopy identity
            update_squares = [s.animate.set_fill(BLUE, 1) for s in squares]
            self.play(*update_squares, run_time=0.1)
        self.play(group.animate.to_edge(UP))
        self.wait()

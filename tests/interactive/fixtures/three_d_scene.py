from manim import *


class ThreeDFills(ThreeDScene):
    def construct(self):
        self.set_camera_orientation(phi=75 * DEGREES, theta=20 * DEGREES)
        blue = Square(side_length=3, fill_opacity=1, color=BLUE)
        red = Square(side_length=3, fill_opacity=1, color=RED).rotate(PI / 2, UP)
        sphere = Sphere(radius=0.8, color=GREEN).shift(RIGHT * 3.5)
        self.add(blue, red, sphere)
        self.wait()

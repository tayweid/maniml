from maniml import *


class OrbsScene(ThreeDScene):
    """tests/surface_fixtures.orbs: the B3 and B4 episodes' agents."""
    def construct(self):
        self.set_camera_orientation(phi=60 * DEGREES, theta=-80 * DEGREES)
        colors = (BLUE, RED, GREEN, YELLOW)
        spheres = [Sphere(radius=.23, color=colors[(i + j) % 4], resolution=(16, 10)).move_to([i * .7 - 3, j * .7 - 1.4, .3])
                   for i in range(10) for j in range(5)]
        small = [Sphere(radius=.065, color=colors[i % 4], resolution=(12, 8)).move_to([i * .3 - 3, 2.2, .16])
                 for i in range(20)]
        group = Group(*spheres, *small)
        self.play(FadeIn(group))
        self.play(group.animate.shift(RIGHT * .5))
        self.play(group.animate.shift(LEFT * .5))


class LatticeScene(ThreeDScene):
    """480 small spheres, one colour per column: a 3D scatter of agents."""
    def construct(self):
        self.set_camera_orientation(phi=60 * DEGREES, theta=-80 * DEGREES)
        colors = (BLUE, RED, GREEN, YELLOW)
        spheres = [Sphere(radius=.1, color=colors[(i + j) % 4], resolution=(12, 8)).move_to([i * .3 - 3.6, j * .3 - 2.4, .2])
                   for i in range(24) for j in range(20)]
        group = Group(*spheres)
        self.play(FadeIn(group))
        self.play(group.animate.shift(RIGHT * .3))
        self.play(group.animate.shift(LEFT * .3))


class CobbDouglasScene(ThreeDScene):
    """tests/surface_fixtures.cobb_douglas: F1's utility surface over its axes."""
    def construct(self):
        import numpy as np
        self.set_camera_orientation(phi=75 * DEGREES, theta=180 * DEGREES)
        self.camera.frame.scale(1 / .6)
        plane = Surface(lambda u, v: np.array([u - 5, v - 5, u ** .5 + v ** .5 - 3]), resolution=(10, 10),
                        fill_color="#29ABCA", v_range=[.5, 10], u_range=[.5, 10])
        axes = ThreeDAxes(x_range=(0, 10, 1), y_range=(0, 10, 1), z_range=(0, 1, 1))
        self.play(FadeIn(axes), FadeIn(plane))
        self.play(plane.animate.shift(OUT * .5))
        self.play(plane.animate.shift(IN * .5))


class TranslucentScene(ThreeDScene):
    """tests/surface_fixtures.translucent: a sphere and a torus, partly transparent."""
    def construct(self):
        self.set_camera_orientation(phi=65 * DEGREES, theta=-30 * DEGREES)
        sphere = Sphere(radius=1.2).set_opacity(.5).shift(LEFT * 1.5)
        torus = Torus(r1=1.2, r2=.4, color=GREEN).set_opacity(.6)
        self.play(FadeIn(sphere), FadeIn(torus))
        self.play(sphere.animate.shift(RIGHT * .5))
        self.play(sphere.animate.shift(LEFT * .5))

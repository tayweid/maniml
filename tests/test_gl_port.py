"""Fidelity test for the Stage-2 shader port.

Renders a scene twice at identical state: once through the native
geometry-shader pipeline (camera.get_image()) and once through the
ported instanced pipeline (web/reference_renderer.py consuming the
web/geometry.py payload — the same shader sources the WebGL2 client
compiles). Asserts the images match within a small tolerance.
"""

import unittest

import numpy as np

from maniml.scene.scene import Scene
from maniml.mobject.geometry import Circle, Square, Polygon
from maniml.mobject.svg.text_mobject import Text
from maniml.constants import LEFT, RIGHT, UP, DOWN
from maniml.constants import BLUE, RED, GREEN, YELLOW, WHITE

from maniml.web.geometry import serialize_scene, parse_geometry_message
from maniml.web.reference_renderer import ReferenceRenderer


class PortScene(Scene):
    def construct(self):
        pass


def build_scene():
    scene = PortScene(window=None)
    circle = Circle(color=BLUE, fill_opacity=0.6).shift(LEFT * 3)
    square = Square(color=RED, fill_opacity=1.0).rotate(0.5).shift(RIGHT * 3)
    # Concave polygon: exercises the winding-number fill
    star = Polygon(
        *[
            (np.cos(a), np.sin(a), 0) if i % 2 == 0
            else (0.4 * np.cos(a), 0.4 * np.sin(a), 0)
            for i, a in enumerate(np.linspace(0, 2 * np.pi, 11)[:-1])
        ],
        color=YELLOW, fill_opacity=0.8,
    ).scale(1.5).shift(UP * 2)
    text = Text("port fidelity", color=WHITE).shift(DOWN * 2.5)
    outline = Circle(color=GREEN, fill_opacity=0.0).scale(2)
    scene.add(circle, square, star, text, outline)
    scene.update_frame(dt=0, force_draw=True)  # get_image reads the FBO
    return scene


class GLPortFidelity(unittest.TestCase):
    def test_reference_matches_native(self):
        scene = build_scene()
        native = np.asarray(scene.get_image().convert("RGB"), dtype=np.float64)

        message = serialize_scene(scene)
        header, vertex_bytes = parse_geometry_message(message)
        self.assertEqual(header["unsupported"], [])
        self.assertGreater(len(header["batches"]), 0)

        ported = ReferenceRenderer().render(header, vertex_bytes)
        ported = np.asarray(ported.convert("RGB"), dtype=np.float64)

        self.assertEqual(native.shape, ported.shape)
        diff = np.abs(native - ported)
        mean_diff = diff.mean()
        frac_off = (diff.max(axis=2) > 24).mean()
        self.assertLess(
            mean_diff, 1.5,
            f"mean |diff| {mean_diff:.3f} too high; "
            f"{frac_off * 100:.2f}% of pixels off by >24")
        self.assertLess(
            frac_off, 0.005,
            f"{frac_off * 100:.2f}% of pixels off by >24 "
            f"(mean |diff| {mean_diff:.3f})")

    def test_payload_wellformed(self):
        scene = build_scene()
        header, vertex_bytes = parse_geometry_message(serialize_scene(scene))
        total = sum(b["num_verts"] * 68 for b in header["batches"])
        self.assertEqual(total, len(vertex_bytes))
        for batch in header["batches"]:
            self.assertEqual(batch["num_verts"] % 3, 0)
            self.assertIn("anti_alias_width", batch["uniforms"])
        self.assertEqual(len(header["camera"]["view"]), 16)


if __name__ == "__main__":
    unittest.main()

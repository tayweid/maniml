"""Fidelity test for the Stage-2 shader port.

Renders a scene twice at identical state: once through the native
geometry-shader pipeline (camera.get_image()) and once through the
ported instanced pipeline (web/reference_renderer.py consuming the
web/geometry.py payload — the same shader sources the WebGL2 client
compiles). Asserts the images match within a small tolerance.
"""

import os
import unittest

import numpy as np

from maniml.scene.scene import Scene, ThreeDScene
from maniml.mobject.geometry import Circle, Square, Polygon
from maniml.mobject.svg.text_mobject import Text
from maniml.constants import LEFT, RIGHT, UP, DOWN
from maniml.constants import BLUE, RED, GREEN, YELLOW, WHITE

from maniml.web.geometry import serialize_scene, parse_geometry_message
from maniml.web.reference_renderer import ReferenceRenderer


class PortScene(Scene):
    def construct(self):
        pass


class Port3DScene(ThreeDScene):
    def construct(self):
        pass


def payload_size(header):
    total = 0
    for batch in header["batches"]:
        total += batch["num_verts"] * batch.get("stride", 68)
        if "tri" in batch:
            total += batch["tri"]["vcount"] * 40 + batch["tri"]["icount"] * 4
    return total


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
    # Overlapping translucent fills, adjacent in draw order: their
    # blending is only native-faithful when they accumulate in ONE
    # winding pass (native batching), not per-mobject composites
    overlap_a = Circle(color=GREEN, fill_opacity=0.5).shift(RIGHT * 5 + UP * 2)
    overlap_b = Circle(color=GREEN, fill_opacity=0.5).shift(
        RIGHT * 5.8 + UP * 2)
    scene.add(circle, square, star, text, outline, overlap_a, overlap_b)
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
        self.assertEqual(payload_size(header), len(vertex_bytes))
        for batch in header["batches"]:
            self.assertEqual(batch["num_verts"] % 3, 0)
            self.assertIn("anti_alias_width", batch["uniforms"])
            self.assertLessEqual(batch["stroke_verts"], 64)
        self.assertEqual(len(header["camera"]["view"]), 16)
        # Native-style batching: the whole Text (12 glyphs) plus every
        # same-state shape merges — far fewer batches than submobjects
        self.assertLess(len(header["batches"]), 8)

    def test_reference_matches_native_dotcloud(self):
        from maniml.mobject.types.dot_cloud import DotCloud
        scene = PortScene(window=None)
        xs, ys = np.meshgrid(np.linspace(-4, 4, 9), np.linspace(-2, 2, 5))
        grid_points = np.column_stack(
            [xs.ravel(), ys.ravel(), np.zeros(xs.size)])
        grid = DotCloud(points=grid_points, color=BLUE, radius=0.08)
        glow = DotCloud(points=np.array([[0.0, 2.8, 0.0]]), color=YELLOW,
                        radius=0.6, glow_factor=2.0)
        scene.add(grid, glow)
        scene.update_frame(dt=0, force_draw=True)
        native = np.asarray(scene.get_image().convert("RGB"), dtype=np.float64)

        header, vertex_bytes = parse_geometry_message(serialize_scene(scene))
        self.assertEqual(header["unsupported"], [])
        self.assertTrue(
            any(b["kind"] == "dotcloud" for b in header["batches"]))
        self.assertEqual(payload_size(header), len(vertex_bytes))

        ported = ReferenceRenderer().render(header, vertex_bytes)
        ported = np.asarray(ported.convert("RGB"), dtype=np.float64)
        diff = np.abs(native - ported)
        self.assertLess(diff.mean(), 1.5, f"dots mean |diff| {diff.mean():.3f}")
        self.assertLess((diff.max(axis=2) > 24).mean(), 0.005)

    def test_delta_encoding(self):
        from maniml.web.geometry import GeometryCache
        from maniml.mobject.types.dot_cloud import DotCloud
        scene = PortScene(window=None)
        circle = Circle(color=BLUE, fill_opacity=0.6).shift(LEFT * 3)
        dots = DotCloud(
            points=np.array([[2.0, 0.0, 0.0], [3.0, 1.0, 0.0]]),
            color=YELLOW, radius=0.2)
        scene.add(circle, dots)
        scene.update_frame(dt=0, force_draw=True)

        cache = GeometryCache()

        # Serialize all three messages (and capture the native image)
        # BEFORE creating the reference GL context: two standalone GL
        # contexts can't interleave raw-GL work in one process
        h1, b1 = parse_geometry_message(serialize_scene(scene, cache))
        self.assertTrue(all("offset" in b for b in h1["batches"]))

        # Unchanged scene: every batch is a cached reference, zero bytes
        h2, b2 = parse_geometry_message(serialize_scene(scene, cache))
        self.assertTrue(all(b.get("cached") for b in h2["batches"]))
        self.assertEqual(len(b2), 0)

        # Move the circle: only its batch re-ships, dots stay cached
        circle.shift(RIGHT * 2)
        scene.update_frame(dt=0, force_draw=True)
        native3 = np.asarray(scene.get_image().convert("RGB"), float)
        h3, b3 = parse_geometry_message(serialize_scene(scene, cache))
        self.assertEqual(
            [b["kind"] for b in h3["batches"] if "offset" in b],
            ["vmobject"])
        self.assertEqual(
            [b["kind"] for b in h3["batches"] if b.get("cached")],
            ["dotcloud"])

        renderer = ReferenceRenderer()
        img1 = np.asarray(renderer.render(h1, b1).convert("RGB"), float)
        img2 = np.asarray(renderer.render(h2, b2).convert("RGB"), float)
        self.assertTrue((img1 == img2).all())
        img3 = np.asarray(renderer.render(h3, b3).convert("RGB"), float)
        self.assertLess(np.abs(native3 - img3).mean(), 1.5)

    @staticmethod
    def _test_image_path():
        import tempfile
        from PIL import Image as PILImage
        path = os.path.join(tempfile.gettempdir(), "maniml_gl_port_tex.png")
        if not os.path.exists(path):
            img = PILImage.new("RGB", (64, 64))
            for x in range(64):
                for y in range(64):
                    img.putpixel((x, y), (4 * x, 4 * y, 255 - 2 * x))
            img.save(path)
        return path

    def test_reference_matches_native_image(self):
        from maniml.mobject.types.image_mobject import ImageMobject
        scene = PortScene(window=None)
        image = ImageMobject(self._test_image_path(), height=3.0)
        circle = Circle(color=BLUE, fill_opacity=0.5).shift(RIGHT * 4)
        scene.add(image, circle)
        scene.update_frame(dt=0, force_draw=True)
        native = np.asarray(scene.get_image().convert("RGB"), dtype=np.float64)

        header, vertex_bytes = parse_geometry_message(serialize_scene(scene))
        self.assertEqual(header["unsupported"], [])
        self.assertTrue(any(b["kind"] == "image" for b in header["batches"]))
        self.assertTrue(header["texture_data"])

        ported = ReferenceRenderer().render(header, vertex_bytes)
        ported = np.asarray(ported.convert("RGB"), dtype=np.float64)
        diff = np.abs(native - ported)
        self.assertLess(diff.mean(), 1.5,
                        f"image mean |diff| {diff.mean():.3f}")
        self.assertLess((diff.max(axis=2) > 24).mean(), 0.005)

    def test_reference_matches_native_surfaces(self):
        from maniml.mobject.three_dimensions import Sphere
        from maniml.mobject.types.surface import TexturedSurface
        scene = Port3DScene(window=None)
        scene.set_camera_orientation(phi=60 * np.pi / 180,
                                     theta=20 * np.pi / 180)
        sphere = Sphere(radius=1.4).shift(LEFT * 2.2)
        textured = TexturedSurface(
            Sphere(radius=1.4), self._test_image_path()).shift(RIGHT * 2.2)
        scene.add(sphere, textured)
        scene.update_frame(dt=0, force_draw=True)
        native = np.asarray(scene.get_image().convert("RGB"), dtype=np.float64)

        header, vertex_bytes = parse_geometry_message(serialize_scene(scene))
        self.assertEqual(header["unsupported"], [])
        kinds = {b["kind"] for b in header["batches"]}
        self.assertIn("surface", kinds)
        self.assertIn("texsurface", kinds)

        ported = ReferenceRenderer().render(header, vertex_bytes)
        ported = np.asarray(ported.convert("RGB"), dtype=np.float64)
        diff = np.abs(native - ported)
        self.assertLess(diff.mean(), 2.0,
                        f"surfaces mean |diff| {diff.mean():.3f}")
        self.assertLess((diff.max(axis=2) > 24).mean(), 0.01)

    def test_reference_matches_native_3d(self):
        scene = Port3DScene(window=None)
        scene.set_camera_orientation(phi=70 * np.pi / 180,
                                     theta=30 * np.pi / 180)
        s1 = Square(color=BLUE, fill_opacity=1.0).scale(1.5)
        s2 = Square(color=RED, fill_opacity=1.0).scale(1.5).rotate(
            np.pi / 2, axis=np.array([1.0, 0.0, 0.0]))
        s3 = Circle(color=YELLOW, fill_opacity=0.9).scale(1.2).shift(UP)
        scene.add(s1, s2, s3)  # ThreeDScene.add applies depth test
        scene.update_frame(dt=0, force_draw=True)
        native = np.asarray(scene.get_image().convert("RGB"), dtype=np.float64)

        header, vertex_bytes = parse_geometry_message(serialize_scene(scene))
        self.assertEqual(header["unsupported"], [])
        self.assertEqual(header["samples"], 4)
        self.assertTrue(any("tri" in b for b in header["batches"]))
        self.assertEqual(payload_size(header), len(vertex_bytes))

        ported = ReferenceRenderer().render(header, vertex_bytes)
        ported = np.asarray(ported.convert("RGB"), dtype=np.float64)

        diff = np.abs(native - ported)
        mean_diff = diff.mean()
        frac_off = (diff.max(axis=2) > 24).mean()
        self.assertLess(mean_diff, 2.0,
                        f"3D mean |diff| {mean_diff:.3f} too high; "
                        f"{frac_off * 100:.2f}% pixels off by >24")
        self.assertLess(frac_off, 0.01,
                        f"3D: {frac_off * 100:.2f}% pixels off by >24 "
                        f"(mean {mean_diff:.3f})")


if __name__ == "__main__":
    unittest.main()

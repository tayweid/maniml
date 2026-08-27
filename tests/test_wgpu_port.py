"""Fidelity tests for the canonical client-side WebGPU renderer.

Render a scene natively, serialize it, render the payload with wgpu + the WGSL
shaders, pixel-diff. Covers the whole parity-ledger scope: 2D winding
fills/strokes/Text, clip planes, dot clouds, images, depth-tested 3D
with MSAA, surfaces and textured surfaces.

Thresholds allow Metal's
rasterizer, MSAA resolve, and f16 blending round differently than
OpenGL's at anti-aliased edges.
"""

import os
import unittest

import numpy as np

from maniml.constants import (
    BLUE,
    DOWN,
    GREEN,
    LEFT,
    RED,
    RIGHT,
    UP,
    WHITE,
    YELLOW,
)
from maniml.mobject.geometry import Circle, Dot, Line, Polygon, Square
from maniml.mobject.svg.text_mobject import Text
from maniml.scene.scene import Scene, ThreeDScene
from maniml.web.geometry import parse_geometry_message, serialize_scene

try:
    import wgpu  # noqa: F401

    HAVE_WGPU = True
except ImportError:
    HAVE_WGPU = False


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


def _test_image_path():
    import tempfile
    from PIL import Image as PILImage

    path = os.path.join(tempfile.gettempdir(), "maniml_wgpu_port_tex.png")
    if not os.path.exists(path):
        image = PILImage.new("RGB", (64, 64))
        for x in range(64):
            for y in range(64):
                image.putpixel((x, y), (4 * x, 4 * y, 255 - 2 * x))
        image.save(path)
    return path


def build_3d_scene():
    scene = Port3DScene(window=None)
    scene.set_camera_orientation(phi=70 * np.pi / 180, theta=30 * np.pi / 180)
    first = Square(color=BLUE, fill_opacity=1.0).scale(1.5)
    second = Square(color=RED, fill_opacity=1.0).scale(1.5).rotate(
        np.pi / 2, axis=np.array([1.0, 0.0, 0.0]))
    third = Circle(color=YELLOW, fill_opacity=0.9).scale(1.2).shift(UP)
    scene.add(first, second, third)
    scene.update_frame(dt=0, force_draw=True)
    return scene


def build_dot_scene():
    from maniml.mobject.types.dot_cloud import DotCloud

    scene = PortScene(window=None)
    xs, ys = np.meshgrid(np.linspace(-4, 4, 9), np.linspace(-2, 2, 5))
    points = np.column_stack([xs.ravel(), ys.ravel(), np.zeros(xs.size)])
    grid = DotCloud(points=points, color=BLUE, radius=0.08)
    glow = DotCloud(
        points=np.array([[0.0, 2.8, 0.0]]), color=YELLOW,
        radius=0.6, glow_factor=2.0)
    scene.add(grid, glow)
    scene.update_frame(dt=0, force_draw=True)
    return scene


def build_image_scene():
    from maniml.mobject.types.image_mobject import ImageMobject

    scene = PortScene(window=None)
    image = ImageMobject(_test_image_path(), height=3.0)
    circle = Circle(color=BLUE, fill_opacity=0.5).shift(RIGHT * 4)
    scene.add(image, circle)
    scene.update_frame(dt=0, force_draw=True)
    return scene


def build_surfaces_scene():
    from maniml.mobject.three_dimensions import Sphere
    from maniml.mobject.types.surface import TexturedSurface

    scene = Port3DScene(window=None)
    scene.set_camera_orientation(phi=60 * np.pi / 180, theta=20 * np.pi / 180)
    sphere = Sphere(radius=1.4).shift(LEFT * 2.2)
    textured = TexturedSurface(
        Sphere(radius=1.4), _test_image_path()).shift(RIGHT * 2.2)
    scene.add(sphere, textured)
    scene.update_frame(dt=0, force_draw=True)
    return scene


def build_clip_scene():
    scene = PortScene(window=None)
    circle = Circle(color=BLUE, fill_opacity=0.8).scale(2)
    circle.set_clip_plane(np.array([1.0, 0.5, 0.0]), 0.4)
    square = Square(color=RED, fill_opacity=0.7).shift(RIGHT * 3)
    scene.add(circle, square)
    scene.update_frame(dt=0, force_draw=True)
    return scene


def build_scene():
    scene = PortScene(window=None)
    circle = Circle(color=BLUE, fill_opacity=0.6).shift(LEFT * 3)
    square = Square(color=RED, fill_opacity=1.0).rotate(0.5).shift(RIGHT * 3)
    star = Polygon(
        *[
            (np.cos(angle), np.sin(angle), 0) if index % 2 == 0
            else (0.4 * np.cos(angle), 0.4 * np.sin(angle), 0)
            for index, angle in enumerate(np.linspace(0, 2 * np.pi, 11)[:-1])
        ],
        color=YELLOW, fill_opacity=0.8,
    ).scale(1.5).shift(UP * 2)
    text = Text("port fidelity", color=WHITE).shift(DOWN * 2.5)
    outline = Circle(color=GREEN, fill_opacity=0.0).scale(2)
    overlap_a = Circle(
        color=GREEN, fill_opacity=0.5).shift(RIGHT * 5 + UP * 2)
    overlap_b = Circle(color=GREEN, fill_opacity=0.5).shift(
        RIGHT * 5.8 + UP * 2)
    scene.add(circle, square, star, text, outline, overlap_a, overlap_b)
    scene.update_frame(dt=0, force_draw=True)
    return scene


class GeometryPayloadTests(unittest.TestCase):
    def test_payload_wellformed(self):
        from maniml.web.geometry import GEOMETRY_FORMAT_VERSION

        scene = build_scene()
        header, vertex_bytes = parse_geometry_message(serialize_scene(scene))
        self.assertEqual(header["format_version"], GEOMETRY_FORMAT_VERSION)
        self.assertEqual(payload_size(header), len(vertex_bytes))
        for batch in header["batches"]:
            self.assertEqual(batch["num_verts"] % 3, 0)
            self.assertIn("anti_alias_width", batch["uniforms"])
            self.assertLessEqual(batch["stroke_verts"], 64)
        self.assertEqual(len(header["camera"]["view"]), 16)
        self.assertLess(len(header["batches"]), 8)

    def test_z_index_boundaries_survive_serialization(self):
        scene = PortScene(window=None)
        dot = Dot(np.array([0.0, 0.0, 0.0]), color=YELLOW, z_index=10)
        line = Line(LEFT * 3, RIGHT * 3, color=BLUE, stroke_width=8)
        scene.add(dot, line)
        scene.update_frame(dt=0, force_draw=True)

        # The higher-z dot is last in native draw order, and the serializer
        # must not merge it back into the line's otherwise-compatible batch.
        self.assertLess(scene.mobjects.index(line), scene.mobjects.index(dot))
        header, _ = parse_geometry_message(serialize_scene(scene))
        self.assertGreater(len(header["batches"]), 1)


# (name, scene builder, mean threshold, fraction-off-by->24 threshold)
CASES = [
    ("2d", build_scene, 1.5, 0.005),
    ("clip", build_clip_scene, 1.5, 0.005),
    ("dots", build_dot_scene, 1.5, 0.005),
    ("image", build_image_scene, 1.5, 0.005),
    ("3d", build_3d_scene, 2.0, 0.01),
    ("surfaces", build_surfaces_scene, 2.0, 0.01),
]


@unittest.skipUnless(HAVE_WGPU, "wgpu not installed")
class WgpuPortFidelity(unittest.TestCase):
    def test_wgpu_matches_native(self):
        from maniml.web.wgpu_renderer import WgpuRenderer

        # Capture every native image before instantiating the wgpu
        # renderer (native standalone-GL contexts and wgpu coexist, but
        # keep the native work batched up front like the GL tests do)
        captured = []
        for name, builder, mean_max, frac_max in CASES:
            scene = builder()
            native = np.asarray(
                scene.get_image().convert("RGB"), dtype=np.float64)
            header, vertex_bytes = parse_geometry_message(
                serialize_scene(scene))
            self.assertEqual(header["unsupported"], [], name)
            captured.append(
                (name, native, header, vertex_bytes, mean_max, frac_max))

        renderer = WgpuRenderer()
        for name, native, header, vertex_bytes, mean_max, frac_max in captured:
            with self.subTest(case=name):
                ported = renderer.render(header, vertex_bytes)
                ported = np.asarray(ported.convert("RGB"), dtype=np.float64)
                self.assertEqual(native.shape, ported.shape)
                diff = np.abs(native - ported)
                mean_diff = diff.mean()
                frac_off = (diff.max(axis=2) > 24).mean()
                self.assertLess(
                    mean_diff, mean_max,
                    f"[{name}] mean |diff| {mean_diff:.3f}; "
                    f"{frac_off * 100:.3f}% of pixels off by >24")
                self.assertLess(
                    frac_off, frac_max,
                    f"[{name}] {frac_off * 100:.3f}% of pixels off by >24 "
                    f"(mean {mean_diff:.3f})")

@unittest.skipUnless(HAVE_WGPU, "wgpu not installed")
class WgpuDeltaEncoding(unittest.TestCase):
    def test_cached_batches_render_identically(self):
        from maniml.web.geometry import GeometryCache
        from maniml.web.wgpu_renderer import WgpuRenderer

        scene = PortScene(window=None)
        circle = Circle(color=BLUE, fill_opacity=0.6).shift(LEFT * 3)
        scene.add(circle)
        scene.update_frame(dt=0, force_draw=True)

        cache = GeometryCache()
        h1, b1 = parse_geometry_message(serialize_scene(scene, cache))
        h2, b2 = parse_geometry_message(serialize_scene(scene, cache))
        self.assertTrue(all(b.get("cached") for b in h2["batches"]))
        circle.shift(RIGHT * 2)
        scene.update_frame(dt=0, force_draw=True)
        native3 = np.asarray(scene.get_image().convert("RGB"), float)
        h3, b3 = parse_geometry_message(serialize_scene(scene, cache))

        renderer = WgpuRenderer()
        img1 = np.asarray(renderer.render(h1, b1).convert("RGB"), float)
        img2 = np.asarray(renderer.render(h2, b2).convert("RGB"), float)
        self.assertTrue((img1 == img2).all())
        img3 = np.asarray(renderer.render(h3, b3).convert("RGB"), float)
        self.assertLess(np.abs(native3 - img3).mean(), 1.5)


if __name__ == "__main__":
    unittest.main()

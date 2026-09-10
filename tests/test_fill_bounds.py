"""Bounded winding compositing must preserve the existing rendered picture.

These fixtures use the real camera projection and geometry serializer without
allocating a native GL context. GPU cases compare optimized metadata against
the same payload with the optional rectangle removed (the legacy full-frame
path), including successive cached frames. They need wgpu, but not TeX.
"""

from copy import deepcopy
from types import SimpleNamespace
import unittest

import numpy as np

from maniml.camera.camera import Camera
from maniml.camera.camera_frame import CameraFrame
from maniml.constants import BLUE, GREEN, RED, WHITE, YELLOW
from maniml.mobject.geometry import Annulus, Circle, Line, Polygon, Square
from maniml.mobject.mobject import Group, Point
from maniml.mobject.types.vectorized_mobject import VGroup
from tests.winding_reference_geometry import GeometryCache, parse_geometry_message, serialize_scene

try:
    import wgpu  # noqa: F401
except ImportError:
    HAVE_WGPU = False
else:
    HAVE_WGPU = True


def _scene(*mobjects, resolution=(384, 216), samples=0):
    # Camera.refresh_uniforms is the production projection. Only its GL
    # framebuffer allocation is replaced: serialization needs its size.
    camera = Camera.__new__(Camera)
    camera.frame = CameraFrame()
    camera.light_source = Point(np.array([-10., 10., 10.]))
    camera.uniforms = {}
    camera.fbo = camera.draw_fbo = SimpleNamespace(size=resolution)
    camera.background_rgba = [0.08, 0.11, 0.14, 1.0]
    camera.samples = samples
    return SimpleNamespace(camera=camera, render_groups=[Group(*mobjects)])


def _payload(scene, cache=None):
    return parse_geometry_message(serialize_scene(scene, cache))


def _without_bounds(header):
    legacy = deepcopy(header)
    for batch in legacy["batches"]:
        batch.pop("fill_rect", None)
    return legacy


def _wordmark():
    # The 211-square B0 regression, made self-contained rather than importing
    # the user's course repository. Positions and default outlines match it.
    font = {
        "C": [1, 2, 3, 5, 9, 10, 15, 20, 25, 29, 31, 32, 33],
        "E": [0, 1, 2, 3, 4, 5, 10, 15, 16, 17, 18, 20, 25, 30, 31, 32, 33, 34],
        "I": [1, 2, 3, 7, 12, 17, 22, 27, 31, 32, 33],
        "M": [0, 4, 5, 6, 8, 9, 10, 12, 14, 15, 19, 20, 24, 25, 29, 30, 34],
        "N": [0, 4, 5, 6, 9, 10, 12, 14, 15, 18, 19, 20, 24, 25, 29, 30, 34],
        "O": [1, 2, 3, 5, 9, 10, 14, 15, 19, 20, 24, 25, 29, 31, 32, 33],
        "R": [0, 1, 2, 3, 5, 9, 10, 14, 15, 16, 17, 18, 20, 23, 25, 29, 30, 34],
        "S": [1, 2, 3, 5, 9, 10, 16, 17, 18, 24, 25, 29, 31, 32, 33],
    }
    squares = []
    colors = [BLUE, GREEN, RED, YELLOW]
    for letter_index, letter in enumerate("MICROECONOMICS"):
        for pixel in font[letter]:
            x, y = pixel % 5 - 2, pixel // 5 - 3
            square = Square(side_length=1 / 6, color=WHITE)
            square.move_to([(x + 6 * letter_index - 39) / 6, -y / 6, 0])
            square.set_fill(colors[len(squares) % len(colors)], opacity=0.75)
            squares.append(square)
    return VGroup(*squares)


class FillBoundsMetadata(unittest.TestCase):
    def test_small_square_has_small_valid_output_rectangle(self):
        header, _ = _payload(_scene(Square(side_length=0.5, fill_opacity=1)))
        rect = header["batches"][0]["fill_rect"]
        x, y, width, height = rect
        self.assertTrue(all(isinstance(value, int) for value in rect))
        self.assertGreater(width, 0)
        self.assertGreater(height, 0)
        self.assertLess(width * height, 0.05 * 384 * 216)
        self.assertGreaterEqual(x, 0)
        self.assertGreaterEqual(y, 0)
        self.assertLessEqual(x + width, 384)
        self.assertLessEqual(y + height, 216)

    def test_empty_fill_and_fully_offscreen_fill_are_empty(self):
        for square in (Square(fill_opacity=0),
                       Square(fill_opacity=1).shift([100, 0, 0])):
            with self.subTest(fill=square.get_fill_opacity()):
                header, _ = _payload(_scene(square))
                _, _, width, height = header["batches"][0]["fill_rect"]
                self.assertEqual(width * height, 0)

    def test_cached_camera_changes_refresh_bounds_without_vertex_bytes(self):
        scene = _scene(Square(side_length=0.8, fill_opacity=1).shift([2, 1, 0]))
        cache = GeometryCache()
        first, first_bytes = _payload(scene, cache)
        scene.camera.frame.shift([1, 0.4, 0]).scale(0.6)
        moved, moved_bytes = _payload(scene, cache)
        self.assertGreater(len(first_bytes), 0)
        self.assertEqual(moved_bytes, b"")
        self.assertTrue(moved["batches"][0]["cached"])
        self.assertEqual(first["batches"][0]["hash"], moved["batches"][0]["hash"])
        self.assertNotEqual(first["batches"][0]["fill_rect"],
                            moved["batches"][0]["fill_rect"])

    def test_b0_wordmark_keeps_draw_order_and_restricts_area(self):
        word = _wordmark()
        self.assertEqual(len(word), 211)
        header, _ = _payload(_scene(word))
        # Draw-order hazards are retained; rectangles must improve this
        # workload without grouping overlapping fills and strokes together.
        self.assertEqual(len(header["batches"]), 135)
        rects = [batch["fill_rect"] for batch in header["batches"]]
        self.assertTrue(all(rect is not None for rect in rects))
        total_area = sum(width * height for _, _, width, height in rects)
        self.assertLess(total_area, 384 * 216)

    def test_unsupported_projection_and_border_keep_full_frame(self):
        nonflat = Square(fill_opacity=1, fill_border_width=3, flat_stroke=False)
        crossing = Square(fill_opacity=1)
        scene = _scene(crossing)
        crossing.shift([0, 0, scene.camera.frame.get_focal_distance()])
        for candidate in (_scene(nonflat), scene):
            with self.subTest(scene=candidate):
                header, _ = _payload(candidate)
                self.assertNotIn("fill_rect", header["batches"][0])

    def test_triangulated_and_nonvector_batches_have_no_fill_rectangle(self):
        from maniml.mobject.types.dot_cloud import DotCloud
        for mob in (Square(fill_opacity=1, use_triangulated_fill=True),
                    DotCloud(points=np.array([[0., 0., 0.]]))):
            with self.subTest(mobject=type(mob).__name__):
                header, _ = _payload(_scene(mob))
                self.assertNotIn("fill_rect", header["batches"][0])

    def test_fan_base_outside_boundary_is_included(self):
        from maniml.web.fill_bounds import fill_composite_rect
        square = Square(side_length=0.5, fill_opacity=1)
        scene = _scene(square)
        scene.camera.refresh_uniforms()
        uniforms = {**scene.camera.uniforms, **square.uniforms}
        data = square.get_shader_data().copy()
        baseline = fill_composite_rect(data, uniforms, (384, 216))
        data["base_normal"][0::3] = [-4., 2., 0.]
        with_fan = fill_composite_rect(data, uniforms, (384, 216))
        self.assertLess(with_fan[0], baseline[0])
        self.assertLess(with_fan[1], baseline[1])
        self.assertGreaterEqual(with_fan[0] + with_fan[2],
                                baseline[0] + baseline[2])

    def test_nonfinite_projection_declines_optimization(self):
        from maniml.web.fill_bounds import fill_composite_rect
        square = Square(fill_opacity=1)
        scene = _scene(square)
        scene.camera.refresh_uniforms()
        uniforms = {**scene.camera.uniforms, **square.uniforms}
        for field in ("view", "frame_rescale_factors"):
            with self.subTest(field=field):
                broken = dict(uniforms)
                broken[field] = np.full_like(uniforms[field], np.nan)
                self.assertIsNone(fill_composite_rect(
                    square.get_shader_data(), broken, (384, 216)))


@unittest.skipUnless(HAVE_WGPU, "wgpu not installed")
class BoundedFillFidelity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from tests.winding_reference_renderer import WgpuRenderer
        cls.renderer = WgpuRenderer()

    def assertSamePicture(self, header, data, max_channel_error=0):
        self.assertEqual(header["unsupported"], [])
        optimized = np.asarray(self.renderer.render(header, data))
        legacy = np.asarray(self.renderer.render(_without_bounds(header), data))
        if max_channel_error:
            error = np.abs(optimized.astype(np.int16) - legacy.astype(np.int16))
            self.assertLessEqual(int(error.max()), max_channel_error)
            self.assertLess(float(error.mean()), 0.001)
        else:
            np.testing.assert_array_equal(optimized, legacy)
        return optimized

    def test_actual_touching_wordmark(self):
        word = _wordmark()
        scene = _scene(word)
        self.assertSamePicture(*_payload(scene))
        # Fade-in plus later color flicker and whole-word movement exercise
        # fresh bounds and varying alpha without reconstructing the scene.
        for index, square in enumerate(word):
            square.set_fill(RED if index % 3 else BLUE, opacity=0.25)
        word.shift([0, 0.9, 0])
        self.assertSamePicture(*_payload(scene))

    def test_holes_transparency_and_curved_boundaries(self):
        ring = Annulus(inner_radius=0.55, outer_radius=1.2,
                       color=YELLOW, fill_opacity=0.55).shift([-1, 0.5, 0])
        circle = Circle(color=BLUE, fill_opacity=0.7, stroke_width=8,
                        fill_border_width=4).shift([0, 0.3, 0])
        circle.set_fill(color=[RED, GREEN, BLUE], opacity=[0.2, 0.6, 0.9])
        clipped = Circle(color=RED, fill_opacity=0.6).shift([1.2, -0.4, 0])
        clipped.set_clip_plane(np.array([1, 0.5, 0]), 0.4)
        self.assertSamePicture(*_payload(_scene(ring, circle, clipped)))

    def test_glyphs_with_holes_and_fill_borders(self):
        from maniml.mobject.svg.text_mobject import Text
        glyphs = Text("B8g OQ", color=WHITE).scale(1.8).shift([1.1, 0.6, 0])
        background = Square(side_length=3, color=BLUE, fill_opacity=0.6)
        # Rescaling into the smaller scratch target can move f16/filter
        # rounding by one 8-bit level at a tiny number of glyph-edge pixels.
        # Bound both its amplitude and its total extent; all other cases
        # still require exact pixel equality.
        self.assertSamePicture(*_payload(_scene(background, glyphs)),
                               max_channel_error=1)

    def test_sharp_joins_large_borders_and_separate_strokes(self):
        for joint in ("auto", "bevel", "miter"):
            with self.subTest(joint=joint):
                tip = Polygon([-2, -1, 0], [2, 0, 0], [-2, -0.85, 0],
                              fill_opacity=0.8, color=GREEN, stroke_width=18,
                              fill_border_width=9, joint_type=joint)
                outline = Line([-5, 2, 0], [5, 2, 0], color=RED, stroke_width=16)
                self.assertSamePicture(*_payload(_scene(tip, outline)))

    def test_stroke_behind_preserves_overlapping_draw_order(self):
        back_stroke = Square(side_length=2, fill_opacity=0.7,
                             fill_color=BLUE, stroke_color=RED,
                             stroke_width=24, stroke_behind=True)
        front_stroke = Circle(radius=0.7, fill_opacity=0.65,
                              fill_color=GREEN, stroke_color=YELLOW,
                              stroke_width=12).shift([0.8, -0.2, 0])
        self.assertSamePicture(*_payload(_scene(back_stroke, front_stroke)))

    def test_partial_and_fully_offscreen_shapes(self):
        scene = _scene()
        half_width = scene.camera.frame.get_width() / 2
        half_height = scene.camera.frame.get_height() / 2
        scene.render_groups = [VGroup(*[
            Square(side_length=1.4, color=color, fill_opacity=0.7,
                   stroke_width=14, fill_border_width=5).shift(position)
            for position, color in (
                ([half_width, 0, 0], RED), ([-half_width, 0, 0], BLUE),
                ([0, half_height, 0], GREEN), ([0, -half_height, 0], YELLOW),
                ([100, 100, 0], WHITE),
            )
        ])]
        self.assertSamePicture(*_payload(scene))

    def test_camera_motion_zoom_tilt_and_fixed_overlay(self):
        fixed = Square(side_length=0.7, color=YELLOW, fill_opacity=1)
        fixed.shift([-3, 2, 0]).fix_in_frame()
        scene = _scene(
            Circle(color=RED, fill_opacity=0.6, fill_border_width=3),
            Annulus(inner_radius=0.3, outer_radius=0.7, color=BLUE)
            .shift([2, 1, 0.8]), fixed,
        )
        cache = GeometryCache()
        self.assertSamePicture(*_payload(scene, cache))
        scene.camera.frame.shift([1.1, -0.7, 0]).scale(0.65)
        self.assertSamePicture(*_payload(scene, cache))
        scene.camera.frame.reorient(18, 35, 12)
        self.assertSamePicture(*_payload(scene, cache))

    def test_offscreen_cached_fill_becomes_visible_after_camera_move(self):
        square = Square(side_length=1, color=GREEN, fill_opacity=0.8)
        square.shift([30, 0, 0])
        scene = _scene(square)
        cache = GeometryCache()
        hidden, data = _payload(scene, cache)
        _, _, width, height = hidden["batches"][0]["fill_rect"]
        self.assertEqual(width * height, 0)
        self.assertSamePicture(hidden, data)
        scene.camera.frame.move_to([30, 0, 0])
        shown, data = _payload(scene, cache)
        self.assertEqual(data, b"")
        image = self.assertSamePicture(shown, data)
        self.assertGreater(np.unique(image.reshape(-1, 4), axis=0).shape[0], 2)

    def test_multisample_output(self):
        scene = _scene(Circle(color=BLUE, fill_opacity=0.65,
                              fill_border_width=3).shift([1.234, -0.567, 0]),
                       samples=4)
        self.assertSamePicture(*_payload(scene))

    def test_reused_scratch_targets_do_not_retain_previous_fills(self):
        square = Square(side_length=1, fill_opacity=0.55, stroke_width=0)
        scene = _scene(square)
        cache = GeometryCache()
        # Far-apart colors reuse small and large target buckets over
        # successive frames. Any missed clear leaves colored remnants.
        frames = (
            (0.5, [-4, -1, 0], RED), (0.6, [4, 1, 0], GREEN),
            (2.8, [3, 1, 0], BLUE), (2.4, [-3, 0.5, 0], YELLOW),
            (0.75, [4, -2, 0], GREEN), (0.5, [-4, -1, 0], RED),
        )
        rendered = []
        for width, position, color in frames:
            square.set_width(width).move_to(position).set_fill(color)
            header, data = _payload(scene, cache)
            rendered.append((header, data,
                             np.asarray(self.renderer.render(header, data))))
        # Keep all optimized frames consecutive: interleaving full-frame
        # comparisons would evict the small pool buckets between frames.
        for index, (header, data, optimized) in enumerate(rendered):
            with self.subTest(frame=index):
                legacy = np.asarray(self.renderer.render(_without_bounds(header), data))
                np.testing.assert_array_equal(optimized, legacy)

    def test_invalid_rectangles_fall_back_to_full_frame(self):
        header, data = _payload(_scene(Square(color=RED, fill_opacity=0.8)))
        legacy = np.asarray(self.renderer.render(_without_bounds(header), data))
        invalid = (
            None, [], [0, 0, 10], [0, 0, 10, 10, 0],
            [-1, 0, 10, 10], [0, 0, -1, 10], [380, 0, 10, 10],
            [0, 212, 10, 10], [0.5, 0, 10, 10], [0, 0, float("nan"), 10],
            [False, 0, 10, 10], ["0", 0, 10, 10], "0,0,10,10",
        )
        for rect in invalid:
            with self.subTest(rect=rect):
                header["batches"][0]["fill_rect"] = rect
                result = np.asarray(self.renderer.render(header, data))
                np.testing.assert_array_equal(result, legacy)

    def test_explicit_empty_rectangle_actually_skips_fill(self):
        # Differential comparisons alone would also pass if a renderer
        # accidentally ignored every rectangle. Pin its observable effect.
        scene = _scene(Square(side_length=2, color=RED, fill_opacity=1,
                              stroke_width=0))
        header, data = _payload(scene)
        legacy = np.asarray(self.renderer.render(_without_bounds(header), data))
        header["batches"][0]["fill_rect"] = [0, 0, 0, 0]
        hidden = np.asarray(self.renderer.render(header, data))
        self.assertGreater(np.count_nonzero(legacy != hidden), 0)
        self.assertTrue(np.all(hidden == hidden[0, 0]))


if __name__ == "__main__":
    unittest.main()

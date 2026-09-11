"""The patch fill (docs/phase_b1_plan.md): preparation, wire, driver commands
and, with MANIML_TEST_GPU=1, pixels against CPU-border Phase A."""

import importlib.util
import os
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np

from maniml.constants import BLUE, GREEN, RED
from maniml.mobject.geometry import Circle, Square
from maniml.mobject.types.vectorized_mobject import VMobject
from maniml.web.generated_geometry import serialize_generated_frame
from maniml.web.geometry import GeometryCache, parse_geometry_message, serialize_scene
from maniml.web.gpu_border_geometry import (
    OBJECT_WORDS, PATCH_VERTICES_PER_CURVE, indices_per_curve, patch_draw_count,
)
from maniml.web.triangle_geometry import LyonFillTessellator
from maniml.web.triangle_scene import TriangleMeshCache, UnsupportedPrototype, prepare_triangle_frame
from tests.renderer_fixtures import build_scene, closed_contours, renderer_cases

HAVE_LYON = bool(os.environ.get("MANIML_LYON_LIBRARY")) or importlib.util.find_spec("maniml.web.maniml_lyon_fill")
no_mesh = patch("maniml.web.triangle_scene._generate_mesh",
                side_effect=AssertionError("the patch fill generated a mesh"))


def _squares(opacity=1, border=4, depth=False):
    shapes = [Square(side_length=1, fill_color=color, fill_opacity=opacity, stroke_width=0,
                     fill_border_width=border).shift([x, 0, 0])
              for color, x in ((RED, -.25), (BLUE, .25))]
    for shape in shapes:
        shape.depth_test = depth
    return build_scene(*shapes, resolution=(960, 540))


def _prepare(scene, cache, **kwargs):
    return prepare_triangle_frame(scene, _prepare.tessellator, mesh_cache=cache,
                                  fill_borders=True, gpu_borders=True, patch_fills=True, **kwargs)


def _encode(frame, scene, wire):
    return parse_geometry_message(serialize_generated_frame(frame, scene.camera.uniforms, wire))


@unittest.skipUnless(HAVE_LYON, "the Lyon helper is the frame preparer's tessellator")
class PatchFillPreparation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _prepare.tessellator = LyonFillTessellator()

    def test_patch_draws_carry_curves_and_object_records_and_no_mesh(self):
        scene, cache = _squares(), TriangleMeshCache()
        with no_mesh:
            separate = _prepare(scene, cache, coalesce=False)
            together = _prepare(scene, cache)
        self.assertEqual(len(separate.draws), 2)
        for shape, draw in zip(scene.mobjects, separate.draws):
            self.assertEqual(draw.pipeline, "patch")
            self.assertEqual(len(draw.vertices), 0)
            self.assertIsNone(draw.indices)
            self.assertEqual(len(draw.border_sources), shape.get_num_curves())
            self.assertEqual(draw.patch_layout, ((shape.get_num_curves(), 1, 0),), "a lone object is group 0")
            self.assertEqual(draw.fill_objects.shape, (1, OBJECT_WORDS))
            anchors = draw.border_sources[:, 0:3]
            np.testing.assert_allclose(draw.fill_objects[0, :3], anchors.mean(axis=0), atol=1e-6)
            self.assertEqual(draw.count, patch_draw_count(draw.patch_layout, draw.border_capacity))
        run, = together.draws
        self.assertEqual(run.pipeline, "patch")
        # Two opaque squares of different colours: each its own group.
        self.assertEqual(run.patch_layout, tuple((n, b, i) for i, (n, b, _) in enumerate(d.patch_layout[0] for d in separate.draws)))
        np.testing.assert_array_equal(run.border_sources,
                                      np.concatenate([d.border_sources for d in separate.draws]))
        self.assertEqual(run.fill_objects.shape, (2, OBJECT_WORDS))
        offsets = np.cumsum([0, *(len(d.border_sources) for d in separate.draws[:-1])])
        np.testing.assert_array_equal(run.fill_objects[:, 3], offsets)
        np.testing.assert_array_equal(run.fill_objects[:, 4], [len(d.border_sources) for d in separate.draws])
        np.testing.assert_array_equal(run.fill_objects[:, 5], 1)
        self.assertEqual(run.count, patch_draw_count(run.patch_layout, run.border_capacity))
        self.assertEqual(together.mesh_cache_stats["retained_fill_cache_bytes"], 0)

    def test_every_curve_is_packed_even_without_a_border(self):
        plain = Square(side_length=1, fill_color=RED, fill_opacity=1, stroke_width=0, fill_border_width=0)
        partial = Square(side_length=1, fill_color=BLUE, fill_opacity=1, stroke_width=0,
                         fill_border_width=4).shift([1.5, 0, 0])
        partial.data["fill_border_width"][:3] = 0  # the first curve has no border
        scene = build_scene(plain, partial)
        with no_mesh:
            draws = _prepare(scene, TriangleMeshCache(), coalesce=False).draws
        for shape, draw in zip((plain, partial), draws):
            self.assertEqual(len(draw.border_sources), shape.get_num_curves())
        self.assertEqual(draws[0].patch_layout, ((4, 0, 0),))
        self.assertFalse(draws[0].border_sources[:, 37].any())
        self.assertEqual(draws[0].count, PATCH_VERTICES_PER_CURVE * 4)
        self.assertEqual(draws[1].patch_layout, ((4, 1, 0),))
        np.testing.assert_array_equal(draws[1].border_sources[:, 37], [0, 1, 1, 1])
        self.assertEqual(draws[1].count, 4 * (PATCH_VERTICES_PER_CURVE + indices_per_curve(draws[1].border_capacity)))

    def test_camera_only_changes_resend_nothing_and_repack_nothing(self):
        scene, meshes, wire = _squares(), TriangleMeshCache(), GeometryCache()
        first = _prepare(scene, meshes)
        header, raw = _encode(first, scene, wire)
        self.assertTrue(raw)
        self.assertEqual(header["format_version"], 7)
        self.assertTrue(header["object_data"])
        draw, = first.draws
        for scale, shift in ((.75, [0, 0, 0]), (1, [.01, -.02, 0]), (.05, [0, 0, 0])):
            scene.camera.frame.scale(scale).shift(shift)
            with no_mesh:
                current = _prepare(scene, meshes)
            changed, = current.draws
            for field in ("border_sources", "fill_objects"):
                self.assertIs(getattr(draw, field), getattr(changed, field))
            with patch("maniml.web.generated_geometry.hashlib.blake2b",
                       side_effect=AssertionError("rehashed a camera-only frame")):
                updated, payload = _encode(current, scene, wire)
            self.assertEqual(payload, b"")
            self.assertEqual(updated["border_data"], {})
            self.assertEqual(updated["object_data"], {})
            batch = updated["batches"][0]
            self.assertTrue(batch["cached"])
            self.assertEqual(batch["hash"], header["batches"][0]["hash"])
            self.assertEqual(batch["objects"], header["batches"][0]["objects"])
            self.assertEqual(current.mesh_cache_stats["gpu_border_source_updates"], 2)
            self.assertEqual(current.mesh_cache_stats["gpu_border_assemblies"], 1)
        self.assertEqual(updated["batches"][0]["count"], changed.count)
        # A curve's steps grow with zoom: the reservation and the draw count
        # follow, and still nothing is resent.
        scene, meshes, wire = (build_scene(Circle(fill_opacity=1, stroke_width=0, fill_border_width=2)),
                               TriangleMeshCache(), GeometryCache())
        header, _ = _encode(_prepare(scene, meshes), scene, wire)
        scene.camera.frame.scale(.05)
        with no_mesh:
            current = _prepare(scene, meshes)
        updated, payload = _encode(current, scene, wire)
        self.assertGreater(current.draws[0].border_capacity, header["batches"][0]["border"]["capacity"])
        self.assertGreater(updated["batches"][0]["count"], header["batches"][0]["count"])
        self.assertTrue(updated["batches"][0]["cached"])
        self.assertEqual(payload, b"")
        self.assertEqual(updated["object_data"], {})

    def test_source_and_style_edits_repack_only_what_changed(self):
        scene, meshes, wire = _squares(opacity=.5), TriangleMeshCache(), GeometryCache()
        previous, _ = _encode(_prepare(scene, meshes), scene, wire)
        first, second = scene.mobjects
        first.shift([0, .3, 0])
        current = _prepare(scene, meshes)
        header, raw = _encode(current, scene, wire)
        self.assertTrue(raw)
        self.assertNotEqual(header["batches"][0]["border"]["hash"], previous["batches"][0]["border"]["hash"])
        self.assertNotEqual(header["batches"][0]["objects"]["hash"], previous["batches"][0]["objects"]["hash"])
        # Counters are cumulative: two packings for the first frame, one more here.
        self.assertEqual(current.mesh_cache_stats["gpu_border_source_updates"], 3)
        record = current.draws[0].fill_objects
        np.testing.assert_allclose(record[0, :3], current.draws[0].border_sources[:4, 0:3].mean(axis=0), atol=1e-6)
        self.assertAlmostEqual(float(record[0, 1]), .3, places=5)
        # A fill colour change keeps the geometry and the base point.
        second.set_fill(GREEN)
        current = _prepare(scene, meshes)
        header, raw = _encode(current, scene, wire)
        self.assertTrue(raw)
        self.assertEqual(current.mesh_cache_stats["gpu_border_source_updates"], 4)
        np.testing.assert_array_equal(current.draws[0].fill_objects, record)
        # Per-point paint makes a material run of its own, with its field.
        second.set_fill(color=[RED, GREEN, BLUE, RED])
        current = _prepare(scene, meshes)
        self.assertEqual([draw.pipeline for draw in current.draws], ["patch", "patch"])
        self.assertIsNone(current.draws[0].paint)
        self.assertIsNotNone(current.draws[1].paint)
        header, _ = _encode(current, scene, wire)
        self.assertNotIn("paint_hash", header["batches"][0])
        self.assertIn("paint_hash", header["batches"][1])

    def test_translucency_and_depth_keep_one_run_and_the_depth_pipeline(self):
        with no_mesh:
            translucent = _prepare(_squares(opacity=.5), TriangleMeshCache()).draws
            depth = _prepare(_squares(depth=True), TriangleMeshCache()).draws
        self.assertEqual(len(translucent), 1)
        self.assertFalse(translucent[0].coverage)
        self.assertEqual([group for _, _, group in translucent[0].patch_layout], [0, 1],
                         "translucent objects never share a count")
        self.assertEqual(len(depth), 1)
        self.assertEqual(depth[0].pipeline, "patch_depth")
        self.assertEqual([group for _, _, group in depth[0].patch_layout], [0, 1])

    def test_opaque_same_colour_objects_of_one_winding_sign_share_a_group(self):
        from maniml.mobject.geometry import Annulus
        from maniml.web.gpu_border_geometry import patch_groups, winding_sign
        from tests.renderer_fixtures import get_fixture
        same = [Square(side_length=1, fill_color=RED, fill_opacity=1, stroke_width=0).shift([x, 0, 0])
                for x in (-1.5, 0, 1.5)]
        ring = Annulus(inner_radius=.2, outer_radius=.4, fill_color=RED, fill_opacity=1, stroke_width=0)
        reversed_square = get_fixture("reversed_winding").build().mobjects[0].set_fill(RED, opacity=1)
        blue = Square(side_length=1, fill_color=BLUE, fill_opacity=1, stroke_width=0)
        scene = build_scene(*same, ring, reversed_square, blue)
        with no_mesh:
            run, = _prepare(scene, TriangleMeshCache()).draws
        signs = [int(record[6]) for record in run.fill_objects]
        self.assertEqual(signs[:4], [signs[0]] * 4, "squares and an annulus share a sign")
        self.assertEqual(signs[4], -signs[0], "the reversed contour has the opposite sign")
        groups = [group for _, _, group in run.patch_layout]
        self.assertEqual(groups, [0, 0, 0, 0, 1, 2])
        self.assertEqual([g[:2] for g in patch_groups(run.patch_layout)], [(0, 4), (4, 1), (5, 1)])
        # A count that changes sign never shares: a hole outside its outer.
        crossing = closed_contours([(-2, -2), (2, -2), (2, 2), (-2, 2)], [(1, -1), (1, 1), (3, 1), (3, -1)])
        apart = closed_contours([(-2, -1), (-1, -1), (-1, 1), (-2, 1)], [(1, -1), (1, 1), (2, 1), (2, -1)])
        for path in (crossing, apart):
            with self.subTest(path=path):
                scene = build_scene(path, Square(fill_opacity=1, stroke_width=0, fill_border_width=0))
                with no_mesh:
                    run, = _prepare(scene, TriangleMeshCache()).draws
                self.assertEqual(int(run.fill_objects[0, 6]), 0)
                self.assertEqual([group for _, _, group in run.patch_layout], [0, 1])

    def test_nonplanar_closed_contour_is_refused_as_before(self):
        path = closed_contours([(-1, -1, 0), (1, -1, 0), (1, 1, 1), (-1, 1, 0)])
        scene = build_scene(path)
        with self.assertRaises(UnsupportedPrototype):
            _prepare(scene, TriangleMeshCache())
        with self.assertRaises(UnsupportedPrototype):
            prepare_triangle_frame(scene, _prepare.tessellator, mesh_cache=TriangleMeshCache(),
                                   fill_borders=True, gpu_borders=True)

    def test_switch_selects_patches_and_needs_the_gpu_border_generator(self):
        scene, wire = _squares(), GeometryCache()
        with patch.dict(os.environ, MANIML_FILL="patches", MANIML_BORDER_GENERATOR="gpu"):
            header, raw = parse_geometry_message(serialize_scene(scene, wire, renderer="triangles"))
            self.assertEqual([batch["pipeline"] for batch in header["batches"]], ["patch"])
            self.assertTrue(header["object_data"])
        with patch.dict(os.environ, MANIML_FILL="meshes"):
            header, raw = parse_geometry_message(serialize_scene(scene, wire, renderer="triangles"))
            self.assertEqual([batch["pipeline"] for batch in header["batches"]], ["surface"])
            self.assertTrue(raw, "the switch resets the wire cache")
        with patch.dict(os.environ, MANIML_FILL="patches", MANIML_BORDER_GENERATOR="cpu"):
            with self.assertRaises(ValueError):
                serialize_scene(scene, wire, renderer="triangles")
        with patch.dict(os.environ, MANIML_FILL="rasters"):
            with self.assertRaises(ValueError):
                serialize_scene(scene, wire, renderer="triangles")


@unittest.skipUnless(HAVE_LYON and importlib.util.find_spec("wgpu"), "needs the Lyon helper and wgpu")
class PatchFillCommands(unittest.TestCase):
    """The driver's commands for a patch run, on the fake device of
    tests.test_generated_wgpu: no GPU is needed to see the draws."""

    def setUp(self):
        from tests.test_generated_wgpu import _Device
        from maniml.web.wgpu_renderer import WgpuRenderer
        _prepare.tessellator = LyonFillTessellator()

        class Device(_Device):
            def create_bind_group_layout(self, **descriptor):
                return ("layout", len(descriptor["entries"]))

            def create_pipeline_layout(self, **descriptor):
                return ("pipeline_layout", len(descriptor["bind_group_layouts"]))

        self.renderer = WgpuRenderer.__new__(WgpuRenderer)
        self.renderer.device = Device()
        for name in ("_generated_geometry", "_generated_uniforms", "_generated_textures",
                     "_generated_paints", "_generated_paint_bindings", "_border_sources",
                     "_border_outputs", "_object_tables", "_patch_uniforms", "_net_sources",
                     "_net_outputs", "_program_sources", "_program_outputs", "_program_pipelines",
                     "texture_cache"):
            setattr(self.renderer, name, {})
        self.renderer._patch_layouts = None
        self.renderer._net_compute_pipeline = None
        self.renderer._border_compute_pipeline = None
        self.renderer._stale_index_buffers = []
        self.renderer.sampler = object()
        self.renderer._ensure_targets = Mock()
        self.renderer._modules = {"resolve2": object(), "border_compute": object(), "patch_fill": object()}
        self.renderer._spatial_pipeline = self.renderer._spatial_texture = self.renderer._spatial_binding = None
        self.renderer.resolve_texture = None
        self.renderer.out_texture = self.renderer.device.create_texture(size=(128, 72, 1))
        self.renderer.out_view = self.renderer.out_texture.create_view()
        self.renderer.depth_view = object()
        self.renderer._pipeline = Mock(side_effect=lambda name, samples: SimpleNamespace(
            name=name, get_bind_group_layout=lambda group: (name, samples, group)))
        self.renderer._patch_pipeline = lambda kind, depth, samples: SimpleNamespace(name=("patch", kind, depth))

    def frame(self, scene=None, wire=None):
        scene = scene or _squares()
        frame = _prepare(scene, TriangleMeshCache())
        frame.samples, frame.supersample = 1, 1
        return _encode(frame, scene, wire or GeometryCache())

    def draws(self):
        events = self.renderer.device.events
        return [event for event in events if event[0] in ("draw", "draw_indexed", "set_stencil_reference")
                or (event[0] == "set_pipeline" and getattr(event[1], "name", None) != "border_compute")]

    def test_each_object_is_marked_stripped_and_covered_in_order(self):
        header, raw = self.frame()
        self.renderer.render(header, raw)
        layout = header["batches"][0]["border"]["layout"]
        capacity = header["batches"][0]["border"]["capacity"]
        strip = indices_per_curve(capacity)
        expected, offset = [], 0
        self.assertEqual([group for _, _, group in layout], [0, 1], "two colours: two groups")
        for index, (curves, bordered, _) in enumerate(layout):
            fan = PATCH_VERTICES_PER_CURVE * curves
            expected += [("set_pipeline", ("patch", "mark_fan", False)), ("draw", fan // 2, 1, 0, index),
                         ("set_pipeline", ("patch", "mark_patch", False)), ("draw", fan // 2, 1, 0, index),
                         ("set_pipeline", "generated_surface_strip_mark"), ("set_stencil_reference", 0x80),
                         ("draw_indexed", strip * curves, 1, strip * offset),
                         ("set_pipeline", ("patch", "cover", False)), ("set_stencil_reference", 0),
                         ("draw", fan, 1, 0, index),
                         ("set_pipeline", "generated_surface_strip_cover"),
                         ("draw_indexed", strip * curves, 1, strip * offset)]
            offset += curves
        recorded = [(name, args[0].name) if name == "set_pipeline" else (name, *args)
                    for name, *args in self.draws()]
        self.assertEqual(recorded, expected)
        self.assertEqual(sum(1 for event in self.renderer.device.events if event[0] == "submit"), 1)
        self.assertEqual(len(self.renderer._object_tables), 1)

    def test_malformed_patch_batches_are_rejected_without_submission(self):
        header, raw = self.frame()
        batch = header["batches"][0]
        tampered = []
        for change in (
            lambda h: h["batches"][0]["border"]["layout"].append([1, 0, 2]),
            lambda h: h["batches"][0]["border"]["layout"][0].__setitem__(1, 2),
            lambda h: h["batches"][0]["border"]["layout"][0].__setitem__(2, -1),
            lambda h: h["batches"][0].__setitem__("count", batch["count"] - 3),
            lambda h: h["batches"][0]["objects"].__setitem__("count", 3),
            lambda h: h["batches"][0].__setitem__("indexed", True),
            lambda h: h["batches"][0].__setitem__("fill_num_verts", 3),
            lambda h: h.__setitem__("format_version", 6),
            lambda h: h["object_data"].__setitem__(batch["objects"]["hash"],
                                                    {"offset": 0, "nbytes": 12}),
            lambda h: h["batches"][0].__setitem__("coverage", True),
        ):
            copy = parse_geometry_message(serialize_generated_frame(
                _prepare(_squares(), TriangleMeshCache()), _squares().camera.uniforms, GeometryCache()))[0]
            copy["samples"], copy["supersample"] = 1, 1
            change(copy)
            tampered.append(copy)
        for copy in tampered:
            with self.assertRaises((ValueError, KeyError)):
                self.renderer.render(copy, raw)
            self.assertFalse(any(event[0] == "submit" for event in self.renderer.device.events))
            self.assertEqual(self.renderer._object_tables, {})
            self.assertEqual(self.renderer._border_outputs, {})

    def test_object_table_records_are_checked_against_the_layout(self):
        header, raw = self.frame()
        span = header["object_data"][header["batches"][0]["objects"]["hash"]]
        table = np.frombuffer(raw[span["offset"]:span["offset"] + span["nbytes"]], dtype="<f4").copy()
        table[3] = 1  # first object's curve offset
        broken = raw[:span["offset"]] + table.tobytes() + raw[span["offset"] + span["nbytes"]:]
        with self.assertRaises(ValueError):
            self.renderer.render(header, broken)
        self.assertFalse(any(event[0] == "submit" for event in self.renderer.device.events))


@unittest.skipUnless(os.environ.get("MANIML_TEST_GPU") == "1", "GPU image comparison not requested")
class PatchFillPixels(unittest.TestCase):
    """Patches against CPU-border Phase A at the existing gate: at most 0.5%
    of pixels off by more than 24 of 255."""

    @classmethod
    def setUpClass(cls):
        from maniml.web.wgpu_renderer import WgpuRenderer
        cls.drivers = (WgpuRenderer(), WgpuRenderer())
        _prepare.tessellator = LyonFillTessellator()

    @classmethod
    def tearDownClass(cls):
        for driver in cls.drivers:
            driver.close()

    def render(self, driver, scene, cache, **kwargs):
        frame = prepare_triangle_frame(scene, _prepare.tessellator, mesh_cache=cache,
                                       fill_borders=True, gpu_borders=True, **kwargs)
        frame.samples, frame.supersample = 4, 2
        header, payload = _encode(frame, scene, GeometryCache())
        return np.asarray(driver.render(header, payload), dtype=int), frame

    def assert_within_gate(self, mesh, patch, name):
        diff = np.abs(mesh - patch)
        self.assertLessEqual((diff.max(axis=2) > 24).mean(), .005, name)

    def test_fixture_corpus_matches_cpu_border_phase_a(self):
        for case in renderer_cases():
            with self.subTest(fixture=case.name):
                mesh, _ = self.render(self.drivers[0], case.build(), TriangleMeshCache())
                patch, _ = self.render(self.drivers[1], case.build(), TriangleMeshCache(), patch_fills=True)
                self.assert_within_gate(mesh, patch, case.name)

    def test_quality_fixtures_match_within_every_region(self):
        from tests.renderer_quality_fixtures import build_quality_frame
        for content in ("tex", "perspective", "hairlines", "border"):
            for view in ("normal", "zoom"):
                for policy in ("production_default", "zero_for_aa"):
                    with self.subTest(content=content, view=view, policy=policy):
                        quality = build_quality_frame(content, view, border_policy=policy)
                        mesh, _ = self.render(self.drivers[0], quality.scene, TriangleMeshCache())
                        quality = build_quality_frame(content, view, border_policy=policy)
                        patch, _ = self.render(self.drivers[1], quality.scene, TriangleMeshCache(),
                                               patch_fills=True)
                        self.assert_within_gate(mesh, patch, f"{content}_{view}_{policy}")
                        # Within a region the gate is the frame's; this bound
                        # catches a region drawn wrong (a filled hole is all of
                        # it). Curved edges differ by Lyon's quarter-pixel
                        # flattening: about 1% of a 27-pixel hole region.
                        diff = np.abs(mesh - patch)
                        for roi in quality.rois:
                            left, top, right, bottom = roi.box
                            error = diff[top:bottom, left:right]
                            self.assertLessEqual((error.max(axis=2) > 24).mean(), .05, roi)
                            self.assertLessEqual(error.max(), 64, roi)

    def test_camera_motion_and_a_morph_regenerate_nothing_but_the_morph(self):
        from tests.renderer_fixtures import concave_quad
        cache = TriangleMeshCache()
        scene = build_scene(concave_quad(0).set_fill(RED, opacity=.55, border_width=4),
                            Circle(radius=.65, fill_color=BLUE, fill_opacity=1, stroke_width=0,
                                   fill_border_width=2).shift([1.5, .5, 0]), resolution=(480, 270))
        reference = TriangleMeshCache()
        _, frame = self.render(self.drivers[1], scene, cache, patch_fills=True)
        packed = frame.mesh_cache_stats["gpu_border_source_updates"]  # cumulative: both objects
        self.assertEqual(packed, 2)
        for step in range(1, 5):
            scene.camera.frame.scale(.8).shift([.05, -.02, 0])
            patch, frame = self.render(self.drivers[1], scene, cache, patch_fills=True)
            self.assertEqual(frame.mesh_cache_stats["gpu_border_source_updates"], packed, step)
            mesh, _ = self.render(self.drivers[0], scene, reference)
            self.assert_within_gate(mesh, patch, f"camera step {step}")
        quad = scene.mobjects[0]
        for alpha in (.5, 2 / 3 + .001, 1):
            quad.set_points(concave_quad(alpha).get_points())
            patch, frame = self.render(self.drivers[1], scene, cache, patch_fills=True)
            packed += 1
            self.assertEqual(frame.mesh_cache_stats["gpu_border_source_updates"], packed, alpha)
            mesh, _ = self.render(self.drivers[0], scene, reference)
            self.assert_within_gate(mesh, patch, f"morph {alpha}")


if __name__ == "__main__":
    unittest.main()

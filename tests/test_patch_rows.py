"""Row sources for the patch fill (MANIML_PATCH_SOURCE=rows, B5.1 of
docs/phase_b4_plan.md): a path's rows travel in place of its curve records
and stroke instances, which each driver finalizes with row_finalize.wgsl.
Preparation and wire against the records' path, the native driver's
commands on a fake device and, with MANIML_TEST_GPU=1, pixels against the
records' path on the fixture corpus."""

import importlib.util
import os
import unittest
from unittest.mock import patch

import numpy as np

from maniml.constants import BLUE, GREEN, RED, RIGHT, UP, YELLOW
from maniml.mobject.geometry import Annulus, Circle, Square
from maniml.mobject.types.vectorized_mobject import VMobject
from maniml.web.border_geometry import BorderSource, _border_density
from maniml.web.generated_geometry import serialize_generated_frame
from maniml.web.geometry import GeometryCache, parse_geometry_message, serialize_scene
from maniml.web.gpu_border_geometry import pack_source
from maniml.web.gpu_program_geometry import rows_hash, rows_key
from maniml.web import triangle_scene
from maniml.web.triangle_geometry import LyonFillTessellator
from maniml.web.triangle_scene import TriangleMeshCache, UnsupportedPrototype, prepare_triangle_frame
from tests.renderer_fixtures import build_scene, closed_contours, renderer_cases

HAVE_LYON = bool(os.environ.get("MANIML_LYON_LIBRARY")) or importlib.util.find_spec("maniml.web.maniml_lyon_fill")
no_mesh = patch("maniml.web.triangle_scene._generate_mesh",
                side_effect=AssertionError("the patch fill generated a mesh"))
# The words of a curve record the border stage and the patch fill read. The
# rest are the three rows' fill colours, which pack_source writes as
# (1, 1, 1, the fill's visibility) and the finalize as (1, 1, 1, active):
# nothing reads them.
READ_WORDS = [word for word in range(44) if word not in (3, 4, 5, 6, 15, 16, 17, 18, 27, 28, 29, 30)]


def finalize(rows):
    """row_finalize.wgsl in numpy, float32 as the kernel computes: the
    curve records and stroke instances a driver makes of ``rows``."""
    rows = np.asarray(rows, dtype="<f4")
    curves = (len(rows) - 1) // 2
    records = np.zeros((curves, 44), dtype="<f4")
    strokes = np.zeros((curves, 51), dtype="<f4")
    fill_alpha = np.zeros(curves, dtype="<f4")
    width = np.zeros(curves, dtype="<f4")
    for k in range(3):
        row = rows[k:k + 2 * curves:2]
        strokes[:, 17 * k:17 * k + 17] = row
        slot = 12 * k
        records[:, slot:slot + 3] = row[:, 0:3]
        records[:, slot + 7] = row[:, 16]
        records[:, slot + 8] = row[:, 8]
        records[:, slot + 9:slot + 12] = row[:, 13:16]
        fill_alpha = np.maximum(fill_alpha, np.abs(row[:, 12]))
        width = np.maximum(width, np.abs(row[:, 16]))
    points = np.stack([rows[0:-2:2, :3], rows[1:-1:2, :3], rows[2::2, :3]], axis=1)
    density = _border_density(points)
    capped = ~np.isfinite(density)
    active = (fill_alpha != 0) & np.any(points[:, 0] != points[:, 1], axis=1) & (width != 0)
    for k in range(3):
        records[:, 12 * k + 3:12 * k + 6] = 1
        records[:, 12 * k + 6] = active
    records[:, 36] = np.where(capped, 0, density)
    records[:, 37] = active
    records[:, 38] = capped
    records[:, 40:44] = rows[0, 9:13]
    return records, strokes


def _prepare(scene, cache, **kwargs):
    return prepare_triangle_frame(scene, _prepare.tessellator, mesh_cache=cache, fill_borders=True,
                                  gpu_borders=True, patch_fills=True, **kwargs)


def _encode(frame, scene, wire):
    return parse_geometry_message(serialize_generated_frame(frame, scene.camera.uniforms, wire))


def _shapes():
    """Bordered opaque squares of one colour, a stroked translucent circle,
    an annulus (two contours) and a stroke-only path."""
    squares = [Square(side_length=1, fill_color=RED, fill_opacity=1, stroke_width=0,
                      fill_border_width=4).shift([x, 1.5, 0]) for x in (-2, 0, 2)]
    circle = Circle(radius=.6, fill_color=BLUE, fill_opacity=.5, stroke_color=YELLOW, stroke_width=6,
                    fill_border_width=2).shift([-2, -1, 0])
    ring = Annulus(inner_radius=.3, outer_radius=.7, fill_color=GREEN, fill_opacity=1, stroke_width=0,
                   fill_border_width=1).shift([0, -1, 0])
    line = VMobject(stroke_color=BLUE, stroke_width=4).set_points_smoothly(
        [[1.5, -1.5, 0], [2, -.5, 0], [2.5, -1.5, 0], [3, -.8, 0]])
    return [*squares, circle, ring, line]


@unittest.skipUnless(HAVE_LYON, "the Lyon helper is the frame preparer's tessellator")
class PatchRowsPreparation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _prepare.tessellator = LyonFillTessellator()

    def test_rows_stand_for_the_records_draw_for_draw(self):
        shapes = _shapes()
        scene = build_scene(*shapes, resolution=(480, 270))
        records = _prepare(scene, TriangleMeshCache(), coalesce=False).draws
        with no_mesh:
            rows = _prepare(scene, TriangleMeshCache(), coalesce=False, patch_rows=True).draws
        self.assertEqual(len(rows), len(records))
        for kept, sent in zip(records, rows):
            for name in ("pipeline", "count", "instances", "border_capacity", "patch_layout"):
                self.assertEqual(getattr(sent, name), getattr(kept, name), name)
            self.assertIsNone(sent.border_sources)
            self.assertEqual(len(sent.vertices), 0, "no curve records and no stroke instances travel")
            self.assertEqual(len(sent.rows), 1)
        # Each object's rows are its data as the read of its shader data
        # leaves it, and the records and instances a driver finalizes from
        # them are the ones the CPU packs, in every word a stage reads.
        drawn = iter(rows)
        for shape in shapes:
            has_fill = bool(np.any(shape.data["fill_rgba"][:, 3]))
            has_stroke = bool(np.any(shape.data["stroke_width"]) and np.any(shape.data["stroke_rgba"][:, 3]))
            draws = [next(drawn) for _ in range(has_fill + has_stroke)]
            sent = draws[0].rows[0]
            self.assertTrue(all(draw.rows[0] is sent for draw in draws), "fill and stroke name one rows")
            self.assertEqual(sent.tobytes(), shape.data.tobytes())
            self.assertFalse(sent.flags.writeable)
            made, instances = finalize(sent)
            np.testing.assert_array_equal(instances, shape.get_shader_data().view("<f4").reshape(-1, 51))
            if has_fill:
                source = BorderSource.read(shape, scene.camera.uniforms, budget=False)
                packed = pack_source(source, shape.data["fill_rgba"][0], every_curve=True)
                np.testing.assert_array_equal(made[:, READ_WORDS], packed[:, READ_WORDS])

    def test_runs_and_groups_are_the_records(self):
        scene = build_scene(*_shapes(), resolution=(480, 270))
        records = _prepare(scene, TriangleMeshCache()).draws
        rows = _prepare(scene, TriangleMeshCache(), patch_rows=True).draws
        self.assertEqual([(d.pipeline, d.count, d.instances, d.patch_layout) for d in rows],
                         [(d.pipeline, d.count, d.instances, d.patch_layout) for d in records])
        # The squares and the circle's fill are one run of four objects; the
        # opaque squares of one colour share a count, the translucent circle
        # groups with no one, and so its record needs no sign.
        run = rows[0]
        self.assertEqual(len(run.rows), 4)
        self.assertEqual([group for _, _, group in run.patch_layout], [0, 0, 0, 1])
        np.testing.assert_array_equal(run.fill_objects[:, 3:6], records[0].fill_objects[:, 3:6])
        np.testing.assert_array_equal(run.fill_objects[:3, 6], records[0].fill_objects[:3, 6])
        self.assertEqual((records[0].fill_objects[3, 6], run.fill_objects[3, 6]), (1, 0))
        self.assertFalse(run.fill_objects[:, :3].any(), "the base words, which nothing reads, stay zero")

    def test_a_moved_path_sends_its_rows_and_its_descriptors_alone(self):
        shapes = _shapes()
        scene, meshes, wire = build_scene(*shapes, resolution=(480, 270)), TriangleMeshCache(), GeometryCache()
        header, raw = _encode(_prepare(scene, meshes, patch_rows=True), scene, wire)
        self.assertEqual(header["border_data"], {})
        sent = header["program_data"]
        self.assertEqual(len(sent), len(shapes), "one rows per path, fill and stroke alike")
        for batch in header["batches"]:
            self.assertIn("rows", batch)
            self.assertEqual(batch["fill_num_verts"], 0)
            if batch["pipeline"] == "patch":
                self.assertEqual(batch["border"]["hash"], rows_key(batch["rows"]))
        # A still frame sends nothing.
        again, raw = _encode(_prepare(scene, meshes, patch_rows=True), scene, wire)
        self.assertEqual((raw, again["program_data"]), (b"", {}))
        self.assertTrue(all(batch["cached"] for batch in again["batches"]))
        # A moved square sends its rows alone; its run's table does not move.
        shapes[1].shift(.25 * UP)
        moved, raw = _encode(_prepare(scene, meshes, patch_rows=True), scene, wire)
        (key, span), = moved["program_data"].items()
        self.assertEqual(key, rows_hash(np.frombuffer(shapes[1].data.tobytes(), dtype="<f4").reshape(-1, 17)))
        self.assertEqual(len(raw), span["nbytes"])
        self.assertEqual(moved["object_data"], {})
        self.assertEqual([batch.get("cached", False) for batch in moved["batches"]],
                         [False, *[True] * (len(moved["batches"]) - 1)])
        # A camera move copies and resends nothing; a zoom only raises counts.
        scene.camera.frame.scale(.05)
        packed = meshes.gpu_border_cache.source_updates
        zoomed, raw = _encode(_prepare(scene, meshes, patch_rows=True), scene, wire)
        self.assertEqual(meshes.gpu_border_cache.source_updates, packed)
        self.assertEqual((raw, zoomed["program_data"]), (b"", {}))
        self.assertGreater(zoomed["batches"][0]["count"], moved["batches"][0]["count"])

    def test_the_planar_refusal_is_the_records(self):
        bent = closed_contours([(-1, -1, 0), (1, -1, 0), (1, 1, 1), (-1, 1, 0)])
        with self.assertRaises(UnsupportedPrototype):
            _prepare(build_scene(bent), TriangleMeshCache(), patch_rows=True)
        # A tilted plane is fitted, and accepted.
        tilted = Square(fill_color=RED, fill_opacity=1).rotate(.7, axis=RIGHT)
        with patch("maniml.web.triangle_scene.planar_coordinates", wraps=triangle_scene.planar_coordinates) as fitted:
            _prepare(build_scene(tilted), TriangleMeshCache(), patch_rows=True)
        self.assertEqual(fitted.call_count, 1)
        # A path in one z is in that plane: nothing to fit.
        with patch("maniml.web.triangle_scene.planar_coordinates",
                   side_effect=AssertionError("fitted a flat path")):
            _prepare(build_scene(Square(fill_color=RED, fill_opacity=1)), TriangleMeshCache(), patch_rows=True)

    def test_rows_that_cannot_stand_for_the_records_keep_them(self):
        class OwnShaderData(Square):
            def get_shader_data(self):
                return super().get_shader_data()

        own = OwnShaderData(fill_color=RED, fill_opacity=1, stroke_width=2)
        edited = Square(fill_color=BLUE, fill_opacity=1, stroke_width=0).shift(2 * RIGHT)
        edited.get_outer_vert_indices()[[1, 2]] = edited.get_outer_vert_indices()[[2, 1]]
        draws = _prepare(build_scene(own, edited), TriangleMeshCache(), coalesce=False, patch_rows=True).draws
        self.assertEqual([draw.pipeline for draw in draws], ["patch", "stroke", "patch"])
        for draw in draws:
            self.assertIsNone(draw.rows)
        self.assertIsNotNone(draws[0].border_sources)
        self.assertEqual(len(draws[1].vertices), 3 * own.get_num_curves())

    def test_a_path_that_keeps_its_records_closes_the_rows_run(self):
        """The draws are the records' call for call only where every path
        is row-sourced: a row-sourced draw runs as patch_rows or
        stroke_rows, which never join a records run, so a path that keeps
        its records splits the run the records' side draws as one."""
        class OwnShaderData(Square):
            def get_shader_data(self):
                return super().get_shader_data()

        scene = build_scene(Square().shift(3 * RIGHT), OwnShaderData(), Square().shift(-3 * RIGHT))
        records = _prepare(scene, TriangleMeshCache()).draws
        rows = _prepare(scene, TriangleMeshCache(), patch_rows=True).draws
        self.assertEqual([(draw.pipeline, draw.instances) for draw in records], [("stroke", 12)])
        self.assertEqual([(draw.pipeline, draw.instances, draw.rows is not None) for draw in rows],
                         [("stroke", 4, True), ("stroke", 4, False), ("stroke", 4, True)])

    def test_the_switch(self):
        scene, wire = build_scene(*_shapes()), GeometryCache()
        with patch.dict(os.environ, MANIML_PATCH_SOURCE="rows"):
            header, _ = parse_geometry_message(serialize_scene(scene, wire, renderer="phase_b"))
            self.assertTrue(all("rows" in batch for batch in header["batches"]))
            # Phase A draws meshes: there is no patch to source.
            header, _ = parse_geometry_message(serialize_scene(scene, wire, renderer="triangles"))
            self.assertFalse(any("rows" in batch for batch in header["batches"]))
            header, raw = parse_geometry_message(serialize_scene(scene, wire, renderer="phase_b"))
            self.assertTrue(raw, "a renderer change resends")
        header, raw = parse_geometry_message(serialize_scene(scene, wire, renderer="phase_b"))
        self.assertFalse(any("rows" in batch for batch in header["batches"]), "records by default")
        self.assertTrue(header["border_data"], "the switch resets the wire cache")
        with patch.dict(os.environ, MANIML_PATCH_SOURCE="curves"):
            with self.assertRaises(ValueError):
                serialize_scene(scene, wire, renderer="phase_b")

    def test_rows_carry_no_nonfinite_or_negative_width(self):
        negative = Square(fill_color=RED, fill_opacity=1, fill_border_width=2)
        negative.data["fill_border_width"][0] = -1
        with self.assertRaises(ValueError):
            _prepare(build_scene(negative), TriangleMeshCache(), patch_rows=True)
        nonfinite = Square(fill_color=RED, fill_opacity=1)
        nonfinite.data["stroke_rgba"][0, 0] = np.nan
        with self.assertRaises(ValueError):
            _prepare(build_scene(nonfinite), TriangleMeshCache(), patch_rows=True)


@unittest.skipUnless(HAVE_LYON and importlib.util.find_spec("wgpu"), "needs the Lyon helper and wgpu")
class PatchRowsCommands(unittest.TestCase):
    """The native driver's commands for row-sourced batches, on the fake
    device of tests.test_generated_wgpu."""

    def setUp(self):
        from tests.test_patch_fill import PatchFillCommands
        PatchFillCommands.setUp(self)
        _prepare.tessellator = LyonFillTessellator()
        self.renderer._modules["row_finalize"] = object()
        self.scene = build_scene(*_shapes(), resolution=(480, 270))
        self.meshes, self.wire = TriangleMeshCache(), GeometryCache()

    def frame(self):
        frame = _prepare(self.scene, self.meshes, patch_rows=True)
        frame.samples, frame.supersample = 1, 1
        return _encode(frame, self.scene, self.wire)

    def events(self, name):
        return [event for event in self.renderer.device.events if event[0] == name]

    def test_rows_are_finalized_once_and_read_as_records_and_instances(self):
        header, raw = self.frame()
        self.renderer.render(header, raw)
        keys = list(header["program_data"])
        self.assertEqual(len(self.events("dispatch_workgroups")) - self.border_dispatches(header),
                         len(keys), "one finalize per rows")
        outputs = self.renderer._row_outputs
        self.assertEqual(set(outputs), set(keys))
        # The first run (three squares and the circle's fill) copies its
        # objects' records in order.
        run = header["batches"][0]
        copies = self.events("copy_buffer_to_buffer")
        self.assertEqual([event[1] for event in copies], [outputs[key]["records"] for key in run["rows"]])
        self.assertEqual([event[4] for event in copies], [0, 4 * 176, 8 * 176, 12 * 176])
        # The border stage and the patch fill read the run's records; a
        # stroke draws its object's finalized instances.
        records = self.renderer._row_runs[("records", tuple(run["rows"]))]
        output, = [value for key, value in self.renderer._border_outputs.items() if key[0] == run["hash"]]
        self.assertIs(output["binding"]["entries"][0]["resource"]["buffer"], records)
        self.assertIs(output["patch_binding"]["entries"][0]["resource"]["buffer"], records)
        strokes = [batch for batch in header["batches"] if batch["pipeline"] == "stroke"]
        vertex_buffers = [event[2] for event in self.events("set_vertex_buffer")]
        for batch in strokes:
            self.assertIn(outputs[batch["rows"][0]]["strokes"], vertex_buffers)
        # The same frame again finalizes and copies nothing.
        before = len(self.renderer.device.events)
        header, raw = self.frame()
        self.renderer.render(header, raw)
        later = [event[0] for event in self.renderer.device.events[before:]]
        self.assertNotIn("copy_buffer_to_buffer", later)
        self.assertNotIn("dispatch_workgroups", later)
        # A moved square finalizes its new rows and copies its run again;
        # the rows no batch names retire.
        self.scene.mobjects[1].shift(.1 * UP)
        before = len(self.renderer.device.events)
        header, raw = self.frame()
        self.renderer.render(header, raw)
        later = self.renderer.device.events[before:]
        self.assertEqual(sum(event[0] == "copy_buffer_to_buffer" for event in later), 4)
        self.assertEqual(len(self.renderer._row_outputs), len(keys))
        self.assertTrue(records.destroyed, "the run's old buffer retires")
        self.assertFalse(self.renderer._row_runs[("records", tuple(header["batches"][0]["rows"]))].destroyed)

    def border_dispatches(self, header):
        return sum(1 for batch in header["batches"] if batch["pipeline"] == "patch")

    def test_malformed_row_sources_are_rejected_without_submission(self):
        header, raw = self.frame()
        run = header["batches"][0]
        span = header["program_data"][run["rows"][1]]
        for change in (
            lambda h: h["batches"][0].__setitem__("rows", run["rows"][:2]),
            lambda h: h["batches"][0]["rows"].reverse(),
            lambda h: h["batches"][0].__setitem__("rows", "a" * 32),
            lambda h: h["program_data"].pop(run["rows"][1]),
            lambda h: h["program_data"].__setitem__(run["rows"][1], {**span, "nbytes": span["nbytes"] - 68}),
            lambda h: h.__setitem__("format_version", 6),
            lambda h: h["batches"][-1].__setitem__("instances", h["batches"][-1]["instances"] + 1),
        ):
            copy = parse_geometry_message(serialize_generated_frame(
                _prepare(self.scene, TriangleMeshCache(), patch_rows=True), self.scene.camera.uniforms,
                GeometryCache()))[0]
            copy["samples"], copy["supersample"] = 1, 1
            change(copy)
            with self.assertRaises((ValueError, KeyError, TypeError)):
                self.renderer.render(copy, raw)
            self.assertFalse(any(event[0] == "submit" for event in self.renderer.device.events))
            self.assertEqual((self.renderer._row_outputs, self.renderer._row_runs, self.renderer._program_sources),
                             ({}, {}, {}))


@unittest.skipUnless(os.environ.get("MANIML_TEST_GPU") == "1", "GPU image comparison not requested")
class PatchRowsPixels(unittest.TestCase):
    """Rows against records at the existing gate (at most 0.5% of pixels off
    by more than 24 of 255); on this corpus they draw the same pixels."""

    @classmethod
    def setUpClass(cls):
        from maniml.web.wgpu_renderer import WgpuRenderer
        cls.drivers = (WgpuRenderer(), WgpuRenderer())
        _prepare.tessellator = LyonFillTessellator()

    @classmethod
    def tearDownClass(cls):
        for driver in cls.drivers:
            driver.close()

    def render(self, driver, scene, cache, wire, rows):
        frame = _prepare(scene, cache, patch_rows=rows)
        frame.samples, frame.supersample = 4, 2
        header, payload = _encode(frame, scene, wire)
        return np.asarray(driver.render(header, payload), dtype=int)

    def assert_matches(self, scene_of, name, steps=(None,)):
        caches = [(TriangleMeshCache(), GeometryCache()) for _ in self.drivers]
        scenes = [scene_of(), scene_of()]
        for step in steps:
            if step is not None:
                for scene in scenes:
                    step(scene)
            records = self.render(self.drivers[0], scenes[0], *caches[0], False)
            rows = self.render(self.drivers[1], scenes[1], *caches[1], True)
            diff = np.abs(records - rows)
            self.assertLessEqual((diff.max(axis=2) > 24).mean(), .005, name)
            self.assertLessEqual(diff.max(), 1, f"{name}: rows and records draw the same pixels")

    def test_fixture_corpus(self):
        for case in renderer_cases():
            with self.subTest(fixture=case.name):
                self.assert_matches(case.build, case.name)

    def test_quality_fixtures(self):
        from tests.renderer_quality_fixtures import build_quality_frame
        for content in ("tex", "perspective", "hairlines", "border"):
            for view in ("normal", "zoom"):
                with self.subTest(content=content, view=view):
                    self.assert_matches(lambda: build_quality_frame(content, view).scene, f"{content}_{view}")

    def test_motion_zoom_and_a_morph(self):
        from tests.renderer_fixtures import concave_quad

        def scene():
            return build_scene(*_shapes(), concave_quad(0).set_fill(RED, opacity=.55, border_width=4),
                               resolution=(480, 270))

        def morph(alpha):
            return lambda scene: scene.mobjects[-1].set_points(concave_quad(alpha).get_points())

        steps = (None, lambda scene: scene.mobjects[1].shift(.3 * UP),
                 lambda scene: scene.camera.frame.scale(.4).shift([.2, -.1, 0]),
                 morph(.5), morph(2 / 3 + .001), lambda scene: scene.camera.frame.scale(2.5), morph(1))
        self.assert_matches(scene, "motion", steps)


if __name__ == "__main__":
    unittest.main()

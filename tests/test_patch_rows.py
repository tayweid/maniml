"""Row sources for the patch fill (MANIML_PATCH_SOURCE=rows, B5.1 of
docs/phase_b4_plan.md; the default wherever patches are drawn since B5.6,
with MANIML_PATCH_SOURCE=records the override): a path's rows travel in
place of its curve records and stroke instances, as its geometry and its
paint since B5.8, which each driver finalizes, a frame's in one dispatch
(row_finalize_table.wgsl).
Preparation and wire against the records' path, the native driver's
commands on a fake device and, with MANIML_TEST_GPU=1, pixels against the
records' path on the fixture corpus."""

import importlib.util
import os
import shutil
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
from maniml.web.gpu_program_geometry import (
    GEOMETRY_FLOATS, PAINT_FLOATS, join_rows, rows_hash, rows_key, split_rows,
)
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
            # What travels (B5.8): the geometry and the paint, which make
            # the rows again, the paint one row where uniform.
            geometry, paint = draws[0].row_parts[0]
            self.assertTrue(all(draw.row_parts[0][0] is geometry for draw in draws))
            self.assertEqual(join_rows(geometry, paint).tobytes(), sent.tobytes())
            self.assertEqual(geometry.shape, (len(sent), GEOMETRY_FLOATS))
            self.assertEqual(paint.shape, (1, PAINT_FLOATS))
            self.assertFalse(geometry.flags.writeable or paint.flags.writeable)
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
        geometry = {key for batch in header["batches"] for key in batch["rows"]}
        paints = {key for batch in header["batches"] for key in batch["row_paints"]}
        self.assertEqual(len(geometry), len(shapes), "one geometry per path, fill and stroke alike")
        self.assertEqual(len(paints), 4, "a paint per look: the three red squares share one")
        self.assertEqual(set(sent), geometry | paints)
        for batch in header["batches"]:
            self.assertIn("rows", batch)
            self.assertEqual(batch["fill_num_verts"], 0)
            if batch["pipeline"] == "patch":
                self.assertEqual(batch["border"]["hash"], rows_key(batch["rows"], batch["row_paints"]))
        # A still frame sends nothing.
        again, raw = _encode(_prepare(scene, meshes, patch_rows=True), scene, wire)
        self.assertEqual((raw, again["program_data"]), (b"", {}))
        self.assertTrue(all(batch["cached"] for batch in again["batches"]))
        # A moved square sends its geometry alone; its paint and its run's
        # table do not move.
        shapes[1].shift(.25 * UP)
        moved, raw = _encode(_prepare(scene, meshes, patch_rows=True), scene, wire)
        (key, span), = moved["program_data"].items()
        rows = np.frombuffer(shapes[1].data.tobytes(), dtype="<f4").reshape(-1, 17)
        self.assertEqual(key, rows_hash(split_rows(rows)[0]))
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

    def test_a_dim_sends_the_paint_and_no_rows(self):
        """B5.8: a change of colour or opacity alone (a dim at a pausepoint)
        sends each path's new paint, one row where uniform and shared by the
        paths that look alike, and none of the geometry, which the receiver
        holds; a stroke-only path's rows are compared every frame and keep
        their geometry too. A batch is named by its geometry, as a records
        run is by its layout and object table (the winding sign is the
        geometry's), so every batch the dim leaves in its groups is held;
        the first run's squares stop sharing a stencil count as they stop
        being opaque, which regroups it, as it does a records run. Undimmed,
        the paint the receiver no longer holds is sent again, and nothing
        else."""
        shapes = _shapes()
        scene, meshes, wire = build_scene(*shapes, resolution=(480, 270)), TriangleMeshCache(), GeometryCache()
        first, _ = _encode(_prepare(scene, meshes, patch_rows=True), scene, wire)
        geometry = [batch["rows"] for batch in first["batches"]]
        for shape in shapes[:-1]:
            shape.set_opacity(.05)
        shapes[-1].set_stroke(opacity=.05)
        dim, raw = _encode(_prepare(scene, meshes, patch_rows=True), scene, wire)
        self.assertEqual([batch["rows"] for batch in dim["batches"]], geometry, "the geometry keeps its name")
        self.assertFalse({key for keys in geometry for key in keys} & set(dim["program_data"]), "no rows travel")
        self.assertEqual(len(dim["program_data"]), 4)
        self.assertTrue(all(span["nbytes"] == 4 * PAINT_FLOATS for span in dim["program_data"].values()))
        self.assertEqual(len(raw), 4 * 4 * PAINT_FLOATS, "the paints are the payload")
        self.assertEqual((dim["border_data"], dim["object_data"]), ({}, {}))
        self.assertEqual([batch.get("cached", False) for batch in dim["batches"]], [False, True, True, True])
        self.assertNotEqual(dim["batches"][0]["border"]["layout"], first["batches"][0]["border"]["layout"])
        for shape in shapes[:-1]:
            shape.set_opacity(1)
        shapes[-1].set_stroke(opacity=1)
        back, raw = _encode(_prepare(scene, meshes, patch_rows=True), scene, wire)
        self.assertEqual([batch["rows"] for batch in back["batches"]], geometry)
        self.assertEqual(set(back["program_data"]), {key for batch in back["batches"] for key in batch["row_paints"]})

    def test_a_gradient_sends_a_paint_a_row(self):
        circle = Circle(radius=.8, fill_opacity=.7, stroke_width=3).set_color_by_gradient(RED, BLUE)
        header, raw = _encode(_prepare(build_scene(circle), TriangleMeshCache(), patch_rows=True),
                              build_scene(circle), GeometryCache())
        (paint,), = {tuple(batch["row_paints"]) for batch in header["batches"]}
        rows = len(circle.data)
        self.assertEqual(header["program_data"][paint]["nbytes"], 4 * PAINT_FLOATS * rows)
        span = header["program_data"][paint]
        painted = np.frombuffer(raw[span["offset"]:span["offset"] + span["nbytes"]], dtype="<f4").reshape(rows, 8)
        np.testing.assert_array_equal(painted[:, :4], circle.data["stroke_rgba"])
        np.testing.assert_array_equal(painted[:, 4:], circle.data["fill_rgba"])

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
        # B5.6: rows wherever patches are drawn, the forced Phase B and a
        # default stack that selects patches alike, unless
        # MANIML_PATCH_SOURCE=records says otherwise.
        scene, wire = build_scene(*_shapes()), GeometryCache()
        with patch.dict(os.environ):
            os.environ.pop("MANIML_PATCH_SOURCE", None)
            os.environ.pop("MANIML_FILL", None)
            header, _ = parse_geometry_message(serialize_scene(scene, wire, renderer="phase_b"))
            self.assertTrue(all("rows" in batch for batch in header["batches"]), "rows by default")
            self.assertEqual(header["border_data"], {}, "no curve records travel")
            # Phase A draws meshes: there is no patch to source, forced or
            # as a default stack told to draw meshes.
            header, _ = parse_geometry_message(serialize_scene(scene, wire, renderer="phase_a"))
            self.assertFalse(any("rows" in batch for batch in header["batches"]), "phase_a")
            with patch.dict(os.environ, MANIML_FILL="meshes"):
                header, _ = parse_geometry_message(serialize_scene(scene, wire, renderer="triangles"))
                self.assertFalse(any("rows" in batch for batch in header["batches"]), "meshes")
            # The default stack draws patches (2026-10-07) and sources them
            # as rows too.
            header, _ = parse_geometry_message(serialize_scene(scene, wire, renderer="triangles"))
            self.assertTrue(all("rows" in batch for batch in header["batches"]), "the default's patches")
            header, raw = parse_geometry_message(serialize_scene(scene, wire, renderer="phase_b"))
            self.assertTrue(raw, "a renderer change resends")
        with patch.dict(os.environ, MANIML_PATCH_SOURCE="records"):
            header, raw = parse_geometry_message(serialize_scene(scene, wire, renderer="phase_b"))
            self.assertFalse(any("rows" in batch for batch in header["batches"]), "records when asked")
            self.assertTrue(header["border_data"], "the switch resets the wire cache")
        with patch.dict(os.environ, MANIML_PATCH_SOURCE="rows"):
            header, raw = parse_geometry_message(serialize_scene(scene, wire, renderer="phase_b"))
            self.assertTrue(all("rows" in batch for batch in header["batches"]))
            self.assertTrue(header["program_data"], "and back: the switch resets the wire cache")
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
        self.renderer._modules["row_finalize"] = self.renderer._modules["row_finalize_table"] = object()
        self.scene = build_scene(*_shapes(), resolution=(480, 270))
        self.meshes, self.wire = TriangleMeshCache(), GeometryCache()

    def frame(self):
        frame = _prepare(self.scene, self.meshes, patch_rows=True)
        frame.samples, frame.supersample = 1, 1
        return _encode(frame, self.scene, self.wire)

    def events(self, name):
        return [event for event in self.renderer.device.events if event[0] == name]

    def table(self, write):
        """A finalize dispatch's table (B5.8), entry by entry, with the bytes
        of the geometry and paint each reads, from the scratch write."""
        region = write[3]
        words = np.frombuffer(region, dtype="<u4")
        entries = []
        for k in range(int(words[0])):
            geometry, paint, stride, output, curves, flags, first, _ = (int(w) for w in words[4 + 8 * k:12 + 8 * k])
            rows = 2 * curves + 1
            at = lambda word, count: region[16 + 4 * word:16 + 4 * (word + count)]
            entries.append({"geometry": at(geometry, 9 * rows), "paint": at(paint, 8 * rows if stride else 8),
                            "output": output, "curves": curves, "flags": flags, "first": first})
        return int(words[1]), entries

    def test_rows_are_finalized_in_one_dispatch_and_read_as_records_and_instances(self):
        header, raw = self.frame()
        self.renderer.render(header, raw)
        span = lambda key: raw[header["program_data"][key]["offset"]:][:header["program_data"][key]["nbytes"]]
        self.assertEqual(len(self.events("dispatch_workgroups")) - self.border_dispatches(header), 1,
                         "one dispatch finalizes every rows")
        # Its table: every member of every batch, in frame order, reading the
        # geometry and paint the message carries.
        write, = self.events("write_buffer")
        curves, entries = self.table(write)
        members = [(batch, key, paint) for batch in header["batches"]
                   for key, paint in zip(batch["rows"], batch["row_paints"])]
        self.assertEqual(len(entries), len(members))
        self.assertEqual(curves, sum(entry["curves"] for entry in entries))
        for entry, (batch, key, paint) in zip(entries, members):
            self.assertEqual(entry["geometry"], span(key))
            self.assertEqual(entry["paint"], span(paint))
            self.assertEqual(entry["flags"], int(batch["pipeline"] == "stroke"))
        # Each batch's records or instances, named by what they are made of,
        # copied from the scratch in one copy into a buffer of their own.
        outputs = self.renderer._row_outputs
        self.assertEqual(len(outputs), len(header["batches"]))
        copies = self.events("copy_buffer_to_buffer")
        self.assertEqual(len(copies), len(header["batches"]))
        for batch, copy in zip(header["batches"], copies):
            flags = int(batch["pipeline"] == "stroke")
            output = outputs[(flags, tuple(batch["rows"]), tuple(batch["row_paints"]))]
            self.assertIs(copy[3], output)
            self.assertEqual((copy[4], copy[5]), (0, output.size))
        # The border stage and the patch fill read the run's records; a
        # stroke draws its object's finalized instances.
        run = header["batches"][0]
        records = outputs[(0, tuple(run["rows"]), tuple(run["row_paints"]))]
        output, = [value for key, value in self.renderer._border_outputs.items() if key[0] == run["hash"]]
        self.assertIs(output["binding"]["entries"][0]["resource"]["buffer"], records)
        self.assertIs(output["patch_binding"]["entries"][0]["resource"]["buffer"], records)
        strokes = [batch for batch in header["batches"] if batch["pipeline"] == "stroke"]
        vertex_buffers = [event[2] for event in self.events("set_vertex_buffer")]
        for batch in strokes:
            self.assertIn(outputs[(1, tuple(batch["rows"]), tuple(batch["row_paints"]))], vertex_buffers)
        # The same frame again finalizes and copies nothing.
        before = len(self.renderer.device.events)
        header, raw = self.frame()
        self.renderer.render(header, raw)
        later = [event[0] for event in self.renderer.device.events[before:]]
        self.assertNotIn("copy_buffer_to_buffer", later)
        self.assertNotIn("dispatch_workgroups", later)
        # A moved square: its run's members finalized again in one dispatch
        # and one copy; the run's old records retire.
        self.scene.mobjects[1].shift(.1 * UP)
        before = len(self.renderer.device.events)
        header, raw = self.frame()
        self.renderer.render(header, raw)
        later = self.renderer.device.events[before:]
        self.assertEqual(sum(event[0] == "copy_buffer_to_buffer" for event in later), 1)
        write, = [event for event in later if event[0] == "write_buffer"]
        self.assertEqual(len(self.table(write)[1]), 4)
        self.assertEqual(len(self.renderer._row_outputs), len(header["batches"]))
        self.assertTrue(records.destroyed, "the run's old records retire")
        # A dim: no rows travel, and every batch is finalized again from the
        # geometry the driver holds and the paint the message carries.
        for shape in self.scene.mobjects[:-1]:
            shape.set_opacity(.05)
        self.scene.mobjects[-1].set_stroke(opacity=.05)
        before = len(self.renderer.device.events)
        header, raw = self.frame()
        self.assertTrue(all(span["nbytes"] == 32 for span in header["program_data"].values()))
        self.renderer.render(header, raw)
        later = self.renderer.device.events[before:]
        write, = [event for event in later if event[0] == "write_buffer"]
        self.assertEqual(len(self.table(write)[1]), sum(len(batch["rows"]) for batch in header["batches"]))

    def test_null_row_paints_are_not_a_recording_before_b58(self):
        """Only a batch without the key names seventeen-column rows: one
        whose row_paints is present and null is malformed, here as in the
        page (resolveRows) and the player (rowsLayout), even over rows a
        recording before B5.8 would name."""
        header, raw = legacy_rows_message(*self.frame())
        for batch in header["batches"]:
            batch["row_paints"] = None
        with self.assertRaises(ValueError):
            self.renderer.render(header, raw)
        self.assertFalse(any(event[0] == "submit" for event in self.renderer.device.events))
        self.assertEqual((self.renderer._row_outputs, self.renderer._row_sources), ({}, {}))

    def border_dispatches(self, header):
        return sum(1 for batch in header["batches"] if batch["pipeline"] == "patch")

    def test_a_recording_before_b58_names_seventeen_column_rows(self):
        """A batch without row_paints names VMobject's rows, whose paint is
        their own: finalized in the same dispatch, flagged, reading them."""
        header, raw = legacy_rows_message(*self.frame())
        self.renderer.render(header, raw)
        write, = self.events("write_buffer")
        words = np.frombuffer(write[3], dtype="<u4")
        flags = [int(words[4 + 8 * k + 5]) for k in range(int(words[0]))]
        members = [int(batch["pipeline"] == "stroke") | 2 for batch in header["batches"] for _ in batch["rows"]]
        self.assertEqual(flags, members)
        self.assertEqual(len(self.renderer._row_outputs), len(header["batches"]))

    def test_rows_and_program_sources_share_one_table(self):
        """One table on the wire names program sources and row sources, so
        a recording before B5.8 can name as a path's rows the rows an
        earlier frame sent as a program's source, and the reverse: the
        driver reads either from the other's, as it did when one map held
        both."""
        header, raw = legacy_rows_message(*self.frame())
        key = header["batches"][-1]["rows"][0]
        ref = header["program_data"].pop(key)
        data = raw[ref["offset"]:ref["offset"] + ref["nbytes"]]
        self.renderer._program_sources[key] = {
            "data": data, "buffer": self.renderer.device.create_buffer_with_data(data=data, usage=0)}
        self.renderer.render(header, raw)
        write, = self.events("write_buffer")
        self.assertIn(data, write[3], "the rows a program held, finalized")
        self.assertNotIn(key, self.renderer._program_sources, "no program holds them after the frame")
        self.assertIs(self.renderer._program_bytes(key, {}), self.renderer._row_sources[key],
                      "and a program's source the rows hold")

    def test_malformed_row_sources_are_rejected_without_submission(self):
        header, raw = self.frame()
        run = header["batches"][0]
        span = header["program_data"][run["rows"][1]]
        paint = header["program_data"][run["row_paints"][-1]]
        for change in (
            lambda h: h["batches"][0].__setitem__("rows", run["rows"][:2]),
            lambda h: h["batches"][0]["rows"].reverse(),
            lambda h: h["batches"][0].__setitem__("rows", "a" * 32),
            lambda h: h["program_data"].pop(run["rows"][1]),
            lambda h: h["program_data"].__setitem__(run["rows"][1], {**span, "nbytes": span["nbytes"] - 36}),
            lambda h: h["batches"][0].__setitem__("row_paints", run["row_paints"][:3]),
            lambda h: h["batches"][0].__setitem__("row_paints", "b" * 32),
            lambda h: h["program_data"].pop(run["row_paints"][-1]),
            lambda h: h["program_data"].__setitem__(run["row_paints"][-1], {**paint, "nbytes": paint["nbytes"] - 4}),
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
            self.assertEqual((self.renderer._row_outputs, self.renderer._row_sources, self.renderer._program_sources),
                             ({}, {}, {}))


class RowFinalizePlan(unittest.TestCase):
    """gpu_program_geometry.plan_row_finalize and the page's planRows
    group a frame's changed row sources alike: a dispatch holds what fits
    the budget in both bindings, the region counting its header once."""

    @staticmethod
    def pair(curves=1, paint_words=None):
        """Two members of their own geometry and paint (a paint a row
        unless ``paint_words``)."""
        geometry = 9 * (2 * curves + 1)
        paint = paint_words or 8 * (2 * curves + 1)
        return [(f"g{k}", geometry, f"p{k}", paint, curves, 0) for k in (1, 2)]

    def cases(self):
        from maniml.web import gpu_program_geometry as programs
        rng = np.random.default_rng(58)
        mixed = []
        for index in range(60):
            curves = int(rng.integers(1, 40))
            flags = int(rng.integers(0, 2))
            if rng.random() < .2:
                mixed.append((f"legacy{index % 7}", 17 * (2 * curves + 1), None, None, curves,
                              flags | programs.ROW_LEGACY))
                continue
            # Geometry and paint names reused, as paths that look alike share them.
            geometry = f"g{int(rng.integers(0, 25))}-{curves}"
            uniform = rng.random() < .6
            paint = f"p{int(rng.integers(0, 6))}" if uniform else f"p{index}-{curves}"
            mixed.append((geometry, 9 * (2 * curves + 1), paint, 8 if uniform else 8 * (2 * curves + 1), curves,
                          flags))
        # The region of one dispatch of self.pair() is exactly 488 bytes; of
        # ten curves each and one shared paint, its output 3520.
        cases = [("region at the budget", self.pair(), budget) for budget in (480, 487, 488, 496, 504)]
        shared = [(name, words, "p", 8, curves, flags) for name, words, _, _, curves, flags in self.pair(10)]
        cases += [("output at the budget", shared, budget) for budget in (3519, 3520, 3521)]
        cases += [("a member larger than the budget", [*self.pair(), ("huge", 9 * 201, "p", 8, 100, 0),
                                                        *self.pair()], 600)]
        cases += [("mixed", mixed, budget) for budget in (1024, 4096, 20000, 1 << 20)]
        return [(label, members, budget, programs.plan_row_finalize(members, budget))
                for label, members, budget in cases]

    def test_a_dispatch_that_fits_its_budget_exactly_stays_whole(self):
        plans = {budget: plan for label, _, budget, plan in self.cases() if label == "region at the budget"}
        self.assertEqual(plans[488][0]["region_bytes"], 488)
        self.assertEqual([len(plans[budget]) for budget in (480, 487, 488, 496, 504)], [2, 2, 1, 1, 1])
        outputs = {budget: plan for label, _, budget, plan in self.cases() if label == "output at the budget"}
        self.assertEqual([len(outputs[budget]) for budget in (3519, 3520, 3521)], [2, 1, 1])
        for label, _, budget, plan in self.cases():
            for dispatch in plan:
                if len(dispatch["entries"]) > 1:
                    self.assertLessEqual(max(dispatch["region_bytes"], dispatch["output_bytes"]), budget, label)

    @unittest.skipIf(shutil.which("node") is None, "node not available")
    def test_the_page_plans_as_python_does(self):
        import json
        import subprocess
        import tempfile
        from pathlib import Path
        keys = ("entries", "inputs", "region_bytes", "output_bytes", "curves")
        cases = [{"label": label, "members": members, "budget": budget,
                  "plans": json.loads(json.dumps([{key: d[key] for key in keys} for d in plan]))}
                 for label, members, budget, plan in self.cases()]
        self.assertGreater(sum(len(case["plans"]) > 1 for case in cases), 5, "the budgets split")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "plans.json"
            path.write_text(json.dumps({"cases": cases}))
            result = subprocess.run(["node", str(Path(__file__).with_name("generated_webgpu_commands.cjs")),
                                     "rowPlansAgree", str(path)], capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout), {"cases": len(cases)})


def legacy_rows_message(header, payload):
    """The message a serializer before B5.8 wrote for the same frame: each
    rows batch naming VMobject's seventeen-column rows (its geometry and
    paint joined), no row_paints, a patch run's border named by rows_key of
    the rows alone; the rest of the payload as it was."""
    import copy
    header, payload = copy.deepcopy(header), bytes(payload)
    definitions, parts = {}, [payload]
    offset = len(payload)

    def span(key):
        ref = header["program_data"][key]
        return np.frombuffer(payload[ref["offset"]:ref["offset"] + ref["nbytes"]], dtype="<f4")

    replaced = {key for batch in header["batches"] for key in (*batch.get("rows", ()), *batch.get("row_paints", ()))}
    for batch in header["batches"]:
        if "rows" not in batch:
            continue
        keys = []
        for key, paint in zip(batch["rows"], batch.pop("row_paints")):
            rows = join_rows(span(key).reshape(-1, GEOMETRY_FLOATS), span(paint).reshape(-1, PAINT_FLOATS))
            digest = rows_hash(rows)
            if digest not in definitions:
                definitions[digest] = {"offset": offset, "nbytes": rows.nbytes}
                parts.append(rows.tobytes())
                offset += rows.nbytes
            keys.append(digest)
        batch["rows"] = keys
        if "border" in batch:
            batch["border"]["hash"] = rows_key(keys)
    header["program_data"] = {**{key: ref for key, ref in header["program_data"].items() if key not in replaced},
                              **definitions}
    return header, b"".join(parts)


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

    def test_a_recording_before_b58_draws_the_same_pixels(self):
        """Seventeen-column rows without their paint beside them, as a
        recording made before B5.8 names them, drawn by a driver of their
        own: the pixels of the geometry and paint they were split into."""
        scene = build_scene(*_shapes(), resolution=(480, 270))
        frame = _prepare(scene, TriangleMeshCache(), patch_rows=True)
        frame.samples, frame.supersample = 4, 2
        header, payload = _encode(frame, scene, GeometryCache())
        split = np.asarray(self.drivers[0].render(header, payload), dtype=int)
        joined = np.asarray(self.drivers[1].render(*legacy_rows_message(header, payload)), dtype=int)
        self.assertEqual(np.abs(split - joined).max(), 0)

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


@unittest.skipUnless(os.environ.get("MANIML_TEST_GPU") == "1", "GPU image comparison not requested")
class RowFinalizeInSeveralDispatches(unittest.TestCase):
    """The native driver's finalize past its budget (B5.8): a frame's
    changed rows planned into several dispatches at aligned regions of one
    input scratch, the output scratch reused by each, a batch's members
    split across dispatches, draw what one dispatch draws and what the
    records draw, through dims, a move, an undim, an alpha change, a zoom,
    a recolour and a gradient flip."""

    @staticmethod
    def scene():
        gradient = Circle(radius=.8, fill_opacity=.7, stroke_width=3).set_color_by_gradient(RED, BLUE)
        return build_scene(*_shapes(), gradient.shift([3, 1, 0]), resolution=(480, 270))

    STEPS = (None,
             lambda scene: [shape.set_opacity(.15) for shape in scene.mobjects[:3]],
             lambda scene: scene.mobjects[3].shift(.3 * UP),
             lambda scene: [shape.set_opacity(1) for shape in scene.mobjects[:3]],
             lambda scene: scene.mobjects[-1].set_fill(opacity=.2),
             lambda scene: scene.camera.frame.scale(.5),
             lambda scene: [shape.set_fill(BLUE) for shape in scene.mobjects],
             lambda scene: scene.mobjects[-1].set_color_by_gradient(BLUE, RED))

    def frames(self, rows, budget=None):
        from maniml.web import gpu_program_geometry as programs
        from maniml.web.wgpu_renderer import WgpuRenderer
        _prepare.tessellator = LyonFillTessellator()
        driver, cache, wire, scene = WgpuRenderer(), TriangleMeshCache(), GeometryCache(), self.scene()
        plans, finalize = [], driver._finalize_rows

        def spy(changed, *args):
            # Each finalize's dispatches, as the targets of their entries.
            budget_now = min(programs.ROW_FINALIZE_BUDGET, args[2])
            plans.append([[id(changed[entry[0]][1]) for entry in dispatch["entries"]]
                          for dispatch in programs.plan_row_finalize([m for m, _, _ in changed], budget_now)])
            return finalize(changed, *args)

        driver._finalize_rows = spy
        images = []
        try:
            with patch.object(programs, "ROW_FINALIZE_BUDGET", budget or programs.ROW_FINALIZE_BUDGET):
                for step in self.STEPS:
                    if step is not None:
                        step(scene)
                    frame = _prepare(scene, cache, patch_rows=rows)
                    frame.samples, frame.supersample = 4, 2
                    images.append(np.asarray(driver.render(*_encode(frame, scene, wire)), dtype=int))
        finally:
            driver.close()
        return images, plans

    def test_several_dispatches_draw_what_one_draws(self):
        many, many_plans = self.frames(True, budget=1024)
        one, one_plans = self.frames(True)
        records, _ = self.frames(False)
        self.assertEqual(len(one_plans), len(self.STEPS) - 1, "every frame but the zoom finalizes rows")
        self.assertTrue(all(len(plan) == 1 for plan in one_plans))
        self.assertEqual(len(many_plans), len(one_plans))
        self.assertGreaterEqual(max(len(plan) for plan in many_plans), 3, "several dispatches")
        self.assertTrue(any(len({target for dispatch in plan for target in set(dispatch)})
                            < sum(len(set(dispatch)) for dispatch in plan) for plan in many_plans),
                        "a batch's members split across dispatches")
        for index, (a, b, c) in enumerate(zip(many, one, records)):
            if index:
                self.assertTrue(np.any(b != one[index - 1]), f"step {index} moves pixels")
            self.assertEqual(np.abs(a - b).max(), 0, f"step {index}: several dispatches against one")
            self.assertLessEqual(np.abs(b - c).max(), 1, f"step {index}: rows against records")


@unittest.skipUnless(os.environ.get("MANIML_TEST_GPU") == "1", "GPU kernel comparison not requested")
class RowTableKernel(unittest.TestCase):
    """row_finalize_table.wgsl (B5.8, a frame's row sources in one
    dispatch) against row_finalize.wgsl (a program's rows, one dispatch
    each), which it repeats: the same curve records and stroke instances,
    word for word, from a path's geometry and paint and from its
    seventeen-column rows, on the fixture corpus' paths, a gradient and a
    path whose curves overflow the density."""

    def rows(self):
        from tests.renderer_quality_fixtures import build_quality_frame
        _prepare.tessellator = LyonFillTessellator()
        gradient = Circle(radius=.8, fill_opacity=.7, stroke_width=3).set_color_by_gradient(RED, BLUE)
        scenes = [case.build() for case in renderer_cases()]
        scenes += [build_quality_frame(content, "normal").scene for content in ("tex", "border")]
        scenes.append(build_scene(*_shapes(), gradient))
        found = {}
        for scene in scenes:
            for draw in _prepare(scene, TriangleMeshCache(), coalesce=False, patch_rows=True).draws:
                for rows, parts in zip(draw.rows or (), draw.row_parts or ()):
                    found[rows.tobytes()] = (rows, parts)
        huge = np.array(_shapes()[0].data).view("<f4").reshape(-1, 17).copy()
        huge[:, :3] *= 3e19
        found[huge.tobytes()] = (huge, split_rows(huge))
        return list(found.values())

    def test_the_table_kernel_writes_the_program_kernel_words(self):
        import struct
        import wgpu
        from maniml.web.wgpu_renderer import WgpuRenderer
        from maniml.web import gpu_program_geometry as programs
        renderer = WgpuRenderer()
        device = renderer.device
        try:
            usage = wgpu.BufferUsage.STORAGE | wgpu.BufferUsage.COPY_SRC
            single = renderer._program_pipeline("row_finalize")
            table = device.create_compute_pipeline(layout="auto", compute={
                "module": renderer._modules["row_finalize_table"], "entry_point": "cs_main"})
            cases = self.rows()
            self.assertGreater(len(cases), 40)
            members, words, expected = [], {}, []
            for index, (rows, (geometry, paint)) in enumerate(cases):
                curves = (len(rows) - 1) // 2
                source = device.create_buffer_with_data(data=rows.tobytes(), usage=wgpu.BufferUsage.STORAGE)
                records = device.create_buffer(size=176 * curves, usage=usage)
                strokes = device.create_buffer(size=204 * curves, usage=usage)
                params = device.create_buffer_with_data(data=struct.pack("<IIII", curves, 17, 0, 0),
                                                        usage=wgpu.BufferUsage.UNIFORM)
                encoder = device.create_command_encoder()
                compute = encoder.begin_compute_pass()
                compute.set_pipeline(single)
                compute.set_bind_group(0, device.create_bind_group(layout=single.get_bind_group_layout(0), entries=[
                    {"binding": 0, "resource": {"buffer": params, "size": 16}}]))
                compute.set_bind_group(1, device.create_bind_group(layout=single.get_bind_group_layout(1), entries=[
                    {"binding": 0, "resource": {"buffer": source, "size": rows.nbytes}},
                    {"binding": 1, "resource": {"buffer": records, "size": 176 * curves}},
                    {"binding": 2, "resource": {"buffer": strokes, "size": 204 * curves}}]))
                compute.dispatch_workgroups((curves + 63) // 64)
                compute.end()
                device.queue.submit([encoder.finish()])
                expected.append((bytes(device.queue.read_buffer(records)), bytes(device.queue.read_buffer(strokes))))
                words[("g", index)], words[("p", index)], words[("l", index)] = (
                    geometry.tobytes(), paint.tobytes(), rows.tobytes())
                for flags in (0, programs.ROW_STROKES):
                    members.append((("g", index), geometry.size, ("p", index), paint.size, curves, flags))
                    members.append((("l", index), rows.size, None, None, curves, flags | programs.ROW_LEGACY))
            dispatch, = programs.plan_row_finalize(members, budget=1 << 30)
            region = programs.pack_row_region(dispatch, words.__getitem__)
            inputs = device.create_buffer_with_data(data=region, usage=wgpu.BufferUsage.STORAGE)
            output = device.create_buffer(size=dispatch["output_bytes"], usage=usage)
            encoder = device.create_command_encoder()
            compute = encoder.begin_compute_pass()
            compute.set_pipeline(table)
            compute.set_bind_group(0, device.create_bind_group(layout=table.get_bind_group_layout(0), entries=[
                {"binding": 0, "resource": {"buffer": inputs, "size": len(region)}}]))
            compute.set_bind_group(1, device.create_bind_group(layout=table.get_bind_group_layout(1), entries=[
                {"binding": 0, "resource": {"buffer": output, "size": dispatch["output_bytes"]}}]))
            compute.dispatch_workgroups(*programs_dispatch(dispatch["curves"]))
            compute.end()
            device.queue.submit([encoder.finish()])
            written = bytes(device.queue.read_buffer(output))
            for entry in dispatch["entries"]:
                index, flags = members[entry[0]][0][1], entry[6]
                size = 4 * entry[5] * (51 if flags & programs.ROW_STROKES else 44)
                got = written[4 * entry[4]:4 * entry[4] + size]
                want = expected[index][1 if flags & programs.ROW_STROKES else 0]
                self.assertEqual(got, want, f"path {index}, flags {flags}")
        finally:
            renderer.close()


def programs_dispatch(curves):
    from maniml.web.gpu_net_geometry import dispatch_shape
    return dispatch_shape(-(-curves // 64), 65535)


if __name__ == "__main__":
    unittest.main()

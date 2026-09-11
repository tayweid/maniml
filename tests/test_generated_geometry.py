"""Derived geometry wire identity, validation and seekable recording contracts."""

import base64
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import unittest
from unittest.mock import patch

import numpy as np

from maniml.web.generated_geometry import serialize_generated_frame
from maniml.web.fill_paint import MAX_PAINT_SAMPLES, PAINT_HASH_PREFIX
from maniml.web.geometry import GeometryCache, SURFACE_DTYPE, parse_geometry_message, serialize_scene
from maniml.web.triangle_scene import TriangleDraw, TriangleFrame

# Writes into public arrays directly to prove the byte comparison sees it:
# the MANIML_RENDER_CACHE=bytes policy (see tests/test_render_cache_revision.py).
bytes_policy = patch.dict(os.environ, {"MANIML_RENDER_CACHE": "bytes"})


def quad():
    vertices = np.zeros(4, dtype=SURFACE_DTYPE)
    vertices["point"] = [[-1, -1, 0], [1, -1, 0], [1, 1, 0], [-1, 1, 0]]
    vertices["d_normal_point"] = vertices["point"] + [0, 0, .001]
    vertices["rgba"] = [1, .2, .3, .4]
    return TriangleDraw("surface", vertices, {"frame_scale": 1, "shading": [0, 0, 0]},
                        np.array([0, 1, 2, 0, 2, 3], dtype="u4"), 6)


def encode(draws, cache=None):
    return serialize_generated_frame(TriangleFrame((32, 16), (0, 0, 0, 0), 4, draws),
                                     {"frame_scale": 1}, cache)


def painted_quad(color=(1, 0, 0, .5)):
    from maniml.web.triangle_scene import _readonly
    draw = quad()
    paint = np.zeros(24, dtype="<f4")
    paint[3] = paint[4] = paint[9] = 1
    paint[12:16] = color
    return replace(draw, pipeline="paint", vertices=_readonly(draw.vertices),
                   indices=_readonly(draw.indices), paint=_readonly(paint))


class GeneratedGeometryWire(unittest.TestCase):
    def test_vertex_index_boundary_is_part_of_identity(self):
        draw, cache = quad(), GeometryCache()
        draw.vertices[3] = np.zeros((), dtype=SURFACE_DTYPE)
        draw.indices = np.array([0, 1, 2], dtype="u4")
        draw.count = 3
        # Identical concatenated bytes, but the next draw starts with three
        # zero indices and should therefore draw no covered triangle.
        other = replace(draw, vertices=draw.vertices[:3],
                        indices=np.array([0] * 10 + [0, 1, 2], dtype="u4"))
        self.assertEqual(draw.vertices.tobytes() + draw.indices.tobytes(),
                         other.vertices.tobytes() + other.indices.tobytes())
        first, _ = parse_geometry_message(encode([draw], cache))
        second, raw = parse_geometry_message(encode([other], cache))
        self.assertNotEqual(first["batches"][0]["hash"], second["batches"][0]["hash"])
        self.assertNotIn("cached", second["batches"][0])
        self.assertTrue(raw)

    def test_connectivity_and_pipeline_are_part_of_cache_identity(self):
        draw, cache = quad(), GeometryCache()
        first, payload = parse_geometry_message(encode([draw], cache))
        same, empty = parse_geometry_message(encode([draw], cache))
        self.assertTrue(same["batches"][0]["cached"])
        self.assertEqual(empty, b"")
        self.assertEqual(same["batches"][0]["index_count"], 6)
        alternate = replace(draw, indices=np.array([0, 1, 3, 1, 2, 3], dtype="u4"))
        changed, raw = parse_geometry_message(encode([alternate], cache))
        self.assertNotEqual(changed["batches"][0]["hash"], first["batches"][0]["hash"])
        self.assertEqual(raw[:draw.vertices.nbytes], payload[:draw.vertices.nbytes])
        np.testing.assert_array_equal(np.frombuffer(raw, "<u4", offset=draw.vertices.nbytes), alternate.indices)
        depth, _ = parse_geometry_message(encode([replace(alternate, pipeline="surface_depth")], cache))
        self.assertNotEqual(depth["batches"][0]["hash"], changed["batches"][0]["hash"])

    def test_absent_geometry_is_retired_and_returning_geometry_is_resent(self):
        draw, cache = quad(), GeometryCache()
        encode([draw], cache)
        encode([], cache)
        self.assertFalse(cache.sent)
        returning, raw = parse_geometry_message(encode([draw], cache))
        self.assertNotIn("cached", returning["batches"][0])
        self.assertEqual(len(raw), draw.vertices.nbytes + draw.indices.nbytes)

    def test_camera_updates_send_fresh_uniforms_without_resending_geometry(self):
        draw, cache = quad(), GeometryCache()
        encode([draw], cache)
        changed = replace(draw, uniforms={**draw.uniforms, "clip_plane": [1, 0, 0, 2]})
        header, raw = parse_geometry_message(encode([changed], cache))
        self.assertEqual(header["batches"][0]["uniforms"],
                         {"shading": [0, 0, 0], "clip_plane": [1, 0, 0, 2]})
        self.assertEqual(raw, b"")

    def test_invalid_draw_never_advances_sender_cache(self):
        draw, cache = quad(), GeometryCache()
        cache.sent.add("previous")
        for invalid in (
            replace(draw, indices=np.array([-1, 0, 1])),
            replace(draw, indices=np.array([0, 1, 4])),
            replace(draw, indices=np.array([0., 1., 2.])),
            replace(draw, count=7), replace(draw, count=-1),
            replace(draw, instances=True), replace(draw, vertices=draw.vertices.reshape(2, 2)),
        ):
            with self.subTest(invalid=invalid.count):
                with self.assertRaises(ValueError):
                    encode([draw, invalid], cache)
                self.assertEqual(cache.sent, {"previous"})

    def test_shared_camera_values_accept_numpy_and_nested_sequences(self):
        camera = {"view": np.eye(4), "light_position": np.array([1., 2., 3.])}
        for view in (np.eye(4), np.eye(4).tolist(), list(np.eye(4))):
            draw = replace(quad(), uniforms={"view": view,
                "light_position": (1., 2., 3.), "shading": np.array([.2, .3, .4])})
            header, _ = parse_geometry_message(serialize_generated_frame(
                TriangleFrame((32, 16), (0, 0, 0, 0), 4, [draw]), camera))
            self.assertEqual(header["batches"][0]["uniforms"], {"shading": [.2, .3, .4]})
        draw.uniforms["view"] = np.eye(4) * 2
        header, _ = parse_geometry_message(serialize_generated_frame(
            TriangleFrame((32, 16), (0, 0, 0, 0), 4, [draw]), camera))
        self.assertEqual(header["batches"][0]["uniforms"]["view"], (np.eye(4) * 2).tolist())

    def test_empty_operations_do_not_create_zero_byte_gpu_buffers(self):
        header, raw = parse_geometry_message(encode([replace(quad(), count=0)]))
        self.assertEqual(header["batches"], [])
        self.assertEqual(raw, b"")

    def test_immutable_mesh_digest_is_reused_and_absent_entries_retire(self):
        from maniml.web.triangle_scene import _readonly
        for dtype in (np.dtype("u4"), np.dtype("u4").newbyteorder("<")):
            with self.subTest(byteorder=dtype.byteorder):
                draw, cache = quad(), GeometryCache()
                draw = replace(draw, vertices=_readonly(draw.vertices),
                               indices=_readonly(draw.indices.astype(dtype)))
                first = encode([draw], cache)
                with patch("maniml.web.generated_geometry.hashlib.blake2b",
                           side_effect=AssertionError("rehashed frozen mesh")):
                    header, raw = parse_geometry_message(encode([draw], cache))
                self.assertTrue(header["batches"][0]["cached"])
                self.assertEqual(raw, b"")
                self.assertEqual(len(cache.generated_payloads), 1)
                encode([], cache)
                self.assertEqual(cache.generated_payloads, {})
                self.assertEqual(encode([draw], cache), first)

    @bytes_policy

    def test_nine_production_fills_reuse_digests_only_for_immutable_draws(self):
        from maniml.mobject.geometry import Square
        from maniml.web.triangle_geometry import LyonFillTessellator
        from maniml.web.triangle_scene import TriangleMeshCache, prepare_triangle_frame
        from tests.renderer_fixtures import build_scene

        tessellator = LyonFillTessellator()
        for coalesce in (False, True):
            with self.subTest(coalesce=coalesce):
                shapes = [Square(side_length=.4, fill_opacity=1, stroke_width=0,
                                 fill_border_width=0).shift([i % 3 - 1, i // 3 - 1, 0])
                          for i in range(9)]
                scene, meshes, cache = build_scene(*shapes), TriangleMeshCache(), GeometryCache()
                source_bytes = [shape.get_points().tobytes() for shape in shapes]

                def prepare():
                    return prepare_triangle_frame(scene, tessellator, mesh_cache=meshes,
                                                  fill_borders=True, coalesce=coalesce)

                first = prepare()
                self.assertEqual(len(first.draws), 1 if coalesce else 9)
                serialize_generated_frame(first, scene.camera.uniforms, cache)
                second = prepare()
                if not coalesce:
                    for before, after in zip(first.draws, second.draws):
                        self.assertIs(before.vertices, after.vertices)
                        self.assertIs(before.indices, after.indices)
                with patch("maniml.web.generated_geometry.hashlib.blake2b",
                           wraps=hashlib.blake2b) as digest:
                    header, raw = parse_geometry_message(serialize_generated_frame(
                        second, scene.camera.uniforms, cache))
                self.assertEqual(digest.call_count, 1 if coalesce else 0)
                self.assertTrue(all(batch.get("cached") for batch in header["batches"]))
                self.assertEqual(raw, b"")
                self.assertEqual(len(cache.generated_payloads), 0 if coalesce else 9)
                self.assertEqual([shape.get_points().tobytes() for shape in shapes], source_bytes)

                # A direct public-array edit must still replace the affected
                # mesh, even when no mobject revision was explicitly bumped.
                shapes[0].get_points()[:, 0] += .125
                changed = prepare()
                header, raw = parse_geometry_message(serialize_generated_frame(
                    changed, scene.camera.uniforms, cache))
                self.assertEqual(sum(not batch.get("cached") for batch in header["batches"]), 1)
                self.assertTrue(raw)

    def test_mutable_and_converted_indices_hash_actual_content(self):
        from maniml.web.triangle_scene import _readonly
        values = [0, 1, 2, 0, 2, 3]
        for layout, indices in (
            ("native", np.array(values, dtype="u4")),
            ("explicit_little", np.array(values, dtype=np.dtype("u4").newbyteorder("<"))),
            ("big_endian", np.array(values, dtype=">u4")),
            ("noncontiguous", np.repeat(np.array(values, dtype="u4"), 2)[::2]),
            ("wide_integer", np.array(values, dtype="i8")),
        ):
            with self.subTest(layout=layout):
                draw, cache = quad(), GeometryCache()
                draw = replace(draw, vertices=_readonly(draw.vertices), indices=indices)
                first, payload = parse_geometry_message(encode([draw], cache))
                batch = first["batches"][0]
                self.assertEqual(payload[batch["index_offset"]:], np.array(values, dtype="<u4").tobytes())
                with patch("maniml.web.generated_geometry.hashlib.blake2b",
                           wraps=hashlib.blake2b) as digest:
                    same, raw = parse_geometry_message(encode([draw], cache))
                self.assertEqual(digest.call_count, 1)
                self.assertTrue(same["batches"][0]["cached"])
                self.assertEqual(raw, b"")
                self.assertEqual(cache.generated_payloads, {})
                indices[:] = [0, 1, 3, 1, 2, 3]
                changed, raw = parse_geometry_message(encode([draw], cache))
                self.assertNotEqual(changed["batches"][0]["hash"], batch["hash"])
                self.assertTrue(raw)

    def test_readonly_owned_arrays_cannot_be_trusted_as_immutable(self):
        draw, cache = quad(), GeometryCache()
        draw.vertices.setflags(write=False)
        before, _ = parse_geometry_message(encode([draw], cache))
        self.assertEqual(cache.generated_payloads, {})
        draw.vertices.setflags(write=True)
        draw.vertices["point"][0, 0] += .125
        after, raw = parse_geometry_message(encode([draw], cache))
        self.assertNotEqual(before["batches"][0]["hash"], after["batches"][0]["hash"])
        self.assertTrue(raw)

    def test_paint_definitions_are_binary_independent_and_deduplicated(self):
        first, cache = painted_quad(), GeometryCache()
        second = replace(first, paint=painted_quad((0, 0, 1, .75)).paint)
        header, raw = parse_geometry_message(encode([first, second, first], cache))
        from maniml.web.geometry import GEOMETRY_FORMAT_VERSION
        self.assertEqual(header["format_version"], GEOMETRY_FORMAT_VERSION)
        self.assertEqual(len({batch["hash"] for batch in header["batches"]}), 1)
        self.assertEqual(len(header["paint_data"]), 2)
        for batch, draw in zip(header["batches"], (first, second, first)):
            self.assertNotIn("paint", batch)
            digest = hashlib.blake2b(PAINT_HASH_PREFIX + draw.paint.tobytes(), digest_size=16).hexdigest()
            self.assertEqual(batch["paint_hash"], digest)
            ref = header["paint_data"][digest]
            self.assertEqual(ref["nbytes"], 96)
            self.assertEqual(raw[ref["offset"]:ref["offset"] + ref["nbytes"]], draw.paint.tobytes())
        with patch("maniml.web.generated_geometry.hashlib.blake2b",
                   side_effect=AssertionError("rehashed immutable geometry or paint")):
            unchanged, raw = parse_geometry_message(encode([first, second], cache))
        self.assertEqual(raw, b"")
        self.assertEqual(unchanged["paint_data"], {})
        self.assertTrue(all(batch["cached"] for batch in unchanged["batches"]))
        self.assertEqual(len(cache.generated_paints), 2)

    def test_paint_absence_return_and_reset_resend_definitions(self):
        red, cache = painted_quad(), GeometryCache()
        blue = replace(red, paint=painted_quad((0, 0, 1, .75)).paint)
        first, _ = parse_geometry_message(encode([red, blue], cache))
        red_hash, blue_hash = [batch["paint_hash"] for batch in first["batches"]]
        encode([blue], cache)
        self.assertNotIn(f"paint:{red_hash}", cache.sent)
        self.assertIn(f"paint:{blue_hash}", cache.sent)
        self.assertEqual(len(cache.generated_paints), 1)
        returned, raw = parse_geometry_message(encode([red], cache))
        self.assertTrue(returned["batches"][0]["cached"])
        self.assertEqual(set(returned["paint_data"]), {red_hash})
        self.assertEqual(raw, red.paint.tobytes())
        cache.reset()
        reset, raw = parse_geometry_message(encode([red], cache))
        self.assertNotIn("cached", reset["batches"][0])
        self.assertEqual(set(reset["paint_data"]), {red_hash})
        self.assertGreater(len(raw), red.paint.nbytes)
        encode([], cache)
        self.assertEqual(cache.sent, set())
        self.assertEqual(cache.generated_paints, {})
        returning, _ = parse_geometry_message(encode([red], cache))
        self.assertEqual(set(returning["paint_data"]), {red_hash})

    def test_mutable_paint_is_validated_and_hashed_after_every_direct_edit(self):
        original = painted_quad()
        for layout, coefficients in (
            ("list", original.paint.tolist()),
            ("float64", original.paint.astype("f8")),
            ("big_endian", original.paint.astype(">f4")),
            ("noncontiguous", np.repeat(original.paint, 2)[::2]),
            ("owned_readonly", original.paint.copy()),
        ):
            with self.subTest(layout=layout):
                if layout == "owned_readonly":
                    coefficients.setflags(write=False)
                draw, cache = replace(original, paint=coefficients), GeometryCache()
                first, _ = parse_geometry_message(encode([draw], cache))
                self.assertEqual(cache.generated_paints, {})
                with patch("maniml.web.generated_geometry.hashlib.blake2b", wraps=hashlib.blake2b) as digest:
                    same, raw = parse_geometry_message(encode([draw], cache))
                self.assertEqual(digest.call_count, 1)
                self.assertEqual(same["paint_data"], {})
                self.assertEqual(raw, b"")
                if layout == "owned_readonly":
                    coefficients.setflags(write=True)
                coefficients[12] = .25
                changed, raw = parse_geometry_message(encode([draw], cache))
                self.assertTrue(changed["batches"][0]["cached"])
                self.assertNotEqual(changed["batches"][0]["paint_hash"], first["batches"][0]["paint_hash"])
                self.assertEqual(len(raw), 96)
                coefficients[12] = float("nan")
                with self.assertRaisesRegex(ValueError, "paint coefficients"):
                    encode([draw], cache)

    def test_invalid_paint_never_advances_any_sender_state(self):
        draw, cache = painted_quad(), GeometryCache()
        encode([draw], cache)
        states = cache.sent, cache.generated_payloads, cache.generated_paints
        invalid = [draw.paint[:-1], np.zeros(24 + 8 * (MAX_PAINT_SAMPLES + 1), dtype="f4")]
        for index, value in ((3, 0), (3, -1), (7, .5), (7, 1), (11, 2), (11, 1), (12, np.inf)):
            coefficients = draw.paint.copy()
            coefficients[index] = value
            invalid.append(coefficients)
        for coefficients in invalid:
            with self.subTest(size=len(coefficients)), self.assertRaisesRegex(ValueError, "paint coefficients"):
                encode([painted_quad((0, 1, 0, 1)), replace(draw, paint=coefficients)], cache)
            self.assertIs(cache.sent, states[0])
            self.assertIs(cache.generated_payloads, states[1])
            self.assertIs(cache.generated_paints, states[2])

    def test_shared_renderer_is_default_and_switches_reset_transport_state(self):
        cache = GeometryCache()
        cache.sent.add("stale")
        with patch.dict(os.environ, {}, clear=True), \
                patch("maniml.web.geometry._serialize_triangle_scene", return_value=b"frame") as generate:
            self.assertEqual(serialize_scene(object(), cache), b"frame")
            generate.assert_called_once()
        self.assertEqual(cache.sent, set())
        self.assertEqual(cache.renderer, "triangles")
        with self.assertRaisesRegex(ValueError, "MANIML_RENDERER"):
            serialize_scene(object(), renderer="typo")


@unittest.skipUnless(shutil.which("node"), "Node is required for recording replay")
class RecordedGeometryReplay(unittest.TestCase):
    @staticmethod
    def border_draw(color=(1, 0, 0, .5), *, fill=True, capacity=64):
        from maniml.web.gpu_border_geometry import indices_per_curve, readonly
        draw = painted_quad()
        curves = np.zeros((1, 44), dtype="<f4")
        curves[0, 37] = 1
        curves[0, 40:44] = color
        vertices = draw.vertices if fill else draw.vertices[:0]
        indices = draw.indices if fill else draw.indices[:0]
        return replace(draw, vertices=vertices, indices=readonly(indices),
                       count=len(indices) + indices_per_curve(capacity),
                       border_sources=readonly(curves), border_capacity=capacity,
                       border_layout=((len(indices), len(vertices), 1),))

    def run_player(self, mode):
        harness = Path(__file__).with_name("player_commands.cjs")
        result = subprocess.run([shutil.which("node"), str(harness), mode],
                                input=base64.b64encode(encode([quad()])).decode(),
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_player_seek_and_playback_recover_without_unhandled_rejections(self):
        self.run_player("recovery")

    def test_segment_selection_displays_first_frame_and_single_frame_segments(self):
        self.run_player("segments")

    def test_player_chooses_renderer_from_headers_across_recording_formats(self):
        self.run_player("formats")

    def test_corrupt_recording_reports_error_before_initializing_a_renderer(self):
        self.run_player("corrupt")

    def test_player_rehydrates_paint_across_reverse_seek_and_render_failure(self):
        self.run_player("paint")

    def test_player_rehydrates_gpu_borders_across_seeks_and_render_failure(self):
        self.run_player("border")

    def test_gpu_border_sources_and_fill_bytes_survive_random_seek_and_sender_reset(self):
        red, blue, cache = self.border_draw(), self.border_draw((0, 0, 1, .75)), GeometryCache()
        messages = [encode([red], cache), encode([red], cache), encode([blue], cache),
                    encode([blue], cache), encode([], cache), encode([red], cache)]
        cache.reset()
        messages.append(encode([blue], cache))
        first, _ = parse_geometry_message(messages[0])
        changed, _ = parse_geometry_message(messages[2])
        self.assertEqual(first["batches"][0]["hash"], changed["batches"][0]["hash"])
        self.assertEqual(first["batches"][0]["paint_hash"], changed["batches"][0]["paint_hash"])
        self.assertNotEqual(first["batches"][0]["border"], changed["batches"][0]["border"])
        for index in (1, 3):
            header, raw = parse_geometry_message(messages[index])
            self.assertTrue(header["batches"][0]["cached"])
            self.assertEqual(header["border_data"], {})
            self.assertEqual(raw, b"")
        order = [3, 1, 6, 4, 2, 5, 0, 3]
        for index, message in zip(order, self.run_recording(messages, order)):
            header, raw = parse_geometry_message(message)
            if index == 4:
                self.assertEqual(header["batches"], [])
                self.assertEqual(header["border_data"], {})
                continue
            batch = header["batches"][0]
            expected = blue if index in (2, 3, 6) else red
            self.assertEqual(batch["num_verts"], 68)
            self.assertEqual(batch["fill_num_verts"], 4)
            self.assertNotIn("cached", batch)
            self.assertEqual(raw[batch["offset"]:batch["index_offset"]], expected.vertices.tobytes())
            self.assertEqual(raw[batch["index_offset"]:batch["index_offset"] + batch["index_count"] * 4],
                             expected.indices.tobytes())
            # Only fill indices travel; the strip pattern is the drivers' to build.
            self.assertEqual(batch["index_count"], 6)
            self.assertEqual(batch["count"], 6 + 186)
            self.assertEqual(batch["border"]["capacity"], 64)
            self.assertEqual(batch["border"]["layout"], [[6, 4, 1]])
            self.assertLess(int(expected.indices.max()), batch["fill_num_verts"])
            self.assertEqual(set(header["border_data"]), {batch["border"]["hash"]})
            info = header["border_data"][batch["border"]["hash"]]
            self.assertEqual(raw[info["offset"]:info["offset"] + info["nbytes"]],
                             expected.border_sources.tobytes())

    def test_border_only_draws_shared_sources_and_unaligned_definitions(self):
        draw = self.border_draw(fill=False)
        header, raw = parse_geometry_message(encode([draw, draw]))
        for batch in header["batches"]:
            batch["offset"] += 1
            batch["index_offset"] += 1
        for field in ("paint_data", "border_data"):
            for info in header[field].values():
                info["offset"] += 1
        message, = self.run_recording([self.pack_recording(header, b"x" + raw)], [0])
        full, payload = parse_geometry_message(message)
        self.assertEqual(len(full["border_data"]), 1)
        self.assertEqual(len(full["paint_data"]), 1)
        for batch in full["batches"]:
            self.assertEqual(batch["fill_num_verts"], 0)
            self.assertEqual(batch["num_verts"], 64)
            self.assertEqual(batch["offset"], batch["index_offset"])
        info = next(iter(full["border_data"].values()))
        self.assertEqual(payload[info["offset"]:info["offset"] + info["nbytes"]], draw.border_sources.tobytes())

    def test_recording_rejects_corrupt_gpu_border_layouts_sources_and_cached_counts(self):
        import struct
        good = encode([self.border_draw()])
        failures = ("missing", "truncated", "short", "zero", "fractional_offset", "hash", "conflict",
                    "nonfinite", "width", "density", "active", "capped", "reserved", "source_count",
                    "old_version", "descriptor", "curves", "curve_limit", "fill", "output", "stride",
                    "pipeline", "indexed", "instances", "index_count", "count", "index", "fill_nan",
                    "cached_fill", "cached_indices", "orphan_fill", "definitions",
                    "capacity", "capacity_type", "layout", "layout_sum", "layout_curves")
        for failure in failures:
            with self.subTest(failure=failure):
                header, raw = parse_geometry_message(good)
                raw = bytearray(raw)
                batch = header["batches"][0]
                info = next(iter(header["border_data"].values()))
                error = "[Bb]order"
                preceding = []
                if failure == "missing":
                    header["border_data"] = {}
                elif failure in ("truncated", "short", "zero", "fractional_offset"):
                    if failure == "fractional_offset": info["offset"] += .5
                    else: info["nbytes"] = {"truncated": 180, "short": 172, "zero": 0}[failure]
                    if failure in ("truncated", "fractional_offset"): error = "Truncated recorded geometry payload"
                elif failure == "hash":
                    batch["border"]["hash"] = "invalid"
                elif failure in ("conflict", "nonfinite", "width", "density", "active", "capped", "reserved"):
                    slot, value = {"conflict": (40, .25), "nonfinite": (0, np.inf), "width": (19, -1),
                                   "density": (36, -1), "active": (37, .5), "capped": (38, 2),
                                   "reserved": (39, 1)}[failure]
                    struct.pack_into("<f", raw, info["offset"] + slot * 4, value)
                    if failure == "conflict": preceding = [good]
                elif failure == "source_count":
                    raw.extend(raw[info["offset"]:info["offset"] + 176])
                    info["nbytes"] = 352
                elif failure == "old_version": header["format_version"] = 4
                elif failure == "descriptor": batch["border"] = []
                elif failure in ("curves", "curve_limit"):
                    from maniml.web.gpu_border_geometry import MAX_BORDER_CURVES
                    batch["border"]["num_curves"] = .5 if failure == "curves" else MAX_BORDER_CURVES + 1
                elif failure in ("fill", "output", "stride", "pipeline", "indexed", "instances", "index_count", "count"):
                    key, value = {"fill": ("fill_num_verts", -1), "output": ("num_verts", 67),
                                  "stride": ("stride", 68), "pipeline": ("pipeline", "stroke"),
                                  "indexed": ("indexed", False), "instances": ("instances", 2),
                                  "index_count": ("index_count", 9), "count": ("count", 189)}[failure]
                    batch[key] = value
                elif failure == "capacity": batch["border"]["capacity"] = 66
                elif failure == "capacity_type": batch["border"]["capacity"] = "64"
                elif failure == "layout": batch["border"]["layout"] = [[6, 4]]
                elif failure == "layout_sum": batch["border"]["layout"] = [[3, 4, 1]]
                elif failure == "layout_curves": batch["border"]["layout"] = [[6, 4, 0]]
                elif failure == "index": struct.pack_into("<I", raw, batch["index_offset"], 68)
                elif failure == "fill_nan": struct.pack_into("<f", raw, batch["offset"], np.nan)
                elif failure in ("cached_fill", "cached_indices"):
                    preceding = [good]
                    batch["cached"] = True
                    if failure == "cached_fill":
                        batch["fill_num_verts"] += 1
                        batch["num_verts"] += 1
                    else:
                        batch["index_count"] += 3
                        batch["count"] += 3
                elif failure == "orphan_fill": del batch["border"]
                elif failure == "definitions": header["border_data"] = []
                self.run_recording(preceding + [self.pack_recording(header, raw)], [0], error=error)

    def test_reverse_seek_rehydrates_paint_independently_of_geometry(self):
        red, blue, cache = painted_quad(), painted_quad((0, 0, 1, .75)), GeometryCache()
        messages = [encode([red], cache), encode([red], cache), encode([], cache),
                    encode([blue], cache), encode([blue], cache), encode([red], cache)]
        first, _ = parse_geometry_message(messages[0])
        changed, _ = parse_geometry_message(messages[3])
        self.assertEqual(first["batches"][0]["hash"], changed["batches"][0]["hash"])
        self.assertNotEqual(first["batches"][0]["paint_hash"], changed["batches"][0]["paint_hash"])
        for index in (1, 4):
            header, _ = parse_geometry_message(messages[index])
            self.assertTrue(header["batches"][0]["cached"])
            self.assertEqual(header["paint_data"], {})
        order = [4, 1, 3, 0, 2, 5, 4, 1]
        for index, message in zip(order, self.run_recording(messages, order)):
            header, raw = parse_geometry_message(message)
            if index == 2:
                self.assertEqual(header["batches"], [])
                self.assertEqual(header["paint_data"], {})
                continue
            batch = header["batches"][0]
            self.assertNotIn("cached", batch)
            self.assertEqual(set(header["paint_data"]), {batch["paint_hash"]})
            info = header["paint_data"][batch["paint_hash"]]
            expected = blue if index in (3, 4) else red
            self.assertEqual(raw[info["offset"]:info["offset"] + info["nbytes"]], expected.paint.tobytes())
            self.assertEqual(raw[:batch["index_offset"]], expected.vertices.tobytes())

    def test_shared_paint_is_rehydrated_once_and_unaligned_input_is_little_endian(self):
        draw = painted_quad()
        header, raw = parse_geometry_message(encode([draw, draw]))
        # Force unaligned payload-relative offsets as well as whatever
        # alignment the JSON envelope happens to give this frame.
        for batch in header["batches"]:
            batch["offset"] += 1
            batch["index_offset"] += 1
        for info in header["paint_data"].values():
            info["offset"] += 1
        message, = self.run_recording([self.pack_recording(header, b"x" + raw)], [0])
        full, payload = parse_geometry_message(message)
        self.assertEqual(len(full["paint_data"]), 1)
        info = next(iter(full["paint_data"].values()))
        np.testing.assert_array_equal(np.frombuffer(payload, "<f4", count=info["nbytes"] // 4,
                                                   offset=info["offset"]), draw.paint)

    def test_binary_paint_reference_takes_precedence_over_legacy_inline_field(self):
        draw = painted_quad()
        header, raw = parse_geometry_message(encode([draw]))
        header["batches"][0]["paint"] = "unused legacy field"
        message, = self.run_recording([self.pack_recording(header, raw)], [0])
        full, payload = parse_geometry_message(message)
        info = full["paint_data"][full["batches"][0]["paint_hash"]]
        self.assertEqual(payload[info["offset"]:info["offset"] + info["nbytes"]], draw.paint.tobytes())

    def test_format_three_inline_paint_survives_cached_geometry_and_reverse_seek(self):
        red, blue = painted_quad(), painted_quad((0, 0, 1, .75))
        header, raw = parse_geometry_message(encode([red]))
        info = next(iter(header.pop("paint_data").values()))
        header["format_version"] = 3
        batch = header["batches"][0]
        batch.pop("paint_hash")
        batch["paint"] = red.paint.tolist()
        first = self.pack_recording(header, raw[:info["offset"]])
        batch["paint"] = blue.paint.tolist()
        batch["cached"] = True
        batch.pop("offset")
        batch.pop("index_offset")
        second = self.pack_recording(header)
        for expected, message in zip((blue, red, blue), self.run_recording([first, second], [1, 0, 1])):
            result, _ = parse_geometry_message(message)
            self.assertEqual(result["format_version"], 3)
            self.assertEqual(result["batches"][0]["paint"], expected.paint.tolist())
            self.assertNotIn("paint_hash", result["batches"][0])
            self.assertEqual(result["paint_data"], {})

    def test_recording_rejects_missing_truncated_and_invalid_paint_definitions(self):
        import struct
        good = encode([painted_quad()])
        for failure in ("missing", "truncated", "short", "fractional_offset", "scale", "count",
                        "mode", "empty_idw", "nonfinite", "hash", "conflict"):
            with self.subTest(failure=failure):
                header, raw = parse_geometry_message(good)
                raw = bytearray(raw)
                info = next(iter(header["paint_data"].values()))
                error = "recorded paint"
                if failure == "missing":
                    header["paint_data"] = {}
                    error = "Missing recorded paint"
                elif failure == "truncated":
                    info["nbytes"] += 4
                    error = "Truncated recorded geometry payload"
                elif failure == "short":
                    info["nbytes"] = 92
                elif failure == "fractional_offset":
                    info["offset"] += .5
                    error = "Truncated recorded geometry payload"
                elif failure == "hash":
                    header["batches"][0]["paint_hash"] = "invalid"
                else:
                    index, value = {"scale": (3, 0), "count": (7, .5), "mode": (11, 2),
                                    "empty_idw": (11, 1), "nonfinite": (12, np.inf),
                                    "conflict": (12, .25)}[failure]
                    struct.pack_into("<f", raw, info["offset"] + 4 * index, value)
                messages = [self.pack_recording(header, raw)]
                if failure == "conflict":
                    messages.insert(0, good)
                    error = "Conflicting recorded paint"
                self.run_recording(messages, [0], error=error)

    @staticmethod
    def pack_recording(header, payload=b""):
        import struct
        encoded = json.dumps(header).encode()
        return b"\x03" + struct.pack("<I", len(encoded)) + encoded + payload

    def test_reverse_seek_reconstructs_indices_after_geometry_was_retired(self):
        draw, cache = quad(), GeometryCache()
        alternate = replace(draw, indices=np.array([0, 1, 3, 1, 2, 3], dtype="u4"))
        messages = [encode([draw], cache), encode([draw], cache), encode([], cache),
                    encode([alternate], cache), encode([alternate], cache)]
        order = [4, 1, 3, 0, 2, 1]
        result = self.run_recording(messages, order)
        for index, message in zip(order, result):
            header, raw = parse_geometry_message(message)
            original, _ = parse_geometry_message(messages[index])
            self.assertEqual(len(header["batches"]), len(original["batches"]))
            for batch in header["batches"]:
                self.assertNotIn("cached", batch)
                expected = alternate if index >= 3 else draw
                np.testing.assert_array_equal(np.frombuffer(raw, "<u4", offset=batch["index_offset"],
                                                           count=batch["index_count"]), expected.indices)
                self.assertEqual(raw[:batch["index_offset"]], expected.vertices.tobytes())

    def test_legacy_indexed_fills_and_textures_are_restored_on_cached_frames(self):
        # The comparison format omits its `tri` metadata on cached frames.
        import struct
        raw = bytes(3 * 68) + bytes(range(120)) + np.array([0, 1, 2], dtype="u4").tobytes() + b"png"
        batch = {"kind": "vmobject", "hash": "legacy", "num_verts": 3, "stride": 68,
                 "offset": 0, "tri": {"voffset": 204, "vcount": 3, "ioffset": 324, "icount": 3},
                 "textures": {"Texture": "texture"}}
        first = {"batches": [batch], "texture_data": {"texture": {"offset": 336, "nbytes": 3}}}
        cached = {"batches": [{key: value for key, value in batch.items() if key not in ("offset", "tri")}],
                  "texture_data": {}}
        cached["batches"][0]["cached"] = True
        def pack(header, payload=b""):
            header = json.dumps(header).encode()
            return b"\x03" + struct.pack("<I", len(header)) + header + payload
        message, = self.run_recording([pack(first, raw), pack(cached)], [1])
        header, payload = parse_geometry_message(message)
        self.assertEqual(header["batches"][0]["tri"], batch["tri"])
        self.assertEqual(payload, raw)

    def run_recording(self, messages, order, *, error=None):
        module = Path(__file__).parents[1] / "maniml/web/static/geometry_recording.js"
        script = """
          require(process.argv[1]);
          const input = JSON.parse(require('fs').readFileSync(0, 'utf8'));
          const recording = ManimlRecording.index(input.messages.map(s => new Uint8Array(Buffer.from(s, 'base64'))));
          process.stdout.write(JSON.stringify(input.order.map(i => Buffer.from(recording.frame(i)).toString('base64'))));
        """
        result = subprocess.run([shutil.which("node"), "-e", script, str(module)],
                                input=json.dumps({"messages": [base64.b64encode(m).decode() for m in messages],
                                                  "order": order}),
                                capture_output=True, text=True, timeout=20)
        if error is not None:
            self.assertNotEqual(result.returncode, 0)
            self.assertRegex(result.stderr, error)
            return []
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return [base64.b64decode(value) for value in json.loads(result.stdout)]


if __name__ == "__main__":
    unittest.main()

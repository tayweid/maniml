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
from maniml.web.geometry import GeometryCache, SURFACE_DTYPE, parse_geometry_message, serialize_scene
from maniml.web.triangle_scene import TriangleDraw, TriangleFrame


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

    def run_recording(self, messages, order):
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
                                capture_output=True, text=True, timeout=20, check=True)
        return [base64.b64decode(value) for value in json.loads(result.stdout)]


if __name__ == "__main__":
    unittest.main()

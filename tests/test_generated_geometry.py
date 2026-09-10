"""Derived geometry wire identity, validation and seekable recording contracts."""

import base64
from dataclasses import replace
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

    def test_empty_operations_do_not_create_zero_byte_gpu_buffers(self):
        header, raw = parse_geometry_message(encode([replace(quad(), count=0)]))
        self.assertEqual(header["batches"], [])
        self.assertEqual(raw, b"")

    def test_selector_validates_and_resets_transport_state(self):
        cache = GeometryCache()
        cache.sent.add("stale")
        with patch.dict(os.environ, {"MANIML_RENDERER": "triangles"}), \
                patch("maniml.web.geometry._serialize_triangle_scene", return_value=b"frame") as generate:
            self.assertEqual(serialize_scene(object(), cache), b"frame")
            generate.assert_called_once()
        self.assertEqual(cache.renderer, "triangles")
        self.assertEqual(cache.sent, set())
        with self.assertRaisesRegex(ValueError, "MANIML_RENDERER"):
            serialize_scene(object(), renderer="typo")


@unittest.skipUnless(shutil.which("node"), "Node is required for recording replay")
class RecordedGeometryReplay(unittest.TestCase):
    def test_player_seek_recovers_after_render_rejection(self):
        # Execute the real player and its key handler: a rejected texture/frame
        # render must reach that caller without poisoning subsequent seeks.
        module = Path(__file__).parents[1] / "maniml/web/static/player.js"
        script = r"""
          const assert = require('node:assert/strict');
          const fs = require('node:fs'), vm = require('node:vm');
          (async () => {
            const elements = new Map(), listeners = new Map(), rendered = [];
            function element() {
              return {replaceChildren() {}, appendChild() {}};
            }
            let failNext = false;
            const meta = {format_version: 2, scene: 'recovery', fps: 30,
                          frames: [{len: 1, segment: 0}], segments: 1, lines: [1]};
            const context = {
              console,
              document: {
                getElementById(id) {
                  if (!elements.has(id)) elements.set(id, element());
                  return elements.get(id);
                },
                createElement: element,
                addEventListener(name, handler) { listeners.set(name, handler); },
              },
              fetch: async path => path === 'scene.json'
                ? {json: async () => meta} : {body: {pipeThrough: value => value}},
              DecompressionStream: class {},
              Response: class {async arrayBuffer() { return new Uint8Array([3]).buffer; }},
              setInterval: () => 1, clearInterval() {},
              ManimlRecording: {index: () => ({frame: index => index})},
              ManimlWGPU: {
                init: async () => {},
                async render(frame) {
                  rendered.push(frame);
                  if (failNext) { failNext = false; throw new Error('texture decode failed'); }
                },
              },
            };
            await vm.runInNewContext(fs.readFileSync(process.argv[1], 'utf8'), context);
            assert.deepEqual(rendered, [0]);
            const seek = () => listeners.get('keydown')({
              key: 'ArrowLeft', shiftKey: true, preventDefault() {},
            });
            failNext = true;
            await assert.rejects(seek(), /texture decode failed/);
            await seek();
            assert.deepEqual(rendered, [0, 0, 0]);
            process.stdout.write('player recovered');
          })().catch(error => { console.error(error); process.exitCode = 1; });
        """
        result = subprocess.run([shutil.which("node"), "-e", script, str(module)],
                                capture_output=True, text=True, timeout=20, check=True)
        self.assertEqual(result.stdout, "player recovered")

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

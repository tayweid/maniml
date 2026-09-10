"""Regressions for border wire knowledge, cache budgets and renderer changes."""

from dataclasses import replace
import os
import unittest
from unittest.mock import patch

from maniml.mobject.geometry import Square
from maniml.web.generated_geometry import serialize_generated_frame
from maniml.web.geometry import GeometryCache, parse_geometry_message, serialize_scene
from maniml.web.gpu_border_geometry import BorderRecipeCache, indices_per_curve, readonly
from maniml.web.triangle_geometry import LyonFillTessellator
from maniml.web.triangle_scene import TriangleDraw, TriangleFrame, TriangleMeshCache, prepare_triangle_frame
from tests.renderer_fixtures import build_scene
from tests.test_gpu_border_geometry import fill_part


def recipe_frame():
    vertices, indices, curves = fill_part()
    curves = curves.copy()
    curves[0, [0, 12, 24]] = [-1, 0, 1]
    curves[0, [7, 19, 31]] = 20
    curves[0, [11, 23, 35]] = 1
    vertices, indices, curves, capacity, layout = BorderRecipeCache().assemble(
        [(vertices, indices, readonly(curves), 64)])
    draw = TriangleDraw("surface", vertices, {}, indices=indices,
                        count=len(indices) + indices_per_curve(capacity) * len(curves),
                        border_sources=curves, border_capacity=capacity, border_layout=layout)
    return TriangleFrame((64, 36), (0, 0, 0, 0), 1, draws=[draw])


def encode(frame, cache):
    return parse_geometry_message(serialize_generated_frame(frame, {}, cache))


class GpuBorderWireAudit(unittest.TestCase):
    def test_skipped_recipe_never_teaches_receiver_an_unretained_definition(self):
        for zero_field in ("count", "instances"):
            with self.subTest(zero_field=zero_field):
                frame, cache = recipe_frame(), GeometryCache()
                skipped = replace(frame, draws=[replace(frame.draws[0], **{zero_field: 0})])
                empty, raw = encode(skipped, cache)
                self.assertEqual(empty["batches"], [])
                self.assertEqual(empty["border_data"], {})
                self.assertEqual(raw, b"")
                self.assertFalse(cache.sent)
                self.assertFalse(cache.generated_borders)

                first, payload = encode(frame, cache)
                key = first["batches"][0]["border"]["hash"]
                ref = first["border_data"][key]
                self.assertEqual(payload[ref["offset"]:ref["offset"] + ref["nbytes"]],
                                 frame.draws[0].border_sources.tobytes())
                same, payload = encode(frame, cache)
                self.assertTrue(same["batches"][0]["cached"])
                self.assertFalse(same["border_data"])
                self.assertEqual(payload, b"")

                encode(skipped, cache)
                self.assertFalse(cache.sent)
                self.assertFalse(cache.generated_borders)
                returning, _ = encode(frame, cache)
                self.assertIn(key, returning["border_data"], "a skipped frame retires receiver knowledge")
                self.assertNotIn("cached", returning["batches"][0])

    def test_partial_border_ranges_fail_before_advancing_sender_knowledge(self):
        frame, cache = recipe_frame(), GeometryCache()
        encode(frame, cache)
        sent = cache.sent.copy()
        memos = cache.generated_borders.copy()
        draw = frame.draws[0]
        for invalid in (replace(draw, count=draw.count - 3),
                        replace(draw, indices=draw.indices[:3], count=3)):
            with self.subTest(count=invalid.count):
                with self.assertRaisesRegex(ValueError, "draw count|run layout"):
                    encode(replace(frame, draws=[invalid]), cache)
                self.assertEqual(cache.sent, sent)
                self.assertEqual(cache.generated_borders, memos)
        valid, payload = encode(frame, cache)
        self.assertTrue(valid["batches"][0]["cached"])
        self.assertEqual(payload, b"")

    def test_reserved_border_word_is_rejected_without_caching_invalid_source(self):
        frame, cache = recipe_frame(), GeometryCache()
        encode(frame, cache)
        sent = cache.sent.copy()
        memos = cache.generated_borders.copy()
        draw = frame.draws[0]
        invalid = draw.border_sources.copy()
        invalid[0, 39] = 1
        with self.assertRaisesRegex(ValueError, "border source values"):
            encode(replace(frame, draws=[replace(draw, border_sources=invalid)]), cache)
        self.assertEqual(cache.sent, sent)
        self.assertEqual(cache.generated_borders, memos)
        valid, payload = encode(frame, cache)
        self.assertFalse(valid["border_data"])
        self.assertEqual(payload, b"")


class GpuBorderCacheAudit(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tessellator = LyonFillTessellator()

    def scene(self, *, gradient=False):
        shapes = [Square(side_length=1, fill_opacity=.5 if gradient else 1,
                         stroke_width=0, fill_border_width=4).shift([index * 1.5 - 1.5, 0, 0])
                  for index in range(3)]
        if gradient:
            shapes[0].data["fill_rgba"][1, 0] = .2
        return build_scene(*shapes, resolution=(160, 90))

    def prepare(self, scene, cache):
        return prepare_triangle_frame(scene, self.tessellator, mesh_cache=cache,
                                      fill_borders=True, gpu_borders=True)

    def test_zero_bytes_or_zero_entries_disables_gpu_recipe_retention(self):
        for config in ({"max_bytes": 0}, {"max_bytes": 1 << 20, "max_entries": 0}):
            with self.subTest(config=config):
                scene, cache = self.scene(), TriangleMeshCache(**config)
                for scale in (1, .95):
                    scene.camera.frame.scale(scale)
                    frame = self.prepare(scene, cache)
                    self.assertTrue(any(draw.border_sources is not None for draw in frame.draws),
                                    "disabling retention must preserve the returned drawing")
                    self.assertTrue(all(
                        draw.count == len(draw.indices)
                        + indices_per_curve(draw.border_capacity) * len(draw.border_sources)
                        for draw in frame.draws))
                    self.assertFalse(cache._entries)
                    self.assertFalse(cache.gpu_border_cache.sources)
                    self.assertFalse(cache.gpu_border_cache.runs)
                    self.assertEqual(cache.stats["retained_bytes"], 0)
                    self.assertEqual(frame.mesh_cache_stats["retained_bytes"], 0)

    def test_completed_fill_and_recipe_retention_share_configured_budget(self):
        scene = self.scene()
        warm = TriangleMeshCache(max_bytes=1 << 20)
        self.prepare(scene, warm)
        fill = warm.stats["retained_fill_cache_bytes"]
        recipes = warm.stats["retained_gpu_recipe_bytes"]
        self.assertGreater(fill, 0)
        self.assertGreater(recipes, 0)
        budget = fill + recipes // 2  # Enough for the fills, forces recipe eviction.
        cache = TriangleMeshCache(max_bytes=budget)
        for scale in (1, .95, 1.1):
            scene.camera.frame.scale(scale)
            frame = self.prepare(scene, cache)
            actual = cache._bytes + cache.gpu_border_cache.nbytes
            self.assertLessEqual(actual, budget)
            self.assertEqual(cache.stats["retained_bytes"], actual)
            self.assertEqual(frame.mesh_cache_stats["retained_bytes"], actual)
            self.assertEqual(cache.stats["retained_fill_cache_bytes"], cache._bytes)
            self.assertEqual(cache.stats["retained_gpu_recipe_bytes"], cache.gpu_border_cache.nbytes)
            self.assertEqual(frame.mesh_cache_stats["retained_gpu_recipe_bytes"], cache.gpu_border_cache.nbytes)
            self.assertTrue(frame.draws, "budget pressure must not remove visible objects")

    def test_original_renderer_retires_paint_border_memos_and_mesh_recipes(self):
        scene, cache = self.scene(gradient=True), GeometryCache()
        with patch.dict(os.environ, MANIML_BORDER_GENERATOR="gpu"):
            initial, _ = parse_geometry_message(serialize_scene(scene, cache, renderer="triangles"))
            self.assertTrue(initial["paint_data"])
            self.assertTrue(initial["border_data"])
            self.assertTrue(cache.generated_payloads)
            self.assertTrue(cache.generated_paints)
            self.assertTrue(cache.generated_borders)
            self.assertGreater(cache.triangle_meshes.gpu_border_cache.nbytes, 0)

            parse_geometry_message(serialize_scene(scene, cache, renderer="winding"))
            self.assertEqual(cache.renderer, "winding")
            self.assertFalse(cache.generated_payloads)
            self.assertFalse(cache.generated_paints)
            self.assertFalse(cache.generated_borders)
            self.assertFalse(cache.triangle_meshes._entries)
            self.assertFalse(cache.triangle_meshes.gpu_border_cache.sources)
            self.assertFalse(cache.triangle_meshes.gpu_border_cache.runs)
            self.assertEqual(cache.triangle_meshes.stats["retained_bytes"], 0)

            returned, _ = parse_geometry_message(serialize_scene(scene, cache, renderer="triangles"))
            self.assertTrue(returned["paint_data"])
            self.assertTrue(returned["border_data"])
            self.assertTrue(all(not batch.get("cached") for batch in returned["batches"]))


if __name__ == "__main__":
    unittest.main()

"""Retained border-source recipes, ordering, mutation and lifetime contracts."""

import gc
import os
import unittest
import weakref
from unittest.mock import patch

import numpy as np

from maniml.mobject.geometry import Circle, Square
from maniml.web.border_geometry import BorderSource
from maniml.constants import BLUE, RED
from maniml.web.generated_geometry import serialize_generated_frame
from maniml.web.geometry import (
    GeometryCache, SURFACE_DTYPE, parse_geometry_message, serialize_scene,
)
from maniml.web.gpu_border_geometry import (
    BorderRecipeCache, CURVE_BYTES, CURVE_WORDS, INDICES_PER_CURVE,
    VERTICES_PER_CURVE, border_indices, pack_source, readonly,
)
from tests.test_border_geometry import UNIFORMS
from maniml.web.triangle_geometry import LyonFillTessellator
from maniml.web.triangle_scene import TriangleMeshCache, prepare_triangle_frame
from tests.renderer_fixtures import build_scene


def fill_part(color=(1, 0, 0, 1), x=0):
    vertices = np.zeros(4, dtype=SURFACE_DTYPE)
    vertices["point"] = [[x - 1, -1, 0], [x + 1, -1, 0], [x + 1, 1, 0], [x - 1, 1, 0]]
    vertices["d_normal_point"] = vertices["point"] + [0, 0, .001]
    vertices["rgba"] = color
    indices = np.array([0, 1, 2, 0, 2, 3], dtype="u4")
    curves = np.zeros((1, CURVE_WORDS), dtype="f4")
    curves[:, 37] = 1
    curves[:, 40:44] = color
    return tuple(readonly(array) for array in (vertices, indices, curves))


class GpuBorderRecipe(unittest.TestCase):
    def test_packed_records_preserve_source_fields_density_and_real_color(self):
        shape = Circle(fill_opacity=.5, stroke_width=0, fill_border_width=4)
        source = BorderSource.read(shape, UNIFORMS)
        authored = {name: shape.data[name].tobytes() for name in ("point", "fill_rgba", "fill_border_width")}
        color = np.array([.2, .4, .6, .8], dtype="f4")
        packed = pack_source(source, color)
        self.assertEqual(packed.nbytes, int(source.active.sum()) * CURVE_BYTES)
        np.testing.assert_array_equal(packed[:, :36], source.data.view("f4").reshape(-1, 36)[source.active])
        np.testing.assert_array_equal(packed[:, 36], source.density[source.active])
        np.testing.assert_array_equal(packed[:, 37], 1)
        np.testing.assert_array_equal(packed[:, 40:44], np.tile(color, (len(packed), 1)))
        with self.assertRaises(ValueError):
            packed.setflags(write=True)
        for name, value in authored.items():
            self.assertEqual(shape.data[name].tobytes(), value)

    def test_camera_zoom_pan_and_style_uniforms_reuse_source_arrays(self):
        shape = Circle(fill_opacity=.5, stroke_width=0, fill_border_width=4)
        cache = BorderRecipeCache()
        cache.begin_frame()
        first = cache.source(shape, UNIFORMS)
        first_counts = cache.sources[id(shape)].source.counts.copy()
        cache.finish_frame()
        before = shape.data.tobytes()
        for changes in ({"frame_scale": .1}, {"camera_position": (1, 2, 3), "flat_stroke": 0},
                        {"scale_stroke_with_zoom": 0, "joint_type": 3}):
            cache.begin_frame()
            current = cache.source(shape, dict(UNIFORMS, **changes))
            self.assertIs(current, first)
            if "frame_scale" in changes:
                self.assertFalse(np.array_equal(cache.sources[id(shape)].source.counts, first_counts))
            cache.finish_frame()
        self.assertEqual(cache.source_updates, 1)
        self.assertEqual(shape.data.tobytes(), before)

    def test_direct_geometry_width_and_color_edits_refresh_without_revision_shortcuts(self):
        shape = Square(fill_opacity=.5, stroke_width=0, fill_border_width=4)
        cache = BorderRecipeCache()
        cache.begin_frame()
        previous = cache.source(shape, UNIFORMS)
        revision = shape.revision
        for field, component, amount in (("point", 0, .2), ("fill_border_width", 0, 2), ("fill_rgba", 0, -.25)):
            shape.data[field][:, component] += amount
            current = cache.source(shape, UNIFORMS)
            self.assertFalse(np.array_equal(previous, current))
            self.assertEqual(shape.revision, revision)
            previous = current
        shape.data["fill_rgba"][:, 3] = 0
        hidden = cache.source(shape, UNIFORMS)
        self.assertEqual(hidden.shape, (0, CURVE_WORDS))

    def test_invalid_source_or_uniforms_cannot_reuse_a_valid_recipe(self):
        shape = Square(fill_opacity=.5, stroke_width=0, fill_border_width=4)
        cache = BorderRecipeCache()
        cache.begin_frame()
        original = cache.source(shape, UNIFORMS)
        for changes in ({"camera_position": (np.nan, 0, 10)}, {"joint_type": 8},
                        {"scale_stroke_with_zoom": np.nan},
                        {"scale_stroke_with_zoom": 3, "frame_scale": 2}):
            with self.subTest(uniforms=changes), self.assertRaises(ValueError):
                cache.source(shape, dict(UNIFORMS, **changes))
        for field, value in (("point", np.nan), ("fill_border_width", -1), ("fill_rgba", np.inf)):
            saved = shape.data[field].copy()
            shape.data[field][0, 0] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                cache.source(shape, UNIFORMS)
            shape.data[field] = saved
        np.testing.assert_array_equal(cache.source(shape, UNIFORMS), original)

    def test_assembly_interleaves_each_fill_and_border_while_storage_is_contiguous(self):
        parts = (fill_part(), fill_part((0, 0, 1, .5), 3))
        cache = BorderRecipeCache()
        cache.begin_frame()
        vertices, indices, curves = cache.assemble(parts)
        self.assertEqual(len(vertices), 8)
        self.assertEqual(len(curves), 2)
        self.assertEqual(len(indices), 12 + 2 * INDICES_PER_CURVE)
        expected = np.concatenate((parts[0][1], border_indices(1, 8),
                                   parts[1][1] + 4, border_indices(1, 8 + VERTICES_PER_CURVE)))
        np.testing.assert_array_equal(indices, expected)
        np.testing.assert_array_equal(vertices, np.concatenate([part[0] for part in parts]))
        np.testing.assert_array_equal(curves, np.concatenate([part[2] for part in parts]))
        for first, repeated in zip((vertices, indices, curves), cache.assemble(parts)):
            self.assertIs(first, repeated)
            with self.assertRaises(ValueError):
                first.setflags(write=True)
        self.assertEqual(cache.assemblies, 1)

    def test_mutable_and_owned_readonly_parts_cannot_reuse_stale_assembly(self):
        for owned_readonly in (False, True):
            with self.subTest(owned_readonly=owned_readonly):
                arrays = [array.copy() for array in fill_part()]
                if owned_readonly:
                    for array in arrays:
                        array.setflags(write=False)
                cache = BorderRecipeCache()
                cache.begin_frame()
                previous = cache.assemble([tuple(arrays)])
                for array in arrays:
                    array.setflags(write=True)
                arrays[0]["point"][:, 0] += .25
                arrays[1][:] = [0, 1, 3, 1, 2, 3]
                arrays[2][:, 40] = .3
                current = cache.assemble([tuple(arrays)])
                np.testing.assert_array_equal(current[0], arrays[0])
                np.testing.assert_array_equal(current[1][:6], arrays[1])
                np.testing.assert_array_equal(current[2], arrays[2])
                self.assertFalse(np.array_equal(previous[0], current[0]))

    def test_current_frame_retention_budget_empty_frame_and_collected_owner(self):
        shape = Circle(fill_opacity=.5, stroke_width=0, fill_border_width=4)
        cache = BorderRecipeCache()
        cache.begin_frame()
        cache.source(shape, UNIFORMS)
        result = cache.assemble([fill_part()])
        self.assertGreater(cache.nbytes, 0)
        cache.finish_frame()
        cache.begin_frame()
        cache.finish_frame()
        self.assertEqual(cache.nbytes, 0)
        self.assertFalse(cache.sources)
        self.assertFalse(cache.runs)
        self.assertEqual(len(result[1]), 6 + INDICES_PER_CURVE)
        cache.begin_frame()
        cache.source(shape, UNIFORMS)
        ref = weakref.ref(shape)
        del shape
        gc.collect()
        self.assertIsNone(ref())
        cache.finish_frame()
        self.assertEqual(cache.nbytes, 0)
        bounded = BorderRecipeCache(max_bytes=0)
        bounded.begin_frame()
        bounded.source(Circle(fill_opacity=.5, fill_border_width=4), UNIFORMS)
        bounded.assemble([fill_part()])
        self.assertEqual(bounded.nbytes, 0)
        self.assertFalse(bounded.sources)
        self.assertFalse(bounded.runs)


class GpuBorderPreparation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tessellator = LyonFillTessellator()

    def scene(self, opacity=1):
        shapes = [Square(side_length=1, fill_color=color, fill_opacity=opacity,
                         stroke_width=0, fill_border_width=4).shift([x, 0, 0])
                  for color, x in ((RED, -.25), (BLUE, .25))]
        return build_scene(*shapes, resolution=(960, 540))

    def prepare(self, scene, cache, **kwargs):
        return prepare_triangle_frame(scene, self.tessellator, mesh_cache=cache,
                                      fill_borders=True, gpu_borders=True, **kwargs)

    def encode(self, frame, scene, cache):
        return parse_geometry_message(serialize_generated_frame(frame, scene.camera.uniforms, cache))

    def authored_bytes(self, scene):
        # Lazy normal/joint attributes are drawing scratch, not authored data.
        return [[shape.data[name].tobytes() for name in (
            "point", "fill_rgba", "fill_border_width", "stroke_rgba", "stroke_width")]
            for shape in scene.mobjects]

    def test_opaque_coalescing_keeps_fill_border_order_and_object_colors_without_cpu_emission(self):
        scene, cache = self.scene(), TriangleMeshCache()
        before = self.authored_bytes(scene)
        with patch("maniml.web.triangle_scene._prepare_border_geometry",
                   side_effect=AssertionError("expanded borders on CPU")), \
             patch("maniml.web.border_geometry.emit_border_triangles",
                   side_effect=AssertionError("expanded borders on CPU")):
            separate = self.prepare(scene, cache, coalesce=False)
            together = self.prepare(scene, cache)
        self.assertEqual(len(separate.draws), 2)
        combined, = together.draws
        self.assertFalse(combined.coverage)
        total_fill = sum(len(draw.vertices) for draw in separate.draws)
        expected, fill_offset, curve_offset = [], 0, 0
        for shape, draw in zip(scene.mobjects, separate.draws):
            fill_count = len(draw.indices) - INDICES_PER_CURVE * len(draw.border_sources)
            expected.extend((draw.indices[:fill_count] + fill_offset,
                             border_indices(len(draw.border_sources),
                                            total_fill + VERTICES_PER_CURVE * curve_offset)))
            np.testing.assert_array_equal(draw.border_sources[:, 40:44],
                np.tile(shape.data["fill_rgba"][0], (len(draw.border_sources), 1)))
            fill_offset += len(draw.vertices)
            curve_offset += len(draw.border_sources)
        np.testing.assert_array_equal(combined.indices, np.concatenate(expected))
        np.testing.assert_array_equal(combined.border_sources,
                                      np.concatenate([d.border_sources for d in separate.draws]))
        self.assertEqual(self.authored_bytes(scene), before)
        self.assertEqual(together.mesh_cache_stats["border_regenerations"], 0)

    def test_camera_only_changes_retain_all_recipe_arrays_and_wire_digests(self):
        scene, meshes, wire = self.scene(), TriangleMeshCache(), GeometryCache()
        first = self.prepare(scene, meshes)
        header, raw = self.encode(first, scene, wire)
        self.assertTrue(raw)
        source_bytes = self.authored_bytes(scene)
        draw, = first.draws
        for scale, shift in ((.75, [0, 0, 0]), (1, [.01, -.02, 0]), (1.5, [0, 0, 0])):
            scene.camera.frame.scale(scale).shift(shift)
            current = self.prepare(scene, meshes)
            changed, = current.draws
            for field in ("vertices", "indices", "border_sources"):
                self.assertIs(getattr(draw, field), getattr(changed, field))
            with patch("maniml.web.generated_geometry.hashlib.blake2b",
                       side_effect=AssertionError("rehashed immutable camera-only recipe")):
                updated, payload = self.encode(current, scene, wire)
            self.assertEqual(payload, b"")
            self.assertEqual(updated["border_data"], {})
            self.assertEqual(updated["batches"][0]["hash"], header["batches"][0]["hash"])
            self.assertEqual(updated["batches"][0]["border"], header["batches"][0]["border"])
            self.assertNotEqual(updated["camera"], header["camera"])
            self.assertEqual(current.mesh_cache_stats["gpu_border_source_updates"], 2)
            self.assertEqual(current.mesh_cache_stats["gpu_border_assemblies"], 1)
        self.assertEqual(self.authored_bytes(scene), source_bytes)

    def test_in_place_source_edits_and_material_changes_refresh_recipe(self):
        scene, meshes, wire = self.scene(opacity=.5), TriangleMeshCache(), GeometryCache()
        previous, _ = self.encode(self.prepare(scene, meshes), scene, wire)
        shape = scene.mobjects[0]
        revision = shape.revision
        for field, component, amount in (("fill_border_width", 0, 1), ("point", 0, .125),
                                          ("fill_rgba", 0, -.1)):
            shape.data[field][:, component] += amount
            current = self.prepare(scene, meshes)
            header, raw = self.encode(current, scene, wire)
            self.assertEqual(shape.revision, revision)
            self.assertNotEqual(header["batches"][0]["border"]["hash"],
                                previous["batches"][0]["border"]["hash"])
            self.assertTrue(raw)
            self.assertTrue(all(draw.coverage for draw in current.draws))
            previous = header
        # Nonconstant paint retains object-level coverage and its own field.
        shape.data["fill_rgba"][1, 1] += .2
        current = self.prepare(scene, meshes)
        self.assertEqual(current.draws[0].pipeline, "paint")
        self.assertIsNotNone(current.draws[0].paint)
        self.assertTrue(current.draws[0].coverage)

    def test_translucency_paint_shading_and_depth_keep_separate_coverage(self):
        for feature in ("translucent", "paint", "shading", "depth"):
            scene = self.scene()
            for shape in scene.mobjects:
                if feature == "translucent":
                    shape.data["fill_rgba"][:, 3] = .5
                elif feature == "paint":
                    shape.data["fill_rgba"][1, 1] += .2
                elif feature == "shading":
                    shape.uniforms["shading"] = [.2, .3, .4]
                else:
                    shape.depth_test = True
            with self.subTest(feature=feature):
                draws = self.prepare(scene, TriangleMeshCache()).draws
                self.assertEqual(len(draws), 2)
                self.assertTrue(all(draw.coverage and draw.border_sources is not None for draw in draws))
                if feature == "depth":
                    self.assertTrue(all(draw.pipeline.endswith("_depth") for draw in draws))

    def test_empty_frame_and_public_generator_switch_retire_and_resend_recipes(self):
        scene, wire = self.scene(), GeometryCache()
        with patch.dict(os.environ, MANIML_BORDER_GENERATOR="gpu"):
            initial, raw = parse_geometry_message(serialize_scene(scene, wire, renderer="triangles"))
            self.assertTrue(initial["border_data"])
            self.assertTrue(raw)
            groups = scene.render_groups
            scene.render_groups = []
            empty, raw = parse_geometry_message(serialize_scene(scene, wire, renderer="triangles"))
            self.assertEqual(empty["batches"], [])
            self.assertEqual(raw, b"")
            self.assertFalse(wire.sent)
            self.assertEqual(wire.triangle_meshes.gpu_border_cache.nbytes, 0)
            scene.render_groups = groups
            returned, raw = parse_geometry_message(serialize_scene(scene, wire, renderer="triangles"))
            self.assertTrue(returned["border_data"])
            self.assertTrue(raw)
        with patch.dict(os.environ, MANIML_BORDER_GENERATOR="cpu"):
            cpu, raw = parse_geometry_message(serialize_scene(scene, wire, renderer="triangles"))
            self.assertTrue(raw)
            self.assertFalse(any("border" in batch for batch in cpu["batches"]))
            self.assertFalse(wire.triangle_meshes.gpu_border_cache.nbytes)
        with patch.dict(os.environ, MANIML_BORDER_GENERATOR="gpu"):
            returned, raw = parse_geometry_message(serialize_scene(scene, wire, renderer="triangles"))
            self.assertTrue(returned["border_data"])
            self.assertTrue(raw)

    def test_compatible_runs_split_by_padded_output_budget_without_rejecting_sources(self):
        scene, cache = self.scene(), TriangleMeshCache()
        separate = self.prepare(scene, cache, coalesce=False)
        one_object_bytes = max((len(draw.vertices) + VERTICES_PER_CURVE * len(draw.border_sources)) * 40
                               for draw in separate.draws)
        with patch("maniml.web.triangle_scene.MAX_RUN_OUTPUT_BYTES", one_object_bytes):
            split = self.prepare(scene, cache)
        self.assertEqual(len(split.draws), 2)
        for before, after in zip(separate.draws, split.draws):
            np.testing.assert_array_equal(before.indices, after.indices)
            np.testing.assert_array_equal(before.border_sources, after.border_sources)


if __name__ == "__main__":
    unittest.main()

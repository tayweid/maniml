"""The renderer trusts ``Mobject.revision`` the way the checkpoint ledger does.

Every mutation a checkpoint must see bumps the counter, so a retained source
snapshot read at the same revision is the same source; the per-frame byte
comparison of every array becomes the verify mode (MANIML_VERIFY_LEDGER=1),
which still reads the arrays and raises naming the attribute a bypassing
write left stale. MANIML_RENDER_CACHE=bytes restores the comparison.
"""

import os
import unittest
from unittest.mock import patch

import numpy as np

from maniml.constants import RED
from maniml.mobject.geometry import Circle, Square
from maniml.web import border_geometry, triangle_scene
from maniml.web.border_geometry import BorderSource, RenderCacheStale, render_cache_policy
from maniml.web.geometry import GeometryCache, parse_geometry_message, serialize_scene
from maniml.web.gpu_border_geometry import BorderRecipeCache
from maniml.web.triangle_geometry import LyonFillTessellator, _packaged_library
from maniml.web.triangle_scene import TriangleMeshCache, prepare_triangle_frame
from tests.renderer_fixtures import build_scene
from tests.test_border_geometry import UNIFORMS


def shape(**kwargs):
    return Circle(fill_opacity=.5, stroke_width=0, fill_border_width=4, **kwargs)


# The suite runs under MANIML_VERIFY_LEDGER=1, where every trusted reuse still
# compares bytes; these tests pin what the default does without it.
no_verify = patch.dict(os.environ, {"MANIML_VERIFY_LEDGER": "0"})


class RenderCachePolicy(unittest.TestCase):
    def test_policy_defaults_to_revision_and_rejects_unknown_values(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("MANIML_RENDER_CACHE", None)
            self.assertEqual(render_cache_policy(), "revision")
        with patch.dict(os.environ, {"MANIML_RENDER_CACHE": "bytes"}):
            self.assertEqual(render_cache_policy(), "bytes")
        with patch.dict(os.environ, {"MANIML_RENDER_CACHE": "hash"}), self.assertRaises(ValueError):
            render_cache_policy()


class BorderSourceRevision(unittest.TestCase):
    @no_verify
    def test_same_revision_skips_byte_comparison_but_a_method_mutation_is_read(self):
        mob = shape()
        cache = BorderRecipeCache()
        cache.begin_frame()
        first = cache.source(mob, UNIFORMS, revision=mob.revision)
        cache.finish_frame()
        cache.begin_frame()
        with patch.object(border_geometry, "_same_bytes", side_effect=AssertionError("compared bytes")):
            again = cache.source(mob, UNIFORMS, revision=mob.revision)
        self.assertIs(again, first)
        cache.finish_frame()
        mob.shift([1, 0, 0])  # bumps revision through affects_data
        cache.begin_frame()
        moved = cache.source(mob, UNIFORMS, revision=mob.revision)
        self.assertIsNot(moved, first)
        self.assertFalse(np.array_equal(moved[:, :3], first[:, :3]))

    def test_bytes_policy_still_reads_arrays_every_frame(self):
        mob = shape()
        with patch.dict(os.environ, {"MANIML_RENDER_CACHE": "bytes"}):
            cache = BorderRecipeCache()
            cache.begin_frame()
            first = cache.source(mob, UNIFORMS, revision=mob.revision)
            cache.finish_frame()
            mob.data["point"][:, 0] += .5  # bypasses the counter on purpose
            cache.begin_frame()
            self.assertFalse(np.array_equal(cache.source(mob, UNIFORMS, revision=mob.revision), first))

    def test_verify_mode_names_the_attribute_a_bypassing_write_left_stale(self):
        mob = shape()
        cache = BorderRecipeCache()
        cache.begin_frame()
        cache.source(mob, UNIFORMS, revision=mob.revision)
        cache.finish_frame()
        mob.data["point"][:, 0] += .5
        cache.begin_frame()
        with patch.dict(os.environ, {"MANIML_VERIFY_LEDGER": "1"}):
            with self.assertRaisesRegex(RenderCacheStale, "Circle changed in 'data'"):
                cache.source(mob, UNIFORMS, revision=mob.revision)
        # Without verification the reuse is stale: the policy's documented
        # contract is that every mutation goes through a bumping method.
        with no_verify:
            self.assertTrue(np.array_equal(cache.source(mob, UNIFORMS, revision=mob.revision),
                                           cache.source(mob, UNIFORMS, revision=mob.revision)))

    def test_custom_source_getters_and_dirty_flags_are_never_trusted(self):
        mob = shape()
        source = BorderSource.read(mob, UNIFORMS)
        mob.data["point"][:, 0] += .5
        # Dirty derived state re-reads even when the caller trusts the revision.
        mob.needs_new_unit_normal = True
        fresh = BorderSource.read(mob, UNIFORMS, previous=source, trusted=True)
        self.assertIsNot(fresh, source)
        custom = shape()
        custom.get_shader_data = lambda: Circle.get_shader_data(custom)
        first = BorderSource.read(custom, UNIFORMS)
        custom.data["point"][:, 0] += .5
        self.assertIsNot(BorderSource.read(custom, UNIFORMS, previous=first, trusted=True), first)


@unittest.skipUnless(os.environ.get("MANIML_LYON_LIBRARY") or _packaged_library(),
                     "Lyon helper is neither packaged nor explicitly built")
class MeshCacheRevision(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tessellator = LyonFillTessellator()

    def prepare(self, scene, cache):
        return prepare_triangle_frame(scene, self.tessellator, mesh_cache=cache,
                                      fill_borders=True, gpu_borders=True)

    @no_verify

    def test_unchanged_frame_reads_no_source_arrays(self):
        shapes = (shape(), Square(fill_opacity=1, stroke_width=0))
        scene, cache = build_scene(*shapes), TriangleMeshCache()
        first = self.prepare(scene, cache)
        original = triangle_scene.Mobject.get_points

        def guarded(mobject):
            if any(mobject is drawn for drawn in shapes):
                raise AssertionError("read points")
            return original(mobject)  # the camera frame may read its own

        with patch.object(triangle_scene.np, "array_equal", side_effect=AssertionError("compared arrays")), \
                patch.object(border_geometry, "_same_bytes", side_effect=AssertionError("compared bytes")), \
                patch.object(triangle_scene.Mobject, "get_points", guarded):
            second = self.prepare(scene, cache)
        for before, after in zip(first.draws, second.draws):
            self.assertIs(before.vertices, after.vertices)
            self.assertIs(before.indices, after.indices)
        self.assertEqual(second.mesh_cache_stats["regenerations"], 0)
        # This counter is cumulative across frames.
        self.assertEqual(second.mesh_cache_stats["gpu_border_source_updates"],
                         first.mesh_cache_stats["gpu_border_source_updates"])

    def test_method_mutations_and_color_changes_are_seen(self):
        circle = shape()
        scene, cache = build_scene(circle), TriangleMeshCache()
        first = self.prepare(scene, cache)
        circle.set_fill(RED, opacity=.25)
        second = self.prepare(scene, cache)
        self.assertEqual(second.mesh_cache_stats["paint_updates"], 1)
        np.testing.assert_allclose(second.draws[0].vertices["rgba"][0], circle.data["fill_rgba"][0])
        circle.scale(1.5)
        third = self.prepare(scene, cache)
        self.assertEqual(third.mesh_cache_stats["regenerations"], 1)
        self.assertGreater(np.abs(third.draws[0].vertices["point"]).max(),
                           np.abs(first.draws[0].vertices["point"]).max())

    def test_verify_mode_catches_a_bypassing_point_write_in_the_fill_path(self):
        circle = shape()
        scene, cache = build_scene(circle), TriangleMeshCache()
        self.prepare(scene, cache)
        circle.data["point"][:, 1] += .25
        with patch.dict(os.environ, {"MANIML_VERIFY_LEDGER": "1"}):
            with self.assertRaisesRegex(RenderCacheStale, "changed in '(points|data)'"):
                self.prepare(scene, cache)
        with patch.dict(os.environ, {"MANIML_RENDER_CACHE": "bytes"}):
            refreshed = self.prepare(scene, cache)
        self.assertEqual(refreshed.mesh_cache_stats["regenerations"], 1)

    def test_camera_changes_and_a_replaced_object_still_regenerate(self):
        circle = shape()
        scene, cache = build_scene(circle), TriangleMeshCache()
        first = self.prepare(scene, cache)
        scene.camera.frame.scale(.1)  # a real refinement, not a source change
        zoomed = self.prepare(scene, cache)
        self.assertEqual(zoomed.mesh_cache_stats["regenerations"], 1)
        self.assertGreater(len(zoomed.draws[0].vertices), len(first.draws[0].vertices))
        copy = circle.copy()  # a new object at the same revision is its own entry
        self.assertEqual(copy.revision, circle.revision)
        replaced = self.prepare(build_scene(copy), cache)
        self.assertEqual(replaced.mesh_cache_stats["regenerations"], 1)

    def test_serialized_frames_agree_between_policies(self):
        scene = build_scene(shape(), Square(fill_opacity=.5, stroke_width=0, fill_border_width=2))
        frames = {}
        for policy in ("revision", "bytes"):
            with patch.dict(os.environ, {"MANIML_RENDER_CACHE": policy}):
                cache = GeometryCache()
                serialize_scene(scene, cache, renderer="triangles")
                scene.camera.frame.shift([.01, 0, 0])
                header, raw = parse_geometry_message(serialize_scene(scene, cache, renderer="triangles"))
                scene.camera.frame.shift([-.01, 0, 0])
                frames[policy] = ([b["hash"] for b in header["batches"]], raw)
        self.assertEqual(frames["revision"], frames["bytes"])


if __name__ == "__main__":
    unittest.main()


class ZoomStepLeftovers(unittest.TestCase):
    """A zoom step must not re-read or rebuild what only the camera changed."""

    def test_density_summary_reserves_exactly_what_the_step_counts_need(self):
        from maniml.web.gpu_border_geometry import (
            density_summary, required_capacity, required_from_density)
        mob = shape()
        for scale in (8., 2., 1., .5, .1, .02, .005):
            uniforms = dict(UNIFORMS, frame_scale=scale)
            source = BorderSource.read(mob, uniforms)
            max_density, capped = density_summary(source)
            self.assertFalse(capped)
            self.assertEqual(required_from_density(max_density, capped, scale), required_capacity(source))
        self.assertEqual(required_from_density(0.0, True, 1.0), 64)
        self.assertEqual(required_from_density(0.0, False, 1.0), 4)
        with self.assertRaises(ValueError):
            required_from_density(1.0, False, 0.0)

    def test_a_trusted_zoom_step_reads_nothing_and_still_grows_the_reservation(self):
        mob = shape()
        cache = BorderRecipeCache()
        cache.begin_frame()
        first = cache.source(mob, UNIFORMS, revision=mob.revision)
        before = cache.capacity(mob)
        cache.finish_frame()
        closer = dict(UNIFORMS, frame_scale=UNIFORMS["frame_scale"] / 8)
        with no_verify, patch.object(BorderSource, "read", side_effect=AssertionError("re-read the source")):
            cache.begin_frame()
            self.assertIs(cache.source(mob, closer, revision=mob.revision), first)
            cache.finish_frame()
        grown = cache.capacity(mob)
        self.assertGreater(grown, before)
        need = BorderSource.read(mob, closer)
        from maniml.web.gpu_border_geometry import required_capacity
        self.assertGreaterEqual(grown, required_capacity(need))
        self.assertEqual(cache.source_updates, 1)


@unittest.skipUnless(os.environ.get("MANIML_LYON_LIBRARY") or _packaged_library(),
                     "Lyon helper is neither packaged nor explicitly built")
class BatchedProjectionBounds(unittest.TestCase):
    def test_batched_bounds_equal_the_per_entry_bounds(self):
        from maniml.web.triangle_scene import _batched_projection_errors, _projection_state
        shapes = [shape().shift([i - 2, .3 * i, 0]).scale(.5 + .2 * i) for i in range(5)]
        shapes.append(Square(fill_opacity=1, stroke_width=0).shift([0, -2, 0]))
        scene, cache = build_scene(*shapes), TriangleMeshCache()
        tessellator = LyonFillTessellator()
        prepare_triangle_frame(scene, tessellator, mesh_cache=cache, fill_borders=True, gpu_borders=True)
        scene.camera.frame.scale(.3).shift([.4, -.2, 0])
        scene.camera.refresh_uniforms()
        uniforms = {key: v for key, v in scene.camera.uniforms.items()}
        resolution = tuple(scene.camera.draw_fbo.size)
        entries = [cache._entries[id(sm)] for sm in shapes]
        _, projection = _projection_state(uniforms, resolution, None)
        batched = _batched_projection_errors(entries, projection, resolution)
        for entry, error in zip(entries, batched):
            single = entry.geometry.pixel_error(entry.source, uniforms, resolution, projection=projection)
            self.assertAlmostEqual(error, single, delta=1e-9 * max(1.0, single))
        # And the frame path uses them: every entry is memoized for this camera.
        before = cache.stats["regenerations"]
        prepare_triangle_frame(scene, tessellator, mesh_cache=cache, fill_borders=True, gpu_borders=True)
        keys = {cache._entries[id(sm)].projection_key for sm in shapes if id(sm) in cache._entries}
        self.assertEqual(len(keys), 1)


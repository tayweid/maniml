"""CPU regressions for the production source-to-triangle integration.

These exercise the serialized material/order contract and public-array cache
invalidation. Image quality and shader execution belong to GPU acceptance.
"""

import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image

from maniml.mobject.geometry import Circle, Square
from maniml.mobject.types.vectorized_mobject import VMobject
from maniml.mobject.types.image_mobject import ImageMobject
from maniml.mobject.types.surface import Surface, TexturedSurface
from maniml.web.geometry import GeometryCache, parse_geometry_message, serialize_scene
from maniml.web.triangle_geometry import LyonFillTessellator, _packaged_library
from maniml.web.triangle_scene import (
    TriangleMeshCache, UnsupportedPrototype, _border_hull,
    mesh_mobject, planar_coordinates, prepare_triangle_frame, projection_scale_bound,
)
from tests.renderer_fixtures import build_scene, closed_contours


def draw_area(draw):
    points = draw.vertices["point"][draw.indices.reshape(-1, 3)].astype(float)
    return float(np.linalg.norm(np.cross(points[:, 1] - points[:, 0],
                                         points[:, 2] - points[:, 0]), axis=1).sum() / 2)


def draw_bounds(draw):
    return np.array([draw.vertices["point"][:, :2].min(axis=0),
                     draw.vertices["point"][:, :2].max(axis=0)])


@unittest.skipUnless(os.environ.get("MANIML_LYON_LIBRARY") or _packaged_library(),
                     "Lyon helper is neither packaged nor explicitly built")
class GeneratedSceneGeometry(unittest.TestCase):
    def setUp(self):
        self.tessellator = LyonFillTessellator()
        self.cache = TriangleMeshCache()
        self.path = Square(side_length=2, fill_opacity=.4, stroke_width=0,
                           fill_border_width=10, joint_type="auto")
        self.scene = build_scene(self.path)

    def prepare(self):
        return prepare_triangle_frame(self.scene, self.tessellator,
            mesh_cache=self.cache, fill_borders=True, coalesce=False)

    def test_border_width_join_and_zero_toggle_invalidate_actual_geometry(self):
        original = self.path.get_points().copy()
        first = self.prepare()
        self.assertTrue(first.draws[0].coverage)
        np.testing.assert_allclose(draw_bounds(first.draws[0]), [[-1.05, -1.05], [1.05, 1.05]])
        self.assertEqual(self.prepare().mesh_cache_stats["hits"], 1)
        revision = self.path.revision
        self.path.data["fill_border_width"][:] = 20  # no revision bump
        self.assertEqual(self.path.revision, revision)
        wide = self.prepare()
        self.assertEqual(wide.mesh_cache_stats["regenerations"], 0)
        self.assertEqual(wide.mesh_cache_stats["border_regenerations"], 1)
        np.testing.assert_allclose(draw_bounds(wide.draws[0]), [[-1.1, -1.1], [1.1, 1.1]])
        self.path.uniforms["joint_type"] = 3
        miter = self.prepare()
        self.assertEqual(miter.mesh_cache_stats["regenerations"], 0)
        self.assertEqual(miter.mesh_cache_stats["border_regenerations"], 1)
        self.assertFalse(np.array_equal(miter.draws[0].vertices, wide.draws[0].vertices))
        self.path.data["fill_border_width"][:] = 0
        plain = self.prepare()
        self.assertEqual(plain.mesh_cache_stats["regenerations"], 0)
        self.assertFalse(plain.draws[0].coverage)
        self.assertAlmostEqual(draw_area(plain.draws[0]), 4, places=5)
        np.testing.assert_array_equal(self.path.get_points(), original)
        np.testing.assert_allclose(draw_bounds(first.draws[0]), [[-1.05, -1.05], [1.05, 1.05]])

    def test_uniform_border_paint_refresh_preserves_geometry_and_old_frames(self):
        before = self.prepare().draws[0]
        old_vertices = before.vertices.copy()
        self.path.data["fill_rgba"][:] = [.2, .4, .8, .3]
        with patch("maniml.web.triangle_scene._generate_mesh",
                   side_effect=AssertionError("paint regenerated geometry")):
            updated = self.prepare()
        after = updated.draws[0]
        self.assertEqual(updated.mesh_cache_stats["paint_updates"], 1)
        self.assertEqual(updated.mesh_cache_stats["regenerations"], 0)
        self.assertEqual(updated.mesh_cache_stats["border_regenerations"], 0)
        self.assertIs(before.indices, after.indices)
        np.testing.assert_array_equal(before.vertices, old_vertices)
        np.testing.assert_array_equal(after.vertices["point"], old_vertices["point"])
        np.testing.assert_allclose(after.vertices["rgba"], np.tile([.2, .4, .8, .3], (len(after.vertices), 1)))

    def test_camera_dependent_width_regenerates_but_pan_reuses(self):
        self.path.set_scale_stroke_with_zoom(False)
        source = self.path.get_points().copy()
        first = self.prepare()
        self.scene.camera.frame.scale(.8)
        zoom = self.prepare()
        self.assertEqual(zoom.mesh_cache_stats["regenerations"], 0)
        self.assertEqual(zoom.mesh_cache_stats["border_regenerations"], 1)
        np.testing.assert_allclose(draw_bounds(zoom.draws[0]), [[-1.04, -1.04], [1.04, 1.04]])
        self.assertFalse(np.array_equal(first.draws[0].vertices, zoom.draws[0].vertices))
        self.scene.camera.frame.shift([.1, -.15, 0])
        pan = self.prepare()
        self.assertEqual(pan.mesh_cache_stats["hits"], 1)
        self.assertIs(pan.draws[0].vertices, zoom.draws[0].vertices)
        np.testing.assert_array_equal(self.path.get_points(), source)

    def test_world_width_survives_camera_zoom_with_mesh_reuse(self):
        self.path.set_scale_stroke_with_zoom(True)
        first = self.prepare()
        self.scene.camera.frame.scale(.8)
        zoom = self.prepare()
        self.assertEqual(zoom.mesh_cache_stats["hits"], 1)
        self.assertIs(zoom.draws[0].vertices, first.draws[0].vertices)
        np.testing.assert_allclose(draw_bounds(zoom.draws[0]), [[-1.05, -1.05], [1.05, 1.05]])

    def test_border_hull_checks_singularity_beyond_source_controls(self):
        path = closed_contours([(-.01, 0, .94), (.01, 0, .94),
                                (.01, 0, .96), (-.01, 0, .96)])
        uniforms = {"view": np.eye(4).T.flatten(), "frame_rescale_factors": [1, 1, 1],
                    "is_fixed_in_frame": 0}
        vertices, indices = mesh_mobject(path, self.tessellator, uniforms, (400, 300))
        self.assertGreater(len(indices), 0)
        with patch.object(self.tessellator, "tessellate", side_effect=AssertionError("singular border reached tessellator")):
            with self.assertRaisesRegex(UnsupportedPrototype, "singular"):
                mesh_mobject(path, self.tessellator, uniforms, (400, 300),
                              border_settings=(.2, "bevel"))

    def test_border_projection_hull_contains_generated_miter_geometry(self):
        path = closed_contours([(-1, -.1), (1, 0), (-1, .1)])
        self.scene = build_scene(path)
        self.scene.camera.refresh_uniforms()
        points = path.get_points()
        _, origin, basis, _ = planar_coordinates(points)
        for join in ("bevel", "miter"):
            vertices, _ = mesh_mobject(path, self.tessellator, self.scene.camera.uniforms,
                self.scene.camera.draw_fbo.size, border_settings=(.2, join))
            hull = _border_hull(points, basis, (.2, join))
            local_hull = (hull - origin) @ basis.T
            local_mesh = (vertices["point"] - origin) @ basis.T
            self.assertTrue(np.all(local_mesh >= local_hull.min(axis=0) - 1e-6))
            self.assertTrue(np.all(local_mesh <= local_hull.max(axis=0) + 1e-6))
            self.assertGreater(projection_scale_bound(hull, basis,
                self.scene.camera.uniforms, self.scene.camera.draw_fbo.size), 0)

    def test_variable_width_and_camera_facing_depth_border_keep_source_positions(self):
        self.path.data["fill_border_width"][0, 0] = 11
        self.path.get_shader_data()  # Prime existing derived normal/joint fields.
        before = self.path.data.tobytes()
        varying = self.prepare().draws[0]
        self.assertTrue(varying.coverage)
        self.assertEqual(self.path.data.tobytes(), before)
        self.path.set_flat_stroke(False)
        self.path.apply_depth_test()
        camera_facing = self.prepare().draws[0]
        self.assertEqual(camera_facing.pipeline, "surface_depth")
        self.assertTrue(camera_facing.coverage)
        # Actual camera-facing strips leave the authored XY plane; their depth
        # is preserved for the driver's coverage and final depth passes.
        self.assertGreater(np.ptp(camera_facing.vertices["point"][:, 2]), 1e-5)
        self.scene.camera.frame.shift([.2, .3, 0])
        moved = self.prepare()
        self.assertEqual(moved.mesh_cache_stats["regenerations"], 0)
        self.assertEqual(moved.mesh_cache_stats["border_regenerations"], 1)
        self.assertFalse(np.array_equal(moved.draws[0].vertices, camera_facing.vertices))

    def test_borders_keep_object_ownership_when_plain_fills_could_coalesce(self):
        other = self.path.copy().shift([.2, .1, 0])
        scene = build_scene(self.path, other)
        frame = prepare_triangle_frame(scene, self.tessellator, mesh_cache=self.cache,
                                       fill_borders=True)
        self.assertEqual(len(frame.draws), 2)
        self.assertTrue(all(draw.coverage for draw in frame.draws))
        for draw in frame.draws:
            # Two fill triangles first; border strips add eight triangles. They
            # intentionally overlap and require the driver's stencil ownership.
            self.assertEqual(draw.count, 30)
            self.assertAlmostEqual(draw_area(draw), 4.8, places=5)

    def test_open_fill_border_can_draw_when_fill_interior_is_empty(self):
        path = VMobject(fill_opacity=.3, stroke_width=0, fill_border_width=20)
        path.set_points_as_corners([[-1, 0, 0], [1, 0, 0]])
        frame = prepare_triangle_frame(build_scene(path), self.tessellator,
                                       mesh_cache=self.cache, fill_borders=True)
        self.assertEqual(len(frame.draws), 1)
        draw = frame.draws[0]
        self.assertTrue(draw.coverage)
        self.assertEqual(draw.count, 6)
        np.testing.assert_allclose(draw.vertices["rgba"][:, 3], .3)
        np.testing.assert_allclose(draw_bounds(draw), [[-1, -.1], [1, .1]])

    def test_curve_subdivision_updates_border_without_regenerating_retained_fill(self):
        self.path = Circle(radius=.8, fill_opacity=.4, stroke_width=0, fill_border_width=1)
        self.scene = build_scene(self.path)
        first = self.prepare()
        self.scene.camera.frame.scale(3)
        zoom_out = self.prepare()
        self.assertEqual(zoom_out.mesh_cache_stats["regenerations"], 0)
        self.assertEqual(zoom_out.mesh_cache_stats["border_regenerations"], 1)
        self.assertLess(zoom_out.draws[0].count, first.draws[0].count)

    def test_combined_border_cache_obeys_retention_limit(self):
        first = self.prepare()
        retained = first.mesh_cache_stats["retained_bytes"]
        self.assertGreater(retained, first.geometry_bytes)
        self.cache.max_bytes = 1
        self.path.data["fill_border_width"][:] = 20
        uncached = self.prepare()
        self.assertTrue(uncached.draws[0].coverage)
        self.assertEqual(uncached.mesh_cache_stats["retained_bytes"], 0)
        self.assertEqual(uncached.mesh_cache_stats["entries"], 0)

    def test_border_canonical_snapshot_is_retained_after_stroke_only_edit(self):
        first = self.prepare().draws[0]
        previous = self.cache._entries[id(self.path)].coverage_geometry
        self.path.data["stroke_rgba"][:, 0] = .3  # Public direct write, no fill change.
        second = self.prepare().draws[0]
        self.assertIs(first.vertices, second.vertices)
        source = self.cache._entries[id(self.path)].coverage_geometry.source
        self.assertEqual(source.raw_data.tobytes(), self.path.data.tobytes())
        self.assertEqual(previous.nbytes, sum(a.nbytes for a in (
            *source.arrays(), previous.vertices, previous.indices)))
        with patch("maniml.web.border_geometry._border_density",
                   side_effect=AssertionError("fresh canonical snapshot was discarded")):
            self.scene.camera.frame.scale(.92)
            self.prepare()

    def test_nonplanar_outline_requires_defined_surface_and_preserves_world_z(self):
        from maniml.mobject.types.vmobject_3d import VMobject3D
        path = VMobject(fill_opacity=.5, stroke_width=0).set_points_as_corners(
            [[-1, -1, 0], [1, -1, 0], [1, 1, 1], [-1, 1, 0], [-1, -1, 0]])
        path.get_shader_data()
        source = path.data.tobytes()
        with self.assertRaisesRegex(UnsupportedPrototype, "nonplanar"):
            prepare_triangle_frame(build_scene(path), self.tessellator, fill_borders=True)
        # An outline alone does not define the saddle's interior. The existing
        # VMobject3D conversion explicitly chooses a triangulated Surface; that
        # actual mesh is supported without flattening its authored world depth.
        surface = VMobject3D(path, resolution=12, opacity=.5)
        vertices = surface.get_points().copy()
        indices = surface.get_triangle_indices().copy()
        frame = prepare_triangle_frame(build_scene(surface), self.tessellator, fill_borders=True)
        self.assertEqual(len(frame.draws), 1)
        self.assertEqual(frame.draws[0].pipeline, "surface_depth")
        np.testing.assert_array_equal(frame.draws[0].vertices["point"], vertices[indices])
        self.assertEqual(float(np.ptp(frame.draws[0].vertices["point"][:, 2])), 1.)
        np.testing.assert_array_equal(surface.get_points(), vertices)
        np.testing.assert_array_equal(surface.get_triangle_indices(), indices)
        self.assertEqual(path.data.tobytes(), source)

    def test_border_cpu_batch_chunks_do_not_reject_valid_individual_objects(self):
        from maniml.web.border_geometry import emit_border_triangles
        other = self.path.copy().shift([.2, .1, 0])
        scene = build_scene(self.path, other)
        # Each square has eight border triangles; the shared CPU operation must
        # split a sixteen-triangle aggregate when its chunk capacity is eight.
        with patch("maniml.web.triangle_scene.MAX_BORDER_TRIANGLES", 8), patch(
                "maniml.web.triangle_scene.emit_border_triangles", wraps=emit_border_triangles) as emit:
            frame = prepare_triangle_frame(scene, self.tessellator, mesh_cache=self.cache,
                                           fill_borders=True)
            self.assertEqual(emit.call_count, 2)
        self.assertEqual(len(frame.draws), 2)
        self.assertTrue(all(draw.coverage for draw in frame.draws))
        # Reuse does not invoke vector emission at all, including its grouped
        # preparation path. Each object retains its own immutable output.
        with patch("maniml.web.triangle_scene.emit_border_triangles",
                   side_effect=AssertionError("cached border was emitted")):
            repeated = prepare_triangle_frame(scene, self.tessellator, mesh_cache=self.cache,
                                               fill_borders=True)
        for before, after in zip(frame.draws, repeated.draws):
            self.assertIs(before.vertices, after.vertices)

    def test_image_and_textured_surface_keep_order_depth_textures_and_wire_deltas(self):
        with TemporaryDirectory() as directory:
            filename = Path(directory) / "sample.png"
            Image.new("RGBA", (3, 2), (31, 95, 181, 173)).save(filename)
            image = ImageMobject(str(filename), height=1)
            texture = TexturedSurface(Surface(
                u_range=(-1, 1), v_range=(-1, 1), resolution=(3, 3)), str(filename))
            texture.apply_depth_test()
            fill = Square(fill_opacity=1, stroke_width=0, fill_border_width=0)
            image.z_index, fill.z_index, texture.z_index = 2, 1, 0
            scene = build_scene(image, fill, texture)
            source = [obj.get_points().copy() for obj in (image, fill, texture)]
            frame = prepare_triangle_frame(scene, self.tessellator, fill_borders=True)
            self.assertEqual([d.pipeline for d in frame.draws], ["texsurface_depth", "surface", "image"])
            self.assertEqual([d.vertices.dtype.itemsize for d in frame.draws], [36, 40, 24])
            self.assertEqual(set(frame.draws[0].textures), {"LightTexture", "DarkTexture"})
            self.assertEqual(set(frame.draws[2].textures), {"Texture"})
            wire_cache = GeometryCache()
            first, payload = parse_geometry_message(serialize_scene(scene, wire_cache, renderer="triangles"))
            second, repeated = parse_geometry_message(serialize_scene(scene, wire_cache, renderer="triangles"))
            self.assertEqual([b["pipeline"] for b in first["batches"]], ["texsurface_depth", "surface", "image"])
            self.assertEqual(len(first["texture_data"]), 1)
            ref = next(iter(first["texture_data"].values()))
            self.assertEqual(payload[ref["offset"]:ref["offset"] + ref["nbytes"]], filename.read_bytes())
            self.assertTrue(all(b["cached"] for b in second["batches"]))
            self.assertEqual(second["texture_data"], {})
            self.assertEqual(repeated, b"")
            for obj, before in zip((image, fill, texture), source):
                np.testing.assert_array_equal(obj.get_points(), before)


if __name__ == "__main__":
    unittest.main()

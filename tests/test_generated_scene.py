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

from maniml.mobject.geometry import Square
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


@unittest.skipUnless(os.environ.get("MANIML_LYON_LIBRARY") or _packaged_library(),
                     "Lyon helper is neither packaged nor explicitly built")
class GeneratedSceneGeometry(unittest.TestCase):
    def setUp(self):
        self.tessellator = LyonFillTessellator()
        self.cache = TriangleMeshCache()
        self.path = Square(side_length=2, fill_opacity=.4, stroke_width=0,
                           fill_border_width=10, joint_type="miter")
        self.scene = build_scene(self.path)

    def prepare(self):
        return prepare_triangle_frame(self.scene, self.tessellator,
            mesh_cache=self.cache, fill_borders=True, coalesce=False)

    def test_border_width_join_and_zero_toggle_invalidate_actual_geometry(self):
        original = self.path.get_points().copy()
        first = self.prepare()
        self.assertAlmostEqual(draw_area(first.draws[0]), 2.1 ** 2, places=5)
        self.assertEqual(self.prepare().mesh_cache_stats["hits"], 1)
        revision = self.path.revision
        self.path.data["fill_border_width"][:] = 20  # no revision bump
        self.assertEqual(self.path.revision, revision)
        wide = self.prepare()
        self.assertEqual(wide.mesh_cache_stats["regenerations"], 1)
        self.assertAlmostEqual(draw_area(wide.draws[0]), 2.2 ** 2, places=5)
        self.path.uniforms["joint_type"] = 2
        bevel = self.prepare()
        self.assertEqual(bevel.mesh_cache_stats["regenerations"], 1)
        self.assertAlmostEqual(draw_area(bevel.draws[0]), 2.2 ** 2 - .02, places=5)
        self.path.data["fill_border_width"][:] = 0
        plain = self.prepare()
        self.assertEqual(plain.mesh_cache_stats["regenerations"], 1)
        self.assertAlmostEqual(draw_area(plain.draws[0]), 4, places=5)
        np.testing.assert_array_equal(self.path.get_points(), original)
        self.assertAlmostEqual(draw_area(first.draws[0]), 2.1 ** 2, places=5)

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
        self.assertEqual(zoom.mesh_cache_stats["regenerations"], 1)
        self.assertAlmostEqual(draw_area(zoom.draws[0]), 2.08 ** 2, places=5)
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
        self.assertAlmostEqual(draw_area(zoom.draws[0]), 2.1 ** 2, places=5)

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

    def test_nonuniform_width_and_camera_facing_border_are_explicit_errors(self):
        self.path.data["fill_border_width"][0, 0] = 11
        with self.assertRaisesRegex(UnsupportedPrototype, "uniform nonnegative"):
            self.prepare()
        self.path.data["fill_border_width"][:] = 10
        self.path.set_flat_stroke(False)
        with self.assertRaisesRegex(UnsupportedPrototype, "camera-facing"):
            self.prepare()

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

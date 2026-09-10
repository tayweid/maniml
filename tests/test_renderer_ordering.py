"""Record the deliberate historical browser/native fixed-frame distinction."""

import os
import unittest

import numpy as np

from maniml import Scene, Square, VGroup
from maniml.web.geometry import GeometryCache, parse_geometry_message
from maniml.web.triangle_geometry import LyonFillTessellator
from maniml.web.triangle_scene import prepare_triangle_frame
from maniml.web.winding_geometry import serialize_scene as serialize_original


def authored_bytes(objects):
    return [tuple(obj.data[field].tobytes() for field in
                  ("point", "fill_rgba", "stroke_rgba", "fill_border_width", "stroke_width"))
            for obj in objects]


def shape(marker, z, fixed=False, depth=False):
    obj = Square(side_length=1, fill_opacity=1, stroke_width=0, z_index=z,
                 use_triangulated_fill=depth)
    if fixed:
        obj.fix_in_frame()
    if depth:
        obj.apply_depth_test()
    # Distinct, permissive clipping planes make each ordered operation
    # identifiable without depending on tessellator vertex/index order.
    obj.uniforms["clip_plane"] = (0., 0., 0., float(marker))
    return obj


class RendererOrdering(unittest.TestCase):
    def test_original_wire_and_phase_a_keep_their_declared_order(self):
        scene = Scene(window=None, camera_config={"resolution": (64, 36)})
        self.addCleanup(scene.camera.release)
        world_low = shape(1, -20)
        world_high = shape(2, 100, depth=True)
        overlay_low = shape(3, -10, fixed=True)
        overlay_high = shape(4, 1, fixed=True)
        overlay_tie = shape(5, 1, fixed=True)
        objects = [overlay_high, world_high, overlay_low, world_low, overlay_tie]
        scene.add(*objects)
        before = authored_bytes(objects)
        original, _ = parse_geometry_message(serialize_original(scene, GeometryCache()))
        triangles = prepare_triangle_frame(scene, LyonFillTessellator(), coalesce=False)
        self.assertEqual([batch["uniforms"]["clip_plane"][3] for batch in original["batches"]],
                         [1, 3, 4, 5, 2])
        self.assertEqual([draw.uniforms["clip_plane"][3] for draw in triangles.draws],
                         [1, 2, 3, 4, 5])
        self.assertEqual([draw.pipeline for draw in triangles.draws],
                         ["surface", "surface_depth", "surface", "surface", "surface"])
        self.assertEqual(authored_bytes(objects), before)

    def test_partition_is_by_top_level_group_not_individual_family_member(self):
        scene = Scene(window=None, camera_config={"resolution": (64, 36)})
        self.addCleanup(scene.camera.release)
        # This records an existing limit, rather than making a child's fixed
        # state or z_index silently lift it out of its top-level family.
        family = VGroup(shape(1, 0), shape(2, 100, fixed=True))
        later_world = shape(3, 1)
        scene.add(family, later_world)
        frame = prepare_triangle_frame(scene, LyonFillTessellator(), coalesce=False)
        self.assertEqual([draw.uniforms["clip_plane"][3] for draw in frame.draws], [1, 2, 3])

    def test_compatible_families_rejoin_after_partition_as_at_the_cutover(self):
        scene = Scene(window=None, camera_config={"resolution": (64, 36)})
        self.addCleanup(scene.camera.release)
        high = VGroup(shape(1, 100))
        overlay = VGroup(shape(3, 0)).fix_in_frame()
        low = VGroup(shape(2, -100))
        # VGroup initially copies its first child's style. Make the parent
        # assembly keys match while retaining distinct child clip markers.
        for group in (high, low):
            group.uniforms = dict(group.uniforms, clip_plane=(0., 0., 0., 0.))
        scene.add(high, overlay, low)
        frame = prepare_triangle_frame(scene, LyonFillTessellator(), coalesce=False)
        self.assertEqual([draw.uniforms["clip_plane"][3] for draw in frame.draws], [2, 1, 3])
        # Original retains the pre-cutover browser grouping and local family
        # sort. No globally flattened child z-index policy is introduced.
        original, _ = parse_geometry_message(serialize_original(scene, GeometryCache()))
        self.assertEqual([batch["uniforms"]["clip_plane"][3] for batch in original["batches"]],
                         [1, 3, 2])


@unittest.skipUnless(os.environ.get("MANIML_TEST_GPU") == "1", "real GPU check not requested")
class RendererOrderingPixels(unittest.TestCase):
    def test_fixed_overlay_policy_matches_native_gl_and_preserves_original_browser(self):
        from maniml import NativeGLCamera
        from tests.winding_reference_renderer import WgpuRenderer as OriginalRenderer

        scene = Scene(window=None, camera_config={"resolution": (96, 54)})
        self.addCleanup(scene.camera.release)
        overlay = shape(1, -10, fixed=True).set_fill("#FF0000")
        world = shape(2, 100, depth=True).set_fill("#0000FF")
        scene.add(overlay, world)
        before = authored_bytes([overlay, world])
        reference = NativeGLCamera(resolution=(96, 54))
        self.addCleanup(reference.release)
        original = OriginalRenderer()
        self.addCleanup(original.device.destroy)
        scene.update_frame(force_draw=True)
        reference.capture(*scene.render_groups)
        picture = original.render(*parse_geometry_message(serialize_original(scene, GeometryCache())))
        # Fixed red goes last in both native paths. Original browser preserves
        # its z-ordered blue draw, including the depth-tested surface and clip.
        np.testing.assert_allclose(scene.get_image().getpixel((48, 27)), [255, 0, 0, 255], atol=1)
        np.testing.assert_allclose(reference.get_image().getpixel((48, 27)), [255, 0, 0, 255], atol=1)
        np.testing.assert_allclose(picture.getpixel((48, 27)), [0, 0, 255, 255], atol=1)
        self.assertEqual(authored_bytes([overlay, world]), before)


if __name__ == "__main__":
    unittest.main()

"""Geometry deltas must track mesh connectivity as well as vertex data."""

from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np

from maniml.camera.camera import Camera
from maniml.camera.camera_frame import CameraFrame
from maniml.mobject.geometry import Square
from maniml.mobject.mobject import Group, Point
from tests.gl_reference_shader_wrapper import VShaderWrapper
from tests.winding_reference_geometry import GeometryCache, parse_geometry_message, serialize_scene


class GeometryMeshCache(unittest.TestCase):
    def setUp(self):
        # Use the real projection/serializer without allocating a GL context.
        camera = Camera.__new__(Camera)
        camera.frame = CameraFrame()
        camera.light_source = Point(np.array([-10., 10., 10.]))
        camera.uniforms = {}
        camera.fbo = camera.draw_fbo = SimpleNamespace(size=(384, 216))
        camera.background_rgba = [0., 0., 0., 1.]
        camera.samples = 0
        square = Square(fill_opacity=1, use_triangulated_fill=True)
        self.scene = SimpleNamespace(camera=camera, render_groups=[Group(square)])
        self.cache = GeometryCache()
        self.vertices = np.array([
            [-1., -1., 0.], [1., -1., 0.],
            [1., 1., 0.], [-1., 1., 0.],
        ])

    def serialize_indices(self, indices):
        # Only the triangulator's connectivity changes: source paths, generated
        # vertices, styles, and camera are identical between these frames.
        indices = np.asarray(indices, dtype=np.int32)
        with patch.object(VShaderWrapper, "_get_triangulation",
                          return_value=(self.vertices, indices)):
            header, data = parse_geometry_message(
                serialize_scene(self.scene, self.cache))
        self.assertEqual(header["unsupported"], [])
        self.assertEqual(len(header["batches"]), 1)
        return header["batches"][0], data

    def assert_index_update_is_sent(self, replacement):
        original = [0, 1, 2, 0, 2, 3]
        first, first_data = self.serialize_indices(original)
        unchanged, unchanged_data = self.serialize_indices(original)
        self.assertTrue(unchanged.get("cached"))
        self.assertEqual(unchanged["hash"], first["hash"])
        self.assertEqual(unchanged_data, b"")

        changed, changed_data = self.serialize_indices(replacement)
        self.assertNotEqual(changed["hash"], first["hash"])
        self.assertFalse(changed.get("cached", False))
        self.assertEqual(changed["tri"]["icount"], len(replacement))
        # All bytes before the index buffer really are unchanged. Inspect the
        # wire payload, rather than deriving the expected content hash.
        index_offset = changed["tri"]["ioffset"]
        self.assertEqual(index_offset, first["tri"]["ioffset"])
        self.assertEqual(changed_data[:index_offset], first_data[:index_offset])
        received = np.frombuffer(changed_data, dtype=np.uint32,
                                 offset=index_offset, count=len(replacement))
        np.testing.assert_array_equal(received, replacement)

        repeated, repeated_data = self.serialize_indices(replacement)
        self.assertTrue(repeated.get("cached"))
        self.assertEqual(repeated["hash"], changed["hash"])
        self.assertEqual(repeated_data, b"")

        restored, restored_data = self.serialize_indices(original)
        self.assertTrue(restored.get("cached"))
        self.assertEqual(restored["hash"], first["hash"])
        self.assertEqual(restored_data, b"")

    def test_index_only_diagonal_change_resends_mesh(self):
        self.assert_index_update_is_sent([0, 1, 3, 1, 2, 3])

    def test_index_count_change_resends_mesh(self):
        self.assert_index_update_is_sent([0, 1, 2])


if __name__ == "__main__":
    unittest.main()

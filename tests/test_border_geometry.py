"""CPU coverage checks for Manim's derived fill-border triangle strips."""

import unittest
from unittest.mock import patch

import numpy as np

from maniml.mobject.geometry import Circle, Square
from maniml.web.border_geometry import BorderSource, _border_density, border_step_counts, emit_border_triangles
from maniml.web.triangle_geometry import TessellationLimitError


DTYPE = np.dtype([("point", "f4", 3), ("fill_rgba", "f4", 4),
                  ("fill_border_width", "f4", 1), ("joint_angle", "f4", 1),
                  ("base_normal", "f4", 3)])


def segment(points=((-1, 0, 0), (0, 0, 0), (1, 0, 0)), widths=(20, 20, 20)):
    data = np.zeros(3, dtype=DTYPE)
    data["point"] = points
    data["fill_rgba"] = (.2, .4, .8, .3)
    data["fill_border_width"][:, 0] = widths
    data["base_normal"] = (0, 0, 1)
    return data


UNIFORMS = dict(frame_scale=1., scale_stroke_with_zoom=1., flat_stroke=1.,
                is_fixed_in_frame=0., joint_type=1., camera_position=(0, 0, 10))


def border(data, **changes):
    return emit_border_triangles(data, dict(UNIFORMS, **changes), normal_offset=False)


class BorderGeometry(unittest.TestCase):
    def test_camera_updates_reuse_canonical_bytes_density_and_expansion(self):
        path = Circle(fill_opacity=.5, fill_border_width=2)
        first = BorderSource.read(path, UNIFORMS).frozen()
        original = path.data.tobytes()
        with patch("maniml.web.border_geometry._border_density",
                   side_effect=AssertionError("unchanged curves recomputed density")):
            self.assertIs(BorderSource.read(path, UNIFORMS, previous=first), first)
            zoom = BorderSource.read(path, dict(UNIFORMS, frame_scale=.1), previous=first).frozen()
        for name in ("data", "density", "active", "raw_data", "raw_indices"):
            self.assertIs(getattr(first, name), getattr(zoom, name))
        self.assertFalse(np.array_equal(first.counts, zoom.counts))
        expected = border_step_counts(first.data["point"].reshape(-1, 3, 3), .1)
        np.testing.assert_array_equal(zoom.counts, expected)
        self.assertEqual(path.data.tobytes(), original)
        for array in zoom.arrays():
            self.assertFalse(array.flags.writeable)
            with self.assertRaises(ValueError):
                array.setflags(write=True)

    def test_canonical_snapshot_detects_direct_writes_and_dirty_derived_data(self):
        path = Square(fill_opacity=.5, fill_border_width=2)
        previous = BorderSource.read(path, UNIFORMS).frozen()
        revision = path.revision
        path.data["fill_border_width"][0] = 7
        changed = BorderSource.read(path, UNIFORMS, previous=previous).frozen()
        self.assertEqual(path.revision, revision)
        self.assertNotEqual(previous, changed)
        self.assertEqual(changed.data["fill_border_width"][0], 7)
        path.needs_new_joint_angles = True
        with patch("maniml.web.border_geometry._border_density", wraps=_border_density) as density:
            BorderSource.read(path, UNIFORMS, previous=changed)
        self.assertEqual(density.call_count, 1)
        self.assertFalse(path.needs_new_joint_angles)
        path.needs_new_unit_normal = True
        with patch("maniml.web.border_geometry._border_density", wraps=_border_density) as density:
            BorderSource.read(path, UNIFORMS, previous=changed)
        self.assertEqual(density.call_count, 1)
        self.assertFalse(path.needs_new_unit_normal)
        # Derived expansion indices can also be edited directly.
        path.outer_vert_indices[:3] = path.outer_vert_indices[:3][::-1]
        reordered = BorderSource.read(path, UNIFORMS, previous=changed)
        np.testing.assert_array_equal(reordered.data["point"][:3], changed.data["point"][:3][::-1])

    def test_custom_source_getter_cannot_reuse_arbitrary_external_state(self):
        class DynamicBorder(Square):
            def get_shader_data(self):
                self.calls += 1
                data = super().get_shader_data()
                data["fill_border_width"] *= self.multiplier
                return data

        path = DynamicBorder(fill_opacity=.5, fill_border_width=2)
        path.calls, path.multiplier = 0, 1
        first = BorderSource.read(path, UNIFORMS).frozen()
        path.multiplier = 2
        second = BorderSource.read(path, UNIFORMS, previous=first)
        self.assertEqual(path.calls, 2)
        self.assertFalse(first.cacheable)
        self.assertNotEqual(first, second)
        np.testing.assert_array_equal(second.data["fill_border_width"], first.data["fill_border_width"] * 2)

    def test_open_variable_width_is_one_trapezoid_without_implicit_closure(self):
        data = segment(widths=(10, 999, 30))
        triangles = border(data)
        self.assertEqual(triangles.shape, (2, 3, 3))
        # Handle width is deliberately different: the shader interpolates only
        # endpoint widths. Open endpoints end at x=-1 and x=1 without caps.
        expected = np.array([[[-1, -.05, 0], [-1, .05, 0], [1, -.15, 0]],
                             [[-1, .05, 0], [1, -.15, 0], [1, .15, 0]]])
        np.testing.assert_allclose(triangles, expected, atol=1e-14)

    def test_partial_sentinels_invisible_segments_and_zero_widths(self):
        valid = segment(widths=(0, 0, 20))
        sentinel = segment(points=((2, 0, 0), (2, 0, 0), (3, 0, 0)))
        hidden = segment()
        hidden["fill_rgba"][:, 3] = 0
        zero = segment(widths=(0, 0, 0))
        np.testing.assert_array_equal(border(np.concatenate([valid, sentinel, hidden, zero])),
                                      border(valid))
        # A collapsed end handle uses the finite limiting tangent; an entirely
        # collapsed curve is the sentinel above and emits no vertices.
        collapsed_end = segment(points=((-1, 0, 0), (1, 0, 0), (1, 0, 0)))
        np.testing.assert_allclose(border(collapsed_end), border(segment()), atol=1e-14)

    def test_width_zoom_policy_and_readonly_source_byte_invariance(self):
        data = segment()
        before = data.tobytes()
        data.flags.writeable = False
        unchanged = border(data, frame_scale=.5)
        np.testing.assert_array_equal(unchanged, border(data))
        fixed_width = border(data, frame_scale=.5, scale_stroke_with_zoom=0)
        np.testing.assert_allclose(fixed_width[:, :, 1], unchanged[:, :, 1] / 2)
        fixed_width[:] = 10
        self.assertEqual(data.tobytes(), before)

    def test_wgsl_count_ties_are_even_and_zoom_refines(self):
        points = np.array([[[0, 0, 0], [1, 0, 0], [0, 2, 0]]], dtype="f4")
        self.assertEqual(border_step_counts(points, 200).tolist(), [2])  # round(.5)=0
        self.assertEqual(border_step_counts(points, 40).tolist(), [4])   # round(2.5)=2
        self.assertEqual(border_step_counts(points, 20).tolist(), [7])
        self.assertEqual(border_step_counts(points, .001).tolist(), [32])
        with self.assertRaises(ValueError):
            border_step_counts(points, 0)

    def test_authored_square_join_corners_follow_manim_not_svg_names(self):
        square = Square(side_length=2, fill_opacity=.4, stroke_width=0,
                        fill_border_width=20)
        data = square.get_shader_data()
        source = data.tobytes()
        # The first edge runs left from (1,1). Source auto and "bevel" extend
        # to the offset-line intersection at this 90-degree corner. Source
        # "miter" uses the opposite diagonal, unlike SVG's miter convention.
        expected = {0: [[1, 1.1, 0], [1, .9, 0]],
                    1: [[1.1, 1.1, 0], [.9, .9, 0]],
                    2: [[1.1, 1.1, 0], [.9, .9, 0]],
                    3: [[.9, 1.1, 0], [1.1, .9, 0]]}
        for joint, corners in expected.items():
            with self.subTest(joint=joint):
                np.testing.assert_allclose(border(data, joint_type=joint)[0, :2],
                                           corners, atol=2e-8)
        self.assertEqual(data.tobytes(), source)

    def test_auto_join_switches_continuously_for_sharp_corners(self):
        data = segment()
        for cosine, expected_mix in ((-.8, 0), (-.85, .5), (-.9, 1)):
            data["joint_angle"][2] = np.arccos(cosine)
            automatic = border(data, joint_type=1)
            bevel = border(data, joint_type=2)
            miter = border(data, joint_type=3)
            np.testing.assert_allclose(automatic, (1 - expected_mix) * bevel + expected_mix * miter,
                                       atol=1e-6)  # Authored angles are float32.

    def test_camera_facing_strip_keeps_actual_world_depth(self):
        data = segment()
        camera = (0, 10, 10)
        result = border(data, flat_stroke=0, camera_position=camera)
        # For an X-axis line, the lateral direction is perpendicular to X and
        # the sightline. A screen-plane drop would lose the nonzero Z offsets.
        np.testing.assert_allclose(result[:, :, 2], -result[:, :, 1], atol=1e-14)
        np.testing.assert_allclose(np.abs(result[:, :, 1]), .1 / np.sqrt(2), atol=1e-14)
        fixed = border(data, flat_stroke=0, is_fixed_in_frame=1, camera_position=camera)
        np.testing.assert_array_equal(fixed, border(data))
        shifted = emit_border_triangles(data, dict(UNIFORMS, flat_stroke=0, camera_position=camera))
        self.assertFalse(np.array_equal(result, shifted))
        with_normals, normals = emit_border_triangles(data,
            dict(UNIFORMS, flat_stroke=0, camera_position=camera), return_normals=True)
        np.testing.assert_array_equal(with_normals, shifted)
        np.testing.assert_allclose(np.linalg.norm(normals, axis=-1), 1)
        centers = np.array([[-1, 0, 0], [1, 0, 0]])
        expected_normals = np.asarray(camera, dtype=float) - centers
        expected_normals /= np.linalg.norm(expected_normals, axis=1)[:, None]
        np.testing.assert_allclose(normals[0, :2], np.tile(expected_normals[0], (2, 1)))
        np.testing.assert_allclose(normals[0, 2], expected_normals[1])
        self.assertTrue(np.isfinite(border(data, flat_stroke=0, camera_position=(10, 0, 0))).all())

    def test_bounded_failure_does_not_change_source(self):
        data = segment()
        original = data.tobytes()
        with patch("maniml.web.border_geometry.MAX_BORDER_TRIANGLES", 1):
            with self.assertRaises(TessellationLimitError):
                border(data)
        self.assertEqual(data.tobytes(), original)
        data["fill_border_width"][0] = -1
        with self.assertRaisesRegex(ValueError, "nonnegative"):
            border(data)

    def test_ragged_curve_batches_preserve_object_order_and_normals(self):
        straight = segment(widths=(0, 5, 20))
        curve = segment(points=((-1, 0, 0), (.3, .8, 0), (1, 0, 0)), widths=(10, 90, 30))
        curve["joint_angle"][[0, 2], 0] = [.7, -2.5]
        hidden = segment()
        hidden["fill_rgba"][:, 3] = 0
        data = np.concatenate([straight, curve, hidden])
        for flat in (0, 1):
            for joint in range(4):
                uniforms = dict(UNIFORMS, frame_scale=7, flat_stroke=flat, joint_type=joint,
                                camera_position=(.4, 2., 4.))
                individual = [emit_border_triangles(part, uniforms, return_normals=True)
                              for part in (straight, curve, hidden)]
                counts = border_step_counts(data["point"].reshape(-1, 3, 3), 7)
                batched = emit_border_triangles(data, uniforms, return_normals=True, step_counts=counts)
                for index in (0, 1):
                    np.testing.assert_array_equal(batched[index], np.concatenate([item[index] for item in individual]))
        with self.assertRaisesRegex(ValueError, "step_counts"):
            emit_border_triangles(data, UNIFORMS, step_counts=[2, 33, 2])

    def test_corner_geometry_is_rotation_equivariant(self):
        data = segment(points=((-1, 0, 0), (.3, .8, 0), (1, 0, 0)), widths=(10, 90, 30))
        data["joint_angle"][[0, 2], 0] = [.7, -2.5]
        angle = .63
        rotation = np.array([[np.cos(angle), 0, np.sin(angle)], [0, 1, 0],
                             [-np.sin(angle), 0, np.cos(angle)]])
        rotated = data.copy()
        rotated["point"] = data["point"] @ rotation.T
        rotated["base_normal"] = data["base_normal"] @ rotation.T
        camera = np.array([.4, 2., 4.])
        for flat in (0, 1):
            for joint in range(4):
                kwargs = dict(flat_stroke=flat, joint_type=joint)
                expected = border(data, camera_position=camera, **kwargs) @ rotation.T
                actual = border(rotated, camera_position=camera @ rotation.T, **kwargs)
                np.testing.assert_allclose(actual, expected, atol=1e-6)


if __name__ == "__main__":
    unittest.main()

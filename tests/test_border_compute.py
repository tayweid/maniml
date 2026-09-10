"""GPU border coordinates versus the independent float64 CPU strip emitter."""

import os
from pathlib import Path
import struct
import unittest

import numpy as np

from maniml.web.border_geometry import _border_density, border_step_counts, emit_border_triangles
from maniml.web.geometry import SURFACE_DTYPE
from tests.test_border_geometry import DTYPE, UNIFORMS, segment


def source_records(data):
    """Test producer for the canonical 176-byte source ABI; no device needed."""
    canonical = np.empty(len(data), dtype=DTYPE)
    for name in DTYPE.names:
        canonical[name] = data[name]
    count = len(data) // 3
    records = np.zeros((count, 44), dtype="<f4")
    records[:, :36] = canonical.view("f4").reshape(count, 36)
    points = canonical["point"].reshape(-1, 3, 3)
    density = _border_density(points)
    records[:, 36] = np.where(np.isposinf(density), 0, density)
    records[:, 38] = np.isposinf(density)
    records[:, 37] = (np.any(points[:, 0] != points[:, 1], axis=1)
                       & np.any(canonical["fill_border_width"].reshape(-1, 3) != 0, axis=1)
                       & np.any(canonical["fill_rgba"][:, 3].reshape(-1, 3) != 0, axis=1))
    records[:, 40:44] = canonical["fill_rgba"].reshape(-1, 3, 4)[:, 0]
    return records


def strip_indices():
    left = 2 * np.arange(31, dtype="u4")
    return np.column_stack((left, left + 1, left + 2, left + 1, left + 2, left + 3)).reshape(-1, 3)


class BorderComputeLayout(unittest.TestCase):
    def test_source_and_fixed_strip_layout_have_exact_raw_byte_strides(self):
        source = source_records(segment(widths=(10, 20, 30)))
        self.assertEqual(source.nbytes, 176)
        np.testing.assert_array_equal(source[0, [7, 19, 31]], [10, 20, 30])
        self.assertEqual(source[0, 37], 1)
        self.assertEqual(SURFACE_DTYPE.itemsize, 40)
        indices = strip_indices()
        self.assertEqual(indices.size, 186)
        self.assertEqual(indices.max(), 63)
        np.testing.assert_array_equal(indices[:2], [[0, 1, 2], [1, 2, 3]])


@unittest.skipUnless(os.environ.get("MANIML_TEST_GPU") == "1", "GPU border oracle not requested")
class BorderComputePixels(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import wgpu
        cls.wgpu = wgpu
        cls.device = wgpu.gpu.request_adapter_sync(power_preference="high-performance").request_device_sync()
        directory = Path(__file__).parents[1] / "maniml/web/static/wgsl"
        shader = cls.device.create_shader_module(code="\n".join(
            (directory / name).read_text() for name in ("common.wgsl", "border_compute.wgsl")))
        cls.pipeline = cls.device.create_compute_pipeline(layout="auto", compute={"module": shader, "entry_point": "cs_main"})

    @classmethod
    def tearDownClass(cls):
        cls.device.destroy()

    def dispatch(self, records, uniforms, *, normal_offset=True, curve_offset=0, count=None, output_base=0):
        from maniml.web.wgpu_renderer import pack_uniforms
        wgpu, device = self.wgpu, self.device
        count = len(records) - curve_offset if count is None else count
        buffers = []

        def upload(data, usage):
            buffer = device.create_buffer_with_data(data=data, usage=usage)
            buffers.append(buffer)
            return buffer

        complete = dict(view=np.eye(4).reshape(-1), frame_rescale_factors=(1, 1, 1),
                        light_position=(0, 0, 10), **uniforms)
        source = upload(records.tobytes(), wgpu.BufferUsage.STORAGE | wgpu.BufferUsage.COPY_SRC)
        camera = upload(pack_uniforms(complete), wgpu.BufferUsage.UNIFORM)
        params = upload(struct.pack("<IIIf", curve_offset, count, output_base, .0001 if normal_offset else 0),
                        wgpu.BufferUsage.UNIFORM)
        output = upload(bytes((output_base + count * 64) * 40), wgpu.BufferUsage.STORAGE | wgpu.BufferUsage.COPY_SRC)
        try:
            group0 = device.create_bind_group(layout=self.pipeline.get_bind_group_layout(0), entries=[
                {"binding": 0, "resource": {"buffer": camera}}, {"binding": 1, "resource": {"buffer": params}}])
            group1 = device.create_bind_group(layout=self.pipeline.get_bind_group_layout(1), entries=[
                {"binding": 0, "resource": {"buffer": source}}, {"binding": 1, "resource": {"buffer": output}}])
            encoder = device.create_command_encoder()
            compute = encoder.begin_compute_pass()
            compute.set_pipeline(self.pipeline)
            compute.set_bind_group(0, group0)
            compute.set_bind_group(1, group1)
            compute.dispatch_workgroups(count + 1)  # Last workgroup must not write past this chunk.
            compute.end()
            device.queue.submit([encoder.finish()])
            result = np.frombuffer(device.queue.read_buffer(output), dtype=SURFACE_DTYPE).copy()
            self.assertEqual(bytes(device.queue.read_buffer(source)), records.tobytes())
            self.assertEqual(result[:output_base].tobytes(), bytes(output_base * 40))
            return result[output_base:].reshape(count, 64)
        finally:
            for buffer in buffers:
                buffer.destroy()

    def check_emission(self, data, uniforms, *, normal_offset=True, records=None):
        records = source_records(data) if records is None else records
        output = self.dispatch(records, uniforms, normal_offset=normal_offset)
        counts = border_step_counts(data["point"].reshape(-1, 3, 3), uniforms["frame_scale"])
        active = records[:, 37] != 0
        triangles = []
        normals = []
        for index, vertices in enumerate(output):
            np.testing.assert_array_equal(vertices["rgba"], np.tile(records[index, 40:44], (64, 1)))
            if not active[index]:
                np.testing.assert_array_equal(vertices["point"], np.tile(vertices["point"][0], (64, 1)))
                continue
            used = 2 * (counts[index] - 1)
            corners = strip_indices()[:used]
            triangles.append(vertices["point"][corners])
            normals.append(vertices["d_normal_point"][corners])
            # The padded index region contains only repeated endpoint pairs.
            for triangle in vertices["point"][strip_indices()[used:]]:
                self.assertEqual(float(np.linalg.norm(np.cross(triangle[1] - triangle[0], triangle[2] - triangle[0]))), 0)
        expected, expected_normals = emit_border_triangles(data, uniforms, normal_offset=normal_offset,
                                                         return_normals=True, step_counts=counts)
        actual = np.concatenate(triangles)
        self.assertTrue(np.isfinite(output.view("f4")).all())
        # GPU float32 arithmetic is compared with the CPU float64 oracle after
        # the shared float32 source/count policy. This is an arithmetic bound,
        # not a relaxation of image-quality gates.
        np.testing.assert_allclose(actual, expected, rtol=2e-5, atol=3e-6)
        np.testing.assert_allclose(np.concatenate(normals), expected + .001 * expected_normals,
                                   rtol=2e-5, atol=3e-6)
        return output

    def test_hardened_geometry_all_joins_zoom_widths_and_partial_sentinels(self):
        straight = segment(widths=(0, 99, 20))
        curve = segment(points=((-1, 0, 0), (.3, .8, 0), (1, 0, 0)), widths=(10, 90, 30))
        curve["joint_angle"][[0, 2], 0] = [.7, -2.5]
        collapsed = segment(points=((-1, 0, 0), (1, 0, 0), (1, 0, 0)))
        sentinel = segment(points=((2, 0, 0), (2, 0, 0), (3, 0, 0)))
        hidden, zero = segment(), segment(widths=(0, 0, 0))
        hidden["fill_rgba"][:, 3] = 0
        data = np.concatenate([straight, curve, collapsed, sentinel, hidden, zero])
        before = data.tobytes()
        for flat in (0, 1):
            for joint in range(4):
                for scale in (.5, 7):
                    with self.subTest(flat=flat, joint=joint, scale=scale):
                        self.check_emission(data, dict(UNIFORMS, flat_stroke=flat, joint_type=joint,
                            frame_scale=scale, scale_stroke_with_zoom=0, camera_position=(.4, 2, 4)))
        self.assertEqual(data.tobytes(), before)

    def test_alignment_camera_coincidence_fixed_frame_and_disabled_normal_offset(self):
        data = segment()
        data["joint_angle"][[0, 2], 0] = [.7, -.7]
        for camera in ((10, 0, 0), (1, 0, 0), (10, .001, .001), (0, 10, 10)):
            for fixed in (0, .5, 1):
                with self.subTest(camera=camera, fixed=fixed):
                    self.check_emission(data, dict(UNIFORMS, flat_stroke=0,
                        is_fixed_in_frame=fixed, camera_position=camera), normal_offset=False)

    def test_retained_density_rounds_ties_even_and_caps_subdivision(self):
        data = segment(points=((0, 0, 0), (1, 0, 0), (0, 2, 0)))
        lower = lambda value: np.nextafter(np.float32(value), np.float32(0))
        upper = lambda value: np.nextafter(np.float32(value), np.float32(np.inf))
        for scale, expected in ((upper(200), 2), (200, 2), (lower(200), 3),
                                (upper(40), 4), (40, 4), (lower(40), 5), (20, 7), (.001, 32)):
            with self.subTest(scale=scale):
                self.assertEqual(border_step_counts(data["point"].reshape(-1, 3, 3), scale)[0], expected)
                self.check_emission(data, dict(UNIFORMS, frame_scale=scale))

    def test_auto_join_transition_endpoints_and_midpoint(self):
        for cosine in (-.8, -.85, -.9):
            data = segment()
            angle = np.arccos(cosine)
            data["joint_angle"][[0, 2], 0] = [angle, -angle]
            with self.subTest(cosine=cosine):
                self.check_emission(data, dict(UNIFORMS, joint_type=1))

    def test_finite_huge_curve_keeps_historical_overflow_density_cap_at_all_scales(self):
        data = segment(points=((0, 0, 0), (1e10, 0, 0), (0, 2e10, 0)))
        with np.errstate(over="ignore", invalid="ignore"):
            density = _border_density(data["point"].reshape(-1, 3, 3))
            self.assertTrue(np.isposinf(density[0]))
            records = source_records(data)
            self.assertEqual(records[0, 36], 0)
            self.assertEqual(records[0, 38], 1)
            self.assertTrue(np.isfinite(records).all())
            for scale in (1., 1e30):
                with self.subTest(scale=scale):
                    self.assertEqual(border_step_counts(data["point"].reshape(-1, 3, 3), scale)[0], 32)
                    self.check_emission(data, dict(UNIFORMS, frame_scale=scale), records=records)

    def test_chunk_offsets_colors_and_same_source_with_distinct_uniforms(self):
        data = np.concatenate([segment(), segment(widths=(4, 8, 12)), segment(widths=(12, 16, 20))])
        records = source_records(data)
        records[:, 40:44] = [[1, 0, 0, .2], [0, 1, 0, .5], [0, 0, 1, .8]]
        uniforms = dict(UNIFORMS, flat_stroke=0, camera_position=(0, 10, 10))
        full = self.dispatch(records, uniforms)
        chunk = self.dispatch(records, uniforms, curve_offset=1, count=2, output_base=7)
        np.testing.assert_array_equal(full[1:], chunk)
        other = self.dispatch(records, dict(uniforms, camera_position=(0, -10, 10)))
        self.assertFalse(np.array_equal(full["point"], other["point"]))
        np.testing.assert_array_equal(full["rgba"], other["rgba"])


if __name__ == "__main__":
    unittest.main()

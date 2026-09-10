"""Generated browser draw commands and buffer lifetimes, without a GPU."""

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np


HARNESS = Path(__file__).with_name("generated_webgpu_commands.cjs")


@unittest.skipIf(shutil.which("node") is None, "node not available")
class GeneratedWebGPUCommands(unittest.TestCase):
    def run_case(self, name, *args):
        result = subprocess.run(
            ["node", str(HARNESS), name, *map(str, args)],
            capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_both_runtime_drivers_drain_pending_decode_destroy_and_reinitialize(self):
        self.run_case("lifecycle")

    def test_sample_coverage_depth_replay_and_stencil_reference_rollover(self):
        self.run_case("coverage")

    def test_one_pass_preserves_order_depth_alpha_and_exact_sample_count(self):
        self.run_case("ordering")

    def test_spatial_resolve_uses_internal_pixels_and_preserves_final_size_and_uniforms(self):
        self.run_case("supersample")

    def test_paint_storage_updates_independently_of_retained_geometry(self):
        self.run_case("paint")

    def test_geometry_and_distinct_uniform_bindings_reuse_across_frames(self):
        self.run_case("reuse")

    def test_large_frames_retire_absent_geometry_only_after_submission(self):
        self.run_case("lifetime")

    def test_texture_bindings_reuse_and_missing_texture_requests_resend(self):
        self.run_case("textures")

    def test_binary_paint_storage_reuses_across_geometry_layouts_and_sample_counts(self):
        self.run_case("paintDefinitions")

    def test_binary_paint_validation_missing_material_and_failed_frame_recovery(self):
        self.run_case("paintDefinitionFailures")

    def test_original_2d_retires_absent_textures_after_submit_and_reinstalls_returning_images(self):
        self.run_case("windingTextures")

    def test_original_2d_preserves_shared_light_dark_texture_storage(self):
        self.run_case("windingSharedTextures")

    def test_original_2d_failed_async_frame_preserves_previous_textures_and_rolls_back_uploads(self):
        self.run_case("windingTextureFailures")

    def test_legacy_wire_is_rejected_and_render_queue_recovers(self):
        self.run_case("modes")

    def test_overlapping_texture_decode_and_resize_preserve_frame_order(self):
        self.run_case("overlap")

    def test_python_encoder_wire_is_consumed_without_repacking(self):
        from maniml.web.generated_geometry import serialize_generated_frame

        surface = np.zeros(3, dtype=[("point", "<f4", (3,)),
                                    ("normal", "<f4", (3,)), ("color", "<f4", (4,))])
        dots = np.zeros(2, dtype=[("point", "<f4", (3,)),
                                 ("radius", "<f4"), ("color", "<f4", (4,))])
        frame = SimpleNamespace(resolution=(160, 90), samples=1,
            background=(0, 0, 0, 0), limitations=[], draws=[
                SimpleNamespace(pipeline="surface", vertices=surface,
                    indices=np.array([2, 0, 1], dtype="<u4"), uniforms={}, count=3, instances=1),
                SimpleNamespace(pipeline="dot", vertices=dots,
                    indices=None, uniforms={}, count=4, instances=2),
            ])
        camera = {"view": np.eye(4).reshape(-1), "frame_rescale_factors": (1, 1, 1),
                  "camera_position": (0, 0, 10), "light_position": (0, 0, 10)}
        with tempfile.TemporaryDirectory() as directory:
            wire = Path(directory) / "generated.bin"
            wire.write_bytes(serialize_generated_frame(frame, camera))
            self.run_case("wire", wire)


if __name__ == "__main__":
    unittest.main()

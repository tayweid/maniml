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

    def test_gpu_border_compute_precedes_draw_and_reuses_distinct_occurrence_outputs(self):
        self.run_case("borderCompute")

    def test_format_6_border_runs_expand_indices_locally_and_rekey_by_occurrence(self):
        self.run_case("borderRuns")

    def test_gpu_border_failure_rolls_back_buffers_and_preserves_generation_state(self):
        self.run_case("borderComputeFailures")

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


def _lyon():
    import importlib.util
    import os
    return bool(os.environ.get("MANIML_LYON_LIBRARY")) or importlib.util.find_spec("maniml.web.maniml_lyon_fill")


@unittest.skipIf(shutil.which("node") is None, "node not available")
@unittest.skipUnless(_lyon(), "the Lyon helper is the frame preparer's tessellator")
class GeneratedWebGPUPhaseB(unittest.TestCase):
    """The browser driver on real Phase B frames: patch fills and surface nets."""

    def run_case(self, name, *args):
        result = subprocess.run(["node", str(HARNESS), name, *map(str, args)],
                                capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    @staticmethod
    def _frames(scene, cache, wire, **kwargs):
        from maniml.web.generated_geometry import serialize_generated_frame
        from maniml.web.triangle_geometry import LyonFillTessellator
        from maniml.web.triangle_scene import prepare_triangle_frame
        frame = prepare_triangle_frame(scene, LyonFillTessellator(), mesh_cache=cache,
                                       fill_borders=True, gpu_borders=True, **kwargs)
        frame.samples, frame.supersample = 4, 2
        return serialize_generated_frame(frame, scene.camera.uniforms, wire)

    def test_patch_fill_wire_draws_instanced_groups_marks_and_covers(self):
        from maniml.constants import BLUE, RED
        from maniml.mobject.geometry import Square
        from maniml.web.geometry import GeometryCache
        from maniml.web.triangle_scene import TriangleMeshCache
        from tests.renderer_fixtures import build_scene
        squares = [Square(side_length=1, fill_color=RED, fill_opacity=1, stroke_width=0,
                          fill_border_width=4).shift([x, 0, 0]) for x in (-2, 0, 2)]
        blue = Square(side_length=1, fill_color=BLUE, fill_opacity=1, stroke_width=0,
                      fill_border_width=4).shift([0, 2, 0])
        scene = build_scene(*squares, blue, resolution=(480, 270))
        with tempfile.TemporaryDirectory() as directory:
            wire = Path(directory) / "patches.bin"
            wire.write_bytes(self._frames(scene, TriangleMeshCache(), GeometryCache(), patch_fills=True))
            self.run_case("patchWire", wire)

    def test_surface_net_wire_evaluates_and_regrows_across_a_zoom(self):
        from maniml.web.geometry import GeometryCache
        from maniml.web.triangle_scene import TriangleMeshCache
        from tests.test_wgpu_port import build_surfaces_scene
        scene, cache, wire = build_surfaces_scene(), TriangleMeshCache(), GeometryCache()
        with tempfile.TemporaryDirectory() as directory:
            first = Path(directory) / "nets_1.bin"
            first.write_bytes(self._frames(scene, cache, wire, net_surfaces=True))
            scene.camera.frame.scale(1 / 16)
            scene.camera.refresh_uniforms()
            second = Path(directory) / "nets_2.bin"
            second.write_bytes(self._frames(scene, cache, wire, net_surfaces=True))
            self.run_case("netWire", first, second)

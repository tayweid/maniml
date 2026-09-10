"""Exercise the browser renderer's commands without a browser or GPU.

The Node harness runs the preserved winding reference webgpu.js against a recording device.
Pixel fidelity is covered separately by test_wgpu_port; these checks cover
scratch allocation, command ordering, and the browser's uniform contract.
"""

import shutil
import subprocess
import unittest
from pathlib import Path


HARNESS = Path(__file__).with_name("webgpu_commands.cjs")


@unittest.skipIf(shutil.which("node") is None, "node not available")
class WebGPUCommandTests(unittest.TestCase):
    def run_case(self, name):
        result = subprocess.run(
            ["node", str(HARNESS), name],
            capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(
            result.returncode, 0,
            f"WebGPU command case {name} failed:\n"
            f"{result.stdout}\n{result.stderr}",
        )

    def test_bounded_fill_preserves_projection_and_uniform_layout(self):
        self.run_case("uniforms")

    def test_invalid_bounds_fall_back_and_empty_fill_keeps_stroke(self):
        self.run_case("bounds")

    def test_scratch_pool_reuses_buckets_and_retires_after_submission(self):
        self.run_case("pool")

    def test_reused_scratch_is_cleared_when_bounds_shrink(self):
        self.run_case("shrink")

    def test_resize_replaces_scratch_and_caps_buckets_to_output(self):
        self.run_case("resize")


if __name__ == "__main__":
    unittest.main()

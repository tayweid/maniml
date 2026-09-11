"""Every test module is either in a CI job's explicit module list or named
here with the reason it cannot run there. The lists in
.github/workflows/ci.yml are hand-maintained; this is the trap for a new
module that nobody added."""

import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]

# Modules CI cannot run, each with why. Remove an entry when the reason goes.
NOT_IN_CI = {
    "test_triangle_renderer": "real-GPU A0 harness, gated on MANIML_TEST_GPU=1",
    "test_renderer_quality": "real wgpu device pixel comparisons against native references",
    "test_wgpu_port": "real wgpu device pixel diff of the browser port",
    "test_ci_module_lists": "this guard runs under discovery, and lists itself here",
}


class CIModuleLists(unittest.TestCase):
    def test_every_test_module_is_listed_or_excused(self):
        workflow = (ROOT / ".github/workflows/ci.yml").read_text()
        listed = set(re.findall(r"tests\.(test_[a-z0-9_]+)", workflow))
        modules = {path.stem for path in (ROOT / "tests").glob("test_*.py")}
        missing = sorted(modules - listed - set(NOT_IN_CI))
        self.assertEqual(missing, [], f"add these to .github/workflows/ci.yml or excuse them here: {missing}")
        stale = sorted((listed - modules) | (set(NOT_IN_CI) - modules))
        self.assertEqual(stale, [], f"listed modules that no longer exist: {stale}")
        self.assertEqual(sorted(listed & set(NOT_IN_CI)), [], "a module cannot be both listed and excused")


if __name__ == "__main__":
    unittest.main()

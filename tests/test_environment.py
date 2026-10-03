"""The scene file's environment (maniml/environment.py): the header, the
missing-import reading, and, with uv on the machine, the environment uv
builds from a header and the layering of it onto this interpreter."""

import os
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path

from maniml import environment as env

REPO_ROOT = Path(__file__).resolve().parent.parent

HEADER = """# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "seaborn==0.13.2",
#     "numpy>=2",
# ]
#
# [tool.uv]
# exclude-newer = "2026-10-01T00:00:00Z"
# ///

from manim import *
"""


class HeaderTests(unittest.TestCase):
    def test_the_floor_is_the_packages_own(self):
        with open(REPO_ROOT / "pyproject.toml", "rb") as f:
            floor = tomllib.load(f)["project"]["requires-python"]
        self.assertEqual(env.REQUIRES_PYTHON, floor)

    def test_a_file_without_a_header_gets_one_above_its_code(self):
        text, created = env.with_header("from manim import *\n")
        self.assertTrue(created)
        self.assertTrue(text.startswith("# /// script\n"))
        self.assertTrue(text.endswith("# ///\n\nfrom manim import *\n"), text)
        header = env.parse_header(text)
        self.assertEqual(header["requires_python"], env.REQUIRES_PYTHON)
        self.assertEqual(header["dependencies"], [])
        self.assertRegex(header["exclude_newer"], r"^\d{4}-\d{2}-\d{2}T00:00:00Z$")
        again, created = env.with_header(text)
        self.assertFalse(created)
        self.assertEqual(again, text)

    def test_a_header_reads_back_its_pins_and_its_stamp(self):
        self.assertEqual(env.find_header(HEADER), (0, 9))
        header = env.parse_header(HEADER)
        self.assertEqual(header["requires_python"], ">=3.11")
        self.assertEqual(header["dependencies"], ["seaborn==0.13.2", "numpy>=2"])
        self.assertEqual(header["exclude_newer"], "2026-10-01T00:00:00Z")
        self.assertEqual(env.pinned_version(HEADER, "seaborn"), "0.13.2")
        self.assertEqual(env.pinned_version(HEADER, "Seaborn"), "0.13.2")
        self.assertIsNone(env.pinned_version(HEADER, "numpy"))  # a range, not a pin
        self.assertIsNone(env.pinned_version(HEADER, "pandas"))

    def test_a_block_broken_by_code_is_no_header(self):
        self.assertIsNone(env.find_header("# /// script\nimport x\n# ///\n"))
        self.assertIsNone(env.find_header("from manim import *\n"))
        self.assertIsNone(env.parse_header(""))

    def test_a_header_that_is_not_toml_is_reported_not_raised(self):
        header = env.parse_header('# /// script\n# dependencies = [\n# ///\n')
        self.assertIn("error", header)
        self.assertEqual(header["dependencies"], [])


class MissingImportTests(unittest.TestCase):
    TRACEBACK = (
        "Traceback (most recent call last):\n"
        '  File "scene.py", line 1, in <module>\n'
        "    import seaborn.palettes\n"
        "\x1b[31mModuleNotFoundError\x1b[0m: No module named 'seaborn.palettes'\n"
    )

    def test_the_top_level_module_is_read_through_colour_codes(self):
        self.assertEqual(env.missing_module(self.TRACEBACK), "seaborn")
        self.assertIsNone(env.missing_module("SyntaxError: invalid syntax"))

    def test_a_distribution_is_the_import_name_unless_listed(self):
        self.assertEqual(env.distribution_for("seaborn"), "seaborn")
        self.assertEqual(env.distribution_for("sklearn"), "scikit-learn")
        self.assertEqual(env.distribution_for("PIL"), "pillow")

    def test_a_package_imported_by_its_own_name_gets_the_import_name(self):
        self.assertIn("PIL", env.import_name_hint("pillow"))
        self.assertIn("sklearn", env.import_name_hint("scikit_learn"))
        self.assertIsNone(env.import_name_hint("seaborn"))

    def test_only_a_package_name_may_reach_uv(self):
        self.assertTrue(env.is_package_name("seaborn"))
        self.assertTrue(env.is_package_name("scikit-learn"))
        self.assertTrue(env.is_package_name("python_dateutil"))
        for bad in ("--index-url", "-e", "", "seaborn>=1", "a b", None, 3):
            self.assertFalse(env.is_package_name(bad), bad)

    def test_the_terminal_hint_names_the_add_command_or_the_import(self):
        if env.find_uv() is None:
            self.skipTest("uv is not installed")
        hint = env.terminal_hint("/tmp/scene.py", "sklearn")
        self.assertIn("uv add --script /tmp/scene.py --bounds exact scikit-learn", hint)
        self.assertIn("imported as PIL", env.terminal_hint("/tmp/scene.py", "pillow"))


@unittest.skipIf(env.find_uv() is None, "uv is not installed")
class EnvironmentTests(unittest.TestCase):
    """Real uv: a header with no packages builds in a moment and needs no
    network, which is enough to see the environment land on this
    interpreter and on sys.path."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.path = os.path.join(self.tmpdir.name, "env_scene.py")
        self._path_before = list(sys.path)
        self.addCleanup(self._restore_path)

    def _restore_path(self):
        sys.path[:] = self._path_before
        env._activated.pop(os.path.abspath(self.path), None)

    def _write(self, text):
        Path(self.path).write_text(text, encoding="utf-8")

    def test_a_file_without_a_header_runs_on_the_engine_alone(self):
        self._write("from manim import *\n")
        built = env.ensure_environment(self.path)
        self.assertFalse(built.managed)
        self.assertEqual(built.reason, "no environment header")
        self.assertEqual(built.python, sys.executable)
        activated = env.activate(self.path, on_progress=lambda step: None)
        self.assertFalse(activated.managed)
        self.assertEqual(sys.path, self._path_before)

    def test_a_header_builds_on_this_interpreter_and_lands_on_sys_path(self):
        text, _ = env.with_header("from manim import *\n")
        self._write(text)
        steps = []
        built = env.ensure_environment(self.path, on_progress=steps.append)
        self.assertTrue(built.managed, built.reason)
        self.assertTrue(os.path.isdir(built.site_packages), built.site_packages)
        if os.name == "posix":
            self.assertIn(
                f"python{sys.version_info.major}.{sys.version_info.minor}",
                built.site_packages)
        # Layered first, once, and gone again with the header.
        activated = env.activate(self.path, on_progress=steps.append)
        self.assertEqual(sys.path[0], activated.site_packages)
        env.activate(self.path, on_progress=steps.append)
        self.assertEqual(sys.path.count(activated.site_packages), 1)
        self._write("from manim import *\n")
        plain = env.activate(self.path, on_progress=steps.append)
        self.assertFalse(plain.managed)
        self.assertNotIn(activated.site_packages, sys.path)

    def test_an_offline_add_of_what_uv_lacks_offers_a_download(self):
        self._write("from manim import *\n")
        ok, reason, download = env.add_dependency(
            self.path, "maniml-no-such-package-xyz", offline=True)
        self.assertFalse(ok)
        self.assertIsNone(reason)
        self.assertTrue(download)
        # The file is as it was: no header written for a package not added.
        self.assertEqual(Path(self.path).read_text(), "from manim import *\n")

    def test_an_add_refuses_anything_but_a_package_name(self):
        self._write("from manim import *\n")
        ok, reason, download = env.add_dependency(self.path, "--index-url")
        self.assertFalse(ok)
        self.assertIn("not a package name", reason)
        self.assertFalse(download)


if __name__ == "__main__":
    unittest.main()

"""Display-independent tests for the non-executing ManimCE API extractor."""

import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from tests.ce_conformance.extract_ce_names import (
    check_names,
    extract_all_names,
    load_names,
    write_names,
)


class CEExtractorTests(unittest.TestCase):
    def test_extracts_literal_all_without_importing_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            package = root / "manim"
            package.mkdir()
            (package / "module.py").write_text(
                "__all__ = ['Circle', 'Square']\nraise RuntimeError('do not run')\n",
                encoding="utf-8",
            )
            self.assertEqual(extract_all_names(str(root)), {"Circle", "Square"})

    def test_write_load_and_check(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "names.txt"
            names = {"Circle", "Square"}
            write_names(names, directory, path)
            self.assertEqual(load_names(path), names)
            self.assertTrue(check_names(names, path))
            with redirect_stdout(StringIO()):
                self.assertFalse(check_names({"Circle", "Triangle"}, path))


if __name__ == "__main__":
    unittest.main()

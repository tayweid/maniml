"""Mapping an OS-launched file handle back to a real path on disk.

The File Handling API gives the page a handle with no path, so the engine
identifies the file by name and content digest. Getting this wrong would
either fail to open a real scene or open the wrong file, so the tests below
cover both directions.
"""

from __future__ import annotations

import hashlib
import os
import tempfile
import unittest
from pathlib import Path

from maniml.web.app import AppServer


def digest(path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


SCENE = (
    "from manim import *\n"
    "class Only(Scene):\n"
    "    def construct(self): pass\n"
)
TWO_SCENES = (
    "from manim import *\n"
    "class Alpha(Scene):\n"
    "    def construct(self): pass\n"
    "class Beta(Scene):\n"
    "    def construct(self): pass\n"
)


class LaunchResolveTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.root = Path(self.tmpdir.name).resolve()
        recents = self.root / "recents.json"
        previous = os.environ.get("MANIML_RECENTS_PATH")
        os.environ["MANIML_RECENTS_PATH"] = str(recents)
        self.addCleanup(
            lambda: os.environ.__setitem__("MANIML_RECENTS_PATH", previous)
            if previous is not None
            else os.environ.pop("MANIML_RECENTS_PATH", None)
        )
        (self.root / "blocks").mkdir()
        self.scene = self.root / "blocks" / "03_Code.py"
        self.scene.write_text(SCENE)
        self.server = AppServer(str(self.root), port=0, control_port=0)
        self.addCleanup(self.server.shutdown)

    def _resolve(self, path, **overrides):
        request = {
            "name": os.path.basename(path),
            "size": os.path.getsize(path),
            "sha256": digest(path),
        }
        request.update(overrides)
        return self.server.resolve_payload(request)

    def test_a_launched_file_resolves_to_its_real_path(self):
        result = self._resolve(self.scene)
        self.assertNotIn("error", result, result.get("error"))
        self.assertEqual(result["file"]["path"], str(self.scene))
        self.assertEqual(result["file"]["rel"], os.path.join("blocks", "03_Code.py"))
        self.assertEqual(result["file"]["scenes"], ["Only"])

    def test_resolving_grants_that_file_so_it_can_be_opened(self):
        self.assertIn("error", self.server.open_payload(
            {"path": str(self.scene), "scene": "Nope"}))
        self._resolve(self.scene)
        # Granted: the failure is now about the scene name, not authorization.
        result = self.server.open_payload(
            {"path": str(self.scene), "scene": "Nope"})
        self.assertEqual(result["error"], "scene was not discovered in this file")

    def test_a_same_named_file_with_other_contents_is_not_matched(self):
        """Name alone is ambiguous — 03_Code.py exists in every block."""
        other = self.root / "blocks" / "elsewhere"
        other.mkdir()
        decoy = other / "03_Code.py"
        decoy.write_text(TWO_SCENES)

        result = self._resolve(decoy)
        self.assertEqual(result["file"]["path"], str(decoy))
        self.assertEqual(result["file"]["scenes"], ["Alpha", "Beta"])

        result = self._resolve(self.scene)
        self.assertEqual(result["file"]["path"], str(self.scene))

    def test_a_file_the_engine_cannot_see_reports_a_hint(self):
        outside = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(outside))
        stray = outside / "stray.py"
        stray.write_text(SCENE)
        result = self._resolve(stray)
        self.assertIn("error", result)
        self.assertIn("stray.py", result["error"])
        self.assertIn("Open", result["hint"])

    def test_contents_must_match_the_digest(self):
        result = self._resolve(self.scene, sha256="0" * 64)
        self.assertIn("error", result)

    def test_malformed_launch_requests_are_rejected(self):
        for bad in (
            {},
            {"name": "x.py"},
            {"name": "x.py", "sha256": "nothex"},
            {"name": "x.txt", "sha256": "a" * 64},
            # A path, not a bare filename: must never escape the search.
            {"name": "../../etc/passwd", "sha256": "a" * 64},
            {"name": "/etc/hosts", "sha256": "a" * 64},
        ):
            with self.subTest(bad=bad):
                self.assertIn("error", self.server.resolve_payload(bad))

    def test_a_size_mismatch_short_circuits_a_name_match(self):
        result = self._resolve(self.scene, size=os.path.getsize(self.scene) + 1)
        self.assertIn("error", result)


if __name__ == "__main__":
    unittest.main()

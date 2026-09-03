"""Display-independent tests for failure-safe web export publication."""

import gzip
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import maniml.web.export as web_export


class FakeCamera:
    fps = 30


class FakeScene:
    camera = FakeCamera()
    animation_checkpoints = [{}, {"line_number": 12}]


class FakeRecorder:
    frames = [(b"first", 0), (b"second", 0)]
    _counter = 0


class ExportPublicationTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)
        self.static = self.root / "static"
        self.static.mkdir()
        for name in web_export.PLAYER_ASSETS:
            (self.static / name).write_text(f"new {name}", encoding="utf-8")
        for dirname in web_export.PLAYER_ASSET_DIRS:
            directory = self.static / dirname
            directory.mkdir()
            (directory / "shader.txt").write_text("shader", encoding="utf-8")

        self.destination = self.root / "published"
        self.scene = FakeScene()
        self.recorder = FakeRecorder()
        static_patcher = patch.object(web_export, "STATIC_DIR", os.fspath(self.static))
        record_patcher = patch.object(
            web_export, "record_scene", return_value=self.recorder
        )
        static_patcher.start()
        record_patcher.start()
        self.addCleanup(static_patcher.stop)
        self.addCleanup(record_patcher.stop)

    def create_previous_export(self):
        self.destination.mkdir()
        (self.destination / "index.html").write_text("old player", encoding="utf-8")
        (self.destination / "scene.json").write_text("old metadata", encoding="utf-8")
        (self.destination / "deployment.txt").write_text("keep me", encoding="utf-8")

    def assert_no_transactions(self):
        self.assertEqual(list(self.root.glob(".published-export-*")), [])

    def test_complete_export_replaces_known_assets_and_preserves_extras(self):
        self.create_previous_export()
        victim = self.root / "outside.txt"
        victim.write_text("do not overwrite", encoding="utf-8")
        (self.destination / "index.html").unlink()
        try:
            (self.destination / "index.html").symlink_to(victim)
        except OSError:
            (self.destination / "index.html").write_text("old player", encoding="utf-8")

        result = web_export.export_scene(self.scene, os.fspath(self.destination))

        self.assertEqual(result, os.fspath(self.destination))
        self.assertEqual(
            (self.destination / "index.html").read_text(encoding="utf-8"),
            "new player.html",
        )
        self.assertEqual(
            (self.destination / "deployment.txt").read_text(encoding="utf-8"),
            "keep me",
        )
        self.assertEqual(victim.read_text(encoding="utf-8"), "do not overwrite")
        with gzip.open(self.destination / "scene.bin.gz", "rb") as file:
            self.assertEqual(file.read(), b"firstsecond")
        metadata = json.loads(
            (self.destination / "scene.json").read_text(encoding="utf-8")
        )
        self.assertEqual(
            metadata["format_version"], web_export.GEOMETRY_FORMAT_VERSION
        )
        self.assertEqual(metadata["scene"], "FakeScene")
        self.assertEqual(metadata["segments"], 1)
        self.assert_no_transactions()

    def test_asset_copy_failure_leaves_previous_export_untouched(self):
        self.create_previous_export()

        with patch.object(
            web_export.shutil, "copy", side_effect=OSError("copy failed")
        ):
            with self.assertRaisesRegex(OSError, "copy failed"):
                web_export.export_scene(self.scene, os.fspath(self.destination))

        self.assertEqual(
            (self.destination / "index.html").read_text(encoding="utf-8"),
            "old player",
        )
        self.assertEqual(
            (self.destination / "scene.json").read_text(encoding="utf-8"),
            "old metadata",
        )
        self.assert_no_transactions()

    def test_recording_failure_leaves_previous_export_untouched(self):
        self.create_previous_export()

        with patch.object(
            web_export, "record_scene", side_effect=ValueError("scene failed")
        ):
            with self.assertRaisesRegex(ValueError, "scene failed"):
                web_export.export_scene(self.scene, os.fspath(self.destination))

        self.assertEqual(
            (self.destination / "index.html").read_text(encoding="utf-8"),
            "old player",
        )
        self.assertEqual(
            (self.destination / "scene.json").read_text(encoding="utf-8"),
            "old metadata",
        )
        self.assert_no_transactions()

    def test_publish_failure_restores_previous_export(self):
        self.create_previous_export()
        real_replace = os.replace

        def fail_new_publish(source, target):
            if Path(source).name == "new":
                raise OSError("publish failed")
            return real_replace(source, target)

        with patch.object(web_export.os, "replace", side_effect=fail_new_publish):
            with self.assertRaisesRegex(OSError, "publish failed"):
                web_export.export_scene(self.scene, os.fspath(self.destination))

        self.assertEqual(
            (self.destination / "index.html").read_text(encoding="utf-8"),
            "old player",
        )
        self.assertEqual(
            (self.destination / "deployment.txt").read_text(encoding="utf-8"),
            "keep me",
        )
        self.assert_no_transactions()

    def test_publish_failure_without_previous_export_leaves_no_output(self):
        real_replace = os.replace

        def fail_new_publish(source, target):
            if Path(source).name == "new":
                raise OSError("publish failed")
            return real_replace(source, target)

        with patch.object(web_export.os, "replace", side_effect=fail_new_publish):
            with self.assertRaisesRegex(OSError, "publish failed"):
                web_export.export_scene(self.scene, os.fspath(self.destination))

        self.assertFalse(self.destination.exists())
        self.assert_no_transactions()

    def test_symlink_destination_is_rejected_before_recording(self):
        target = self.root / "target"
        target.mkdir()
        try:
            self.destination.symlink_to(target, target_is_directory=True)
        except OSError:
            self.skipTest("directory symlinks are unavailable")

        with patch.object(web_export, "record_scene") as record_scene:
            with self.assertRaisesRegex(ValueError, "cannot be a symlink"):
                web_export.export_scene(self.scene, os.fspath(self.destination))

        record_scene.assert_not_called()
        self.assertEqual(list(target.iterdir()), [])


if __name__ == "__main__":
    unittest.main()

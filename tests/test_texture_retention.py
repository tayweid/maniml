"""Texture reads are bounded; prepared frames pin their own immutable bytes."""

from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from PIL import Image

from maniml.mobject.types.image_mobject import ImageMobject
from maniml.web import geometry


class TextureRetention(unittest.TestCase):
    def test_image_mobject_closes_owned_file_and_keeps_sampleable_pixels(self):
        with TemporaryDirectory() as tmp:
            filename = Path(tmp) / "texture.png"
            rgba = (31, 95, 181, 173)
            Image.new("RGBA", (3, 2), rgba).save(filename)
            opened_files = []
            original_open = Image.open

            def tracked_open(*args, **kwargs):
                image = original_open(*args, **kwargs)
                opened_files.append(image.fp)
                return image

            with patch("maniml.mobject.types.image_mobject.Image.open", side_effect=tracked_open):
                mobject = ImageMobject(str(filename), height=2)
            self.assertEqual(len(opened_files), 1)
            self.assertTrue(opened_files[0].closed)
            self.assertEqual(mobject.image.mode, "RGBA")
            self.assertEqual(mobject.image.size, (3, 2))
            self.assertEqual(mobject.image.getpixel((1, 1)), rgba)
            self.assertAlmostEqual(mobject.get_width(), 3)
            self.assertAlmostEqual(mobject.get_height(), 2)
            filename.unlink()
            self.assertEqual(tuple(mobject.point_to_rgb(mobject.get_center())),
                             tuple(value / 255 for value in rgba[:3]))

    def test_file_edits_and_evictions_do_not_change_prepared_payloads(self):
        with TemporaryDirectory() as tmp, patch.object(geometry, "MAX_TEXTURE_CACHE_FILES", 2), \
                patch.object(geometry, "MAX_TEXTURE_CACHE_BYTES", 20):
            geometry._TEXTURE_FILES.clear()
            geometry._TEXTURE_BY_HASH.clear()
            first = Path(tmp) / "first"
            first.write_bytes(b"original")
            payloads = {}
            old = geometry._texture_refs(SimpleNamespace(texture_paths={"Texture": first}), payloads)["Texture"]
            first.write_bytes(b"changed-content")
            new, raw = geometry._texture_file(first)
            self.assertNotEqual(old, new)
            self.assertEqual(raw, b"changed-content")
            for index in range(4):
                path = Path(tmp) / str(index)
                path.write_bytes(bytes([index]) * 12)
                geometry._texture_file(path)
            self.assertLessEqual(len(geometry._TEXTURE_FILES), 2)
            self.assertLessEqual(sum(len(item[2]) for item in geometry._TEXTURE_FILES.values()), 20)
            self.assertNotIn(old, geometry._TEXTURE_BY_HASH)
            self.assertEqual(payloads[old], b"original")

    def test_oversized_file_is_returned_without_becoming_history(self):
        with TemporaryDirectory() as tmp, patch.object(geometry, "MAX_TEXTURE_CACHE_BYTES", 3):
            path = Path(tmp) / "oversized"
            path.write_bytes(b"12345")
            key, raw = geometry._texture_file(path)
            self.assertEqual(raw, b"12345")
            self.assertNotIn(str(path), geometry._TEXTURE_FILES)
            self.assertNotIn(key, geometry._TEXTURE_BY_HASH)

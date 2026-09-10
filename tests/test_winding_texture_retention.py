"""The comparison renderer shares fresh, bounded texture bytes with Phase A."""

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from PIL import Image

from maniml import ImageMobject, Scene
from maniml.web import geometry


class WindingTextureRetention(unittest.TestCase):
    def setUp(self):
        geometry._TEXTURE_FILES.clear()
        geometry._TEXTURE_BY_HASH.clear()

    def tearDown(self):
        geometry._TEXTURE_FILES.clear()
        geometry._TEXTURE_BY_HASH.clear()

    def scene(self, *paths):
        scene = Scene(window=None, camera_config={"resolution": (32, 18)})
        scene.add(*(ImageMobject(str(path), height=1).shift([i, 0, 0])
                    for i, path in enumerate(paths)))
        for mob in scene.mobjects:
            if isinstance(mob, ImageMobject):
                mob.image.close()
        return scene

    def encode(self, scene, cache, mode):
        # Image-only frames need no tessellation; fail if that ever changes.
        helper = Mock()
        helper.tessellate.side_effect = AssertionError("image tessellation")
        with patch("maniml.web.triangle_geometry.LyonFillTessellator", return_value=helper):
            return geometry.parse_geometry_message(geometry.serialize_scene(scene, cache, renderer=mode))

    def test_image_edit_is_transmitted_by_both_renderer_modes(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "image.png"
            Image.new("RGBA", (4, 4), "red").save(path)
            scene = self.scene(path)
            caches = {mode: geometry.GeometryCache() for mode in ("triangles", "winding")}
            old = {}
            for mode, cache in caches.items():
                header, _ = self.encode(scene, cache, mode)
                old[mode] = header["batches"][0]["textures"]["Texture"]
            self.assertEqual(old["triangles"], old["winding"])
            Image.new("RGBA", (4, 4), "blue").save(path)
            raw_file = path.read_bytes()
            for mode, cache in caches.items():
                header, raw = self.encode(scene, cache, mode)
                key = header["batches"][0]["textures"]["Texture"]
                self.assertNotEqual(key, old[mode])
                self.assertTrue(header["batches"][0]["cached"], "paint change must reuse image vertices")
                info = header["texture_data"][key]
                self.assertEqual(raw[info["offset"]:info["offset"] + info["nbytes"]], raw_file)
                self.assertNotIn("tex:" + old[mode], cache.sent)

    def test_current_frame_pins_textures_across_reader_eviction(self):
        with TemporaryDirectory() as tmp, patch.object(geometry, "MAX_TEXTURE_CACHE_FILES", 1):
            paths = [Path(tmp) / f"{index}.png" for index in range(2)]
            for path, color in zip(paths, ("red", "blue")):
                Image.new("RGBA", (4, 4), color).save(path)
            scene = self.scene(*paths)
            cache = geometry.GeometryCache()
            header, raw = self.encode(scene, cache, "winding")
            self.assertEqual(len(header["texture_data"]), 2)
            actual = {raw[info["offset"]:info["offset"] + info["nbytes"]]
                      for info in header["texture_data"].values()}
            self.assertEqual(actual, {path.read_bytes() for path in paths})
            self.assertLessEqual(len(geometry._TEXTURE_FILES), 1)
            cache.generated_payloads["previous-triangle-frame"] = object()
            scene.clear()
            header, _ = self.encode(scene, cache, "winding")
            self.assertFalse(header["batches"])
            self.assertFalse(cache.sent)
            self.assertFalse(cache.generated_payloads)

    def test_serialization_failure_does_not_advance_sender_knowledge(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "image.png"
            Image.new("RGBA", (4, 4), "red").save(path)
            scene, cache = self.scene(path), geometry.GeometryCache()
            cache.renderer = "winding"
            cache.sent = {"previous-frame"}
            with patch("maniml.web.winding_geometry.json.dumps", side_effect=ValueError("encode failure")):
                with self.assertRaisesRegex(ValueError, "encode failure"):
                    self.encode(scene, cache, "winding")
            self.assertEqual(cache.sent, {"previous-frame"})

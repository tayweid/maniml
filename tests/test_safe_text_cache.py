"""Display-independent tests for the generated-text disk cache."""

import importlib.util
import pickle
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CACHE_PATH = REPO_ROOT / "maniml" / "utils" / "safe_text_cache.py"
SPEC = importlib.util.spec_from_file_location("maniml_safe_text_cache", CACHE_PATH)
safe_text_cache = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(safe_text_cache)


class SafeTextCacheTests(unittest.TestCase):
    def test_round_trip_and_clear(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = safe_text_cache.SafeTextCache(directory, size_limit=1_000)
            cache.set("key", "<svg>safe</svg>")
            self.assertEqual(cache.get("key"), "<svg>safe</svg>")
            cache.clear()
            self.assertIsNone(cache.get("key"))

    def test_rejects_non_text_values(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = safe_text_cache.SafeTextCache(directory, size_limit=1_000)
            with self.assertRaises(TypeError):
                cache.set("key", {"not": "text"})

    def test_pickle_payload_is_never_deserialized(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = safe_text_cache.SafeTextCache(directory, size_limit=1_000)
            marker = Path(directory) / "executed"

            class Payload:
                def __reduce__(self):
                    return (marker.write_text, ("unsafe",))

            cache._path_for_key("key").write_bytes(pickle.dumps(Payload()))
            cache.get("key")
            self.assertFalse(marker.exists())

    def test_prunes_oldest_entries(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = safe_text_cache.SafeTextCache(directory, size_limit=5)
            cache.set("old", "1234")
            cache.set("new", "5678")
            self.assertIsNone(cache.get("old"))
            self.assertEqual(cache.get("new"), "5678")


if __name__ == "__main__":
    unittest.main()

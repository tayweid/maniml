"""Display-independent tests for the localhost security boundary."""

import importlib.util
import os
from pathlib import Path
import tempfile
import unittest

REPO_ROOT = Path(__file__).resolve().parent.parent
SECURITY_PATH = REPO_ROOT / "maniml" / "web" / "security.py"
SPEC = importlib.util.spec_from_file_location("maniml_web_security", SECURITY_PATH)
security = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(security)


class WebSecurityTests(unittest.TestCase):
    def test_tokens_are_random_and_compared_as_strings(self):
        first = security.new_capability_token()
        second = security.new_capability_token()
        self.assertNotEqual(first, second)
        self.assertGreaterEqual(len(first), 40)
        self.assertTrue(security.token_matches(first, first))
        self.assertFalse(security.token_matches(second, first))
        self.assertFalse(security.token_matches(None, first))

    def test_no_public_origin_is_baked_into_the_engine(self):
        """Everything is same-origin on loopback now; a public origin in here
        would be a standing invitation for any site to drive the engine."""
        source = Path(security.__file__).read_text()
        self.assertNotIn("https://", source)
        for name in ("HOSTED_APP_ORIGIN", "HOSTED_APP_ORIGINS", "HOSTED_APP_URL"):
            self.assertFalse(hasattr(security, name), name)

    def test_auth_message_and_strict_json(self):
        token = security.new_capability_token()
        self.assertTrue(
            security.is_auth_message(
                f'{{"type":"authenticate","token":"{token}"}}', token
            )
        )
        self.assertFalse(
            security.is_auth_message('{"type":"authenticate","token":"wrong"}', token)
        )
        self.assertIsNone(security.parse_json_object('{"x":NaN}'))
        self.assertIsNone(security.parse_json_object("[]"))
        self.assertIsNone(security.parse_json_object("[" * 1100 + "0" + "]" * 1100))
        self.assertIsNone(
            security.parse_json_object(" " * (security.MAX_CONTROL_MESSAGE + 1))
        )

    def test_path_resolution_confines_symlinks_to_root(self):
        with (
            tempfile.TemporaryDirectory() as root_dir,
            tempfile.TemporaryDirectory() as outside_dir,
        ):
            root = Path(root_dir)
            inside = root / "scene.py"
            inside.write_text("class Demo: pass\n")
            resolved = security.resolve_authorized_file(root, str(inside), suffix=".py")
            self.assertEqual(resolved, inside.resolve())

            outside = Path(outside_dir) / "outside.py"
            outside.write_text("class Outside: pass\n")
            with self.assertRaisesRegex(ValueError, "outside the app root"):
                security.resolve_authorized_file(root, str(outside), suffix=".py")

            link = root / "linked.py"
            try:
                os.symlink(outside, link)
            except (OSError, NotImplementedError):
                return
            with self.assertRaisesRegex(ValueError, "outside the app root"):
                security.resolve_authorized_file(root, str(link), suffix=".py")

            self.assertEqual(
                security.resolve_authorized_file(
                    root, str(outside), suffix=".py", allow_outside_root=True
                ),
                outside.resolve(),
            )

    def test_path_resolution_requires_regular_python_file(self):
        with tempfile.TemporaryDirectory() as root_dir:
            root = Path(root_dir)
            text = root / "scene.txt"
            text.write_text("not Python\n")
            with self.assertRaisesRegex(ValueError, r"\.py suffix"):
                security.resolve_authorized_file(root, str(text), suffix=".py")
            with self.assertRaisesRegex(ValueError, "regular file"):
                security.resolve_authorized_file(root, str(root), suffix=".py")


if __name__ == "__main__":
    unittest.main()

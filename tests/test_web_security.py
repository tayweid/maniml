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
    def test_no_capability_machinery_survives(self):
        """The Origin check is the boundary. A token that reaches the page
        through the served HTML defends against nothing the Origin check did
        not already cover, and one that does not reach it that way makes
        launching a delivery problem — so there is no token at all."""
        for name in (
            "new_capability_token", "token_matches", "is_auth_message",
            "load_or_create_capability", "rotate_capability", "capability_path",
        ):
            self.assertFalse(hasattr(security, name), name)

    def test_no_public_origin_is_baked_into_the_engine(self):
        """Everything is same-origin on loopback now; a public origin in here
        would be a standing invitation for any site to drive the engine."""
        source = Path(security.__file__).read_text()
        self.assertNotIn("https://", source)
        for name in ("HOSTED_APP_ORIGIN", "HOSTED_APP_ORIGINS", "HOSTED_APP_URL"):
            self.assertFalse(hasattr(security, name), name)

    def test_strict_json(self):
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

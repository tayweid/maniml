"""app/maniml.json: ManimLive's config for the Claerbout shell.

The shell builds ManimLive.app from it (docs/claerbout_experiment.md). What
it names must exist, and what it installs must be what maniml declares: the
bundle carries the maniml package itself (with the Lyon helper prebuilt),
so `requirements` is the dependency list, and nothing else.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "app" / "maniml.json"
PACKAGE = ROOT / "maniml"


class ShellConfigTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = json.loads(CONFIG.read_text())

    def test_the_engine_installs_the_exported_lockfile(self):
        """The shell installs app/engine-requirements.txt (claerbout 0.1.7,
        `requirementsFile`): an exact export of uv.lock, so every install of
        the app resolves to the same versions. The export must be current:
        regenerate it with the command in its header after `uv lock`."""
        engine = self.config["engine"]
        self.assertNotIn("requirements", engine, "the ranges are replaced by the export")
        exported = CONFIG.parent / engine["requirementsFile"]
        self.assertTrue(exported.is_file(), exported)
        declared = tomllib.loads((ROOT / "pyproject.toml").read_text())
        pinned = {line.split("==")[0].lower() for line in exported.read_text().splitlines()
                  if "==" in line and not line.startswith("#")}
        for requirement in declared["project"]["dependencies"]:
            name = requirement.split(";")[0].split(">")[0].split("=")[0].strip().lower()
            self.assertIn(name, pinned, f"{name} is declared but not in the export")
        uv = shutil.which("uv")
        if uv is None:
            self.skipTest("uv is not on PATH; cannot check the export is current")
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "export.txt"
            subprocess.run([uv, "export", "--no-dev", "--no-emit-project", "--no-hashes",
                            "--frozen", "-q", "-o", str(out)], cwd=ROOT, check=True)
            self.assertEqual(
                [l for l in out.read_text().splitlines() if not l.startswith("#")],
                [l for l in exported.read_text().splitlines() if not l.startswith("#")],
                "app/engine-requirements.txt is stale: re-run the uv export in its header",
            )

    def test_the_bundle_carries_the_package_and_names_what_exists(self):
        config = self.config
        self.assertEqual(config["package"], "maniml")
        dev_python = (CONFIG.parent / config["devPython"]).resolve()
        self.assertEqual(dev_python / "maniml", PACKAGE)
        self.assertTrue((PACKAGE / config["engine"]["marker"]).is_file())
        # The setup page is served from the package's web/ folder, and it
        # is the only page the bundle serves: the engine serves the rest.
        self.assertTrue((PACKAGE / "web" / config["setupPage"]).is_file())
        self.assertTrue((CONFIG.parent / config["icon"]).is_file())
        self.assertEqual(config["pythons"], ["uv"])
        self.assertEqual(config["engine"]["args"][:3], ["-m", "maniml", "app"])

    def test_the_window_has_the_bar_beside_the_lights(self):
        """Zen's shape, as Knuth's and Plass's configs have it: no title bar,
        the traffic lights in the page's bar, their band (2·y + 14, the
        shell's overlay) exactly the bar's 44 px, the --topbar fallback."""
        window = self.config["window"]
        self.assertEqual(window["titleBarStyle"], "hiddenInset")
        self.assertEqual(window["trafficLightPosition"], {"x": 14, "y": 15})
        band = 2 * window["trafficLightPosition"]["y"] + 14
        shell = (PACKAGE / "web" / "static" / "shell.css").read_text()
        self.assertIn(f"--topbar: env(titlebar-area-height, {band}px);", shell)
        # The smoke still reads the name in the pill.
        self.assertEqual(self.config["smoke"]["ready"], "#file-name")

    def test_package_json_pins_the_shell_and_the_version(self):
        """The shell comes from a claerbout release tarball (its Electron is
        pinned; every app moves together), and the app's version is the
        package's, which package.mjs reads from this file."""
        package = json.loads((ROOT / "package.json").read_text())
        pinned = package["devDependencies"]["claerbout"]
        self.assertRegex(pinned, r"^https://github\.com/tayweid/claerbout/archive/refs/tags/v\d+\.\d+\.\d+\.tar\.gz$")
        declared = tomllib.loads((ROOT / "pyproject.toml").read_text())
        self.assertEqual(package["version"], declared["project"]["version"])
        for script in ("app", "app:build", "app:smoke"):
            self.assertIn("app/maniml.json", package["scripts"][script])

    def test_the_probe_matches_the_landing_page(self):
        page = (PACKAGE / "web" / "static" / "app.html").read_text().lower()
        self.assertIn(self.config["engine"]["probe"], page)

    def test_documents_are_python_scene_files_and_never_the_default_handler(self):
        for kind in self.config["documentTypes"]:
            self.assertEqual(kind["extensions"], ["py"])
            self.assertNotEqual(kind["rank"], "Owner")

    def test_the_setup_page_reaches_for_nothing_outside_the_bundle(self):
        page = (PACKAGE / "web" / "static" / "setup.html").read_text()
        self.assertIn("default-src 'none'", page)
        self.assertNotIn("http", page.split("<body>")[1])


class ParentWatchTests(unittest.TestCase):
    """`maniml app --port N --parent PID`: the shell's engine."""

    def test_parent_alive_tells_a_live_process_from_a_gone_one(self):
        from maniml.web.cli import parent_alive

        self.assertTrue(parent_alive(os.getpid()))
        child = subprocess.Popen([sys.executable, "-c", "pass"])
        child.wait()
        self.assertFalse(parent_alive(child.pid))

    def test_the_engine_stops_when_its_parent_is_gone(self):
        parent = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        self.addCleanup(lambda: parent.poll() is None and parent.kill())
        with tempfile.TemporaryDirectory() as tmpdir:
            engine = subprocess.Popen(
                [sys.executable, "-m", "maniml", "app", tmpdir,
                 "--port", "0", "--parent", str(parent.pid)],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                env={**os.environ, "MANIML_RECENTS_PATH": os.path.join(tmpdir, "r.json")},
            )
            self.addCleanup(lambda: engine.poll() is None and engine.kill())
            deadline = time.monotonic() + 30
            url = None
            while time.monotonic() < deadline and url is None:
                line = engine.stdout.readline()
                if not line:
                    break
                if line.startswith("maniml app: http://"):
                    url = line.split()[2]
            self.assertIsNotNone(url, "the engine never announced its address")
            # --port 0 was honoured: an OS-assigned port, not 8685.
            self.assertNotIn(":8685/", url)
            parent.kill()
            parent.wait()
            try:
                engine.wait(timeout=15)
            except subprocess.TimeoutExpired:
                self.fail("the engine outlived its parent")
            self.assertIn("parent process", engine.stdout.read())


class RecentsHomeTests(unittest.TestCase):
    def test_the_recents_list_follows_the_shells_config_dir(self):
        from unittest import mock

        from maniml.web.library import recents_path

        with mock.patch.dict(os.environ, {"MANIML_RECENTS_PATH": "", "MANIML_CONFIG_DIR": ""}):
            os.environ.pop("MANIML_RECENTS_PATH"); os.environ.pop("MANIML_CONFIG_DIR")
            self.assertEqual(recents_path(), os.path.expanduser("~/.maniml_recents.json"))
        with mock.patch.dict(os.environ, {"MANIML_CONFIG_DIR": "/tmp/cfg"}):
            os.environ.pop("MANIML_RECENTS_PATH", None)
            self.assertEqual(recents_path(), os.path.join("/tmp/cfg", "recents.json"))
        with mock.patch.dict(os.environ, {"MANIML_CONFIG_DIR": "/tmp/cfg", "MANIML_RECENTS_PATH": "/x/r.json"}):
            self.assertEqual(recents_path(), "/x/r.json")


if __name__ == "__main__":
    unittest.main()

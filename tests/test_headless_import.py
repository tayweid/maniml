"""Regression tests for using ManimLive without a desktop display."""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
from types import SimpleNamespace
import unittest
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]


class HeadlessImportTests(unittest.TestCase):
    def run_without_display(self, *args: str, **environ: str) -> subprocess.CompletedProcess:
        env = {**os.environ, **environ}
        for name in (
            "DISPLAY",
            "WAYLAND_DISPLAY",
            "MIR_SOCKET",
        ):
            env.pop(name, None)
        return subprocess.run(
            [sys.executable, *args],
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )

    def assert_succeeded(self, result: subprocess.CompletedProcess) -> None:
        self.assertEqual(
            result.returncode,
            0,
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}",
        )

    def test_package_and_star_import_touch_no_window_toolkit(self):
        # The pyglet window is retired (2026-09-02): importing maniml must
        # not pull in pyglet or moderngl-window, which would try to reach
        # a display and are no longer dependencies.
        script = textwrap.dedent("""
            import sys
            import maniml
            from maniml import *

            assert "pyglet" not in sys.modules
            assert "moderngl_window" not in sys.modules
            assert not hasattr(maniml, "Window")
            assert Scene.__module__ == "maniml.scene.scene"
            """)
        self.assert_succeeded(self.run_without_display("-c", script))

    def test_a_host_programs_flags_are_not_manimls(self):
        # The config is parsed when maniml is imported, from maniml's own
        # command line only. Under unittest discover's -t every scene the
        # suite built used to get --transparent's background.
        result = self.run_without_display(
            "-c", "from maniml.config import manim_config; print(manim_config.camera.background_opacity)",
            "discover", "-s", "tests", "-t", ".", "-p", "test_x.py")
        self.assert_succeeded(result)
        self.assertEqual(result.stdout.split(), ["1.0"])

    def test_cli_help_does_not_require_a_display(self):
        result = self.run_without_display("-m", "maniml", "--help")
        self.assert_succeeded(result)
        self.assertIn("usage:", result.stdout.lower())

    def test_both_launch_paths_parse_the_scene_command_line_at_import(self):
        # The app and the viewer launch a scene as ``python -m maniml``,
        # a terminal as the console script; the config each builds at
        # import is the same one. The probe scene reports it as it is
        # loaded and stops there.
        with tempfile.TemporaryDirectory() as tmp:
            probe = Path(tmp) / "probe.py"
            probe.write_text(textwrap.dedent("""\
                from maniml.config import manim_config
                print("PROBE", manim_config.run.file_name, *manim_config.run.scene_names)
                raise SystemExit(0)
                """))
            script = Path(tmp) / "maniml"
            script.write_text("import sys\nfrom maniml.__main__ import main\nsys.exit(main())\n")
            launches = {
                "python -m maniml": ("-m", "maniml"),
                # A script's own directory leads sys.path; the checkout
                # must still be the maniml it imports.
                "the console script": (str(script),),
            }
            for launch, command in launches.items():
                with self.subTest(launch):
                    result = self.run_without_display(*command, str(probe), "Probe",
                                                      PYTHONPATH=str(REPO_ROOT))
                    self.assert_succeeded(result)
                    reports = [line.split()[1:] for line in result.stdout.splitlines()
                               if line.startswith("PROBE ")]
                    self.assertEqual(reports, [[str(probe), "Probe"]])


class CliArguments(unittest.TestCase):
    """maniml.config parses maniml's own command line, never the program
    that imported it."""

    def arguments(self, argv, orig_argv=(), **main):
        from maniml.config import cli_arguments
        with patch.dict(sys.modules, {"__main__": SimpleNamespace(**main)}), \
                patch.object(sys, "argv", argv), patch.object(sys, "orig_argv", list(orig_argv)):
            return cli_arguments()

    def test_python_m_names_the_module_only_in_the_interpreters_command_line(self):
        # The state runpy imports a package in: argv[0] is "-m", and no
        # __main__ has a spec or a file yet.
        self.assertEqual(self.arguments(["-m", "scene.py", "Demo"],
                                        orig_argv=["python", "-X", "dev", "-m", "maniml", "scene.py", "Demo"]),
                         ["scene.py", "Demo"])
        self.assertEqual(self.arguments(["-m", "--fps", "30"],
                                        orig_argv=["python", "-m", "benchmarks.episode_frames", "--fps", "30"]), [])

    def test_another_programs_flags_are_left_alone(self):
        self.assertEqual(self.arguments(["python -m unittest", "discover", "-s", "tests", "-t", "."],
                                        __spec__=SimpleNamespace(name="unittest.__main__")), [])
        self.assertEqual(self.arguments(["-c", "-t"]), [])
        self.assertEqual(self.arguments(["bench.py", "-t"], __file__="/work/bench.py"), [])


if __name__ == "__main__":
    unittest.main()

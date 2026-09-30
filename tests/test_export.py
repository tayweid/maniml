"""End-to-end test of the baked web player (--export).

Exports a scene via the CLI, checks the static folder is complete, and walks
the recorded geometry stream in order — exactly what the player page does —
verifying that every cached batch resolves to content sent earlier.
"""

import json
import os
import shutil
import subprocess
import sys
import unittest

SCENE_SOURCE = """
from manim import *

class ExportDemo(Scene):
    def construct(self):
        circle = Circle(color=BLUE, fill_opacity=0.6).shift(LEFT * 2)
        self.play(Create(circle))
        self.play(circle.animate.shift(RIGHT * 4))
"""

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class WebExportE2E(unittest.TestCase):
    # The original viewer environment preference cannot change baked exports.
    renderer = "winding"

    def test_export_and_replay(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            scene_path = os.path.join(tmp, "export_scene.py")
            with open(scene_path, "w") as f:
                f.write(SCENE_SOURCE)
            result = subprocess.run(
                [sys.executable, "-m", "maniml", scene_path, "ExportDemo",
                 "--export"],
                cwd=tmp, env={**os.environ, "PYTHONPATH": REPO_ROOT,
                              "MANIML_RENDERER": self.renderer},
                capture_output=True, text=True, timeout=120)
            self.assertEqual(result.returncode, 0,
                             result.stdout + result.stderr)

            out = os.path.join(tmp, "media", "ExportDemo_web")
            for name in ["index.html", "player.js", "webgpu.js",
                         "winding_webgpu.js", "geometry_recording.js", "scene.json", "scene.bin.gz"]:
                self.assertTrue(os.path.exists(os.path.join(out, name)),
                                f"missing {name}")
            for dirname in ["wgsl", "winding_wgsl"]:
                self.assertTrue(
                    os.listdir(os.path.join(out, dirname)),
                    f"empty {dirname}")
            self.assertFalse(os.path.exists(os.path.join(out, "gl.js")))
            self.assertFalse(os.path.exists(os.path.join(out, "glsl")))

            with open(os.path.join(out, "scene.json")) as f:
                meta = json.load(f)
            # The recorder never negotiates format 8: full frames, format 7.
            from maniml.web.geometry import FULL_FRAME_FORMAT_VERSION

            self.assertEqual(meta["format_version"], FULL_FRAME_FORMAT_VERSION)
            self.assertEqual(meta["scene"], "ExportDemo")
            self.assertEqual(meta["segments"], 2)
            self.assertGreater(len(meta["frames"]), 10)

            import gzip
            with gzip.open(os.path.join(out, "scene.bin.gz"), "rb") as f:
                blob = f.read()
            self.assertEqual(sum(fr["len"] for fr in meta["frames"]),
                             len(blob))

            # Replay the delta ledger in order. A cached batch is valid only
            # if an earlier frame supplied its bytes; this is the invariant
            # the player relies on before it can seek directly.
            from maniml.web.geometry import parse_geometry_message

            available_batches = set()
            offset = 0
            last_header = None
            for frame in meta["frames"]:
                message = blob[offset:offset + frame["len"]]
                offset += frame["len"]
                header, vertex_bytes = parse_geometry_message(message)
                self.assertEqual(
                    header["format_version"], FULL_FRAME_FORMAT_VERSION)
                self.assertEqual(header["unsupported"], [])
                self.assertEqual(header["renderer"], "triangles")
                self.assertEqual((header["samples"], header["supersample"]), (4, 2))
                for batch in header["batches"]:
                    content_hash = batch["hash"]
                    if batch.get("cached"):
                        self.assertIn(content_hash, available_batches)
                    else:
                        self.assertIn("offset", batch)
                        self.assertLess(batch["offset"], len(vertex_bytes))
                        available_batches.add(content_hash)
                last_header = header
            self.assertTrue(available_batches)
            self.assertTrue(last_header["batches"])


def _require_lyon():
    from maniml.web.triangle_geometry import _packaged_library
    if not os.environ.get("MANIML_LYON_LIBRARY") and _packaged_library() is None:
        raise unittest.SkipTest("build or install the Lyon helper for triangle export")


class TriangleWebExportE2E(WebExportE2E):
    renderer = "triangles"

    @classmethod
    def setUpClass(cls):
        _require_lyon()


# A small sphere alone (a net: the square drawn after it parts it from the
# others), a filled square (a patch run), two spheres side by side (a run of
# nets, B5.7) and a Transform (a blend program over the square's rows, drawn
# as a patch run and a stroke).
PHASE_B_SCENE_SOURCE = """
from manim import *

class PhaseBDemo(Scene):
    def construct(self):
        pebble = Sphere(radius=.3, resolution=(5, 3)).shift(LEFT * 2 + DOWN * 1.8)
        square = Square(side_length=2, fill_color=BLUE, fill_opacity=0.8, stroke_color=RED,
                        stroke_width=6, fill_border_width=3).shift(LEFT * 2)
        sphere = Sphere(radius=1, resolution=(9, 5)).shift(RIGHT * 2)
        moon = Sphere(radius=.4, resolution=(7, 5)).shift(RIGHT * 2 + UP * 1.6)
        self.add(pebble, square, sphere, moon)
        self.wait(0.1)
        circle = Circle(radius=1, fill_color=GREEN, fill_opacity=0.8, stroke_color=BLUE,
                        stroke_width=6, fill_border_width=3).shift(LEFT * 2)
        self.play(Transform(square, circle), run_time=0.2)
"""


@unittest.skipIf(shutil.which("node") is None, "node not available")
class PhaseBWebExportE2E(unittest.TestCase):
    """A Phase B export (docs/phase_b1_plan.md, phase_b2_plan.md,
    phase_b3_plan.md) records the tables its batches draw from — object
    tables, nets, program sources — by hash, once, and the player must
    carry them into every frame it reconstructs. Recording needs no GPU:
    the recorder skips native capture and the serializer only packs arrays."""

    @classmethod
    def setUpClass(cls):
        _require_lyon()

    def test_phase_b_export_records_tables_and_replays_through_the_indexer(self):
        import gzip
        import tempfile
        from unittest.mock import patch
        from maniml.web.geometry import FULL_FRAME_FORMAT_VERSION, parse_geometry_message

        # The records packed (MANIML_PATCH_SOURCE=records, the override
        # since B5.6 made rows the source wherever patches are drawn): the
        # curve records' tables a seek must fill back in. The rows' export
        # is the next test.
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
                os.environ, MANIML_FILL="patches", MANIML_SURFACE="nets",
                MANIML_PROGRAMS="gpu", MANIML_BORDER_GENERATOR="gpu", MANIML_PATCH_SOURCE="records"):
            scene_path = os.path.join(tmp, "phase_b_scene.py")
            with open(scene_path, "w") as f:
                f.write(PHASE_B_SCENE_SOURCE)
            result = subprocess.run(
                [sys.executable, "-m", "maniml", scene_path, "PhaseBDemo", "--export"],
                cwd=tmp, env={**os.environ, "PYTHONPATH": REPO_ROOT},
                capture_output=True, text=True, timeout=120)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            out = os.path.join(tmp, "media", "PhaseBDemo_web")
            with open(os.path.join(out, "scene.json")) as f:
                meta = json.load(f)
            self.assertEqual((meta["format_version"], FULL_FRAME_FORMAT_VERSION), (7, 7))
            with gzip.open(os.path.join(out, "scene.bin.gz"), "rb") as f:
                blob = f.read()

            # Every record a batch references was defined in this frame or
            # an earlier one, and some frames reference records they do not
            # define: exactly what a seek must fill back in.
            defined = {table: set() for table in ("border_data", "object_data", "net_data", "program_data")}
            seen, relied, offset = set(), set(), 0
            for frame in meta["frames"]:
                header, _ = parse_geometry_message(blob[offset:offset + frame["len"]])
                offset += frame["len"]
                self.assertEqual((header["format_version"], header["renderer"]), (7, "triangles"))
                for table, keys in defined.items():
                    keys.update(header[table])

                def reference(table, key):
                    self.assertIn(key, defined[table])
                    if key not in header[table]:
                        relied.add(table)

                for batch in header["batches"]:
                    program = "program" in batch
                    if batch["pipeline"] == "patch":
                        reference("object_data", batch["objects"]["hash"])
                        tag = "program patch" if program else "patch"
                        if not program:
                            reference("border_data", batch["border"]["hash"])
                    elif isinstance(batch.get("net"), list):
                        # A run of nets (B5.7): the sphere and the moon, one
                        # batch. The pebble is a net alone.
                        for member in batch["net"]:
                            reference("net_data", member["hash"])
                        tag = "net run"
                    elif "net" in batch:
                        reference("net_data", batch["net"]["hash"])
                        tag = "program net" if program else "net"
                    else:
                        tag = "program stroke" if program else batch["pipeline"]
                    if program:
                        self.assertEqual(batch["program"]["kind"], "blend")
                        for source in batch["program"]["sources"]:
                            reference("program_data", source)
                    seen.add(tag)
                    if batch.get("cached"):
                        seen.add("cached " + tag)
            self.assertLessEqual({"patch", "cached patch", "net", "cached net", "net run", "cached net run",
                                  "program patch", "cached program patch", "program stroke",
                                  "cached program stroke"}, seen)
            self.assertEqual(relied, set(defined))

            # The player's load and seek path over the folder, then the
            # browser driver on every reconstructed frame with nothing missing.
            for harness, mode in (("player_commands.cjs", "export"),
                                  ("generated_webgpu_commands.cjs", "recordingReplay")):
                replay = subprocess.run(
                    ["node", os.path.join(REPO_ROOT, "tests", harness), mode, out],
                    input="", capture_output=True, text=True, timeout=60)
                self.assertEqual(replay.returncode, 0, f"{mode}: {replay.stdout}{replay.stderr}")
                report = json.loads(replay.stdout)
                self.assertEqual(report["frames"], len(meta["frames"]))
                self.assertGreaterEqual(report["rendered"], 2 * len(meta["frames"]))
                if mode == "export":
                    self.assertEqual(set(report["tags"]), {"objects", "border", "net", "rows"})

    def test_a_row_sourced_export_records_rows_and_replays_through_the_indexer(self):
        """B5.1 (docs/phase_b4_plan.md): with MANIML_PATCH_SOURCE=rows (the
        default wherever patches are drawn since B5.6) the patch fills and
        strokes name their objects' rows in the program sources' table,
        and a seek must carry them into its frame. The switch is stated,
        so the case holds whatever the default is."""
        import gzip
        import tempfile
        from unittest.mock import patch
        from maniml.web.geometry import parse_geometry_message

        with tempfile.TemporaryDirectory() as tmp, patch.dict(
                os.environ, MANIML_FILL="patches", MANIML_SURFACE="nets", MANIML_PROGRAMS="gpu",
                MANIML_BORDER_GENERATOR="gpu", MANIML_PATCH_SOURCE="rows"):
            scene_path = os.path.join(tmp, "phase_b_scene.py")
            with open(scene_path, "w") as f:
                f.write(PHASE_B_SCENE_SOURCE)
            result = subprocess.run(
                [sys.executable, "-m", "maniml", scene_path, "PhaseBDemo", "--export"],
                cwd=tmp, env={**os.environ, "PYTHONPATH": REPO_ROOT},
                capture_output=True, text=True, timeout=120)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            out = os.path.join(tmp, "media", "PhaseBDemo_web")
            with open(os.path.join(out, "scene.json")) as f:
                meta = json.load(f)
            with gzip.open(os.path.join(out, "scene.bin.gz"), "rb") as f:
                blob = f.read()
            defined, seen, relied, offset = set(), set(), False, 0
            for frame in meta["frames"]:
                header, _ = parse_geometry_message(blob[offset:offset + frame["len"]])
                offset += frame["len"]
                defined.update(header["program_data"])
                self.assertEqual(header["border_data"], {}, "no curve records travel")
                for batch in header["batches"]:
                    if "rows" not in batch:
                        continue
                    seen.add(batch["pipeline"] + (" cached" if batch.get("cached") else ""))
                    # Each rows as its geometry and its paint (B5.8), both
                    # carried into every seek's frame.
                    self.assertEqual(len(batch["row_paints"]), len(batch["rows"]))
                    for key in (*batch["rows"], *batch["row_paints"]):
                        self.assertIn(key, defined)
                        relied = relied or key not in header["program_data"]
            self.assertLessEqual({"patch", "patch cached", "stroke", "stroke cached"}, seen)
            self.assertTrue(relied, "a frame names rows an earlier frame defined")
            for harness, mode in (("player_commands.cjs", "export"),
                                  ("generated_webgpu_commands.cjs", "recordingReplay")):
                replay = subprocess.run(
                    ["node", os.path.join(REPO_ROOT, "tests", harness), mode, out],
                    input="", capture_output=True, text=True, timeout=60)
                self.assertEqual(replay.returncode, 0, f"{mode}: {replay.stdout}{replay.stderr}")
                report = json.loads(replay.stdout)
                self.assertEqual(report["frames"], len(meta["frames"]))
                if mode == "export":
                    self.assertEqual(set(report["tags"]), {"objects", "net", "rows", "paint"})


if __name__ == "__main__":
    unittest.main()

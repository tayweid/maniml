"""Generated browser draw commands and buffer lifetimes, without a GPU."""

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np


HARNESS = Path(__file__).with_name("generated_webgpu_commands.cjs")


@unittest.skipIf(shutil.which("node") is None, "node not available")
class GeneratedWebGPUCommands(unittest.TestCase):
    def run_case(self, name, *args):
        result = subprocess.run(
            ["node", str(HARNESS), name, *map(str, args)],
            capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_both_runtime_drivers_drain_pending_decode_destroy_and_reinitialize(self):
        self.run_case("lifecycle")

    def test_sample_coverage_depth_replay_and_stencil_reference_rollover(self):
        self.run_case("coverage")

    def test_one_pass_preserves_order_depth_alpha_and_exact_sample_count(self):
        self.run_case("ordering")

    def test_spatial_resolve_uses_internal_pixels_and_preserves_final_size_and_uniforms(self):
        self.run_case("supersample")

    def test_paint_storage_updates_independently_of_retained_geometry(self):
        self.run_case("paint")

    def test_geometry_and_distinct_uniform_bindings_reuse_across_frames(self):
        self.run_case("reuse")

    def test_large_frames_retire_absent_geometry_only_after_submission(self):
        self.run_case("lifetime")

    def test_texture_bindings_reuse_and_missing_texture_requests_resend(self):
        self.run_case("textures")

    def test_gpu_border_compute_precedes_draw_and_gives_each_draw_its_own_output(self):
        self.run_case("borderCompute")

    def test_format_6_border_runs_expand_indices_locally_and_survive_an_insertion(self):
        self.run_case("borderRuns")

    def test_identical_full_frames_reuse_every_slot_and_create_nothing(self):
        self.run_case("slotsReuseAcrossFullFrames")

    def test_an_inserted_batch_leaves_later_border_and_net_outputs_in_place(self):
        self.run_case("outputsSurviveInsertion")

    def test_program_outputs_survive_scalars_that_coincide_and_diverge(self):
        self.run_case("programOutputsSurviveCoincidence")

    def test_a_failed_frame_leaves_the_uniform_sets_at_the_submitted_camera(self):
        self.run_case("failedFramesKeepTheCamera")

    def test_camera_position_and_net_density_evaluate_what_reads_them(self):
        self.run_case("generationFollowsItsInputs")

    def test_changed_nets_split_into_dispatches_only_past_the_scratch_budget(self):
        self.run_case("netsInSeveralDispatches")

    def test_retained_frames_draw_what_a_fresh_driver_draws_from_each_frame(self):
        self.run_case("retainedFramesDrawWhatFreshDriversDraw")

    def test_a_delta_applies_only_to_its_base_and_a_failed_one_is_rolled_back(self):
        self.run_case("deltasApplyOnlyToTheirBase")

    def test_gpu_border_failure_rolls_back_buffers_and_preserves_generation_state(self):
        self.run_case("borderComputeFailures")

    def test_binary_paint_storage_reuses_across_geometry_layouts_and_sample_counts(self):
        self.run_case("paintDefinitions")

    def test_binary_paint_validation_missing_material_and_failed_frame_recovery(self):
        self.run_case("paintDefinitionFailures")

    def test_original_2d_retires_absent_textures_after_submit_and_reinstalls_returning_images(self):
        self.run_case("windingTextures")

    def test_original_2d_preserves_shared_light_dark_texture_storage(self):
        self.run_case("windingSharedTextures")

    def test_original_2d_failed_async_frame_preserves_previous_textures_and_rolls_back_uploads(self):
        self.run_case("windingTextureFailures")

    def test_legacy_wire_is_rejected_and_render_queue_recovers(self):
        self.run_case("modes")

    def test_overlapping_texture_decode_and_resize_preserve_frame_order(self):
        self.run_case("overlap")

    def test_python_encoder_wire_is_consumed_without_repacking(self):
        from maniml.web.generated_geometry import serialize_generated_frame

        surface = np.zeros(3, dtype=[("point", "<f4", (3,)),
                                    ("normal", "<f4", (3,)), ("color", "<f4", (4,))])
        dots = np.zeros(2, dtype=[("point", "<f4", (3,)),
                                 ("radius", "<f4"), ("color", "<f4", (4,))])
        frame = SimpleNamespace(resolution=(160, 90), samples=1,
            background=(0, 0, 0, 0), limitations=[], draws=[
                SimpleNamespace(pipeline="surface", vertices=surface,
                    indices=np.array([2, 0, 1], dtype="<u4"), uniforms={}, count=3, instances=1),
                SimpleNamespace(pipeline="dot", vertices=dots,
                    indices=None, uniforms={}, count=4, instances=2),
            ])
        camera = {"view": np.eye(4).reshape(-1), "frame_rescale_factors": (1, 1, 1),
                  "camera_position": (0, 0, 10), "light_position": (0, 0, 10)}
        with tempfile.TemporaryDirectory() as directory:
            wire = Path(directory) / "generated.bin"
            wire.write_bytes(serialize_generated_frame(frame, camera))
            self.run_case("wire", wire)


if __name__ == "__main__":
    unittest.main()


def delta_equals_full(test, sent):
    """Play one history's format 7 frames (``sent["full"]``) and its format
    8 stream (``sent["delta"]``, None where nothing was sent) on two drivers
    (deltaEqualsFull), and return what the harness counted."""
    import gzip
    import json
    with tempfile.TemporaryDirectory() as directory:
        for name, messages in sent.items():
            folder = Path(directory) / name
            folder.mkdir()
            with gzip.open(folder / "scene.bin.gz", "wb") as file:
                file.writelines(message for message in messages if message is not None)
            (folder / "scene.json").write_text(json.dumps(
                {"frames": [{"len": len(message or b"")} for message in messages]}))
        result = subprocess.run(["node", str(HARNESS), "deltaEqualsFull", Path(directory) / "full",
                                 Path(directory) / "delta"], capture_output=True, text=True, timeout=60)
    test.assertEqual(result.returncode, 0, result.stdout + result.stderr)
    return json.loads(result.stdout)


def _lyon():
    import importlib.util
    import os
    return bool(os.environ.get("MANIML_LYON_LIBRARY")) or importlib.util.find_spec("maniml.web.maniml_lyon_fill")


@unittest.skipIf(shutil.which("node") is None, "node not available")
@unittest.skipUnless(_lyon(), "the Lyon helper is the frame preparer's tessellator")
class GeneratedWebGPUPhaseB(unittest.TestCase):
    """The browser driver on real Phase B frames: patch fills and surface nets."""

    def run_case(self, name, *args):
        result = subprocess.run(["node", str(HARNESS), name, *map(str, args)],
                                capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    @staticmethod
    def _frames(scene, cache, wire, **kwargs):
        from maniml.web.generated_geometry import serialize_generated_frame
        from maniml.web.triangle_geometry import LyonFillTessellator
        from maniml.web.triangle_scene import prepare_triangle_frame
        frame = prepare_triangle_frame(scene, LyonFillTessellator(), mesh_cache=cache,
                                       fill_borders=True, gpu_borders=True, **kwargs)
        frame.samples, frame.supersample = 4, 2
        return serialize_generated_frame(frame, scene.camera.uniforms, wire)

    def test_patch_fill_wire_draws_instanced_groups_marks_and_covers(self):
        from maniml.constants import BLUE, RED
        from maniml.mobject.geometry import Square
        from maniml.web.geometry import GeometryCache
        from maniml.web.triangle_scene import TriangleMeshCache
        from tests.renderer_fixtures import build_scene
        squares = [Square(side_length=1, fill_color=RED, fill_opacity=1, stroke_width=0,
                          fill_border_width=4).shift([x, 0, 0]) for x in (-2, 0, 2)]
        blue = Square(side_length=1, fill_color=BLUE, fill_opacity=1, stroke_width=0,
                      fill_border_width=4).shift([0, 2, 0])
        scene = build_scene(*squares, blue, resolution=(480, 270))
        with tempfile.TemporaryDirectory() as directory:
            wire = Path(directory) / "patches.bin"
            wire.write_bytes(self._frames(scene, TriangleMeshCache(), GeometryCache(), patch_fills=True))
            self.run_case("patchWire", wire)

    def test_program_wire_blends_finalizes_and_reuses_sources(self):
        import os
        from unittest.mock import patch
        from maniml.animation.transform import Transform
        from maniml.constants import BLUE, GREEN, RED
        from maniml.mobject.geometry import Circle, Square
        from maniml.mobject.three_dimensions import Sphere, Torus
        from maniml.web.geometry import GeometryCache, serialize_scene
        from tests.renderer_fixtures import build_scene
        with patch.dict(os.environ, MANIML_FILL="patches", MANIML_BORDER_GENERATOR="gpu", MANIML_SURFACE="nets",
                        MANIML_PROGRAMS="gpu"):
            circle = Circle(radius=1.2, fill_color=BLUE, fill_opacity=.6, stroke_color=RED, stroke_width=6,
                            fill_border_width=3)
            square = Square(side_length=2.5, fill_color=GREEN, fill_opacity=.9, stroke_color=BLUE, stroke_width=10,
                            fill_border_width=3)
            sphere, torus = Sphere(resolution=(9, 5)), Torus(resolution=(9, 5))
            scene, wire = build_scene(circle, sphere, resolution=(480, 270), samples=4), GeometryCache()
            anims = [Transform(circle, square), Transform(sphere, torus)]
            for anim in anims:
                anim.begin()
            with tempfile.TemporaryDirectory() as directory:
                files = []
                for index, alpha in enumerate((.3, .6, .6)):
                    for anim in anims:
                        anim.interpolate(alpha)
                    files.append(Path(directory) / f"programs_{index}.bin")
                    files[-1].write_bytes(serialize_scene(scene, wire, renderer="triangles"))
                self.run_case("programWire", *files)
            for anim in anims:
                anim.finish()

    def test_program_kinds_wire_runs_every_row_kernel(self):
        import os
        from unittest.mock import patch
        from maniml.animation.creation import ShowCreation
        from maniml.animation.fading import VFadeIn
        from maniml.animation.rotation import Rotate
        from maniml.constants import BLUE, GREEN, RED
        from maniml.mobject.geometry import Circle, Square
        from maniml.web.geometry import GeometryCache, serialize_scene
        from tests.renderer_fixtures import build_scene
        with patch.dict(os.environ, MANIML_FILL="patches", MANIML_BORDER_GENERATOR="gpu", MANIML_PROGRAMS="gpu"):
            shapes = [Circle(radius=1, fill_color=BLUE, fill_opacity=.6, stroke_color=RED, stroke_width=6).shift([-3, 0, 0]),
                      Square(side_length=2, fill_color=GREEN, fill_opacity=.9, stroke_width=4),
                      Circle(radius=1, fill_color=RED, fill_opacity=.5, stroke_width=5).shift([3, 0, 0])]
            scene, wire = build_scene(*shapes, resolution=(480, 270), samples=4), GeometryCache()
            anims = [Rotate(shapes[0], angle=1.0), VFadeIn(shapes[1]), ShowCreation(shapes[2])]
            for anim in anims:
                anim.begin()
            for anim in anims:
                anim.interpolate(.4)
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "kinds.bin"
                path.write_bytes(serialize_scene(scene, wire, renderer="triangles"))
                self.run_case("programKindsWire", path)
            for anim in anims:
                anim.finish()

    def test_row_sources_are_finalized_and_draw_what_records_draw(self):
        from maniml.web.geometry import GeometryCache
        from maniml.web.triangle_scene import TriangleMeshCache
        from tests.test_patch_rows import _shapes
        from tests.renderer_fixtures import build_scene
        shapes = _shapes()
        scene = build_scene(*shapes, resolution=(480, 270))
        with tempfile.TemporaryDirectory() as directory:
            files = [Path(directory) / name for name in ("records.bin", "rows_0.bin", "rows_1.bin", "rows_2.bin")]
            files[0].write_bytes(self._frames(scene, TriangleMeshCache(), GeometryCache(), patch_fills=True))
            cache, wire = TriangleMeshCache(), GeometryCache()
            for path in files[1:3]:
                path.write_bytes(self._frames(scene, cache, wire, patch_fills=True, patch_rows=True))
            shapes[1].shift([0, .2, 0])
            files[3].write_bytes(self._frames(scene, cache, wire, patch_fills=True, patch_rows=True))
            self.run_case("rowsWire", *files)

    def test_a_format_8_stream_draws_what_its_full_frames_draw(self):
        """B4.8 (docs/phase_b4_plan.md): one history serialized twice, as the
        format 7 full frames a receiver that has not negotiated is sent and
        as the format 8 stream one that has is sent, and played on two
        drivers (deltaEqualsFull): stills, a move, a pan and a zoom, a
        child's z_index up and back, a leaf added and one removed, a play
        and its landing, a client's reset, and each renderer switched to and
        back, Phase B's plays drawn from GPU programs, whose scalars travel
        as scalars ops. Phase B's frames with their records packed and, B5.1,
        sent as rows (MANIML_PATCH_SOURCE=rows), whose runs the drivers
        finalize and assemble slot by slot."""
        import os
        from unittest.mock import patch
        for source in ("records", "rows"):
            with self.subTest(patch_source=source), patch.dict(os.environ, MANIML_PATCH_SOURCE=source):
                self._stream_equals_full()

    def _stream_equals_full(self):
        import os
        from maniml.animation.animation import prepare_animation
        from maniml.animation.creation import ShowCreation
        from maniml.animation.rotation import Rotate
        from maniml.constants import LEFT, RIGHT, UP, YELLOW
        from maniml.mobject.geometry import Square
        from maniml.utils import programs
        from maniml.web.geometry import GeometryCache, parse_geometry_message, serialize_scene
        from tests.test_retained_frame import synthetic_scene
        scene, family, path, cloud, globe = synthetic_scene()
        full, stream = GeometryCache(), GeometryCache()
        stream.negotiate(True)
        sent = {"full": [], "delta": []}
        renderer = "triangles"

        def frame():
            sent["full"].append(serialize_scene(scene, full, renderer=renderer))
            sent["delta"].append(serialize_scene(scene, stream, renderer=renderer))

        def play(*animations):
            animations = [prepare_animation(animation) for animation in animations]
            for animation in animations:
                animation.begin()
            frame()
            for alpha in (.2, .45, .7, .9):
                for animation in animations:
                    animation.interpolate(alpha)
                frame()
            for animation in animations:
                animation.finish()
            frame()

        for _ in range(3):
            frame()
        family.shift(.3 * UP)
        frame()
        scene.camera.frame.shift(.05 * RIGHT)
        frame()
        scene.camera.frame.scale(1.1)
        frame()
        for z_index in (5, 0):
            family[1].z_index = z_index
            frame()
        extra = Square(side_length=.8, fill_color=YELLOW, fill_opacity=1, stroke_width=0).shift(2.4 * UP)
        scene.mobjects.append(extra)
        scene.render_groups[0].add(extra)
        frame()
        scene.mobjects.remove(path)
        scene.render_groups[0].remove(path)
        frame()
        play(family.animate.shift(LEFT))
        full.reset()
        stream.reset()
        frame()
        frame()
        renderer = "phase_b"
        frame()
        programs.set_override("gpu")
        try:
            play(family.animate.shift(RIGHT), Rotate(extra, 1.0), ShowCreation(family[0]))
        finally:
            programs.set_override(None)
        frame()
        renderer = "triangles"
        frame()
        frame()
        headers = [parse_geometry_message(message)[0] for message in sent["delta"] if message is not None]
        self.assertTrue(any(header.get("scalars") for header in headers), "a program play sends scalars ops")
        rows = [batch for message in sent["full"] for batch in parse_geometry_message(message)[0]["batches"]
                if "rows" in batch]
        self.assertEqual(bool(rows), os.environ.get("MANIML_PATCH_SOURCE") == "rows")
        if rows:
            self.assertTrue(any(len(batch["rows"]) > 1 for batch in rows), "a run of several row sources")
            self.assertEqual({batch["pipeline"] for batch in rows}, {"patch", "stroke"})
        played = delta_equals_full(self, sent)
        self.assertEqual(played["frames"], len(sent["full"]))
        # Four epochs open with a full frame (the cold frame, the reset and
        # each switch); every frame that changed nothing is sent nothing.
        self.assertEqual(sum(message is None for message in sent["delta"]), played["skipped"])
        self.assertEqual(played["frames"] - played["deltas"] - played["skipped"], 4)
        self.assertGreater(played["skipped"], 3)

    def test_surface_net_wire_evaluates_and_regrows_across_a_zoom(self):
        """The port's surfaces scene, zoomed 16x (the reservations grow),
        then moved at those reservations (B5.5): a pan, a zoom that moves no
        net's step count and one that moves some. The browser driver
        evaluates each frame exactly the nets whose steps moved, at the steps
        Python's rule (gpu_net_geometry.evaluation_steps, the native
        driver's) gives, in one dispatch."""
        import json
        from maniml.web import gpu_net_geometry
        from maniml.web.geometry import GeometryCache, parse_geometry_message
        from maniml.web.triangle_scene import TriangleMeshCache
        from maniml.web.wgpu_renderer import pack_uniforms
        from tests.test_wgpu_port import build_surfaces_scene
        scene, cache, wire = build_surfaces_scene(), TriangleMeshCache(), GeometryCache()

        def steps_of(header, capacities=None):
            """Each net's (capacity, steps), at ``capacities`` if given."""
            nets = []
            for index, batch in enumerate(header["batches"]):
                floats = np.frombuffer(pack_uniforms({**header["camera"], **batch.get("uniforms", {})}), dtype="<f4")
                capacity = batch["net"]["capacity"] if capacities is None else capacities[index]
                nets.append((capacity, gpu_net_geometry.evaluation_steps(
                    batch["net"]["density"], floats[17], header["resolution"][1], floats[23], capacity)))
            return nets

        messages, expected, previous = [], [], None
        for step in ("first", "zoom", "pan", "still steps", "moved steps"):
            if step == "zoom":
                scene.camera.frame.scale(1 / 16)
            elif step == "pan":
                scene.camera.frame.shift([.05, -.03, 0])
            elif step in ("still steps", "moved steps"):
                # A zoom whose steps, at the reservations standing, did or
                # did not move: probed through caches of their own.
                for factor in ((.998, 1.002, .995, 1.005, .99, 1.01) if step == "still steps"
                               else (.9, 1.1, .8, 1.25, .7)):
                    scene.camera.frame.scale(factor)
                    scene.camera.refresh_uniforms()
                    probe = parse_geometry_message(self._frames(scene, TriangleMeshCache(), GeometryCache(),
                                                                net_surfaces=True))[0]
                    probed = steps_of(probe, [capacity for capacity, _ in previous])
                    if (probed != previous) == (step == "moved steps"):
                        break
                    scene.camera.frame.scale(1 / factor)
                else:
                    self.fail(f"no zoom found for {step}")
            scene.camera.refresh_uniforms()
            message = self._frames(scene, cache, wire, net_surfaces=True)
            nets = steps_of(parse_geometry_message(message)[0])
            messages.append(message)
            if step in ("pan", "still steps", "moved steps"):
                self.assertEqual([capacity for capacity, _ in nets], [capacity for capacity, _ in previous],
                                 f"{step}: the reservations stand")
            expected.append([steps for (capacity, steps), before in zip(nets, previous or [None] * len(nets))
                             if before != (capacity, steps)])
            previous = nets
        self.assertEqual([len(steps) for steps in expected], [2, 2, 0, 0, len(expected[4])])
        self.assertTrue(expected[4], "some step count moved")
        with tempfile.TemporaryDirectory() as directory:
            files = []
            for index, message in enumerate(messages):
                files.append(Path(directory) / f"nets_{index}.bin")
                files[-1].write_bytes(message)
            self.run_case("netWire", json.dumps(expected), *files)

    def test_net_runs_draw_each_members_steps_in_one_draw(self):
        """B5.7: consecutive nets that can share a draw are one batch, a run
        drawn in one indexed draw over its output with the index pattern of
        each member's steps (Python's gpu_net_geometry.run_indices, not the
        capacity's); a textured surface between them splits them. Then a
        member moves, and the run that stands for it evaluates that member
        alone into its span of the output the run drew before; then a zoom
        that moves some members' steps at the reservations standing
        evaluates those and draws the new pattern."""
        import json
        from maniml.mobject.three_dimensions import Sphere
        from maniml.mobject.types.surface import TexturedSurface
        from maniml.constants import LEFT, RIGHT, UP
        from maniml.web import gpu_net_geometry
        from maniml.web.geometry import GeometryCache, parse_geometry_message
        from maniml.web.triangle_scene import TriangleMeshCache
        from maniml.web.wgpu_renderer import pack_uniforms
        from tests.renderer_fixtures import build_scene
        from tests.surface_fixtures import image_path
        spheres = [Sphere(radius=.6, resolution=(9, 7)).shift(2.4 * LEFT), Sphere(radius=.4, resolution=(7, 5)).shift(LEFT),
                   TexturedSurface(Sphere(radius=.4, resolution=(7, 7)), image_path()).shift(UP),
                   Sphere(radius=.5, resolution=(9, 7)).shift(RIGHT), Sphere(radius=.3, resolution=(7, 5)).shift(2.2 * RIGHT),
                   Sphere(radius=.3, resolution=(5, 5)).shift(2.2 * RIGHT + UP)]
        scene = build_scene(*spheres, resolution=(480, 270), samples=4)
        cache, wire = TriangleMeshCache(), GeometryCache()

        def draws_of(header, capacity=None):
            """Per net batch: its members' (hash, capacity, steps, first byte)
            and the pattern it draws; the steps at ``capacity`` if given."""
            out = []
            for batch in header["batches"]:
                floats = np.frombuffer(pack_uniforms({**header["camera"], **batch.get("uniforms", {})}), dtype="<f4")
                members, first, pattern = [], 0, []
                for net in batch["net"] if isinstance(batch["net"], list) else [batch["net"]]:
                    patches = ((net["nu"] - 1) // 2) * ((net["nv"] - 1) // 2)
                    steps = gpu_net_geometry.evaluation_steps(net["density"], floats[17], header["resolution"][1],
                                                              floats[23], capacity or net["capacity"])
                    members.append((net["hash"], net["capacity"], steps, first * batch["stride"]))
                    pattern.append((patches, net["capacity"], steps))
                    first += patches * gpu_net_geometry.vertices_per_patch(net["capacity"])
                out.append((members, gpu_net_geometry.run_indices(pattern)))
            return out

        messages, expected, previous = [], [], None
        for step in ("first", "moved", "zoom"):
            if step == "moved":
                spheres[3].shift([.05, .02, 0])
            elif step == "zoom":
                # A zoom that moves some steps while every reservation stands:
                # what each net needs (its steps uncapped) within the
                # capacity it holds, probed through caches of their own.
                held = [[capacity for _, capacity, _, _ in members] for members, _ in previous]
                for factor in (.9, .8, .7, .6, .5):
                    scene.camera.frame.scale(factor)
                    scene.camera.refresh_uniforms()
                    probe = draws_of(parse_geometry_message(self._frames(
                        scene, TriangleMeshCache(), GeometryCache(), net_surfaces=True))[0], 32)
                    needed = [[steps for _, _, steps, _ in members] for members, _ in probe]
                    if (all(n <= c for ns, cs in zip(needed, held) for n, c in zip(ns, cs))
                            and needed != [[steps for _, _, steps, _ in members] for members, _ in previous]):
                        break
                    scene.camera.frame.scale(1 / factor)
                else:
                    self.fail("no zoom moves a step count at the reservations standing")
            scene.camera.refresh_uniforms()
            message = self._frames(scene, cache, wire, net_surfaces=True)
            header = parse_geometry_message(message)[0]
            draws = draws_of(header)
            if previous is None:
                self.assertEqual([len(batch["net"]) if isinstance(batch["net"], list) else 1
                                  for batch in header["batches"]], [2, 1, 3], "two runs split by the textured net")
            frame = []
            for index, (members, indices) in enumerate(draws):
                before = previous[index][0] if previous else [None] * len(members)
                frame.append({"count": len(indices),
                              "evaluated": [[first, steps] for (key, capacity, steps, first), was
                                            in zip(members, before) if was != (key, capacity, steps, first)]})
            messages.append((message, b"".join(indices.astype("<u4").tobytes() for _, indices in draws)))
            expected.append({"draws": frame})
            previous = draws
        self.assertEqual([[len(draw["evaluated"]) for draw in frame["draws"]] for frame in expected[:2]],
                         [[2, 1, 3], [0, 0, 1]])
        self.assertTrue(any(draw["evaluated"] for draw in expected[2]["draws"]))
        self.assertEqual([[capacity for _, capacity, _, _ in members] for members, _ in previous], held,
                         "the reservations stand through the zoom")
        with tempfile.TemporaryDirectory() as directory:
            files = []
            for index, (message, pattern) in enumerate(messages):
                files.append(Path(directory) / f"runs_{index}.bin")
                files[-1].write_bytes(message)
                files.append(Path(directory) / f"pattern_{index}.bin")
                files[-1].write_bytes(pattern)
            self.run_case("netRunsWire", json.dumps(expected), *files)


@unittest.skipIf(shutil.which("node") is None, "node not available")
@unittest.skipUnless(_lyon(), "the Lyon helper is the frame preparer's tessellator")
class GeneratedWebGPUStrokePrograms(unittest.TestCase):
    """The browser driver on real Phase A frames under MANIML_PROGRAMS=strokes
    (docs/phase_b4_plan.md, B5.3): paths without fill drawn from GPU
    programs, filled paths from Phase A's own meshes and strokes."""

    @staticmethod
    def _play():
        """A static axis; a curve's creation, a ring's fade in, a triangle's
        rotation and a square outline's blend into a circle's, programs all;
        and a filled square's move, the CPU's."""
        from maniml.animation.creation import ShowCreation
        from maniml.animation.fading import VFadeIn
        from maniml.animation.rotation import Rotate
        from maniml.animation.transform import Transform
        from maniml.constants import BLUE, DOWN, GREEN, LEFT, RED, RIGHT, UP, YELLOW
        from maniml.mobject.functions import FunctionGraph
        from maniml.mobject.geometry import Circle, Line, Square, Triangle
        from tests.renderer_fixtures import build_scene
        axis = Line(4 * LEFT + 2.5 * DOWN, 4 * RIGHT + 2.5 * DOWN, stroke_width=3)
        curve = FunctionGraph(lambda x: .3 * x * x - 1.5, x_range=(-2.5, 2.5, .25), color=YELLOW, stroke_width=5)
        ring = Circle(radius=.8, stroke_color=RED, stroke_width=6).shift(2.8 * RIGHT)
        triangle = Triangle(stroke_color=GREEN, stroke_width=4).shift(2.8 * LEFT + UP)
        outline = Square(side_length=1.2, stroke_color=BLUE, stroke_width=5).shift(1.5 * UP)
        filled = Square(side_length=1, fill_color=GREEN, fill_opacity=.9, stroke_color=BLUE, stroke_width=4).shift(2 * DOWN)
        scene = build_scene(axis, curve, ring, triangle, outline, filled, resolution=(480, 270), samples=4)
        animations = [ShowCreation(curve), VFadeIn(ring), Rotate(triangle, 1.0),
                      Transform(outline, Circle(radius=.7, stroke_color=RED, stroke_width=3).shift(1.5 * UP)),
                      filled.animate.shift(RIGHT)]
        return scene, animations

    def test_stroke_programs_draw_their_finalized_instances(self):
        import os
        from unittest.mock import patch
        from maniml.animation.animation import prepare_animation
        from maniml.web.geometry import GeometryCache, serialize_scene
        with patch.dict(os.environ, MANIML_FILL="meshes", MANIML_BORDER_GENERATOR="gpu", MANIML_PROGRAMS="strokes"):
            scene, animations = self._play()
            animations = [prepare_animation(animation) for animation in animations]
            wire = GeometryCache()
            for animation in animations:
                animation.begin()
            with tempfile.TemporaryDirectory() as directory:
                files = []
                for index, alpha in enumerate((.3, .6, .6)):
                    for animation in animations:
                        animation.interpolate(alpha)
                    files.append(Path(directory) / f"strokes_{index}.bin")
                    files[-1].write_bytes(serialize_scene(scene, wire, renderer="triangles"))
                result = subprocess.run(["node", str(HARNESS), "strokeProgramsWire", *map(str, files)],
                                        capture_output=True, text=True, timeout=60)
            for animation in animations:
                animation.finish()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_a_format_8_stream_draws_what_its_full_frames_draw(self):
        # B4.8's equivalence over a Phase A history whose play is drawn from
        # stroke programs: their scalars travel as scalars ops.
        import os
        from unittest.mock import patch
        from maniml.animation.animation import prepare_animation
        from maniml.constants import RIGHT
        from maniml.web.geometry import GeometryCache, parse_geometry_message, serialize_scene
        with patch.dict(os.environ, MANIML_FILL="meshes", MANIML_BORDER_GENERATOR="gpu", MANIML_PROGRAMS="strokes"):
            scene, animations = self._play()
            full, stream = GeometryCache(), GeometryCache()
            stream.negotiate(True)
            sent = {"full": [], "delta": []}

            def frame():
                sent["full"].append(serialize_scene(scene, full, renderer="triangles"))
                sent["delta"].append(serialize_scene(scene, stream, renderer="triangles"))

            frame()
            frame()
            animations = [prepare_animation(animation) for animation in animations]
            for animation in animations:
                animation.begin()
            frame()
            for alpha in (.2, .45, .45, .7, .9):
                for animation in animations:
                    animation.interpolate(alpha)
                frame()
            for animation in animations:
                animation.finish()
            frame()
            frame()
            scene.camera.frame.shift(.05 * RIGHT)
            frame()
        headers = [parse_geometry_message(message)[0] for message in sent["delta"] if message is not None]
        self.assertTrue(sum(bool(header.get("scalars")) for header in headers) >= 3, "the play's scalars ops")
        played = delta_equals_full(self, sent)
        self.assertEqual(played["frames"], len(sent["full"]))
        self.assertEqual(sum(message is None for message in sent["delta"]), played["skipped"])
        self.assertEqual(played["frames"] - played["deltas"] - played["skipped"], 1)

"""The blend program (docs/phase_b3_plan.md): the row summary, the
mobject's pending program and its materialize-on-read guarantee, the
Transform integration under MANIML_PROGRAMS, the wire, and, with
MANIML_TEST_GPU=1, pixels against the CPU path at several alphas."""

import copy
import importlib.util
import os
import unittest
from unittest.mock import patch

import numpy as np

from maniml.animation.transform import Transform
from maniml.constants import BLUE, GREEN, RED
from maniml.mobject.geometry import Circle, Square
from maniml.mobject.mobject import Mobject, copy_mode
from maniml.mobject.svg.text_mobject import Text
from maniml.mobject.three_dimensions import Sphere, Torus
from maniml.scene.checkpoints import DERIVED_DATA_KEYS, ledger_stale_attribute
from maniml.utils import programs
from maniml.web import gpu_program_geometry as programs_geometry
from maniml.web.generated_geometry import serialize_generated_frame
from maniml.web.geometry import GeometryCache, parse_geometry_message, serialize_scene
from maniml.web.triangle_geometry import LyonFillTessellator
from maniml.web.triangle_scene import TriangleMeshCache, prepare_triangle_frame
from tests.renderer_fixtures import build_scene

HAVE_LYON = bool(os.environ.get("MANIML_LYON_LIBRARY")) or importlib.util.find_spec("maniml.web.maniml_lyon_fill")
PHASE_B = dict(MANIML_FILL="patches", MANIML_BORDER_GENERATOR="gpu", MANIML_SURFACE="nets")


def _endpoints():
    start = Circle(radius=1.2, fill_color=BLUE, fill_opacity=.6, stroke_color=RED, stroke_width=6,
                   fill_border_width=3).shift([-1, 0, 0])
    target = Square(side_length=2.5, fill_color=GREEN, fill_opacity=.9, stroke_color=BLUE, stroke_width=10,
                    fill_border_width=3).shift([1.5, .5, 0])
    return start, target


def _aligned():
    """(mobject, start copy, target) aligned as Transform.begin aligns them."""
    mob, target = _endpoints()
    mob.align_data_and_family(target)
    start = mob.copy()
    for each in (mob, start, target):
        each.get_joint_angles()
    return mob, start, target


def _state(mobject):
    """What the ledger compares: every column but the derived ones (a
    program's sources carry fresh derived columns; the CPU path's rows
    hold whatever the last read left), the uniforms, the box."""
    return [([sm._data[k].tobytes() for k in sm._data.dtype.names if k not in DERIVED_DATA_KEYS],
             sorted((k, np.asarray(v).tobytes()) for k, v in sm.uniforms.items()),
             sm.bounding_box.tobytes()) for sm in mobject.get_family()]


class ProgramGeometry(unittest.TestCase):
    def test_rows_hash_and_program_key_follow_content(self):
        start, target = _endpoints()
        rows = programs_geometry.pack_rows(start)
        self.assertEqual(rows.shape, (start.get_num_points(), programs_geometry.ROW_FLOATS))
        self.assertFalse(rows.flags.writeable)
        self.assertEqual(programs_geometry.rows_hash(rows), programs_geometry.rows_hash(rows.copy()))
        self.assertNotEqual(programs_geometry.rows_hash(rows),
                            programs_geometry.rows_hash(programs_geometry.pack_rows(target)))
        a, b = programs_geometry.rows_hash(rows), programs_geometry.rows_hash(programs_geometry.pack_rows(target))
        self.assertNotEqual(programs_geometry.program_key("blend", [a, b]), programs_geometry.program_key("blend", [b, a]))

    def test_descriptor_validation(self):
        good = {"kind": "blend", "sources": ["0" * 32, "f" * 32], "scalars": [0.5], "rows": 9, "channels": 17}
        self.assertEqual(programs_geometry.validate_program(good), ("blend", ["0" * 32, "f" * 32], [0.5], 9, 17))
        for bad in ({**good, "kind": "warp"}, {**good, "sources": ["0" * 32]}, {**good, "sources": ["g" * 32, "0" * 32]},
                    {**good, "scalars": [float("nan")]}, {**good, "scalars": [True]}, {**good, "rows": 0},
                    {**good, "channels": "17"}, "blend"):
            with self.assertRaises(ValueError, msg=str(bad)):
                programs_geometry.validate_program(bad)
        with self.assertRaises(ValueError):
            programs_geometry.validate_program(good, stride=72)
        programs_geometry.validate_program(good, stride=68)

    def test_recipe_summarizes_both_endpoints_once(self):
        mob, start, target = _aligned()
        sources = [programs_geometry.pack_rows(start), programs_geometry.pack_rows(target)]
        recipe = programs_geometry.ProgramRecipe(sources)
        self.assertTrue(recipe.aligned)
        self.assertEqual(recipe.curves, programs_geometry.curve_count(mob.get_num_points()))
        self.assertTrue(recipe.has_fill and recipe.has_stroke and recipe.bordered and recipe.uniform_fill)
        record = recipe.fill_record
        self.assertEqual(record.shape, (1, 8))
        self.assertEqual(tuple(record[0, 3:8]), (0, recipe.curves, 1, 0, 0))
        # A reservation grows only when a zoom outgrows it, from either endpoint's need.
        far = recipe.border_capacity(frame_scale=8.0)
        near = recipe.border_capacity(frame_scale=0.5)
        self.assertLessEqual(far, near)
        self.assertEqual(recipe.border_capacity(frame_scale=8.0), near)
        self.assertGreaterEqual(recipe.stroke_vertices(0.5), recipe.stroke_vertices(8.0))
        self.assertFalse(programs_geometry.ProgramRecipe([sources[0], sources[1][:-2]]).aligned)
        self.assertFalse(programs_geometry.ProgramRecipe([sources[0][:1], sources[1][:1]]).aligned)
        # A per-vertex fill colour on either end needs a paint field: not this program.
        painted = sources[1].copy()
        painted[0, 9] += .5
        self.assertFalse(programs_geometry.ProgramRecipe([sources[0], painted]).uniform_fill)


class ProgramMobject(unittest.TestCase):
    def setUp(self):
        self.count = 0
        original = Mobject._materialize_program

        def counting(mobject):
            self.count += 1
            return original(mobject)
        patcher = patch.object(Mobject, "_materialize_program", counting)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_deferred_blend_writes_rows_on_the_first_read_only(self):
        mob, start, target = _aligned()
        before, revision = mob._data.copy(), mob.revision
        self.assertTrue(mob.blend_program(start, target, .4, defer=True))
        self.assertGreater(mob.revision, revision, "a program is a change the ledger and the renderer see")
        self.assertEqual(mob.get_num_points(), len(before))
        self.assertTrue(mob.has_points())
        self.assertEqual(mob.family_members_with_points(), [mob])
        self.assertEqual(self.count, 0, "counts read no rows")
        np.testing.assert_array_equal(mob._data.view(np.float32), before.view(np.float32))
        expected = mob.copy()   # a copy is a read
        self.assertEqual(self.count, 1)
        self.assertNotIn("_program", expected.__dict__)
        reference = start.copy().interpolate(start, target, .4)
        self.assertEqual(mob.data.tobytes(), reference.data.tobytes())
        self.assertEqual(mob.get_points().tobytes(), reference.get_points().tobytes())
        self.assertEqual(self.count, 1, "materialized once")
        np.testing.assert_array_equal(mob.bounding_box, reference.bounding_box)
        self.assertIn("_program", mob.__dict__, "the renderer still draws the program")
        mob.finish_program()
        self.assertNotIn("_program", mob.__dict__)
        self.assertEqual(mob.data.tobytes(), reference.data.tobytes())

    def test_shadow_blend_writes_rows_now(self):
        mob, start, target = _aligned()
        self.assertTrue(mob.blend_program(start, target, .7, defer=False))
        reference = start.copy().interpolate(start, target, .7)
        self.assertEqual(mob._data.tobytes(), reference._data.tobytes())
        self.assertEqual(self.count, 0)
        self.assertEqual(mob._program["scalars"], [.7])

    def test_misaligned_endpoints_are_refused_untouched(self):
        mob, start, target = _aligned()
        other = Square()
        revision = mob.revision
        self.assertFalse(mob.blend_program(start, other, .5, defer=True))
        self.assertEqual(mob.revision, revision)
        self.assertNotIn("_program", mob.__dict__)

    def test_finish_writes_exactly_what_the_cpu_path_writes(self):
        for alpha in (0.0, .3, 1.0):
            mob, start, target = _aligned()
            mob.blend_program(start, target, alpha, defer=True)
            mob.finish_program()
            reference = start.copy().interpolate(start, target, alpha)
            self.assertEqual(mob._data.tobytes(), reference._data.tobytes(), alpha)

    def test_copies_and_checkpoints_carry_rows_not_programs(self):
        mob, start, target = _aligned()
        mob.blend_program(start, target, .25, defer=True)
        with copy_mode("freeze"):
            frozen = copy.deepcopy(mob)
        self.assertNotIn("_program", frozen.__dict__)
        self.assertFalse(frozen.data.flags.writeable)
        self.assertEqual(self.count, 1)
        self.assertEqual(frozen.data.tobytes(), mob.data.tobytes())
        self.assertIsNone(ledger_stale_attribute(mob, frozen), "a pending program is not a stale checkpoint")
        deep = mob.deepcopy()
        self.assertNotIn("_program", deep.__dict__)
        self.assertEqual(self.count, 1, "once materialized, no copy reads again")

    def test_assigning_rows_supersedes_the_program(self):
        mob, start, target = _aligned()
        mob.blend_program(start, target, .5, defer=True)
        mob.set_data(target.data)
        self.assertNotIn("_program", mob.__dict__)
        self.assertEqual(mob.data.tobytes(), target.data.tobytes())
        mob.blend_program(start, target, .5, defer=True)
        mob.data = target.data.copy()
        self.assertNotIn("_program", mob.__dict__)
        self.assertEqual(mob.data.tobytes(), target.data.tobytes())


class ProgramTransform(unittest.TestCase):
    def play(self, mode, arc=0.0):
        with patch.dict(os.environ, MANIML_PROGRAMS=mode):
            mob, target = _endpoints()
            text, text_target = Text("ab", font_size=48), Text("ab", font_size=72, color=GREEN).shift([0, 2, 0])
            anims = [Transform(mob, target, path_arc=arc), Transform(text, text_target)]
            for anim in anims:
                anim.begin()
            frames = []
            for alpha in (0.0, .5, 1.0):
                for anim in anims:
                    anim.interpolate(alpha)
                # A member with every column locked (the text's pointless parent) records nothing.
                frames.append([("_program" in sm.__dict__, sm._program is not None and not sm._program["materialized"])
                               for sm in mob.get_family() + text.get_family() if sm.has_points()])
            for anim in anims:
                anim.finish()
            self.assertFalse(any("_program" in sm.__dict__ for sm in mob.get_family() + text.get_family()))
            return frames, _state(mob) + _state(text)

    def test_mode_switch(self):
        self.assertEqual(programs.mode(), "off")
        with patch.dict(os.environ, MANIML_PROGRAMS="gpu"):
            self.assertEqual(programs.mode(), "gpu")
        with patch.dict(os.environ, MANIML_PROGRAMS="fast"):
            with self.assertRaises(ValueError):
                programs.mode()

    def test_every_mode_ends_in_the_same_state(self):
        off_frames, off_state = self.play("off")
        shadow_frames, shadow_state = self.play("shadow")
        gpu_frames, gpu_state = self.play("gpu")
        self.assertEqual(shadow_state, off_state)
        self.assertEqual(gpu_state, off_state)
        self.assertFalse(any(flag for frame in off_frames for flag, _ in frame))
        self.assertTrue(all(pending and not deferred for frame in shadow_frames for pending, deferred in frame))
        self.assertTrue(all(pending and deferred for frame in gpu_frames for pending, deferred in frame))

    def test_an_arc_keeps_the_cpu_path(self):
        frames, state = self.play("gpu", arc=1.0)
        circle_frames = [frame[0] for frame in frames]
        self.assertFalse(any(pending for pending, _ in circle_frames))
        self.assertEqual(state, self.play("off", arc=1.0)[1])


@unittest.skipUnless(HAVE_LYON, "the Lyon helper is the frame preparer's tessellator")
class ProgramWire(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tessellator = LyonFillTessellator()

    def prepare(self, scene, cache, **kwargs):
        return prepare_triangle_frame(scene, self.tessellator, mesh_cache=cache, fill_borders=True,
                                      gpu_borders=True, patch_fills=True, net_surfaces=True, programs=True, **kwargs)

    def test_program_draws_and_sources_sent_once(self):
        mob, start, target = _aligned()
        sphere, torus = Sphere(resolution=(9, 5)), Torus(resolution=(9, 5))
        sphere.align_data_and_family(torus)
        sphere_start = sphere.copy()
        scene = build_scene(mob, sphere)
        cache, wire = TriangleMeshCache(), GeometryCache()
        headers = []
        for alpha in (.2, .6, .6):
            # Programs as blend_program records them, with the rows already written.
            mob._program = {"kind": "blend", "sources": (start, target), "scalars": [alpha], "keys": [], "materialized": True}
            sphere._program = {"kind": "blend", "sources": (sphere_start, torus), "scalars": [alpha], "keys": [], "materialized": True}
            frame = self.prepare(scene, cache)
            self.assertEqual([d.pipeline for d in frame.draws], ["patch", "stroke", "surface_depth"])
            self.assertTrue(all(d.program is not None for d in frame.draws))
            header, payload = parse_geometry_message(serialize_generated_frame(frame, scene.camera.uniforms, wire))
            headers.append((header, len(payload)))
        first, later, same = headers
        self.assertEqual(len(first[0]["program_data"]), 4)
        self.assertEqual(first[0]["batches"][0]["program"]["scalars"], [.2])
        self.assertEqual(first[0]["batches"][0]["program"]["rows"], mob.get_num_points())
        self.assertEqual(first[0]["batches"][0]["program"]["channels"], 17)
        self.assertEqual(first[0]["batches"][2]["program"]["channels"], sphere.data.dtype.itemsize // 4)
        for header, payload_size in (later, same):
            self.assertEqual(payload_size, 0, "only the scalar travels after the first frame")
            self.assertEqual(header["program_data"], {})
            self.assertTrue(all(batch["cached"] for batch in header["batches"]))
            self.assertEqual([batch["program"]["scalars"] for batch in header["batches"]], [[.6]] * 3)
        self.assertEqual(first[0]["batches"][0]["program"]["sources"], later[0]["batches"][0]["program"]["sources"])
        self.assertEqual(first[0]["batches"][0]["border"]["layout"], [[len(start.get_points()) // 2, 1, 0]])

    def test_switch_requires_the_patch_fill_and_never_materializes_a_drawn_program(self):
        with patch.dict(os.environ, MANIML_PROGRAMS="gpu", MANIML_FILL="meshes"):
            with self.assertRaises(ValueError):
                serialize_scene(build_scene(Square()), GeometryCache(), renderer="triangles")
        with patch.dict(os.environ, **PHASE_B, MANIML_PROGRAMS="gpu"):
            mob, target = _endpoints()
            scene, wire = build_scene(mob), GeometryCache()
            anim = Transform(mob, target)
            anim.begin()
            with patch.object(Mobject, "_materialize_program", side_effect=AssertionError("a frame read rows")):
                for alpha in (0.0, .5, 1.0):
                    anim.interpolate(alpha)
                    header, _ = parse_geometry_message(serialize_scene(scene, wire, renderer="triangles"))
                    self.assertEqual([b["pipeline"] for b in header["batches"]], ["patch", "stroke"])
                    self.assertEqual(header["batches"][0]["program"]["scalars"], [alpha])
            anim.finish()

    def test_unsupported_programs_fall_back_to_the_rows(self):
        with patch.dict(os.environ, **PHASE_B, MANIML_PROGRAMS="gpu"):
            mob, target = _endpoints()
            mob.set_fill([RED, BLUE])   # a paint field: B3b's work
            scene, wire = build_scene(mob), GeometryCache()
            anim = Transform(mob, target)
            anim.begin()
            anim.interpolate(.5)
            header, _ = parse_geometry_message(serialize_scene(scene, wire, renderer="triangles"))
            self.assertTrue(all("program" not in batch for batch in header["batches"]))
            self.assertEqual(mob.data.tobytes(), mob.copy().interpolate(anim.starting_mobject, anim.target_copy, .5).data.tobytes())
            anim.finish()


@unittest.skipUnless(os.environ.get("MANIML_TEST_GPU") == "1", "GPU image comparison not requested")
class ProgramPixels(unittest.TestCase):
    """Every mode draws the same frame, at every alpha, for paths (fill,
    border, stroke) and for nets; the CPU rows after the play are the same."""

    ALPHAS = (0.0, .13, .37, .5, .75, 1.0)

    @classmethod
    def setUpClass(cls):
        from maniml.web.wgpu_renderer import WgpuRenderer
        cls.drivers = {mode: WgpuRenderer() for mode in programs.MODES}

    @classmethod
    def tearDownClass(cls):
        for driver in cls.drivers.values():
            driver.close()

    def frames(self, mode, build):
        with patch.dict(os.environ, **PHASE_B, MANIML_PROGRAMS=mode):
            mobjects, targets = build()
            scene, wire = build_scene(*mobjects, resolution=(480, 270), samples=4), GeometryCache()
            anims = [Transform(a, b) for a, b in zip(mobjects, targets)]
            for anim in anims:
                anim.begin()
            frames = []
            for alpha in self.ALPHAS:
                for anim in anims:
                    anim.interpolate(alpha)
                header, payload = parse_geometry_message(serialize_scene(scene, wire, renderer="triangles"))
                frames.append(np.asarray(self.drivers[mode].render(header, payload), dtype=int))
            for anim in anims:
                anim.finish()
            return frames, [_state(m) for m in mobjects]

    def assert_modes_agree(self, build, tolerance):
        reference, state = self.frames("off", build)
        for mode in ("shadow", "gpu"):
            frames, end = self.frames(mode, build)
            self.assertEqual(end, state, mode)
            for alpha, frame, expected in zip(self.ALPHAS, frames, reference):
                diff = np.abs(frame - expected)
                self.assertLessEqual((diff.max(axis=2) > 24).mean(), .005, (mode, alpha))
                if tolerance is not None:
                    self.assertLessEqual(diff.max(), tolerance, (mode, alpha))

    def test_paths_with_fill_border_and_stroke(self):
        def build():
            mob, target = _endpoints()
            text = Text("blend", font_size=48).shift([0, -1.5, 0])
            text_target = Text("blend", font_size=64, color=GREEN).shift([0, 1.5, 0])
            return (mob, text), (target, text_target)
        self.assert_modes_agree(build, tolerance=1)

    def test_nets(self):
        # A program's net is reserved from the larger endpoint's density,
        # the CPU path's from the current net's, so the step counts can
        # differ; the gate is the arbiter, as for every zoom.
        def build():
            return (Sphere(radius=1.2, resolution=(17, 9)),), (Torus(resolution=(17, 9)),)
        self.assert_modes_agree(build, tolerance=None)


if __name__ == "__main__":
    unittest.main()

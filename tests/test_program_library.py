"""B3b (docs/phase_b3_plan.md): the affine, paint and partial programs;
their animations under MANIML_PROGRAMS; composition with CPU writes; and,
with MANIML_TEST_GPU=1, pixels against the CPU path at several alphas."""

import importlib.util
import os
import unittest
from unittest.mock import patch

import numpy as np

from maniml.animation.creation import DrawBorderThenFill, ShowCreation, Uncreate, Write
from maniml.animation.fading import VFadeIn, VFadeOut
from maniml.animation.indication import ShowPassingFlash
from maniml.animation.rotation import Rotate, Rotating
from maniml.animation.transform import Transform
from maniml.constants import BLUE, GREEN, RED, RIGHT, UP, YELLOW
from maniml.mobject.geometry import Circle, Square
from maniml.mobject.mobject import Mobject
from maniml.mobject.svg.text_mobject import Text
from maniml.mobject.types.vectorized_mobject import VGroup, partial_points
from maniml.scene.checkpoints import DERIVED_DATA_KEYS
from maniml.utils import programs
from maniml.utils.space_ops import rotation_matrix_transpose
from maniml.web import gpu_program_geometry as programs_geometry
from maniml.web.geometry import GeometryCache, parse_geometry_message, serialize_scene
from tests.renderer_fixtures import build_scene

HAVE_LYON = bool(os.environ.get("MANIML_LYON_LIBRARY")) or importlib.util.find_spec("maniml.web.maniml_lyon_fill")
PHASE_B = dict(MANIML_FILL="patches", MANIML_BORDER_GENERATOR="gpu", MANIML_SURFACE="nets")


def _shapes():
    circle = Circle(radius=1.2, fill_color=BLUE, fill_opacity=.6, stroke_color=RED, stroke_width=6,
                    fill_border_width=3).shift([-3, 0, 0])
    text = Text("program", font_size=56, color=YELLOW).shift([1.5, 1.5, 0])
    square = Square(side_length=1.5, fill_color=GREEN, fill_opacity=.9, stroke_color=BLUE, stroke_width=10,
                    fill_border_width=3).shift([2, -1.5, 0])
    return VGroup(circle, text, square)


CASES = {
    "rotate": lambda g: [Rotate(g, angle=2.0)],
    "rotate_axis": lambda g: [Rotate(g[0], angle=1.0, axis=UP + RIGHT), Rotating(g[2], angle=3.0, axis=UP)],
    "vfade": lambda g: [VFadeIn(g[0]), VFadeOut(g[1]), VFadeIn(g[2])],
    "show_creation": lambda g: [ShowCreation(g)],
    "uncreate": lambda g: [Uncreate(g[1])],
    "write": lambda g: [Write(g[1]), DrawBorderThenFill(g[0])],
    "flash": lambda g: [ShowPassingFlash(g[0].copy().set_stroke(YELLOW, 8), time_width=.5)],
}
ALPHAS = (0.0, .11, .3, .5, .62, .8, .97, 1.0)


def _state(mobject):
    """What the ledger compares, plus the derived-column flags."""
    return [([sm._data[k].tobytes() for k in sm._data.dtype.names if k not in DERIVED_DATA_KEYS],
             sorted((k, np.asarray(v).tobytes()) for k, v in sm.uniforms.items()),
             sm.needs_new_unit_normal, sm.needs_new_joint_angles) for sm in mobject.get_family()]


def _play(name, mode, frames=None, render=None):
    """Run a case under a mode; ``render(header, payload)`` per frame when given."""
    with patch.dict(os.environ, **PHASE_B, MANIML_PROGRAMS=mode):
        group = _shapes()
        anims = CASES[name](group)
        extra = [a.mobject for a in anims if a.mobject not in group.get_family()]
        scene, wire = build_scene(group, *extra, resolution=(480, 270), samples=4), GeometryCache()
        for anim in anims:
            anim.begin()
        kinds, out = set(), []
        for alpha in ALPHAS:
            for anim in anims:
                anim.interpolate(alpha)
            header, payload = parse_geometry_message(serialize_scene(scene, wire, renderer="triangles"))
            kinds.update(b["program"]["kind"] for b in header["batches"] if "program" in b)
            if render is not None:
                out.append(render(header, payload))
        for anim in anims:
            anim.finish()
        return _state(group), kinds, out


class RowPrograms(unittest.TestCase):
    """Each program's CPU evaluation is the CPU path's own arithmetic."""

    def test_partial_program_writes_what_pointwise_become_partial_writes(self):
        for a, b in ((0, .37), (0, 1), (.2, .9), (.45, .45), (0, 0)):
            mob, source = Circle(), Circle()
            for each in (mob, source):
                each.get_joint_angles()
                each.get_unit_normal()
            expected = Circle()
            expected.get_joint_angles()
            expected.pointwise_become_partial(source, a, b)
            self.assertTrue(mob.partial_program(source, a, b, defer=True))
            self.assertEqual(mob._program["kind"], "partial")
            self.assertEqual(mob.data.tobytes(), expected.data.tobytes(), (a, b))
            self.assertFalse(mob.needs_new_unit_normal)
        points, i1, i4 = partial_points(Circle().get_points(), 8, .3, .6)
        self.assertEqual((i1, i4), (4, 11))
        self.assertTrue(np.all(points[:i1] == points[i1]) and np.all(points[i4:] == points[i4 - 1]))

    def test_paint_program_writes_what_set_opacity_writes(self):
        mob, source = Circle(fill_opacity=.6, stroke_width=4), Circle(fill_opacity=.6, stroke_width=4)
        expected = Circle(fill_opacity=.6, stroke_width=4)
        expected.set_stroke(opacity=.25)
        expected.set_fill(opacity=.125)
        self.assertTrue(mob.paint_program(source, .25, .125, defer=True))
        self.assertEqual(mob.data["stroke_rgba"].tobytes(), expected.data["stroke_rgba"].tobytes())
        self.assertEqual(mob.data["fill_rgba"].tobytes(), expected.data["fill_rgba"].tobytes())

    def test_affine_program_writes_what_rotate_writes(self):
        for about_point in (None, np.array([.3, -.2, .1])):
            mob, source = Square().shift([1, .5, 0]), Square().shift([1, .5, 0])
            expected = Square().shift([1, .5, 0])
            rot_matrix_T = rotation_matrix_transpose(.7, UP + RIGHT)
            expected.rotate(.7, UP + RIGHT, about_point=about_point, about_edge=None)
            self.assertTrue(mob.affine_program(source, rot_matrix_T, about_point, defer=True))
            self.assertEqual(len(mob._program["scalars"]), 16)
            self.assertEqual(mob.data["point"].tobytes(), expected.data["point"].tobytes())
            self.assertTrue(mob.needs_new_unit_normal)
            matrix = np.asarray(mob._program["scalars"]).reshape(4, 4).T   # column-major on the wire
            points = source.get_points()
            mapped = (matrix[:3, :3] @ points.T).T + matrix[:3, 3]
            np.testing.assert_allclose(mapped, expected.get_points(), atol=1e-6)

    def test_a_cpu_write_supersedes_a_pending_program(self):
        mob, source = Circle(fill_opacity=.5), Circle(fill_opacity=.5)
        mob.partial_program(source, 0, .4, defer=True)
        count = []
        original = Mobject._materialize_program
        with patch.object(Mobject, "_materialize_program", lambda self: (count.append(1), original(self))):
            mob.set_fill(opacity=.9)   # reads (materializes), writes, and drops the program
        self.assertEqual(count, [1])
        self.assertNotIn("_program", mob.__dict__)
        expected = Circle(fill_opacity=.5)
        expected.get_joint_angles()
        expected.pointwise_become_partial(source, 0, .4)
        expected.set_fill(opacity=.9)
        self.assertEqual(mob.data["point"].tobytes(), expected.data["point"].tobytes())
        self.assertEqual(mob.data["fill_rgba"].tobytes(), expected.data["fill_rgba"].tobytes())

    def test_wire_scalars_and_validation(self):
        self.assertEqual(programs_geometry.wire_scalars("partial", [0, .37], 17), [0.0, 0.0, 2.0, 0.96, 0.0])
        self.assertEqual(programs_geometry.wire_scalars("partial", [0, 1], 17), [0.0, 0.0, 7.0, 1.0, 1.0])
        self.assertEqual(programs_geometry.wire_scalars("paint", [.5, .25], 17), [.5, .25])
        good = {"kind": "partial", "sources": ["0" * 32], "scalars": [0, 0, 2, .96, 0], "rows": 17, "channels": 17}
        programs_geometry.validate_program(good)
        for bad in ({**good, "scalars": [0, 0, 9, .5, 0]}, {**good, "scalars": [0, 0, 2, 1.5, 0]},
                    {**good, "scalars": [0, 0, 2, .5, 2]}, {**good, "channels": 10},
                    {**good, "kind": "affine"}, {"kind": "paint", "sources": ["0" * 32], "scalars": [1], "rows": 3, "channels": 17}):
            with self.assertRaises(ValueError, msg=str(bad)):
                programs_geometry.validate_program(bad)


class LibraryAnimations(unittest.TestCase):
    def test_every_case_ends_in_the_same_state_in_every_mode(self):
        for name in CASES:
            with self.subTest(case=name):
                off, off_kinds, _ = _play(name, "off")
                self.assertEqual(off_kinds, set())
                for mode in ("shadow", "gpu"):
                    state, kinds, _ = _play(name, mode)
                    self.assertEqual(state, off, (name, mode))
                    self.assertTrue(kinds, (name, mode))

    def test_gpu_frames_read_no_rows(self):
        for name in ("rotate", "vfade", "show_creation", "flash"):
            with patch.object(Mobject, "_materialize_program", side_effect=AssertionError(f"{name} read rows mid-play")):
                with patch.dict(os.environ, **PHASE_B, MANIML_PROGRAMS="gpu"):
                    group = _shapes()
                    anims = CASES[name](group)
                    extra = [a.mobject for a in anims if a.mobject not in group.get_family()]
                    scene, wire = build_scene(group, *extra, resolution=(480, 270), samples=4), GeometryCache()
                    for anim in anims:
                        anim.begin()
                    for alpha in ALPHAS:
                        for anim in anims:
                            anim.interpolate(alpha)
                        serialize_scene(scene, wire, renderer="triangles")
            for anim in anims:
                anim.finish()

    def test_updaters_and_composition_keep_the_cpu_path(self):
        with patch.dict(os.environ, **PHASE_B, MANIML_PROGRAMS="gpu"):
            live = Circle(fill_opacity=.5)
            live.add_updater(lambda m, dt: None)
            fade = VFadeIn(live)
            fade.begin()
            fade.interpolate(.5)
            self.assertNotIn("_program", live.__dict__, "an updater on the family keeps the fade on the CPU")
            fade.finish()
            # A fade on top of a transform in one play: the transform's blend is
            # materialized and the opacity applied to its rows, as the CPU does.
            mob, target = Circle(fill_opacity=.5).shift([-1, 0, 0]), Square(fill_opacity=.5).shift([1, 0, 0])
            anims = [Transform(mob, target), VFadeIn(mob)]
            for anim in anims:
                anim.begin()
            for anim in anims:
                anim.interpolate(.5)
            self.assertNotIn("_program", mob.__dict__)
            with patch.dict(os.environ, MANIML_PROGRAMS="off"):
                expected, expected_target = Circle(fill_opacity=.5).shift([-1, 0, 0]), Square(fill_opacity=.5).shift([1, 0, 0])
                reference = [Transform(expected, expected_target), VFadeIn(expected)]
                for anim in reference:
                    anim.begin()
                for anim in reference:
                    anim.interpolate(.5)
            self.assertEqual(mob.data["point"].tobytes(), expected.data["point"].tobytes())
            self.assertEqual(mob.data["fill_rgba"].tobytes(), expected.data["fill_rgba"].tobytes())
            for anim in anims + reference:
                anim.finish()

    def test_an_arc_transform_keeps_the_cpu_path(self):
        with patch.dict(os.environ, **PHASE_B, MANIML_PROGRAMS="gpu"):
            mob = Circle()
            anim = Transform(mob, Square(), path_arc=1.0)
            anim.begin()
            anim.interpolate(.5)
            self.assertNotIn("_program", mob.__dict__)
            anim.finish()


@unittest.skipUnless(HAVE_LYON, "the Lyon helper is the frame preparer's tessellator")
class LibraryWire(unittest.TestCase):
    def test_each_case_sends_its_kind(self):
        expected = {"rotate": {"affine"}, "vfade": {"paint"}, "show_creation": {"partial"},
                    "write": {"partial", "blend"}, "flash": {"partial"}}
        for name, kinds in expected.items():
            _, seen, _ = _play(name, "gpu")
            self.assertEqual(seen, kinds, name)


@unittest.skipUnless(os.environ.get("MANIML_TEST_GPU") == "1", "GPU image comparison not requested")
class LibraryPixels(unittest.TestCase):
    """Every mode draws the same frames at the existing gate, and to the
    pixel where the arithmetic is the same (everything but the blends)."""

    @classmethod
    def setUpClass(cls):
        from maniml.web.wgpu_renderer import WgpuRenderer
        cls.driver = WgpuRenderer()

    @classmethod
    def tearDownClass(cls):
        cls.driver.close()

    def render(self, header, payload):
        return np.asarray(self.driver.render(header, payload), dtype=int)

    def test_cases_match_the_cpu_path(self):
        exact = {"rotate", "rotate_axis", "vfade", "show_creation", "uncreate", "flash"}
        for name in CASES:
            with self.subTest(case=name):
                _, _, reference = _play(name, "off", render=self.render)
                for mode in ("shadow", "gpu"):
                    _, _, frames = _play(name, mode, render=self.render)
                    for alpha, frame, expected in zip(ALPHAS, frames, reference):
                        diff = np.abs(frame - expected)
                        self.assertLessEqual((diff.max(axis=2) > 24).mean(), .005, (name, mode, alpha))
                        if name in exact:
                            self.assertLessEqual(diff.max(), 1, (name, mode, alpha))


if __name__ == "__main__":
    unittest.main()

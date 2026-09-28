"""B3b (docs/phase_b3_plan.md): the affine, paint and partial programs;
their animations under MANIML_PROGRAMS; composition with CPU writes; and,
with MANIML_TEST_GPU=1, pixels against the CPU path at several alphas.
B5.3 (docs/phase_b4_plan.md): the same under MANIML_PROGRAMS=strokes on
Phase A, where only a path without fill is a program."""

import importlib.util
import os
import unittest
from unittest.mock import patch

import numpy as np

from maniml.animation.creation import DrawBorderThenFill, ShowCreation, Uncreate, Write
from maniml.animation.fading import FadeIn, FadeOut, VFadeIn, VFadeOut
from maniml.animation.indication import ShowPassingFlash
from maniml.animation.rotation import Rotate, Rotating
from maniml.animation.transform import Transform
from maniml.constants import BLUE, DOWN, GREEN, RED, RIGHT, UP, YELLOW
from maniml.mobject.functions import FunctionGraph
from maniml.mobject.geometry import Circle, DashedLine, Line, Square
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
PHASE_A = dict(MANIML_FILL="meshes", MANIML_BORDER_GENERATOR="gpu", MANIML_SURFACE="grids")


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


def _strokes():
    """Paths without fill, as an episode's axes, curves and dashed lines
    are, beside a filled square and a word, whose animations keep the CPU
    path under MANIML_PROGRAMS=strokes (docs/phase_b4_plan.md, B5.3)."""
    axes = VGroup(Line([-4, -2.5, 0], [4, -2.5, 0], stroke_width=3),
                  Line([-4, -2.5, 0], [-4, 2, 0], stroke_width=3),
                  *(Line([x, -2.65, 0], [x, -2.35, 0], stroke_width=2) for x in (-2, 0, 2)))
    curve = FunctionGraph(lambda x: .3 * x * x - 1.5, x_range=(-2.5, 2.5, .25), color=YELLOW, stroke_width=5)
    dashed = DashedLine([-3.5, 1.4, 0], [2, 1.4, 0], color=BLUE).set_opacity(.5)
    ring = Circle(radius=.8, stroke_color=RED, stroke_width=6).shift([2.8, -.4, 0])
    square = Square(side_length=1.2, fill_color=GREEN, fill_opacity=.9, stroke_color=BLUE, stroke_width=6,
                    fill_border_width=3).shift([-2.6, .2, 0])
    word = Text("stroke", font_size=40, color=YELLOW).shift([0, 2.5, 0])
    return VGroup(axes, curve, dashed, ring, square, word)


# The stroke-only cases (every animated member a path without fill), then
# ones that mix in filled members, which keep the CPU path. A gradient
# writes the fill colours too, unseen, which a stroke's program never reads.
# Two animations of one member in a play keep the CPU path (programs.admits):
# a program recorded after the other's write would hide it.
STROKE_CASES = {
    "create": lambda g: [ShowCreation(VGroup(g[0], g[1], g[2]))],
    "uncreate": lambda g: [Uncreate(g[1])],
    "vfade": lambda g: [VFadeIn(g[3]), VFadeOut(g[2])],
    "rotate": lambda g: [Rotate(VGroup(g[3], g[2]), angle=2.0), Rotating(g[1], angle=1.0, axis=UP)],
    "transform": lambda g: [Transform(g[1], FunctionGraph(lambda x: 1 - .2 * x * x, x_range=(-3, 2, .25),
                                                          color=BLUE, stroke_width=3)),
                            FadeIn(g[2], shift=DOWN), FadeOut(g[0])],
    "write": lambda g: [Write(g[3]), DrawBorderThenFill(g[1])],
    "flash": lambda g: [ShowPassingFlash(g[3].copy().set_stroke(YELLOW, 8), time_width=.5)],
    "gradient": lambda g: [ShowCreation(g[1].set_stroke(width=[2, 10, 3]).set_color([RED, YELLOW, GREEN])),
                           VFadeIn(g[3].set_color([RED, BLUE]))],
    "fade_create": lambda g: [VFadeIn(g[1]), ShowCreation(g[1])],
}
MIXED_CASES = {
    "create_mixed": lambda g: [ShowCreation(VGroup(g[0], g[4])), FadeIn(g[5])],
    "rotate_mixed": lambda g: [Rotate(VGroup(g[3], g[4]), angle=1.5), VFadeOut(g[5])],
    "transform_mixed": lambda g: [Transform(VGroup(g[1], g[4]), VGroup(g[1].copy().shift(UP), g[4].copy().shift(DOWN)))],
    "write_mixed": lambda g: [Write(VGroup(g[1], g[4], g[5]))],
    "draw_mixed": lambda g: [DrawBorderThenFill(VGroup(g[1], g[4]), lag_ratio=.3)],
    "fill_create": lambda g: [Transform(g[3], g[3].copy().set_fill(BLUE, 1)), ShowCreation(g[3])],
}
STROKE_ALPHAS = (0.0, .07, .19, .3, .42, .5, .63, .77, .91, 1.0)


def _state(mobject):
    """What the ledger compares, plus the derived-column flags."""
    return [([sm._data[k].tobytes() for k in sm._data.dtype.names if k not in DERIVED_DATA_KEYS],
             sorted((k, np.asarray(v).tobytes()) for k, v in sm.uniforms.items()),
             sm.needs_new_unit_normal, sm.needs_new_joint_angles) for sm in mobject.get_family()]


def _play(name, mode, frames=None, render=None, *, cases=CASES, shapes=_shapes, env=PHASE_B, alphas=ALPHAS,
          interpolated=None, inspect=None):
    """Run a case under a mode; ``render(header, payload)`` per frame when
    given, ``interpolated(group)`` after each frame's interpolation and
    ``inspect(group, header)`` after its serialization too."""
    with patch.dict(os.environ, **env, MANIML_PROGRAMS=mode):
        group = shapes()
        anims = cases[name](group)
        # A case's own mobject is drawn beside the group unless it only
        # gathers the group's members.
        drawn = set(map(id, group.get_family()))
        extra = [a.mobject for a in anims if not drawn.issuperset(map(id, a.mobject.family_members_with_points()))]
        scene, wire = build_scene(group, *extra, resolution=(480, 270), samples=4), GeometryCache()
        for anim in anims:
            anim.begin()
        kinds, out = set(), []
        for alpha in alphas:
            for anim in anims:
                anim.interpolate(alpha)
            if interpolated is not None:
                interpolated(group)
            header, payload = parse_geometry_message(serialize_scene(scene, wire, renderer="triangles"))
            kinds.update(b["program"]["kind"] for b in header["batches"] if "program" in b)
            if inspect is not None:
                inspect(group, header)
            if render is not None:
                out.append(render(header, payload))
        for anim in anims:
            anim.finish()
        return _state(group), kinds, out


def _play_strokes(name, mode, render=None, **hooks):
    """A stroke or mixed case on Phase A (B5.3), at ten alphas."""
    return _play(name, mode, render=render, cases={**STROKE_CASES, **MIXED_CASES}, shapes=_strokes, env=PHASE_A,
                 alphas=STROKE_ALPHAS, **hooks)


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

    def test_a_second_writer_keeps_the_cpu_path(self):
        # Two animations of one member in a play, whichever runs first: a
        # program recorded after the other's write would be drawn from its
        # own sources' rows and hide that write (a fill, an opacity), so
        # once the member is not as the animation left it the frame is
        # the CPU's (programs.admits), with the same rows as programs off.
        plays = (lambda ring: [Transform(ring, ring.copy().set_fill(BLUE, 1)), ShowCreation(ring)],
                 lambda ring: [ShowCreation(ring), Transform(ring, ring.copy().set_fill(BLUE, 1))],
                 lambda ring: [VFadeIn(ring), ShowCreation(ring)],
                 lambda ring: [ShowCreation(ring), VFadeIn(ring)],
                 lambda ring: [Transform(ring, ring.copy().shift(UP)), Rotate(ring, angle=1.0)])

        def frames(play, mode, env):
            with patch.dict(os.environ, **env, MANIML_PROGRAMS=mode):
                ring = Circle(radius=1.2, stroke_color=RED, stroke_width=6)
                anims = play(ring)
                for anim in anims:
                    anim.begin()
                seen = []
                for alpha in ALPHAS:
                    for anim in anims:
                        anim.interpolate(alpha)
                    seen.append(("_program" in ring.__dict__, _state(ring)))
                for anim in anims:
                    anim.finish()
                return seen

        for index, play in enumerate(plays):
            off = frames(play, "off", PHASE_B)
            for mode, env in (("gpu", PHASE_B), ("strokes", PHASE_A)):
                with self.subTest(play=index, mode=mode):
                    self.assertEqual(frames(play, mode, env), off)

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


# What a stroke case sends on Phase A under strokes: the stroke-only cases
# their programs; the mixed ones only their paths without fill's (a Rotate
# is all or nothing, so one of a filled member is the CPU's whole); a
# member two animations write, nothing.
STROKE_KINDS = {"create": {"partial"}, "uncreate": {"partial"}, "vfade": {"paint"}, "rotate": {"affine"},
                "transform": {"blend"}, "write": {"partial", "blend"}, "flash": {"partial"},
                "gradient": {"partial", "paint"}, "fade_create": set(),
                "create_mixed": {"partial"}, "rotate_mixed": set(), "transform_mixed": {"blend"},
                "write_mixed": {"partial", "blend"}, "draw_mixed": {"partial", "blend"}, "fill_create": set()}
# The cases whose frames are held to the gate alone: a lagged write's
# partial path ends mid-curve at sub-alphas where the partial kernel's
# float32 tip lands a pixel or two away from the CPU's float64 one (12/255
# on two pixels at most here; 17 under Phase B, whose partial it is).
STROKE_TIPS = {"write_mixed", "draw_mixed"}
# Write's index transition writes the outline's rows over the border
# phase's program (set_data), a read once per member, as under Phase B.
STROKE_WRITES = {"write", "write_mixed", "draw_mixed"}


def _filled(mobject):
    return mobject.has_points() and bool(np.any(mobject._data["fill_rgba"][:, 3]))


@unittest.skipUnless(HAVE_LYON, "the Lyon helper is the frame preparer's tessellator")
class StrokePrograms(unittest.TestCase):
    """B5.3 (docs/phase_b4_plan.md): MANIML_PROGRAMS=strokes on Phase A. A
    path without fill is a program, drawn as a stroke from its finalized
    rows; a filled member's animation is the CPU path's, frame by frame."""

    def test_the_switch_needs_no_patch_fill(self):
        scene = build_scene(Square(), Circle(fill_opacity=.5))
        with patch.dict(os.environ, **PHASE_A, MANIML_PROGRAMS="strokes"):
            self.assertEqual(programs.mode(), "strokes")
            self.assertTrue(programs.deferred(programs.mode()))
            serialize_scene(scene, GeometryCache(), renderer="triangles")
        for mode in ("shadow", "gpu"):
            with patch.dict(os.environ, **PHASE_A, MANIML_PROGRAMS=mode), self.assertRaises(ValueError):
                serialize_scene(scene, GeometryCache(), renderer="triangles")
        with patch.dict(os.environ, **PHASE_B, MANIML_PROGRAMS="strokes"):
            serialize_scene(scene, GeometryCache(), renderer="triangles")

    def test_every_case_ends_in_the_cpu_paths_state(self):
        for name, kinds in STROKE_KINDS.items():
            with self.subTest(case=name):
                off, off_kinds, _ = _play_strokes(name, "off")
                self.assertEqual(off_kinds, set())
                state, seen, _ = _play_strokes(name, "strokes")
                self.assertEqual(state, off)
                self.assertEqual(seen, kinds)

    def test_only_paths_without_fill_are_programs(self):
        def inspect(group, header):
            pipelines = [batch["pipeline"] for batch in header["batches"]]
            self.assertNotIn("patch", pipelines)
            self.assertTrue(all(batch["pipeline"] == "stroke" for batch in header["batches"] if "program" in batch))
            self.assertFalse(any(sm._program is not None for sm in group.get_family() if _filled(sm)))

        for name in STROKE_KINDS:
            with self.subTest(case=name):
                _play_strokes(name, "strokes", inspect=inspect)

    def test_a_filled_members_frames_are_the_cpu_paths(self):
        # Exactly as with programs off: the same rows, derived columns and
        # refresh flags included, and the same uniforms, at every frame, as
        # the animation leaves them and as the frame's reads leave them (an
        # endpoint freshened for a program it cannot record would show in
        # the first).
        def frames(mode):
            seen = []

            def record(group, header=None):
                seen.append([(sm._data.tobytes(), sm.needs_new_joint_angles, sm.needs_new_unit_normal,
                              sorted((k, np.asarray(v).tobytes()) for k, v in sm.uniforms.items()))
                             for sm in group.get_family() if _filled(sm)])
            _play_strokes(name, mode, interpolated=record, inspect=record)
            return seen

        for name in MIXED_CASES:
            with self.subTest(case=name):
                off = frames("off")
                self.assertTrue(all(off))
                self.assertEqual(frames("strokes"), off)

    def test_stroke_frames_read_no_rows(self):
        # But a write's (STROKE_WRITES). The play's end reads them all
        # (finish).
        original = Mobject._materialize_program
        for name in STROKE_KINDS.keys() - STROKE_WRITES:
            with self.subTest(case=name):
                reads, seen = [], []
                with patch.object(Mobject, "_materialize_program", lambda mobject: (reads.append(mobject),
                                                                                    original(mobject))):
                    _play_strokes(name, "strokes", inspect=lambda group, header: seen.append(len(reads)))
                self.assertEqual(seen[-1], 0)

    def test_a_stream_sends_a_programs_scalars(self):
        # Format 8 (docs/phase_b4_plan.md, B4.8): past a play's first frame
        # a program run that holds its place is a scalars op.
        with patch.dict(os.environ, **PHASE_A, MANIML_PROGRAMS="strokes"):
            group = _strokes()
            scene, wire = build_scene(group, resolution=(480, 270), samples=4), GeometryCache()
            wire.negotiate(True)
            anims = MIXED_CASES["create_mixed"](group) + STROKE_CASES["vfade"](group)
            for anim in anims:
                anim.begin()
            headers = []
            for alpha in (.2, .4, .6):
                for anim in anims:
                    anim.interpolate(alpha)
                headers.append(parse_geometry_message(serialize_scene(scene, wire, renderer="triangles"))[0])
            for anim in anims:
                anim.finish()
        self.assertTrue(any("program" in batch for batch in headers[0]["batches"]))
        for header in headers[1:]:
            # The members the lag has not reached, or has finished, hold
            # their scalars; the square's CPU path is spliced.
            self.assertTrue(header["scalars"])
            self.assertTrue(header["splices"])
            self.assertFalse(any("program" in batch for _, _, batches in header["splices"] for batch in batches))


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

    def test_stroke_cases_match_the_cpu_path_on_phase_a(self):
        # B5.3 (docs/phase_b4_plan.md): strokes on Phase A, at ten alphas,
        # against programs off: the gate, and but for a lagged write's tips
        # (STROKE_TIPS) to the pixel, blends included (a stroke's blend
        # moves its points by float32 rounding at most). The cases two
        # animations write are exact: nothing there is a program.
        for name in STROKE_KINDS:
            with self.subTest(case=name):
                _, _, reference = _play_strokes(name, "off", render=self.render)
                _, kinds, frames = _play_strokes(name, "strokes", render=self.render)
                self.assertEqual(kinds, STROKE_KINDS[name])
                for alpha, frame, expected in zip(STROKE_ALPHAS, frames, reference):
                    diff = np.abs(frame - expected)
                    self.assertLessEqual((diff.max(axis=2) > 24).mean(), .005, (name, alpha))
                    if name not in STROKE_TIPS:
                        self.assertLessEqual(diff.max(), 1, (name, alpha))


if __name__ == "__main__":
    unittest.main()

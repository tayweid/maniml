"""The retained frame's unchanged frames (docs/phase_b4_plan.md, "Phase B
as the default", B5.10): the last frame's runs taken again without
walking coalesce_draws, and an idle frame's message returned as the last
encode left it, held to the whole-frame path's bytes and cache by the
golden pin's Lockstep. In a module of its own, so the pin's stays as it
was recorded."""

import os
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from maniml.constants import BLUE, DOWN, GREEN, RED, RIGHT, UP, YELLOW
from maniml.mobject.geometry import Square
from maniml.mobject.three_dimensions import Sphere
from maniml.utils import programs
from maniml.web import generated_geometry
from maniml.web.geometry import parse_geometry_message
from tests.renderer_fixtures import build_scene
from tests.test_retained_frame import RENDERERS, GoldenCase, Lockstep, requires_lyon, tick, updater_scene


@requires_lyon
class UnchangedFrames(GoldenCase):
    def setUp(self):
        self.enterContext(patch.object(generated_geometry, "_TEXTURE_BY_HASH", {}))
        self.addCleanup(programs.set_override, None)

    def test_an_unchanged_frame_reuses_its_runs_and_its_message(self):
        # B5.10: a frame whose draws are the last frame's, the same objects
        # in the same order under the same camera, takes the last frame's
        # runs without walking coalesce_draws; and once a message carried
        # every run, the same frame again returns that message untouched (a
        # full frame's same bytes, a stream's nothing) without encoding.
        # The flag-off bytes and the flag-off cache all along, through
        # stills, a client's connect, a pan, a tick that moves two leaves
        # and the stills after each, in both formats.
        for deltas in (False, True):
            for renderer in RENDERERS:
                with self.subTest(renderer=renderer, deltas=deltas):
                    lock = Lockstep(self, updater_scene, deltas=deltas)
                    lock.frame("cold", renderer)
                    self.assertFalse(lock.retained.stats["runs_reused"])
                    lock.frame("still", renderer)
                    self.assertTrue(lock.retained.stats["runs_reused"])
                    idle = lock.retained._idle
                    self.assertIsNotNone(idle, "a frame that carried every run")
                    for index in range(3):
                        lock.frame(f"still {index}", renderer)
                        self.assertIs(lock.retained._idle, idle, "the message returned as it was")
                        lock.expect(batches_encoded=0, runs_reused=True)
                    for cache in lock.caches:
                        cache.reset()
                    lock.frame("a client connects", renderer)
                    self.assertIsNone(lock.retained._idle, "every run sent again")
                    lock.frame("still", renderer)
                    self.assertIsNotNone(lock.retained._idle)
                    lock.step(lambda side: side.scene.camera.frame.shift(.2 * RIGHT))
                    lock.frame("pan", renderer)
                    self.assertFalse(lock.retained.stats["runs_reused"])
                    lock.frame("still after the pan", renderer)
                    self.assertTrue(lock.retained.stats["runs_reused"])
                    lock.step(tick)
                    lock.frame("tick", renderer)
                    self.assertFalse(lock.retained.stats["runs_reused"], "two leaves moved")
                    for index in range(3):
                        lock.frame(f"still after the tick {index}", renderer)
                        lock.expect(runs_reused=True, batches_encoded=0)



class UnchangedFramesFromRows(UnchangedFrames):
    """The same with Phase B's patch fills and strokes sent as rows."""

    def setUp(self):
        super().setUp()
        self.enterContext(patch.dict(os.environ, MANIML_PATCH_SOURCE="rows"))


def net_runs_scene():
    """test_retained_frame's orbs_scene without its textured sphere (a
    frame that sends texture payloads is never idle): spheres whose nets
    share a draw, as runs of nets, and a square."""
    colors = (BLUE, RED, GREEN, YELLOW)
    spheres = [Sphere(radius=.3, color=colors[index % 4], resolution=(9, 7)).move_to([index * .8 - 3, .4, 0])
               for index in range(6)]
    small = [Sphere(radius=.15, color=colors[index % 4], resolution=(7, 5)).move_to([index * .5 - 1, -1, 0])
             for index in range(4)]
    square = Square(side_length=.5, fill_color=YELLOW, fill_opacity=1, stroke_width=0).shift(2 * UP)
    return SimpleNamespace(scene=build_scene(*spheres, *small, square), spheres=spheres)


@requires_lyon
class UnchangedNetRuns(GoldenCase):
    """The same paths on frames holding runs of nets (MANIML_NET_RUNS=1,
    the default the Default and Phase B ship; rows the patch source), and
    through what replaces the cache's state or the retained frame's under
    them: a renegotiation of the format and back, a restart, a zoom and
    the zoom back, and renderer switches on one cache. After each, the
    stills settle into the idle message again, the flag-off bytes and
    cache all along."""

    def setUp(self):
        self.enterContext(patch.object(generated_geometry, "_TEXTURE_BY_HASH", {}))
        self.enterContext(patch.dict(os.environ, MANIML_NET_RUNS="1", MANIML_PATCH_SOURCE="rows"))
        self.addCleanup(programs.set_override, None)

    def settles(self, lock, label, renderer):
        """Three stills after ``label``: from the second on, the same idle
        message, returned without encoding."""
        lock.frame(f"still after {label}", renderer)
        lock.frame(f"still after {label}", renderer)
        idle = lock.retained._idle
        self.assertIsNotNone(idle, f"idle after {label} ({renderer})")
        lock.frame(f"still after {label}", renderer)
        self.assertIs(lock.retained._idle, idle, f"the message returned as it was after {label} ({renderer})")
        lock.expect(batches_encoded=0, runs_reused=True)

    def test_an_idle_frame_of_net_runs(self):
        def zoom(factor):
            def step(side):
                side.scene.camera.frame.scale(factor)
                side.scene.camera.refresh_uniforms()
            return step

        for deltas in (False, True):
            for renderer in (*RENDERERS, "triangles"):
                with self.subTest(renderer=renderer, deltas=deltas):
                    lock = Lockstep(self, net_runs_scene, deltas=deltas)
                    cold = lock.frame("cold", renderer)
                    if not deltas:
                        # Phase A forced draws its surfaces as grids; the
                        # Default and Phase B as nets, in runs.
                        header = parse_geometry_message(cold)[0]
                        runs = [len(batch["net"]) for batch in header["batches"] if isinstance(batch.get("net"), list)]
                        self.assertEqual(any(count > 1 for count in runs), renderer != "phase_a", runs)
                    self.settles(lock, "the cold frame", renderer)
                    for cache in lock.caches:
                        cache.negotiate(not deltas)
                    lock.frame("renegotiated", renderer)
                    self.settles(lock, "the renegotiation", renderer)
                    for cache in lock.caches:
                        cache.negotiate(deltas)
                    lock.frame("renegotiated back", renderer)
                    self.settles(lock, "the renegotiation back", renderer)
                    for cache in lock.caches:
                        cache.restart()
                    lock.frame("restart", renderer)
                    self.settles(lock, "the restart", renderer)
                    lock.step(zoom(1.1))
                    lock.frame("zoom", renderer)
                    self.assertFalse(lock.retained.stats["runs_reused"], "the camera moved")
                    self.settles(lock, "the zoom", renderer)
                    lock.step(zoom(1 / 1.1))
                    lock.frame("zoom back", renderer)
                    self.settles(lock, "the zoom back", renderer)
                    lock.step(lambda side: side.spheres[2].shift(.1 * DOWN))
                    lock.frame("a member moved", renderer)
                    self.assertFalse(lock.retained.stats["runs_reused"], "a member of a run moved")
                    self.settles(lock, "the move", renderer)

    def test_renderer_switches_on_one_cache(self):
        for deltas in (False, True):
            with self.subTest(deltas=deltas):
                lock = Lockstep(self, net_runs_scene, deltas=deltas)
                for renderer in ("phase_a", "phase_b", "phase_a", "triangles", "phase_b", "triangles"):
                    lock.frame(f"switched to {renderer}", renderer)
                    self.settles(lock, f"the switch to {renderer}", renderer)


if __name__ == "__main__":
    unittest.main()

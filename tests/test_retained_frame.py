"""The golden pin of Phase B4 (docs/phase_b4_plan.md, B4.0).

blake2b digests of ``serialize_scene``'s message bytes, frame by frame
through one persistent GeometryCache per case and renderer, for
``renderer="triangles"`` (Phase A) and ``"phase_b"``, over the renderer
fixtures, the quality fixtures, scripted synthetic sequences and frames
of the two course episodes, asserted against the recorded files in
tests/goldens/retained_frame/. They are the contract every increment of
the retained frame holds: with MANIML_RETAINED_FRAME unset the bytes may
not move, and with it set they are the flag-off bytes.

The synthetic cases carry what the per-record loop must preserve, since
they run everywhere (CI has no episodes): CE's z_index order within a
family and the render-group rejoin across a fixed-in-frame overlay,
fixed-frame groups last, runs and their output cap, a run's uniforms as
its first member spells them (``1`` and ``1.0`` are equal and print
differently), texture payloads and their resend after a reset,
reservations a zoom grows and the zoom back keeps, leaves skipped for
having no points, uniforms that move with no row, and program draws.

Record with ``python -m tests.test_retained_frame --record`` (or
MANIML_RECORD_GOLDENS=1 under any unittest invocation); only the cases
that ran are rewritten. A golden may move only for a reason the commit
that re-records it names. The episode cases skip when the econ-0100
checkout is absent; the TeX quality cases skip when TeX is absent or its
glyphs differ from the recording's.
"""

from contextlib import contextmanager, redirect_stderr, redirect_stdout
import gc
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image

from maniml import config
from maniml.animation.animation import prepare_animation
from maniml.constants import BLUE, DEFAULT_RESOLUTION, DOWN, GREEN, LEFT, RED, RIGHT, UL, UP, WHITE, YELLOW
from maniml.mobject.geometry import Annulus, Circle, Rectangle, Square
from maniml.mobject.three_dimensions import Sphere
from maniml.mobject.types.dot_cloud import DotCloud
from maniml.mobject.types.image_mobject import ImageMobject
from maniml.mobject.types.surface import TexturedSurface
from maniml.mobject.types.vectorized_mobject import VGroup, VMobject
from maniml.scene.scene import Scene
from maniml.utils import programs
from maniml.web import triangle_scene
from maniml.web.geometry import GEOMETRY_FORMAT_VERSION, GeometryCache, parse_geometry_message, serialize_scene
from maniml.web.triangle_geometry import _packaged_library
from tests.renderer_fixtures import build_scene, renderer_cases
from tests.renderer_quality_fixtures import QualityFixtureUnavailable, quality_cases

GOLDEN_DIR = Path(__file__).resolve().parent / "goldens" / "retained_frame"
RECORD_ENV = "MANIML_RECORD_GOLDENS"
RENDERERS = ("triangles", "phase_b")
# The Phase B switches and the cache policy select other bytes on purpose;
# the pin is the default configuration. MANIML_RETAINED_FRAME and
# MANIML_VERIFY_LEDGER stay as the run has them: neither may change a byte.
PINNED_ENV = ("MANIML_BORDER_GENERATOR", "MANIML_FILL", "MANIML_SURFACE", "MANIML_PROGRAMS",
              "MANIML_RENDER_CACHE", "MANIML_RENDERER")
# The course episodes the plan's gates are measured on, with the checkpoint
# each gate names: EpisodeB2's 8.a and PriceDiscovery's 3.a.4.
EPISODES_ROOT = Path(os.environ.get("MANIML_EPISODES", Path.home() / "Projects" / "econ-0100"))
EPISODES = {
    "EpisodeB2": ("Blocks/B2_Supply/03_Code.py", 307),
    "PriceDiscovery": ("Blocks/B3_Equilibrium/Animate.py", 63),
}
# A run's output cap as the run-cap case lowers it: two or three of its
# discs' worth of border output under either renderer, so its row of eight
# splits into several runs. The real cap (128 MiB) no test scene reaches.
RUN_CAP_BYTES = 40_000


def play_frames(count):
    """Ten frames spread evenly over a play of ``count`` frames, first and
    last included (fewer when the play is shorter): the movers appear on
    the first, the landing state is the last."""
    return sorted({round(k * (count - 1) / 9) for k in range(10)})

requires_lyon = unittest.skipUnless(os.environ.get("MANIML_LYON_LIBRARY") or _packaged_library(),
                                    "Lyon helper is neither packaged nor explicitly built")


def recording():
    return os.environ.get(RECORD_ENV) == "1"


@contextmanager
def camera_config(resolution):
    """``resolution`` as the CE config's pixel resolution, which the
    camera frame's shape follows, for the block; after it, the camera
    settings as they were before, the background and frame rate among
    them: an episode's style module sets all three as it is imported, and
    every later test in the process would build its scenes under them."""
    held = (config.pixel_width, config.pixel_height, config.background_color, config.frame_rate)
    config.pixel_width, config.pixel_height = resolution
    try:
        yield
    finally:
        config.pixel_width, config.pixel_height, config.background_color, config.frame_rate = held


def frame_contract():
    """What the camera frame's uniforms are a function of beyond the scene:
    part of every case's input."""
    return [config.pixel_width, config.pixel_height, config.frame_height]


class Pin:
    """One case's history: a GeometryCache per renderer that lives across
    the case's frames, as the viewer's does, and the digest of every
    frame's bytes in the order they were produced."""

    def __init__(self):
        self.caches = {renderer: GeometryCache() for renderer in RENDERERS}
        self.frames = {}

    def frame(self, scene, name):
        label = f"{len(self.frames):02d} {name}"
        self.frames[label] = {
            renderer: hashlib.blake2b(serialize_scene(scene, cache, renderer=renderer),
                                      digest_size=16).hexdigest()
            for renderer, cache in self.caches.items()}
        return label

    def reset(self):
        # What a client's connect does to the viewer's cache: the next
        # message ships every batch in full.
        for cache in self.caches.values():
            cache.reset()


def play(pin, scene, *animations, name, alphas=(.25, .5, .75)):
    """Drive ``animations`` through a play's life by hand, a frame pinned
    at its start, at each of ``alphas`` and at its landing: the frames a
    viewer is sent mid-play, without a scene loop behind them."""
    animations = [prepare_animation(animation) for animation in animations]
    for animation in animations:
        animation.begin()
    pin.frame(scene, f"{name} begins")
    for alpha in alphas:
        for animation in animations:
            animation.interpolate(alpha)
        pin.frame(scene, f"{name} at {alpha}")
    for animation in animations:
        animation.finish()
    pin.frame(scene, f"{name} lands")


def batch_counts(scene):
    """Batches per renderer in a cold frame of ``scene``."""
    return {renderer: len(parse_geometry_message(serialize_scene(scene, GeometryCache(),
                                                                 renderer=renderer))[0]["batches"])
            for renderer in RENDERERS}


def differences(recorded, fresh):
    lines = []
    for label in sorted(set(recorded) | set(fresh)):
        if label not in fresh:
            lines.append(f"{label}: recorded, not produced")
        elif label not in recorded:
            lines.append(f"{label}: produced, not recorded")
        else:
            for renderer in RENDERERS:
                if recorded[label].get(renderer) != fresh[label].get(renderer):
                    lines.append(f"{label} {renderer}: recorded {recorded[label].get(renderer)} "
                                 f"now {fresh[label].get(renderer)}")
    return lines


class GoldenFile:
    """One JSON file of the pin: ``cases`` keyed by case name, each with
    its frames' digests and the ``input`` its bytes are a function of
    beyond the serializer (the frame contract, a source digest): a changed
    input makes the case incomparable, not wrong."""

    def __init__(self, name):
        self.path = GOLDEN_DIR / f"{name}.json"
        self.cases = json.loads(self.path.read_text())["cases"] if self.path.exists() else {}

    def check(self, test, case, pin, *, input):
        if recording():
            self.record(case, {"input": input, "frames": pin.frames})
            return
        recorded = self.cases.get(case)
        if recorded is None:
            test.fail(f"no golden for {case!r} in {self.path.name}; record it with "
                      f"python -m tests.test_retained_frame --record")
        if recorded["input"] != input:
            test.skipTest(f"{case!r}'s source differs from the recording's "
                          f"({recorded['input']} vs {input}); the golden cannot be compared here")
        moved = differences(recorded["frames"], pin.frames)
        test.assertEqual(moved, [], f"{case!r} bytes moved from {self.path.name}:\n  " + "\n  ".join(moved))

    def record(self, case, entry):
        # Reread first: several tests share a file, each with its own
        # GoldenFile read when it began.
        self.cases = json.loads(self.path.read_text())["cases"] if self.path.exists() else {}
        self.cases[case] = entry
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({
            "format_version": GEOMETRY_FORMAT_VERSION,
            "recorded_with": "python -m tests.test_retained_frame --record",
            "cases": self.cases,
        }, indent=1, sort_keys=True) + "\n")


class GoldenCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.enterClassContext(patch.dict(os.environ))
        for name in PINNED_ENV:
            os.environ.pop(name, None)
        # An episode sets the CE config for itself (EpisodeB2 is 2:1, both
        # are 60 fps on #212121) and the process keeps it, so every class
        # starts from the import-time default resolution the fixtures were
        # recorded under, and hands the config back as it found it, even
        # when its setUpClass fails after this.
        cls.enterClassContext(camera_config(DEFAULT_RESOLUTION))

    def camera_moves(self, scene, pin):
        """The camera-only frames every fixture gets after its cold frame
        and one still: a pan reuses everything, a zoom out changes the
        stroke counts, and the zoom back finds the border reservations
        kept."""
        pin.frame(scene, "still")
        scene.camera.frame.shift(.05 * RIGHT)
        pin.frame(scene, "pan")
        scene.camera.frame.scale(1.1)
        pin.frame(scene, "zoom out")
        scene.camera.frame.scale(1 / 1.1)
        pin.frame(scene, "zoom back")


@requires_lyon
class FixtureGoldens(GoldenCase):
    def test_renderer_fixtures(self):
        golden = GoldenFile("renderer_fixtures")
        for case in renderer_cases():
            with self.subTest(fixture=case.name):
                scene, pin = case.build(), Pin()
                pin.frame(scene, "cold")
                self.camera_moves(scene, pin)
                golden.check(self, case.name, pin, input={"frame": frame_contract()})

    def test_quality_fixtures(self):
        golden = GoldenFile("quality_fixtures")
        for case in quality_cases():
            with self.subTest(fixture=case.name):
                try:
                    frame = case.build()
                except QualityFixtureUnavailable as exc:
                    self.skipTest(str(exc))
                pin = Pin()
                pin.frame(frame.scene, "cold")
                self.camera_moves(frame.scene, pin)
                # TeX glyphs are the installation's; the source digest says
                # whether this machine built the recording's paths.
                golden.check(self, case.name, pin,
                             input={"frame": frame_contract(), "source": frame.metadata["source_sha256"]})


def synthetic_scene():
    """A family of three, a stroke-only path, a dot cloud, a surface and a
    cloud with no points: every pipeline the serializer emits, a leaf it
    skips, and the family the sequence's z_index, shift and stroke_behind
    steps act on."""
    box = Square(side_length=1.6, fill_color=RED, fill_opacity=.6,
                 stroke_color=BLUE, stroke_width=6).shift(1.8 * LEFT)
    disc = Circle(radius=.7, fill_color=GREEN, fill_opacity=.8, stroke_width=0, fill_border_width=2)
    ring = Annulus(inner_radius=.3, outer_radius=.6, fill_opacity=1, stroke_width=0).shift(1.8 * RIGHT)
    family = VGroup(box, disc, ring)
    path = VMobject(stroke_color=YELLOW, stroke_width=4, fill_opacity=0)
    path.set_points_as_corners([[-2.5, -1.5, 0], [-1, -.8, 0], [1, -1.6, 0], [2.5, -.9, 0]])
    cloud = DotCloud(np.array([[-2, 1.4, 0], [-1, 1.5, 0], [0, 1.4, 0], [1, 1.5, 0], [2, 1.4, 0]]))
    globe = Sphere(radius=.45, resolution=(7, 7)).shift(2.6 * RIGHT + 1.2 * UP)
    nothing = DotCloud(np.zeros((0, 3)))
    return build_scene(family, path, cloud, globe, nothing), family, path, cloud, globe


@requires_lyon
class SyntheticGoldens(GoldenCase):
    def test_scripted_sequence(self):
        scene, family, path, cloud, globe = synthetic_scene()
        box, disc, _ = family
        pin = Pin()
        pin.frame(scene, "cold")
        for _ in range(3):
            pin.frame(scene, "still")
        extra = Square(side_length=.8, fill_color=YELLOW, fill_opacity=1, stroke_width=0).shift(2.4 * UP)
        scene.mobjects.append(extra)
        scene.render_groups[0].add(extra)
        pin.frame(scene, "add a square")
        scene.mobjects.remove(path)
        scene.render_groups[0].remove(path)
        pin.frame(scene, "remove the path")
        disc.z_index = 5
        pin.frame(scene, "child z_index 5")
        disc.z_index = 0
        pin.frame(scene, "child z_index 0")
        family.shift(.3 * UP)
        pin.frame(scene, "shift the family")
        box.set_stroke(behind=True)
        pin.frame(scene, "stroke behind")
        pin.frame(scene, "still")
        box.set_stroke(behind=False)
        pin.frame(scene, "stroke in front")
        self.camera_moves(scene, pin)
        pin.reset()
        pin.frame(scene, "after a cache reset")
        pin.frame(scene, "still")
        scene.mobjects.append(path)
        scene.render_groups[0].add(path)
        pin.frame(scene, "re-add the path")
        dots = cloud.get_points().copy()
        cloud.clear_points()
        pin.frame(scene, "empty the cloud")
        cloud.set_points(dots)
        pin.frame(scene, "refill the cloud")
        # A zoom in outgrows the border and net reservations (the net's
        # only past 3x); the zoom back keeps them grown.
        scene.camera.frame.scale(1 / 6)
        pin.frame(scene, "zoom in 6x")
        scene.camera.frame.scale(6)
        pin.frame(scene, "zoom back")
        # Plays that move only uniforms: every row locked, the uniforms
        # lerped frame by frame.
        play(pin, scene, box.animate.set_anti_alias_width(6), globe.animate.set_shading(.6, .2, .4),
             name="a uniforms-only play")
        GoldenFile("synthetic").check(self, "scripted_sequence", pin, input={"frame": frame_contract()})

    def test_textured_leaves(self):
        # Texture bytes travel beside the draws, keyed by content, once per
        # connection: a still frame sends none, a reset sends them again.
        # Written as a BMP, whose bytes an encoder cannot vary; its digest
        # is the case's input all the same.
        with tempfile.TemporaryDirectory() as tmp:
            texture = Path(tmp) / "texture.bmp"
            pixels = np.zeros((8, 16, 3), dtype=np.uint8)
            pixels[..., 0] = np.arange(16) * 16
            pixels[..., 1] = (np.arange(8) * 32)[:, None]
            pixels[..., 2] = 200
            Image.fromarray(pixels, "RGB").save(texture, format="BMP")
            image = ImageMobject(str(texture), height=1.5).shift(2 * LEFT)
            globe = TexturedSurface(Sphere(radius=.8, resolution=(9, 9)), str(texture)).shift(2 * RIGHT)
            scene, pin = build_scene(image, globe), Pin()
            pin.frame(scene, "cold")
            pin.frame(scene, "still")
            image.shift(.3 * UP)
            pin.frame(scene, "move the image")
            pin.reset()
            pin.frame(scene, "after a cache reset")
            pin.frame(scene, "still")
            source = hashlib.sha256(texture.read_bytes()).hexdigest()
        GoldenFile("synthetic").check(self, "textures", pin, input={"frame": frame_contract(), "texture": source})

    def test_runs_split_at_the_output_cap(self):
        # A border or patch run reserves its largest member's capacity for
        # every curve and ends before its output would pass the cap. The
        # cap is lowered on both sides of the recording, and the case
        # fails rather than stops covering the split if it ever stops
        # splitting.
        scene = build_scene(*(Circle(radius=.35, fill_color=BLUE, fill_opacity=1, stroke_width=0,
                                     fill_border_width=2).shift((i - 3.5) * .8 * RIGHT)
                              for i in range(8)))
        whole = batch_counts(scene)
        with patch.object(triangle_scene, "MAX_RUN_OUTPUT_BYTES", RUN_CAP_BYTES):
            split = batch_counts(scene)
            pin = Pin()
            pin.frame(scene, "cold")
            self.camera_moves(scene, pin)
            scene.camera.frame.scale(1 / 3)
            pin.frame(scene, "zoom in 3x")
            scene.camera.frame.scale(3)
            pin.frame(scene, "zoom back")
        for renderer in RENDERERS:
            self.assertGreater(split[renderer], whole[renderer], f"no {renderer} run reached the cap")
        GoldenFile("synthetic").check(self, "run_cap", pin,
                                      input={"frame": frame_contract(), "cap": RUN_CAP_BYTES})


@requires_lyon
class SceneGoldens(GoldenCase):
    """A real Scene: its render groups are the _RenderBatch wrappers
    Scene.add assembles, with the batch keys the rejoin compares, which
    build_scene's single Group never has."""

    def test_render_groups(self):
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            scene = Scene(window=None)
        self.addCleanup(scene.camera.release)
        # The process's config chooses the background; the golden does not.
        scene.camera.background_rgba = [0.08, 0.11, 0.14, 1.0]
        lifted = Square(side_length=1.2, fill_color=RED, fill_opacity=1, stroke_width=0).shift(.4 * LEFT)
        lifted.z_index = 1
        a = VGroup(lifted, Circle(radius=.8, fill_color=GREEN, fill_opacity=1, stroke_color=WHITE, stroke_width=3))
        overlay = Rectangle(width=1.2, height=.5, fill_color=YELLOW, fill_opacity=.8, stroke_width=0)
        overlay.to_corner(UL).fix_in_frame()
        b = VGroup(Square(side_length=1.5, fill_color=BLUE, fill_opacity=1, stroke_width=0).shift(.5 * RIGHT))
        # Equal uniforms spelled two ways: the run's first member's
        # spelling is the one on the wire.
        spelled = VGroup(*(Square(side_length=.5, fill_color=YELLOW, fill_opacity=1, stroke_width=0)
                           .set_anti_alias_width(width).shift(x * RIGHT + 2 * DOWN)
                           for width, x in ((1.0, -.6), (1, .6))))
        # a and b share a batch key and the fixed overlay splits them: the
        # fixed group draws last, and a and b rejoin as one family, whose
        # z_index sort lifts a's square over b's.
        scene.add(a, overlay, b, spelled)
        pin = Pin()
        pin.frame(scene, "cold")
        pin.frame(scene, "still")
        scene.camera.frame.shift(.2 * RIGHT)
        pin.frame(scene, "pan under the fixed overlay")
        # A toggle after the add: the groups keep the keys they were
        # assembled with and sort by the live flag.
        overlay.unfix_from_frame()
        pin.frame(scene, "overlay unfixed")
        overlay.fix_in_frame()
        pin.frame(scene, "overlay fixed again")
        # A top-level z_index reorders only on the next add.
        b.z_index = -1
        pin.frame(scene, "b z_index -1")
        scene.add(b)
        pin.frame(scene, "b added again")
        # The viewer's Phase B records plays as GPU programs, which the
        # phase_b messages carry as program draws.
        programs.set_override("gpu")
        try:
            play(pin, scene, a.animate.shift(.3 * DOWN), name="a program play")
        finally:
            programs.set_override(None)
        pin.frame(scene, "still")
        GoldenFile("synthetic").check(self, "scene_render_groups", pin, input={"frame": frame_contract()})


class EpisodeGoldens:
    """Frames of one course episode: every pausepoint the benchmark
    measures (benchmarks.episode_frames.select_frames) restored as a
    navigation restores it, the gate's checkpoint ticked once, ten frames
    spread over the play that arrives there, and the landing after it.
    Loading builds every checkpoint of the episode, once per class. A
    mixin, so only the named episodes are collected."""

    EPISODE = None

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        relative, cls.checkpoint = EPISODES[cls.EPISODE]
        cls.path = EPISODES_ROOT / relative
        if not cls.path.exists():
            raise unittest.SkipTest(f"no econ-0100 checkout: {cls.path} is absent")
        cls.input = {"source": hashlib.sha256(cls.path.read_bytes()).hexdigest()}
        cls.golden = GoldenFile("episodes")
        recorded = cls.golden.cases.get(cls.EPISODE)
        if recorded is not None and recorded["input"] != cls.input and not recording():
            raise unittest.SkipTest(f"{cls.path.name} changed since the golden was recorded; "
                                    f"the golden cannot be compared here")
        from benchmarks.episode_frames import load_episode
        # The CLI gives every scene file its own process. Here two episodes
        # share one, and both import the course's ``style`` module, which
        # sets the CE config (the 2:1 frame) as it is imported, once per
        # process: the second episode would keep the resolution pinned
        # above. Each class loads into the import state it found and hands
        # it back, so every episode loads as the first.
        cls.sys_path, cls.modules = list(sys.path), set(sys.modules)
        cls.addClassCleanup(cls.forget_the_episode)
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            cls.scene, error = load_episode(cls.path, cls.EPISODE)
        if error is not None:
            raise RuntimeError(f"{cls.EPISODE} did not build: {error['error']}")

    @classmethod
    def forget_the_episode(cls):
        # The episode's checkpoints are a large graph; hand them back
        # before the next episode loads.
        scene = cls.__dict__.get("scene")
        if scene is not None:
            scene.camera.release()
            del cls.scene
        gc.collect()
        for name in set(sys.modules) - cls.modules:
            if Path(getattr(sys.modules[name], "__file__", None) or "/").is_relative_to(EPISODES_ROOT):
                del sys.modules[name]
        sys.path[:] = cls.sys_path

    def test_pausepoints_and_the_gate_play(self):
        from benchmarks.episode_frames import (play_before, play_frame_count, replay_play, select_frames,
                                               show_frame)
        scene, checkpoints, pin = self.scene, self.scene.animation_checkpoints, Pin()
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            for index in sorted(set(select_frames(checkpoints)) | {self.checkpoint}):
                show_frame(scene, index)
                pin.frame(scene, f"pausepoint {index}")
            show_frame(scene, self.checkpoint)
            scene.update_mobjects(1 / scene.camera.fps)
            pin.frame(scene, f"pausepoint {self.checkpoint} ticked")
            target = play_before(checkpoints, self.checkpoint)
            wanted = play_frames(play_frame_count(scene.camera.fps, checkpoints[target]["run_time"]))

            def on_frame(k):
                if k in wanted:
                    pin.frame(scene, f"play {target} frame {k}")

            replay_play(scene, target, on_frame)
            show_frame(scene, self.checkpoint)
            pin.frame(scene, f"pausepoint {self.checkpoint} after the play")
        self.assertEqual(sum(" play " in label for label in pin.frames), len(wanted),
                         "the replay delivered other frames than the play's run_time says")
        self.golden.check(self, self.EPISODE, pin, input=self.input)


@requires_lyon
class EpisodeB2Goldens(EpisodeGoldens, GoldenCase):
    EPISODE = "EpisodeB2"


@requires_lyon
class PriceDiscoveryGoldens(EpisodeGoldens, GoldenCase):
    EPISODE = "PriceDiscovery"


if __name__ == "__main__":
    if "--record" in sys.argv:
        sys.argv.remove("--record")
        os.environ[RECORD_ENV] = "1"
    unittest.main()

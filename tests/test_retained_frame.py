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

RetainedFrameLockstep (B4.2) holds the retained frame to the flag-off path
directly, wherever the goldens cannot reach: one scripted history driven on
two scenes built alike, one serialized with MANIML_RETAINED_FRAME=1, equal
messages and equal cache contents asserted at every frame. Its histories
never navigate: which thaws hand back a live object depends on when the
collector last ran, so two scenes, or two processes, seeking alike need
not hold the same objects (B4.4's seek proof takes that up).

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
from types import SimpleNamespace
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
from maniml.mobject.types.point_cloud_mobject import PGroup
from maniml.mobject.types.surface import TexturedSurface
from maniml.mobject.types.vectorized_mobject import VGroup, VMobject
from maniml.scene.scene import Scene
from maniml.utils import programs
from maniml.web import generated_geometry, triangle_scene
from maniml.web.border_geometry import RenderCacheStale
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
        # is the case's input all the same. The serializer finds the bytes
        # in the frame alone: its fallback, the module's read cache, holds
        # every file this case reads and would hide a frame (or a retained
        # leaf) that lost its payload.
        self.enterContext(patch.object(generated_geometry, "_TEXTURE_BY_HASH", {}))
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



# The retained frame (B4.2): the flag-on serializer against the flag-off one
# over the same history, frame by frame, wherever the episodes are absent.
RETAINED_ENV = "MANIML_RETAINED_FRAME"
MEMO_TABLES = ("generated_payloads", "generated_paints", "generated_borders", "generated_objects",
               "generated_nets", "generated_rows")


def trusting():
    """Whether the run lets the retained frame keep a leaf at all: under
    MANIML_VERIFY_LEDGER=1 it prepares every leaf, as B4.2 leaves it."""
    return os.environ.get("MANIML_VERIFY_LEDGER") != "1"


def census(cache):
    """What a GeometryCache holds beside the bytes it wrote: the names the
    receiver is recorded as holding, the digest memos, and what each render
    cache retains. The retained frame must leave the same, or a later
    frame's bytes follow another history: a budget evicts by recency, and a
    reservation kept one frame too long stays grown."""
    held = {"sent": set(cache.sent),
            "memos": [len(getattr(cache, name, {})) for name in MEMO_TABLES]}
    meshes = cache.triangle_meshes
    if meshes is not None:
        border, nets = meshes.gpu_border_cache, meshes.gpu_net_cache
        held.update(meshes=(len(meshes._entries), meshes._bytes, len(meshes._classes)),
                    border=(len(border.sources), len(border.capacities), len(border.runs), border.nbytes),
                    nets=(len(nets.entries), nets.nbytes))
    return held


def difference(expected, actual):
    """Where two geometry messages first differ, in a line or two."""
    (header, payload), (other, other_payload) = parse_geometry_message(expected), parse_geometry_message(actual)
    for key in header:
        if key != "batches" and header[key] != other.get(key):
            return f"header {key!r}: {str(header[key])[:300]} != {str(other.get(key))[:300]}"
    if len(header["batches"]) != len(other["batches"]):
        return f"{len(header['batches'])} batches != {len(other['batches'])}"
    for index, (batch, mine) in enumerate(zip(header["batches"], other["batches"])):
        if batch != mine:
            return f"batch {index}: {json.dumps(batch)[:400]} != {json.dumps(mine)[:400]}"
    if payload != other_payload:
        return f"payloads of {len(payload)} and {len(other_payload)} bytes"
    # The payloads are equal: what precedes them is the header's text.
    text, other_text = expected[5:len(expected) - len(payload)], actual[5:len(actual) - len(payload)]
    at = next((i for i, (a, b) in enumerate(zip(text, other_text)) if a != b), min(len(text), len(other_text)))
    return (f"equal once parsed, spelled differently at header byte {at}: "
            f"{text[max(0, at - 60):at + 60]!r} != {other_text[max(0, at - 60):at + 60]!r}")


class Lockstep:
    """One scripted history driven twice: two copies of a scene, built alike
    and stepped alike, each serialized through its own GeometryCache, one
    with MANIML_RETAINED_FRAME unset and one with it set. Every frame's two
    messages must be equal, and so must what the two caches hold after it.

    Two scenes rather than one serialized twice: a serializer's reads write
    to the scene (a stroke's shader data refreshes its derived columns, a
    data read materializes a pending program), and the retained frame skips
    exactly the reads of the leaves it keeps. One scene serialized twice
    would hand one side the scene as the other left it, a history neither
    has alone, and could hide a kept leaf whose draws depend on a read it
    skipped. Building the scene twice gives each side its own history
    without asking the scene to survive a deep copy.
    """

    def __init__(self, test, build):
        self.test = test
        self.sides = (build(), build())
        self.caches = (GeometryCache(), GeometryCache())
        self.count = 0

    @property
    def retained(self):
        return self.caches[1].retained_frame

    def step(self, action):
        """Apply ``action`` to each side (its scene and handles)."""
        for side in self.sides:
            action(side)

    def serialize(self, index, renderer, retained):
        with patch.dict(os.environ):
            os.environ.pop(RETAINED_ENV, None)
            if retained:
                os.environ[RETAINED_ENV] = "1"
            return serialize_scene(self.sides[index].scene, self.caches[index], renderer=renderer)

    def messages(self, renderer="triangles", *, retained=True):
        """This frame's two messages, flag off then flag on, uncompared.
        ``retained=False`` serializes the flag-on side without the flag
        too, as a run that turned it off would."""
        self.count += 1
        return self.serialize(0, renderer, False), self.serialize(1, renderer, retained)

    def frame(self, label, renderer="triangles", *, retained=True):
        """Both sides' messages for this frame (``messages``), compared; the
        flag-off one is returned."""
        messages = self.messages(renderer, retained=retained)
        where = f"frame {self.count} ({label}, {renderer})"
        if messages[1] != messages[0]:
            self.test.fail(f"{where}: flag on differs from flag off: {difference(*messages)}")
        self.test.assertEqual(census(self.caches[1]), census(self.caches[0]), f"{where}: the caches differ")
        return messages[0]

    def raises(self, label, exception, renderer="triangles"):
        """Both sides refuse this frame with ``exception``."""
        self.count += 1
        for index, retained in ((0, False), (1, True)):
            with self.test.assertRaises(exception, msg=f"frame {self.count} ({label}, {renderer})"):
                self.serialize(index, renderer, retained)

    def play(self, animations, name, renderer, alphas=(.25, .5, .75)):
        """Each side's ``animations(side)`` driven through a play by hand, a
        frame at its start, at each of ``alphas`` and at its landing."""
        plays = [[prepare_animation(animation) for animation in animations(side)] for side in self.sides]
        for animation in (animation for group in plays for animation in group):
            animation.begin()
        self.frame(f"{name} begins", renderer)
        for alpha in alphas:
            for animation in (animation for group in plays for animation in group):
                animation.interpolate(alpha)
            self.frame(f"{name} at {alpha}", renderer)
        for animation in (animation for group in plays for animation in group):
            animation.finish()
        self.frame(f"{name} lands", renderer)

    def expect(self, **counts):
        """The flag-on side's counts for the last frame, where a leaf may be
        kept at all."""
        if trusting():
            stats = self.retained.stats
            self.test.assertEqual({key: stats[key] for key in counts}, counts, f"after frame {self.count}")


def write_texture(path, blue):
    """A BMP, whose bytes no encoder can vary, of a gradient with ``blue``."""
    pixels = np.zeros((8, 16, 3), dtype=np.uint8)
    pixels[..., 0] = np.arange(16) * 16
    pixels[..., 1] = (np.arange(8) * 32)[:, None]
    pixels[..., 2] = blue
    Image.fromarray(pixels, "RGB").save(path, format="BMP")


def lockstep_scene(texture):
    """synthetic_scene's leaves, an image and a textured surface over one
    texture file, and two squares whose equal uniforms are spelled 1.0 and
    1: every pipeline, every kind of leaf the retained frame keeps by a
    different rule, and a run that prints its first member's spelling."""
    scene, family, path, cloud, globe = synthetic_scene()
    image = ImageMobject(str(texture), height=1.2).shift(3 * LEFT + 1.4 * DOWN)
    textured = TexturedSurface(Sphere(radius=.5, resolution=(9, 9)), str(texture)).shift(3 * RIGHT + 1.4 * DOWN)
    spelled = [Square(side_length=.4, fill_color=YELLOW, fill_opacity=1, stroke_width=0)
               .set_anti_alias_width(width).shift(x * RIGHT + 2.6 * DOWN)
               for width, x in ((1.0, -.5), (1, .5))]
    for mobject in (image, textured, *spelled):
        scene.mobjects.append(mobject)
        scene.render_groups[0].add(mobject)
    return SimpleNamespace(scene=scene, family=family, path=path, cloud=cloud, globe=globe, image=image,
                           spelled=spelled)


class StrokeFromAnAttribute(Square):
    """A stroke whose rows scale with an attribute no revision covers, as
    tests.test_border_geometry's DynamicBorder is a border's."""

    factor = 1.0

    def get_shader_data(self):
        data = super().get_shader_data().copy()
        data["stroke_width"] *= self.factor
        return data


class FillFromAnAttribute(Circle):
    """A fill whose points are offset by an attribute no revision covers."""

    offset = 0.0

    def get_points(self):
        return super().get_points() + self.offset * RIGHT


class DotsFromAnAttribute(DotCloud):
    """A dot cloud whose radii scale with an attribute no revision covers."""

    factor = 1.0

    def get_shader_data(self):
        data = super().get_shader_data().copy()
        data["radius"] *= self.factor
        return data


def rows_from(mobject, state):
    """``mobject``'s stroke rows through an instance's own getter, scaled by
    ``state["factor"]``, which no revision covers."""
    method = type(mobject).get_shader_data

    def get_shader_data():
        data = method(mobject).copy()
        data["stroke_width"] *= state["factor"]
        return data

    mobject.get_shader_data = get_shader_data
    return mobject


def add(side, name, mobject):
    setattr(side, name, mobject)
    side.scene.mobjects.append(mobject)
    side.scene.render_groups[0].add(mobject)


def remove(side, name):
    mobject = getattr(side, name)
    side.scene.mobjects.remove(mobject)
    side.scene.render_groups[0].remove(mobject)


@requires_lyon
class RetainedFrameLockstep(GoldenCase):
    """The flag-on bytes are the flag-off bytes of the same history (B4.2).

    The scripted sequence runs under each renderer: a cold frame, twenty
    stills that keep every leaf and reuse every descriptor, a leaf added,
    moved and removed, a child's z_index, a stroke moved behind (and the
    same flag and the depth test written as plain attributes), a client's
    connect (cache.reset()), the renderer switched and back (Phase A and
    Phase B each way, and Original 2D, which clears the triangle caches), a
    6x zoom and back followed by a paint-only edit (a kept leaf must keep
    its refined mesh and grown reservation), a pan, a texture file
    rewritten in place (no revision moves), the flag turned off for a
    frame, a frame that raises, two plays (uniforms only; a program play,
    drawn from GPU programs under Phase B) and a cold cache.

    Beside it: a full budget evicting in the frame's order, the memos and
    the frame's own bytes bounded by one frame, leaves read through
    getters of their own (a subclass's, an instance's), a point-cloud
    group rewriting its members, and the writes that bump no revision,
    which a kept leaf does not see (B4.5's verify mode is proven against
    them).
    """

    def setUp(self):
        # The serializer finds texture bytes in the frame alone, as in the
        # textures pin: a kept leaf that lost its payload must fail here.
        self.enterContext(patch.object(generated_geometry, "_TEXTURE_BY_HASH", {}))
        self.addCleanup(programs.set_override, None)

    def test_scripted_sequence(self):
        for renderer in RENDERERS:
            with self.subTest(renderer=renderer), tempfile.TemporaryDirectory() as tmp:
                self.scripted_sequence(renderer, Path(tmp) / "texture.bmp")

    def scripted_sequence(self, renderer, texture):
        other = "phase_b" if renderer == "triangles" else "triangles"
        write_texture(texture, 200)
        lock = Lockstep(self, lambda: lockstep_scene(texture))
        lock.frame("cold", renderer)
        lock.expect(leaves_kept=0)
        for index in range(20):
            lock.frame(f"still {index}", renderer)
            lock.expect(leaves_prepared=0, runs_combined=0, batches_encoded=0)

        lock.step(lambda side: add(side, "extra", Square(side_length=.8, fill_color=YELLOW, fill_opacity=1,
                                                         stroke_width=0).shift(2.4 * UP)))
        lock.frame("add a square", renderer)
        lock.expect(leaves_prepared=1)
        lock.step(lambda side: side.extra.shift(.2 * RIGHT))
        lock.frame("move the square", renderer)
        lock.expect(leaves_prepared=1)
        # Group.remove bumps every member of the group's family: each leaf
        # is prepared again (B4.3's source compare is what keeps them).
        lock.step(lambda side: remove(side, "path"))
        lock.frame("remove the path", renderer)
        lock.step(lambda side: setattr(side.family[1], "z_index", 5))
        lock.frame("child z_index 5", renderer)
        lock.expect(leaves_prepared=1)
        lock.step(lambda side: setattr(side.family[1], "z_index", 0))
        lock.frame("child z_index 0", renderer)
        lock.step(lambda side: side.family[0].set_stroke(behind=True))
        lock.frame("stroke behind", renderer)
        lock.step(lambda side: side.family[0].set_stroke(behind=False))
        lock.frame("stroke in front", renderer)
        # The same flag, and the depth test, written as plain attributes:
        # no revision moves, the frame's loop reads both every frame, and
        # a kept leaf compares them.
        for name in ("stroke_behind", "depth_test"):
            lock.step(lambda side: setattr(side.family[0], name, True))
            lock.frame(f"{name} set as an attribute", renderer)
            lock.expect(leaves_prepared=1)
            lock.step(lambda side: setattr(side.family[0], name, False))
            lock.frame(f"{name} cleared as an attribute", renderer)
            lock.expect(leaves_prepared=1)
        # The square spelled 1.0 leaves the front of the run: the run now
        # prints the square spelled 1, which one uniform set for both
        # would print as 1.0.
        lock.step(lambda side: setattr(side.spelled[0], "z_index", 1))
        lock.frame("spelled 1.0 lifted", renderer)
        lock.step(lambda side: setattr(side.spelled[0], "z_index", 0))
        lock.frame("spelled 1.0 back", renderer)
        # A leaf that stops reading its border source lets the caches
        # sweep it: a kept leaf must hold only what its draws were read from.
        lock.step(lambda side: side.family[1].set_fill(border_width=0))
        lock.frame("border off", renderer)
        lock.frame("still", renderer)
        lock.step(lambda side: side.family[1].set_fill(border_width=2))
        lock.frame("border on", renderer)
        lock.frame("still", renderer)

        for cache in lock.caches:
            cache.reset()  # a client's connect
        lock.frame("after a reset", renderer)
        lock.expect(leaves_prepared=0, batches_reused=0)
        lock.frame("still", renderer)
        lock.expect(batches_encoded=0)

        for switched in (other, "winding"):
            lock.frame(f"switched to {switched}", switched)
            lock.frame(f"back from {switched}", renderer)
            lock.expect(leaves_kept=0)
            lock.frame("still", renderer)
            lock.expect(leaves_prepared=0, batches_encoded=0)

        # A zoom in grows the disc's mesh and border reservation; the zoom
        # back keeps them; a paint-only edit then refreshes the mesh it
        # kept, which the kept leaf must not have let the caches sweep.
        lock.step(lambda side: side.scene.camera.frame.scale(1 / 6))
        lock.frame("zoom in 6x", renderer)
        lock.step(lambda side: side.scene.camera.frame.scale(6))
        lock.frame("zoom back", renderer)
        lock.frame("still", renderer)
        lock.step(lambda side: side.family[1].set_fill(YELLOW))
        lock.frame("paint-only edit", renderer)
        lock.expect(leaves_prepared=1)
        lock.step(lambda side: side.scene.camera.frame.shift(.05 * RIGHT))
        lock.frame("pan", renderer)
        lock.frame("still", renderer)

        # Rewriting the file moves its hash and bumps no revision.
        stat = texture.stat()
        write_texture(texture, 90)
        os.utime(texture, ns=(stat.st_atime_ns, stat.st_mtime_ns + 10 ** 9))
        lock.frame("texture rewritten", renderer)
        lock.expect(leaves_prepared=2)
        lock.frame("still", renderer)

        lock.frame("flag off", renderer, retained=False)
        self.assertIsNone(lock.retained)
        lock.frame("flag on again", renderer)
        lock.expect(leaves_kept=0)
        lock.frame("still", renderer)

        # A nonplanar closed fill is refused, and a refused frame leaves
        # the retained frame cold.
        def bent(side):
            add(side, "bent", VMobject(fill_color=RED, fill_opacity=1, stroke_width=0)
                .set_points_as_corners([[0, 0, 0], [1, 0, 0], [1, 1, 1], [0, 1, 0], [0, 0, 0]]))

        lock.step(bent)
        lock.raises("a nonplanar fill", triangle_scene.UnsupportedPrototype, renderer)
        lock.step(lambda side: remove(side, "bent"))
        lock.frame("the nonplanar fill removed", renderer)
        lock.expect(leaves_kept=0)
        lock.frame("still", renderer)

        lock.play(lambda side: [side.family[0].animate.set_anti_alias_width(6),
                                side.globe.animate.set_shading(.6, .2, .4)],
                  "a uniforms-only play", renderer)
        programs.set_override("gpu")
        lock.play(lambda side: [side.family.animate.shift(.3 * DOWN)], "a program play", renderer)
        programs.set_override(None)
        lock.frame("still", renderer)

        lock.caches = (GeometryCache(), GeometryCache())
        lock.frame("cold again", renderer)
        lock.frame("still", renderer)
        lock.expect(leaves_prepared=0, batches_encoded=0)

    def test_a_budget_evicts_what_the_frame_would(self):
        # The caches evict by recency, so a kept leaf must be marked used
        # where the frame's own loop reads it, in draw order. Six discs
        # refined by a zoom in and kept by the zoom back fill the mesh
        # budget exactly; one grows, and its new mesh evicts the entry used
        # longest ago, which regenerates coarser at this zoom: evicting
        # another shows in the bytes. No fill borders, whose recipes the
        # full budget would leave no room (every leaf would be prepared
        # again, hiding the order), and Phase A only: Phase B's patch fills
        # keep no meshes.
        def build():
            discs = [Circle(radius=.3, fill_color=GREEN, fill_opacity=1, stroke_width=0,
                            fill_border_width=0).shift((index - 2.5) * .8 * RIGHT)
                     for index in range(6)]
            return SimpleNamespace(scene=build_scene(*discs), discs=discs)

        lock = Lockstep(self, build)
        lock.frame("cold")
        lock.step(lambda side: side.scene.camera.frame.scale(1 / 4))
        lock.frame("zoom in 4x")
        lock.step(lambda side: side.scene.camera.frame.scale(4))
        lock.frame("zoom back")
        for cache in lock.caches:
            cache.triangle_meshes.max_bytes = cache.triangle_meshes._bytes
        lock.frame("a full budget")
        meshes = lock.caches[0].triangle_meshes
        evictions = meshes.stats["evictions"]
        lock.step(lambda side: side.discs[2].scale(6))
        lock.frame("a disc grows")
        # Its own old entry, and at least one other's.
        self.assertGreater(meshes.stats["evictions"], evictions + 1, "the budget evicted nothing")
        lock.expect(leaves_prepared=2)
        for index in range(3):
            lock.frame(f"still {index}")
        lock.expect(leaves_prepared=0, batches_encoded=0)

    def test_memos_stay_bounded_by_one_frame(self):
        # The digest memos hold what the last message named, reused batches
        # included, and nothing else: the prototype merged them instead and
        # kept every regenerated mesh alive (984 KB after sixty frames of
        # ten moving circles). Five circles move and five stand still, so
        # half the batches are reused every frame. What the retained frame
        # itself holds outside the caches' budget (its gauge) is one
        # frame's too, the same from the second frame on.
        def build():
            circles = [Circle(radius=.25, fill_color=BLUE, fill_opacity=1, stroke_color=WHITE, stroke_width=2,
                              fill_border_width=1).shift((index - 4.5) * .7 * RIGHT + (index % 2) * UP)
                       for index in range(10)]
            return SimpleNamespace(scene=build_scene(*circles), circles=circles)

        for renderer in RENDERERS:
            with self.subTest(renderer=renderer):
                lock = Lockstep(self, build)
                held = []
                for index in range(60):
                    lock.step(lambda side: [circle.shift(.01 * UP) for circle in side.circles[::2]])
                    message = lock.frame(f"step {index}", renderer)
                    held.append(lock.retained.retained_bytes())
                self.assertEqual(set(held[1:]), {held[1]})
                batches = len(parse_geometry_message(message)[0]["batches"])
                for name in MEMO_TABLES:
                    self.assertLessEqual(len(getattr(lock.caches[1], name, {})), batches, name)
                retained = sum(value[0].nbytes + (0 if value[1] is None else value[1].nbytes)
                               for value in lock.caches[1].generated_payloads.values())
                self.assertLess(retained, 64 << 10)

    def test_a_leaf_read_through_its_own_getter_is_prepared_every_frame(self):
        # The frame's loop reads a stroke's and a plain leaf's shader data
        # every frame, and the caches trust a revision only for the
        # library's own getters: a subclass's or an instance's may read
        # anything. Here each reads an attribute that moves between frames
        # with no revision bump.
        def build():
            stroke = StrokeFromAnAttribute(side_length=1, fill_opacity=0, stroke_width=4).shift(2 * LEFT)
            fill = FillFromAnAttribute(radius=.5, fill_color=BLUE, fill_opacity=1, stroke_width=0)
            dots = DotsFromAnAttribute(np.array([[-1, 1.5, 0], [1, 1.5, 0]]))
            state = {"factor": 1.0}
            outline = rows_from(Rectangle(width=2, height=.5, fill_opacity=0, stroke_width=3), state)
            plain = Square(side_length=.6, fill_color=RED, fill_opacity=1, stroke_width=2).shift(2 * RIGHT)
            scene = build_scene(stroke, fill, dots, outline.shift(1.5 * DOWN), plain)
            return SimpleNamespace(scene=scene, stroke=stroke, fill=fill, dots=dots, state=state)

        def move(side, k):
            side.stroke.factor = 1 + k
            side.fill.offset = .1 * k
            side.dots.factor = 1 + .5 * k
            side.state["factor"] = 1 + k

        for renderer in RENDERERS:
            with self.subTest(renderer=renderer):
                lock = Lockstep(self, build)
                lock.frame("cold", renderer)
                lock.frame("still", renderer)
                lock.expect(leaves_kept=1, leaves_prepared=4)
                for k in range(1, 4):
                    lock.step(lambda side: move(side, k))
                    lock.frame(f"attributes moved {k}", renderer)
                    lock.expect(leaves_kept=1, leaves_prepared=4)

    def test_a_point_cloud_group_rewrites_every_member(self):
        # PGroup.sort_points and filter_out rewrite each member's rows
        # (PMobject bumps each since B4.2): a kept member would draw its
        # old order, and the dots filtered out.
        def build():
            a = DotCloud(np.array([[1, 0, 0], [-1, 0, 0], [0, 1, 0]]))
            a.set_color_by_gradient(BLUE, RED)
            b = DotCloud(np.array([[2, 1, 0], [-2, 1, 0]]), color=RED)
            group = PGroup(a, b)
            return SimpleNamespace(scene=build_scene(group), group=group)

        for renderer in RENDERERS:
            with self.subTest(renderer=renderer):
                lock = Lockstep(self, build)
                lock.frame("cold", renderer)
                lock.frame("still", renderer)
                lock.step(lambda side: side.group.sort_points(lambda p: p[0]))
                lock.frame("sorted", renderer)
                lock.expect(leaves_prepared=2)
                lock.step(lambda side: side.group.filter_out(lambda p: p[0] > 1.5))
                lock.frame("filtered", renderer)
                lock.expect(leaves_prepared=2)
                lock.step(lambda side: side.group.filter_out(lambda p: p[1] > .5))
                lock.frame("one member emptied", renderer)
                lock.frame("still", renderer)
                lock.expect(leaves_prepared=0)

    def test_writes_that_bump_no_revision(self):
        # In-place writes the revision contract does not cover: the frame's
        # loop reads each of these every frame, so the flag-off path draws
        # them on its next frame, while a kept leaf keeps its draws until
        # its revision moves. Under MANIML_VERIFY_LEDGER=1 every leaf is
        # prepared (B4.2), so the flag-on side draws them too, or raises
        # where a cache's own check sees the write, as the flag-off side
        # does; B4.5's verify mode rebuilds the kept leaves instead and
        # must raise RenderCacheStale for each.
        def build():
            scene, family, path, cloud, _ = synthetic_scene()
            return SimpleNamespace(scene=scene, family=family, path=path, cloud=cloud)

        def stroke_color(side):
            side.family[0].data["stroke_rgba"][:, :2] = (1, 0)

        def uniform(side):
            side.family[0].uniforms["anti_alias_width"] = 4.0

        def radius(side):
            side.cloud.data["radius"][:] = .2

        def point_view(side):
            points = side.path.get_points()  # a stroke-only path's, which only its stroke reads
            points[:, 1] += .1

        for write in (stroke_color, uniform, radius, point_view):
            for renderer in RENDERERS:
                with self.subTest(write=write.__name__, renderer=renderer):
                    lock = Lockstep(self, build)
                    lock.frame("cold", renderer)
                    still = lock.frame("still", renderer)
                    lock.step(write)
                    if not trusting():
                        try:
                            expected = lock.serialize(0, renderer, False)
                        except RenderCacheStale:
                            with self.assertRaises(RenderCacheStale):
                                lock.serialize(1, renderer, True)
                        else:
                            self.assertEqual(lock.serialize(1, renderer, True), expected)
                        continue
                    off, on = lock.messages(renderer)
                    self.assertNotEqual(off, still, "the frame's loop did not see the write")
                    self.assertEqual(on, still, "a kept leaf saw a write that bumped nothing")
                    lock.expect(leaves_prepared=0)


if __name__ == "__main__":
    if "--record" in sys.argv:
        sys.argv.remove("--record")
        os.environ[RECORD_ENV] = "1"
    unittest.main()

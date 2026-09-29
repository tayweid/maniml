"""The golden pin of Phase B4 (docs/phase_b4_plan.md, B4.0).

blake2b digests of ``serialize_scene``'s message bytes, frame by frame
through one persistent GeometryCache per case and renderer, for
``renderer="phase_a"`` (Phase A forced) and ``"phase_b"`` (the Phase B
stack forced), over the renderer fixtures, the quality fixtures, scripted
synthetic sequences and frames of the two course episodes, asserted
against the recorded files in tests/goldens/retained_frame/. They are the
contract every increment of the retained frame holds: with
MANIML_RETAINED_FRAME=0 the bytes may not move, and with the retained
frame on, the default since B4.5, they are the flag-off bytes. The pin
runs with whatever the run's switch is. It pins the two forced names, not
the default ("triangles"), so a default that flips (docs/phase_b4_plan.md,
"The flips") moves no pinned byte; Phase A's frames are the bytes the
default wrote before the flips (they were recorded as "triangles", and
renamed "phase_a" in B5.4 with every digest unchanged).

The synthetic cases carry what the per-record loop must preserve, since
they run everywhere (CI has no episodes): CE's z_index order within a
family and the render-group rejoin across a fixed-in-frame overlay,
fixed-frame groups last, runs and their output cap, a run's uniforms as
its first member spells them (``1`` and ``1.0`` are equal and print
differently), texture payloads and their resend after a reset,
reservations a zoom grows and the zoom back keeps, leaves skipped for
having no points, uniforms that move with no row, and program draws.

RetainedFrameLockstep (B4.2, B4.3, B4.5) holds the retained frame to the
flag-off path directly, wherever the goldens cannot reach: one scripted
history driven on two scenes built alike, one serialized with
MANIML_RETAINED_FRAME=1 and one with it 0, equal messages, equal cache
contents and equal leaf rows and refresh state asserted at every frame.
Its histories never navigate. RetainedFrameNavigation (B4.4) does,
through a scene's checkpoints: which thaws hand back a live object
depends on when the collector last ran, so it runs the collector around
every navigation and holds it off during one, and both scenes hold the
same objects.

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
import itertools
import json
import os
from pathlib import Path
import re
import struct
import sys
import tempfile
import textwrap
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image

from maniml import config
from maniml.__main__ import load_scene_module
from maniml.animation.animation import prepare_animation
from maniml.animation.creation import ShowCreation
from maniml.animation.fading import FadeIn
from maniml.animation.rotation import Rotate
from maniml.animation.transform import Transform
from maniml.constants import BLUE, DEFAULT_RESOLUTION, DOWN, GREEN, LEFT, ORIGIN, RED, RIGHT, UL, UP, WHITE, YELLOW
from maniml.mobject.geometry import Annulus, Circle, DashedLine, Line, Rectangle, Square
from maniml.mobject.three_dimensions import Sphere
from maniml.mobject.types.dot_cloud import DotCloud
from maniml.mobject.types.image_mobject import ImageMobject
from maniml.mobject.types.point_cloud_mobject import PGroup
from maniml.mobject.types.surface import TexturedSurface
from maniml.mobject.types.vectorized_mobject import VGroup, VMobject
from maniml.scene.scene import Scene
from maniml.utils import programs
from maniml.web import generated_geometry, retained_frame, triangle_scene
from maniml.web.border_geometry import RenderCacheStale
from maniml.web.geometry import (
    FULL_FRAME_FORMAT_VERSION, POLYLINE_FACTOR, GeometryCache, _jsonable, _stroke_sqrt_area, _stroke_verts,
    _stroke_verts_at, expand_delta, parse_geometry_message, serialize_scene,
)
from maniml.web.triangle_geometry import LyonFillTessellator, _packaged_library
from tests.renderer_fixtures import build_scene, renderer_cases
from tests.renderer_quality_fixtures import QualityFixtureUnavailable, quality_cases

GOLDEN_DIR = Path(__file__).resolve().parent / "goldens" / "retained_frame"
RECORD_ENV = "MANIML_RECORD_GOLDENS"
RENDERERS = ("phase_a", "phase_b")
# The switches the forced renderers still read (the border generator, the
# patch source) and the cache policy select other bytes on purpose; the pin
# is the border generator's and the cache policy's defaults and the patch
# source it was recorded under, stated (GoldenCase); the stack's own (fill,
# surface, programs) the forced names ignore, and are cleared all the same.
# MANIML_RETAINED_FRAME and MANIML_VERIFY_LEDGER stay as the run has them:
# neither may change a byte.
PINNED_ENV = ("MANIML_BORDER_GENERATOR", "MANIML_FILL", "MANIML_SURFACE", "MANIML_PROGRAMS",
              "MANIML_PATCH_SOURCE", "MANIML_RENDER_CACHE", "MANIML_RENDERER")
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


def format_seven(message):
    """A format 8 full frame with its epoch and frame number taken out and
    its version put back: exactly the format 7 frame, when the two keys are
    all that format 8 added to it."""
    (length,) = struct.unpack_from("<I", message, 1)
    text = message[5:5 + length]
    added = re.match(rb'\{"format_version": 8, "epoch": \d+, "frame": \d+, ', text)
    if added is None:
        raise AssertionError(f"not a format 8 full frame: {text[:80]!r}")
    text = b'{"format_version": 7, ' + text[added.end():]
    return b"".join((message[:1], struct.pack("<I", len(text)), text, message[5 + length:]))


def expanded(previous, message):
    """expand_delta's frame for ``message`` (bytes, or None for a frame the
    stream did not send), as its header and message bytes."""
    header, payload = expand_delta(previous, message)
    text = json.dumps(header).encode()
    return header, b"".join((b"\x03", struct.pack("<I", len(text)), text, payload))


class Pin:
    """One case's history: a GeometryCache per renderer that lives across
    the case's frames, as the viewer's does, and the digest of every
    frame's bytes in the order they were produced.

    The same history is also streamed as format 8 (docs/phase_b4_plan.md,
    B4.8) through a cache per renderer whose receivers negotiated it, after
    the pinned caches, and every message is held to the pinned frame: a
    full frame is the pinned bytes but for its two keys (format_seven),
    and a delta, or the silence of a frame that changed nothing, applied
    to the frame before it is the pinned bytes exactly (expand_delta).
    ``kinds`` counts what the streams sent."""

    def __init__(self):
        self.caches = {renderer: GeometryCache() for renderer in RENDERERS}
        self.streams = {renderer: GeometryCache() for renderer in RENDERERS}
        for cache in self.streams.values():
            cache.negotiate(True)
        self.shown = dict.fromkeys(RENDERERS)
        self.kinds = dict.fromkeys(("full", "delta", "silent"), 0)
        self.frames = {}

    def frame(self, scene, name):
        label = f"{len(self.frames):02d} {name}"
        messages = {renderer: serialize_scene(scene, cache, renderer=renderer)
                    for renderer, cache in self.caches.items()}
        self.frames[label] = {renderer: hashlib.blake2b(message, digest_size=16).hexdigest()
                              for renderer, message in messages.items()}
        for renderer, cache in self.streams.items():
            message = serialize_scene(scene, cache, renderer=renderer)
            kind = ("silent" if message is None
                    else "delta" if "base" in parse_geometry_message(message)[0] else "full")
            if kind == "full" and format_seven(message) != messages[renderer]:
                raise AssertionError(f"{label} {renderer}: the format 8 full frame is not the pinned frame "
                                     f"with its epoch and frame: {difference(messages[renderer], format_seven(message))}")
            self.shown[renderer], frame = expanded(self.shown[renderer], message)
            if frame != messages[renderer]:
                raise AssertionError(f"{label} {renderer}: the format 8 {kind} does not stand for the pinned "
                                     f"frame: {difference(messages[renderer], frame)}")
            self.kinds[kind] += 1
        return label

    def reset(self):
        # What a client's connect does to the viewer's cache: the next
        # message ships every batch in full, and a stream opens an epoch.
        for cache in (*self.caches.values(), *self.streams.values()):
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
            "format_version": FULL_FRAME_FORMAT_VERSION,
            "recorded_with": "python -m tests.test_retained_frame --record",
            "cases": self.cases,
        }, indent=1, sort_keys=True) + "\n")


class GoldenCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.enterClassContext(patch.dict(os.environ))
        for name in PINNED_ENV:
            os.environ.pop(name, None)
        # The plays were recorded with their animations writing no program,
        # the default then: stated, so that a default that flips
        # (programs.DEFAULT_MODE, docs/phase_b4_plan.md "The flips") moves
        # no pinned byte. The forced renderers never read it.
        os.environ["MANIML_PROGRAMS"] = "off"
        # The patch fills were recorded as their records packed, the patch
        # source's default then: stated, so that its default since B5.6
        # (geometry.DEFAULT_PATCH_SOURCE, rows) moves no pinned byte. Rows
        # draw the same pixels (PatchRowsPixels) and keep the retained
        # frame's lockstep (RowSourcesLockstep, RowSourcesNavigation).
        os.environ["MANIML_PATCH_SOURCE"] = "records"
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
        # The format 8 streams the pin held to these frames opened an epoch
        # at the cold frame and at the reset, sent nothing for the stills
        # and the play's first frame (its begin changes nothing drawn), and
        # a delta for every other frame.
        stills = sum(label.endswith((" still", " begins")) for label in pin.frames)
        self.assertEqual(pin.kinds, {"full": 2 * len(RENDERERS), "silent": stills * len(RENDERERS),
                                     "delta": (len(pin.frames) - 2 - stills) * len(RENDERERS)})

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



class RetainedFrameSwitch(unittest.TestCase):
    """The retained frame is the default since B4.5: MANIML_RETAINED_FRAME=0
    turns it off, and a cache serialized without it drops it; a frame
    serialized without a cache keeps nothing."""

    def test_on_unless_turned_off(self):
        with patch.dict(os.environ):
            os.environ.pop("MANIML_RETAINED_FRAME", None)
            self.assertTrue(retained_frame.retained_frame_enabled())
            for value, enabled in (("1", True), ("0", False)):
                os.environ["MANIML_RETAINED_FRAME"] = value
                self.assertIs(retained_frame.retained_frame_enabled(), enabled)
            os.environ["MANIML_RETAINED_FRAME"] = "yes"
            with self.assertRaises(ValueError):
                retained_frame.retained_frame_enabled()

    @requires_lyon
    def test_a_cache_keeps_draws_by_default(self):
        scene, cache = build_scene(Square(fill_opacity=1)), GeometryCache()
        with patch.dict(os.environ):
            os.environ.pop("MANIML_RETAINED_FRAME", None)
            serialize_scene(scene, cache)
            self.assertIsInstance(cache.retained_frame, retained_frame.RetainedFrame)
            os.environ["MANIML_RETAINED_FRAME"] = "0"
            serialize_scene(scene, cache)
            self.assertIsNone(cache.retained_frame)
            os.environ.pop("MANIML_RETAINED_FRAME")
            with patch.object(retained_frame, "RetainedFrame") as made:
                serialize_scene(scene)
            made.assert_not_called()


class StrokeCountFromTheLargestCurve(unittest.TestCase):
    """A kept stroke's count after a zoom (B4.3): _stroke_verts_at over the
    largest curve's sqrt(area) is _stroke_verts over every curve, at every
    positive frame scale, the scales that put a curve's count on a rounding
    tie among them."""

    @staticmethod
    def outcome(count):
        """``count()``'s value, or the kind of error it raised: a scale past
        float32's range makes both forms divide infinity by infinity."""
        try:
            with np.errstate(over="ignore", invalid="ignore"):
                return count()
        except ValueError as error:
            return type(error)

    def test_the_count_is_stroke_verts(self):
        rng = np.random.default_rng(3)
        dtype = np.dtype([("point", "<f4", (3,))])
        cases = []
        for index in range(120):
            curves = int(rng.integers(1, 30))
            data = np.zeros(3 * curves, dtype=dtype)
            data["point"] = rng.normal(size=(3 * curves, 3)) * 10 ** rng.uniform(-3, 1)
            if index % 3 == 0:
                data["point"][:, 2] = 0
            cases.append(data)
        # No curves, a degenerate one, and one whose area overflows float32.
        cases.append(np.zeros(0, dtype=dtype))
        cases.append(np.zeros(3, dtype=dtype))
        huge = np.zeros(3, dtype=dtype)
        huge["point"] = [[0, 0, 0], [1e20, 0, 0], [0, 1e20, 0]]
        cases.append(huge)
        checked = 0
        for data in cases:
            p0, p1, p2 = data["point"][0::3], data["point"][1::3], data["point"][2::3]
            with np.errstate(over="ignore"):
                sqrt_area = _stroke_sqrt_area(data)
                roots = np.sqrt(0.5 * np.linalg.norm(np.cross(p1 - p0, p2 - p0), axis=1))
            scales = list(10 ** np.linspace(-4, 3, 40))
            for root in roots[:4]:
                for steps in range(31):
                    tie = float(POLYLINE_FACTOR * root / (steps + .5))
                    scales += [tie, np.nextafter(tie, 0), np.nextafter(tie, np.inf)]
            for frame_scale in scales:
                frame_scale = float(frame_scale)
                if not 0 < frame_scale < np.inf:
                    continue
                self.assertEqual(self.outcome(lambda: _stroke_verts_at(sqrt_area, frame_scale)),
                                 self.outcome(lambda: _stroke_verts(data, frame_scale)),
                                 f"{len(data) // 3} curves at frame scale {frame_scale!r}")
                checked += 1
        self.assertGreater(checked, 40_000)
        # A NaN area is refused alike.
        broken = np.zeros(3, dtype=dtype)
        broken["point"] = [[0, 0, 0], [np.nan, 0, 0], [0, 1, 0]]
        self.assertIs(self.outcome(lambda: _stroke_verts(broken, 1.0)), ValueError)
        self.assertIs(self.outcome(lambda: _stroke_verts_at(_stroke_sqrt_area(broken), 1.0)), ValueError)


# The retained frame (B4.2): the flag-on serializer against the flag-off one
# over the same history, frame by frame, wherever the episodes are absent.
RETAINED_ENV = "MANIML_RETAINED_FRAME"
MEMO_TABLES = ("generated_payloads", "generated_paints", "generated_borders", "generated_objects",
               "generated_nets", "generated_rows")


def verifying():
    """Whether the run verifies (MANIML_VERIFY_LEDGER=1). The retained frame
    then keeps what it keeps without it and reads each kept leaf again
    (B4.5), but prepares a leaf it would adopt, and counts it prepared."""
    return os.environ.get("MANIML_VERIFY_LEDGER") == "1"


def adopting_under_verification(stats):
    """Whether the last frame, verified, prepared a leaf it would have
    adopted: every kept leaf is verified, so any other is one. Its counts,
    and the meshes its caches made from scratch, are then not the ones the
    tests expect of the run without verification."""
    return verifying() and stats["leaves_verified"] > stats["leaves_kept"]


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


def leaf_states(scene):
    """What the serializer's reads may leave on each drawn leaf: its rows
    and, on a path, the refresh flags and cached subpath ends. A kept leaf
    whose read would have refreshed its derived columns must be left as
    the read leaves it, or a later lock of its joint angles, or a write
    that sets no flag, finds another scene on each side."""
    return [(type(sm).__name__, sm._data.tobytes(),
             *((sm.needs_new_joint_angles, sm.needs_new_unit_normal,
                None if sm.subpath_end_indices is None else sm.subpath_end_indices.tobytes())
               if isinstance(sm, VMobject) else ()))
            for sm in triangle_scene.draw_order(scene)]


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
    with MANIML_RETAINED_FRAME=0 and one with it on. Every frame's two
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

    def __init__(self, test, build, *, deltas=False):
        self.test = test
        self.sides = (build(), build())
        self.deltas = deltas
        self.fresh_caches()
        self.count = 0

    def fresh_caches(self):
        """A cache per side, as a new viewer holds; under ``deltas`` its
        receivers negotiated format 8, so the two sides' messages are the
        same stream (docs/phase_b4_plan.md, B4.8)."""
        self.caches = (GeometryCache(), GeometryCache())
        for cache in self.caches:
            cache.negotiate(self.deltas)

    @property
    def retained(self):
        return self.caches[1].retained_frame

    def step(self, action):
        """Apply ``action`` to each side (its scene and handles)."""
        for side in self.sides:
            action(side)

    def serialize(self, index, renderer, retained):
        with patch.dict(os.environ, {RETAINED_ENV: "1" if retained else "0"}):
            return serialize_scene(self.sides[index].scene, self.caches[index], renderer=renderer)

    def messages(self, renderer="phase_a", *, retained=True):
        """This frame's two messages, flag off then flag on, uncompared.
        ``retained=False`` serializes the flag-on side without the flag
        too, as a run that turned it off would."""
        self.count += 1
        return self.serialize(0, renderer, False), self.serialize(1, renderer, retained)

    def frame(self, label, renderer="phase_a", *, retained=True):
        """Both sides' messages for this frame (``messages``), compared; the
        flag-off one is returned."""
        messages = self.messages(renderer, retained=retained)
        where = f"frame {self.count} ({label}, {renderer})"
        if messages[1] != messages[0]:
            self.test.fail(f"{where}: flag on differs from flag off: {difference(*messages)}")
        self.test.assertEqual(census(self.caches[1]), census(self.caches[0]), f"{where}: the caches differ")
        states = [leaf_states(side.scene) for side in self.sides]
        if states[1] != states[0]:
            leaf = next((index for index, (a, b) in enumerate(zip(*states)) if a != b), "count")
            self.test.fail(f"{where}: the retained frame left another scene (leaf {leaf})")
        return messages[0]

    def raises(self, label, exception, renderer="phase_a"):
        """Both sides refuse this frame with ``exception``, and leave the
        same scene: the leaves read before the refusal as their reads
        leave them, the rest as they were."""
        self.count += 1
        where = f"frame {self.count} ({label}, {renderer})"
        for index, retained in ((0, False), (1, True)):
            with self.test.assertRaises(exception, msg=where):
                self.serialize(index, renderer, retained)
        states = [leaf_states(side.scene) for side in self.sides]
        if states[1] != states[0]:
            leaf = next((index for index, (a, b) in enumerate(zip(*states)) if a != b), "count")
            self.test.fail(f"{where}: the refused frame left another scene (leaf {leaf})")

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
        kept at all: unless verification prepared a leaf it would adopt."""
        stats = self.retained.stats
        if not adopting_under_verification(stats):
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


class MovesAnother(Square):
    """A stroke whose read moves another mobject, once, when armed: a getter
    of its own, which the frame's loop runs in draw order, after the walk
    and before the leaves behind it are read. ``quietly``, by a write to
    its rows that bumps nothing."""

    follower = None
    armed = False
    quietly = False

    def get_shader_data(self):
        if self.armed:
            self.armed = False
            if self.quietly:
                self.follower.data["point"][:, 0] += .4
            else:
                self.follower.shift(.3 * UP)
        return super().get_shader_data()


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


def updater_scene():
    """A pausepoint whose mobjects have updaters, which the viewer ticks
    every frame. Most bump a revision and change no byte, each its own
    way, as at EpisodeB2's 8.a; two really move."""
    corners = VMobject(stroke_color=YELLOW, stroke_width=4, fill_opacity=0)
    route = [[-3, -1.8, 0], [-1.5, -1.2, 0], [0, -1.9, 0], [1.5, -1.3, 0]]
    # The same corners every tick: both refresh flags set, the rows equal.
    corners.add_updater(lambda m: m.set_points_as_corners(route))
    template = Square(side_length=.9, fill_color=RED, fill_opacity=.7, stroke_color=WHITE,
                      stroke_width=3).shift(2 * LEFT + UP)
    framed = template.copy()
    # An unchanged target: become() copies its derived columns, which were
    # never refreshed, over the ones the last read refreshed.
    framed.add_updater(lambda m: m.become(template))
    disc = Circle(radius=.5, fill_color=GREEN, fill_opacity=.9, stroke_width=0,
                  fill_border_width=2).shift(.5 * UP)
    # A move to where it is: the same bytes and no flag.
    disc.add_updater(lambda m: m.move_to(m.get_center()))
    # A curved stroke, whose count a zoom changes (the straight ones keep
    # theirs at every scale).
    ring = Circle(radius=.3, stroke_color=WHITE, stroke_width=3, fill_opacity=0).shift(1.5 * RIGHT + .5 * DOWN)
    ring.add_updater(lambda m: m.move_to(m.get_center()))
    glyph = VMobject(fill_color=BLUE, fill_opacity=1, stroke_width=0, fill_border_width=0)
    outline = [[2, 1, 0], [2.8, 1, 0], [2.4, 1.8, 0], [2, 1, 0]]
    # A fill Phase A draws from its mesh alone: no read refreshes its
    # joint angles, so its rows are never a refresh's own output, and with
    # both flags set it is prepared every tick. Phase B reads its border
    # source, which refreshes them, and keeps it.
    glyph.add_updater(lambda m: m.set_points_as_corners(outline))
    hidden = VMobject(fill_opacity=0, stroke_width=0)
    # Nothing to fill or stroke, as a dashed line's own path under its
    # dashes: the read looks at its classification alone.
    hidden.add_updater(lambda m: m.set_points_as_corners(route[::-1]))
    badge = Rectangle(width=1, height=.4, fill_color=YELLOW, fill_opacity=.8, stroke_width=1).to_corner(UL)
    badge.fix_in_frame()
    badge.add_updater(lambda m: m.move_to(m.get_center()))
    spots = np.array([[-2, 1.8, 0], [-1, 1.9, 0], [0, 1.8, 0]])
    dots = DotCloud(spots)
    dots.add_updater(lambda m: m.set_points(spots))
    globe = Sphere(radius=.4, resolution=(7, 7)).shift(3 * RIGHT + 1.5 * DOWN)
    net = globe.get_points().copy()
    # A plain leaf under Phase A, a net under Phase B.
    globe.add_updater(lambda m: m.set_points(net))
    mover = Square(side_length=.4, fill_color=YELLOW, fill_opacity=1, stroke_color=BLUE, stroke_width=2).shift(DOWN)
    mover.add_updater(lambda m, dt: m.shift(.5 * dt * RIGHT))
    spinner = Line(ORIGIN, RIGHT, stroke_width=3).shift(2 * DOWN + LEFT)
    spinner.add_updater(lambda m, dt: m.rotate(dt))
    mobjects = (corners, framed, disc, ring, glyph, hidden, badge, dots, globe, mover, spinner)
    return SimpleNamespace(scene=build_scene(*mobjects))


def tick(side, dt=1 / 60):
    """What Scene.update_mobjects does to a fixture scene."""
    for mobject in side.scene.mobjects:
        mobject.update(dt)


# The camera moves of a pausepoint's proof: six pans, four zooms in and
# four out, each as (label, what it does to the camera frame).
CAMERA_MOVES = (*((f"pan {index}", lambda frame, sign=(-1) ** index: frame.shift(.05 * sign * RIGHT))
                  for index in range(6)),
                *((f"zoom in {index}", lambda frame: frame.scale(1 / 1.3)) for index in range(4)),
                *((f"zoom out {index}", lambda frame: frame.scale(1.3)) for index in range(4)))


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
    """The flag-on bytes are the flag-off bytes of the same history (B4.2,
    B4.3), and the flag-on scene is the scene the flag-off reads leave.

    The scripted sequence runs under each renderer: a cold frame, twenty
    stills that keep every leaf and reuse every descriptor, a leaf added,
    moved and removed, a child's z_index, a stroke moved behind (and the
    same flag and the depth test written as plain attributes), a client's
    connect (cache.reset()), the renderer switched and back (Phase A and
    Phase B each way, and Original 2D, which clears the triangle caches), a
    6x zoom and back followed by a paint-only edit (a kept leaf must keep
    its refined mesh and grown reservation), a pan, six pans, four zooms in
    and four out, a texture file rewritten in place (no revision moves),
    the flag turned off for a frame, a frame that raises, two plays
    (uniforms only; a program play, drawn from GPU programs under Phase B)
    and a cold cache.

    Beside it: a pausepoint whose updaters tick, most rewriting the same
    bytes each its own way and two really moving, through twenty ticks and
    the same camera moves; each way a moved revision can or cannot leave
    the drawn rows alone; a leaf compared and then prepared by a zoom; the
    reads that write to the scene or read other leaves (a program packing
    a later leaf's rows, a getter moving a later leaf or writing its rows
    without a bump, a frame refused before a leaf the walk found
    unchanged); uniforms a camera move changes; a full budget evicting in
    the frame's order, and a mesh no budget holds; the memos and the
    frame's own bytes bounded by one frame, and what the retired store and
    the gauge count; leaves read through getters of their own (a
    subclass's, an instance's), a point-cloud group rewriting its members,
    and the writes that bump no revision, which a kept leaf does not see
    until a bump has the frame's loop read them, cached reads or not. Then
    verification (B4.5): those writes refused, naming the leaf (a
    surface's too, whose read hands its cached grid back); every kept leaf
    read again, the frame keeping exactly what it keeps unverified, and
    every leaf that would adopt prepared, with the bytes still the
    flag-off bytes; and a rule that keeps or adopts a leaf its read draws
    otherwise (a verdict, a uniform set a camera move skipped) refused as
    the retained frame's own where, unverified, it sends the wrong draws.
    And the bytes policy, under which nothing is kept, retired or adopted.
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

    def test_scripted_sequence_as_a_format_8_stream(self):
        # The same history streamed (B4.8): the retained frame's deltas are
        # the whole-frame path's, byte for byte, silence included, across
        # resets, renderer switches, a refused frame and the flag's toggle.
        for renderer in RENDERERS:
            with self.subTest(renderer=renderer), tempfile.TemporaryDirectory() as tmp:
                self.scripted_sequence(renderer, Path(tmp) / "texture.bmp", deltas=True)

    def scripted_sequence(self, renderer, texture, deltas=False):
        other = "phase_b" if renderer == "phase_a" else "phase_a"
        write_texture(texture, 200)
        lock = Lockstep(self, lambda: lockstep_scene(texture), deltas=deltas)
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
        # Group.remove bumps every member of the group's family and changes
        # no row: every leaf is compared and kept.
        lock.step(lambda side: remove(side, "path"))
        lock.frame("remove the path", renderer)
        lock.expect(leaves_prepared=0, leaves_compared=10)
        # A z_index bumps the child's revision and changes none of its
        # rows: the leaf is kept, and only the order moves.
        lock.step(lambda side: setattr(side.family[1], "z_index", 5))
        lock.frame("child z_index 5", renderer)
        lock.expect(leaves_prepared=0, leaves_compared=1)
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
        # A camera move keeps every leaf whose counts it leaves alone (B4.3):
        # a pan all of them, the image and the surfaces included.
        for label, move in CAMERA_MOVES:
            lock.step(lambda side: move(side.scene.camera.frame))
            lock.frame(label, renderer)
            if label.startswith("pan"):
                lock.expect(leaves_prepared=0, batches_encoded=0)
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

        lock.fresh_caches()
        lock.frame("cold again", renderer)
        lock.frame("still", renderer)
        lock.expect(leaves_prepared=0, batches_encoded=0)

    def test_a_pausepoint_with_updaters(self):
        # The viewer ticks a pausepoint's updaters every frame (B4.3): the
        # leaves whose updaters change no byte are kept, whatever their
        # revision says, and the ones that move are prepared. Twenty ticks,
        # then the six pans, four zooms in and four out with the updaters
        # ticking, then the same moves with the scene still. Under Phase A
        # the glyph is prepared every tick too (updater_scene says why).
        for renderer in RENDERERS:
            with self.subTest(renderer=renderer):
                lock = Lockstep(self, updater_scene)
                leaves = 11
                moving = 3 if renderer == "phase_a" else 2
                lock.frame("cold", renderer)
                lock.frame("still", renderer)
                for index in range(20):
                    lock.step(tick)
                    lock.frame(f"tick {index}", renderer)
                    lock.expect(leaves_prepared=moving, leaves_compared=leaves - moving)
                for ticking in (True, False):
                    for label, move in CAMERA_MOVES:
                        lock.step(lambda side: (move(side.scene.camera.frame), ticking and tick(side)))
                        lock.frame(f"{label}{', ticking' if ticking else ''}", renderer)
                        if label.startswith("pan"):
                            # A pan changes no count: every leaf that is not
                            # moving is kept across it.
                            lock.expect(leaves_prepared=moving if ticking else 0,
                                        leaves_revalidated=leaves - moving if ticking else leaves)
                lock.frame("still", renderer)
                lock.expect(leaves_prepared=0, batches_encoded=0)

    def test_a_moved_revision_keeps_only_what_the_read_would_draw(self):
        # A leaf whose revision moved is kept only where prepare_leaf would
        # draw it as it stands (compare_rows): each step below either keeps
        # it or prepares it, and the lockstep holds the bytes, the caches
        # and the scene to the flag-off side's either way.
        def build():
            path = VMobject(stroke_color=YELLOW, stroke_width=4, fill_opacity=0)
            path.set_points_as_corners([[-2, 0, 0], [-1, .5, 0], [0, 0, 0], [1, .5, 0]])
            box = Square(side_length=.8, fill_color=BLUE, fill_opacity=1, stroke_color=WHITE,
                         stroke_width=2).shift(2 * RIGHT)
            hidden = VMobject(fill_opacity=0, stroke_width=0)
            hidden.set_points_as_corners([[-2, -1, 0], [2, -1, 0]])
            dots = DotCloud(np.array([[-2, 1.5, 0], [0, 1.6, 0], [2, 1.5, 0]]))
            globe = Sphere(radius=.4, resolution=(7, 7)).shift(2.5 * LEFT + 1.2 * DOWN)
            # A fill with no stroke and no border: under Phase A only its
            # mesh is read, which never refreshes its joint angles.
            blot = Circle(radius=.3, fill_color=RED, fill_opacity=1, stroke_width=0,
                          fill_border_width=0).shift(2.5 * RIGHT + 1.2 * DOWN)
            return SimpleNamespace(scene=build_scene(path, box, hidden, dots, globe, blot), path=path, box=box,
                                   hidden=hidden, dots=dots, globe=globe, blot=blot)

        def rewrite(side):
            side.path.set_points(side.path.get_points().copy())

        def bump(side):
            side.path.note_changed_data()

        def joint_angles(side):
            side.path.data["joint_angle"][:, 0] = .5
            side.path.note_changed_data()

        def negative_zero(side):
            side.path.data["point"][:, 2] = -0.0
            side.path.note_changed_data()

        def lock_joints(side):
            side.path.lock_data(["joint_angle"])
            rewrite(side)

        def unlock_joints(side):
            side.path.unlock_data()
            rewrite(side)

        def spelled(side):
            side.path.set_anti_alias_width(int(side.path.get_anti_alias_width()))

        def joints_flagged(name):
            def action(side):
                mobject = getattr(side, name)
                mobject.refresh_joint_angles()
                mobject.note_changed_data()
            return action

        def normal_written(side):
            # Another unit normal than the points give, which the joint
            # angles' refresh then reads.
            side.path.data["base_normal"][1::2] = [0, 0, -1]
            side.path.refresh_joint_angles()
            side.path.note_changed_data()

        def hidden_moves(side):
            side.hidden.set_points_as_corners([[-2, -1.2, 0], [2, -.8, 0]])

        def hidden_stroked(side):
            side.hidden.set_stroke(WHITE, width=2)

        def same_points(name):
            def action(side):
                mobject = getattr(side, name)
                mobject.set_points(mobject.get_points().copy())
            return action

        def shifted(name):
            return lambda side: getattr(side, name).shift(.1 * UP)

        def sorted_faces(side):
            side.globe.sort_faces_back_to_front(RIGHT)

        def steps(renderer):
            # (step, what it does, prepared, compared). Phase B reads the
            # blot's border source, through its shader data, and draws the
            # globe from its net.
            phase_a = renderer == "phase_a"
            return (
                (rewrite, "the same points set again: both flags, the rows the refresh makes", 0, 1),
                (bump, "a bump alone", 0, 1),
                (joint_angles, "joint angles written, no flag: the read draws them", 1, 0),
                (rewrite, "the same points again, over rows no refresh made", 1, 0),
                (rewrite, "and again, over the rows that refresh made", 0, 1),
                (negative_zero, "0.0 written as -0.0: equal values, other bytes", 1, 0),
                (lock_joints, "the joint angles locked: the refresh leaves them", 1, 0),
                (unlock_joints, "unlocked", 1, 0),
                (rewrite, "the same points once more", 0, 1),
                (spelled, "a uniform spelled 1 where it was 1.0", 1, 0),
                (joints_flagged("path"), "joint angles flagged alone: the stroke's read refreshes them as they were",
                 0, 1),
                (normal_written, "and from another unit normal, which the refresh reads", 1, 0),
                (rewrite, "the same points again, both flags", 1, 0),
                (rewrite, "and again", 0, 1),
                (joints_flagged("blot"), "and a fill's, which its read does not reach", 0 if phase_a else 1,
                 1 if phase_a else 0),
                (hidden_moves, "a path that draws nothing moved", 0, 1),
                (hidden_stroked, "and stroked", 1, 0),
                (same_points("dots"), "a dot cloud set to its own points", 0, 1),
                (shifted("dots"), "and shifted", 1, 0),
                (same_points("globe"), "a surface set to its own points", 0, 1),
                (shifted("globe"), "and shifted", 1, 0),
                # Its rows unchanged, its triangles reordered in place: a
                # grid draws them in the new order, a net draws no triangles.
                (sorted_faces, "its faces sorted", 1 if phase_a else 0, 0 if phase_a else 1),
            )

        for renderer in RENDERERS:
            with self.subTest(renderer=renderer):
                lock = Lockstep(self, build)
                lock.frame("cold", renderer)
                lock.frame("still", renderer)
                for action, label, prepared, compared in steps(renderer):
                    lock.step(action)
                    lock.frame(label, renderer)
                    lock.expect(leaves_prepared=prepared, leaves_compared=compared)

    def test_a_leaf_compared_and_then_prepared_is_compared_again(self):
        # A zoom that changes a curved stroke's count, in the frame its
        # revision moved over the same bytes: the walk compares it and the
        # camera check prepares it, with its caches stamped at the revision
        # the rows were compared at. They are the rows its new draws are
        # read from, so the next such bump keeps it.
        def build():
            ring = Circle(radius=.3, stroke_color=WHITE, stroke_width=3, fill_opacity=0)
            return SimpleNamespace(scene=build_scene(ring), ring=ring)

        def still_move(side):
            side.ring.move_to(side.ring.get_center())

        for renderer in RENDERERS:
            with self.subTest(renderer=renderer):
                lock = Lockstep(self, build)
                lock.frame("cold", renderer)
                lock.frame("still", renderer)
                lock.step(lambda side: (still_move(side), side.scene.camera.frame.scale(1 / 2)))
                lock.frame("a zero move and a zoom in", renderer)
                lock.expect(leaves_prepared=1, leaves_compared=0)
                lock.step(still_move)
                lock.frame("a zero move", renderer)
                lock.expect(leaves_prepared=0, leaves_compared=1)

    def test_a_program_reads_a_later_leaf_as_the_frame_leaves_it(self):
        # A program packs its endpoints' rows as they stand when its own
        # leaf is read. Here a Transform's target is a drawn leaf after the
        # start (aligned with it, so the play blends straight to it), whose
        # updater's become() copies in derived columns no read refreshed:
        # the frame's loop packs them unrefreshed, before the target's own
        # read refreshes them, and so must the retained frame, which keeps
        # the target by comparison and refreshes it in its own place.
        def build():
            template = Square(side_length=1, fill_color=RED, fill_opacity=.7, stroke_color=WHITE,
                              stroke_width=3).shift(2 * RIGHT)
            start = Square(side_length=1, fill_color=BLUE, fill_opacity=.7, stroke_color=WHITE,
                           stroke_width=3).shift(2 * LEFT)
            target = template.copy()
            target.add_updater(lambda m: m.become(template))
            return SimpleNamespace(scene=build_scene(start, target), start=start, target=target)

        programs.set_override("gpu")
        for renderer in RENDERERS:
            with self.subTest(renderer=renderer):
                lock = Lockstep(self, build)
                lock.frame("cold", renderer)
                for index in range(2):
                    lock.step(tick)
                    lock.frame(f"tick {index}", renderer)
                    lock.expect(leaves_prepared=0, leaves_compared=1)
                plays = [prepare_animation(Transform(side.start, side.target)) for side in lock.sides]
                for play, side in zip(plays, lock.sides):
                    play.begin()
                    self.assertIs(play.target_copy, side.target)
                for alpha in (0, .25, .5, .75):
                    lock.step(tick)
                    for play in plays:
                        play.interpolate(alpha)
                    lock.frame(f"play at {alpha}", renderer)
                    lock.expect(leaves_compared=1)
                for play in plays:
                    play.finish()
                lock.frame("lands", renderer)

    def test_a_read_that_moves_a_later_leaf(self):
        # The walk decides from each leaf as it stands, and the reads come
        # after it, in draw order. Here a leaf's own getter moves a later
        # leaf in the frame that leaf's revision moved over the same bytes:
        # the walk compares it and finds it unchanged, then the read moves
        # it. The frame's loop draws it moved; the retained frame prepares
        # it rather than keep what the walk vouched for, or stamp its caches
        # with the revision the move made. So too where the getter writes
        # its rows without a bump: the frame's loop reads a leaf whose
        # revision moved from its arrays and draws the write, so the
        # retained frame compares it again in its place once a getter of a
        # leaf's own has run, rather than stamp the caches' old reads with
        # its revision, which would keep them on screen until its next
        # bump.
        def build(quietly=False):
            driver = MovesAnother(side_length=.5, fill_opacity=0, stroke_width=3)
            follower = Circle(radius=.4, fill_color=RED, fill_opacity=1, stroke_color=BLUE,
                              stroke_width=2).shift(2 * RIGHT)
            driver.follower, driver.quietly = follower, quietly
            return SimpleNamespace(scene=build_scene(driver, follower), driver=driver, follower=follower)

        def arm(side):
            side.follower.shift(0 * UP)
            side.driver.armed = True

        for renderer, quietly in itertools.product(RENDERERS, (False, True)):
            with self.subTest(renderer=renderer, quietly=quietly):
                lock = Lockstep(self, lambda: build(quietly))
                lock.frame("cold", renderer)
                still = lock.frame("still", renderer)
                lock.step(arm)
                self.assertNotEqual(lock.frame("the follower moved by the driver's read", renderer), still)
                # The driver, read through its own getter, is prepared every frame.
                lock.expect(leaves_prepared=2, leaves_compared=0)
                for index in range(3):
                    lock.frame(f"still {index}", renderer)
                    lock.expect(leaves_prepared=1)

    def test_a_refused_frame_leaves_the_later_leaves_alone(self):
        # A frame refused at a leaf has read the leaves before it and none
        # after. Here the leaf after the refused one is kept by comparison
        # (become() of an unchanged target), and its refresh must wait for
        # its own place in the order, which the refused frame never
        # reaches: Lockstep.raises holds the two scenes equal, and a lock
        # of its joint angles before the next frame keeps whatever rows
        # each side left.
        flat = [[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0], [0, 0, 0]]
        bent = [[0, 0, 0], [1, 0, 0], [1, 1, 1], [0, 1, 0], [0, 0, 0]]

        def build():
            refused = VMobject(fill_color=RED, fill_opacity=1, stroke_width=0).set_points_as_corners(flat)
            template = Square(side_length=.9, fill_color=RED, fill_opacity=.7, stroke_color=WHITE, stroke_width=3)
            framed = template.copy()
            return SimpleNamespace(scene=build_scene(refused.shift(3 * LEFT), framed), refused=refused,
                                   template=template, framed=framed)

        for renderer in RENDERERS:
            with self.subTest(renderer=renderer):
                lock = Lockstep(self, build)
                lock.frame("cold", renderer)
                lock.frame("still", renderer)
                lock.step(lambda side: side.framed.become(side.template))
                lock.frame("become", renderer)
                lock.expect(leaves_prepared=0, leaves_compared=1)
                lock.step(lambda side: (side.framed.become(side.template), side.refused.set_points_as_corners(bent)))
                lock.raises("a nonplanar fill before it", triangle_scene.UnsupportedPrototype, renderer)
                lock.step(lambda side: (side.framed.lock_data(["joint_angle"]),
                                        side.refused.set_points_as_corners(flat).shift(3 * LEFT)))
                lock.frame("the joint angles locked", renderer)

    def test_uniforms_a_camera_move_changes(self):
        # A batch prints its draw's uniforms where they differ from the
        # camera's. One whose leaf sets a camera uniform of its own prints
        # it only while the two differ, so its descriptor is encoded again
        # after a camera move, where the others are reused; and a leaf
        # whose own uniforms hold a NaN draws with a dict of its own, which
        # no camera move is written into, so it is prepared again.
        def build():
            plain = Square(side_length=.6, fill_color=BLUE, fill_opacity=1, stroke_width=2).shift(2 * LEFT)
            named = Square(side_length=.6, fill_color=RED, fill_opacity=1, stroke_width=2)
            odd = Square(side_length=.6, fill_color=GREEN, fill_opacity=1, stroke_width=2).shift(2 * RIGHT)
            scene = build_scene(plain, named, odd)
            scene.camera.refresh_uniforms()
            named.set_uniform(frame_scale=scene.camera.uniforms["frame_scale"])
            odd.set_uniform(unused=float("nan"))
            return SimpleNamespace(scene=scene)

        for renderer in RENDERERS:
            with self.subTest(renderer=renderer):
                lock = Lockstep(self, build)
                lock.frame("cold", renderer)
                lock.frame("still", renderer)
                lock.step(lambda side: side.scene.camera.frame.scale(1.2))
                lock.frame("zoom out", renderer)
                lock.expect(leaves_prepared=1, leaves_revalidated=2)
                self.assertGreater(lock.retained.stats["batches_encoded"], 0)
                self.assertGreater(lock.retained.stats["batches_reused"], 0)
                lock.step(lambda side: side.scene.camera.frame.scale(1 / 1.2))
                lock.frame("zoom back", renderer)
                lock.frame("still", renderer)

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

    def test_a_mesh_the_cache_does_not_hold_is_made_at_every_camera(self):
        # A fill mesh larger than the mesh cache's budget is drawn and not
        # retained, so the frame's loop makes it again every frame, at that
        # frame's camera. A kept leaf's draws hold the mesh made last: the
        # same bytes while the camera stands, a coarser one after a zoom in,
        # so on a camera move the leaf is prepared. A zero budget stands for
        # a mesh over 64 MiB. The retained frame then holds meshes no cache
        # counts, which its gauge does. Phase A only: patch fills keep no
        # meshes.
        def build():
            discs = [Circle(radius=radius, fill_color=color, fill_opacity=1, stroke_width=0,
                            fill_border_width=0).shift(x * RIGHT)
                     for radius, color, x in ((1.5, RED, 0), (.2, BLUE, 3))]
            return SimpleNamespace(scene=build_scene(*discs))

        def mesh_bytes():
            return sum(draw.vertices.nbytes + draw.indices.nbytes
                       for entry in lock.retained.leaves.values() for draw in entry.leaf.draws)

        lock = Lockstep(self, build)
        lock.frame("cold")
        lock.frame("still")
        held = lock.retained.retained_bytes()
        for cache in lock.caches:
            cache.triangle_meshes.max_bytes = 0
        # The first read evicts both entries, the second disc's before it
        # is read; the first disc's goes the frame after.
        lock.frame("the budget emptied")
        lock.frame("still")
        lock.frame("still")
        lock.expect(leaves_prepared=0, batches_encoded=0)
        self.assertEqual(lock.retained.retained_bytes() - held, mesh_bytes())
        for index in range(3):
            lock.step(lambda side: side.scene.camera.frame.scale(1 / 3))
            lock.frame(f"zoom in {index}")
            lock.expect(leaves_prepared=2)
        lock.step(lambda side: side.scene.camera.frame.shift(.2 * RIGHT))
        lock.frame("a pan")
        lock.expect(leaves_prepared=2)

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

    def test_the_retired_store_counts_what_its_entries_hold(self):
        # A parked path's entry counts every array it keeps alive against
        # the caches' budget (B4.4), the patch fill's object words and
        # paint field among them, which the border cache's own count of a
        # source leaves out: eighteen stroked circles with a gradient fill
        # taken off at once. And the retained frame's gauge counts the
        # texture payloads a kept textured leaf carries, which live outside
        # the texture read cache's bound while the leaf is drawn.
        def arrays(entry):
            held = {}
            reached = [entry.rows]
            if entry.mesh_entry is not None:
                reached += [*entry.mesh_entry.source.arrays(), *entry.mesh_entry.geometry.arrays()]
                if entry.mesh_entry.paint_field is not None:
                    reached.append(entry.mesh_entry.paint_field.wire())
            source = entry.source_entry
            if source is not None:
                reached += [*source.source.arrays(), source.rgba, source.curves, source.record, source.paint]
            reached += [getattr(draw, name) for draw in entry.leaf.draws
                        for name in ("vertices", "indices", "paint", "border_sources", "fill_objects")]
            for array in reached:
                if isinstance(array, np.ndarray):
                    while isinstance(array.base, np.ndarray):
                        array = array.base
                    held[id(array)] = array.nbytes
            return held

        for renderer in RENDERERS:
            with self.subTest(renderer=renderer), patch.dict(os.environ, {RETAINED_ENV: "1"}):
                shapes = VGroup(*(Circle(radius=.3, stroke_width=2).set_fill([RED, YELLOW, BLUE, GREEN], opacity=1)
                                  .shift((index % 6 - 2.5) * RIGHT + (index // 6 - 1) * UP) for index in range(18)))
                scene, cache = build_scene(shapes), GeometryCache()
                for _ in range(2):
                    serialize_scene(scene, cache, renderer=renderer)
                scene.mobjects.remove(shapes)
                scene.render_groups[0].remove(shapes)
                serialize_scene(scene, cache, renderer=renderer)
                retained = cache.retained_frame
                self.assertEqual(len(retained.retired), 18)
                self.assertEqual(retained.retired_bytes,
                                 sum(sum(arrays(entry).values()) for entry in retained.retired.values()))
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {RETAINED_ENV: "1"}):
            texture = Path(folder) / "texture.bmp"
            write_texture(texture, 40)
            scene = build_scene(ImageMobject(str(texture), height=1.2))
            cache = GeometryCache()
            held = []
            for _ in range(3):
                serialize_scene(scene, cache)
                held.append(cache.retained_frame.retained_bytes())
            self.assertEqual(cache.retained_frame.stats["leaves_kept"], 1)
            self.assertEqual(held[2], held[1])
            with patch.object(cache.retained_frame.leaves[id(scene.mobjects[0])].leaf, "textures", None):
                self.assertEqual(held[2] - cache.retained_frame.retained_bytes(), texture.stat().st_size)

    def test_a_surface_written_in_place(self):
        # A surface's grid (Phase A) is cached per revision
        # (Surface.get_grid_data), so a write to its rows that bumps
        # nothing is drawn by neither path, and its read hands the cached
        # grid back: verification (B4.5) holds a kept plain leaf to the
        # rows its draws were made from as well, and refuses the write on
        # the flag-on side. Under Phase B the net cache compares the rows
        # itself, and both sides refuse it.
        def build():
            globe = Sphere(radius=.6, resolution=(7, 7)).shift(RIGHT)
            return SimpleNamespace(scene=build_scene(globe), globe=globe)

        def write(side):
            side.globe.data["point"][:, 0] += .5

        for renderer, verifying in itertools.product(RENDERERS, (False, True)):
            with self.subTest(renderer=renderer, verifying=verifying), \
                    patch.dict(os.environ, {"MANIML_VERIFY_LEDGER": "1" if verifying else "0"}):
                lock = Lockstep(self, build)
                lock.frame("cold", renderer)
                still = lock.frame("still", renderer)
                lock.step(write)
                if not verifying:
                    self.assertEqual(lock.frame("written in place", renderer), still)
                elif renderer == "phase_b":
                    lock.raises("written in place", RenderCacheStale, renderer)
                else:
                    self.assertEqual(lock.serialize(0, renderer, False), still)
                    with self.assertRaises(RenderCacheStale) as refused:
                        lock.serialize(1, renderer, True)
                    self.assertIn("Sphere (leaf 0 of the draw order) changed in 'point' since its last frame "
                                  "without a revision bump", str(refused.exception))

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
                # Only the second member has a dot past 1.5: the first is
                # bumped with its rows unchanged, and kept.
                lock.step(lambda side: side.group.filter_out(lambda p: p[0] > 1.5))
                lock.frame("filtered", renderer)
                lock.expect(leaves_prepared=1, leaves_compared=1)
                lock.step(lambda side: side.group.filter_out(lambda p: p[1] > .5))
                lock.frame("one member emptied", renderer)
                lock.frame("still", renderer)
                lock.expect(leaves_prepared=0)

    def test_writes_that_bump_no_revision(self):
        # In-place writes the revision contract does not cover: the frame's
        # loop reads each of these every frame, so the flag-off path draws
        # them on its next frame, while a kept leaf keeps its draws until
        # its revision moves. Under MANIML_VERIFY_LEDGER=1 the retained
        # frame reads every leaf it keeps as well (B4.5) and refuses the
        # frame with RenderCacheStale naming the leaf, its place in the
        # draw order and what moved; where a cache's own check sees the
        # write first (the patch fill's border source compares every
        # column), both sides refuse it there. Each write is run both ways,
        # whatever the suite's switch.
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

        # (write, the leaf the refusal names, what moved)
        writes = ((stroke_color, "Square (leaf 0 of the draw order)", "'stroke_rgba'"),
                  (uniform, "Square (leaf 0 of the draw order)", "uniforms['anti_alias_width']"),
                  (radius, "DotCloud (leaf 4 of the draw order)", "'radius'"),
                  (point_view, "VMobject (leaf 3 of the draw order)", "'point'"))
        for (write, leaf, moved), renderer, verifying in itertools.product(writes, RENDERERS, (False, True)):
            with self.subTest(write=write.__name__, renderer=renderer, verifying=verifying), \
                    patch.dict(os.environ, {"MANIML_VERIFY_LEDGER": "1" if verifying else "0"}):
                lock = Lockstep(self, build)
                lock.frame("cold", renderer)
                still = lock.frame("still", renderer)
                lock.step(write)
                if not verifying:
                    off, on = lock.messages(renderer)
                    self.assertNotEqual(off, still, "the frame's loop did not see the write")
                    self.assertEqual(on, still, "a kept leaf saw a write that bumped nothing")
                    self.assertEqual(lock.retained.stats["leaves_prepared"], 0)
                    continue
                try:
                    lock.serialize(0, renderer, False)
                except RenderCacheStale:
                    self.assertEqual((write, renderer), (stroke_color, "phase_b"), "a cache saw the write")
                    with self.assertRaises(RenderCacheStale):
                        lock.serialize(1, renderer, True)
                    continue
                with self.assertRaises(RenderCacheStale) as refused:
                    lock.serialize(1, renderer, True)
                self.assertIn(leaf, str(refused.exception))
                self.assertIn(f"changed in {moved}", str(refused.exception))
                # A refused frame leaves the retained frame cold.
                self.assertEqual(lock.retained.leaves, {})

    def test_a_bump_after_a_write_no_read_saw(self):
        # A cache that holds a read made at a leaf's revision hands it back
        # without reading the arrays: a fill's mesh or border source, a
        # surface's grid or net. So a write that bumps nothing goes unseen
        # with the flag off too while the revision stands, even through a
        # frame that prepares the leaf again (stroke_behind set as an
        # attribute, a zoom that refines the mesh, a retained frame made
        # anew over warm caches), whose draws are made from the rows the
        # cached read was made from, not the arrays. The bump after it has
        # the frame's loop read the arrays and draw the write. A kept leaf
        # held to the written rows would find them unchanged and keep the
        # old draws, and stamp the caches' old reads with the new revision,
        # so that the flag-off path on the same caches would trust them
        # too: the last frame serializes the flag-on side's caches with the
        # flag off.
        def build():
            disc = Circle(radius=.5, fill_color=RED, fill_opacity=1, stroke_width=0, fill_border_width=0)
            globe = Sphere(radius=.4, resolution=(7, 7)).shift(2 * RIGHT)
            return SimpleNamespace(scene=build_scene(disc, globe), disc=disc, globe=globe)

        def write(side):
            for mobject in (side.disc, side.globe):
                mobject.data["point"][:, 0] += .5

        def behind(lock, renderer):
            lock.step(lambda side: [setattr(mobject, "stroke_behind", True) for mobject in (side.disc, side.globe)])
            lock.frame("stroke_behind set as an attribute", renderer)

        def zoom(lock, renderer):
            lock.step(lambda side: side.scene.camera.frame.scale(1 / 6))
            lock.frame("a zoom in", renderer)

        def anew(lock, renderer):
            lock.frame("the flag off", renderer, retained=False)
            lock.frame("the flag on again", renderer)

        def bump(side):
            for mobject in (side.disc, side.globe):
                mobject.note_changed_data()

        for renderer in RENDERERS:
            for trigger in (behind, zoom, anew):
                with self.subTest(renderer=renderer, trigger=trigger.__name__):
                    lock = Lockstep(self, build)
                    lock.frame("cold", renderer)
                    lock.frame("still", renderer)
                    lock.step(write)
                    if verifying():
                        # Verification compares every trusted read: the
                        # write is refused where the cache reuses the read.
                        lock.raises("written in place", RenderCacheStale, renderer)
                        continue
                    still = lock.frame("written in place", renderer)
                    trigger(lock, renderer)
                    lock.step(bump)
                    self.assertNotEqual(lock.frame("a bump over the written rows", renderer), still)
                    lock.frame("the flag-on side's caches with the flag off", renderer, retained=False)


    def test_verification_reads_every_leaf_it_keeps(self):
        # Under MANIML_VERIFY_LEDGER=1 (B4.5) every leaf the frame keeps is
        # read as well, and the frame is still the flag-off frame of the
        # same history, and keeps exactly what it keeps without the switch:
        # a pausepoint's updaters ticking, then the camera moves (a fill's
        # mesh held to its error bound and read through mesh(), a border
        # source packed again by a zoom's read). And a rule that keeps a
        # leaf its read draws otherwise is refused at that leaf, as the
        # retained frame's own, where without the switch the frame sends
        # the old draws: compare_rows finding every moved path unchanged
        # (a line an updater moves keeps its old stroke), or refreshing a
        # path whose joint angles are locked (the read keeps the locked
        # ones, the rule would write the refreshed ones over them). Nothing
        # is written or stamped for a kept leaf before its read, so the
        # read refreshes the path itself and no cache vouches for rows the
        # rule compared.
        def decisions(renderer, verify):
            counts = []
            with patch.dict(os.environ, {"MANIML_VERIFY_LEDGER": "1" if verify else "0"}):
                lock = Lockstep(self, updater_scene)
                lock.frame("cold", renderer)
                steps = [(f"frame {index}", tick if index > 1 else None) for index in range(8)]
                steps += [(label, lambda side, move=move: (move(side.scene.camera.frame), tick(side)))
                          for label, move in CAMERA_MOVES]
                for label, step in steps:
                    if step is not None:
                        lock.step(step)
                    lock.frame(label, renderer)
                    stats = lock.retained.stats
                    counts.append((label, *(stats[key] for key in ("leaves_kept", "leaves_prepared",
                                                                   "leaves_compared", "leaves_revalidated"))))
                    if verify:
                        self.assertEqual(stats["leaves_verified"], stats["leaves_kept"], label)
            return counts

        for renderer in RENDERERS:
            with self.subTest(renderer=renderer):
                verified = decisions(renderer, True)
                self.assertEqual(verified, decisions(renderer, False))
                self.assertEqual([kept > (5 if index else 10) for index, (_, kept, *_) in enumerate(verified[:8])],
                                 [True] * 8)
                self.assertTrue(all(revalidated for *_, revalidated in verified[8:]))

        def build():
            square = Square(side_length=.6, fill_color=RED, fill_opacity=1, stroke_width=2).shift(RIGHT)
            line = Line(LEFT, ORIGIN, stroke_width=3).shift(DOWN)
            line.add_updater(lambda m, dt: m.shift(dt * UP))
            return SimpleNamespace(scene=build_scene(square, line))

        def build_locked():
            path = VMobject(stroke_color=WHITE, stroke_width=6, fill_opacity=0)
            path.set_points_as_corners([[-2, -1, 0], [-.5, 1, 0], [.5, -1, 0], [2, 1, 0]])
            return SimpleNamespace(scene=build_scene(path), path=path)

        def lock_joints(side):
            # Written and locked as lock_data leaves them, then flagged and
            # bumped: the read refreshes nothing it may not.
            path = side.path
            path.data["joint_angle"][:, 0] = .3
            path.locked_data_keys = {"joint_angle"}
            path.refresh_joint_angles()
            path.note_changed_data()

        def ignoring_the_lock(sm, entry):
            locked, sm.locked_data_keys = sm.locked_data_keys, set()
            try:
                return compare_rows(sm, entry)
            finally:
                sm.locked_data_keys = locked

        def build_disc():
            disc = Circle(radius=.8, fill_color=BLUE, fill_opacity=1, stroke_width=0, fill_border_width=0)
            return SimpleNamespace(scene=build_scene(disc), disc=disc)

        def unchanged(sm, entry):
            return retained_frame.SAME

        compare_rows = retained_frame.compare_rows
        rules = (("every moved path unchanged", unchanged, build, tick,
                  "Line (leaf 1 of the draw order) was kept over a moved revision, its rows judged 'same'", "'point'"),
                 ("every moved fill unchanged", unchanged, build_disc, lambda side: side.disc.shift(.5 * UP),
                  "Circle (leaf 0 of the draw order) was kept over a moved revision, its rows judged 'same'",
                  "'point'"),
                 ("a refresh that ignores the lock", ignoring_the_lock, build_locked, lock_joints,
                  "VMobject (leaf 0 of the draw order) was kept over a moved revision, its rows judged 'refreshed'",
                  "'joint_angle'"))
        for (rule, compare, scene, step, leaf, moved), renderer, verifying in itertools.product(
                rules, RENDERERS, (False, True)):
            with self.subTest(renderer=renderer, verifying=verifying, rule=rule), \
                    patch.dict(os.environ, {"MANIML_VERIFY_LEDGER": "1" if verifying else "0"}):
                lock = Lockstep(self, scene)
                lock.frame("cold", renderer)
                lock.frame("still", renderer)
                lock.step(step)
                with patch.object(retained_frame, "compare_rows", compare):
                    if not verifying:
                        off, on = lock.messages(renderer)
                        self.assertNotEqual(on, off, "the rule kept no leaf its read draws otherwise")
                        continue
                    lock.serialize(0, renderer, False)
                    with self.assertRaises(RenderCacheStale) as refused:
                        lock.serialize(1, renderer, True)
                self.assertIn(leaf, str(refused.exception))
                self.assertIn(moved, str(refused.exception))
                self.assertIn("the retained frame's own rule is at fault", str(refused.exception))
                # The kept leaf was read before anything was stamped for it,
                # so the refusal leaves no cache vouching for the rows the
                # rule compared: with the rule mended and a client connected
                # (every batch sent in full), the frame is the flag-off
                # frame again.
                for cache in lock.caches:
                    cache.reset()
                lock.frame("the rule mended, a client connected", renderer)

    def test_verification_prepares_what_it_would_adopt(self):
        # A path that would adopt a retired entry is prepared instead under
        # MANIML_VERIFY_LEDGER=1, and counted prepared, and the entry's
        # draws and uniform set are held to that read's (B4.5): the disc
        # taken off and put back in one frame is prepared and matches; a
        # digest that ignores the rows, with compare_rows finding them
        # unchanged, has a wider disc adopt the narrower one's mesh; and a
        # camera move that is not written into one uniform set has a line
        # put back across a pan adopt draws of the old camera. Without the
        # switch both are sent, with it refused.
        def build():
            disc = Circle(radius=.5, fill_color=BLUE, fill_opacity=1, stroke_width=0,
                          fill_border_width=0).shift(LEFT)
            square = Square(side_length=.6, fill_color=RED, fill_opacity=1, stroke_width=0).shift(RIGHT)
            return SimpleNamespace(scene=build_scene(square, disc), disc=disc)

        def replaced(radius=None):
            # By a copy (as a thaw puts one back), or by a new disc.
            def action(side):
                disc = side.disc
                remove(side, "disc")
                add(side, "disc", disc.copy() if radius is None else
                    Circle(radius=radius, fill_color=BLUE, fill_opacity=1, stroke_width=0,
                           fill_border_width=0).shift(LEFT))
            return action

        with patch.dict(os.environ, {"MANIML_VERIFY_LEDGER": "1"}):
            for renderer in RENDERERS:
                with self.subTest(renderer=renderer):
                    lock = Lockstep(self, build)
                    lock.frame("cold", renderer)
                    lock.frame("still", renderer)
                    lock.step(replaced())
                    lock.frame("the disc replaced by its copy", renderer)
                    self.assertEqual({key: lock.retained.stats[key] for key in
                                      ("leaves_kept", "leaves_prepared", "leaves_adopted", "leaves_verified")},
                                     {"leaves_kept": 1, "leaves_prepared": 1, "leaves_adopted": 0,
                                      "leaves_verified": 2})

        def rowless(type_name, text, flags, rows):
            return hashlib.blake2b(f"{type_name} {text} {flags}".encode(), digest_size=16).digest()

        with patch.object(retained_frame, "leaf_digest", rowless), \
                patch.object(retained_frame, "compare_rows", lambda sm, entry: retained_frame.SAME):
            for renderer, verifying in itertools.product(RENDERERS, (False, True)):
                with self.subTest(renderer=renderer, verifying=verifying, rule="a digest without the rows"), \
                        patch.dict(os.environ, {"MANIML_VERIFY_LEDGER": "1" if verifying else "0"}):
                    lock = Lockstep(self, build)
                    lock.frame("cold", renderer)
                    lock.frame("still", renderer)
                    lock.step(replaced(.8))
                    if not verifying:
                        off, on = lock.messages(renderer)
                        self.assertEqual(lock.retained.stats["leaves_adopted"], 1)
                        self.assertNotEqual(on, off, "the wider disc drew its own mesh")
                        continue
                    lock.serialize(0, renderer, False)
                    with self.assertRaises(RenderCacheStale) as refused:
                        lock.serialize(1, renderer, True)
                    self.assertIn("Circle (leaf 1 of the draw order) would adopt the draws of a retired Circle",
                                  str(refused.exception))

        def build_marked():
            square = Square(side_length=.6, fill_color=RED, fill_opacity=1, stroke_width=0).shift(RIGHT)
            line = Line(LEFT, ORIGIN, stroke_width=3).shift(DOWN)
            line.set_uniform(marked=1.0)  # a uniform set of its own
            return SimpleNamespace(scene=build_scene(square, line), line=line)

        def panned_and_put_back(side):
            side.scene.camera.frame.shift(.3 * RIGHT)
            add(side, "line", side.line.copy())

        camera_moved = retained_frame.UniformSets.camera_moved

        def forgets_one(sets, camera):
            # The set of the marked line keeps the camera it was made with.
            held = [(merged, dict(merged)) for merged, overrides in sets.sets.values() if "marked" in overrides]
            followed = camera_moved(sets, camera)
            for merged, before in held:
                merged.clear()
                merged.update(before)
            return followed

        with patch.object(retained_frame.UniformSets, "camera_moved", forgets_one):
            for renderer, verifying in itertools.product(RENDERERS, (False, True)):
                with self.subTest(renderer=renderer, verifying=verifying, rule="a set the camera skips"), \
                        patch.dict(os.environ, {"MANIML_VERIFY_LEDGER": "1" if verifying else "0"}):
                    lock = Lockstep(self, build_marked)
                    lock.frame("cold", renderer)
                    lock.frame("still", renderer)
                    lock.step(lambda side: remove(side, "line"))
                    lock.frame("the line taken off", renderer)
                    lock.step(panned_and_put_back)
                    if not verifying:
                        off, on = lock.messages(renderer)
                        self.assertEqual(lock.retained.stats["leaves_adopted"], 1)
                        self.assertNotEqual(on, off, "the line drew under the camera it was put back under")
                        continue
                    lock.serialize(0, renderer, False)
                    with self.assertRaises(RenderCacheStale) as refused:
                        lock.serialize(1, renderer, True)
                    self.assertIn("Line (leaf 1 of the draw order) would adopt the draws of a retired Line of equal "
                                  "content made with a uniform set other than its own", str(refused.exception))

    def test_the_bytes_policy_keeps_no_leaf(self):
        # MANIML_RENDER_CACHE=bytes compares every array every frame: the
        # retained frame keeps, retires and adopts nothing (B4.5), so a
        # write that bumps no revision is drawn on the next frame, as the
        # flag-off path draws it, and a path taken off and put back is
        # prepared.
        def build():
            scene, family, path, cloud, _ = synthetic_scene()
            return SimpleNamespace(scene=scene, family=family, path=path, cloud=cloud)

        with patch.dict(os.environ, {"MANIML_RENDER_CACHE": "bytes"}):
            for renderer in RENDERERS:
                with self.subTest(renderer=renderer):
                    lock = Lockstep(self, build)
                    lock.frame("cold", renderer)
                    still = lock.frame("still", renderer)
                    self.assertEqual({key: lock.retained.stats[key] for key in ("leaves_kept", "leaves_prepared")},
                                     {"leaves_kept": 0, "leaves_prepared": 6})
                    lock.step(lambda side: side.family[0].data["stroke_rgba"].__setitem__((slice(None), 0), 0))
                    self.assertNotEqual(lock.frame("written in place", renderer), still)
                    lock.step(lambda side: remove(side, "path"))
                    lock.frame("the path taken off", renderer)
                    lock.step(lambda side: add(side, "path", side.path.copy()))
                    lock.frame("a copy put back", renderer)
                    self.assertEqual({key: lock.retained.stats[key] for key in ("leaves_kept", "leaves_adopted")},
                                     {"leaves_kept": 0, "leaves_adopted": 0})
                    self.assertEqual(len(lock.retained.retired), 0)


class RowSourcesLockstep(RetainedFrameLockstep):
    """Every lockstep above with Phase B's patch fills and strokes sent as
    rows (MANIML_PATCH_SOURCE=rows, docs/phase_b4_plan.md B5.1): the rows
    entry is the border cache's, kept, compared, parked and adopted as a
    curve source is, and a stroke's rows are compared every frame as its
    shader data is read every frame, so the same writes that bump nothing
    stay off a kept leaf and reach the frame's loop."""

    def setUp(self):
        super().setUp()
        self.enterContext(patch.dict(os.environ, MANIML_PATCH_SOURCE="rows"))


@requires_lyon
class StrokeProgramsLockstep(GoldenCase):
    """B5.3 (docs/phase_b4_plan.md): Phase A under MANIML_PROGRAMS=strokes.
    A play whose paths without fill are GPU programs (a creation, a
    rotation, a fade in, which is a blend) beside a filled leaf's move,
    which keeps the CPU path: the retained frame's bytes are the
    whole-frame path's at every frame, as full frames and as a format 8
    stream, verified or not; a program leaf is prepared every frame it is
    one, and the still after the landing keeps every leaf."""

    def setUp(self):
        self.enterContext(patch.dict(os.environ, MANIML_PROGRAMS="strokes"))

    def test_a_play_of_paths_without_fill(self):
        for deltas, verify in ((False, None), (True, None), (False, "1")):
            with self.subTest(deltas=deltas, verify=verify), patch.dict(os.environ):
                if verify is not None:
                    os.environ["MANIML_VERIFY_LEDGER"] = verify
                self.play_of_paths_without_fill(deltas)

    def play_of_paths_without_fill(self, deltas):
        def build():
            scene, family, path, _, _ = synthetic_scene()
            side = SimpleNamespace(scene=scene, family=family, path=path)
            add(side, "ring", Circle(radius=.5, stroke_color=WHITE, stroke_width=4).shift(2 * LEFT + 1.5 * UP))
            add(side, "dashes", DashedLine(3 * LEFT + 2.2 * DOWN, 3 * RIGHT + 2.2 * DOWN, stroke_width=3))
            return side

        # The default stack, which the environment's strokes governs: Phase
        # A forced ("phase_a") draws no programs.
        lock, renderer = Lockstep(self, build, deltas=deltas), "triangles"
        lock.frame("cold", renderer)
        lock.frame("still", renderer)
        lock.expect(leaves_prepared=0)
        plays = [[prepare_animation(animation) for animation in (
            ShowCreation(side.path), Rotate(side.ring, 1.0), FadeIn(side.dashes), side.family[0].animate.shift(.3 * UP))]
            for side in lock.sides]
        for animation in (animation for group in plays for animation in group):
            animation.begin()
        lock.frame("the play begins", renderer)
        headers = []
        for alpha in (.25, .5, .75):
            for animation in (animation for group in plays for animation in group):
                animation.interpolate(alpha)
            message = lock.frame(f"the play at {alpha}", renderer)
            headers.append(parse_geometry_message(message)[0])
            # The path, the ring and every dash, and nothing filled.
            self.assertEqual(lock.retained.stats["leaves_prepared"], 2 + len(lock.sides[1].dashes) + 1)
        for animation in (animation for group in plays for animation in group):
            animation.finish()
        lock.frame("the play lands", renderer)
        lock.frame("still", renderer)
        lock.expect(leaves_prepared=0)
        if deltas:
            self.assertTrue(all(header["scalars"] for header in headers[1:]))
        else:
            kinds = {batch["program"]["kind"] for header in headers for batch in header["batches"] if "program" in batch}
            self.assertEqual(kinds, {"partial", "affine", "blend"})
            self.assertTrue(all(batch["pipeline"] == "stroke" for header in headers
                                for batch in header["batches"] if "program" in batch))


@requires_lyon
class AdoptionMirrorsTheRead(unittest.TestCase):
    """TriangleMeshCache.adopt and BorderRecipeCache.adopt (B4.4) leave
    their caches as the reads they stand in for: adopting, for an object a
    cache holds nothing of, the entries read for another object of equal
    content is prepare_leaf's generation and packing for it, bar the work.
    Two caches with one history; then a frame in which a copy of one leaf
    is read in the first and adopted in the second, the leaf it copies no
    longer drawn. Compared right after, before the sweep hides what the
    frame's own insertions did: the entries in their order, the bytes, the
    evictions, the reservations, the arrays drawn. Under a budget with room
    to spare, and one with none, where the insertions evict."""

    def shapes(self):
        # A bordered disc; a disc whose fill varies, so its read builds a
        # paint field; a disc shaded for its first frame, whose mesh keeps
        # the paint field that built after the shading is gone (a read of
        # a new object builds none); and the square they leave room for.
        return [Circle(radius=.5, fill_color=GREEN, fill_opacity=.9, stroke_width=0, fill_border_width=2),
                Circle(radius=.4, fill_opacity=1, stroke_width=0, fill_border_width=0).set_fill([RED, BLUE])
                .shift(1.5 * RIGHT),
                Circle(radius=.3, fill_color=BLUE, fill_opacity=1, stroke_width=0, fill_border_width=0)
                .set_shading(.5, .2, .1).shift(UP),
                Square(side_length=.6, fill_color=YELLOW, fill_opacity=1, stroke_width=0).shift(1.5 * LEFT)]

    def census(self, meshes):
        border = meshes.gpu_border_cache
        return ([(key, entry.nbytes, entry.revision, entry.last_frame, entry.made_under)
                 for key, entry in meshes._entries.items()],
                meshes._bytes, meshes.stats["evictions"],
                {key: held[1:] for key, held in meshes._classes.items()},
                [(key, entry.nbytes, entry.frame) for key, entry in border.sources.items()], border.nbytes,
                {key: held[1:] for key, held in border.capacities.items()})

    def test_adoption_is_the_read(self):
        for spare in (None, 0):
            for index in range(3):
                with self.subTest(spare=spare, leaf=index):
                    self.adoption(spare, index)

    def adoption(self, spare, index):
        tessellator = LyonFillTessellator()
        shapes = self.shapes()
        scene = build_scene(*shapes)
        caches = (triangle_scene.TriangleMeshCache(), triangle_scene.TriangleMeshCache())
        options = dict(fill_borders=True, gpu_borders=True)
        for cache in caches:
            triangle_scene.prepare_triangle_frame(scene, tessellator, mesh_cache=cache, **options)
        shapes[2].set_shading(0, 0, 0)
        for cache in caches:
            triangle_scene.prepare_triangle_frame(scene, tessellator, mesh_cache=cache, **options)
        self.assertIsNotNone(caches[0]._entries[id(shapes[2])].paint_field)
        retired = shapes[index]
        copy = retired.copy()
        scene = build_scene(copy, shapes[3])
        if spare is not None:
            # The meshes' own bytes: the border sources' share is gone too.
            for cache in caches:
                cache.max_bytes = cache._bytes + spare
        read, adopted = [triangle_scene.begin_triangle_frame(scene, tessellator, mesh_cache=cache, **options)
                         for cache in caches]
        # As prepare_triangle_frame merges them.
        uniforms = {**read[1].camera_uniforms, **{key: _jsonable(value) for key, value in copy.uniforms.items()}}
        drawn = triangle_scene.prepare_leaf(copy, uniforms, read[1])
        meshes, border = caches[1], caches[1].gpu_border_cache
        mesh_entry, classes = meshes._entries[id(retired)], meshes._classes[id(retired)][2]
        source_entry, reservation = border.sources.get(id(retired)), border.capacities.get(id(retired))
        painted = drawn.draws[0].paint is not None
        if source_entry is not None:
            density = reservation[3:5]
            border.adopt(copy, source_entry, density, border.first_reservation(density, uniforms["frame_scale"]),
                         uniforms=uniforms)
        held = meshes.adopt(copy, classes, mesh_entry, paint=painted)
        self.assertEqual(self.census(caches[1]), self.census(caches[0]))
        fill = drawn.draws[0]
        self.assertEqual(held.geometry.vertices.tobytes(), fill.vertices.tobytes())
        self.assertEqual(held.geometry.indices.tobytes(), fill.indices.tobytes())
        if painted:
            self.assertEqual(held.paint_field.wire().tobytes(), fill.paint.tobytes())
        for cache, (frame, context) in zip(caches, (read, adopted)):
            triangle_scene.finish_triangle_frame(frame, context)
        self.assertEqual(self.census(caches[1]), self.census(caches[0]))


# B4.4: a scene with checkpoints, navigated as the viewer navigates it. The
# group of discs moves one disc per play of the loop, so a seek between two
# of its checkpoints thaws the whole group afresh and brings the unchanged
# discs back as copies, with the rest of the group: an arc, a curved stroke
# whose count a zoom changes, and a blot, a curved fill with no stroke and
# no border, whose mesh a zoom refines; the dashed axis is eighty paths
# frozen before any read wrote their base points; the twins are two paths
# of equal content; the dot follows the box through an updater, so every
# thaw copies it.
SEEK_SCENE = textwrap.dedent('''\
    from maniml import *

    SHIFT = 0.5


    class SeekScene(Scene):
        def construct(self):
            discs = VGroup(*(Circle(radius=.3, fill_color=BLUE, fill_opacity=.8, stroke_color=WHITE,
                                    stroke_width=2, fill_border_width=1).shift(x * RIGHT) for x in range(-3, 4)),
                           Arc(radius=.4, angle=PI, stroke_color=YELLOW, stroke_width=3).shift(3 * RIGHT + UP),
                           Circle(radius=.25, fill_color=GREEN, fill_opacity=1, stroke_width=0,
                                  fill_border_width=0).shift(3 * LEFT + UP))
            axis = DashedLine(4 * LEFT, 4 * RIGHT, stroke_width=3).shift(2 * DOWN)
            self.play(FadeIn(discs), Create(axis), run_time=.1)
            box = Square(side_length=1, fill_color=RED, fill_opacity=.6, stroke_width=3).shift(1.5 * UP + SHIFT * RIGHT)
            twins = VGroup(*(Triangle(fill_color=YELLOW, fill_opacity=1, stroke_width=0).scale(.3)
                             .shift(3 * LEFT + 1.5 * UP) for _ in range(2)))
            self.play(FadeIn(box), FadeIn(twins), run_time=.1)
            for k in range(3):
                self.play(discs[k].animate.shift(.5 * UP), run_time=.1)
            badge = Rectangle(width=1, height=.4, fill_color=YELLOW, fill_opacity=.8).to_corner(UL).fix_in_frame()
            dot = Dot(color=GREEN).add_updater(lambda m: m.move_to(box.get_center() + DOWN))
            self.add(badge, dot)
            self.play(box.animate.shift(RIGHT), run_time=.1)
            self.play(Transform(box, Circle(radius=.6, fill_color=GREEN, fill_opacity=.7).shift(2 * UP)), run_time=.1)
            self.wait(.05)
''')
# Checkpoints 3 and 4 are the loop's first and second plays; 8 is the
# last, the wait's.
LOOP_PLAYS, LAST_CHECKPOINT = (3, 4), 8


def navigate(action):
    """A step applying ``action`` to a side's scene with the collector run
    before it and after it and held off in between: which live objects a
    thaw hands back depends on which the collector has freed (B4.2's
    note), so both sides are kept to the same ones."""
    def step(side):
        gc.collect()
        gc.disable()
        try:
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                action(side.scene)
        finally:
            gc.collect()
            gc.enable()
    return step


def seek(index):
    """A navigation to checkpoint ``index``, as the viewer's arrow keys and
    benchmarks.episode_frames.show_frame make it."""
    def action(scene):
        scene._restore_checkpoint_for_display(index)
        scene.update_mobjects(0)
    return navigate(action)


def edited(old, new, line):
    """A watcher's save of the side's scene file with ``old`` replaced by
    ``new`` at ``line``, handled as tests.test_checkpoint_reload's save."""
    def action(scene):
        path = Path(scene._scene_filepath)
        path.write_text(path.read_text().replace(old, new))
        scene._on_file_changed({"earliest_changed_line": line})
        scene._file_changed_flag = False
        scene._handle_file_change()
    return navigate(action)


def cache_work(cache):
    """What the flag-on side's caches made from scratch so far: fill meshes
    generated and border sources packed. An adoption makes neither."""
    meshes = cache.triangle_meshes
    return meshes.stats["regenerations"] + meshes.gpu_border_cache.source_updates


@requires_lyon
class RetainedFrameNavigation(GoldenCase):
    """Retired leaves and their adoption (B4.4): navigation through a
    scene's checkpoints, flag on against flag off, frame by frame, as in
    RetainedFrameLockstep, with the collector held to the same objects on
    both sides. A seek back and forth inside a loop, a far jump and back,
    a RIGHT press replaying a play (every frame of it compared) and its
    landing, a watcher's restart from a reloaded module, which rebuilds
    every mobject, and an edit inside construct(), which replays the last
    unit, then a zoom whose refined meshes the seeks after it find made
    at another camera. Beside it: a budget that leaves the store room for
    some parked paths only, a mesh no budget holds, a path read through a
    getter of its own and one whose class of the same name reads through
    a helper of its own (a restart's), a reservation whose source the
    budget let go, and the store's bound in entries."""

    def setUp(self):
        self.directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.names = iter(f"seek_scene_{index}" for index in range(100))

    def seek_side(self):
        """A SeekScene built as the CLI builds it, from a file of its own,
        and run to its last checkpoint. The camera's capture stands down,
        as it does while a client renders."""
        name = next(self.names)
        path = self.directory / f"{name}.py"
        path.write_text(SEEK_SCENE)
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            scene = load_scene_module(str(path)).SeekScene(window=None)
        self.addCleanup(sys.modules.pop, name, None)
        self.addCleanup(scene.camera.release)
        self.enterContext(patch.object(scene.camera, "capture"))
        scene._scene_filepath = str(path)
        scene.skip_animations = True
        scene.setup()
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            scene._create_checkpoint_zero()
            scene._run_all_units()
        self.assertEqual(len(scene.animation_checkpoints), LAST_CHECKPOINT + 1)
        return SimpleNamespace(scene=scene)

    def frame(self, lock, label, renderer, *, made=None, **counts):
        """``lock.frame``; where the retained frame keeps leaves at all, the
        flag-on side's ``counts`` and, given ``made``, how many meshes and
        border sources its caches made from scratch in the frame."""
        before = cache_work(lock.caches[1]) if lock.caches[1].triangle_meshes is not None else 0
        message = lock.frame(label, renderer)
        lock.expect(**counts)
        if made is not None and not adopting_under_verification(lock.retained.stats):
            self.assertEqual(cache_work(lock.caches[1]) - before, made, f"{label}: made from scratch")
        return message

    def replayed(self, lock, target, renderer):
        """A RIGHT press replaying the play that saved checkpoint ``target``
        (benchmarks.episode_frames.replay_play): each side in turn, every
        frame serialized as the play draws it and held to the other side's
        (the message, the caches, the scene), then the landing."""
        from benchmarks.episode_frames import replay_play
        seen = ([], [])
        for index, side in enumerate(lock.sides):
            def on_frame(k, index=index, side=side):
                seen[index].append((lock.serialize(index, renderer, bool(index)),
                                    census(lock.caches[index]), leaf_states(side.scene)))

            navigate(lambda scene: replay_play(scene, target, on_frame))(side)
        self.assertEqual(len(seen[0]), len(seen[1]))
        self.assertGreater(len(seen[0]), 1)
        for k, (off, on) in enumerate(zip(*seen)):
            if on[0] != off[0]:
                self.fail(f"play into {target}, frame {k}: flag on differs from flag off: {difference(off[0], on[0])}")
            self.assertEqual(on[1], off[1], f"play into {target}, frame {k}: the caches differ")
            self.assertEqual(on[2], off[2], f"play into {target}, frame {k}: the scenes differ")
        return self.frame(lock, f"landed at {target}", renderer)

    def test_seeks_jumps_replays_and_restarts(self):
        for renderer in RENDERERS:
            with self.subTest(renderer=renderer):
                self.navigation(renderer)

    def navigation(self, renderer):
        # Under Phase B the dot's fill is read through its shader data, and
        # its updater's move leaves the joint angles' flag alone set: rows
        # a refresh of the joint angles alone made are of unknown
        # derivation to a later comparison (compare_rows), so every thaw's
        # copy of it is prepared, as a kept leaf in that state would be.
        dot = int(renderer == "phase_b")
        lock = Lockstep(self, self.seek_side)
        self.frame(lock, "cold at the last checkpoint", renderer)
        self.frame(lock, "still", renderer, leaves_prepared=0)
        # Inside the loop every seek thaws the group of discs afresh, and
        # its unchanged members come back as copies of what the frame
        # before parked. The first seek there also puts back two paths no
        # frame has drawn yet, the disc the loop's last play moves, still
        # in place, and the box before its play; the first seek down, the
        # disc the loop's second play moves. From then on every member a
        # seek puts back was parked.
        down, up = LOOP_PLAYS
        lock.step(seek(up))
        self.frame(lock, f"seek to {up}", renderer, leaves_prepared=2, leaves_adopted=8)
        lock.step(seek(down))
        self.frame(lock, "first seek down", renderer, leaves_prepared=1, leaves_adopted=8)
        for index in range(2):
            lock.step(seek(up))
            self.frame(lock, f"seek up {index}", renderer, leaves_prepared=0, leaves_adopted=9, made=0)
            lock.step(seek(down))
            self.frame(lock, f"seek down {index}", renderer, leaves_prepared=0, leaves_adopted=9, made=0)
        # A far jump parks the whole scene, and the jump back adopts it:
        # all but one of the twins, whose equal twin was parked under the
        # same digest, displacing it.
        lock.step(seek(1))
        self.frame(lock, "far jump", renderer)
        lock.step(seek(LAST_CHECKPOINT))
        self.frame(lock, "and back", renderer, leaves_prepared=1 + dot, made=1 + dot)
        # The play into the loop's last checkpoint, replayed from the one
        # before it: its landing thaws what the last frame of the play drew.
        self.replayed(lock, up, renderer)
        lock.step(seek(LAST_CHECKPOINT))
        self.frame(lock, "back at the last checkpoint", renderer)
        # A save outside construct() reloads the module and rebuilds every
        # mobject: all new, all of the same content, all adopted but a twin.
        lock.step(edited("SHIFT = 0.5", "SHIFT = 0.25 + 0.25", 3))
        self.frame(lock, "restarted from source", renderer, leaves_prepared=1 + dot, made=1 + dot)
        self.frame(lock, "still", renderer, leaves_prepared=0)
        # A save of the last unit replays it from the checkpoint before.
        line = SEEK_SCENE.splitlines().index("        self.wait(.05)") + 1
        lock.step(edited("self.wait(.05)", "self.wait(.06)", line))
        self.frame(lock, "the last unit replayed", renderer, leaves_prepared=dot, made=dot)
        self.frame(lock, "still", renderer, leaves_prepared=0)
        # A zoom refines the fills' meshes and grows the discs' border
        # reservations (under Phase B their patch records' too, and not
        # the blot's, whose curves need fewer steps), and a zoom back keeps
        # both; a zoom changes the arc's count. What a frame parks under
        # either camera is then not what the frame's loop makes for a copy
        # under the authored camera (a mesh generated at this camera, a
        # first reservation at this zoom, the count at this frame scale),
        # and those copies are prepared. The disc the loop moves between
        # the two checkpoints was last drawn in place under the authored
        # camera, before the zoom, and adopts what that frame parked. Seeks
        # from the zoom back, and then from the zoom.
        blot = 1 - dot
        lock.step(seek(up))
        self.frame(lock, f"seek to {up}", renderer)
        lock.step(lambda side: side.scene.camera.frame.scale(1 / 6))
        self.frame(lock, "zoom in 6x", renderer)
        lock.step(lambda side: side.scene.camera.frame.scale(6))
        self.frame(lock, "zoom back", renderer)
        lock.step(seek(down))
        self.frame(lock, "seek down after the zoom", renderer, leaves_prepared=6 + blot, leaves_adopted=3 - blot)
        lock.step(seek(up))
        self.frame(lock, "seek up", renderer, leaves_prepared=1, leaves_adopted=8)
        lock.step(lambda side: side.scene.camera.frame.scale(1 / 6))
        self.frame(lock, "zoom in 6x again", renderer)
        lock.step(seek(down))
        self.frame(lock, "seek down from the zoom", renderer, leaves_prepared=7 + blot, leaves_adopted=2 - blot)
        # The first seek back finds the moved disc's other place parked
        # only from the zoomed frame, and prepares it too.
        lock.step(seek(up))
        self.frame(lock, "seek up", renderer, leaves_prepared=1, leaves_adopted=8)
        lock.step(seek(down))
        self.frame(lock, "seek down", renderer, leaves_prepared=0, leaves_adopted=9, made=0)
        lock.step(seek(up))
        self.frame(lock, "seek up", renderer, leaves_prepared=0, leaves_adopted=9, made=0)
        self.frame(lock, "still", renderer, leaves_prepared=0)

    def test_the_store_takes_what_the_budget_leaves(self):
        # The store yields to the caches: after every frame it holds no more
        # than the mesh and border caches leave of their shared budget, and
        # it never costs them an entry, so the flag-off path's evictions are
        # the flag-on path's. A far jump parks the whole scene and adopts
        # little of it. A budget with a few KiB to spare keeps a few of the
        # paths it parked, where the whole budget keeps them all, and the
        # jump back adopts fewer, preparing the rest as the budget evicts in
        # the frame's order.
        adopted = []
        for spare in (12 << 10, None):
            lock = Lockstep(self, self.seek_side)
            self.frame(lock, "cold", "phase_a")
            lock.step(seek(1))
            self.frame(lock, "far jump", "phase_a")
            if spare is not None:
                for cache in lock.caches:
                    meshes = cache.triangle_meshes
                    meshes.max_bytes = meshes._bytes + meshes.gpu_border_cache.nbytes + spare
            for label in ("the budget set", "still"):
                self.frame(lock, label, "phase_a")
                meshes = lock.caches[1].triangle_meshes
                self.assertLessEqual(lock.retained.retired_bytes,
                                     meshes.max_bytes - meshes._bytes - meshes.gpu_border_cache.nbytes)
            lock.step(seek(LAST_CHECKPOINT))
            self.frame(lock, "and back", "phase_a")
            adopted.append(lock.retained.stats["leaves_adopted"])
        if not verifying():
            self.assertLess(adopted[0], adopted[1])

    def test_a_mesh_no_budget_holds_is_not_parked(self):
        # A fill mesh the cache does not retain is made again at every
        # camera by the frame's loop, and a kept leaf's draws hold the one
        # made last (B4.3): parked, a copy at another camera would adopt a
        # mesh made at the zoom. A zero budget stands for one over 64 MiB.
        lock = Lockstep(self, self.seek_side)
        self.frame(lock, "cold", "phase_a")
        for cache in lock.caches:
            cache.triangle_meshes.max_bytes = 0
        for target in LOOP_PLAYS:
            lock.step(seek(target))
            self.frame(lock, f"seek to {target} with no budget", "phase_a")
        lock.step(lambda side: side.scene.camera.frame.scale(1 / 3))
        self.frame(lock, "zoom in 3x", "phase_a")
        for target in LOOP_PLAYS:
            lock.step(seek(target))
            self.frame(lock, f"seek to {target} from the zoom", "phase_a")

    def test_a_path_read_through_its_own_getter_is_not_parked(self):
        # Its draws are what its getter made of its rows, which a path of
        # the same rows and the library's getters would not draw. Here the
        # getter doubles the stroke, and the plain square that takes its
        # place, of the same class and rows, is prepared.
        def build():
            state = {"factor": 2.0}
            own = rows_from(Square(side_length=.8, stroke_color=WHITE, stroke_width=3), state)
            return SimpleNamespace(scene=build_scene(own), own=own)

        def replace_it(side):
            plain = Square(side_length=.8, stroke_color=WHITE, stroke_width=3)
            # The same digest: a candidate for the parked entry.
            self.assertEqual(*(retained_frame.leaf_digest("Square", retained_frame.override_text(square)[1],
                                                          retained_frame.leaf_flags(square), square._data)
                               for square in (plain, side.own)))
            remove(side, "own")
            add(side, "plain", plain)

        lock = Lockstep(self, build)
        self.frame(lock, "cold", "phase_a")
        lock.step(replace_it)
        self.frame(lock, "a plain path of the same rows in its place", "phase_a",
                   leaves_prepared=1, leaves_adopted=0)

    def test_a_class_of_the_same_name_is_read_through_its_own_helpers(self):
        # A restart redefines the scene file's classes, so a path of the new
        # class with the rows of a parked path of the old is a candidate for
        # its entry: the digest names a class by its name. Here the edit
        # gave the class a helper of its own, which the refresh of the
        # derived columns reads the anchors through, in the other order,
        # which turns the unit normal around. The path is prepared, as any
        # path read through a method of its own is, and left with the
        # normal its own read writes.
        def blob_class(flip):
            class Blob(VMobject):
                if flip:
                    def get_anchors(self):
                        return super().get_anchors()[::-1]
            return Blob

        def blob(cls):
            path = cls(fill_color=BLUE, fill_opacity=.8, stroke_color=WHITE, stroke_width=4)
            return path.set_points_as_corners([[-1, -.6, 0], [1.2, -.5, 0], [.8, .9, 0], [-.7, .7, 0], [-1, -.6, 0]])

        def build():
            path = blob(old)
            return SimpleNamespace(scene=build_scene(path), blob=path)

        def restart(side):
            remove(side, "blob")
            add(side, "blob", blob(new))

        old, new = blob_class(False), blob_class(True)
        for renderer in RENDERERS:
            with self.subTest(renderer=renderer):
                lock = Lockstep(self, build)
                self.frame(lock, "cold", renderer)
                self.frame(lock, "still", renderer, leaves_prepared=0)
                lock.step(restart)
                self.frame(lock, "the class defined again", renderer, leaves_prepared=1, leaves_adopted=0)

    def test_a_reservation_whose_source_the_budget_let_go_is_not_parked(self):
        # A budget that leaves the border cache less room than the disc's
        # one source: each read of the disc packs it, reserves, and lets it
        # go. A copy's read packs it again and makes the first reservation
        # at this zoom, which the parked entry holds no source for, and
        # after a scale up and back (the mesh made again at the authored
        # camera) a reservation the scale grew and the disc kept.
        def build():
            filler = [Square(side_length=.3, fill_color=RED, fill_opacity=1, stroke_width=0).shift(x * RIGHT + 2 * UP)
                      for x in range(-3, 4)]
            disc = Circle(radius=.5, fill_color=GREEN, fill_opacity=.9, stroke_width=0, fill_border_width=2)
            return SimpleNamespace(scene=build_scene(*filler, disc), disc=disc, points=disc.get_points().copy())

        def replace_it(side):
            copy = side.disc.copy()
            remove(side, "disc")
            add(side, "disc", copy)

        lock = Lockstep(self, build)
        self.frame(lock, "cold", "phase_a")
        for cache in lock.caches:
            meshes = cache.triangle_meshes
            meshes.max_bytes = meshes._bytes + 2000
        self.frame(lock, "the budget set", "phase_a")
        # Kept in that frame, and let go by its sweep; read in this one.
        self.frame(lock, "still", "phase_a", leaves_prepared=1)
        border, disc = lock.caches[0].triangle_meshes.gpu_border_cache, lock.sides[0].disc
        self.assertNotIn(id(disc), border.sources)
        self.assertIn(id(disc), border.capacities)
        lock.step(replace_it)
        self.frame(lock, "a copy in its place", "phase_a", leaves_prepared=1, leaves_adopted=0)
        lock.step(lambda side: side.disc.scale(3))
        self.frame(lock, "scaled up", "phase_a")
        lock.step(lambda side: side.disc.set_points(side.points.copy()))
        self.frame(lock, "scaled back", "phase_a")
        grown = border.capacities[id(lock.sides[0].disc)][1]
        lock.step(replace_it)
        self.frame(lock, "a copy in its place again", "phase_a", leaves_prepared=1, leaves_adopted=0)
        self.assertLess(border.capacities[id(lock.sides[0].disc)][1], grown)

    def test_the_store_is_bounded_in_entries(self):
        # The least recently parked go first.
        self.enterContext(patch.object(retained_frame, "MAX_RETIRED", 3))
        lock = Lockstep(self, self.seek_side)
        self.frame(lock, "cold", "phase_a")
        for target in (1, LAST_CHECKPOINT, *LOOP_PLAYS, LAST_CHECKPOINT):
            lock.step(seek(target))
            self.frame(lock, f"seek to {target}", "phase_a")
            self.assertLessEqual(len(lock.retained.retired), 3)


class RowSourcesNavigation(RetainedFrameNavigation):
    """The navigation above with Phase B's paths sent as rows (B5.1): a
    seek's retired paths are parked with their rows entry and adopted."""

    def setUp(self):
        super().setUp()
        self.enterContext(patch.dict(os.environ, MANIML_PATCH_SOURCE="rows"))


if __name__ == "__main__":
    if "--record" in sys.argv:
        sys.argv.remove("--record")
        os.environ[RECORD_ENV] = "1"
    unittest.main()

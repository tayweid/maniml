"""The retained frame: tier 1 of Phase B4 (docs/phase_b4_plan.md).

Under MANIML_RETAINED_FRAME=1 a GeometryCache keeps, per drawn leaf, the
draws prepare_leaf made for it and what they were made under, and a frame
prepares again only the leaves it cannot keep. The draw order is walked
again every frame, so CE's family order, fixed-frame groups last and the
render-group rejoin are decided exactly as prepare_triangle_frame decides
them; coalesce_draws closes every run, with the run kind memoized on each
draw and a run's combination memoized by its members' identities; and a
run whose members, camera and receiver are unchanged reuses its encoded
descriptor. The message is the one serialize_generated_frame writes for the
same GeometryCache history, byte for byte: nothing on the wire, in the
browser, in native capture or in a recording changes.

A leaf is kept while its ``Mobject.revision`` and the frame's camera are the
ones its draws were made under (the revision policy's own promise, and the
checkpoint ledger's), and while the caches still hold, and are told they
used, exactly the entries its draws were read from: a leaf the caches have
let go is prepared again, as the frame's own loop would prepare it. What
the frame's loop reads every frame and no revision covers is checked every
frame: the depth-test and stroke-behind attributes, the leaf's getters
(a leaf whose rows come through a getter of its own is prepared every
frame) and a textured leaf's files, which are hashed again. Nothing else is
trusted yet: a leaf whose revision or camera moved is prepared again
whatever changed (B4.3 compares its source and revalidates its
camera-dependent counts), and a leaf that leaves the walk is forgotten
(B4.4 adopts it by content). An in-place write to a kept leaf's arrays or
uniforms that bumps no revision stays off the screen until the revision
moves, where the frame's loop would draw it on its next frame: the
revision contract the checkpoint ledger already rests on, which verify
mode checks at a save, is here a per-frame one. Under verification every
leaf is prepared, so verify mode does not yet check the kept leaves
themselves (B4.5 rebuilds and compares them).
"""

import json
import os
import weakref

from maniml.mobject.mobject import Mobject
from maniml.mobject.types.dot_cloud import DotCloud
from maniml.mobject.types.image_mobject import ImageMobject
from maniml.mobject.types.surface import Surface
from maniml.mobject.types.vectorized_mobject import VMobject
from maniml.mobject.types.vmobject_3d import VMobject3D
from maniml.web.border_geometry import _STANDARD_SOURCE_METHODS
from maniml.web.generated_geometry import (
    BatchRecord, MessageParts, _supersample, assemble_message, encode_draw, held_batch,
)
from maniml.web.geometry import _jsonable
from maniml.web.triangle_scene import (
    _STANDARD_MESH_GETTERS, _prepare_border_geometry, begin_triangle_frame, border_parts, combine_run,
    draw_order, finish_triangle_frame, patch_parts, prepare_leaf, run_kind,
)

RETAINED_FRAME_ENV = "MANIML_RETAINED_FRAME"

# What a leaf's draws are made from, which decides what keeps them: a
# VMobject's rows (the mesh and border caches), a surface's net (the net
# cache), a pending program (never kept: its scalars move every frame and
# its endpoints are other mobjects), or the leaf's own shader data.
ROWS, NET, PROGRAM, PLAIN = "rows", "net", "program", "plain"

# The getters prepare_leaf reads a leaf's rows through, each with the
# definitions whose output is a function of the rows at a revision: the
# library's own. A VMobject's are the ones the mesh and border caches trust
# a revision for (triangle_scene._standard_mesh_getters,
# border_geometry.standard_source_methods); a dot cloud's, surface's or
# image's shader data is read every frame, through the rest. Any other
# definition, a subclass's or an instance's, may read state no revision
# covers, and its leaf is prepared every frame, as the frame's loop reads it.
_VMOBJECT_GETTERS = tuple((name, (method,))
                          for name, method in (*_STANDARD_SOURCE_METHODS, *_STANDARD_MESH_GETTERS))
_PLAIN_GETTERS = (
    ("get_shader_data", (Mobject.get_shader_data, Surface.get_shader_data)),
    ("get_shader_vert_indices", (Mobject.get_shader_vert_indices, Surface.get_shader_vert_indices)),
    # A surface's, through its shader data; None where the class has none.
    ("get_triangle_indices", (None, Surface.get_triangle_indices, VMobject3D.get_triangle_indices)),
    ("get_grid_data", (None, Surface.get_grid_data)),
    ("get_net", (None, Surface.get_net)),
)
_GETTER_NAMES = frozenset(name for name, _ in (*_VMOBJECT_GETTERS, *_PLAIN_GETTERS))
_LIBRARY_GETTER_CLASSES = {}


def retained_frame_enabled():
    """Whether MANIML_RETAINED_FRAME=1 asks for the retained frame."""
    return os.environ.get(RETAINED_FRAME_ENV) == "1"


def library_getters(sm):
    """Whether every getter ``sm``'s rows are read through is the library's
    own: a class-level answer, memoized per class, plus a check that no
    instance overrides one."""
    cls = type(sm)
    standard = _LIBRARY_GETTER_CLASSES.get(cls)
    if standard is None:
        getters = _VMOBJECT_GETTERS if issubclass(cls, VMobject) else _PLAIN_GETTERS
        standard = _LIBRARY_GETTER_CLASSES[cls] = all(
            getattr(cls, name, None) in methods for name, methods in getters)
    return standard and sm.__dict__.keys().isdisjoint(_GETTER_NAMES)


def leaf_flags(sm):
    """The two attributes prepare_leaf reads on every leaf that a plain
    assignment changes without a revision bump: the depth test (the
    pipeline) and stroke behind (the order of its two draws)."""
    return bool(sm.depth_test), bool(getattr(sm, "stroke_behind", False))


class LeafEntry:
    """One leaf's draws as prepare_leaf made them (``leaf``, a LeafDraws),
    and what they were made under: the leaf (a weak reference) at its
    ``revision``, the frame's interned ``camera_key`` (compared by
    identity), the shared ``uniforms`` its draws reference, its ``flags``
    (leaf_flags), the entries the caches held for it that frame, and the
    sampler-to-hash map of its textures. The flags and the cache entries
    are also what a later increment adopts a leaf by."""

    __slots__ = ("owner", "revision", "camera_key", "uniforms", "leaf", "kind", "flags",
                 "textures", "mesh_entry", "classes", "source_entry", "capacity", "net_entry")

    def __init__(self, sm, camera_key, uniforms, leaf, kind):
        self.owner = weakref.ref(sm)
        self.revision = sm.revision
        self.camera_key = camera_key
        self.uniforms = uniforms
        self.leaf = leaf
        self.kind = kind
        self.flags = leaf_flags(sm)
        # A textured leaf resolved its textures into the LeafDraws; its one
        # draw carries the map.
        self.textures = leaf.draws[0].textures if leaf.textures is not None else None
        self.mesh_entry = self.classes = self.source_entry = self.capacity = self.net_entry = None


class UniformSets:
    """The leaves' merged uniforms, one dict per distinct set of a leaf's
    own uniforms (its overrides over the camera's), shared by every leaf
    with that set and by all their draws.

    Sharing makes equal uniforms one dict, so a run compares them by
    identity rather than key by key, and a camera change is written into
    each set in place. A set is keyed by its overrides' JSON text, not their
    values: 1 and 1.0 are equal and hash alike, but a run prints its first
    member's spelling, so one set for both would print whichever leaf made
    it. Overrides holding a NaN are never shared: NaN is unequal to itself,
    so the per-leaf dicts prepare_triangle_frame builds never let two such
    leaves join a run, and one dict would.
    """

    def __init__(self):
        self.sets = {}  # overrides' JSON text -> (merged, overrides)
        self.names = None  # the camera uniforms' names, in the order the sets were merged with

    def merged(self, sm, camera):
        """``sm``'s uniforms over ``camera``'s, as prepare_triangle_frame
        merges them, from the set they belong to."""
        overrides = {key: _jsonable(value) for key, value in sm.uniforms.items()}
        try:
            text = json.dumps(list(overrides.items()))
        except (TypeError, ValueError):
            text = None  # not JSON: never equal to another leaf's text, so never shared
        held = self.sets.get(text)
        if held is not None:
            return held[0]
        merged = {**camera, **overrides}
        if text is not None and "NaN" not in text:
            self.sets[text] = (merged, overrides)
        return merged

    def camera_moved(self, camera):
        """Write a new camera into every set, its overrides still over it."""
        names = tuple(camera)
        if names != self.names:
            # A merged dict keeps the key order it was made with, which
            # follows the camera's names: sets made under other names are
            # made again.
            self.sets.clear()
            self.names = names
            return
        for merged, overrides in self.sets.values():
            merged.update(camera)
            merged.update(overrides)

    def prune(self, leaves):
        """Forget the sets no leaf in ``leaves`` (LeafEntries) references."""
        live = {id(entry.uniforms) for entry in leaves}
        self.sets = {text: held for text, held in self.sets.items() if id(held[0]) in live}


class RunMemo:
    """One coalesced run kept across frames: its ``members`` (the leaves'
    draws, held so that their ids stay theirs), the ``draw`` they combine
    into, and for a run the border cache assembles, the ``key`` it keeps
    the assembly under and the ``assembly`` it gave back; then the run's
    encoded descriptor (``batch``, in the form encode_draw wrote it last),
    the camera it was encoded under, the ``record`` of what it named, and
    its text once the receiver holds it."""

    __slots__ = ("members", "draw", "key", "assembly", "batch", "camera_key", "record", "held_text")

    def __init__(self, members, draw):
        self.members = members
        self.draw = draw
        self.key = self.assembly = None
        self.batch = self.camera_key = self.record = self.held_text = None

    def held(self):
        """The run's descriptor text for a message whose receiver holds
        everything it names."""
        if self.held_text is None:
            self.held_text = json.dumps(held_batch(self.batch))
        return self.held_text


def memoized_run_kind(draw):
    """run_kind, memoized on the draw: a function of the draw alone, and a
    kept leaf's draws are the same objects frame after frame."""
    try:
        return draw._run_kind
    except AttributeError:
        kind = draw._run_kind = run_kind(draw)
        return kind


def _leaf_kind(sm, draws):
    if any(draw.program is not None for draw in draws):
        return PROGRAM
    if any(draw.net is not None for draw in draws):
        return NET
    return PLAIN if isinstance(sm, (DotCloud, Surface, ImageMobject)) else ROWS


class RetainedFrame:
    """A GeometryCache's draws kept across its frames (``cache.retained_frame``).

    ``prepare`` is prepare_triangle_frame for the options it is given and
    ``encode`` is serialize_generated_frame, both writing the same bytes as
    they do for the same history, provided this object sees every frame the
    cache serializes; the serializer drops it whenever that would fail (the
    flag off, a renderer or generator change). A frame that raises leaves
    it cold.
    """

    def __init__(self):
        self.clear()

    def clear(self):
        """Forget everything: the next frame prepares every leaf."""
        self.leaves = {}  # id(leaf) -> LeafEntry, the last frame's leaves
        self.runs = {}  # member ids -> RunMemo, the last frame's runs
        self.uniform_sets = UniformSets()
        self.camera_key = None
        self._frame_runs = []  # this frame's RunMemos, in draw order
        self._next_runs = {}
        # The last frame's counts: leaves kept and prepared, runs kept and
        # combined, descriptors reused and encoded.
        self.stats = {}

    def retained_bytes(self):
        """What this object keeps between frames that no cache's budget
        counts: the rows prepare_leaf copied for strokes and plain leaves,
        the arrays a run of several draws was combined into, and the text
        of the held descriptors. Bounded by one frame's draws: a gauge's
        business (geometry.retained_frame_bytes), not the budget's."""
        arrays = {}
        for entry in self.leaves.values():
            for draw in entry.leaf.draws:
                if entry.kind is PLAIN or draw.pipeline.startswith("stroke"):
                    arrays[id(draw.vertices)] = draw.vertices.nbytes
        for memo in self.runs.values():
            draw = memo.draw
            # A run of one is its member, and the border cache counts the
            # assemblies it retains; any other run's arrays are the run's.
            if draw is memo.members[0] or memo.assembly is not None:
                continue
            for array in (draw.vertices, draw.indices, draw.border_sources, draw.fill_objects):
                if array is not None:
                    arrays[id(array)] = array.nbytes
        return sum(arrays.values()) + sum(len(memo.held_text or "") for memo in self.runs.values())

    def prepare(self, scene, tessellator, **options):
        """The frame prepare_triangle_frame prepares for ``scene`` with these
        ``options``, preparing only the leaves it cannot keep."""
        try:
            return self._prepare(scene, tessellator, options)
        except BaseException:
            self.clear()
            raise

    def encode(self, frame, camera_uniforms, cache, *, renderer="triangles"):
        """serialize_generated_frame(frame, camera_uniforms, cache,
        renderer=renderer), for the frame ``prepare`` just returned: a run
        whose members and camera are unchanged, and whose names the
        receiver holds, is the descriptor encode_draw gave it before, in
        the form it takes once held, and adds no bytes."""
        try:
            return self._encode(frame, camera_uniforms, cache, renderer)
        except BaseException:
            self.clear()
            raise

    def _prepare(self, scene, tessellator, options):
        frame, ctx = begin_triangle_frame(scene, tessellator, **options)
        mesh_cache = ctx.mesh_cache
        camera_key = self._camera_key(ctx)
        sets, camera = self.uniform_sets, ctx.camera_uniforms
        # The revision policy is the promise a kept leaf rests on. The bytes
        # policy compares every array every frame and verification every
        # trusted read, so under either every leaf is prepared (B4.5 has
        # verification rebuild and compare the kept leaves instead); so it
        # is under the CPU border reference, which expands the frame's
        # borders all at once.
        trusting = (ctx.gpu_borders and mesh_cache is not None and mesh_cache.policy == "revision"
                    and not mesh_cache.verify)
        leaves, programs = self.leaves, ctx.programs
        plan, records = [], []
        for sm in draw_order(scene):
            entry = leaves.get(id(sm))
            if (trusting and entry is not None and entry.revision == sm.revision
                    and entry.camera_key is camera_key and entry.kind is not PROGRAM
                    and entry.owner() is sm and not (programs and sm._program is not None)
                    and entry.flags == leaf_flags(sm) and library_getters(sm)):
                mesh_entry = entry.mesh_entry
                if mesh_entry is not None and mesh_entry.projection_key is None:
                    # A mesh made last frame has no error bound yet, and the
                    # frame's own loop bounds it now, stacked with every
                    # other unbounded mesh: so is it here, in that company.
                    records.append((sm, entry.uniforms))
                plan.append((sm, entry, entry.uniforms))
            else:
                uniforms = sets.merged(sm, camera)
                records.append((sm, uniforms))
                plan.append((sm, None, uniforms))
        if mesh_cache is not None:
            mesh_cache.bound_errors(records, frame.resolution)
        if ctx.fill_borders and ctx.fill_builder is None and not ctx.gpu_borders:
            ctx.borders = _prepare_border_geometry(records, mesh_cache)
        # In draw order, as the frame's own loop reads the caches: their
        # recency decides what a budget evicts.
        kept, prepared = {}, 0
        for sm, entry, uniforms in plan:
            if entry is None or not self._keep(sm, entry, ctx, frame):
                leaf = prepare_leaf(sm, uniforms, ctx)
                entry = self._entry(sm, leaf, uniforms, ctx, camera_key)
                prepared += 1
            kept[id(sm)] = entry
            frame.add_leaf(entry.leaf)
        self.leaves = kept
        self.stats = {"leaves_kept": len(plan) - prepared, "leaves_prepared": prepared,
                      "runs_kept": 0, "runs_combined": 0}
        if len(sets.sets) > 2 * len(kept) + 64:
            sets.prune(kept.values())
        self._frame_runs, self._next_runs = [], {}
        frame = finish_triangle_frame(frame, ctx, kind=memoized_run_kind, combine=self._combine)
        self.runs, self._next_runs = self._next_runs, {}
        return frame

    def _camera_key(self, ctx):
        """The frame's camera as one object, the same object for as long as
        the camera is unchanged; the uniform sets follow a change. Its JSON
        text, like a uniform set's: equal text is equal spelling and equal
        bits, where equal values could be 0.0 and -0.0."""
        key = json.dumps([list(ctx.camera_uniforms.items()), ctx.resolution, ctx.pixel_tolerance])
        if key == self.camera_key:
            return self.camera_key
        self.camera_key = key
        self.uniform_sets.camera_moved(ctx.camera_uniforms)
        return key

    @staticmethod
    def _keep(sm, entry, ctx, frame):
        """Whether ``entry``'s draws stand for ``sm`` in this frame. The
        caches are told the leaf's entries were used, as prepare_leaf's
        reads would tell them, and must still hold exactly the entries its
        draws were read from; a textured leaf's files are hashed again, the
        payloads going to the frame as prepare_leaf sends them."""
        kind = entry.kind
        if kind is ROWS:
            mesh_entry, classes = ctx.mesh_cache.keep(sm)
            source_entry, capacity = ctx.border_cache.keep(sm)
            if (mesh_entry is not entry.mesh_entry or classes is not entry.classes
                    or source_entry is not entry.source_entry or capacity != entry.capacity):
                return False
        elif kind is NET and ctx.net_cache.keep(sm) is not entry.net_entry:
            return False
        return entry.textures is None or frame.texture_refs(sm) == entry.textures

    @staticmethod
    def _entry(sm, leaf, uniforms, ctx, camera_key):
        """The LeafEntry of a leaf prepare_leaf has just prepared, with the
        cache entries it read."""
        entry = LeafEntry(sm, camera_key, uniforms, leaf, _leaf_kind(sm, leaf.draws))
        if entry.kind is ROWS and ctx.mesh_cache is not None:
            entry.mesh_entry, entry.classes = ctx.mesh_cache.held(sm)
            if ctx.border_cache is not None:
                entry.source_entry, entry.capacity = ctx.border_cache.held(sm)
        elif entry.kind is NET:
            entry.net_entry = ctx.net_cache.held(sm)
        return entry

    def _combine(self, run, kind, *, border_cache=None):
        """combine_run, memoized by the members' identities: an unchanged
        run is the same draw, so its encoded descriptor can be kept too. A
        memo holds its members, so no other draw can carry their ids."""
        ids = tuple(map(id, run))
        memo = self.runs.get(ids)
        if memo is not None and memo.key is not None:
            # The border cache assembled it: kept only while the cache
            # keeps that assembly, and told it was used, as asking for it
            # again would tell it.
            if memo.assembly is None or border_cache.keep_run(memo.key) is not memo.assembly:
                memo = None
        if memo is not None:
            self.stats["runs_kept"] += 1
        else:
            self.stats["runs_combined"] += 1
            memo = RunMemo(tuple(run), combine_run(run, kind, border_cache=border_cache))
            first = run[0]
            if first.program is None and first.border_sources is not None:
                memo.key = (border_cache.patch_run_key(patch_parts(run)) if first.fill_objects is not None
                            else border_cache.run_key(border_parts(run)))
                memo.assembly = border_cache.keep_run(memo.key)
        self._next_runs[ids] = memo
        self._frame_runs.append(memo)
        return memo.draw

    def _encode(self, frame, camera_uniforms, cache, renderer):
        # The frame's own checks come before any draw is encoded, as
        # serialize_generated_frame makes them.
        _supersample(frame)
        runs = self._frame_runs
        if len(runs) != len(frame.draws) or any(memo.draw is not draw for memo, draw in zip(runs, frame.draws)):
            raise RuntimeError("the retained frame encodes only the frame it prepared last")
        camera = {key: _jsonable(value) for key, value in camera_uniforms.items()}
        parts = MessageParts(cache)
        sent = cache.sent if cache is not None else frozenset()
        camera_key = self.camera_key
        texts, reused = [], 0
        for memo in runs:
            if memo.camera_key is camera_key and memo.record.names <= sent:
                if memo.batch is not None:
                    texts.append(memo.held())
                    parts.carry(memo.record)
                reused += 1
                continue
            record = BatchRecord()
            memo.batch = encode_draw(memo.draw, camera, parts, record=record)
            memo.record, memo.camera_key, memo.held_text = record, camera_key, None
            if memo.batch is not None:
                texts.append(json.dumps(memo.batch))
        message = assemble_message(frame, camera, ", ".join(texts), parts, renderer=renderer)
        parts.commit()
        self.stats.update(batches_reused=reused, batches_encoded=len(runs) - reused)
        return message

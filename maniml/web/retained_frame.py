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

A leaf is kept while prepare_leaf would make the same draws for it. Its
revision unchanged and the frame's camera the one its draws were made
under, that is the revision policy's own promise (and the checkpoint
ledger's). A revision that moved is checked against what the draws were
made from, since most bumps change nothing drawn (at EpisodeB2's 8.a an
idle tick bumps 415 of 531 leaves and changes no byte): a path's rows,
byte for byte or as the read's refresh of the derived columns would leave
them (compare_rows), a plain leaf's rows and the other inputs of its
shader data (same_plain), a net's rows by the net cache's own compare, and
the leaf's own uniforms by their text. The rows are the ones the draws
were read from, which are not always the arrays as prepare_leaf found
them: a cache that holds a read made at the same revision hands that back
without reading them (cached_read), so a leaf whose rows its last entry
cannot vouch for is not compared, and its next moved revision has it read
in full. A camera that moved is checked through the caches' own paths:
the mesh's error bound where mesh() takes it, the border and net
reservations as their trusted reads recompute them, and a stroke's count
from its largest curve (geometry._stroke_verts_at); a fill mesh the cache
does not hold is made again at every camera. Either way the caches are
told, in draw order, what the frame's reads would tell them, and must
still hold exactly the entries the draws were read from: a leaf the caches
have let go is prepared again, as the frame's own loop would prepare it.

The walk decides what it can from each leaf as it stands before any leaf
is read, and the reads come after, in draw order, as the frame's loop
makes them. A read writes to the scene (a path's refresh of its derived
columns) and reads other leaves (a program packs its endpoints' rows as
they stand), so a kept leaf is left as its read would leave it in its own
place in the order, and a leaf whose revision an earlier leaf's read moved
is prepared there. What the frame's loop reads every frame and no
revision covers is checked every frame: the depth-test and stroke-behind
attributes, the leaf's getters (a leaf whose rows come through a getter
of its own is prepared every frame) and a textured leaf's files, which
are hashed again. A leaf that leaves the walk is forgotten (B4.4 adopts
it by content). An in-place write to a kept leaf's arrays or uniforms
that bumps no revision stays off the screen until the revision moves,
where the frame's loop would draw it on its next frame: the revision
contract the checkpoint ledger already rests on, which verify mode checks
at a save, is here a per-frame one. Under verification every leaf is
prepared, so verify mode does not yet check the kept leaves themselves
(B4.5 rebuilds and compares them).
"""

import json
import os
import weakref

import numpy as np

from maniml.mobject.mobject import Mobject
from maniml.mobject.types.dot_cloud import DotCloud
from maniml.mobject.types.image_mobject import ImageMobject
from maniml.mobject.types.surface import Surface
from maniml.mobject.types.vectorized_mobject import VMobject
from maniml.mobject.types.vmobject_3d import VMobject3D
from maniml.scene.checkpoints import DERIVED_DATA_KEYS
from maniml.web.border_geometry import _STANDARD_SOURCE_METHODS
from maniml.web.generated_geometry import (
    BatchRecord, MessageParts, _supersample, assemble_message, encode_draw, held_batch,
)
from maniml.web.geometry import _jsonable, _stroke_sqrt_area, _stroke_verts_at
from maniml.web.gpu_net_geometry import pixels_per_unit
from maniml.web.triangle_scene import (
    CLASSIFY_COLUMNS, _STANDARD_MESH_GETTERS, _prepare_border_geometry, begin_triangle_frame, border_parts,
    combine_run, draw_order, finish_triangle_frame, patch_parts, prepare_leaf, run_kind,
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
# image's shader data is read every frame, through the rest. A path's
# also include the two its derived columns' refresh reads through, which
# compare_rows takes to rewrite them from the other columns alone. Any
# other definition, a subclass's or an instance's, may read state no
# revision covers, and its leaf is prepared every frame, as the frame's
# loop reads it.
_VMOBJECT_GETTERS = tuple((name, (method,))
                          for name, method in (*_STANDARD_SOURCE_METHODS, *_STANDARD_MESH_GETTERS,
                                               ("get_subpath_end_indices", VMobject.get_subpath_end_indices),
                                               ("get_area_vector", VMobject.get_area_vector)))
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


def override_text(sm):
    """``sm``'s own uniforms, as prepare_triangle_frame merges them over the
    camera's, and their JSON text, or None where they are not JSON: equal
    text is equal spelling, which equal values need not be (1 and 1.0)."""
    overrides = {key: _jsonable(value) for key, value in sm.uniforms.items()}
    try:
        return overrides, json.dumps(list(overrides.items()))
    except (TypeError, ValueError):
        return overrides, None


# How a path's rows stand against the rows its draws were made from:
# the same bytes, or the same once the read's refresh has rewritten the
# derived columns (compare_rows).
SAME, REFRESHED = "same", "refreshed"
_SOURCE_COLUMNS = {}


def _source_columns(dtype):
    names = _SOURCE_COLUMNS.get(dtype)
    if names is None:
        names = _SOURCE_COLUMNS[dtype] = tuple(name for name in dtype.names if name not in DERIVED_DATA_KEYS)
    return names


def refresh_pending(sm):
    """Whether the next read of ``sm``'s shader data rewrites every derived
    column from the others: both refresh flags set, the joint angles not
    locked, and the subpath ends not cached, so that they come from the
    points too. A path prepared in this state keeps rows that are what
    the refresh makes of their other columns (LeafEntry.ends)."""
    return (isinstance(sm, VMobject) and sm.needs_new_joint_angles and sm.needs_new_unit_normal
            and sm.subpath_end_indices is None and "joint_angle" not in sm.locked_data_keys)


def compare_rows(sm, entry):
    """How a path whose revision moved stands against ``entry.rows``, the
    rows its draws were made from as prepare_leaf left them: SAME, REFRESHED
    or None.

    What prepare_leaf reads of a path (its classification, fill mesh,
    border source and stroke rows) is a function of the rows as its read
    leaves them. Where the read refreshes nothing it leaves them as they
    are, so they must be the same bytes, compared whole in one comparison:
    with neither refresh flag set, and with only the joint angles' where
    the read never reaches them (a fill drawn from its mesh alone, which
    refreshes the unit normal and nothing else). With both set, the read of
    a stroked or bordered path's shader data rewrites every derived column
    (checkpoints.DERIVED_DATA_KEYS) from the others, so those must be the
    same bytes, compared whole first and column by column where the
    derived ones differ (the stale ones an updater's ``become`` copies in);
    and the rewrite must make ``entry.rows`` again: they must be a
    rewrite's own output (``entry.ends`` holds the subpath ends it used,
    and is set only then) and it must use the same ends, cached or
    computed again from the same points, and not find the joint angles
    locked. A path that neither fills nor strokes is read for its
    classification alone. Every other state is None, and the leaf is
    prepared as the frame's loop prepares it, as is a leaf whose rows are
    not known (``entry.rows`` None). Bytes, not values: 0.0 and -0.0 are
    equal and draw different bytes."""
    rows, live = entry.rows, sm._data
    if rows is None or live.dtype != rows.dtype or live.shape != rows.shape:
        return None
    classes = entry.classes
    if classes is not None and not classes[0] and not classes[4]:
        # Nothing to fill and nothing to stroke (a dashed line's own path
        # under its dashes): prepare_leaf reads the classification alone,
        # which these columns decide, and refreshes nothing.
        return SAME if all(live[name].tobytes() == rows[name].tobytes() for name in CLASSIFY_COLUMNS) else None
    joint, normal = sm.needs_new_joint_angles, sm.needs_new_unit_normal
    if not normal and not (joint and entry.shaded):
        return SAME if live.tobytes() == rows.tobytes() else None
    if (not (joint and normal) or entry.ends is None or "joint_angle" in sm.locked_data_keys
            or sm.subpath_end_indices is not None and sm.subpath_end_indices is not entry.ends
            or not live.flags.writeable):
        return None
    if live.tobytes() == rows.tobytes() or all(live[name].tobytes() == rows[name].tobytes()
                                               for name in _source_columns(live.dtype)):
        return REFRESHED
    return None


def refresh_as_read(sm, entry):
    """Leave ``sm`` as the read's refresh would, for a leaf compare_rows
    found REFRESHED: its rows ``entry.rows`` (what the refresh computes
    from these very columns, and what the draws were made from), both
    flags clear, the subpath ends cached. Copied, not computed: the joint
    angles cost ~28 us a path at EpisodeB2's 8.a, the copy under one. The
    scene is then the one the frame's own loop leaves, so a later lock of
    the joint angles, or a write that sets no flag, finds what it would
    find there."""
    np.copyto(sm._data, entry.rows)
    sm.needs_new_joint_angles = sm.needs_new_unit_normal = False
    if sm.subpath_end_indices is None:
        sm.subpath_end_indices = entry.ends
    sm._data_has_changed = True


def plain_inputs(sm):
    """What a plain leaf's shader data is made of beside its rows, read
    through the library's getters (library_getters): a surface's net switch
    and resolution, which decide whether and how the rows are evaluated as
    a net, and the vertex indices that pick the drawn rows (a surface's
    triangles, which sorting its faces reorders in place). None for a dot
    cloud's or an image's, which draw their rows as they are."""
    indices = sm.get_shader_vert_indices()
    return (getattr(sm, "net", None), getattr(sm, "resolution", None),
            None if indices is None else np.asarray(indices).tobytes())


def same_plain(sm, entry):
    """Whether a plain leaf whose revision moved (a dot cloud, a surface's
    grid, an image) would draw what its one draw copied: the same rows,
    byte for byte, as the ones it was made from (never, where those are
    not known), and the same plain_inputs. Compared rather than read: a
    net surface's shader data is its net evaluated again, ~28 us, where
    the comparison costs a few. What the read would have cached (the
    surface's grid at the new revision) is left to the next read."""
    rows, live = entry.rows, sm._data
    return (rows is not None and live.dtype == rows.dtype and live.shape == rows.shape
            and live.tobytes() == rows.tobytes() and plain_inputs(sm) == entry.inputs)


def cached_read(sm, ctx):
    """Whether prepare_leaf may draw ``sm`` from a read a cache made
    earlier at its current revision rather than from its arrays as they
    stand: a path's classification, fill mesh or border source (the
    caches' read_at), a surface's grid (Surface.get_grid_data, cached per
    revision). The revision policy hands such a read back without looking
    at the arrays, so the draws are made from what they held when it was
    made, which an in-place write since then may have changed; only the
    leaf's entry from that frame can say what it was (held_rows). Dot
    clouds and images read their arrays every time."""
    if isinstance(sm, Surface):
        held = getattr(sm, "_grid_cache", None)
        return held is not None and held[0] == sm.revision
    if isinstance(sm, VMobject) and ctx.mesh_cache is not None:
        return ctx.mesh_cache.read_at(sm) or ctx.border_cache is not None and ctx.border_cache.read_at(sm)
    return False


def held_rows(sm, cached, previous, current):
    """The rows a leaf's draws were read from, for the entry of a leaf
    prepare_leaf has just read: its rows as the read left them, frozen, or
    ``previous.rows`` (its last entry's) where those are the same bytes.
    Where a cache held a read of the leaf at its revision (``cached``,
    cached_read before the read), the draws may be made from what that
    read was made from rather than from the arrays: ``previous.rows``
    where that entry is ``current`` (made at this revision, or compared
    to it in this frame, so that the caches' reads at it were made from
    its rows) and the arrays still hold them. Any other rows (a write
    since then that bumped nothing, a read made before this object knew
    the leaf) are not known, and None: the leaf is not compared, and its
    next moved revision has it read in full."""
    live, rows = sm._data, None if previous is None else previous.rows
    if ((current or not cached) and rows is not None and rows.dtype == live.dtype and rows.shape == live.shape
            and rows.tobytes() == live.tobytes()):
        return rows
    if cached:
        return None
    rows = live.copy()
    rows.flags.writeable = False
    return rows


class LeafEntry:
    """One leaf's draws as prepare_leaf made them (``leaf``, a LeafDraws),
    and what they were made under: the leaf (a weak reference) at its
    ``revision``, the frame's interned ``camera_key`` (compared by
    identity), the shared ``uniforms`` its draws reference and the
    ``text`` of the leaf's own (None when they are not a shared set, which
    a camera change cannot write in place), its ``flags`` (leaf_flags), the
    entries the caches held for it that frame, and the sampler-to-hash map
    of its textures. A path also keeps the ``rows`` its draws were read
    from, which compare_rows holds a moved revision to (None where they
    are not known), whether its read goes through its shader data
    (``shaded``: a stroke, or a border source, where a mesh alone reads
    the unit normal), and ``ends``, its cached subpath ends where those
    rows are a refresh's output; a plain leaf, its ``rows`` and the other
    ``inputs`` of its shader data (plain_inputs); a stroke, the
    ``frame_scale`` its count was made at and, from the first zoom on, its
    largest curve's ``sqrt_area``. The flags and the cache entries are also
    what a later increment adopts a leaf by."""

    __slots__ = ("owner", "revision", "camera_key", "uniforms", "text", "leaf", "kind", "flags",
                 "textures", "mesh_entry", "classes", "source_entry", "capacity", "net_entry",
                 "rows", "shaded", "ends", "inputs", "frame_scale", "sqrt_area")

    def __init__(self, sm, camera_key, uniforms, text, leaf, kind):
        self.owner = weakref.ref(sm)
        self.revision = sm.revision
        self.camera_key = camera_key
        self.uniforms = uniforms
        self.text = text
        self.leaf = leaf
        self.kind = kind
        self.flags = leaf_flags(sm)
        # A textured leaf resolved its textures into the LeafDraws; its one
        # draw carries the map.
        self.textures = leaf.draws[0].textures if leaf.textures is not None else None
        self.mesh_entry = self.classes = self.source_entry = self.capacity = self.net_entry = None
        self.rows = self.ends = self.inputs = self.sqrt_area = None
        self.shaded = True
        self.frame_scale = uniforms.get("frame_scale")

    def stroke_holds(self):
        """Whether this leaf's stroke count (if it has a stroke) is the one
        prepare_leaf would make at the frame scale its uniforms now hold:
        without arithmetic at the scale it was made at, and at another
        from the largest curve (geometry._stroke_verts_at), measured once.
        A scale that is not a finite positive float is prepare_leaf's to
        refuse or answer."""
        frame_scale = self.uniforms.get("frame_scale")
        if type(frame_scale) is type(self.frame_scale) and frame_scale == self.frame_scale:
            return True
        for draw in self.leaf.draws:
            if draw.pipeline.startswith("stroke"):
                if type(frame_scale) is not float or not 0 < frame_scale < float("inf"):
                    return False
                if self.sqrt_area is None:
                    self.sqrt_area = _stroke_sqrt_area(draw.vertices)
                if _stroke_verts_at(self.sqrt_area, frame_scale) != draw.count:
                    return False
        self.frame_scale = frame_scale
        return True


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
        # id(merged) -> merged, for the sets whose overrides name no camera
        # uniform: their batches print the overrides alone (encode_draw
        # leaves out what equals the camera), whatever the camera holds.
        self.free = {}

    def merged(self, sm, camera):
        """``sm``'s uniforms over ``camera``'s, as prepare_triangle_frame
        merges them, from the set they belong to, and the set's text: None
        for a dict of the leaf's own, which no camera change is written
        into."""
        overrides, text = override_text(sm)
        if text is None or "NaN" in text:
            # Not JSON (never equal to another leaf's text), or a NaN.
            return {**camera, **overrides}, None
        held = self.sets.get(text)
        if held is not None:
            return held[0], text
        merged = {**camera, **overrides}
        self.sets[text] = (merged, overrides)
        if overrides.keys().isdisjoint(camera):
            self.free[id(merged)] = merged
        return merged, text

    def camera_free(self, uniforms):
        """Whether ``uniforms`` is a set whose overrides name no camera
        uniform, so that a batch drawn with it prints the same uniforms
        under any camera without a NaN."""
        return self.free.get(id(uniforms)) is uniforms

    def camera_moved(self, camera):
        """Write a new camera into every set, its overrides still over it.
        False when the sets were dropped instead, which leaves every dict a
        kept draw references with the old camera."""
        names = tuple(camera)
        if names != self.names:
            # A merged dict keeps the key order it was made with, which
            # follows the camera's names: sets made under other names are
            # made again.
            self.sets.clear()
            self.free.clear()
            self.names = names
            return False
        for merged, overrides in self.sets.values():
            merged.update(camera)
            merged.update(overrides)
        return True

    def prune(self, leaves):
        """Forget the sets no leaf in ``leaves`` (LeafEntries) references."""
        live = {id(entry.uniforms) for entry in leaves}
        self.sets = {text: held for text, held in self.sets.items() if id(held[0]) in live}
        self.free = {key: merged for key, merged in self.free.items() if key in live}


class RunMemo:
    """One coalesced run kept across frames: its ``members`` (the leaves'
    draws, held so that their ids stay theirs), the ``draw`` they combine
    into, and for a run the border cache assembles, the ``key`` it keeps
    the assembly under and the ``assembly`` it gave back; then the run's
    encoded descriptor (``batch``, in the form encode_draw wrote it last),
    the camera it was encoded under and whether the descriptor holds under
    any other (``free``), the ``record`` of what it named, and its text
    once the receiver holds it."""

    __slots__ = ("members", "draw", "key", "assembly", "batch", "camera_key", "free", "record", "held_text")

    def __init__(self, members, draw):
        self.members = members
        self.draw = draw
        self.key = self.assembly = None
        self.batch = self.camera_key = self.record = self.held_text = None
        self.free = False

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
        # The last frame's counts: leaves kept (those among them whose
        # revision moved, and whose camera moved) and prepared, runs kept
        # and combined, descriptors reused and encoded.
        self.stats = {}

    def retained_bytes(self):
        """What this object keeps between frames that no cache's budget
        counts: the rows prepare_leaf copied for strokes and plain leaves,
        each path's rows as its draws were read from them, a fill mesh the
        mesh cache did not retain (one larger than its budget), the arrays
        a run of several draws was combined into, and the text of the held
        descriptors. Bounded by one frame's leaves and draws: a gauge's
        business (geometry.retained_frame_bytes), not the budget's."""
        arrays = {}
        for entry in self.leaves.values():
            if entry.rows is not None:
                arrays[id(entry.rows)] = entry.rows.nbytes
            for draw in entry.leaf.draws:
                if entry.kind is PLAIN or draw.pipeline.startswith("stroke"):
                    arrays[id(draw.vertices)] = draw.vertices.nbytes
                elif entry.kind is ROWS and entry.mesh_entry is None and draw.indices is not None:
                    for array in (draw.vertices, draw.indices, draw.paint):
                        if isinstance(array, np.ndarray):
                            arrays[id(array)] = array.nbytes
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
        camera_key, followed = self._camera_key(ctx)
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
        # The walk writes nothing: it decides from each leaf as it stands,
        # before any leaf is read. Its plan, per leaf in draw order: the
        # leaf, the entry to keep if the caches still hold it (None:
        # prepare it), the leaf's last entry, the uniforms and their text
        # it is drawn with, the revision the walk saw, the verdict of a
        # moved revision's comparison, and whether the camera moved under
        # the entry.
        plan, records = [], []
        for sm in draw_order(scene):
            previous = leaves.get(id(sm))
            if previous is not None and previous.owner() is not sm:
                previous = None
            entry, verdict, moved = previous, None, False
            if (trusting and entry is not None and entry.kind is not PROGRAM
                    and not (programs and sm._program is not None)
                    and entry.flags == leaf_flags(sm) and library_getters(sm)):
                # Its draws reference uniforms a moved camera was written
                # into, or the leaf is prepared; then its revision holds,
                # or its source is compared.
                moved = entry.camera_key is not camera_key
                if moved and not (followed and entry.text is not None):
                    entry = None
                elif entry.revision != sm.revision:
                    verdict = None if sm._program is not None else self._verdict(sm, entry)
                    if verdict is None:
                        entry = None
            else:
                entry = None
            if entry is None:
                uniforms, text = sets.merged(sm, camera)
                records.append((sm, uniforms))
                plan.append((sm, None, previous, uniforms, text, sm.revision, None, False))
                continue
            mesh_entry = entry.mesh_entry
            if mesh_entry is not None and (moved or mesh_entry.projection_key is None):
                # A mesh made last frame has no error bound yet, and after a
                # camera move none has one at this camera: the frame's own
                # loop bounds them now, stacked with every other unbounded
                # mesh, and so are they here, in that company.
                records.append((sm, entry.uniforms))
            plan.append((sm, entry, previous, entry.uniforms, entry.text, sm.revision, verdict, moved))
        if mesh_cache is not None:
            mesh_cache.bound_errors(records, frame.resolution)
        if ctx.fill_borders and ctx.fill_builder is None and not ctx.gpu_borders:
            ctx.borders = _prepare_border_geometry(records, mesh_cache)
        # In draw order, as the frame's own loop reads the caches: their
        # recency decides what a budget evicts.
        kept, prepared, compared_kept, revalidated = {}, 0, 0, 0
        for sm, entry, previous, uniforms, text, revision, verdict, moved in plan:
            if entry is not None:
                if sm.revision != revision:
                    # An earlier leaf's read moved this one after the walk
                    # saw it (a getter of its own may write to any mobject):
                    # the frame's loop reads it as it now stands.
                    entry = verdict = None
                elif verdict is REFRESHED:
                    # Here, in the leaf's own place, where its read would
                    # refresh it: a leaf read before it (a program packing
                    # its endpoints' rows) finds it unrefreshed, as in the
                    # frame's loop, and a frame refused before it leaves
                    # it alone.
                    refresh_as_read(sm, entry)
            if entry is None or not self._keep(sm, entry, ctx, frame, revision, moved):
                cached = cached_read(sm, ctx)
                current = previous is not None and (previous.revision == sm.revision or verdict is not None)
                refresh = refresh_pending(sm)
                leaf = prepare_leaf(sm, uniforms, ctx)
                entry = self._entry(sm, leaf, uniforms, text, ctx, camera_key, refresh=refresh, cached=cached,
                                    previous=previous, current=current)
                prepared += 1
            else:
                if verdict is not None:
                    entry.revision = revision
                    compared_kept += 1
                if moved:
                    entry.camera_key = camera_key
                    revalidated += 1
            kept[id(sm)] = entry
            frame.add_leaf(entry.leaf)
        self.leaves = kept
        self.stats = {"leaves_kept": len(plan) - prepared, "leaves_prepared": prepared,
                      "leaves_compared": compared_kept, "leaves_revalidated": revalidated,
                      "runs_kept": 0, "runs_combined": 0}
        if len(sets.sets) > 2 * len(kept) + 64:
            sets.prune(kept.values())
        self._frame_runs, self._next_runs = [], {}
        frame = finish_triangle_frame(frame, ctx, kind=memoized_run_kind, combine=self._combine)
        self.runs, self._next_runs = self._next_runs, {}
        return frame

    def _camera_key(self, ctx):
        """The frame's camera as one object, the same object for as long as
        the camera is unchanged, and whether the uniform sets follow it:
        False when a change dropped them rather than writing into them.
        Its JSON text, like a uniform set's: equal text is equal spelling
        and equal bits, where equal values could be 0.0 and -0.0."""
        key = json.dumps([list(ctx.camera_uniforms.items()), ctx.resolution, ctx.pixel_tolerance])
        if key == self.camera_key:
            return self.camera_key, True
        self.camera_key = key
        return key, self.uniform_sets.camera_moved(ctx.camera_uniforms)

    @staticmethod
    def _verdict(sm, entry):
        """How a leaf whose revision moved stands against what its draws
        were made from, its own uniforms included: SAME, REFRESHED (a path
        whose read's refresh would leave its rows as they were made from),
        or None, where it is prepared. Most bumps change no byte (a zero
        shift, an updater writing the same corners, ``become`` of an
        unchanged target). Nothing is written here: the walk runs before
        any leaf is read, and a REFRESHED leaf is refreshed in its own
        place in the order. A net's rows are the net cache's to compare,
        where the frame reads them (_keep)."""
        kind = entry.kind
        if kind is ROWS:
            verdict = compare_rows(sm, entry)
        else:
            verdict = SAME if kind is NET or same_plain(sm, entry) else None
        if verdict is None or entry.text is None or override_text(sm)[1] != entry.text:
            return None
        return verdict

    @staticmethod
    def _keep(sm, entry, ctx, frame, revision, moved):
        """Whether ``entry``'s draws stand for ``sm`` in this frame, at the
        ``revision`` the walk saw. The caches are told the leaf's entries
        were used, as prepare_leaf's reads would tell them, and must still
        hold exactly the entries its draws were read from; a textured
        leaf's files are hashed again, the payloads going to the frame as
        prepare_leaf sends them. A leaf compared at another revision than
        its entry's has its entries stamped with the walk's (the one its
        rows were compared at, never one read after other leaves ran); one
        whose camera ``moved`` has its mesh held to its error bound, its
        reservations to the new zoom and its stroke count to the new frame
        scale, each as prepare_leaf's reads would decide them."""
        kind = entry.kind
        compared = entry.revision != revision
        if kind is ROWS:
            # The border source before the mesh, as prepare_leaf reads them:
            # a camera either refuses is refused with the same error.
            stamp = revision if compared else None
            source_entry, capacity = ctx.border_cache.keep(sm, revision=stamp,
                                                           uniforms=entry.uniforms if moved else None)
            camera = (entry.uniforms, ctx.resolution, ctx.pixel_tolerance) if moved else None
            mesh_entry, classes = ctx.mesh_cache.keep(sm, revision=stamp, camera=camera)
            if (mesh_entry is not entry.mesh_entry or classes is not entry.classes
                    or source_entry is not entry.source_entry or capacity != entry.capacity):
                return False
            if moved and mesh_entry is None and classes is not None and classes[0] and not ctx.patch_fills:
                # A fill whose mesh the cache holds none of (one larger
                # than its budget is drawn and not retained): mesh() makes
                # it again at every camera, and so does prepare_leaf.
                return False
            if moved and not entry.stroke_holds():
                return False
        elif kind is NET:
            if compared or moved:
                # The read itself: the net cache compares the rows with the
                # bytes it packed and reserves for this zoom.
                net_entry = ctx.net_cache.source(
                    sm, revision=revision, pixels_per_unit=pixels_per_unit(ctx.camera_uniforms, ctx.resolution),
                    frame_scale=entry.uniforms["frame_scale"])
                if net_entry is not entry.net_entry or net_entry.capacity != entry.leaf.draws[0].net_capacity:
                    return False
            elif ctx.net_cache.keep(sm) is not entry.net_entry:
                return False
        return entry.textures is None or frame.texture_refs(sm) == entry.textures

    @staticmethod
    def _entry(sm, leaf, uniforms, text, ctx, camera_key, *, refresh, cached, previous, current):
        """The LeafEntry of a leaf prepare_leaf has just prepared, with the
        cache entries it read.

        A path's or a plain leaf's keeps the rows its draws were read from
        (held_rows): its rows as the read left them, where no cache held a
        read of the leaf at its revision (``cached``, cached_read before
        the read); where one did, the rows that read was made from, which
        are ``previous``'s (the leaf's last entry) where that entry was
        made at this revision or compared to it in this frame
        (``current``) and the arrays hold them still, and are otherwise
        not known. A path's also keeps, where those rows are a refresh's
        own output, the subpath ends it used: where they are still
        ``previous``'s, which were, with the same ends and nothing to
        refresh, or where ``refresh`` (refresh_pending before the read) was
        true and the read did refresh them."""
        entry = LeafEntry(sm, camera_key, uniforms, text, leaf, _leaf_kind(sm, leaf.draws))
        if entry.kind is ROWS and ctx.mesh_cache is not None:
            entry.mesh_entry, entry.classes = ctx.mesh_cache.held(sm)
            if ctx.border_cache is not None:
                entry.source_entry, entry.capacity = ctx.border_cache.held(sm)
            if entry.classes is not None:
                # Whether the read went through the shader data, by what
                # prepare_leaf read rather than what the caches kept.
                has_fill, _, has_border, _, has_stroke = entry.classes
                entry.shaded = has_stroke or (has_fill and (has_border or ctx.patch_fills))
            entry.rows = held_rows(sm, cached, previous, current)
            if entry.rows is not None and not sm.needs_new_joint_angles and not sm.needs_new_unit_normal:
                if (previous is not None and entry.rows is previous.rows and previous.ends is not None
                        and sm.subpath_end_indices is previous.ends):
                    entry.ends = previous.ends
                elif refresh and sm.subpath_end_indices is not None:
                    entry.ends = sm.subpath_end_indices
        elif entry.kind is PLAIN:
            entry.inputs = plain_inputs(sm)
            if entry.inputs == (None, None, None) and leaf.draws:
                # A dot cloud's or an image's draw copied its rows as they
                # are: they are the rows to compare with.
                entry.rows = leaf.draws[0].vertices
            else:
                entry.rows = held_rows(sm, cached, previous, current)
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
        # A batch names the camera only where its draw's uniforms differ
        # from it: nowhere, for a set whose overrides name no camera
        # uniform, unless a NaN (unequal to itself) is on either camera.
        # Such a run's descriptor survives a camera move; a zoom that
        # changes what a run draws has already made it another run.
        portable = "NaN" not in camera_key
        texts, reused = [], 0
        for memo in runs:
            if ((memo.camera_key is camera_key or (memo.free and portable))
                    and memo.record.names <= sent):
                if memo.batch is not None:
                    texts.append(memo.held())
                    parts.carry(memo.record)
                reused += 1
                continue
            record = BatchRecord()
            memo.batch = encode_draw(memo.draw, camera, parts, record=record)
            memo.record, memo.camera_key, memo.held_text = record, camera_key, None
            memo.free = portable and self.uniform_sets.camera_free(memo.draw.uniforms)
            if memo.batch is not None:
                texts.append(json.dumps(memo.batch))
        message = assemble_message(frame, camera, ", ".join(texts), parts, renderer=renderer)
        parts.commit()
        self.stats.update(batches_reused=reused, batches_encoded=len(runs) - reused)
        return message

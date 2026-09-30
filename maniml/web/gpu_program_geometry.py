"""Programs over control-point rows (Phase B3, docs/phase_b3_plan.md).

A program names its sources (a mobject's rows, sent once per play and
retained by content hash) and its scalars (sent per frame). The driver
evaluates the rows (row_blend.wgsl), finalizes them into the curve records
and stroke instances the drawing stages consume (row_finalize.wgsl), and
draws from those buffers instead of uploaded ones.
"""

from __future__ import annotations

import hashlib
import re

import numpy as np

from maniml.web.border_geometry import _border_density, _density_counts
from maniml.web.gpu_border_geometry import (
    MAX_VERTICES_PER_CURVE, MIN_VERTICES_PER_CURVE, readonly, reserve_capacity, required_from_density,
)

ROW_FLOATS = 17  # a VMobject's data row
RECORD_FLOATS = 44
STROKE_FLOATS = 51
# kind -> (number of sources, number of scalars on the wire)
PROGRAM_KINDS = {"blend": (2, 1), "affine": (1, 16), "paint": (1, 2), "partial": (1, 5)}
SOURCE_HASH_PREFIX = b"maniml.rows.f32.v1\0"
_HASH = re.compile(r"[0-9a-f]{32}")


def pack_rows(mobject):
    """A mobject's data as an immutable float32 (rows, channels) array.

    A VMobject's base point rows are its first point, as
    VMobject.get_shader_data writes them on every read of the CPU path:
    each row kernel takes them from its sources so (a blend lerps them,
    an affine map moves them with the points), and the patch fill fans
    from them. ``programs.freshen`` writes them at an animation's begin,
    but a source rebuilt after it (an updater's become() on a starting
    or target copy, which Animation.update_mobjects runs every frame)
    holds whatever the rows it copied held."""
    data = np.array(mobject.data)
    if "base_normal" in (data.dtype.names or ()) and len(data):
        data["base_normal"][0::2] = data["point"][0]
    channels = data.dtype.itemsize // 4
    rows = data.view(np.float32).reshape(len(data), channels)
    if not np.isfinite(rows).all():
        raise ValueError("program source rows must be finite")
    return readonly(rows)


def rows_hash(rows):
    digest = hashlib.blake2b(digest_size=16)
    digest.update(SOURCE_HASH_PREFIX + np.asarray(rows.shape, dtype="<u8").tobytes())
    digest.update(memoryview(np.ascontiguousarray(rows, dtype="<f4")).cast("B"))
    return digest.hexdigest()


def program_key(kind, source_hashes):
    """The identity of a program apart from its per-frame scalars."""
    digest = hashlib.blake2b(digest_size=16)
    digest.update(b"maniml.program.v1\0" + kind.encode() + b"\0")
    for source in source_hashes:
        digest.update(source.encode() + b"\0")
    return digest.hexdigest()


def rows_key(source_hashes, paint_hashes=None):
    """The name of the curve records a run of row sources finalizes into
    (MANIML_PATCH_SOURCE=rows, docs/phase_b4_plan.md B5.1): its objects'
    rows, in order, stand for them, so it is a digest of their hashes.
    Since B5.8 a row source is its geometry and its paint (split_rows),
    and the records are made of both: each object's pair, in order."""
    digest = hashlib.blake2b(digest_size=16)
    if paint_hashes is None:
        digest.update(b"maniml.rows.run.v1\0")
        for source in source_hashes:
            digest.update(source.encode() + b"\0")
        return digest.hexdigest()
    if len(paint_hashes) != len(source_hashes):
        raise ValueError("a row source's geometry and paint go in pairs")
    digest.update(b"maniml.rows.run.v2\0")
    for source, paint in zip(source_hashes, paint_hashes):
        digest.update(source.encode() + b"\0" + paint.encode() + b"\0")
    return digest.hexdigest()


# A row source on the wire (docs/phase_b4_plan.md, B5.8): VMobject's
# seventeen columns split into the geometry the finalized records and
# instances are made of, keyed on those columns alone, and the paint, so a
# change of colour or opacity alone (a dim at a pausepoint) sends the paint
# and none of the rows. Geometry: point, stroke width, joint angle, base
# point or unit normal, fill border width. Paint: stroke RGBA, fill RGBA,
# one row where every row carries the same (bit for bit), which the drivers
# read at stride 0.
GEOMETRY_COLUMNS = (0, 1, 2, 7, 8, 13, 14, 15, 16)
PAINT_COLUMNS = (3, 4, 5, 6, 9, 10, 11, 12)
GEOMETRY_FLOATS, PAINT_FLOATS = len(GEOMETRY_COLUMNS), len(PAINT_COLUMNS)
_GEOMETRY_INDEX, _PAINT_INDEX = np.array(GEOMETRY_COLUMNS), np.array(PAINT_COLUMNS)
_F4 = np.dtype("<f4")
_UNIFORM_PAINTS = {}


def _backing(array):
    """The bytes an array made here is a view of (None for any other)."""
    while isinstance(array, np.ndarray):
        array = array.base
    return array if isinstance(array, bytes) else None


def split_rows(rows, previous=None):
    """(geometry, paint) of float32 VMobject ``rows``, each immutable
    (bytes-backed, so a serializer memoizes its digest by identity): the
    geometry columns, and the paint columns, one row when every row's bits
    are the same. Where ``previous`` (an earlier split of the same path)
    holds the same bytes, its array is handed back, so an unchanged half
    keeps its identity and its digest; a uniform paint is shared by every
    path that has it. A mover pays this every frame, so it is kept to a few
    calls: the paint's uniformity is its bytes against its first row's."""
    if type(rows) is not np.ndarray:
        rows = np.asarray(rows)
    if rows.ndim != 2 or rows.shape[1] != ROW_FLOATS or rows.dtype != _F4:
        raise ValueError("row sources must be float32 VMobject rows")
    count = len(rows)
    held_geometry, held_paint = (None, None) if previous is None else previous
    geometry = rows[:, _GEOMETRY_INDEX].tobytes()
    if held_geometry is not None and _backing(held_geometry) == geometry:
        geometry = held_geometry
    else:
        geometry = np.ndarray((count, GEOMETRY_FLOATS), dtype=_F4, buffer=geometry)
    paint = rows[:, _PAINT_INDEX].tobytes()
    first = paint[:4 * PAINT_FLOATS]
    if count and (paint == first * count if count <= 256
                  else bool((rows[:, _PAINT_INDEX].view("<u4") == np.frombuffer(first, "<u4")).all())):
        shared = _UNIFORM_PAINTS.get(first)
        if shared is None:
            if len(_UNIFORM_PAINTS) >= 4096:
                _UNIFORM_PAINTS.clear()
            shared = _UNIFORM_PAINTS[first] = np.ndarray((1, PAINT_FLOATS), dtype=_F4, buffer=first)
        return geometry, shared
    if held_paint is not None and _backing(held_paint) == paint:
        return geometry, held_paint
    return geometry, np.ndarray((count, PAINT_FLOATS), dtype=_F4, buffer=paint)


def join_rows(geometry, paint):
    """The seventeen-column rows ``split_rows`` split, from the geometry
    and the paint (one row or one per geometry row): what every driver's
    finalize reconstructs of them."""
    geometry, paint = np.asarray(geometry, dtype="<f4"), np.asarray(paint, dtype="<f4")
    rows = np.empty((len(geometry), ROW_FLOATS), dtype="<f4")
    rows[:, GEOMETRY_COLUMNS] = geometry
    rows[:, PAINT_COLUMNS] = paint
    return rows


def validate_program(program, stride=None):
    """The descriptor on the wire: kind, sources, scalars, rows, channels."""
    if not isinstance(program, dict):
        raise ValueError("invalid program descriptor")
    kind, sources, scalars = program.get("kind"), program.get("sources"), program.get("scalars")
    rows, channels = program.get("rows"), program.get("channels")
    if (kind not in PROGRAM_KINDS or not isinstance(sources, (list, tuple))
            or len(sources) != PROGRAM_KINDS[kind][0]
            or any(not isinstance(s, str) or _HASH.fullmatch(s) is None for s in sources)
            or not isinstance(scalars, (list, tuple)) or len(scalars) != PROGRAM_KINDS[kind][1]
            or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not np.isfinite(v) for v in scalars)
            or isinstance(rows, bool) or not isinstance(rows, int) or rows < 1
            or isinstance(channels, bool) or not isinstance(channels, int) or channels < 1
            or (stride is not None and channels * 4 != stride)
            or (kind != "blend" and channels != ROW_FLOATS)):
        raise ValueError("invalid program descriptor")
    scalars = [float(v) for v in scalars]
    if kind == "partial":
        lower, lower_residue, upper, upper_residue, full = scalars
        curves = rows // 2
        if (any(v != int(v) for v in (lower, upper, full)) or full not in (0, 1)
                or not 0 <= lower < max(1, curves) or not 0 <= upper < max(1, curves)
                or not 0 <= lower_residue <= 1 or not 0 <= upper_residue <= 1):
            raise ValueError("invalid partial program scalars")
    return kind, list(sources), scalars, rows, channels


def wire_scalars(kind, scalars, rows):
    """The scalars a program sends, from what the animation recorded: a
    ``partial`` records its proportions (a, b) and sends the curve indices
    and residues the CPU derives from them (``integer_interpolate``, in
    float64), so the kernel's only arithmetic is the Bézier evaluation."""
    if kind != "partial":
        return [float(v) for v in scalars]
    from maniml.utils.bezier import integer_interpolate
    a, b = scalars
    curves = int(rows) // 2
    lower, lower_residue = integer_interpolate(0, curves, a)
    upper, upper_residue = integer_interpolate(0, curves, b)
    return [float(lower), float(lower_residue), float(upper), float(upper_residue),
            1.0 if a <= 0 and b >= 1 else 0.0]


def curve_count(rows):
    """Curves in a VMobject of ``rows`` control points: (rows - 1) // 2, the
    outer-vertex pattern's count; zero when there is no complete curve."""
    return max(0, (int(rows) - 1) // 2)


def _curve_points(rows):
    """(N, 3, 3) float32 control points of the rows' complete curves."""
    curves = curve_count(len(rows))
    points = np.asarray(rows)[:2 * curves + 1, :3].astype("f4")
    return np.stack([points[0:-2:2], points[1:-1:2], points[2::2]], axis=1)


class ProgramRecipe:
    """What the draws of a program over VMobject rows need, summarized once
    from its sources: the curve count, which stages apply, the largest
    curve density over both endpoints (a blend's density is at most the
    larger endpoint's, so the reservation follows from it), and the
    object record. Per frame only the zoom-dependent counts are evaluated,
    and the border reservation is kept across frames as a retained
    source's is. ``aligned`` is False when the sources cannot stand for
    the rows (shape, or no complete curve)."""

    def __init__(self, sources):
        self.sources = tuple(sources)
        rows = len(self.sources[0]) if self.sources else 0
        self.rows, self.curves = rows, curve_count(rows)
        self.aligned = bool(self.sources) and self.curves > 0 and all(
            s.shape == (rows, ROW_FLOATS) for s in self.sources)
        self.capacity = None
        # The stroke count at the last frame scale asked for, which a play
        # rarely moves: (frame_scale, count).
        self._stroke_count = (None, None)
        if not self.aligned:
            return
        self.has_fill = any(bool(np.any(s[:, 12] != 0)) for s in self.sources)
        self.has_stroke = any(bool(np.any(s[:, 7] != 0) and np.any(s[:, 6] != 0)) for s in self.sources)
        self.bordered = int(any(bool(np.any(s[:, 16] != 0)) for s in self.sources))
        self.uniform_fill = all(bool(np.all(s[:, 9:13] == s[0, 9:13])) for s in self.sources)
        densities = [_border_density(_curve_points(s)) for s in self.sources]
        self.capped = any(bool(np.isposinf(d).any()) for d in densities)
        finite = [d[np.isfinite(d)] for d in densities]
        self.density = max((float(f.max()) for f in finite if len(f)), default=0.0)
        # Step counts are monotone in density, so the largest (possibly
        # overflowed) density decides the largest count.
        self.stroke_density = np.float32(max(float(d.max()) for d in densities))
        self.fill_record = fill_record(self.sources[0], self.bordered)

    def stroke_vertices(self, frame_scale):
        """The strip vertex count a stroke draw reserves: twice the largest
        count either endpoint needs at this zoom, capped at the shader's
        64, so the bulge a blend can make between them is covered."""
        scale, count = self._stroke_count
        if scale != frame_scale:
            counts = _density_counts(np.asarray([self.stroke_density], dtype="f4"), frame_scale)
            count = int(min(64, 2 * max(2, 2 * int(counts.max()))))
            self._stroke_count = (frame_scale, count)
        return count

    def border_capacity(self, frame_scale):
        """The border reservation at this zoom: twice the endpoints' need,
        as the stroke count is, kept while it still fits."""
        needed = min(MAX_VERTICES_PER_CURVE, 2 * required_from_density(self.density, self.capped, frame_scale))
        self.capacity = reserve_capacity(max(MIN_VERTICES_PER_CURVE, needed), self.capacity)
        return self.capacity


def fill_record(rows, bordered):
    """The patch fill's object record for a program, complete since no run
    assembly fills it in: the base point is the first source's anchor
    centroid (any fixed point gives the same count), curve offset 0, the
    curve count, the border flag, and sign 0 (ungrouped, since a blend can
    change the winding sign)."""
    rows = np.asarray(rows)
    curves = curve_count(len(rows))
    record = np.zeros((1, 8), dtype="<f4")
    if curves:
        record[0, :3] = rows[:2 * curves + 1:2, :3].astype(float).mean(axis=0)
    record[0, 3:6] = (0, curves, int(bool(bordered)))
    return readonly(record)


# The one dispatch that finalizes a frame's row sources
# (row_finalize_table.wgsl, docs/phase_b4_plan.md B5.8): a four-word
# header, eight words an entry, then the inputs the entries point into, in
# one binding; the outputs in a second, from which the driver copies each
# batch's into the output it owns.
ROW_TABLE_HEADER_WORDS, ROW_TABLE_ENTRY_WORDS = 4, 8
RECORD_WORDS, INSTANCE_WORDS = RECORD_FLOATS, STROKE_FLOATS
ROW_STROKES, ROW_LEGACY = 1, 2
ROW_FINALIZE_BUDGET = 32 << 20


def plan_row_finalize(members, budget=ROW_FINALIZE_BUDGET):
    """Group the row sources a frame finalizes into dispatches, in order.
    ``members`` is a sequence of (geometry, geometry_words, paint,
    paint_words, curves, flags): geometry and paint any hashable naming
    their words (paint None for a legacy seventeen-column rows, whose
    paint is its own; a paint of eight words is read at stride 0), flags
    ROW_STROKES for stroke instances and ROW_LEGACY for such rows. Each
    dispatch is a dict: ``entries`` (index into members, then the table's
    eight words: geometry and paint word, paint stride, output word, curves,
    flags, first curve, 0; the input words counted in the table's word
    space, after every entry), ``inputs`` (name, first word, words: each
    geometry and paint once, in the order the entries name them),
    ``region_bytes`` (the header, the table and the inputs), ``output_bytes``
    and ``curves``. A dispatch stays within ``budget`` in both bindings
    unless one member alone is larger, which is then a dispatch of its own."""
    dispatches, current = [], None
    for index, (geometry, geometry_words, paint, paint_words, curves, flags) in enumerate(members):
        output_words = curves * (INSTANCE_WORDS if flags & ROW_STROKES else RECORD_WORDS)
        new_inputs = [(name, words) for name, words in ((geometry, geometry_words), (paint, paint_words))
                      if name is not None and (current is None or name not in current["offsets"])]
        # The region this member grows: an entry and its inputs the dispatch
        # does not hold yet (its region already counts the header).
        if current is not None and current["entries"] and (
                current["region_bytes"] + 4 * (ROW_TABLE_ENTRY_WORDS + sum(w for _, w in new_inputs)) > budget
                or current["output_bytes"] + 4 * output_words > budget):
            current = None
            new_inputs = [(name, words) for name, words in ((geometry, geometry_words), (paint, paint_words))
                          if name is not None]
        if current is None:
            current = {"entries": [], "inputs": [], "offsets": {}, "input_words": 0,
                       "region_bytes": 4 * ROW_TABLE_HEADER_WORDS, "output_bytes": 0, "curves": 0}
            dispatches.append(current)
        for name, words in new_inputs:
            current["offsets"][name] = current["input_words"]
            current["inputs"].append((name, current["input_words"], words))
            current["input_words"] += words
        stride = 0 if paint is None or paint_words == 8 else 8
        current["entries"].append([index, current["offsets"][geometry],
                                   0 if paint is None else current["offsets"][paint], stride,
                                   current["output_bytes"] // 4, curves, flags, current["curves"], 0])
        current["region_bytes"] = (4 * ROW_TABLE_HEADER_WORDS
                                   + 4 * ROW_TABLE_ENTRY_WORDS * len(current["entries"]) + 4 * current["input_words"])
        current["output_bytes"] += 4 * output_words
        current["curves"] += curves
    for dispatch in dispatches:
        # The inputs follow the table: every word offset moves past it.
        table = ROW_TABLE_ENTRY_WORDS * len(dispatch["entries"])
        for entry in dispatch["entries"]:
            entry[1] += table
            if members[entry[0]][2] is not None:
                entry[2] += table
        dispatch["inputs"] = [(name, first + table, words) for name, first, words in dispatch["inputs"]]
        del dispatch["offsets"]
    return dispatches


def pack_row_region(dispatch, words_of):
    """A dispatch's binding: the header, its table and its inputs, whose
    little-endian bytes ``words_of(name)`` gives."""
    table = [len(dispatch["entries"]), dispatch["curves"], 0, 0]
    for entry in dispatch["entries"]:
        table.extend(entry[1:])
    parts = [np.asarray(table, dtype="<u4").tobytes()]
    parts.extend(words_of(name) for name, _, _ in dispatch["inputs"])
    region = b"".join(parts)
    if len(region) != dispatch["region_bytes"]:
        raise ValueError("a row table's inputs do not match its plan")
    return region

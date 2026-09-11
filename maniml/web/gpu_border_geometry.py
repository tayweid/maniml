"""Retained CPU source recipes for the general GPU fill-border generator.

The CPU still owns public points and validates active triangle budgets. Camera
changes update uniforms; they do not expand border triangles or repack sources.
The output layout deliberately matches the existing surface/paint pipelines.
"""

from collections import OrderedDict
from dataclasses import dataclass
import weakref

import numpy as np

from maniml.web.border_geometry import (
    BorderSource, _BORDER_DTYPE, render_cache_policy, verify_render_cache,
)


CURVE_WORDS = 44
CURVE_BYTES = CURVE_WORDS * 4
# Output vertices reserved per curve: two per subdivision step. The emitter's
# step policy caps at 32 steps, so 64 is the most any curve can use. A run
# reserves what its curves need at the current zoom, with headroom, rather
# than this maximum: the fixed 64 retained nine times the geometry of the
# CPU emitter for a paragraph of text (seventh review, 2026-09-10).
MAX_VERTICES_PER_CURVE = 64
MIN_VERTICES_PER_CURVE = 4
# The patch fill (docs/phase_b1_plan.md) draws six vertices per curve, a fan
# triangle and a patch triangle, pulled from the same curve records; its
# object table carries eight words per object.
PATCH_VERTICES_PER_CURVE = 6
OBJECT_WORDS = 8
OBJECT_BYTES = OBJECT_WORDS * 4
# The format 5 layout: every curve reserved the maximum, and its 186-index
# strip pattern travelled on the wire. Recordings in that format still load.
VERTICES_PER_CURVE = MAX_VERTICES_PER_CURVE
INDICES_PER_CURVE = 186
# WebGPU's portable storage binding limit. Split compatible runs before this
# bound; a single object can bind just its border tail instead of the fill.
MAX_RUN_OUTPUT_BYTES = 128 << 20


def readonly(array):
    return np.frombuffer(array.tobytes(), dtype=array.dtype).reshape(array.shape)


def immutable(array):
    while isinstance(array, np.ndarray):
        if array.flags.writeable:
            return False
        array = array.base
    return isinstance(array, bytes)


def validate_uniforms(uniforms):
    scale = float(uniforms.get("scale_stroke_with_zoom", 1))
    fixed = float(uniforms.get("is_fixed_in_frame", 0))
    camera = np.asarray(uniforms["camera_position"], dtype=float)
    joint = float(uniforms.get("joint_type", 1))
    if (not np.isfinite([scale, fixed, joint]).all() or camera.shape != (3,)
            or not np.isfinite(camera).all()):
        raise ValueError("border camera/style uniforms must be finite")
    if int(joint) not in (0, 1, 2, 3):
        raise ValueError("unknown Manim border joint type")
    factor = .01 * (float(uniforms["frame_scale"]) * (1 - scale) + scale)
    if not np.isfinite(factor) or factor < 0:
        raise ValueError("border width scale must be finite and nonnegative")


def pack_source(source, rgba, *, every_curve=False):
    """44 little-endian float32 words per active quadratic, with authored paint.

    ``every_curve`` packs every quadratic, not only the border-active ones,
    with word 37 saying which are active: the patch fill needs a curve with
    no border to bound the interior all the same."""
    data = source.data
    if (data.ndim != 1 or data.dtype != _BORDER_DTYPE or len(data) % 3
            or source.density.shape != (len(data) // 3,)
            or source.active.shape != (len(data) // 3,) or source.active.dtype != np.dtype(bool)):
        raise ValueError("invalid canonical border source layout")
    for name in data.dtype.names:
        if not np.isfinite(data[name]).all():
            raise ValueError("border source data must be finite")
    if np.any(data["fill_border_width"] < 0):
        raise ValueError("fill border widths must be nonnegative")
    if np.isnan(source.density).any() or np.any(source.density < 0):
        raise ValueError("border density must be nonnegative and not NaN")
    rgba = np.asarray(rgba, dtype="<f4")
    if rgba.shape != (4,) or not np.isfinite(rgba).all():
        raise ValueError("border paint must be four finite float32 values")
    rows = np.ones(len(source.active), dtype=bool) if every_curve else source.active
    packed = np.zeros((int(rows.sum()), CURVE_WORDS), dtype="<f4")
    packed[:, :36] = data.view("f4").reshape(-1, 36)[rows]
    density = source.density[rows]
    capped = np.isposinf(density)
    packed[:, 36] = np.where(capped, 0, density)
    packed[:, 37] = source.active[rows]
    # The historical float32 density can overflow on very large finite
    # curves. Its CPU subdivision policy then always caps at 32. Preserve
    # that behavior without sending nonfinite values to a storage buffer.
    packed[:, 38] = capped
    packed[:, 40:44] = rgba
    return readonly(packed)


def fill_record(curves):
    """The object words the patch fill needs from its packed curves: a base
    point for the fan, then the slots the run assembly fills in (curve
    offset, curve count, bordered). Any fixed point per object gives the
    same winding count; the anchors' centroid keeps the fan's slivers small."""
    curves = np.asarray(curves)
    if curves.ndim != 2 or curves.shape[1] != CURVE_WORDS or not len(curves):
        raise ValueError("a fill record needs at least one packed curve")
    record = np.zeros((1, OBJECT_WORDS), dtype="<f4")
    record[0, :3] = curves[:, 0:3].astype(float).mean(axis=0)
    record[0, 6] = winding_sign(curves)
    return readonly(record)


# Beyond this many curves the sign test is skipped and the object draws on
# its own; the test is quadratic in a contour's samples.
MAX_SIGN_TEST_CURVES = 4096


def canonical_normal(normal):
    """The object's plane normal with a fixed sign: an object's own unit
    normal follows its winding, so the winding sign is taken in this frame,
    which every object of one plane shares."""
    normal = np.asarray(normal, dtype=float)
    if not np.isfinite(normal).all() or not np.linalg.norm(normal) > 0:
        normal = np.array([0.0, 0.0, 1.0])
    normal = normal / np.linalg.norm(normal)
    for component in normal[::-1]:
        if component:
            return normal if component > 0 else -normal
    return normal


def _contour_polygons(curves):
    """The sampled polygon of each subpath: anchor and midpoint per curve, in
    the plane of the object's canonical normal. A subpath ends, as
    ``VMobject.get_subpath_end_indices_from_points`` says, at a curve whose
    handle sits on its anchor and whose next anchor is elsewhere (the
    kernel draws nothing for it). Returns None when a subpath is not closed,
    since its winding is then undefined."""
    p0 = curves[:, 0:3].astype(float)
    p1 = curves[:, 12:15].astype(float)
    p2 = curves[:, 24:27].astype(float)
    normal = canonical_normal(curves[0, 21:24])  # record 1's normal; record 0 holds the base point
    helper = np.array([1.0, 0.0, 0.0]) if abs(normal[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
    u = np.cross(normal, helper)
    u /= np.linalg.norm(u)
    v = np.cross(normal, u)
    ends = np.all(p0 == p1, axis=1) & np.any(np.abs(p1 - p2) > 1e-4, axis=1)
    polygons, start = [], 0
    scale = max(float(np.abs(p0).max()), 1.0)
    for end in [*np.flatnonzero(ends), len(curves)]:
        if end > start:
            a0, h, a1 = p0[start:end], p1[start:end], p2[start:end]
            if np.linalg.norm(a1[-1] - a0[0]) > 1e-6 * scale:
                return None
            mid = 0.25 * a0 + 0.5 * h + 0.25 * a1
            points = np.empty((2 * (end - start), 3))
            points[0::2], points[1::2] = a0, mid
            polygons.append(np.column_stack((points @ u, points @ v)))
        start = end + 1
    return polygons


def _winding_numbers(points, polygon):
    """Winding number of each point with respect to one closed polygon."""
    a = polygon
    b = np.roll(polygon, -1, axis=0)
    px, py = points[:, 0][:, None], points[:, 1][:, None]
    ay, by = a[:, 1][None, :], b[:, 1][None, :]
    cross = (b[:, 0] - a[:, 0])[None, :] * (py - ay) - (b[:, 1] - a[:, 1])[None, :] * (px - a[:, 0][None, :])
    upward = (ay <= py) & (py < by) & (cross > 0)
    downward = (by <= py) & (py < ay) & (cross < 0)
    return upward.sum(axis=1) - downward.sum(axis=1)


def winding_sign(curves):
    """+1 when the object's winding count is nonnegative everywhere, -1 when
    it is nonpositive everywhere, 0 when it changes sign or cannot be told.

    Objects whose counts share a sign can share a stencil count: the sum is
    nonzero exactly on their union, so an opaque same-colour run of them
    draws as one instanced group. A count that changes sign (a hole outside
    its outer contour, a lone clockwise contour beside a counterclockwise
    one) could cancel another object's, so such an object draws alone.
    Checked on the sampled polygons: at every sample of every contour, the
    other contours' winding must keep both sides of that contour on the
    sign's side.
    """
    curves = np.asarray(curves)
    if len(curves) > MAX_SIGN_TEST_CURVES:
        return 0
    polygons = _contour_polygons(curves)
    if polygons is None:
        return 0
    areas = [0.5 * float(np.sum(p[:, 0] * np.roll(p[:, 1], -1) - np.roll(p[:, 0], -1) * p[:, 1]))
             for p in polygons]
    for sign in (1, -1):
        ok = True
        for index, (polygon, area) in enumerate(zip(polygons, areas)):
            if area == 0:
                continue
            others = sum((_winding_numbers(polygon, other) for other_index, other in enumerate(polygons)
                          if other_index != index), np.zeros(len(polygon), dtype=int))
            # A contour oriented with the sign needs the outside to stay on
            # the sign's side; one against it needs the inside to.
            needed = 0 if sign * area > 0 else 1
            if np.any(sign * others < needed):
                ok = False
                break
        if ok:
            return sign
    return 0


def validate_patch_layout(layout, curve_count):
    """The patch run layout: (curve count, bordered, group) per object in
    draw order; consecutive objects with the same group draw as one
    instanced group. Returns it as a list of lists."""
    if not isinstance(layout, (list, tuple)) or not layout:
        raise ValueError("invalid patch run layout")
    parts = []
    for item in layout:
        if (not isinstance(item, (list, tuple)) or len(item) != 3
                or any(isinstance(v, bool) or not isinstance(v, (int, np.integer)) for v in item)
                or item[0] < 1 or item[1] not in (0, 1) or item[2] < 0):
            raise ValueError("invalid patch run layout")
        parts.append([int(v) for v in item])
    if sum(curves for curves, _, _ in parts) != curve_count:
        raise ValueError("patch run layout does not match its source array")
    return parts


def patch_groups(layout):
    """(first object, object count, first curve, curve count, bordered) per
    run of consecutive objects sharing a group id."""
    groups, curve_offset = [], 0
    for index, (curves, bordered, group) in enumerate(layout):
        if groups and groups[-1][5] == group:
            first, count, first_curve, total, any_border, _ = groups[-1]
            groups[-1] = (first, count + 1, first_curve, total + curves, any_border or bool(bordered), group)
        else:
            groups.append((index, 1, curve_offset, curves, bool(bordered), group))
        curve_offset += curves
    return [group[:5] for group in groups]


def patch_draw_count(layout, capacity):
    """Vertices the cover draws for a run: six per curve, plus each bordered
    object's strip pattern at the run's capacity."""
    strip = indices_per_curve(capacity)
    return sum(curves * (PATCH_VERTICES_PER_CURVE + (strip if bordered else 0))
               for curves, bordered, *_ in layout)


def validate_objects(objects, layout):
    """The object table on the wire against its layout: base points finite,
    the run slots exactly what the layout says."""
    objects = np.asarray(objects)
    if (objects.ndim != 2 or objects.shape[1] != OBJECT_WORDS or objects.dtype != np.dtype("<f4")
            or len(objects) != len(layout) or not np.isfinite(objects).all()):
        raise ValueError("invalid patch object table")
    offset = 0
    for record, (curves, bordered, _) in zip(objects, layout):
        if (record[3] != offset or record[4] != curves or record[5] != bordered
                or record[6] not in (-1, 0, 1) or record[7] != 0):
            raise ValueError("patch object table does not match its run layout")
        offset += curves
    return objects


def validate_capacity(capacity):
    if (isinstance(capacity, bool) or not isinstance(capacity, (int, np.integer))
            or capacity % 2 or not MIN_VERTICES_PER_CURVE <= capacity <= MAX_VERTICES_PER_CURVE):
        raise ValueError("border capacity must be an even vertex count between 4 and 64")
    return int(capacity)


def indices_per_curve(capacity):
    """Six indices per strip quad; a curve of ``capacity`` vertices has one fewer
    quad than it has vertex pairs, and unused pairs clamp to a zero-area tail."""
    return 6 * (validate_capacity(capacity) // 2 - 1)


def required_capacity(source):
    """Vertices per curve this source needs at its current zoom: two per step."""
    counts = source.counts[source.active]
    if not len(counts):
        return MIN_VERTICES_PER_CURVE
    return max(MIN_VERTICES_PER_CURVE, int(2 * counts.max()))


def density_summary(source):
    """What a later zoom needs to know about a source: its largest finite
    density and whether any active curve's density overflowed to +inf."""
    density = source.density[source.active]
    if not len(density):
        return 0.0, False
    capped = bool(np.isposinf(density).any())
    finite = density[np.isfinite(density)]
    return (float(finite.max()) if len(finite) else 0.0), capped


def required_from_density(max_density, capped, frame_scale):
    """``required_capacity`` from the summary alone. Step counts are
    ``min(2 + rint(density / frame_scale), 32)`` per curve and monotone in
    density, so the largest density decides the largest count, and an
    overflowed density always takes the 32-step cap (the emitter's policy)."""
    if capped:
        return MAX_VERTICES_PER_CURVE
    scale = np.float32(frame_scale)
    if not np.isfinite(scale) or scale <= 0:
        raise ValueError("frame_scale must be a finite positive float32 value")
    steps = int(min(2 + np.rint(max_density / scale), 32))
    return max(MIN_VERTICES_PER_CURVE, 2 * steps)


def reserve_capacity(needed, previous=None):
    """The fill cache's 2x policy: keep a reservation that still fits, otherwise
    reserve twice the need so a few more zoom steps regenerate nothing."""
    needed = validate_capacity(needed)
    if previous is not None and validate_capacity(previous) >= needed:
        return previous
    return min(MAX_VERTICES_PER_CURVE, 2 * needed)


def border_indices(curve_count, vertex_base=0, capacity=MAX_VERTICES_PER_CURVE):
    """Triangle-list order of the strips, including degenerate tail slots.

    Deterministic from the curve count, base and capacity; both drivers build
    it locally, so it no longer travels on the wire.
    """
    capacity = validate_capacity(capacity)
    steps = 2 * np.arange(capacity // 2 - 1, dtype="u4")
    strip = (steps[:, None] + np.array([0, 1, 2, 1, 2, 3], dtype="u4")).reshape(-1)
    return (np.arange(curve_count, dtype="u4")[:, None] * np.uint32(capacity)
            + strip + np.uint32(vertex_base)).reshape(-1)


# Sources are 176 bytes per curve and must fit one portable storage binding.
MAX_BORDER_CURVES = MAX_RUN_OUTPUT_BYTES // CURVE_BYTES


def validate_layout(layout, fill_indices, fill_vertices, curve_count):
    """The run layout the drivers expand: (fill index count, fill vertex count,
    curve count) per object, in draw order. Returns it as a list of lists."""
    if not isinstance(layout, (list, tuple)) or not layout:
        raise ValueError("invalid GPU border run layout")
    parts = []
    for item in layout:
        if (not isinstance(item, (list, tuple)) or len(item) != 3
                or any(isinstance(v, bool) or not isinstance(v, (int, np.integer)) or v < 0 for v in item)):
            raise ValueError("invalid GPU border run layout")
        parts.append([int(v) for v in item])
    if (any(curves < 1 for _, _, curves in parts)
            or sum(indices for indices, _, _ in parts) != fill_indices
            or sum(vertices for _, vertices, _ in parts) != fill_vertices
            or sum(curves for _, _, curves in parts) != curve_count):
        raise ValueError("GPU border run layout does not match its fill and source arrays")
    return parts


def expand_run_indices(fill_indices, layout, fill_count, capacity):
    """The ordered index buffer both drivers draw: each object's fill indices
    followed by its strip pattern, with every strip addressing the run's
    border storage after all fills."""
    fill_indices = np.asarray(fill_indices, dtype="<u4")
    ordered, index_offset, curve_offset = [], 0, 0
    for indices, _, curves in layout:
        ordered.append(fill_indices[index_offset:index_offset + indices])
        ordered.append(border_indices(curves, fill_count + capacity * curve_offset, capacity))
        index_offset += indices
        curve_offset += curves
    return np.concatenate(ordered).astype("<u4", copy=False)


@dataclass
class _SourceEntry:
    owner: object
    source: BorderSource
    rgba: np.ndarray
    curves: np.ndarray
    frame: int
    revision: int | None = None
    every_curve: bool = False
    # The patch fill's per-object words, its paint field, and whether the
    # source has passed the planar check since it was packed.
    record: np.ndarray | None = None
    paint: np.ndarray | None = None
    checked: bool = False

    @property
    def nbytes(self):
        return sum(a.nbytes for a in self.source.arrays()) + self.rgba.nbytes + self.curves.nbytes


class BorderRecipeCache:
    """Current-frame source snapshots and immutable ordered assemblies, bounded."""

    def __init__(self, max_bytes=64 << 20):
        self.max_bytes = max_bytes
        self.sources = OrderedDict()
        self.runs = OrderedDict()
        # Reservations outlive the budgeted source entries: a few words per
        # object, kept while the object is drawn, so a zoom step that fits
        # the headroom regenerates nothing even with retention disabled.
        self.capacities = {}
        self.frame = 0
        self._bytes = 0
        self.source_updates = 0
        self.assemblies = 0
        self.policy = render_cache_policy()
        self._validated = set()

    @property
    def nbytes(self):
        return self._bytes

    def begin_frame(self):
        self.frame += 1
        self.policy = render_cache_policy()
        self._validated = set()

    def _validate(self, uniforms):
        # Objects share the camera's values; validate each distinct state once per frame.
        key = (uniforms["frame_scale"], uniforms.get("scale_stroke_with_zoom", 1),
               uniforms.get("is_fixed_in_frame", 0), uniforms.get("joint_type", 1),
               tuple(uniforms["camera_position"]))
        if key not in self._validated:
            validate_uniforms(uniforms)
            self._validated.add(key)

    def clear(self):
        self.sources.clear()
        self.runs.clear()
        self.capacities.clear()
        self._bytes = 0

    def _remove_source(self, key):
        self._bytes -= self.sources.pop(key).nbytes

    def _remove_run(self, key):
        value = self.runs.pop(key)
        result = value[1]
        retained = (result[0], result[2]) if key[0] == "patch" else result[:3]
        self._bytes -= sum(a.nbytes for a in (*value[0], *retained))

    def _bound(self):
        while self.nbytes > self.max_bytes:
            if self.runs:
                self._remove_run(next(iter(self.runs)))
            elif self.sources:
                self._remove_source(next(iter(self.sources)))
            else:
                break

    def finish_frame(self):
        for key, entry in list(self.sources.items()):
            if entry.frame != self.frame or entry.owner() is None:
                self._remove_source(key)
        for key, (owner, _, frame, _, _) in list(self.capacities.items()):
            if frame != self.frame or owner() is None:
                del self.capacities[key]
        for key, value in list(self.runs.items()):
            if value[2] != self.frame:
                self._remove_run(key)
        self._bound()

    def source(self, mobject, uniforms, *, revision=None, every_curve=False):
        """Packed curve records for ``mobject``. With ``revision`` (the
        mobject's current ``Mobject.revision``) and the revision policy, an
        entry read at the same revision is reused without comparing bytes.
        ``every_curve`` is the patch fill's packing (see ``pack_source``)."""
        self._validate(uniforms)
        previous = self.sources.get(id(mobject))
        if previous is not None and (previous.owner() is not mobject
                                     or previous.every_curve != every_curve):
            previous = None
        trusted = (self.policy == "revision" and revision is not None
                   and previous is not None and previous.revision == revision)
        if trusted and not verify_render_cache() and id(mobject) in self.capacities:
            # Nothing in the packed curves depends on the camera; a zoom only
            # changes how many steps each curve gets, which the compute stage
            # decides for itself. All the CPU must know is whether the
            # reservation still fits, and the stored density summary answers
            # that without re-reading a single array.
            self._reserve(mobject, None, frame_scale=uniforms["frame_scale"])
            previous.frame = self.frame
            self.sources.move_to_end(id(mobject))
            return previous.curves
        # The CPU triangle budget bounds the CPU emitter's output arrays. GPU
        # output is fixed capacity, already sized and checked against the
        # device's buffer limits by the drivers, so the budget would only
        # turn a deep zoom into a render error.
        source = BorderSource.read(mobject, uniforms, budget=False, trusted=trusted,
                                   previous=None if previous is None else previous.source)
        rgba = np.asarray(mobject.data["fill_rgba"][0], dtype="<f4")
        self._reserve(mobject, source, frame_scale=uniforms["frame_scale"])
        # A fill color change bumps the revision, so a trusted read keeps its paint.
        same_rgba = trusted or (previous is not None and np.array_equal(rgba, previous.rgba))
        if previous is not None and source is previous.source and same_rgba:
            previous.frame = self.frame
            self.sources.move_to_end(id(mobject))
            return previous.curves
        if previous is not None and source.data is previous.source.data and same_rgba:
            curves, record, paint, checked = previous.curves, previous.record, previous.paint, previous.checked
        else:
            curves = pack_source(source, rgba, every_curve=every_curve)
            record = fill_record(curves) if every_curve and len(curves) else None
            paint, checked = None, False
            self.source_updates += 1
        entry = _SourceEntry(weakref.ref(mobject), source.frozen(), readonly(rgba), curves,
                             self.frame, revision, every_curve, record, paint, checked)
        if id(mobject) in self.sources:
            self._remove_source(id(mobject))
        self.sources[id(mobject)] = entry
        self._bytes += entry.nbytes
        self.sources.move_to_end(id(mobject))
        self._bound()
        return curves

    def _reserve(self, mobject, source, *, frame_scale):
        """Reserve for ``source`` at this zoom, or for the retained density
        summary when ``source`` is None (a trusted frame)."""
        previous = self.capacities.get(id(mobject))
        if previous is not None and previous[0]() is not mobject:
            previous = None
        held = None if previous is None else previous[1]
        if source is None:
            max_density, capped = previous[3], previous[4]
        else:
            max_density, capped = density_summary(source)
        capacity = reserve_capacity(required_from_density(max_density, capped, frame_scale), held)
        self.capacities[id(mobject)] = (weakref.ref(mobject), capacity, self.frame, max_density, capped)
        return capacity

    def _entry(self, mobject):
        entry = self.sources.get(id(mobject))
        if entry is None or entry.owner() is not mobject or not entry.every_curve:
            raise KeyError("no patch fill source for this mobject")
        return entry

    def fill_record(self, mobject, check=None):
        """The patch fill's object words for ``mobject``'s current source.
        ``check`` runs once per packing, before the record is first handed
        out: the caller's planar refusal."""
        entry = self._entry(mobject)
        if entry.record is None:
            raise KeyError("no patch fill source for this mobject")
        if not entry.checked:
            if check is not None:
                check()
            entry.checked = True
        return entry.record

    def paint(self, mobject, build):
        """The patch fill's paint field for ``mobject``'s current source,
        built once per packing by ``build()`` (a fill colour change bumps
        the revision, so a trusted read keeps its field)."""
        entry = self._entry(mobject)
        if entry.paint is None:
            entry.paint = build()
        return entry.paint

    def capacity(self, mobject):
        """Vertices per curve reserved for this mobject's current source."""
        entry = self.capacities.get(id(mobject))
        if entry is None or entry[0]() is not mobject:
            raise KeyError("no border reservation for this mobject")
        return entry[1]

    def assemble_patches(self, parts):
        """One patch run: (curves, capacity, record, bordered, shareable) per
        object; ``shareable`` says the object may share a stencil count (an
        opaque, uniform, unshaded painter object; the record's winding sign
        and its colour decide with whom).

        Returns (curves, run capacity, layout, objects): the curves
        concatenated in draw order, the largest reservation, the layout of
        (curve count, bordered, group) per object, and the object table with
        each record's run slots filled in. Nothing here depends on the
        camera.
        """
        arrays = tuple(a for curves, _, record, _, _ in parts for a in (curves, record))
        capacities = tuple(validate_capacity(capacity) for _, capacity, _, _, _ in parts)
        flags = tuple((bool(bordered), bool(shareable)) for _, _, _, bordered, shareable in parts)
        key = ("patch", *(id(a) for a in arrays), *flags)
        cacheable = all(immutable(a) for a in arrays)
        previous = self.runs.get(key)
        if previous is not None and all(a is b for a, b in zip(arrays, previous[0])):
            self.runs[key] = (arrays, previous[1], self.frame)
            self.runs.move_to_end(key)
            curves, layout, objects = previous[1]
            return curves, max(capacities), layout, objects
        curves = readonly(np.concatenate([c for c, _, _, _, _ in parts]))
        objects = np.zeros((len(parts), OBJECT_WORDS), dtype="<f4")
        layout, offset, group, previous = [], 0, -1, None
        for index, ((source, _, record, _, _), (bordered, shareable)) in enumerate(zip(parts, flags)):
            objects[index] = record[0]
            objects[index, 3:6] = (offset, len(source), int(bordered))
            # Consecutive shareable objects of one winding sign and one
            # colour share a group; anything else is a group of its own.
            sign = int(record[0, 6])
            # The normal is compared to three decimals: coplanar objects'
            # normals differ in the last bits (a -0.0 differs from 0.0 in
            # bytes, hence the + 0.0).
            identity = ((sign, source[0, 40:44].tobytes(),
                         (np.round(canonical_normal(source[0, 21:24]), 3) + 0.0).tobytes())
                        if shareable and sign else None)
            if identity is None or identity != previous:
                group += 1
            previous = identity
            layout.append((len(source), int(bordered), group))
            offset += len(source)
        objects = readonly(objects)
        result = (curves, tuple(layout), objects)
        self.assemblies += 1
        if cacheable:
            self.runs[key] = (arrays, result, self.frame)
            self._bytes += sum(a.nbytes for a in (*arrays, curves, objects))
            self._bound()
        return curves, max(capacities), tuple(layout), objects

    def assemble(self, parts):
        """Fill storage first, then border storage, for one run of objects.

        Each part is (fill vertices, fill indices, curves, capacity). Returns
        (vertices, fill indices, curves, run capacity, layout): the fill
        indices are offset into the run's fill storage and cover only fills;
        the layout lists (fill index count, fill vertex count, curve count)
        per part, from which either driver interleaves each object's border
        strip pattern after its fill at the run's capacity.
        """
        arrays = tuple(a for vertices, indices, curves, _ in parts for a in (vertices, indices, curves))
        capacities = tuple(validate_capacity(capacity) for _, _, _, capacity in parts)
        key = (*(id(a) for a in arrays), *capacities)
        cacheable = all(immutable(a) for a in arrays)
        previous = self.runs.get(key)
        if previous is not None and all(a is b for a, b in zip(arrays, previous[0])):
            self.runs[key] = (arrays, previous[1], self.frame)
            self.runs.move_to_end(key)
            return previous[1]
        vertices = readonly(np.concatenate([v for v, _, _, _ in parts]))
        curves = readonly(np.concatenate([c for _, _, c, _ in parts]))
        ordered, layout, fill_offset = [], [], 0
        for verts, indices, source, _ in parts:
            ordered.append(indices + np.uint32(fill_offset))
            layout.append((len(indices), len(verts), len(source)))
            fill_offset += len(verts)
        indices = readonly(np.concatenate(ordered))
        result = (vertices, indices, curves, max(capacities), tuple(layout))
        self.assemblies += 1
        if cacheable:
            self.runs[key] = (arrays, result, self.frame)
            # The identity proof pins its input arrays too. Count them even
            # when another cache shares them, so eviction cannot hide memory.
            self._bytes += sum(a.nbytes for a in (*arrays, *result[:3]))
            self._bound()
        return result

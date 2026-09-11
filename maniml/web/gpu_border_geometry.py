"""Retained CPU source recipes for the general GPU fill-border generator.

The CPU still owns public points and validates active triangle budgets. Camera
changes update uniforms; they do not expand border triangles or repack sources.
The output layout deliberately matches the existing surface/paint pipelines.
"""

from collections import OrderedDict
from dataclasses import dataclass
import weakref

import numpy as np

from maniml.web.border_geometry import BorderSource, _BORDER_DTYPE, render_cache_policy


CURVE_WORDS = 44
CURVE_BYTES = CURVE_WORDS * 4
# Output vertices reserved per curve: two per subdivision step. The emitter's
# step policy caps at 32 steps, so 64 is the most any curve can use. A run
# reserves what its curves need at the current zoom, with headroom, rather
# than this maximum: the fixed 64 retained nine times the geometry of the
# CPU emitter for a paragraph of text (seventh review, 2026-09-10).
MAX_VERTICES_PER_CURVE = 64
MIN_VERTICES_PER_CURVE = 4
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


def pack_source(source, rgba):
    """44 little-endian float32 words per active quadratic, with authored paint."""
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
    packed = np.zeros((int(source.active.sum()), CURVE_WORDS), dtype="<f4")
    packed[:, :36] = data.view("f4").reshape(-1, 36)[source.active]
    density = source.density[source.active]
    capped = np.isposinf(density)
    packed[:, 36] = np.where(capped, 0, density)
    packed[:, 37] = 1
    # The historical float32 density can overflow on very large finite
    # curves. Its CPU subdivision policy then always caps at 32. Preserve
    # that behavior without sending nonfinite values to a storage buffer.
    packed[:, 38] = capped
    packed[:, 40:44] = rgba
    return readonly(packed)


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
        self._bytes -= sum(a.nbytes for a in (*value[0], *value[1][:3]))

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
        for key, (owner, _, frame) in list(self.capacities.items()):
            if frame != self.frame or owner() is None:
                del self.capacities[key]
        for key, value in list(self.runs.items()):
            if value[2] != self.frame:
                self._remove_run(key)
        self._bound()

    def source(self, mobject, uniforms, *, revision=None):
        """Packed curve records for ``mobject``. With ``revision`` (the
        mobject's current ``Mobject.revision``) and the revision policy, an
        entry read at the same revision is reused without comparing bytes."""
        self._validate(uniforms)
        previous = self.sources.get(id(mobject))
        if previous is not None and previous.owner() is not mobject:
            previous = None
        trusted = (self.policy == "revision" and revision is not None
                   and previous is not None and previous.revision == revision)
        # The CPU triangle budget bounds the CPU emitter's output arrays. GPU
        # output is fixed capacity, already sized and checked against the
        # device's buffer limits by the drivers, so the budget would only
        # turn a deep zoom into a render error.
        source = BorderSource.read(mobject, uniforms, budget=False, trusted=trusted,
                                   previous=None if previous is None else previous.source)
        rgba = np.asarray(mobject.data["fill_rgba"][0], dtype="<f4")
        self._reserve(mobject, source)
        # A fill color change bumps the revision, so a trusted read keeps its paint.
        same_rgba = trusted or (previous is not None and np.array_equal(rgba, previous.rgba))
        if previous is not None and source is previous.source and same_rgba:
            previous.frame = self.frame
            self.sources.move_to_end(id(mobject))
            return previous.curves
        if previous is not None and source.data is previous.source.data and same_rgba:
            curves = previous.curves
        else:
            curves = pack_source(source, rgba)
            self.source_updates += 1
        entry = _SourceEntry(weakref.ref(mobject), source.frozen(), readonly(rgba), curves,
                             self.frame, revision)
        if id(mobject) in self.sources:
            self._remove_source(id(mobject))
        self.sources[id(mobject)] = entry
        self._bytes += entry.nbytes
        self.sources.move_to_end(id(mobject))
        self._bound()
        return curves

    def _reserve(self, mobject, source):
        previous = self.capacities.get(id(mobject))
        held = previous[1] if previous is not None and previous[0]() is mobject else None
        capacity = reserve_capacity(required_capacity(source), held)
        self.capacities[id(mobject)] = (weakref.ref(mobject), capacity, self.frame)
        return capacity

    def capacity(self, mobject):
        """Vertices per curve reserved for this mobject's current source."""
        entry = self.capacities.get(id(mobject))
        if entry is None or entry[0]() is not mobject:
            raise KeyError("no border reservation for this mobject")
        return entry[1]

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

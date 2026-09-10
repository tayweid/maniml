"""Retained CPU source recipes for the general GPU fill-border generator.

The CPU still owns public points and validates active triangle budgets. Camera
changes update uniforms; they do not expand border triangles or repack sources.
The output layout deliberately matches the existing surface/paint pipelines.
"""

from collections import OrderedDict
from dataclasses import dataclass
import weakref

import numpy as np

from maniml.web.border_geometry import BorderSource, _BORDER_DTYPE


CURVE_WORDS = 44
CURVE_BYTES = CURVE_WORDS * 4
VERTICES_PER_CURVE = 64
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


def border_indices(curve_count, vertex_base=0):
    """Triangle-list order of the old strips, including degenerate tail slots."""
    steps = 2 * np.arange(31, dtype="u4")
    strip = (steps[:, None] + np.array([0, 1, 2, 1, 2, 3], dtype="u4")).reshape(-1)
    return (np.arange(curve_count, dtype="u4")[:, None] * 64
            + strip + np.uint32(vertex_base)).reshape(-1)


@dataclass
class _SourceEntry:
    owner: object
    source: BorderSource
    rgba: np.ndarray
    curves: np.ndarray
    frame: int

    @property
    def nbytes(self):
        return sum(a.nbytes for a in self.source.arrays()) + self.rgba.nbytes + self.curves.nbytes


class BorderRecipeCache:
    """Current-frame source snapshots and immutable ordered assemblies, bounded."""

    def __init__(self, max_bytes=64 << 20):
        self.max_bytes = max_bytes
        self.sources = OrderedDict()
        self.runs = OrderedDict()
        self.frame = 0
        self._bytes = 0
        self.source_updates = 0
        self.assemblies = 0

    @property
    def nbytes(self):
        return self._bytes

    def begin_frame(self):
        self.frame += 1

    def clear(self):
        self.sources.clear()
        self.runs.clear()
        self._bytes = 0

    def _remove_source(self, key):
        self._bytes -= self.sources.pop(key).nbytes

    def _remove_run(self, key):
        value = self.runs.pop(key)
        self._bytes -= sum(a.nbytes for a in (*value[0], *value[1]))

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
        for key, value in list(self.runs.items()):
            if value[2] != self.frame:
                self._remove_run(key)
        self._bound()

    def source(self, mobject, uniforms):
        validate_uniforms(uniforms)
        previous = self.sources.get(id(mobject))
        if previous is not None and previous.owner() is not mobject:
            previous = None
        source = BorderSource.read(mobject, uniforms,
                                   previous=None if previous is None else previous.source)
        rgba = np.asarray(mobject.data["fill_rgba"][0], dtype="<f4")
        if previous is not None and source is previous.source and np.array_equal(rgba, previous.rgba):
            previous.frame = self.frame
            self.sources.move_to_end(id(mobject))
            return previous.curves
        if (previous is not None and source.data is previous.source.data
                and np.array_equal(rgba, previous.rgba)):
            curves = previous.curves
        else:
            curves = pack_source(source, rgba)
            self.source_updates += 1
        entry = _SourceEntry(weakref.ref(mobject), source.frozen(), readonly(rgba), curves, self.frame)
        if id(mobject) in self.sources:
            self._remove_source(id(mobject))
        self.sources[id(mobject)] = entry
        self._bytes += entry.nbytes
        self.sources.move_to_end(id(mobject))
        self._bound()
        return curves

    def assemble(self, parts):
        """Fill storage first, then border storage; indices preserve object order."""
        arrays = tuple(a for vertices, indices, curves in parts for a in (vertices, indices, curves))
        key = tuple(id(a) for a in arrays)
        cacheable = all(immutable(a) for a in arrays)
        previous = self.runs.get(key)
        if previous is not None and all(a is b for a, b in zip(arrays, previous[0])):
            self.runs[key] = (arrays, previous[1], self.frame)
            self.runs.move_to_end(key)
            return previous[1]
        fill_count = sum(len(vertices) for vertices, _, _ in parts)
        vertices = readonly(np.concatenate([v for v, _, _ in parts]))
        curves = readonly(np.concatenate([c for _, _, c in parts]))
        ordered, fill_offset, curve_offset = [], 0, 0
        for verts, indices, source in parts:
            ordered.append(indices + np.uint32(fill_offset))
            ordered.append(border_indices(len(source), fill_count + 64 * curve_offset))
            fill_offset += len(verts)
            curve_offset += len(source)
        indices = readonly(np.concatenate(ordered))
        result = (vertices, indices, curves)
        self.assemblies += 1
        if cacheable:
            self.runs[key] = (arrays, result, self.frame)
            # The identity proof pins its input arrays too. Count them even
            # when another cache shares them, so eviction cannot hide memory.
            self._bytes += sum(a.nbytes for a in (*arrays, *result))
            self._bound()
        return result

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
PROGRAM_KINDS = {"blend": 2}  # kind -> number of sources
SOURCE_HASH_PREFIX = b"maniml.rows.f32.v1\0"
_HASH = re.compile(r"[0-9a-f]{32}")


def pack_rows(mobject):
    """A mobject's data as an immutable float32 (rows, channels) array."""
    data = np.ascontiguousarray(mobject.data)
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


def validate_program(program, stride=None):
    """The descriptor on the wire: kind, sources, scalars, rows, channels."""
    if not isinstance(program, dict):
        raise ValueError("invalid program descriptor")
    kind, sources, scalars = program.get("kind"), program.get("sources"), program.get("scalars")
    rows, channels = program.get("rows"), program.get("channels")
    if (kind not in PROGRAM_KINDS or not isinstance(sources, (list, tuple))
            or len(sources) != PROGRAM_KINDS[kind]
            or any(not isinstance(s, str) or _HASH.fullmatch(s) is None for s in sources)
            or not isinstance(scalars, (list, tuple)) or len(scalars) != 1
            or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not np.isfinite(v) for v in scalars)
            or isinstance(rows, bool) or not isinstance(rows, int) or rows < 1
            or isinstance(channels, bool) or not isinstance(channels, int) or channels < 1
            or (stride is not None and channels * 4 != stride)):
        raise ValueError("invalid program descriptor")
    return kind, list(sources), [float(v) for v in scalars], rows, channels


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
        counts = _density_counts(np.asarray([self.stroke_density], dtype="f4"), frame_scale)
        return int(min(64, 2 * max(2, 2 * int(counts.max()))))

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

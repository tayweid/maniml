"""Retained control nets for the GPU surface evaluation (Phase B2,
docs/phase_b2_plan.md).

A surface's net travels once per source revision; the driver's compute
stage (net_compute.wgsl) evaluates it at the steps its second difference
needs at the current zoom, into a reserved capacity per patch. The CPU keeps
the density and the reservation, nothing that depends on the camera beyond
the reservation itself, which grows only when a zoom outgrows it.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from functools import lru_cache
import math
import weakref

import numpy as np

from maniml.utils import bezier_net
from maniml.web.border_geometry import render_cache_policy, verify_render_cache


MAX_NET_STEPS = 32
# Never fewer steps than the construction's samples (two per patch):
# lighting is per vertex, so fewer vertices than the samples would shade
# more coarsely than the CPU grid the reference renderers draw.
MIN_NET_STEPS = 2
# The step rule's target: a quarter of an output pixel of chord deviation.
PIXEL_TOLERANCE = 0.25
# A dense net's reservation is bounded per object: the largest steps whose
# (steps + 1)² vertices per patch keep the output under this many bytes.
MAX_NET_OUTPUT_BYTES = 8 << 20


def readonly(array):
    return np.frombuffer(array.tobytes(), dtype=array.dtype).reshape(array.shape)


def pack_net(surface):
    """(net, nu, nv, channels, density): the surface's data as float32
    control points, `channels` per point in the vertex layout its pipeline
    draws, and the largest second difference of its points."""
    nu, nv = surface.resolution
    data = surface.data
    if nu * nv != len(data):
        raise ValueError("a surface's data must be its net")
    channels = data.dtype.itemsize // 4
    net = np.ascontiguousarray(data.view(np.float32).reshape(nu * nv, channels))
    if not np.isfinite(net).all():
        raise ValueError("net control points must be finite")
    density = bezier_net.second_difference(net[:, :3].astype(float).reshape(nu, nv, 3))
    return readonly(net), nu, nv, channels, float(density)


def steps_needed(density, pixels_per_unit, frame_scale):
    """The kernel's rule: steps per patch edge so the chord deviation stays
    under a quarter pixel, at least two, capped."""
    return _steps_needed(float(density), float(pixels_per_unit), float(frame_scale))


# Memoized on its float arguments: the reservation reads it for every net
# on every camera move, and a frame's many equal surfaces share a density.
@lru_cache(maxsize=4096)
def _steps_needed(density, pixels_per_unit, frame_scale):
    pixels = density * pixels_per_unit / frame_scale
    if not np.isfinite(pixels) or pixels <= 4.0:
        return MIN_NET_STEPS
    return int(min(MAX_NET_STEPS, max(MIN_NET_STEPS, np.ceil(np.sqrt(np.float32(pixels))))))


def evaluation_steps(density, rescale_y, height, frame_scale, capacity):
    """The steps a driver evaluates a net at (docs/phase_b4_plan.md, B5.5):
    the kernel's rule, decided where the frame is encoded so that a net's
    output depends on its control points, its capacity and this integer
    alone, and a camera move that leaves it unchanged evaluates nothing.
    Computed in double precision from the descriptor's density and the
    uniforms as packed (float32 y rescale factor and frame scale), as the
    browser driver computes it (netSteps), so both reach the same integer."""
    capacity = validate_capacity(capacity)
    pixels = float(density) * (float(rescale_y) * float(height) / 2.0) / float(frame_scale)
    if not pixels > 4.0:
        return MIN_NET_STEPS
    root = math.sqrt(pixels)
    if root >= capacity:
        return capacity
    return max(MIN_NET_STEPS, min(capacity, math.ceil(root)))


# The table net_compute.wgsl reads: a header of four words (entries,
# patches), then eight words per net (source offset, output offset, nu, nv,
# channels, capacity, steps, first patch), offsets in floats.
NET_TABLE_HEADER_BYTES = 16
NET_ENTRY_BYTES = 32
# A dispatch of several nets gathers their control points into one scratch
# buffer and evaluates into another, each at most this many bytes (and the
# device's storage binding limit); a net whose own output is larger is a
# dispatch of its own, bound directly.
NET_SCRATCH_BUDGET = 32 << 20


def plan_evaluation(nets, budget=NET_SCRATCH_BUDGET):
    """Group the nets a frame evaluates into dispatches, in order. ``nets``
    is a sequence of (source, source_bytes, output_bytes, patches), source
    any hashable naming its control points. Each dispatch is a dict:
    ``entries`` (index into nets, source offset and output offset in floats,
    first patch), ``sources`` (source, byte offset, bytes: what is gathered,
    each source once), ``input_bytes``, ``output_bytes`` and ``patches``.
    A dispatch of one net reads its source and writes its output directly
    (both offsets 0); the others fit ``budget`` in both scratch buffers."""
    dispatches, current = [], None
    for index, (source, source_bytes, output_bytes, patches) in enumerate(nets):
        fresh = current is None or source not in current["offsets"]
        if current is not None and (current["input_bytes"] + (source_bytes if fresh else 0) > budget
                                    or current["output_bytes"] + output_bytes > budget):
            current = None
        if current is None:
            current = {"entries": [], "sources": [], "offsets": {}, "input_bytes": 0, "output_bytes": 0,
                       "patches": 0}
            dispatches.append(current)
        offset = current["offsets"].get(source)
        if offset is None:
            offset = current["offsets"][source] = current["input_bytes"]
            current["sources"].append((source, offset, source_bytes))
            current["input_bytes"] += source_bytes
        current["entries"].append((index, offset // 4, current["output_bytes"] // 4, current["patches"]))
        current["output_bytes"] += output_bytes
        current["patches"] += patches
    for dispatch in dispatches:
        del dispatch["offsets"]
    return dispatches


def pack_table(rows, patches):
    """A dispatch's table: the header, then each row of eight words."""
    words = [len(rows), patches, 0, 0]
    for row in rows:
        words.extend(row)
    return np.asarray(words, dtype="<u4").tobytes()


def dispatch_shape(patches, max_dispatch):
    """Workgroups (x, y) covering ``patches``, one per patch, in rows of at
    most ``max_dispatch``."""
    width = max(1, min(patches, max_dispatch))
    return width, -(-patches // width)


@lru_cache(maxsize=1024)
def steps_cap(patches, stride):
    """The largest reservation whose output stays under MAX_NET_OUTPUT_BYTES."""
    side = int(np.sqrt(MAX_NET_OUTPUT_BYTES // max(1, patches * stride)))
    return max(MIN_NET_STEPS, min(MAX_NET_STEPS, side - 1))


def reserve_steps(needed, previous=None, cap=MAX_NET_STEPS):
    """Keep a reservation that still fits, otherwise twice the need, within
    the object's cap."""
    needed = validate_capacity(needed)
    cap = validate_capacity(cap)
    return _reserve(needed, None if previous is None else validate_capacity(previous), cap)


def _reserve(needed, previous, cap):
    """reserve_steps for step counts the cache made itself (valid by
    construction), without checking them again on every camera move."""
    if previous is not None and previous >= min(needed, cap):
        return previous
    return min(cap, 2 * needed)


def validate_capacity(capacity):
    if (isinstance(capacity, bool) or not isinstance(capacity, (int, np.integer))
            or not MIN_NET_STEPS <= capacity <= MAX_NET_STEPS):
        raise ValueError("net capacity must be a step count between 2 and 32")
    return int(capacity)


def vertices_per_patch(capacity):
    return (validate_capacity(capacity) + 1) ** 2


def indices_per_patch(capacity):
    return 6 * validate_capacity(capacity) ** 2


def net_indices(patches, capacity, vertex_base=0):
    """The triangle list over every patch's (capacity + 1)² grid, in the
    order Surface.compute_triangle_indices uses; deterministic from the
    counts, so both drivers build it locally."""
    capacity = validate_capacity(capacity)
    side = capacity + 1
    a, b = np.meshgrid(np.arange(capacity, dtype="u4"), np.arange(capacity, dtype="u4"), indexing="ij")
    top_left = (a * side + b).reshape(-1)
    quad = np.stack([top_left, top_left + side, top_left + 1,
                     top_left + 1, top_left + side, top_left + side + 1], axis=1).reshape(-1)
    return (np.arange(patches, dtype="u4")[:, None] * np.uint32(side * side)
            + quad + np.uint32(vertex_base)).reshape(-1)


def pixels_per_unit(uniforms, resolution):
    """Output pixels per world unit at frame scale 1, from the camera's
    rescale factor for y and the output height."""
    # float() of the element is what np.asarray(..., dtype=float) makes of
    # it, without building the array: the retained frame asks per net.
    return float(uniforms["frame_rescale_factors"][1]) * float(resolution[1]) / 2.0


_NO_NET = readonly(np.zeros((0, 0), dtype="<f4"))  # a program entry carries no net


@dataclass
class _NetEntry:
    owner: object
    net: np.ndarray
    nu: int
    nv: int
    channels: int
    density: float
    revision: int | None
    frame: int
    capacity: int = MIN_NET_STEPS
    data_bytes: bytes | None = None

    @property
    def patches(self):
        return ((self.nu - 1) // 2) * ((self.nv - 1) // 2)


class NetRecipeCache:
    """Current-frame net snapshots per surface, keyed by revision."""

    def __init__(self, max_bytes=64 << 20):
        self.max_bytes = max_bytes
        self.entries = OrderedDict()
        self.frame = 0
        self._bytes = 0
        # Entries used in the current frame: when every entry was,
        # finish_frame has nothing to sweep.
        self._used = 0
        self.updates = 0
        self.policy = render_cache_policy()
        self.verify = verify_render_cache()

    @property
    def nbytes(self):
        return self._bytes

    def begin_frame(self):
        self.frame += 1
        self._used = 0
        # Read once per frame: ``source`` is asked per surface.
        self.policy = render_cache_policy()
        self.verify = verify_render_cache()

    def clear(self):
        self.entries.clear()
        self._bytes = 0
        self._used = 0

    def _use(self, entry, counted):
        """Stamp ``entry`` used in this frame, counting its place once
        (``counted``: an entry at its place was already used in it)."""
        if not counted:
            self._used += 1
        entry.frame = self.frame

    def finish_frame(self):
        if self._used == len(self.entries) and self._bytes <= self.max_bytes:
            return
        for key, entry in list(self.entries.items()):
            if entry.frame != self.frame or entry.owner() is None:
                self._bytes -= entry.net.nbytes
                del self.entries[key]
        while self._bytes > self.max_bytes and self.entries:
            key = next(iter(self.entries))
            self._bytes -= self.entries.pop(key).net.nbytes

    def _previous(self, surface):
        """The surface's entry, or None. An entry at its id whose owner is
        another object is a dead surface's whose id CPython handed on
        before a finish_frame saw it die: dropped here, bytes and all, or
        the overwrite would leave its bytes counted for good."""
        previous = self.entries.get(id(surface))
        if previous is not None and previous.owner() is not surface:
            self._bytes -= self.entries.pop(id(surface)).net.nbytes
            if previous.frame == self.frame:
                self._used -= 1
            previous = None
        return previous

    def held(self, surface):
        """The net entry this frame read for ``surface``, or None: what a
        caller that keeps the leaf's draws across frames
        (docs/phase_b4_plan.md) records beside them, to compare with what
        ``keep`` answers on a later frame."""
        entry = self.entries.get(id(surface))
        if entry is None or entry.owner() is not surface or entry.frame != self.frame:
            return None
        return entry

    def keep(self, surface):
        """Mark the surface's entry used in this frame, as a trusted
        ``source`` read would, for a caller that reuses the leaf's draws
        without preparing it. The reservation is kept as it stands: at the
        zoom it was made for, the read gives it back unchanged. Returns
        the entry as ``held`` does."""
        entry = self.entries.get(id(surface))
        if entry is None or entry.owner() is not surface:
            return None
        self._use(entry, entry.frame == self.frame)
        self.entries.move_to_end(id(surface))
        return entry

    def source(self, surface, *, revision=None, pixels_per_unit, frame_scale):
        """The surface's net entry, reserved for this zoom."""
        previous = self._previous(surface)
        counted = previous is not None and previous.frame == self.frame
        trusted = (self.policy == "revision" and revision is not None
                   and previous is not None and previous.revision == revision)
        if trusted and self.verify:
            fresh = surface.data.tobytes()
            if fresh != previous.data_bytes:
                from maniml.web.border_geometry import RenderCacheStale
                raise RenderCacheStale(f"{type(surface).__name__} changed in 'data' since its last "
                                       "frame without a revision bump")
        if not trusted:
            raw = surface.data.tobytes()
            if previous is not None and previous.data_bytes == raw:
                entry = previous
            else:
                net, nu, nv, channels, density = pack_net(surface)
                entry = _NetEntry(weakref.ref(surface), net, nu, nv, channels, density, revision, self.frame,
                                  data_bytes=raw)
                if previous is not None:
                    self._bytes -= previous.net.nbytes
                    entry.capacity = previous.capacity
                self.entries[id(surface)] = entry
                self._bytes += net.nbytes
                self.updates += 1
        else:
            entry = previous
        entry.revision = revision
        self._use(entry, counted)
        entry.capacity = _reserve(steps_needed(entry.density, pixels_per_unit, frame_scale), entry.capacity,
                                  steps_cap(entry.patches, entry.channels * 4))
        self.entries.move_to_end(id(surface))
        return entry

    def program_entry(self, surface, sources, *, pixels_per_unit, frame_scale):
        """The entry a program over the surface's net draws from: its
        shape from the surface, its density the larger endpoint's (a
        blend's second difference is at most the endpoints' largest),
        and a reservation kept across frames. Reads no rows of the
        surface itself, which would materialize the program."""
        nu, nv = surface.resolution
        rows, channels = surface.get_num_points(), surface._data.dtype.itemsize // 4
        if nu * nv != rows or any(s.shape != (rows, channels) for s in sources):
            return None
        previous = self._previous(surface)
        counted = previous is not None and previous.frame == self.frame
        key = tuple(id(s) for s in sources)
        if previous is None or previous.data_bytes != key:
            density = max(float(bezier_net.second_difference(
                np.asarray(s[:, :3], dtype=float).reshape(nu, nv, 3))) for s in sources)
            entry = _NetEntry(weakref.ref(surface), _NO_NET, nu, nv, channels, density, None, self.frame,
                              data_bytes=key)
            if previous is not None:
                self._bytes -= previous.net.nbytes
                entry.capacity = previous.capacity
            self.entries[id(surface)] = entry
        else:
            entry = previous
        self._use(entry, counted)
        entry.capacity = _reserve(steps_needed(entry.density, pixels_per_unit, frame_scale), entry.capacity,
                                  steps_cap(entry.patches, entry.channels * 4))
        self.entries.move_to_end(id(surface))
        return entry

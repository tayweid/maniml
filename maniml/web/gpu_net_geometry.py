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
    pixels = float(density) * float(pixels_per_unit) / float(frame_scale)
    if not np.isfinite(pixels) or pixels <= 4.0:
        return MIN_NET_STEPS
    return int(min(MAX_NET_STEPS, max(MIN_NET_STEPS, np.ceil(np.sqrt(np.float32(pixels))))))


def steps_cap(patches, stride):
    """The largest reservation whose output stays under MAX_NET_OUTPUT_BYTES."""
    side = int(np.sqrt(MAX_NET_OUTPUT_BYTES // max(1, patches * stride)))
    return max(MIN_NET_STEPS, min(MAX_NET_STEPS, side - 1))


def reserve_steps(needed, previous=None, cap=MAX_NET_STEPS):
    """Keep a reservation that still fits, otherwise twice the need, within
    the object's cap."""
    needed = validate_capacity(needed)
    cap = validate_capacity(cap)
    if previous is not None and validate_capacity(previous) >= min(needed, cap):
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
    factors = np.asarray(uniforms["frame_rescale_factors"], dtype=float)
    return float(factors[1]) * float(resolution[1]) / 2.0


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
        self.updates = 0
        self.policy = render_cache_policy()

    @property
    def nbytes(self):
        return self._bytes

    def begin_frame(self):
        self.frame += 1
        self.policy = render_cache_policy()

    def clear(self):
        self.entries.clear()
        self._bytes = 0

    def finish_frame(self):
        for key, entry in list(self.entries.items()):
            if entry.frame != self.frame or entry.owner() is None:
                self._bytes -= entry.net.nbytes
                del self.entries[key]
        while self._bytes > self.max_bytes and self.entries:
            key = next(iter(self.entries))
            self._bytes -= self.entries.pop(key).net.nbytes

    def source(self, surface, *, revision=None, pixels_per_unit, frame_scale):
        """The surface's net entry, reserved for this zoom."""
        previous = self.entries.get(id(surface))
        if previous is not None and previous.owner() is not surface:
            previous = None
        trusted = (self.policy == "revision" and revision is not None
                   and previous is not None and previous.revision == revision)
        if trusted and verify_render_cache():
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
        entry.frame = self.frame
        entry.capacity = reserve_steps(steps_needed(entry.density, pixels_per_unit, frame_scale), entry.capacity,
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
        previous = self.entries.get(id(surface))
        if previous is not None and previous.owner() is not surface:
            previous = None
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
        entry.frame = self.frame
        entry.capacity = reserve_steps(steps_needed(entry.density, pixels_per_unit, frame_scale), entry.capacity,
                                       steps_cap(entry.patches, entry.channels * 4))
        self.entries.move_to_end(id(surface))
        return entry

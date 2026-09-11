"""Biquadratic Bézier nets: the surface representation of Phase B2
(docs/phase_b2_plan.md).

A net is an odd-sized grid of control points, ``(2 * pu + 1, 2 * pv + 1,
channels)`` for ``pu × pv`` patches. Patch ``(i, j)`` is the ``3 × 3``
block ``net[2i:2i+3, 2j:2j+3]``; adjacent patches share their edge rows and
columns exactly as a path's curves share anchors. Every channel (points,
colours, image coordinates) is evaluated with the same quadratic Bernstein
weights, so a net carries whatever a surface's vertices carry.

Everything here is float64 NumPy on the CPU; the GPU kernel evaluates the
same net with the same weights.
"""

from __future__ import annotations

import numpy as np


def net_shape(resolution):
    """The net size a requested sample resolution gets: odd, and at least
    three along each axis, so that a ``(2, 2)`` surface is one patch.
    Zero stays zero (an empty surface)."""
    shape = []
    for n in resolution:
        n = int(n)
        if n <= 0:
            shape.append(0)
        elif n < 3:
            shape.append(3)
        else:
            shape.append(n if n % 2 else n + 1)
    return tuple(shape)


def patch_counts(shape):
    nu, nv = int(shape[0]), int(shape[1])
    if nu == 0 or nv == 0:
        return 0, 0
    if nu < 3 or nv < 3 or nu % 2 == 0 or nv % 2 == 0:
        raise ValueError(f"a net needs odd sizes of at least three, not {(nu, nv)}")
    return (nu - 1) // 2, (nv - 1) // 2


def _interpolate_axis(samples, axis):
    """Solve one axis of the interpolating net: anchors are the samples,
    each handle is what makes its quadratic pass through the sample there:
    ``h = 2 s - (a0 + a1) / 2``."""
    samples = np.moveaxis(np.asarray(samples, dtype=float), axis, 0)
    net = samples.copy()
    net[1::2] = 2 * samples[1::2] - (samples[0:-2:2] + samples[2::2]) / 2
    return np.moveaxis(net, 0, axis)


def interpolating_net(samples):
    """The net whose patches pass through every sample of an odd-sized
    ``(nu, nv, channels)`` grid taken at the net's own parameter positions
    (each patch's anchors and midpoints). Exact by the tensor product: rows
    first, then columns."""
    samples = np.asarray(samples, dtype=float)
    if samples.ndim != 3:
        raise ValueError("samples must be (nu, nv, channels)")
    patch_counts(samples.shape[:2])
    if samples.shape[0] == 0 or samples.shape[1] == 0:
        return samples.copy()
    return _interpolate_axis(_interpolate_axis(samples, 0), 1)


def bernstein(t):
    """Quadratic Bernstein weights, shape ``(len(t), 3)``."""
    t = np.asarray(t, dtype=float)
    return np.stack([(1 - t) ** 2, 2 * t * (1 - t), t ** 2], axis=-1)


def bernstein_derivative(t):
    t = np.asarray(t, dtype=float)
    return np.stack([2 * t - 2, 2 - 4 * t, 2 * t], axis=-1)


def _patches(net):
    """View a net as ``(pu, pv, 3, 3, channels)`` patch blocks."""
    pu, pv = patch_counts(net.shape[:2])
    channels = net.shape[2]
    blocks = np.empty((pu, pv, 3, 3, channels))
    for a in range(3):
        for b in range(3):
            blocks[:, :, a, b] = net[a:a + 2 * pu:2, b:b + 2 * pv:2]
    return blocks


def _grid_parameters(patches, steps):
    """Per patch, the local parameters of an evaluated edge: ``steps + 1``
    values in ``[0, 1]``; the shared last row of one patch is the first of
    the next and is emitted once."""
    steps = int(steps)
    if steps < 1:
        raise ValueError("steps must be at least 1")
    return np.linspace(0, 1, steps + 1), steps


def evaluate(net, steps_u, steps_v, *, derivatives=False):
    """Evaluate a net on a uniform grid of ``steps`` per patch edge.

    Returns the grid ``(pu * steps_u + 1, pv * steps_v + 1, channels)``; with
    ``derivatives`` also the partial derivatives with respect to the local
    patch parameters, same shape, for normals.
    """
    net = np.asarray(net, dtype=float)
    pu, pv = patch_counts(net.shape[:2])
    channels = net.shape[2]
    if pu == 0:
        empty = np.zeros((0, 0, channels))
        return (empty, empty, empty) if derivatives else empty
    tu, su = _grid_parameters(pu, steps_u)
    tv, sv = _grid_parameters(pv, steps_v)
    blocks = _patches(net)
    bu, bv = bernstein(tu), bernstein(tv)

    def assemble(wu, wv):
        # (pu, su+1, pv, sv+1, channels): every patch's full grid, then drop
        # each patch's last row and column except the last patch's.
        full = np.einsum("ac,bd,ijcdk->iajbk", wu, wv, blocks)
        rows = np.concatenate([full[:, :-1].reshape(pu * su, pv, sv + 1, channels),
                               full[-1:, -1].reshape(1, pv, sv + 1, channels)], axis=0)
        return np.concatenate([rows[:, :, :-1].reshape(rows.shape[0], pv * sv, channels),
                               rows[:, -1:, -1].reshape(rows.shape[0], 1, channels)], axis=1)

    grid = assemble(bu, bv)
    if not derivatives:
        return grid
    return grid, assemble(bernstein_derivative(tu), bv), assemble(bu, bernstein_derivative(tv))


def evaluate_at(net, u, v):
    """Evaluate a net at global parameters in ``[0, 1]²`` (``u`` along the
    net's first axis), scalars or equal-shaped arrays."""
    net = np.asarray(net, dtype=float)
    pu, pv = patch_counts(net.shape[:2])
    u = np.clip(np.asarray(u, dtype=float), 0, 1)
    v = np.clip(np.asarray(v, dtype=float), 0, 1)
    su, sv = u * pu, v * pv
    i = np.minimum(su.astype(int), pu - 1)
    j = np.minimum(sv.astype(int), pv - 1)
    wu, wv = bernstein(su - i), bernstein(sv - j)
    result = np.zeros((*np.shape(u), net.shape[2]))
    for a in range(3):
        for b in range(3):
            result += (wu[..., a] * wv[..., b])[..., None] * net[2 * i + a, 2 * j + b]
    return result


def subdivide(net, axis, index, t=0.5):
    """Split the patches at ``index`` along ``axis`` at local parameter
    ``t`` by de Casteljau, in every row: two patches where there was one,
    evaluating to the same surface."""
    net = np.moveaxis(np.asarray(net, dtype=float), axis, 0)
    count = (net.shape[0] - 1) // 2
    if not 0 <= index < count:
        raise IndexError("no such patch")
    p0, p1, p2 = net[2 * index], net[2 * index + 1], net[2 * index + 2]
    q0 = (1 - t) * p0 + t * p1
    q1 = (1 - t) * p1 + t * p2
    mid = (1 - t) * q0 + t * q1
    result = np.concatenate([net[:2 * index + 1], [q0, mid, q1], net[2 * index + 2:]], axis=0)
    return np.moveaxis(result, 0, axis)


def align(first, second):
    """Subdivide the coarser net along each axis, splitting its largest
    patches (by control-point extent) in turn, until both nets have the
    same patch counts. Exact: neither surface changes."""
    first, second = np.asarray(first, dtype=float), np.asarray(second, dtype=float)
    for axis in (0, 1):
        while True:
            counts = [(net.shape[axis] - 1) // 2 for net in (first, second)]
            if counts[0] == counts[1]:
                break
            coarser = 0 if counts[0] < counts[1] else 1
            net = (first, second)[coarser]
            moved = np.moveaxis(net, axis, 0)
            extents = [np.abs(moved[2 * k + 2] - moved[2 * k]).sum() for k in range((moved.shape[0] - 1) // 2)]
            split = subdivide(net, axis, int(np.argmax(extents)))
            if coarser == 0:
                first = split
            else:
                second = split
    return first, second


def second_difference(net):
    """The largest second difference ``|p0 - 2 p1 + p2|`` over every row and
    column of every patch, in the net's units: what the step count at a
    zoom follows from (four times the chord deviation of the worst
    quadratic)."""
    net = np.asarray(net, dtype=float)
    pu, pv = patch_counts(net.shape[:2])
    if pu == 0:
        return 0.0
    along_u = net[0:-2:2] - 2 * net[1:-1:2] + net[2::2]
    along_v = net[:, 0:-2:2] - 2 * net[:, 1:-1:2] + net[:, 2::2]
    return max(float(np.linalg.norm(along_u, axis=-1).max()),
               float(np.linalg.norm(along_v, axis=-1).max()))


def steps_for(second_difference_pixels, *, tolerance=0.25, cap=32):
    """Steps per patch edge so the chord deviation stays under ``tolerance``
    pixels: the deviation of a quadratic over one step is a quarter of its
    second difference divided by ``steps²``."""
    if not np.isfinite(second_difference_pixels) or second_difference_pixels <= 0:
        return 1
    return int(min(cap, max(1, np.ceil(np.sqrt(second_difference_pixels / (4 * tolerance))))))


def arc_net(count, angle=2 * np.pi, radius=1.0):
    """Control points of ``count`` quadratic curves along an arc, the
    construction ``Arc`` uses: each curve's handle sits where the tangents
    at its ends meet. ``(2 * count + 1, 2)`` in the plane."""
    thetas = np.linspace(0, angle, count + 1)
    anchors = np.stack([np.cos(thetas), np.sin(thetas)], axis=1)
    half = angle / count / 2
    mids = (thetas[:-1] + thetas[1:]) / 2
    handles = np.stack([np.cos(mids), np.sin(mids)], axis=1) / np.cos(half)
    net = np.empty((2 * count + 1, 2))
    net[0::2], net[1::2] = anchors, handles
    return radius * net

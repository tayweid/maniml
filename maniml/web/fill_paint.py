"""A source-space paint field, independent of drawing-mesh connectivity.

Uniform and affine fields are exact. Other point colors use a thin-plate
spline with an affine term, evaluated per fragment rather than interpolated
across renderer-selected triangles. Coincident samples have their mean paint.
Ill-conditioned or larger data uses positive inverse-distance interpolation;
that bounded branch preserves samples and cannot overshoot their color range.
All output is clamped to the public RGBA range. These are explicit interior
paint semantics, replacing the old winding fan's diagonal-dependent seam.

The TPS system follows scipy.interpolate.RBFInterpolator's documented degree-1
form. Solving it here exposes a small coefficient buffer shared with WGSL;
no private SciPy representation or renderer-specific tessellation is involved.
"""

from dataclasses import dataclass, field

import numpy as np

from maniml.web.triangle_geometry import TessellationError, TessellationLimitError


MAX_PAINT_SAMPLES = 4096
MAX_SPLINE_SAMPLES = 256
PAINT_EPSILON = 1 / 4096
PAINT_HASH_PREFIX = b"maniml.paint.f32.v1\0"


@dataclass(frozen=True)
class PaintField:
    data: np.ndarray
    _flat: np.ndarray = field(init=False, repr=False, compare=False)

    def __post_init__(self):
        object.__setattr__(self, "_flat", self.data.reshape(-1))

    @property
    def nbytes(self):
        return self.data.nbytes

    def wire(self):
        """Keep the same immutable coefficient view through scene preparation."""
        return self._flat


def _kernel(squared_distance):
    return .5 * squared_distance * np.log(np.maximum(squared_distance, 1e-20))


def evaluate_paint(field, points):
    """CPU reference for the shared float32 shader field (not coverage)."""
    data = np.asarray(field.data, dtype="f4")
    points = np.asarray(points, dtype="f4")
    local = (points - data[0, :3]) / data[0, 3]
    xy = np.column_stack((local @ data[1, :3], local @ data[2, :3]))
    count, mode = int(data[1, 3]), int(data[2, 3])
    result = data[3] + xy[:, :1] * data[4] + xy[:, 1:] * data[5]
    if count:
        nodes, coefficients = data[6::2], data[7::2]
        # Chunking bounds temporary arrays even for a large source path.
        for start in range(0, len(xy), 256):
            q = xy[start:start + 256]
            distance = np.sum((q[:, None] - nodes[None, :, :2]) ** 2, axis=-1)
            if mode == 0:
                result[start:start + len(q)] += _kernel(distance) @ coefficients
            else:
                weights = 1 / np.maximum(distance, np.float32(1e-20))
                weights /= weights.sum(axis=1, keepdims=True)
                result[start:start + len(q)] = weights @ coefficients
    return np.clip(result, 0, 1)


def build_paint(points, rgba):
    """Freeze source paint into bounded, camera-independent shader coefficients."""
    points, rgba = np.asarray(points, dtype=float), np.asarray(rgba, dtype=float)
    if (points.ndim != 2 or points.shape[1:] != (3,) or rgba.shape != (len(points), 4)
            or not len(points) or not np.isfinite(points).all() or not np.isfinite(rgba).all()):
        raise TessellationError("fill paint requires finite matching XYZ and RGBA arrays")
    rgba = np.clip(rgba, 0, 1)
    origin = points.mean(axis=0)
    centered = points - origin
    scale = max(float(np.linalg.norm(centered, axis=1).max()), 1e-12)
    normalized = centered / scale
    basis = np.linalg.svd(normalized, full_matrices=False)[2][:2] if len(points) >= 3 else np.eye(3)[:2]
    xy = normalized @ basis.T
    # Source positions can coincide at closed endpoints or intersections with
    # conflicting paint. Average those values deterministically before fitting.
    unique, inverse = np.unique(xy.astype("f4"), axis=0, return_inverse=True)
    colors = np.zeros((len(unique), 4))
    np.add.at(colors, inverse, rgba)
    colors /= np.bincount(inverse)[:, None]
    base = np.zeros((6, 4), dtype="f4")
    base[0] = [*origin, scale]
    base[1, :3], base[2, :3] = basis
    polynomial = np.column_stack((np.ones(len(unique)), unique)).astype(float)
    affine = np.linalg.lstsq(polynomial, colors, rcond=1e-12)[0]
    if np.max(np.abs(polynomial @ affine - colors)) <= PAINT_EPSILON / 4:
        base[3:6] = affine
        return _frozen(base)
    if len(unique) > MAX_PAINT_SAMPLES:
        raise TessellationLimitError(f"non-affine fill paint exceeds {MAX_PAINT_SAMPLES} distinct samples")
    if len(unique) <= MAX_SPLINE_SAMPLES and np.linalg.matrix_rank(polynomial) == 3:
        delta = unique[:, None].astype(float) - unique[None, :]
        kernel = _kernel(np.sum(delta * delta, axis=-1))
        matrix = np.block([[kernel, polynomial], [polynomial.T, np.zeros((3, 3))]])
        try:
            coefficients = np.linalg.solve(matrix, np.vstack((colors, np.zeros((3, 4)))))
            candidate = np.zeros((6 + 2 * len(unique), 4), dtype="f4")
            candidate[:6] = base
            candidate[1, 3] = len(unique)
            candidate[3:6] = coefficients[-3:]
            candidate[6::2, :2] = unique
            candidate[7::2] = coefficients[:-3]
            # Reject a numerically fragile GPU representation, not the user's
            # path. Positive interpolation below handles those samples safely.
            world = unique @ basis * scale + origin
            if np.isfinite(candidate).all() and np.max(np.abs(evaluate_paint(PaintField(candidate), world) - colors)) <= PAINT_EPSILON:
                return _frozen(candidate)
        except np.linalg.LinAlgError:
            pass
    data = np.zeros((6 + 2 * len(unique), 4), dtype="f4")
    data[:6] = base
    data[1, 3], data[2, 3] = len(unique), 1
    data[6::2, :2], data[7::2] = unique, colors
    return _frozen(data)


def _frozen(data):
    data = np.asarray(data, dtype="f4")
    return PaintField(np.frombuffer(data.tobytes(), dtype="f4").reshape(-1, 4))

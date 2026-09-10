"""Restricted A0 quadratic interiors and analytic patches; never a fallback.

The ordinary mesh excludes every quadratic control triangle. Its boundary
follows an anchor chord for an outward curve and the two control edges for
an inward curve. A patch then selects one side of v-u*u, without signed alpha.
Overlapping control hulls are subdivided before triangulation. This is the
quadratic construction described by Loop and Blinn, GPU Gems 3, chapter 25:
https://developer.nvidia.com/gpugems/gpugems3/part-iv-image-effects/chapter-25-rendering-vector-art-gpu

Supported: separated simple planar contours with alternating nonzero winding,
holes, islands, and uniform paint supplied by the caller. Repeated, crossing,
touching, numerically ambiguous and excessively complex contours are rejected.
The float64 geometric checks are experimental, not exact predicates; GPU
float32 conversion, AA, clipping, paint and borders are separate A0 gates.
"""

from dataclasses import dataclass
from fractions import Fraction

import mapbox_earcut
import numpy as np


class UnsupportedAnalyticGeometry(ValueError):
    """The restricted candidate cannot establish single-owner coverage."""


PATCH_DTYPE = np.dtype([
    ("point", "<f4", (3,)), ("uv", "<f4", (2,)),
    ("rgba", "<f4", (4,)), ("fill_side", "<f4"),
])
PATCH_UV = np.array([[0., 0.], [.5, 0.], [1., 1.]])
_EPS = 1e-12  # Predicates run in normalized coordinates, not world units.


@dataclass
class AnalyticMesh:
    positions: np.ndarray  # float64 (N, 2), ordinary interior vertices
    indices: np.ndarray  # uint32 flat triangle indices
    patches: np.ndarray  # float64 (P, 3, 2), anchor/control/anchor
    sides: np.ndarray  # +1 accepts v-u*u >= 0; -1 accepts <= 0
    subdivision_rounds: int
    closure_displacement: float = 0.  # Max source-space movement of a closing endpoint.
    linearization_displacement: float = 0.  # Max curve-to-chord distance for numerical repairs.
    degenerate_triangles_removed: int = 0
    nonzero_sliver_triangles: int = 0

    def patch_vertices(self, *, origin, basis, rgba):
        """Pack patches into world xyz; no normal/lighting or gradient support.

        The shader must perspective-interpolate uv, keep fill_side flat, and
        evaluate coverage per sample when using MSAA. This does not implement
        an antialiasing fringe outside the control-triangle domain.
        """
        origin, basis, rgba = (np.asarray(x, dtype=float) for x in (origin, basis, rgba))
        if (origin.shape != (3,) or basis.shape != (2, 3) or rgba.shape != (4,)
                or not all(np.isfinite(x).all() for x in (origin, basis, rgba))):
            raise ValueError("expected finite origin (3), basis (2,3), uniform rgba (4)")
        vertices = np.zeros(len(self.patches) * 3, dtype=PATCH_DTYPE)
        world = self.patches.reshape(-1, 2) @ basis + origin
        if not np.isfinite(world).all() or np.max(np.abs(world), initial=0) > np.finfo("f4").max:
            raise UnsupportedAnalyticGeometry("patch coordinates exceed float32 range")
        vertices["point"] = world
        vertices["uv"] = np.tile(PATCH_UV, (len(self.patches), 1))
        vertices["rgba"] = rgba
        vertices["fill_side"] = np.repeat(self.sides, 3)
        return vertices


def _cross(a, b):
    return a[..., 0] * b[..., 1] - a[..., 1] * b[..., 0]


def _area(polygon):
    return float(_cross(polygon, np.roll(polygon, -1, axis=0)).sum() / 2)


def _orientation(a, b, c):
    """2D determinant with exact fallback for cancellation/zero decisions.

    Fraction operates on the supplied binary floats, not decimal approximations.
    This small predicate is used to distinguish zero-area triangles from real
    slivers; a nonzero sliver is never discarded because its area is small.
    """
    if np.array_equal(a, b) or np.array_equal(a, c) or np.array_equal(b, c):
        return 0.
    ab, ac = b-a, c-a
    left, right = ab[0]*ac[1], ab[1]*ac[0]
    value = float(left-right)
    error = 8*np.finfo(float).eps*(abs(left)+abs(right))
    if abs(value) > error:
        return value
    ax, ay, bx, by, cx, cy = (Fraction(float(v)) for p in (a, b, c) for v in p)
    exact = (bx-ax)*(cy-ay) - (by-ay)*(cx-ax)
    value = float(exact)
    if exact and not value:
        raise UnsupportedAnalyticGeometry("orientation is below float64 range")
    return value


def _curvature(curve):
    value = _orientation(*curve)
    if abs(value) <= _EPS:
        chord = curve[2]-curve[0]
        square_length = np.dot(chord, chord)
        projected = np.dot(curve[1]-curve[0], chord)
        if square_length == 0 or not 0 <= projected <= square_length:
            raise UnsupportedAnalyticGeometry("collinear curve reverses direction")
        # Only numerical near-collinearity is eligible. The caller must also
        # accept the separately measured curve-to-chord displacement below.
        return 0.
    return value


def _linearization_error(rings):
    maximum = 0.
    for ring in rings:
        for curve in ring:
            if _curvature(curve):
                continue
            determinant = abs(_orientation(*curve))
            if determinant:
                # The projected control lies on the anchor segment, so the
                # projected quadratic traces that whole chord monotonically.
                # 2*t*(1-t) <= 1/2 bounds curve-to-chord distance in both
                # directions. Inflate rounding in the scalar bound slightly.
                error = determinant/(2*np.linalg.norm(curve[2]-curve[0]))
                maximum = max(maximum, float(np.nextafter(error*(1+16*np.finfo(float).eps), np.inf)))
    return maximum


def _triangles_overlap(a, b):
    """Strict interior overlap; exact orientation fallback preserves slivers."""
    if np.any(a.max(axis=0) <= b.min(axis=0)) or np.any(b.max(axis=0) <= a.min(axis=0)):
        return False
    for triangle, other in ((a, b), (b, a)):
        side = np.sign(_orientation(*triangle))
        for start, end in zip(triangle, np.roll(triangle, -1, axis=0)):
            if all(side*_orientation(start, end, point) <= 0 for point in other):
                return False
    return True


def _segment_enters_triangle(a, b, triangle):
    """Clip a segment to the strict interior of a nondegenerate triangle."""
    if np.any(np.maximum(a, b) <= triangle.min(axis=0) + _EPS) or np.any(triangle.max(axis=0) <= np.minimum(a, b) + _EPS):
        return False
    orientation = np.sign(_cross(triangle[1] - triangle[0], triangle[2] - triangle[0]))
    low, high = 0., 1.
    for start, end in zip(triangle, np.roll(triangle, -1, axis=0)):
        edge = end - start
        initial = orientation * _cross(edge, a - start)
        slope = orientation * _cross(edge, b - a)
        threshold = _EPS * np.linalg.norm(edge)
        if slope == 0:
            if initial <= threshold:
                return False
        elif slope > 0:
            low = max(low, (threshold - initial) / slope)
        else:
            high = min(high, (threshold - initial) / slope)
    return low < high and high > 0 and low < 1


def _segments_touch(a, b, c, d):
    if np.any(np.maximum(a, b) < np.minimum(c, d) - _EPS) or np.any(np.maximum(c, d) < np.minimum(a, b) - _EPS):
        return False
    values = (_cross(b-a, c-a), _cross(b-a, d-a), _cross(d-c, a-c), _cross(d-c, b-c))
    return (min(values[:2]) <= _EPS and max(values[:2]) >= -_EPS
            and min(values[2:]) <= _EPS and max(values[2:]) >= -_EPS)


def _point_on_segment(point, a, b):
    return (abs(_cross(b-a, point-a)) <= _EPS * max(np.linalg.norm(b-a), _EPS)
            and np.dot(point-a, point-b) <= _EPS**2)


def _validate_rings(rings):
    """Establish Earcut's simple, separated polygon preconditions."""
    edges = [(r, i, p[i], p[(i + 1) % len(p)]) for r, p in enumerate(rings) for i in range(len(p))]
    for r, polygon in enumerate(rings):
        if len(polygon) < 3 or abs(_area(polygon)) <= _EPS:
            raise UnsupportedAnalyticGeometry("degenerate contour")
        for i in range(len(polygon)):
            a, b, c = polygon[i-1], polygon[i], polygon[(i+1) % len(polygon)]
            if np.linalg.norm(b-a) <= _EPS:
                raise UnsupportedAnalyticGeometry("repeated or near-coincident anchors")
            if abs(_cross(b-a, c-b)) <= _EPS and np.dot(b-a, c-b) < 0:
                raise UnsupportedAnalyticGeometry("adjacent boundary edges reverse or overlap")
    for index, (r, i, a, b) in enumerate(edges):
        for s, j, c, d in edges[index+1:]:
            if r == s and (abs(i-j) == 1 or abs(i-j) == len(rings[r])-1):
                continue
            if _segments_touch(a, b, c, d):
                raise UnsupportedAnalyticGeometry("crossing, touching or ambiguous contour boundaries")


def _inside(point, polygon):
    a, b = polygon, np.roll(polygon, -1, axis=0)
    active = (a[:, 1] > point[1]) != (b[:, 1] > point[1])
    a, b = a[active], b[active]
    x = a[:, 0] + (point[1] - a[:, 1]) * (b[:, 0] - a[:, 0]) / (b[:, 1] - a[:, 1])
    return bool(np.count_nonzero(x > point[0]) % 2)


def _subdivide(curve):
    left = (curve[0] + curve[1]) / 2
    right = (curve[1] + curve[2]) / 2
    middle = (left + right) / 2
    return np.array([curve[0], left, middle]), np.array([middle, right, curve[2]])


def _separate_hulls(rings, max_segments, max_subdivisions):
    """Subdivide geometric conflicts, without introducing a screen tolerance."""
    for iteration in range(max_subdivisions + 1):
        curves = [(r, i, c) for r, ring in enumerate(rings) for i, c in enumerate(ring)]
        curved = [(r, i, c) for r, i, c in curves if _curvature(c)]
        conflicts = set()
        for index, (r, i, c) in enumerate(curved):
            for s, j, d in curved[index+1:]:
                control_contact = any(_point_on_segment(c[1], a, b)
                                      for a, b in zip(d, np.roll(d, -1, axis=0)))
                control_contact |= any(_point_on_segment(d[1], a, b)
                                       for a, b in zip(c, np.roll(c, -1, axis=0)))
                if _triangles_overlap(c, d) or control_contact:
                    conflicts.update(((r, i), (s, j)))
            for s, j, d in curves:
                if (r, i) != (s, j) and (_segment_enters_triangle(d[0], d[2], c)
                                       or _point_on_segment(c[1], d[0], d[2])):
                    conflicts.add((r, i))
                    if _curvature(d):
                        conflicts.add((s, j))
        if not conflicts:
            return rings, iteration
        if iteration == max_subdivisions or len(curves) + len(conflicts) > max_segments:
            raise UnsupportedAnalyticGeometry("control hulls overlap beyond the subdivision budget")
        rings = [[piece for i, c in enumerate(ring)
                  for piece in (_subdivide(c) if (r, i) in conflicts else (c,))]
                 for r, ring in enumerate(rings)]
    raise AssertionError("unreachable")


def build_analytic_mesh(contours, *, max_segments=2048, max_subdivisions=8,
                        max_linearization_error=0.):
    """Decompose Manim-style (2*n+1,2) quadratic contours, implicitly closing.

    Supports nonzero fill only when every nested boundary changes filledness.
    Same-direction nested/repeated contours are explicit unsupported cases.
    Returns float64 geometry; no screen-dependent curve flattening occurs.
    A closing endpoint within 1e-12 of the total source extent is welded to its
    existing first anchor. The maximum displacement is reported on the result
    and must be charged against the caller's projected geometric-error budget.
    Nearly collinear segments can become straight only within the explicit
    source-space max_linearization_error allowance (default zero). Their
    measured Hausdorff bound is reported separately. This is numerical repair
    at the fixed determinant threshold, not general screen-dependent flattening.
    """
    if (isinstance(max_segments, bool) or not isinstance(max_segments, int) or not 3 <= max_segments <= 8192
            or isinstance(max_subdivisions, bool) or not isinstance(max_subdivisions, int)
            or not 0 <= max_subdivisions <= 16):
        raise ValueError("invalid analytic subdivision limits")
    if (isinstance(max_linearization_error, bool)
            or not np.isfinite(max_linearization_error) or max_linearization_error < 0):
        raise ValueError("max_linearization_error must be finite and nonnegative")
    inputs = []
    for contour in contours:
        p = np.asarray(contour)
        if (p.ndim != 2 or p.shape[1] != 2 or len(p) % 2 != 1
                or p.dtype.kind not in "fiu" or not np.isfinite(p).all()):
            raise ValueError("expected finite real (2*n+1,2) quadratic contours")
        if len(p) >= 3:
            inputs.append(p.astype(float, copy=True))
    empty = lambda: AnalyticMesh(np.empty((0, 2)), np.empty(0, dtype="u4"),
                                 np.empty((0, 3, 2)), np.empty(0, dtype="i4"), 0)
    if not inputs:
        return empty()
    all_points = np.concatenate(inputs)
    origin = all_points.min(axis=0)
    extent = float(np.ptp(all_points, axis=0).max())
    if extent == 0:
        return empty()
    if not np.isfinite(extent):
        raise UnsupportedAnalyticGeometry("source extent exceeds float64 range")
    rings = []
    closure_displacement = 0.
    for source in inputs:
        p = (source - origin) / extent
        closing_distance = float(np.linalg.norm(p[-1] - p[0]))
        if 0 < closing_distance <= _EPS:
            closure_displacement = max(closure_displacement, float(np.linalg.norm(source[-1] - source[0])))
            p[-1] = p[0]
        ring = [p[i:i+3] for i in range(0, len(p)-2, 2)]
        if not np.array_equal(p[0], p[-1]):
            ring.append(np.array([p[-1], (p[-1]+p[0])/2, p[0]]))
        # Exact zero-length commands occur in normal path construction.
        ring = [c for c in ring if not np.array_equal(c, np.tile(c[0], (3, 1)))]
        if ring:
            # A valid lens may contain just two quadratic segments. Its anchor
            # polygon has no area until one curve is split, with exact de Casteljau.
            if len(ring) == 2 and any(_curvature(c) for c in ring):
                target = max(range(2), key=lambda i: abs(_curvature(ring[i])))
                ring[target:target+1] = _subdivide(ring[target])
            rings.append(ring)
    if not rings:
        return empty()
    if sum(map(len, rings)) > max_segments:
        raise UnsupportedAnalyticGeometry("source exceeds analytic segment budget")
    linearization = _linearization_error(rings)
    if linearization*extent > max_linearization_error:
        raise UnsupportedAnalyticGeometry("near-collinear approximation exceeds the geometry error budget")
    rings, rounds = _separate_hulls(rings, max_segments, max_subdivisions)
    linearization = max(linearization, _linearization_error(rings))
    if linearization*extent > max_linearization_error:
        raise UnsupportedAnalyticGeometry("near-collinear approximation exceeds the geometry error budget")
    anchor_rings = [np.array([c[0] for c in ring]) for ring in rings]
    _validate_rings(anchor_rings)
    areas = np.array([_area(p) for p in anchor_rings])
    parents = []
    for i, polygon in enumerate(anchor_rings):
        containers = [j for j, other in enumerate(anchor_rings) if j != i and _inside(polygon[0], other)]
        parents.append(min(containers, key=lambda j: abs(areas[j])) if containers else None)
    depths = []
    for i in range(len(rings)):
        depth, parent = 0, parents[i]
        while parent is not None:
            depth += 1
            if depth > len(rings):
                raise UnsupportedAnalyticGeometry("ambiguous contour containment")
            parent = parents[parent]
        depths.append(depth)
        if parents[i] is not None and np.sign(areas[i]) == np.sign(areas[parents[i]]):
            raise UnsupportedAnalyticGeometry("same-direction nested nonzero contours are unsupported")
    polygons, patches, sides = [], [], []
    for r, ring in enumerate(rings):
        filled_side = np.sign(areas[r]) * (-1 if depths[r] % 2 else 1)
        polygon = []
        for curve in ring:
            polygon.append(curve[0])
            curvature = _curvature(curve)
            if curvature:
                side = int(np.sign(curvature) * filled_side)
                patches.append(curve)
                sides.append(side)
                if side < 0:
                    polygon.append(curve[1])
        polygons.append(np.array(polygon))
    _validate_rings(polygons)
    patches_array = np.array(patches).reshape(-1, 3, 2)
    positions, indices, offset = [], [], 0
    degenerate_count, sliver_count = 0, 0
    for outer in range(len(polygons)):
        if depths[outer] % 2:
            continue
        group = [polygons[outer], *(polygons[i] for i in range(len(polygons)) if parents[i] == outer)]
        vertices = np.concatenate(group)
        ends = np.cumsum([len(p) for p in group], dtype="u4")
        triangles = np.asarray(mapbox_earcut.triangulate_float64(vertices, ends), dtype="u4")
        if triangles.size % 3 or (triangles.size and int(triangles.max()) >= len(vertices)):
            raise UnsupportedAnalyticGeometry("invalid Earcut output")
        tri = vertices[triangles.reshape(-1, 3)]
        determinants = np.array([_orientation(*triangle) for triangle in tri])
        degenerate_count += int(np.count_nonzero(determinants == 0))
        sliver_count += int(np.count_nonzero((abs(determinants) <= _EPS) & (determinants != 0)))
        nonzero = determinants != 0
        triangles = triangles.reshape(-1, 3)[nonzero].reshape(-1)
        tri = tri[nonzero]
        actual = np.abs(_cross(tri[:, 1]-tri[:, 0], tri[:, 2]-tri[:, 0])).sum() / 2
        expected = abs(_area(group[0])) - sum(abs(_area(p)) for p in group[1:])
        if not np.isclose(actual, expected, atol=1e-10, rtol=1e-10):
            raise UnsupportedAnalyticGeometry("Earcut coverage area mismatch")
        for triangle in tri:
            if any(_triangles_overlap(triangle, patch) for patch in patches_array):
                raise UnsupportedAnalyticGeometry("interior mesh overlaps an analytic patch")
        positions.append(vertices)
        indices.append(triangles + offset)
        offset += len(vertices)
    return AnalyticMesh(np.concatenate(positions) * extent + origin,
                        np.concatenate(indices).astype("u4"),
                        patches_array * extent + origin, np.asarray(sides, dtype="i4"), rounds,
                        closure_displacement, linearization*extent,
                        degenerate_count, sliver_count)

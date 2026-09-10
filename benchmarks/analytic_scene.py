"""A0 analytic fills in the shared ordered scene loop; no production imports.

This candidate keeps the current stroke/surface/dot paths. Analytic fills have
uniform unlit paint and no implemented fill border; diagnostic mode can record
an omitted border, but never substitutes a color for a gradient or lighting.

Acceptance depends on the exact source, coordinate conversion and numerical
policy: a direct world-XY probe does not exercise this module's SVD plane fit.
Use report source/code digests and identify the entry point when quoting glyph
counts. Numerically near-collinear curves may be replaced only by bounded
chords; nonzero Earcut slivers are retained. Other unsupported geometry still
rejects the entire frame, never authorizes omission of a glyph.
"""

from dataclasses import dataclass
import weakref

import numpy as np

from benchmarks.analytic_geometry import (
    PATCH_DTYPE, PATCH_UV, UnsupportedAnalyticGeometry, build_analytic_mesh,
)
from benchmarks.triangle_scene import (
    TriangleDraw, TriangleMeshCache, UnsupportedPrototype,
    _MeshEntry, _MeshSource, _readonly, planar_coordinates,
    planar_projection_error, prepare_triangle_frame, projection_scale_bound,
)


@dataclass
class _AnalyticGeometry:
    vertices: np.ndarray
    fitted_points: np.ndarray
    basis: np.ndarray
    closure_displacement: float
    rounding_displacement: float
    linearization_displacement: float

    def arrays(self):
        return (self.vertices, self.fitted_points, self.basis)

    def frozen(self):
        return _AnalyticGeometry(*(_readonly(array) for array in self.arrays()),
                                 self.closure_displacement, self.rounding_displacement,
                                 self.linearization_displacement)

    def pixel_error(self, source, uniforms, resolution):
        if not len(self.vertices):
            return 0.
        residual = planar_projection_error(source.points, self.fitted_points, uniforms, resolution)
        closure_scale = projection_scale_bound(self.fitted_points, self.basis, uniforms, resolution)
        # Rounded points can lie just outside the source control hull. Include
        # both sets when bounding the projection derivative for that movement.
        rounding_hull = np.concatenate((self.fitted_points, self.vertices["point"].astype(float)))
        rounding_scale = projection_scale_bound(rounding_hull, np.eye(3), uniforms, resolution)
        return (residual + closure_scale * (self.closure_displacement+self.linearization_displacement)
                + rounding_scale * self.rounding_displacement)


def _generate_analytic(source, uniforms, resolution, pixel_tolerance):
    points = source.points
    empty = _AnalyticGeometry(np.empty(0, dtype=PATCH_DTYPE), np.empty((0, 3)),
                              np.empty((0, 3)), 0., 0., 0.)
    if len(points) < 3:
        return empty
    starts = [0, *(source.ends[:-1] + 2)]
    ranges = [slice(int(start), int(end) + 1) for start, end in zip(starts, source.ends)
              if end - start >= 2]
    if not ranges:
        return empty
    xy, origin, basis, _ = planar_coordinates(points)
    fitted_points = xy @ basis + origin
    # Validate projection before the potentially expensive geometric checks.
    residual = planar_projection_error(points, fitted_points, uniforms, resolution)
    if not np.isfinite(residual) or residual >= pixel_tolerance:
        raise UnsupportedPrototype("analytic plane-fitting residual exceeds the pixel error budget")
    scale = projection_scale_bound(fitted_points, basis, uniforms, resolution)
    numerical_budget = (pixel_tolerance-residual)/(4*max(scale, 1e-12))
    try:
        mesh = build_analytic_mesh([xy[part] for part in ranges],
                                   max_linearization_error=numerical_budget)
    except UnsupportedAnalyticGeometry as error:
        raise UnsupportedPrototype(f"analytic geometry: {error}") from error
    interior = mesh.positions[mesh.indices]
    local = np.concatenate((interior, mesh.patches.reshape(-1, 2)))
    world = local @ basis + origin
    if not np.isfinite(world).all() or np.max(abs(world), initial=0) > np.finfo("f4").max:
        raise UnsupportedPrototype("analytic coordinates exceed float32 range")
    vertices = np.zeros(len(local), dtype=PATCH_DTYPE)
    vertices["point"] = world
    vertices["rgba"] = source.rgba[0]
    boundary = vertices[len(interior):]
    boundary["uv"] = np.tile(PATCH_UV, (len(mesh.patches), 1))
    boundary["fill_side"] = np.repeat(mesh.sides, 3)
    rounding = float(np.linalg.norm(vertices["point"].astype(float)-world, axis=1).max(initial=0))
    geometry = _AnalyticGeometry(vertices, fitted_points, basis,
                                 mesh.closure_displacement, rounding,
                                 mesh.linearization_displacement)
    if geometry.pixel_error(source, uniforms, resolution) > pixel_tolerance:
        raise UnsupportedPrototype("analytic closure/plane-fitting/linearization/float32 displacement exceeds the pixel error budget")
    return geometry


class _GeneratorIdentity:
    """Fixed source-space settings for the shared cache lifecycle machinery."""
    cache_key = "analytic-a0-separated-quadratics-v2-bounded-numerics"
    tessellate = staticmethod(build_analytic_mesh)


_GENERATOR = _GeneratorIdentity()


class AnalyticMeshCache(TriangleMeshCache):
    """Optional bounded analytic geometry cache, using the A0 mesh lifecycle.

    Exact source/contour/paint/normal comparison prevents stale in-place array
    edits. Camera-only reuse checks the current projection bound for plane
    fitting, reported endpoint closure/linearization movement, and float32
    vertex rounding.
    It does not rebuild curves for camera zoom. A camera requiring more quality
    than this representation can provide raises an explicit unsupported error.
    Bounds cover retained source/geometry NumPy bytes and entry count, not
    temporary generation storage, old frames, Python metadata bytes or GPU RAM.
    """

    def __init__(self, *, max_bytes=64 << 20, max_entries=2048):
        super().__init__(max_bytes=max_bytes, max_entries=max_entries, refinement_factor=1.)

    def mesh(self, mobject, uniforms, resolution, pixel_tolerance):
        source = _MeshSource.read(mobject)
        owner_id = id(mobject)
        entry = self._entries.get(owner_id)
        if entry is not None:
            try:
                valid = (entry.owner() is mobject and entry.source.matches(source)
                         and entry.geometry.pixel_error(source, uniforms, resolution) <= pixel_tolerance)
            except Exception:
                self._remove(owner_id)
                raise
            if valid:
                self._totals["hits"] += 1
                entry.last_frame = self._frame
                self._entries.move_to_end(owner_id)
                return entry.geometry.vertices
            self._remove(owner_id)
        geometry = _generate_analytic(source, uniforms, resolution, pixel_tolerance)
        self._totals["regenerations"] += 1
        nbytes = sum(a.nbytes for a in (*source.arrays(), *geometry.arrays()))
        if self.max_entries and nbytes <= self.max_bytes:
            while (len(self._entries) >= self.max_entries or self._bytes + nbytes > self.max_bytes):
                self._remove(next(iter(self._entries)))
            entry = _MeshEntry(weakref.ref(mobject), source.frozen(), geometry.frozen(), self._frame)
            self._entries[owner_id] = entry
            self._bytes += entry.nbytes
            geometry = entry.geometry
        return geometry.vertices


def prepare_analytic_frame(scene, *, diagnostic=False, pixel_tolerance=.25, cache=None):
    """Prepare one shared-loop frame with single-owner analytic fill draws."""
    if not np.isfinite(pixel_tolerance) or pixel_tolerance <= 0:
        raise ValueError("pixel_tolerance must be finite and positive")
    if cache is not None and not isinstance(cache, AnalyticMeshCache):
        raise TypeError("cache must be AnalyticMeshCache")
    before = cache.begin_frame(_GENERATOR) if cache is not None else None

    def fill_builder(mobject, uniforms, resolution, budget):
        rgba = mobject.data["fill_rgba"]
        if not np.isfinite(rgba).all():
            raise UnsupportedPrototype("analytic fills require finite paint")
        if not np.all(rgba == rgba[0]):
            raise UnsupportedPrototype("analytic fills require uniform paint, including in diagnostic mode")
        if np.any(uniforms.get("shading", (0, 0, 0))):
            raise UnsupportedPrototype("analytic fills require unlit paint, including in diagnostic mode")
        if cache is None:
            vertices = _generate_analytic(_MeshSource.read(mobject), uniforms, resolution, budget).vertices
        else:
            vertices = cache.mesh(mobject, uniforms, resolution, budget)
        if not len(vertices):
            return None
        suffix = "_depth" if mobject.depth_test else ""
        return TriangleDraw("analytic" + suffix, vertices, uniforms, count=len(vertices))

    try:
        frame = prepare_triangle_frame(scene, None, pixel_tolerance=pixel_tolerance,
                                       diagnostic=diagnostic, fill_builder=fill_builder)
    except Exception:
        # A partially prepared failed frame must not leave stale retained fills.
        if cache is not None:
            cache.clear()
        raise
    if cache is not None:
        frame.mesh_cache_stats = cache.finish_frame(before)
    return frame

"""CPU generation for the opt-in shared triangle renderer.

The default rejects unsupported appearance instead of silently dropping it.
The diagnostic benchmark can opt in to incomplete pictures, with every known
omission recorded on the frame. That mode is never a renderer fallback.
"""

from collections import OrderedDict
from dataclasses import dataclass, field, replace
import weakref

import numpy as np

from maniml.camera.camera_frame import CameraFrame
from maniml.mobject.types.dot_cloud import DotCloud
from maniml.mobject.types.image_mobject import ImageMobject
from maniml.mobject.types.surface import Surface, TexturedSurface
from maniml.mobject.types.vectorized_mobject import VMobject
from maniml.web.geometry import SURFACE_DTYPE, _jsonable, _stroke_verts, _texture_refs
from maniml.web.triangle_geometry import TessellationError


class UnsupportedPrototype(TessellationError):
    """The selected triangle path cannot promise the requested appearance.

    The historical exception name remains compatible with benchmark callers.
    """


@dataclass
class TriangleDraw:
    pipeline: str
    vertices: np.ndarray
    uniforms: dict
    indices: np.ndarray | None = None
    count: int = 0
    instances: int = 1
    textures: dict = field(default_factory=dict)


def coalesce_draws(draws):
    """Join consecutive compatible draws without changing primitive order.

    Full normalized uniforms, vertex layout and depth pipeline must agree.
    Indexed fills keep every triangle in source order; strokes keep every
    curve instance in source order. The stroke shader clamps extra strip
    vertices to a degenerate tail, so a run can use its largest strip count.
    Unknown pipelines and partial draw ranges remain separate. Runs allocate
    frame-owned arrays; a single draw retains its original array identities.
    """
    def kind(draw):
        if draw.pipeline in ("surface", "surface_depth") and draw.instances == 1:
            if (draw.indices is not None and draw.count == len(draw.indices)
                    and draw.count % 3 == 0):
                return "indexed"
            if (draw.indices is None and draw.count == len(draw.vertices)
                    and draw.count % 3 == 0):
                return "triangles"
        if (draw.pipeline in ("stroke", "stroke_depth") and draw.indices is None
                and len(draw.vertices) == 3 * draw.instances
                and draw.count >= 4 and draw.count % 2 == 0):
            return "stroke"
        return None

    def combine(run, run_kind):
        if len(run) == 1:
            return run[0]
        first = run[0]
        vertices = np.concatenate([draw.vertices for draw in run])
        if run_kind == "indexed":
            # Draw indices are uint32 in the shared surface pipeline.
            offsets = np.cumsum([0, *(len(draw.vertices) for draw in run[:-1])], dtype="u8")
            indices = np.concatenate([draw.indices + np.uint32(offset)
                                      for draw, offset in zip(run, offsets)])
            return replace(first, vertices=vertices, indices=indices,
                           count=sum(draw.count for draw in run))
        return replace(first, vertices=vertices,
                       count=max(draw.count for draw in run) if run_kind == "stroke"
                       else sum(draw.count for draw in run),
                       instances=sum(draw.instances for draw in run) if run_kind == "stroke" else 1)

    result, run, run_kind, vertex_count = [], [], None, 0
    for draw in draws:
        draw_kind = kind(draw)
        compatible = (run and run_kind is not None and draw_kind == run_kind
                      and draw.pipeline == run[0].pipeline
                      and draw.vertices.dtype == run[0].vertices.dtype
                      and draw.uniforms == run[0].uniforms
                      and draw.textures == run[0].textures
                      and (draw_kind != "indexed" or
                           (draw.indices.dtype == np.dtype("u4")
                            and run[0].indices.dtype == np.dtype("u4")
                            and vertex_count + len(draw.vertices) <= 2 ** 32)))
        if run and not compatible:
            result.append(combine(run, run_kind))
            run, vertex_count = [], 0
        run.append(draw)
        run_kind = draw_kind
        vertex_count += len(draw.vertices)
    if run:
        result.append(combine(run, run_kind))
    return result


@dataclass
class TriangleFrame:
    resolution: tuple[int, int]
    background: tuple[float, ...]
    samples: int
    draws: list[TriangleDraw] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    source_bytes: int = 0
    pixel_tolerance: float = 0.25
    mesh_cache_stats: dict = field(default_factory=dict)

    @property
    def geometry_bytes(self):
        return sum(draw.vertices.nbytes + (0 if draw.indices is None else
                                          draw.indices.nbytes)
                   for draw in self.draws)


def _readonly(array):
    """Own immutable backing bytes: callers cannot re-enable array writes."""
    array = np.ascontiguousarray(array)
    return np.frombuffer(array.tobytes(), dtype=array.dtype).reshape(array.shape)


@dataclass
class _MeshSource:
    points: np.ndarray
    ends: np.ndarray
    rgba: np.ndarray
    normal: np.ndarray
    border_settings: tuple = (0.0, "bevel")

    @classmethod
    def read(cls, mobject, border_settings=(0.0, "bevel")):
        points = np.asarray(mobject.get_points(), dtype=float)
        ends = (mobject.get_subpath_end_indices_from_points(points) if len(points)
                else np.empty(0, dtype=int))
        return cls(points, np.asarray(ends), mobject.data["fill_rgba"],
                   np.asarray(mobject.get_unit_normal()), border_settings)

    def arrays(self):
        return (self.points, self.ends, self.rgba, self.normal)

    def matches(self, other):
        # Read actual content, not object identity/revision alone: public arrays
        # can be modified in place without a revision bump. No hash collision can
        # accidentally validate a stale mesh. This remains O(source bytes).
        return (self.border_settings == other.border_settings and
                all(np.array_equal(a, b) for a, b in zip(self.arrays(), other.arrays())))

    def geometry_matches(self, other):
        return (self.border_settings == other.border_settings and
                all(np.array_equal(getattr(self, name), getattr(other, name))
                    for name in ("points", "ends", "normal")))

    def frozen(self):
        return _MeshSource(*(_readonly(array) for array in self.arrays()), self.border_settings)


@dataclass
class _MeshGeometry:
    vertices: np.ndarray
    indices: np.ndarray
    fitted_points: np.ndarray
    basis: np.ndarray
    local_tolerance: float
    fit_residual: float = 0.0

    def arrays(self):
        return (self.vertices, self.indices, self.fitted_points, self.basis)

    def frozen(self):
        return _MeshGeometry(*(_readonly(array) for array in self.arrays()),
                             self.local_tolerance, self.fit_residual)

    def pixel_error(self, source, uniforms, resolution, *, projection=None):
        if not self.local_tolerance:  # No eligible filled contour.
            return 0.0
        residual = planar_projection_error(source.points, self.fitted_points,
                                           uniforms, resolution, _projection=projection,
                                           _residual=self.fit_residual)
        scale = projection_scale_bound(_border_hull(self.fitted_points, self.basis,
                                                   source.border_settings), self.basis,
                                       uniforms, resolution, _projection=projection)
        return residual + self.local_tolerance * scale


@dataclass
class _MeshEntry:
    owner: weakref.ReferenceType
    source: _MeshSource
    geometry: _MeshGeometry
    last_frame: int
    projection_key: tuple | None = None
    projected_error: float | None = None

    @property
    def nbytes(self):
        return sum(array.nbytes for array in (*self.source.arrays(),
                                             *self.geometry.arrays()))

    def pixel_error(self, source, uniforms, resolution, *, projection_cache=None):
        """Memoize only this immutable mesh's most recent camera error bound.

        The caller must first establish exact source identity. Key the actual
        projection inputs at the float32 precision consumed by the shader,
        including fixed-frame interpolation and output size. A changed quality
        request still compares against the stored numeric error; it is never
        treated as automatic permission to reuse. Unrelated lighting/AA changes
        do not invalidate the geometric projection bound.
        """
        view = np.asarray(uniforms["view"], dtype="f4").reshape(16)
        scale = np.asarray(uniforms["frame_rescale_factors"], dtype="f4").reshape(3)
        fixed = np.float32(uniforms.get("is_fixed_in_frame", 0))
        key = (view.tobytes(), scale.tobytes(), fixed.tobytes(), tuple(resolution))
        if key != self.projection_key:
            # Validate before computing even an empty mesh's bound. Do not
            # publish a failed/NaN camera key that a later call could reuse.
            if (not np.isfinite(view).all() or not np.isfinite(scale).all()
                    or not 0 <= fixed <= 1 or not np.isfinite(resolution).all()):
                raise UnsupportedPrototype("nonfinite or unsupported camera transform")
            if projection_cache is None:
                error = self.geometry.pixel_error(source, uniforms, resolution)
            else:
                if key not in projection_cache:
                    projection_cache[key] = projection_matrix(uniforms)
                error = self.geometry.pixel_error(source, uniforms, resolution,
                                                 projection=projection_cache[key])
            if not np.isfinite(error):
                raise UnsupportedPrototype("unbounded projection error")
            self.projection_key, self.projected_error = key, error
        return self.projected_error


class TriangleMeshCache:
    """Retained fill meshes, bounded by array bytes and entry count.

    Reuse requires exact source/contour/normal content, effective border width
    and mapped join style, and the same
    tessellator instance. A configurable generator must additionally expose an
    immutable ``cache_key`` value and change it when output-affecting settings
    change. The last projected error is memoized by exact projection inputs;
    Uniform paint changes refresh vertex colors without regenerating geometry.
    Diagnostic nonuniform paint still regenerates until its interpolation has a
    separate representation. Both paths inspect actual paint bytes each frame;
    color refresh still copies/uploads the interleaved vertices. Changed camera
    dependencies recompute the bound without altering source
    identity. With ``refinement_factor=0.5``, a rebuild
    spends half the remaining geometric budget, giving headroom for zooming in.
    Zooming out retains the finer mesh rather than producing repeated coarse
    versions. The projection bound includes the expanded border hull. The
    tolerance controls plane fitting plus curve flattening; it does not prove
    arbitrary stroked-cusp/miter accuracy, float32 arithmetic or antialiasing,
    and does not bound total CPU time or tessellator scratch allocations.

    The byte limit counts all retained NumPy payloads (source snapshots, plane
    metadata, vertices, indices); ``max_entries`` also bounds Python metadata.
    Oversized results can be drawn but are not retained. This is not a peak
    process/GPU-memory bound: returned frames may keep their own references and
    generation/copying has temporary allocations. Completed frames discard
    entries for absent fills. ``clear`` releases retained state explicitly.
    Cached output is immutable; preparation without a cache stays mutable.
    """

    def __init__(self, *, max_bytes=64 << 20, max_entries=2048,
                 refinement_factor=0.5):
        for name, value in (("max_bytes", max_bytes), ("max_entries", max_entries)):
            if isinstance(value, bool) or not isinstance(value, (int, np.integer)) or value < 0:
                raise ValueError(f"{name} must be a nonnegative integer")
        if not np.isfinite(refinement_factor) or not 0 < refinement_factor <= 1:
            raise ValueError("refinement_factor must be finite and in (0, 1]")
        self.max_bytes = int(max_bytes)
        self.max_entries = int(max_entries)
        self.refinement_factor = float(refinement_factor)
        self._entries = OrderedDict()
        self._bytes = 0
        self._frame = 0
        self._generator = None
        self._generator_key = None
        self._projections = {}
        self._totals = {"hits": 0, "regenerations": 0, "evictions": 0, "paint_updates": 0}

    @property
    def stats(self):
        return {**self._totals, "retained_bytes": self._bytes,
                "entries": len(self._entries)}

    def _remove(self, key):
        self._bytes -= self._entries.pop(key).nbytes
        self._totals["evictions"] += 1

    def clear(self):
        for key in list(self._entries):
            self._remove(key)
        self._generator = None
        self._generator_key = None
        self._projections.clear()

    def begin_frame(self, tessellator):
        before = self.stats
        # Instance identity also prevents two different loaded libraries that
        # report the same ABI/version from sharing a cached result.
        key = (getattr(tessellator, "cache_key", None),
               getattr(tessellator, "library_path", None),
               getattr(tessellator.tessellate, "__func__", tessellator.tessellate))
        if (self._generator is None or self._generator() is not tessellator
                or self._generator_key != key):
            self.clear()
            self._generator = weakref.ref(tessellator)
            self._generator_key = key
        self._frame += 1
        self._projections.clear()
        for owner_id, entry in list(self._entries.items()):
            if entry.owner() is None:
                self._remove(owner_id)
        return before

    def finish_frame(self, before):
        for owner_id, entry in list(self._entries.items()):
            if entry.last_frame != self._frame:
                self._remove(owner_id)
        now = self.stats
        # Camera matrix sharing is preparation scratch, not retained mesh data.
        self._projections.clear()
        return {**now, **{key: now[key] - before[key] for key in self._totals}}

    def mesh(self, mobject, tessellator, uniforms, resolution, pixel_tolerance,
             *, border_settings=(0.0, "bevel")):
        source = _MeshSource.read(mobject, border_settings)
        owner_id = id(mobject)
        entry = self._entries.get(owner_id)
        if entry is not None:
            same_paint = np.array_equal(entry.source.rgba, source.rgba)
            uniform_refresh = (len(source.rgba) > 0 and len(entry.source.rgba) > 0
                               and np.isfinite(source.rgba).all()
                               and np.all(source.rgba == source.rgba[0])
                               and np.all(entry.source.rgba == entry.source.rgba[0])) if not same_paint else False
            if (entry.owner() is mobject and entry.source.geometry_matches(source)
                    and (same_paint or uniform_refresh)
                    and entry.pixel_error(source, uniforms, resolution,
                                          projection_cache=self._projections)
                    <= pixel_tolerance):
                if not same_paint:
                    vertices = entry.geometry.vertices.copy()
                    vertices["rgba"] = source.rgba[0]
                    old_bytes = entry.nbytes
                    entry.geometry = replace(entry.geometry, vertices=_readonly(vertices))
                    entry.source = replace(entry.source, rgba=_readonly(source.rgba))
                    self._bytes += entry.nbytes - old_bytes
                    self._totals["paint_updates"] += 1
                self._totals["hits"] += 1
                entry.last_frame = self._frame
                self._entries.move_to_end(owner_id)
                # A changed paint-array dtype/shape must not escape retention
                # limits. Returned immutable frame data may outlive the cache.
                while self._bytes > self.max_bytes:
                    self._remove(next(iter(self._entries)))
                return entry.geometry.vertices, entry.geometry.indices
            # Never preserve a stale mesh when replacement generation fails.
            self._remove(owner_id)
        geometry = _generate_mesh(source, tessellator, uniforms, resolution,
                                  pixel_tolerance, self.refinement_factor)
        self._totals["regenerations"] += 1
        nbytes = sum(a.nbytes for a in (*source.arrays(), *geometry.arrays()))
        if self.max_entries and nbytes <= self.max_bytes:
            while (len(self._entries) >= self.max_entries
                   or self._bytes + nbytes > self.max_bytes):
                self._remove(next(iter(self._entries)))
            entry = _MeshEntry(weakref.ref(mobject), source.frozen(),
                               geometry.frozen(), self._frame)
            self._entries[owner_id] = entry
            self._bytes += entry.nbytes
            geometry = entry.geometry
        return geometry.vertices, geometry.indices


def projection_matrix(uniforms):
    """World xyz -> the shader's pre-perspective xyz, in float64 arithmetic."""
    view = np.asarray(uniforms["view"], dtype="f4").reshape(4, 4).T.astype(float)
    scale = np.asarray(uniforms["frame_rescale_factors"], dtype="f4").astype(float)
    fixed = float(np.float32(uniforms.get("is_fixed_in_frame", 0)))
    if not 0 <= fixed <= 1 or not np.isfinite(view).all() or not np.isfinite(scale).all():
        raise UnsupportedPrototype("nonfinite or unsupported camera transform")
    matrix = ((1 - fixed) * view[:3, :3] + fixed * np.eye(3)) * scale[:, None]
    shift = (1 - fixed) * view[:3, 3] * scale
    return matrix, shift


def world_to_pixel(points, uniforms, resolution):
    matrix, shift = projection_matrix(uniforms)
    p = np.asarray(points) @ matrix.T + shift
    w = 1 - p[..., 2]
    if np.any(w <= 0):
        raise UnsupportedPrototype("path crosses the perspective singularity")
    ndc = p[..., :2] / w[..., None]
    return (ndc * [1, -1] + 1) * np.asarray(resolution) / 2


def planar_coordinates(points):
    """Choose an orthonormal plane; refuse to invent a nonplanar interior."""
    points = np.asarray(points, dtype=float)
    if not np.isfinite(points).all():
        raise UnsupportedPrototype("nonfinite source points")
    origin = points[0]
    centered = points - origin
    if len(points) < 3:
        return centered[:, :2], origin, np.eye(3)[:2], np.array([0., 0., 1.])
    _, _, basis = np.linalg.svd(centered, full_matrices=False)
    normal = basis[2]
    extent = max(float(np.linalg.norm(centered, axis=1).max()), 1.0)
    if np.max(np.abs(centered @ normal)) > 1e-6 * extent:
        raise UnsupportedPrototype("nonplanar filled path needs a defined surface/projection")
    return centered @ basis[:2].T, origin, basis[:2], normal


def projection_scale_bound(points, basis, uniforms, resolution, *, _projection=None):
    """Bound pixels per unit along orthonormal basis directions over a hull."""
    matrix, shift = projection_matrix(uniforms) if _projection is None else _projection
    projected = points @ matrix.T + shift
    w = 1 - projected[:, 2]
    min_w = float(w.min())
    if min_w <= 1e-5:
        raise UnsupportedPrototype("near-plane/singular projection requires clipping before meshing")
    derivatives = matrix @ basis.T
    # |d(n/w)| <= |dn|/min(w) + max(|n|)*|dw|/min(w)^2.
    row_bounds = (np.linalg.norm(derivatives[:2], axis=1) / min_w
                  + np.max(abs(projected[:, :2]), axis=0)
                  * np.linalg.norm(derivatives[2]) / min_w ** 2)
    pixels_per_unit = float(np.linalg.norm(row_bounds * np.asarray(resolution) / 2))
    if not np.isfinite(pixels_per_unit):
        raise UnsupportedPrototype("unbounded projection error")
    return pixels_per_unit


def plane_tolerance(points, basis, uniforms, resolution, pixel_tolerance):
    """Convert a remaining pixel budget into local-plane flattening tolerance.

    A quadratic and its flattened segments remain in the control hull. The
    Jacobian bound there is conservative for geometric flattening. Subsequent
    float32 rounding and antialiasing are separate fidelity gates.
    """
    if not np.isfinite(pixel_tolerance) or pixel_tolerance <= 0:
        raise ValueError("pixel_tolerance must be finite and positive")
    pixels_per_unit = projection_scale_bound(points, basis, uniforms, resolution)
    return pixel_tolerance / max(pixels_per_unit, 1e-12)


def planar_projection_error(source_points, fitted_points, uniforms, resolution, *,
                            _projection=None, _residual=None):
    """Conservatively charge plane fitting against the screen-error budget.

    The displacement of corresponding points on the two quadratic curves is
    at most the largest control-point displacement. Their connecting segments
    stay inside the combined control hull. The full 3D projection Jacobian on
    that hull therefore bounds screen displacement, including perspective's
    changing weights; projecting the control-point displacements alone would
    not establish this bound.
    """
    residual = (np.linalg.norm(source_points - fitted_points, axis=1).max()
                if _residual is None else _residual)
    if residual == 0:
        return 0.0
    hull = np.concatenate((source_points, fitted_points))
    scale = projection_scale_bound(hull, np.eye(3), uniforms, resolution,
                                   _projection=_projection)
    return float(residual * scale)


def mesh_mobject(mobject, tessellator, uniforms, resolution, pixel_tolerance=0.25,
                 *, border_settings=(0.0, "bevel")):
    """Return surface-layout fill data without changing public source points."""
    geometry = _generate_mesh(_MeshSource.read(mobject, border_settings), tessellator, uniforms,
                              resolution, pixel_tolerance)
    return geometry.vertices, geometry.indices


def _border_hull(points, basis, settings):
    """Conservative projection hull for the border's bounded local extent."""
    width, join = settings
    if not width:
        return points
    radius = width * (2.0 if join == "miter" else 0.5)
    corners = np.array([[-1, -1], [-1, 1], [1, -1], [1, 1]]) * radius
    return (points[:, None, :] + corners @ basis).reshape(-1, 3)


def _generate_mesh(source, tessellator, uniforms, resolution, pixel_tolerance,
                   refinement_factor=1.0):
    if not np.isfinite(pixel_tolerance) or pixel_tolerance <= 0:
        raise ValueError("pixel_tolerance must be finite and positive")
    points = source.points
    empty = _MeshGeometry(np.empty(0, dtype=SURFACE_DTYPE), np.empty(0, dtype="u4"),
                          np.empty((0, 3)), np.empty((0, 3)), 0.0)
    if len(points) < 3:
        return empty
    ends = source.ends
    starts = [0, *(ends[:-1] + 2)]
    ranges = [slice(int(start), int(end) + 1) for start, end in zip(starts, ends)
              if end - start >= 2]
    if not ranges:
        return empty
    xy, origin, basis, normal = planar_coordinates(points)
    contours = [xy[part] for part in ranges]
    rgba = source.rgba
    fitted_points = xy @ basis + origin
    residual_pixels = planar_projection_error(points, fitted_points, uniforms, resolution)
    if not np.isfinite(residual_pixels) or residual_pixels >= pixel_tolerance:
        raise UnsupportedPrototype("plane-fitting residual exceeds the pixel error budget")
    tolerance = plane_tolerance(_border_hull(fitted_points, basis, source.border_settings),
                                basis, uniforms, resolution,
                                (pixel_tolerance - residual_pixels) * refinement_factor)
    # The native adapter takes f32. Round downward so converting the requested
    # tolerance cannot overspend a strict caller budget on an uncached frame.
    tolerance32 = np.float32(min(tolerance, np.finfo("f4").max))
    if float(tolerance32) > tolerance:
        tolerance32 = np.nextafter(tolerance32, np.float32(0))
    if tolerance32 <= 0:
        raise UnsupportedPrototype("required tolerance is below float32 range")
    border_options = ({"border_width": source.border_settings[0],
                       "border_join": source.border_settings[1]}
                      if source.border_settings[0] else {})
    mesh = tessellator.tessellate(
        contours, attributes=[rgba[part] for part in ranges],
        tolerance=float(tolerance32), fill_rule="nonzero", **border_options)
    if not np.isfinite(mesh.tolerance) or not 0 < mesh.tolerance <= tolerance:
        raise UnsupportedPrototype("generator returned a tolerance above the requested budget")
    vertices = np.zeros(len(mesh.positions), dtype=SURFACE_DTYPE)
    vertices["point"] = mesh.positions @ basis + origin
    # Keep the source normal orientation for lighting; SVD's sign is arbitrary.
    source_normal = source.normal
    if np.dot(normal, source_normal) < 0:
        normal = -normal
    vertices["d_normal_point"] = vertices["point"] + 0.001 * normal
    vertices["rgba"] = mesh.attributes
    residual = float(np.linalg.norm(points - fitted_points, axis=1).max())
    return _MeshGeometry(vertices, mesh.indices, fitted_points, basis,
                         float(mesh.tolerance), residual)


def prepare_triangle_frame(scene, tessellator, *, pixel_tolerance=0.25,
                           diagnostic=False, mesh_cache=None, fill_builder=None,
                           coalesce=True, fill_borders=False):
    """Prepare ordered operations for the shared triangle pipelines.

    Supports planar vector fills, existing strokes, surfaces, textured surfaces,
    images and dot clouds. ``fill_borders=True`` includes uniform flat borders
    as one binary fill/stroke union and records the remaining auto-join/AA gap.
    Per-point fill paint and fill lighting still require explicit diagnostic
    mode until their appearance has passed the parity gate.
    An optional TriangleMeshCache retains per-path fills across calls. Its frame
    statistics count cache hits, successful regenerations, and discarded entries;
    retained_bytes includes source snapshots and mesh metadata as well as draws.
    A diagnostic candidate can supply fill_builder(mobject, uniforms,
    resolution, pixel_tolerance), returning one ordered TriangleDraw or None.
    Its own cache/lifecycle belongs to that callback's caller; mesh_cache and
    fill_builder are mutually exclusive. Default fill generation is unchanged.
    Consecutive compatible surface/stroke draws are coalesced by default;
    ``coalesce=False`` retains per-object draws for diagnostics. Coalesced arrays
    belong to the returned frame and are not included in retained cache bytes.
    """
    camera = scene.camera
    if not np.isfinite(pixel_tolerance) or pixel_tolerance <= 0:
        raise ValueError("pixel_tolerance must be finite and positive")
    if fill_builder is not None and mesh_cache is not None:
        raise ValueError("fill_builder and mesh_cache are mutually exclusive")
    camera.refresh_uniforms()
    frame = TriangleFrame(tuple(camera.draw_fbo.size), tuple(camera.background_rgba),
                          4 if camera.samples else 1, pixel_tolerance=pixel_tolerance)
    cache_before = mesh_cache.begin_frame(tessellator) if mesh_cache is not None else None
    camera_uniforms = {key: _jsonable(value) for key, value in camera.uniforms.items()}

    def limitation(message):
        if not diagnostic:
            raise UnsupportedPrototype(message)
        if message not in frame.limitations:
            frame.limitations.append(message)

    for group in scene.render_groups:
        for sm in sorted(group.family_members_with_points(), key=lambda obj: obj.z_index):
            if isinstance(sm, CameraFrame):
                continue
            uniforms = {**camera_uniforms,
                        **{key: _jsonable(value) for key, value in sm.uniforms.items()}}
            depth_suffix = "_depth" if sm.depth_test else ""
            if isinstance(sm, (DotCloud, Surface, ImageMobject)):
                data = np.ascontiguousarray(sm.get_shader_data()).copy()
                if not len(data):
                    continue
                pipeline = ("dot" if isinstance(sm, DotCloud) else
                            "image" if isinstance(sm, ImageMobject) else
                            "texsurface" if isinstance(sm, TexturedSurface) else "surface")
                frame.draws.append(TriangleDraw(
                    pipeline + depth_suffix, data, uniforms,
                    count=4 if pipeline == "dot" else len(data),
                    instances=len(data) if pipeline == "dot" else 1,
                    textures=_texture_refs(sm) if pipeline in ("image", "texsurface") else {}))
                frame.source_bytes += data.nbytes
                continue
            if not isinstance(sm, VMobject):
                raise UnsupportedPrototype(f"{type(sm).__name__} awaits primitive integration")
            frame.source_bytes += sm.data.nbytes
            fill = None
            border_settings = (0.0, "bevel")
            if np.any(sm.data["fill_rgba"][:, 3]):
                if not np.all(sm.data["fill_rgba"] == sm.data["fill_rgba"][0]):
                    limitation("per-point fill paint uses endpoint interpolation; interior parity unproved")
                if np.any(sm.data["fill_border_width"]):
                    if not fill_borders:
                        limitation("fill-border coverage is disabled for this triangle frame")
                    else:
                        widths = sm.data["fill_border_width"]
                        if not np.isfinite(widths).all() or not np.all(widths == widths[0]) or widths[0, 0] < 0:
                            raise UnsupportedPrototype("border union requires a uniform nonnegative width")
                        if not uniforms.get("flat_stroke") and not uniforms.get("is_fixed_in_frame"):
                            raise UnsupportedPrototype("camera-facing fill borders require a projected coverage implementation")
                        factor = 0.01 * (uniforms["frame_scale"] *
                            (1 - uniforms["scale_stroke_with_zoom"]) + uniforms["scale_stroke_with_zoom"])
                        join = "miter" if uniforms.get("joint_type") == 3 else "bevel"
                        border_settings = (float(widths[0, 0]) * factor, join)
                        note = "fill borders use a binary Lyon union; auto joins and edge AA await parity acceptance"
                        if note not in frame.limitations:
                            frame.limitations.append(note)
                if np.any(uniforms.get("shading", (0, 0, 0))):
                    limitation("fill lighting is evaluated at generated vertices; parity unproved")
                if fill_builder is not None:
                    fill = fill_builder(sm, uniforms, frame.resolution, pixel_tolerance)
                else:
                    mesh_function = mesh_cache.mesh if mesh_cache is not None else mesh_mobject
                    vertices, indices = mesh_function(sm, tessellator, uniforms,
                                                      frame.resolution, pixel_tolerance,
                                                      border_settings=border_settings)
                    if len(indices):
                        fill = TriangleDraw("surface" + depth_suffix, vertices, uniforms,
                                            indices, len(indices))
            stroke = None
            if np.any(sm.data["stroke_width"]) and np.any(sm.data["stroke_rgba"][:, 3]):
                data = np.ascontiguousarray(sm.get_shader_data()).copy()
                stroke = TriangleDraw("stroke" + depth_suffix, data, uniforms,
                                      count=_stroke_verts(data, uniforms["frame_scale"]),
                                      instances=len(data) // 3)
            ordered = (stroke, fill) if sm.stroke_behind else (fill, stroke)
            frame.draws.extend(draw for draw in ordered if draw is not None)
    if mesh_cache is not None:
        frame.mesh_cache_stats = mesh_cache.finish_frame(cache_before)
    if coalesce:
        frame.draws = coalesce_draws(frame.draws)
    return frame

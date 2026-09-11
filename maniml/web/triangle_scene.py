"""CPU generation for the shared triangle renderer.

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
from maniml.mobject.mobject import Mobject
from maniml.mobject.types.vectorized_mobject import VMobject
from maniml.web.geometry import SURFACE_DTYPE, _jsonable, _stroke_verts, _texture_refs
from maniml.web.triangle_geometry import TessellationError
from maniml.web.border_geometry import (
    BorderSource, MAX_BORDER_TRIANGLES, RenderCacheStale, emit_border_triangles,
    render_cache_policy, verify_render_cache,
)
from maniml.web.fill_paint import MAX_PAINT_SAMPLES, build_paint
from maniml.web.gpu_border_geometry import (
    BorderRecipeCache, MAX_RUN_OUTPUT_BYTES, MAX_VERTICES_PER_CURVE, indices_per_curve,
    patch_draw_count,
)
from maniml.web.gpu_net_geometry import NetRecipeCache, indices_per_patch, pixels_per_unit


_DEFAULT_CONTOUR_METHOD = VMobject.get_subpath_end_indices_from_points
_STANDARD_MESH_GETTERS = (("get_points", Mobject.get_points),
                          ("get_unit_normal", VMobject.get_unit_normal),
                          ("get_subpath_end_indices_from_points", _DEFAULT_CONTOUR_METHOD))


_STANDARD_MESH_NAMES = frozenset(name for name, _ in _STANDARD_MESH_GETTERS)
_STANDARD_MESH_CLASSES = {}


def _standard_mesh_getters(mobject):
    cls = type(mobject)
    standard = _STANDARD_MESH_CLASSES.get(cls)
    if standard is None:
        standard = _STANDARD_MESH_CLASSES[cls] = all(
            getattr(cls, name, None) is method for name, method in _STANDARD_MESH_GETTERS)
    return standard and not (_STANDARD_MESH_NAMES & mobject.__dict__.keys())


def classify_source(mobject):
    """The per-object style facts frame preparation branches on, read from the
    public arrays: (has fill, uniform fill color, has fill border, opaque fill
    alpha, has visible stroke)."""
    data = mobject.data
    fill = data["fill_rgba"]
    return (bool(np.any(fill[:, 3])), bool(np.all(fill == fill[0])),
            bool(np.any(data["fill_border_width"])), bool(fill[0, 3] == 1) if len(fill) else False,
            bool(np.any(data["stroke_width"]) and np.any(data["stroke_rgba"][:, 3])))


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
    paint: np.ndarray | list | None = None
    coverage: bool = False
    border_sources: np.ndarray | None = None
    # GPU border runs: vertices reserved per curve, and the per-object
    # (fill index count, fill vertex count, curve count) layout the drivers
    # expand into the interleaved fill/border index buffer locally.
    border_capacity: int = MAX_VERTICES_PER_CURVE
    border_layout: tuple | None = None
    # Patch fill runs (docs/phase_b1_plan.md): the object table, eight words
    # per object, and the (curve count, bordered) layout the drivers draw
    # per object. Such a draw has no vertices or indices of its own.
    fill_objects: np.ndarray | None = None
    patch_layout: tuple | None = None
    # Surface nets (docs/phase_b2_plan.md): the control net the driver
    # evaluates at screen density, its (nu, nv, channels), the reserved
    # steps per patch edge and the density the steps follow from.
    net: np.ndarray | None = None
    net_shape: tuple | None = None
    net_capacity: int = 2
    net_density: float = 0.0


def coalesce_draws(draws, *, border_cache=None):
    """Join consecutive compatible draws without changing primitive order.

    Full normalized uniforms, vertex layout and depth pipeline must agree.
    Indexed fills keep every triangle in source order; strokes keep every
    curve instance in source order. The stroke shader clamps extra strip
    vertices to a degenerate tail, so a run can use its largest strip count.
    Unknown pipelines and partial draw ranges remain separate. Runs allocate
    frame-owned arrays; a single draw retains its original array identities.
    """
    def kind(draw):
        if draw.net is not None:
            return None  # one evaluated net per draw
        if draw.fill_objects is not None:
            # A material run binds one paint field, so a painted patch
            # draw stays a run of its own.
            return "patch" if draw.paint is None else None
        if draw.border_sources is not None:
            return None if draw.coverage else "border"
        if draw.coverage:
            return None  # A stencil reference belongs to exactly one object.
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
        if run[0].fill_objects is not None:
            curves, capacity, layout, objects = border_cache.assemble_patches(
                [(draw.border_sources, draw.border_capacity, draw.fill_objects,
                  draw.patch_layout[0][1], draw.patch_layout[0][2])
                 for draw in run])
            return replace(run[0], border_sources=curves, border_capacity=capacity,
                           patch_layout=layout, fill_objects=objects,
                           count=patch_draw_count(layout, capacity))
        if run[0].border_sources is not None:
            vertices, indices, curves, capacity, layout = border_cache.assemble(
                [(draw.vertices, draw.indices, draw.border_sources, draw.border_capacity)
                 for draw in run])
            return replace(run[0], vertices=vertices, indices=indices, border_sources=curves,
                           border_capacity=capacity, border_layout=layout,
                           count=len(indices) + indices_per_curve(capacity) * len(curves))
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
    curve_count, run_capacity = 0, 0

    def border_run_bytes(draw):
        # A run reserves its largest member's capacity for every curve.
        capacity = max(run_capacity, draw.border_capacity)
        curves = curve_count + len(draw.border_sources)
        return (vertex_count + len(draw.vertices) + capacity * curves) * 40

    for draw in draws:
        draw_kind = kind(draw)
        compatible = (run and run_kind is not None and draw_kind == run_kind
                      and draw.pipeline == run[0].pipeline
                      and draw.vertices.dtype == run[0].vertices.dtype
                      and draw.uniforms == run[0].uniforms
                      and draw.textures == run[0].textures
                      and (draw_kind not in ("border", "patch") or border_run_bytes(draw) <= MAX_RUN_OUTPUT_BYTES)
                      and (draw_kind != "indexed" or
                           (draw.indices.dtype == np.dtype("u4")
                            and run[0].indices.dtype == np.dtype("u4")
                            and vertex_count + len(draw.vertices) <= 2 ** 32)))
        if run and not compatible:
            result.append(combine(run, run_kind))
            run, vertex_count, curve_count, run_capacity = [], 0, 0, 0
        run.append(draw)
        run_kind = draw_kind
        vertex_count += len(draw.vertices)
        if draw.border_sources is not None:
            curve_count += len(draw.border_sources)
            run_capacity = max(run_capacity, draw.border_capacity)
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
    supersample: int = 1
    texture_data: dict = field(default_factory=dict)

    @property
    def geometry_bytes(self):
        return sum(draw.vertices.nbytes + (0 if draw.indices is None else
                                          draw.indices.nbytes)
                   + (0 if draw.border_sources is None else draw.border_sources.nbytes)
                   for draw in self.draws)


def _readonly(array):
    """Own immutable backing bytes: callers cannot re-enable array writes."""
    array = np.ascontiguousarray(array)
    return np.frombuffer(array.tobytes(), dtype=array.dtype).reshape(array.shape)


# A patch fill draw owns no vertices; every one shares this empty array.
_NO_VERTICES = _readonly(np.zeros(0, dtype=SURFACE_DTYPE))


@dataclass
class _MeshSource:
    points: np.ndarray
    ends: np.ndarray
    rgba: np.ndarray
    normal: np.ndarray
    border_settings: tuple = (0.0, "bevel")
    contour_rule: object = None

    @classmethod
    def read(cls, mobject, border_settings=(0.0, "bevel"), *, previous=None, trusted=False):
        """Snapshot the fill's source. ``trusted`` says the caller saw the
        same ``Mobject.revision`` as when ``previous`` was read: the snapshot
        is reused without reading the arrays, unless a custom getter or
        contour rule could depend on other state. Under MANIML_VERIFY_LEDGER=1
        the arrays are read anyway and a stale reuse raises."""
        if (trusted and previous is not None and previous.contour_rule is _DEFAULT_CONTOUR_METHOD
                and _standard_mesh_getters(mobject)):
            if verify_render_cache():
                fresh = cls.read(mobject, border_settings, previous=previous)
                for name, kept, live in (("points", previous.points, fresh.points),
                                         ("fill_rgba", previous.rgba, fresh.rgba),
                                         ("unit_normal", previous.normal, fresh.normal)):
                    if not np.array_equal(kept, live):
                        raise RenderCacheStale(
                            f"{type(mobject).__name__} changed in '{name}' since its last "
                            f"frame without a revision bump")
                return fresh
            if previous.border_settings == border_settings:
                return previous
            return replace(previous, border_settings=border_settings)
        points = np.asarray(mobject.get_points(), dtype=float)
        contour_method = mobject.get_subpath_end_indices_from_points
        contour_rule = getattr(contour_method, "__func__", contour_method)
        if (previous is not None
                and contour_rule is _DEFAULT_CONTOUR_METHOD
                and previous.contour_rule is _DEFAULT_CONTOUR_METHOD
                and np.array_equal(points, previous.points)):
            # The built-in contour rule depends only on the actual points.
            # Content equality was established above, including untracked
            # public-array writes; custom contour methods still run each time.
            points, ends = previous.points, previous.ends
        else:
            ends = contour_method(points) if len(points) else np.empty(0, dtype=int)
        return cls(points, np.asarray(ends), mobject.data["fill_rgba"],
                   np.asarray(mobject.get_unit_normal()), border_settings, contour_rule)

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
                all(getattr(self, name) is getattr(other, name)
                    or np.array_equal(getattr(self, name), getattr(other, name))
                    for name in ("points", "ends", "normal")))

    def frozen(self):
        return _MeshSource(*(_readonly(array) for array in self.arrays()),
                           self.border_settings, self.contour_rule)


@dataclass
class _MeshGeometry:
    vertices: np.ndarray
    indices: np.ndarray
    fitted_points: np.ndarray
    basis: np.ndarray
    local_tolerance: float
    fit_residual: float = 0.0
    error_hull: np.ndarray | None = None
    error_basis: np.ndarray | None = None

    def arrays(self):
        return tuple(array for array in (self.vertices, self.indices, self.fitted_points,
                                          self.basis, self.error_hull, self.error_basis)
                     if array is not None)

    def frozen(self):
        return replace(self, **{name: _readonly(getattr(self, name))
                                for name in ("vertices", "indices", "fitted_points", "basis",
                                             "error_hull", "error_basis")
                                if getattr(self, name) is not None})

    def pixel_error(self, source, uniforms, resolution, *, projection=None):
        if not self.local_tolerance:  # No eligible filled contour.
            return 0.0
        if self.error_hull is not None:
            scales = projection_scale_bound(self.error_hull, self.error_basis,
                                             uniforms, resolution, _projection=projection)
            # Both derivative bounds use a hull containing source and fitted
            # controls. Sharing it can enlarge a bound, never undercharge the
            # fit residual or the curve-flattening displacement.
            return self.local_tolerance * scales[0] + self.fit_residual * scales[1]
        residual = planar_projection_error(source.points, self.fitted_points,
                                           uniforms, resolution, _projection=projection,
                                           _residual=self.fit_residual)
        scale = projection_scale_bound(_border_hull(self.fitted_points, self.basis,
                                                   source.border_settings), self.basis,
                                       uniforms, resolution, _projection=projection)
        return residual + self.local_tolerance * scale


@dataclass
class _CoverageGeometry:
    source: BorderSource
    vertices: np.ndarray
    indices: np.ndarray
    border_vertex_count: int
    fill_vertices: weakref.ReferenceType
    fill_indices: weakref.ReferenceType

    @property
    def nbytes(self):
        return sum(a.nbytes for a in (*self.source.arrays(), self.vertices, self.indices))


def _combine_border(vertices, indices, source, uniforms, rgba, *, previous=None, border_vertices=None):
    """Complete object geometry; fill triangles precede overlapping border strips."""
    if border_vertices is not None:
        border = border_vertices
    elif previous is not None and previous.source == source:
        border_count = previous.border_vertex_count
        border = previous.vertices[-border_count:].copy() if border_count else previous.vertices[:0]
    else:
        triangles, normals = emit_border_triangles(source.data, uniforms, return_normals=True,
                                                   step_counts=source.counts)
        border = np.zeros(len(triangles) * 3, dtype=SURFACE_DTYPE)
        border["point"] = triangles.reshape(-1, 3)
        border["d_normal_point"] = (triangles + .001 * normals).reshape(-1, 3)
    combined = np.concatenate([vertices, border])
    combined["rgba"][len(vertices):] = rgba
    if (previous is not None and previous.fill_indices() is indices
            and previous.border_vertex_count == len(border)
            and len(previous.vertices) == len(combined)):
        combined_indices = previous.indices
    else:
        combined_indices = np.concatenate([indices, np.arange(len(vertices), len(combined), dtype="u4")])
    return combined, combined_indices, len(border)


def _prepare_border_geometry(records, mesh_cache):
    """Vectorize changed borders sharing geometry uniforms, with bounded chunks.

    Object order and stencil ownership are unchanged; this only shares CPU
    arithmetic. Each object keeps its independent retention/error checks.
    Cached strips are views until composition copies them into a new frame.
    """
    prepared, groups = {}, {}
    for mobject, uniforms in records:
        if (not isinstance(mobject, VMobject) or not np.any(mobject.data["fill_rgba"][:, 3])
                or not np.any(mobject.data["fill_border_width"])):
            continue
        entry = None if mesh_cache is None else mesh_cache._entries.get(id(mobject))
        previous = None if entry is None else entry.coverage_geometry
        source = BorderSource.read(mobject, uniforms,
                                   previous=None if previous is None else previous.source,
                                   trusted=previous is not None and mesh_cache.trusts(mobject))
        if previous is not None and previous.source == source:
            count = previous.border_vertex_count
            border = previous.vertices[-count:] if count else previous.vertices[:0]
            prepared[id(mobject)] = (source, border)
        elif not source.triangle_count:
            prepared[id(mobject)] = (source, np.empty(0, dtype=SURFACE_DTYPE))
        else:
            groups.setdefault(source.key, []).append((mobject, source, uniforms))

    def emit_chunk(chunk):
        data = np.concatenate([source.data for _, source, _ in chunk])
        counts = np.concatenate([source.counts for _, source, _ in chunk])
        triangles, normals = emit_border_triangles(data, chunk[0][2], return_normals=True,
                                                   step_counts=counts)
        border = np.zeros(len(triangles) * 3, dtype=SURFACE_DTYPE)
        border["point"] = triangles.reshape(-1, 3)
        border["d_normal_point"] = (triangles + .001 * normals).reshape(-1, 3)
        offset = 0
        for mobject, source, _ in chunk:
            count = source.triangle_count * 3
            prepared[id(mobject)] = (source, border[offset:offset + count])
            offset += count
        if offset != len(border):
            raise TessellationError("grouped border emission returned inconsistent counts")

    for jobs in groups.values():
        chunk, triangles, source_bytes = [], 0, 0
        for job in jobs:
            count, size = job[1].triangle_count, job[1].data.nbytes
            if chunk and (triangles + count > MAX_BORDER_TRIANGLES or source_bytes + size > 8 << 20):
                emit_chunk(chunk)
                chunk, triangles, source_bytes = [], 0, 0
            chunk.append(job)
            triangles += count
            source_bytes += size
        if chunk:
            emit_chunk(chunk)
    return prepared


@dataclass
class _MeshEntry:
    owner: weakref.ReferenceType
    source: _MeshSource
    geometry: _MeshGeometry
    last_frame: int
    projection_key: tuple | None = None
    projected_error: float | None = None
    paint_field: object = None
    coverage_geometry: _CoverageGeometry | None = None
    # Mobject.revision when the source snapshot was read; the revision policy
    # reuses the snapshot while it still matches.
    revision: int | None = None
    # Whether every fill vertex carries the source's first color (set at
    # generation and after a paint refresh), for the opaque-painter test.
    uniform_vertex_color: bool = False

    @property
    def nbytes(self):
        return (sum(array.nbytes for array in (*self.source.arrays(),
                                               *self.geometry.arrays()))
                + (0 if self.paint_field is None else self.paint_field.nbytes)
                + (0 if self.coverage_geometry is None else self.coverage_geometry.nbytes))

    def pixel_error(self, source, uniforms, resolution, *, projection_cache=None):
        """Memoize only this immutable mesh's most recent camera error bound.

        The caller must first establish exact source identity. Key the actual
        projection inputs at the float32 precision consumed by the shader,
        including fixed-frame interpolation and output size. A changed quality
        request still compares against the stored numeric error; it is never
        treated as automatic permission to reuse. Unrelated lighting/AA changes
        do not invalidate the geometric projection bound.
        """
        key, projection = _projection_state(uniforms, resolution, projection_cache)
        if key != self.projection_key:
            error = self.geometry.pixel_error(source, uniforms, resolution,
                                             projection=projection)
            if not np.isfinite(error):
                raise UnsupportedPrototype("unbounded projection error")
            self.projection_key, self.projected_error = key, error
        return self.projected_error


class TriangleMeshCache:
    """Retained fill meshes, bounded by array bytes and entry count.

    Fill reuse requires exact source/contour/normal content and the same
    tessellator instance. A configurable generator must additionally expose an
    immutable ``cache_key`` value and change it when output-affecting settings
    change. The last projected error is memoized by exact projection inputs;
    Paint changes refresh vertex colors and the independent paint field without
    regenerating geometry. Actual paint bytes are checked each frame; color
    refresh still copies/uploads interleaved vertices. Border strips have a
    separate source/style/subdivision key and retain their actual world depth.
    Width, join or camera-facing changes regenerate borders without retessellating
    the fill. Combined object arrays remain immutable and count against the same
    retention limit. Changed camera
    dependencies recompute the bound without altering source
    identity. With ``refinement_factor=0.5``, a rebuild
    spends half the remaining geometric budget, giving headroom for zooming in.
    Zooming out retains the finer mesh rather than producing repeated coarse
    versions. The fill tolerance controls plane fitting plus curve flattening.
    Borders follow the existing shader's own quantized subdivision; this does
    not prove arbitrary stroked-cusp accuracy, float32 arithmetic or antialiasing,
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
        self._classes = {}
        self.gpu_net_cache = NetRecipeCache()
        self.gpu_border_cache = BorderRecipeCache(max_bytes=self.max_bytes if self.max_entries else 0)
        self._totals = {"hits": 0, "regenerations": 0, "evictions": 0, "paint_updates": 0,
                        "border_regenerations": 0}
        self.policy = render_cache_policy()

    @property
    def stats(self):
        return {**self._totals, "retained_bytes": self._bytes + self.gpu_border_cache.nbytes,
                "retained_fill_cache_bytes": self._bytes,
                "retained_gpu_recipe_bytes": self.gpu_border_cache.nbytes,
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
        self._classes.clear()
        self.gpu_border_cache.clear()

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
        self.policy = render_cache_policy()
        for owner_id, entry in list(self._entries.items()):
            if entry.owner() is None:
                self._remove(owner_id)
        return before

    def classify(self, mobject):
        """``classify_source`` memoized by revision under the revision policy;
        verification recomputes and raises on a bypassing style write."""
        owner_id = id(mobject)
        held = self._classes.get(owner_id)
        if (held is not None and self.policy == "revision" and held[0]() is mobject
                and held[1] == mobject.revision):
            if verify_render_cache():
                fresh = classify_source(mobject)
                if fresh != held[2]:
                    raise RenderCacheStale(
                        f"{type(mobject).__name__} changed in 'fill_rgba', 'fill_border_width', "
                        f"'stroke_width' or 'stroke_rgba' since its last frame without a revision bump")
            self._classes[owner_id] = (held[0], held[1], held[2], self._frame)
            return held[2]
        classes = classify_source(mobject)
        self._classes[owner_id] = (weakref.ref(mobject), mobject.revision, classes, self._frame)
        return classes

    def uniform_vertex_color(self, mobject):
        entry = self._entries.get(id(mobject))
        return entry is not None and entry.owner() is mobject and entry.uniform_vertex_color

    def bound_errors(self, records, resolution):
        """Bound this frame's projection error for every retained mesh at once.

        ``mesh()`` asks each entry whether its mesh still meets tolerance at
        the current camera; done per object that is a hundred small numpy
        calls per frame on a text slide. Group the retained entries by exact
        camera state, project every error hull in one product, reduce per
        entry, and leave each entry's memo set so ``mesh()`` finds it. The
        arithmetic is the per-entry bound's, only stacked. Entries whose
        projection is singular are left unset so ``mesh()`` reports them.
        """
        groups = {}
        for mobject, uniforms in records:
            entry = self._entries.get(id(mobject))
            if entry is None or entry.owner() is not mobject:
                continue
            geometry = entry.geometry
            if geometry.error_hull is None or not geometry.local_tolerance:
                continue
            try:
                key, projection = _projection_state(uniforms, resolution, self._projections)
            except UnsupportedPrototype:
                continue
            if entry.projection_key == key:
                continue
            groups.setdefault(key, (projection, []))[1].append(entry)
        for key, (projection, entries) in groups.items():
            for entry, error in zip(entries, _batched_projection_errors(entries, projection, resolution)):
                if np.isfinite(error):
                    entry.projection_key, entry.projected_error = key, float(error)

    def trusts(self, mobject):
        """Whether this mobject's retained source was read at its current
        revision, so the revision policy may reuse it without reading bytes."""
        entry = self._entries.get(id(mobject))
        return (self.policy == "revision" and entry is not None and entry.owner() is mobject
                and entry.revision == mobject.revision)

    def finish_frame(self, before):
        for owner_id, entry in list(self._entries.items()):
            if entry.last_frame != self._frame:
                self._remove(owner_id)
        for owner_id, (_, _, _, frame) in list(self._classes.items()):
            if frame != self._frame:
                del self._classes[owner_id]
        now = self.stats
        # Camera matrix sharing is preparation scratch, not retained mesh data.
        self._projections.clear()
        return {**now, **{key: now[key] - before[key] for key in self._totals}}

    def mesh(self, mobject, tessellator, uniforms, resolution, pixel_tolerance,
             *, border_settings=(0.0, "bevel")):
        owner_id = id(mobject)
        entry = self._entries.get(owner_id)
        held = entry is not None and entry.owner() is mobject
        source = _MeshSource.read(mobject, border_settings,
                                  previous=entry.source if held else None,
                                  trusted=held and self.trusts(mobject)
                                  and not mobject.needs_new_unit_normal)
        if entry is not None:
            same_paint = entry.source.rgba is source.rgba or np.array_equal(entry.source.rgba, source.rgba)
            paint_refresh = same_paint or (len(source.rgba) > 0 and np.isfinite(source.rgba).all()
                # The mesh stores this uniform attribute as float32, matching
                # native generation's input validation. Finite float64 source
                # values must not overflow only on the cache-refresh path.
                and (source.rgba.dtype == np.float32
                     or np.all(np.abs(source.rgba[0]) <= np.finfo("f4").max)))
            if (entry.owner() is mobject and entry.source.geometry_matches(source)
                    and (same_paint or paint_refresh)
                    and entry.pixel_error(source, uniforms, resolution,
                                          projection_cache=self._projections)
                    <= pixel_tolerance):
                if not same_paint:
                    vertices = entry.geometry.vertices.copy()
                    vertices["rgba"] = source.rgba[0]
                    old_bytes = entry.nbytes
                    entry.geometry = replace(entry.geometry, vertices=_readonly(vertices))
                    entry.source = replace(entry.source, rgba=_readonly(source.rgba))
                    entry.paint_field = None
                    entry.uniform_vertex_color = True
                    self._bytes += entry.nbytes - old_bytes
                    self._totals["paint_updates"] += 1
                self._totals["hits"] += 1
                entry.last_frame = self._frame
                entry.revision = mobject.revision
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
                               geometry.frozen(), self._frame, revision=mobject.revision,
                               uniform_vertex_color=bool(len(source.rgba)) and bool(
                                   np.all(geometry.vertices["rgba"] == source.rgba[0])))
            self._entries[owner_id] = entry
            self._bytes += entry.nbytes
            geometry = entry.geometry
        return geometry.vertices, geometry.indices

    def paint(self, mobject):
        """Material coefficients reuse the mesh entry's exact source snapshot."""
        entry = self._entries.get(id(mobject))
        if entry is None:
            return build_paint(mobject.get_points(), mobject.data["fill_rgba"]).wire()
        if entry.paint_field is None:
            paint = build_paint(entry.source.points, entry.source.rgba)
            entry.paint_field = paint
            self._bytes += paint.nbytes
            while self._bytes > self.max_bytes:
                self._remove(next(iter(self._entries)))
        return entry.paint_field.wire()

    def coverage(self, mobject, vertices, indices, uniforms, source, *, border_vertices=None):
        """Retain complete fill/border geometry independently of fill tessellation."""
        entry = self._entries.get(id(mobject))
        previous = None if entry is None else entry.coverage_geometry
        if source is None:
            if previous is not None:
                self._bytes -= previous.nbytes
                entry.coverage_geometry = None
            return vertices, indices, False
        if (previous is not None and previous.source == source
                and previous.fill_vertices() is vertices and previous.fill_indices() is indices):
            # A source paint/stroke-only edit can preserve all border geometry.
            # Retain its new canonical snapshot, otherwise each following
            # camera update would unnecessarily expand the same source again.
            if previous.source is not source:
                old_bytes = previous.nbytes
                previous.source = source.frozen()
                self._bytes += previous.nbytes - old_bytes
                while self._bytes > self.max_bytes:
                    self._remove(next(iter(self._entries)))
            return previous.vertices, previous.indices, bool(previous.border_vertex_count)
        reused = previous is not None and previous.source == source
        combined, combined_indices, border_count = _combine_border(
            vertices, indices, source, uniforms, mobject.data["fill_rgba"][0],
            previous=previous, border_vertices=border_vertices)
        if not reused:
            self._totals["border_regenerations"] += 1
        if entry is not None:
            old_bytes = entry.nbytes
            frozen_indices = (combined_indices if previous is not None and combined_indices is previous.indices
                              else _readonly(combined_indices))
            geometry = _CoverageGeometry(source.frozen(), _readonly(combined),
                frozen_indices, border_count, weakref.ref(vertices), weakref.ref(indices))
            entry.coverage_geometry = geometry
            self._bytes += entry.nbytes - old_bytes
            while self._bytes > self.max_bytes:
                self._remove(next(iter(self._entries)))
            return geometry.vertices, geometry.indices, bool(border_count)
        return combined, combined_indices, bool(border_count)


def _projection_state(uniforms, resolution, cache):
    """Share validation/float32 packing by exact input values within a frame.

    The scratch map is cleared at each frame boundary. Keys contain values,
    never object revisions or array identities; direct camera edits therefore
    remain visible. Nested matrix inputs use the ordinary uncached path.
    """
    raw_key = None
    if cache is not None:
        try:
            raw_key = (tuple(uniforms["view"]), tuple(uniforms["frame_rescale_factors"]),
                       float(uniforms.get("is_fixed_in_frame", 0)), tuple(resolution))
            cached = cache.get(raw_key)
            if cached is not None:
                return cached
        except TypeError:
            raw_key = None
    view = np.asarray(uniforms["view"], dtype="f4").reshape(16)
    scale = np.asarray(uniforms["frame_rescale_factors"], dtype="f4").reshape(3)
    fixed = np.float32(uniforms.get("is_fixed_in_frame", 0))
    if (not np.isfinite(view).all() or not np.isfinite(scale).all()
            or not 0 <= fixed <= 1 or not np.isfinite(resolution).all()):
        raise UnsupportedPrototype("nonfinite or unsupported camera transform")
    key = (view.tobytes(), scale.tobytes(), fixed.tobytes(), tuple(resolution))
    state = (key, projection_matrix(uniforms))
    if raw_key is not None:
        cache[raw_key] = state
    return state


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
    derivatives = matrix @ basis.swapaxes(-1, -2)
    # |d(n/w)| <= |dn|/min(w) + max(|n|)*|dw|/min(w)^2.
    norms = np.linalg.norm(derivatives, axis=-1)
    row_bounds = (norms[..., :2] / min_w
                  + np.max(abs(projected[:, :2]), axis=0)
                  * norms[..., 2, None] / min_w ** 2)
    pixels_per_unit = np.linalg.norm(row_bounds * np.asarray(resolution) / 2, axis=-1)
    if not np.isfinite(pixels_per_unit).all():
        raise UnsupportedPrototype("unbounded projection error")
    return float(pixels_per_unit) if pixels_per_unit.ndim == 0 else pixels_per_unit


def _batched_projection_errors(entries, projection, resolution):
    """``_MeshGeometry.pixel_error`` for many entries with retained error hulls,
    in one pass: the same bound as ``projection_scale_bound``, stacked."""
    matrix, shift = projection
    hulls = [entry.geometry.error_hull for entry in entries]
    lengths = np.array([len(hull) for hull in hulls])
    starts = np.cumsum(np.r_[0, lengths[:-1]])
    projected = np.concatenate(hulls) @ matrix.T + shift
    w = 1 - projected[:, 2]
    min_w = np.minimum.reduceat(w, starts)
    max_xy = np.maximum.reduceat(np.abs(projected[:, :2]), starts, axis=0)
    bases = np.stack([entry.geometry.error_basis for entry in entries])  # (N, 2, 3, 3)
    derivatives = matrix @ bases.swapaxes(-1, -2)
    norms = np.linalg.norm(derivatives, axis=-1)  # (N, 2, 3)
    with np.errstate(divide="ignore", invalid="ignore"):
        row_bounds = (norms[..., :2] / min_w[:, None, None]
                      + max_xy[:, None, :] * norms[..., 2, None] / min_w[:, None, None] ** 2)
        scales = np.linalg.norm(row_bounds * np.asarray(resolution) / 2, axis=-1)  # (N, 2)
    tolerances = np.array([entry.geometry.local_tolerance for entry in entries])
    residuals = np.array([entry.geometry.fit_residual for entry in entries])
    errors = tolerances * scales[:, 0] + residuals * scales[:, 1]
    # A singular or near-plane projection is the per-entry path's error to raise.
    errors[min_w <= 1e-5] = np.nan
    return errors


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
        contours, attributes=[np.broadcast_to(rgba[0], (len(xy[part]), 4)) for part in ranges],
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
    error_basis = np.zeros((2, 3, 3))
    error_basis[0, :2], error_basis[1] = basis, np.eye(3)
    error_hull = np.concatenate((points, _border_hull(fitted_points, basis, source.border_settings)))
    return _MeshGeometry(vertices, mesh.indices, fitted_points, basis,
                         float(mesh.tolerance), residual, error_hull, error_basis)


def _note_paint_cost(frame, paint):
    """A non-affine paint field is supported with a known interpolation and
    cost limit; it is recorded on the frame, not rejected."""
    if paint is not None and paint[11] == 1:
        message = ("non-affine fill paint uses inverse-distance interpolation "
                   f"(mode=1, node_count={int(paint[7])}, maximum_nodes={MAX_PAINT_SAMPLES}); "
                   "fragment cost grows with node_count")
        if message not in frame.limitations:
            frame.limitations.append(message)


def prepare_triangle_frame(scene, tessellator, *, pixel_tolerance=0.25,
                           diagnostic=False, mesh_cache=None, fill_builder=None,
                           coalesce=True, fill_borders=False, gpu_borders=False,
                           patch_fills=False, net_surfaces=False):
    """Prepare ordered operations for the shared triangle pipelines.

    Supports planar vector fills, existing strokes, surfaces, textured surfaces,
    images and dot clouds. ``fill_borders=True`` adds Manim's variable-width
    border strips to each object's fill operation, preserving its own join,
    partial-path and camera-facing geometry. Per-sample stencil ownership
    paints the complete object once, including translucent overlaps.
    ``gpu_borders=True`` retains curve sources and ordered index recipes;
    the driver expands their vertices on the GPU. The default CPU mode remains
    an explicit diagnostic reference, independent of that compute shader.
    ``patch_fills=True`` (with GPU borders) prepares no fill mesh at all: each
    filled path becomes a patch draw the driver builds from its curve records
    on the GPU (docs/phase_b1_plan.md); the CPU keeps only the planar refusal.
    ``net_surfaces=True`` sends each surface's control net instead of its
    evaluated grid; the driver evaluates it at screen density
    (docs/phase_b2_plan.md).
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
    if gpu_borders and (not fill_borders or fill_builder is not None):
        raise ValueError("GPU borders require the standard fill builder and fill_borders=True")
    if patch_fills and not gpu_borders:
        raise ValueError("patch fills require gpu_borders=True")
    camera.refresh_uniforms()
    frame = TriangleFrame(tuple(camera.draw_fbo.size), tuple(camera.background_rgba),
                          4 if camera.samples else 1, pixel_tolerance=pixel_tolerance)
    cache_before = mesh_cache.begin_frame(tessellator) if mesh_cache is not None else None
    border_cache = (mesh_cache.gpu_border_cache if mesh_cache is not None else BorderRecipeCache()) if gpu_borders else None
    net_cache = (mesh_cache.gpu_net_cache if mesh_cache is not None else NetRecipeCache()) if net_surfaces else None
    if net_cache is not None:
        net_cache.begin_frame()
    if border_cache is not None:
        if mesh_cache is not None:
            border_cache.max_bytes = max(0, mesh_cache.max_bytes - mesh_cache._bytes) if mesh_cache.max_entries else 0
        border_cache.begin_frame()
    camera_uniforms = {key: _jsonable(value) for key, value in camera.uniforms.items()}

    def limitation(message):
        if not diagnostic:
            raise UnsupportedPrototype(message)
        if message not in frame.limitations:
            frame.limitations.append(message)

    # Our historical native camera paints fixed-frame groups last. Phase A
    # shares that policy across native/browser output; Original 2D receives
    # the scene's historical browser z/add order without this partition.
    groups = sorted(scene.render_groups, key=lambda group: group.is_fixed_in_frame())
    families, previous_key = [], None
    for group in groups:
        key = getattr(group, "_triangle_batch_key", None)
        members = group.family_members_with_points()
        if families and key is not None and key == previous_key:
            # The cutover partitioned before Scene batching. Preserve its
            # family z-sort when an intervening overlay moves out of the way.
            families[-1].extend(members)
        else:
            families.append(list(members))
        previous_key = key
    records = [(sm, {**camera_uniforms,
                     **{key: _jsonable(value) for key, value in sm.uniforms.items()}})
               for family in families
               for sm in sorted(family, key=lambda obj: obj.z_index)
               if not isinstance(sm, CameraFrame)]
    if mesh_cache is not None:
        mesh_cache.bound_errors(records, frame.resolution)
    borders = (_prepare_border_geometry(records, mesh_cache)
               if fill_borders and fill_builder is None and not gpu_borders else {})
    for sm, uniforms in records:
        depth_suffix = "_depth" if sm.depth_test else ""
        if isinstance(sm, (DotCloud, Surface, ImageMobject)):
            pipeline = ("dot" if isinstance(sm, DotCloud) else
                        "image" if isinstance(sm, ImageMobject) else
                        "texsurface" if isinstance(sm, TexturedSurface) else "surface")
            if (net_cache is not None and pipeline in ("surface", "texsurface")
                    and getattr(sm, "net", False) and sm.has_points()):
                entry = net_cache.source(sm, revision=sm.revision,
                                         pixels_per_unit=pixels_per_unit(camera_uniforms, frame.resolution),
                                         frame_scale=uniforms["frame_scale"])
                patches = ((entry.nu - 1) // 2) * ((entry.nv - 1) // 2)
                frame.draws.append(TriangleDraw(
                    pipeline + depth_suffix, np.zeros(0, dtype=sm.data.dtype), uniforms,
                    count=patches * indices_per_patch(entry.capacity), instances=1,
                    textures=_texture_refs(sm, frame.texture_data) if pipeline == "texsurface" else {},
                    net=entry.net, net_shape=(entry.nu, entry.nv, entry.channels),
                    net_capacity=entry.capacity, net_density=entry.density))
                frame.source_bytes += entry.net.nbytes
                continue
            data = np.ascontiguousarray(sm.get_shader_data()).copy()
            if not len(data):
                continue
            frame.draws.append(TriangleDraw(
                pipeline + depth_suffix, data, uniforms,
                count=4 if pipeline == "dot" else len(data),
                instances=len(data) if pipeline == "dot" else 1,
                textures=_texture_refs(sm, frame.texture_data) if pipeline in ("image", "texsurface") else {}))
            frame.source_bytes += data.nbytes
            continue
        if not isinstance(sm, VMobject):
            raise UnsupportedPrototype(f"{type(sm).__name__} awaits primitive integration")
        frame.source_bytes += sm.data.nbytes
        fill = None
        border_curves = None
        border_source, border_vertices = borders.get(id(sm), (None, None))
        has_fill, uniform_fill, has_border, opaque_alpha, has_stroke = (
            mesh_cache.classify(sm) if mesh_cache is not None else classify_source(sm))
        if has_fill and patch_fills:
            material = not uniform_fill or bool(np.any(uniforms.get("shading", (0, 0, 0))))
            curves = border_cache.source(sm, uniforms, revision=sm.revision, every_curve=True)
            if len(curves):
                record = border_cache.fill_record(sm, lambda: planar_coordinates(sm.get_points()))
                paint = (border_cache.paint(sm, lambda: build_paint(sm.get_points(), sm.data["fill_rgba"]).wire())
                         if material else None)
                _note_paint_cost(frame, paint)
                bordered = bool(has_border and np.any(curves[:, 37]))
                capacity = border_cache.capacity(sm)
                # Before assembly the layout's third field says whether the
                # object may share a stencil count with its neighbours: an
                # opaque, uniformly coloured, unshaded painter object whose
                # count never changes sign (the record's winding sign).
                shareable = int(not material and opaque_alpha and not sm.depth_test)
                layout = ((len(curves), int(bordered), shareable),)
                fill = TriangleDraw("patch" + depth_suffix, _NO_VERTICES, uniforms, None, patch_draw_count(layout, capacity),
                                    paint=paint, border_sources=curves, border_capacity=capacity,
                                    fill_objects=record, patch_layout=layout)
        elif has_fill:
            material = not uniform_fill or bool(np.any(uniforms.get("shading", (0, 0, 0))))
            if material and fill_builder is not None:
                limitation("per-point fill paint uses endpoint interpolation; interior parity unproved")
            if has_border:
                if not fill_borders:
                    limitation("fill-border coverage is disabled for this triangle frame")
                else:
                    if gpu_borders:
                        border_curves = border_cache.source(sm, uniforms, revision=sm.revision)
                    else:
                        border_source = borders[id(sm)][0] if id(sm) in borders else BorderSource.read(sm, uniforms)
            if fill_builder is not None:
                fill = fill_builder(sm, uniforms, frame.resolution, pixel_tolerance)
            else:
                mesh_function = mesh_cache.mesh if mesh_cache is not None else mesh_mobject
                vertices, indices = mesh_function(sm, tessellator, uniforms,
                                                  frame.resolution, pixel_tolerance)
                # Surface shading has no AA/alpha multiplier. For a uniform,
                # opaque, unshaded painter object, every surviving fragment
                # writes the same color, so its fill/border overlap needs no
                # stencil ownership. Check the smaller fill mesh as well as
                # the exact source style; border composition explicitly assigns
                # this source RGBA to every border vertex. Source order remains
                # unchanged when these operations coalesce, even if different
                # objects have different colors or overlap one another.
                opaque_painter = (not material and not sm.depth_test and opaque_alpha
                                  and (mesh_cache.uniform_vertex_color(sm) if mesh_cache is not None
                                       else bool(np.all(vertices["rgba"] == sm.data["fill_rgba"][0]))))
                coverage = False
                if gpu_borders:
                    if mesh_cache is not None:
                        mesh_cache.coverage(sm, vertices, indices, uniforms, None)
                    coverage = border_curves is not None and len(border_curves) > 0
                elif mesh_cache is not None:
                    vertices, indices, coverage = mesh_cache.coverage(
                        sm, vertices, indices, uniforms, border_source, border_vertices=border_vertices)
                elif border_source is not None:
                    vertices, indices, border_count = _combine_border(
                        vertices, indices, border_source, uniforms, sm.data["fill_rgba"][0],
                        border_vertices=border_vertices)
                    coverage = bool(border_count)
                if len(indices) or (border_curves is not None and len(border_curves)):
                    paint = ((mesh_cache.paint(sm) if mesh_cache is not None else
                              build_paint(sm.get_points(), sm.data["fill_rgba"]).wire())
                             if material else None)
                    _note_paint_cost(frame, paint)
                    fill = TriangleDraw(("paint" if material else "surface") + depth_suffix,
                                        vertices, uniforms, indices, len(indices), paint=paint,
                                        coverage=coverage and not opaque_painter,
                                        border_sources=border_curves if coverage else None,
                                        border_capacity=(border_cache.capacity(sm)
                                                         if gpu_borders and coverage
                                                         else MAX_VERTICES_PER_CURVE))
        stroke = None
        if has_stroke:
            data = np.ascontiguousarray(sm.get_shader_data()).copy()
            stroke = TriangleDraw("stroke" + depth_suffix, data, uniforms,
                                  count=_stroke_verts(data, uniforms["frame_scale"]),
                                  instances=len(data) // 3)
        ordered = (stroke, fill) if sm.stroke_behind else (fill, stroke)
        frame.draws.extend(draw for draw in ordered if draw is not None)
    if mesh_cache is not None:
        frame.mesh_cache_stats = mesh_cache.finish_frame(cache_before)
    if net_cache is not None:
        net_cache.finish_frame()
        frame.mesh_cache_stats.update(gpu_net_updates=net_cache.updates,
                                      retained_gpu_net_bytes=net_cache.nbytes)
    if coalesce:
        frame.draws = coalesce_draws(frame.draws, border_cache=border_cache)
    elif gpu_borders:
        frame.draws = [coalesce_draws([draw], border_cache=border_cache)[0] for draw in frame.draws]
    if border_cache is not None:
        if mesh_cache is not None:
            border_cache.max_bytes = max(0, mesh_cache.max_bytes - mesh_cache._bytes) if mesh_cache.max_entries else 0
        border_cache.finish_frame()
        frame.mesh_cache_stats.update(gpu_border_source_updates=border_cache.source_updates,
                                      gpu_border_assemblies=border_cache.assemblies,
                                      gpu_border_retained_bytes=border_cache.nbytes,
                                      retained_gpu_recipe_bytes=border_cache.nbytes,
                                      retained_fill_cache_bytes=0 if mesh_cache is None else mesh_cache._bytes,
                                      retained_bytes=(0 if mesh_cache is None else mesh_cache._bytes) + border_cache.nbytes)
    return frame

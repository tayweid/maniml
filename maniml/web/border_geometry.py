"""Derived hard-coverage fill borders using Manim's stroke geometry rules.

The current WGSL/GL stroke stages define variable widths, joints, subdivision
and camera-facing orientation. This module emits the same triangle strips at
the geometric half width, without the old smooth AA band. The triangles may
overlap: render them with the fill using per-sample stencil ownership so
each translucent object paints a sample once. They are world-space drawing data and never replace source points.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np

from maniml.mobject.types.vectorized_mobject import VMobject
from maniml.web.triangle_geometry import TessellationError, TessellationLimitError


MAX_BORDER_TRIANGLES = 262_144 // 3
_REQUIRED = {"point", "fill_rgba", "fill_border_width", "joint_angle", "base_normal"}
_BORDER_DTYPE = np.dtype([("point", "f4", 3), ("fill_rgba", "f4", 4),
                         ("fill_border_width", "f4", 1), ("joint_angle", "f4", 1),
                         ("base_normal", "f4", 3)])
_STANDARD_SOURCE_METHODS = tuple((name, getattr(VMobject, name)) for name in (
    "get_shader_data", "get_shader_vert_indices", "get_outer_vert_indices",
    "get_num_curves", "get_num_points", "get_joint_angles", "get_unit_normal"))


def _same_bytes(left, right):
    if left is right:
        return True
    if left.dtype != right.dtype or left.shape != right.shape:
        return False
    if not left.flags.c_contiguous or not right.flags.c_contiguous:
        return left.tobytes() == right.tobytes()
    return np.array_equal(left.view("u1"), right.view("u1"))


def _readonly(array):
    # Already-frozen canonical arrays are shared across camera-only updates.
    if not array.flags.writeable and isinstance(array.base, np.ndarray) and isinstance(array.base.base, bytes):
        return array
    return np.frombuffer(array.tobytes(), dtype=array.dtype).reshape(array.shape)


@dataclass(eq=False)
class BorderSource:
    """Geometry-only border snapshot; ordinary paint changes do not rebuild it."""

    data: np.ndarray
    counts: np.ndarray
    key: tuple
    flat: bool
    triangle_count: int
    density: np.ndarray
    active: np.ndarray
    raw_data: np.ndarray
    raw_indices: np.ndarray
    cacheable: bool
    frame_scale: float

    @classmethod
    def read(cls, mobject, uniforms, *, previous=None):
        """Reuse expanded curves only after exact canonical-data comparison.

        No revision counter substitutes for reading public arrays. Custom
        source getters may depend on arbitrary state, so their output is read
        every time. Standard getters also honor dirty normals/joints and direct
        edits of the derived expansion indices before taking a fresh snapshot.
        """
        cacheable = (mobject.data.flags.c_contiguous
                     and all(getattr(getattr(mobject, name), "__func__", None) is method
                             for name, method in _STANDARD_SOURCE_METHODS))
        reuse = (cacheable and previous is not None and previous.cacheable
                 and not mobject.needs_new_joint_angles and not mobject.needs_new_unit_normal
                 and _same_bytes(mobject.data, previous.raw_data)
                 and _same_bytes(mobject.outer_vert_indices, previous.raw_indices))
        if reuse:
            data, density, active = previous.data, previous.density, previous.active
            raw_data, raw_indices = previous.raw_data, previous.raw_indices
        else:
            if mobject.needs_new_unit_normal:
                mobject.get_unit_normal()
            expanded = mobject.get_shader_data()
            data = np.empty(len(expanded), dtype=_BORDER_DTYPE)
            for name in _REQUIRED - {"fill_rgba"}:
                data[name] = expanded[name]
            # Only wholly invisible segments change the geometry. Leave RGBA
            # interpolation to the independent paint field.
            active = np.any(expanded["fill_rgba"][:, 3].reshape(-1, 3) != 0, axis=1)
            data["fill_rgba"] = 1
            data["fill_rgba"][:, 3] = np.repeat(active, 3)
            points = data["point"].reshape(-1, 3, 3)
            density = _border_density(points)
            active &= np.any(points[:, 0] != points[:, 1], axis=1)
            active &= np.any(data["fill_border_width"].reshape(-1, 3) != 0, axis=1)
            raw_data, raw_indices = _readonly(mobject.data), _readonly(mobject.outer_vert_indices)
        frame_scale = float(uniforms["frame_scale"])
        if reuse and frame_scale == previous.frame_scale:
            counts, triangle_count = previous.counts, previous.triangle_count
        else:
            counts = _density_counts(density, frame_scale)
            triangle_count = int(np.sum(2 * (counts[active] - 1)))
        if triangle_count > MAX_BORDER_TRIANGLES:
            raise TessellationLimitError(f"border exceeds {MAX_BORDER_TRIANGLES} triangles")
        flat = bool(uniforms.get("flat_stroke", 1)) or bool(uniforms.get("is_fixed_in_frame", 0))
        scale = float(uniforms.get("scale_stroke_with_zoom", 1))
        factor = .01 * (float(uniforms["frame_scale"]) * (1 - scale) + scale)
        key = (factor, float(uniforms.get("joint_type", 1)), flat)
        if not flat:
            key += (tuple(uniforms["camera_position"]),)
        if reuse and frame_scale == previous.frame_scale and key == previous.key:
            return previous
        return cls(data, counts, key, flat, triangle_count, density, active,
                   raw_data, raw_indices, cacheable, frame_scale)

    def arrays(self):
        return (self.data, self.counts, self.density, self.active, self.raw_data, self.raw_indices)

    def __eq__(self, other):
        return (isinstance(other, BorderSource) and self.key == other.key
                and _same_bytes(self.data, other.data) and _same_bytes(self.counts, other.counts))

    def frozen(self):
        return replace(self, **{name: _readonly(getattr(self, name)) for name in
                       ("data", "counts", "density", "active", "raw_data", "raw_indices")})


def _smoothstep(left, right, value):
    t = np.clip((value - left) / (right - left), 0, 1)
    return t * t * (3 - 2 * t)


def _normalize_rows(vectors, fallback=None):
    lengths = np.linalg.norm(vectors, axis=-1, keepdims=True)
    result = vectors / np.where(lengths > 0, lengths, 1)
    if fallback is not None:
        result = np.where(lengths > 0, result, _normalize_rows(fallback))
    return result


def border_step_counts(points, frame_scale):
    """WGSL subdivision policy, useful for camera cache invalidation.

    Source coordinates and arithmetic use float32, as the shader does. Device
    arithmetic can still differ at an exact threshold by a rounding ulp.
    """
    return _density_counts(_border_density(points), frame_scale)


def _border_density(points):
    points = np.asarray(points, dtype="f4")
    if points.ndim != 3 or points.shape[1:] != (3, 3):
        raise ValueError("curve points must have shape (N, 3, 3)")
    if not np.isfinite(points).all():
        raise ValueError("curve points must be finite float32 values")
    area = .5 * np.linalg.norm(np.cross(points[:, 1] - points[:, 0],
                                       points[:, 2] - points[:, 0]), axis=1)
    return 100 * np.sqrt(area)


def _density_counts(density, frame_scale):
    frame_scale = float(frame_scale)
    if not np.isfinite(frame_scale) or frame_scale <= 0:
        raise ValueError("frame_scale must be finite and positive")
    frame_scale = np.float32(frame_scale)
    if not np.isfinite(frame_scale) or frame_scale <= 0:
        raise ValueError("frame_scale must be a finite positive float32 value")
    # WGSL round chooses the nearest even integer at ties (§17.5.52).
    # Apply the cap before integer conversion, including very large curves.
    counts = np.minimum(2 + np.rint(density / frame_scale), 32)
    return counts.astype(np.int32)


def emit_border_triangles(shader_data, uniforms, *, normal_offset=True, return_normals=False,
                          step_counts=None):
    """Return finite (N, 3, 3) world-space border triangles.

    Input is the existing expanded three-record-per-quadratic shader data.
    Endpoint widths interpolate linearly; handle widths only participate in
    the shader's all-zero gate. Sentinel curves with p0==p1 and fully invisible
    source segments emit nothing. Open/partially revealed paths stay open: this
    function does not invent an implicit closing stroke or join.

    Manim joint types 0/1/2/3 are no_joint/auto/bevel/miter. Camera-facing borders
    use the point-to-camera normal, except fixed-in-frame sources remain flat,
    exactly as in the shader. Their geometry generally leaves the fill plane;
    per-sample stencil ownership preserves their actual world-space depth.
    ``return_normals=True`` also returns each emitted vertex's lighting normal.

    The optional default normal offset reproduces the shader's 0.0001 offset.
    Antialiasing is applied to the resolved union by the shared renderer. Zero
    tangents use their limiting segment direction to avoid NaN output. Negative
    widths are invalid source style; they are rejected instead of producing
    inverted hard coverage unrelated to the shader's alpha test.
    """
    data = np.asarray(shader_data)
    if data.ndim != 1 or data.dtype.names is None or not _REQUIRED.issubset(data.dtype.names):
        raise ValueError("border input must use the expanded VMobject shader layout")
    if len(data) % 3:
        raise ValueError("border input must contain three records per quadratic")
    for field in _REQUIRED:
        if not np.isfinite(data[field]).all():
            raise ValueError("border source data must be finite")
    widths = np.asarray(data["fill_border_width"], dtype=float).reshape(-1, 3)
    if np.any(widths < 0):
        raise ValueError("fill border widths must be nonnegative")
    points = np.asarray(data["point"], dtype=float).reshape(-1, 3, 3)
    if step_counts is None:
        counts = border_step_counts(points, uniforms["frame_scale"])
    else:
        counts = np.asarray(step_counts)
        if (counts.shape != (len(points),) or not np.issubdtype(counts.dtype, np.integer)
                or np.any((counts < 2) | (counts > 32))):
            raise ValueError("step_counts must contain one integer in [2, 32] per curve")
    scale = float(uniforms.get("scale_stroke_with_zoom", 1))
    fixed = float(uniforms.get("is_fixed_in_frame", 0))
    flat = bool(uniforms.get("flat_stroke", 1)) or bool(fixed)
    joint = int(uniforms.get("joint_type", 1))
    camera = np.asarray(uniforms["camera_position"], dtype=float)
    if not np.isfinite([scale, fixed]).all() or camera.shape != (3,) or not np.isfinite(camera).all():
        raise ValueError("border camera/style uniforms must be finite")
    if joint not in (0, 1, 2, 3):
        raise ValueError("unknown Manim border joint type")
    factor = .01 * (float(uniforms["frame_scale"]) * (1 - scale) + scale)
    if not np.isfinite(factor) or factor < 0:
        raise ValueError("border width scale must be finite and nonnegative")
    rgba = np.asarray(data["fill_rgba"], dtype=float).reshape(-1, 3, 4)
    normals = np.asarray(data["base_normal"], dtype=float).reshape(-1, 3, 3)[:, 1]
    angles = np.asarray(data["joint_angle"], dtype=float).reshape(-1, 3)
    active = (np.any(points[:, 0] != points[:, 1], axis=1)
              & np.any(widths != 0, axis=1) & np.any(rgba[:, :, 3] != 0, axis=1))
    triangle_count = int(np.sum(2 * (counts[active] - 1)))
    if triangle_count > MAX_BORDER_TRIANGLES:
        raise TessellationLimitError(f"border exceeds {MAX_BORDER_TRIANGLES} triangles")
    if not triangle_count:
        empty = np.empty((0, 3, 3), dtype=float)
        return (empty, empty.copy()) if return_normals else empty
    # Flatten all curve samples once. Every subsequent vector operation covers
    # the whole object; there is no Python iteration per curve or sample.
    active_indices = np.flatnonzero(active)
    active_counts = counts[active]
    indices = np.repeat(active_indices, active_counts)
    starts = np.cumsum(np.r_[0, active_counts[:-1]])
    steps = np.arange(len(indices)) - np.repeat(starts, active_counts)
    last = counts[indices] - 1
    t = steps / last
    p0, p1, p2 = (points[indices, i] for i in range(3))
    c1, c2 = 2 * (p1 - p0), p0 - 2 * p1 + p2
    position = p0 + c1 * t[:, None] + c2 * t[:, None] * t[:, None]
    tangent = c1 + 2 * c2 * t[:, None]
    chord = p2 - p0
    limiting = np.where(np.any(chord != 0, axis=1)[:, None], chord, c1)
    tangent = np.where(np.any(tangent != 0, axis=1)[:, None], tangent, limiting)
    source_normal = normals[indices]
    normal = source_normal if flat else _normalize_rows(camera - position, source_normal)
    projected_tangent = tangent if flat else tangent - np.sum(tangent * normal, axis=1)[:, None] * normal
    unit_tangent = _normalize_rows(projected_tangent)
    fallback = np.cross(source_normal, tangent)
    direction = _normalize_rows(np.cross(normal, unit_tangent), fallback)
    angle = np.where(steps == 0, -angles[indices, 0],
                     np.where(steps == last, angles[indices, 2], 0.))
    alignment = np.abs(np.sum(_normalize_rows(tangent) * normal, axis=1))
    aligned = (angle != 0) & (alignment > .97)
    if np.any(aligned):
        perpendicular = _normalize_rows(fallback[aligned])
        old = direction[aligned]
        projected = old - np.sum(old * perpendicular, axis=1)[:, None] * perpendicular
        blend = _smoothstep(.97, 1., alignment[aligned])[:, None]
        direction[aligned] = (1 - blend) * old + blend * projected
    if joint != 0:
        cosine, sine = np.cos(angle), np.sin(angle)
        corner = ((steps == 0) | (steps == last)) & (np.abs(cosine) <= .999)
        if not flat and np.any(corner):
            selected_normal, selected_tangent = normal[corner], unit_tangent[corner]
            direction[corner] = _normalize_rows(np.cross(selected_normal, selected_tangent), fallback[corner])
            adjacent = cosine[corner, None] * tangent[corner] + sine[corner, None] * fallback[corner]
            adjacent -= np.sum(adjacent * selected_normal, axis=1)[:, None] * selected_normal
            cosine[corner] = np.clip(np.sum(selected_tangent * _normalize_rows(adjacent), axis=1), -1, 1)
            sine[corner] = (np.sqrt(np.maximum(0., 1 - cosine[corner] ** 2)) * np.sign(angle[corner])
                            * np.sign(np.sum(selected_normal * source_normal[corner], axis=1)))
            corner &= np.abs(sine) >= 1e-12
        factor_miter = (0. if joint == 2 else 1. if joint == 3
                        else _smoothstep(-.8, -.9, cosine[corner]))
        shift = (cosine[corner] - 1 + 2 * factor_miter) / sine[corner]
        direction[corner] += shift[:, None] * unit_tangent[corner]
    half_width = .5 * factor * ((1 - t) * widths[indices, 0] + t * widths[indices, 2])
    center = position + (.0001 * normal if normal_offset else 0)
    strip = center[:, None, :] + np.array([-1., 1.])[None, :, None] * half_width[:, None, None] * direction[:, None, :]
    # Every adjacent pair within a curve produces the original two triangles,
    # in the same order used by the GPU's triangle strip.
    left = np.flatnonzero(steps < last)
    corners = np.column_stack([2 * left, 2 * left + 1, 2 * left + 2,
                               2 * left + 1, 2 * left + 2, 2 * left + 3]).reshape(-1, 3)
    output = strip.reshape(-1, 3)[corners]
    if not np.isfinite(output).all():
        raise TessellationError("border geometry produced nonfinite positions")
    if return_normals:
        output_normals = np.repeat(normal, 2, axis=0)[corners]
        return output, output_normals
    return output

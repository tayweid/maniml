"""Conservative screen footprints for the winding-fill composite.

The fill shader draws control/fan triangles, not just a curve's anchors.
Its optional border uses the stroke shader and can extend farther still.
These bounds size the temporary fill image and its composite; drawing
order and coverage stay with the existing shaders. An unsupported or
unbounded case returns None.
"""

from __future__ import annotations

import math

import numpy as np


_F32_EPS = float(np.finfo(np.float32).eps)
_CORNERS = np.array([
    [0, 0, 0], [0, 0, 1], [0, 1, 0], [0, 1, 1],
    [1, 0, 0], [1, 0, 1], [1, 1, 0], [1, 1, 1],
], dtype=bool)


@np.errstate(all="ignore")
def fill_composite_rects(records, camera_uniforms, resolution):
    """Compute a frame's bounds together, without changing its batches.

    Most fills have no extra border. Reducing and projecting those in
    arrays avoids paying for many tiny NumPy calls per drawing batch.
    Border geometry retains the per-batch conservative expansion below.
    Nothing is cached across frames, including camera or object uniforms.
    """
    result = [None] * len(records)
    simple = []
    for index, record in enumerate(records):
        if record["kind"] != "vmobject" or record["fill_mode"] != "winding":
            continue
        data = record["data"]
        uniforms = {**camera_uniforms, **record["uniforms"]}
        if not len(data) or len(data) % 3 or np.any(data["fill_border_width"]):
            result[index] = fill_composite_rect(data, uniforms, resolution)
        else:
            simple.append((index, data, uniforms))
    if not simple:
        return result

    counts = np.array([len(data) for _, data, _ in simple])
    starts = np.r_[0, counts.cumsum()[:-1]]
    points = np.concatenate([data["point"] for _, data, _ in simple])
    bases = np.concatenate([data["base_normal"][0::3] for _, data, _ in simple])
    alpha = np.concatenate([data["fill_rgba"][:, 3] for _, data, _ in simple])
    triples = points.reshape(-1, 3, 3)
    active = np.any(alpha.reshape(-1, 3) != 0, axis=1)
    active &= np.any(triples[:, 0] != triples[:, 1], axis=1)
    # Include all control/fan points in each box, even skipped triangles:
    # that can only enlarge its footprint. Still recognize entirely empty
    # batches so stroke-only content pays no fill passes.
    has_fill = np.logical_or.reduceat(active, starts // 3)
    lo = np.minimum(np.minimum.reduceat(points, starts, axis=0),
                    np.minimum.reduceat(bases, starts // 3, axis=0)).astype(float)
    hi = np.maximum(np.maximum.reduceat(points, starts, axis=0),
                    np.maximum.reduceat(bases, starts // 3, axis=0)).astype(float)
    world_error = 64 * _F32_EPS * (1 + np.maximum(abs(lo), abs(hi)))
    rectangles = _project_boxes(
        lo - world_error, hi + world_error,
        [uniforms for _, _, uniforms in simple], resolution)
    for (index, _, _), rect, filled in zip(simple, rectangles, has_fill):
        result[index] = rect if filled else [0, 0, 0, 0]
    return result


@np.errstate(all="ignore")
def fill_composite_rect(data, uniforms, resolution):
    """Return [x, y, width, height] in top-down output pixels.

    None means use the full frame; zero dimensions mean no fill can
    contribute. Inputs are the expanded VMobject shader vertices and
    the same merged camera/mobject uniforms the renderer packs. Compute
    this even for cached geometry: camera, zoom, AA, and fixed-in-frame
    uniforms can all change without changing the vertex buffer.
    """
    if not len(data):
        return [0, 0, 0, 0]
    if len(data) % 3:
        return None
    # Match the shader's per-instance early exit. A transparent batch
    # need not clear a temporary image or run a composite at all.
    rgba = data["fill_rgba"].reshape(-1, 3, 4)
    points = data["point"].reshape(-1, 3, 3)
    active = np.any(rgba[:, :, 3] != 0, axis=1)
    active &= np.any(points[:, 0] != points[:, 1], axis=1)
    if not active.any():
        return [0, 0, 0, 0]
    points = points[active].reshape(-1, 3)
    bases = data["base_normal"][0::3][active]
    lo = np.minimum(points.min(axis=0), bases.min(axis=0)).astype(float)
    hi = np.maximum(points.max(axis=0), bases.max(axis=0)).astype(float)
    if not (np.isfinite(lo).all() and np.isfinite(hi).all()):
        return None

    try:
        fixed = float(np.float32(uniforms.get("is_fixed_in_frame", 0.0)))
    except (KeyError, TypeError, ValueError, OverflowError):
        return None
    reach = _border_reach(data, active, uniforms, fixed)
    if reach is None:
        return None
    # Covers float32 evaluation of quadratic points (the shader's
    # polynomial can round outside the exact control-point hull).
    world_error = 64 * _F32_EPS * (1 + np.maximum(abs(lo), abs(hi)) + reach)
    lo -= reach + world_error
    hi += reach + world_error
    return _project_boxes(lo[None, :], hi[None, :], [uniforms], resolution)[0]


def _project_boxes(lo, hi, uniforms, resolution):
    """Project boxes together with each batch's exact uniform values."""
    count = len(uniforms)
    try:
        # Uniforms are uploaded as float32. Use those same values for
        # the CPU projection, doing the error-bound arithmetic in float64.
        view = np.asarray([u["view"] for u in uniforms], dtype=np.float32)
        view = view.reshape(count, 4, 4).transpose(0, 2, 1).astype(float)
        rescale = np.asarray([u["frame_rescale_factors"] for u in uniforms],
                             dtype=np.float32).reshape(count, 3).astype(float)
        fixed = np.asarray([u.get("is_fixed_in_frame", 0.0) for u in uniforms],
                           dtype=np.float32).reshape(count, 1).astype(float)
        width, height = map(int, resolution)
    except (KeyError, TypeError, ValueError, OverflowError):
        return [None] * count
    if width <= 0 or height <= 0:
        return [None] * count
    valid = np.isfinite(view).all(axis=(1, 2)) & np.isfinite(rescale).all(axis=1)
    valid &= ((fixed >= 0) & (fixed <= 1)).all(axis=1)
    # The shader mixes the ordinary view transform with identity for
    # fixed-in-frame transitions, rescales xyz, then sets w = 1-z.
    # A linear-fractional projection reaches its extrema at box corners
    # provided w is strictly positive throughout the box.
    corners = np.where(_CORNERS[None, :, :], hi[:, None, :], lo[:, None, :])
    matrix = ((1 - fixed[:, :, None]) * view[:, :3, :3]
              + fixed[:, :, None] * np.eye(3))
    shift = (1 - fixed) * view[:, :3, 3]
    projected = ((corners @ matrix.transpose(0, 2, 1) + shift[:, None, :])
                 * rescale[:, None, :])
    w = 1 - projected[:, :, 2]
    # Bound the shader's float32 matrix/mix/projection rounding. Use an
    # absolute sum, so camera translations that almost cancel points
    # still get their correct error allowance.
    magnitude = np.maximum(abs(lo), abs(hi))
    error = 32 * _F32_EPS * (
        (np.einsum("nij,nj->ni", abs(view[:, :3, :3]), magnitude)
         + abs(view[:, :3, 3])) * (1 - fixed)
        + fixed * magnitude + 1
    ) * abs(rescale)
    min_w = w.min(axis=1)
    valid &= np.isfinite(projected).all(axis=(1, 2))
    valid &= min_w > error[:, 2] + 1e-6
    ndc = projected[:, :, :2] / w[:, :, None]
    error_xy = ((error[:, :2] + abs(ndc).max(axis=1) * error[:, 2, None])
                / (min_w - error[:, 2])[:, None])
    lower = ndc.min(axis=1) - error_xy
    upper = ndc.max(axis=1) + error_xy

    # Two pixels include subpixel rasterization, MSAA sample positions,
    # and the composite's linear texture filtering footprint.
    x0 = np.clip(np.floor((lower[:, 0] + 1) * width / 2) - 2, 0, width)
    x1 = np.clip(np.ceil((upper[:, 0] + 1) * width / 2) + 2, 0, width)
    y0 = np.clip(np.floor((1 - upper[:, 1]) * height / 2) - 2, 0, height)
    y1 = np.clip(np.ceil((1 - lower[:, 1]) * height / 2) + 2, 0, height)
    rectangles = np.column_stack((x0, y0, x1 - x0, y1 - y0)).astype(int).tolist()
    return [rect if ok else None for rect, ok in zip(rectangles, valid)]


def _border_reach(data, active, uniforms, fixed):
    """Bound stroke.wgsl's fill-border vertex offset in world units."""
    widths = data["fill_border_width"].reshape(-1, 3)[active]
    if not np.any(widths):
        return 0.0  # The border shader skips zero-width instances.
    # Non-flat strokes derive their joint directions from a per-point
    # camera vector. Leave that path unchanged until it has its own bound.
    if not uniforms.get("flat_stroke", 0.0) and not fixed:
        return None
    normals = data["base_normal"][1::3][active]
    norms = np.linalg.norm(normals, axis=1)
    if (not np.isfinite(widths).all() or not np.isfinite(norms).all()
            or np.any(abs(norms - 1) > 1e-5)):
        return None
    try:
        scale = float(np.float32(uniforms.get("frame_scale", 1.0)))
        zoom = float(np.float32(uniforms.get("scale_stroke_with_zoom", 1.0)))
        aa = float(np.float32(uniforms.get("anti_alias_width", 1.5)))
        pixel_size = float(np.float32(uniforms.get("pixel_size", 1.0)))
        joint = int(uniforms.get("joint_type", 1))
    except (TypeError, ValueError, OverflowError):
        return None
    if not all(map(math.isfinite, (scale, zoom, aa, pixel_size))):
        return None
    width_factor = 0.01 * ((1 - zoom) * scale + zoom)
    half_width = 0.5 * (float(abs(widths).max()) * abs(width_factor)
                        + max(aa * pixel_size, 1e-8))

    step_norm = 1.0
    if joint != 0:
        angles = data["joint_angle"].reshape(-1, 3)[active][:, (0, 2)].astype(float)
        if not np.isfinite(angles).all() or np.any(abs(angles) > math.pi):
            return None
        cosines = abs(np.cos(angles))
        # step_to_corner adds shift * unit_tangent to a vector of length
        # at most one. Every join has |shift| <= (1+|cos|)/|sin|.
        # WGSL permits absolute sin/cos errors of 2^-11 on [-pi, pi],
        # so both the .999 bypass branch and the denominator need that
        # allowance (not just float32 arithmetic epsilon).
        # https://www.w3.org/TR/WGSL/#floating-point-accuracy
        trig_error = 2 ** -11 + 4 * _F32_EPS
        threshold = float(np.float32(0.999))
        joining = cosines <= threshold + trig_error
        if joining.any():
            cosine = float(cosines[joining].max())
            min_sine = math.sqrt(1 - cosine * cosine) - trig_error
            step_norm += (1 + min(cosine + trig_error, threshold)) / min_sine
    # Includes the shader's .0001 normal offset and float32 width/join
    # rounding. Normals were checked above, so their tiny deviation is
    # covered by this allowance too.
    return half_width * step_norm * 1.001 + 0.000101

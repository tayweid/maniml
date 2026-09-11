"""Wire encoding for ordered, CPU-generated drawing operations.

Source control points remain owned by mobjects. This serializes derived vertex
and index buffers, with draw order explicit and no fill/stroke regrouping.
The consumer retains only the current frame's geometry; the sender uses the
same retention rule so a returning object is resent after it was retired.
"""

import hashlib
import json
import struct

import numpy as np

from maniml.web.geometry import (
    GEOMETRY_FORMAT_VERSION, GEOMETRY_MESSAGE_TYPE, _jsonable, _TEXTURE_BY_HASH,
)
from maniml.web.fill_paint import MAX_PAINT_SAMPLES, PAINT_HASH_PREFIX
from maniml.web.gpu_border_geometry import (
    CURVE_WORDS, MAX_VERTICES_PER_CURVE, indices_per_curve, patch_draw_count,
    validate_capacity, validate_layout, validate_objects, validate_patch_layout,
)


PIPELINE_STRIDES = {"surface": 40, "paint": 40, "stroke": 68, "dot": 32,
                    "image": 24, "texsurface": 36, "patch": 40}


def _immutable(array):
    """Only bytes-backed views are safe: a read-only owned ndarray can thaw."""
    if array is None:
        return True
    while isinstance(array, np.ndarray):
        if array.flags.writeable:
            return False
        array = array.base
    return isinstance(array, bytes)


def _paint_payload(value, previous, retained):
    """Validate actual float32 paint; memoize only immutable coefficient bytes."""
    paint = np.asarray(value)
    if (paint.ndim != 1 or len(paint) < 24 or (len(paint) - 24) % 8
            or len(paint) > 24 + 8 * MAX_PAINT_SAMPLES):
        raise ValueError("invalid generated paint coefficients")
    if paint.dtype != np.dtype("<f4") or not paint.flags.c_contiguous:
        paint = np.ascontiguousarray(paint, dtype="<f4")
    payload = retained.get(id(paint))
    if payload is None:
        payload = previous.get(id(paint))
    if payload is not None and payload[0] is paint:
        content_hash = payload[1]
    else:
        nodes = (len(paint) - 24) // 8
        if (not np.isfinite(paint).all() or paint[3] <= 0 or paint[7] != nodes
                or paint[11] not in (0, 1) or (paint[11] == 1 and nodes == 0)):
            raise ValueError("invalid generated paint coefficients")
        digest = hashlib.blake2b(digest_size=16)
        digest.update(PAINT_HASH_PREFIX)
        digest.update(memoryview(paint).cast("B"))
        content_hash = digest.hexdigest()
    if _immutable(paint):
        retained[id(paint)] = (paint, content_hash)
    return content_hash, paint


def _border_payload(value, previous, retained):
    curves = np.asarray(value)
    if curves.ndim != 2 or curves.shape[1] != CURVE_WORDS or not len(curves):
        raise ValueError("invalid generated border source layout")
    if curves.dtype != np.dtype("<f4") or not curves.flags.c_contiguous:
        curves = np.ascontiguousarray(curves, dtype="<f4")
    memo = previous.get(id(curves))
    if memo is not None and memo[0] is curves:
        digest = memo[1]
    else:
        if (not np.isfinite(curves).all() or np.any(curves[:, [7, 19, 31, 36]] < 0)
                or np.any((curves[:, 37:39] != 0) & (curves[:, 37:39] != 1))
                or np.any(curves[:, 39] != 0)):
            raise ValueError("invalid generated border source values")
        identity = hashlib.blake2b(digest_size=16)
        identity.update(b"maniml.border.f32.v1\0")
        identity.update(memoryview(curves).cast("B"))
        digest = identity.hexdigest()
    if _immutable(curves):
        retained[id(curves)] = (curves, digest)
    return digest, curves


def _objects_payload(value, layout, previous, retained):
    objects = validate_objects(value, layout)
    if not objects.flags.c_contiguous:
        objects = np.ascontiguousarray(objects)
    memo = previous.get(id(objects))
    if memo is not None and memo[0] is objects:
        digest = memo[1]
    else:
        identity = hashlib.blake2b(digest_size=16)
        identity.update(b"maniml.patch.objects.f32.v1\0")
        identity.update(memoryview(objects).cast("B"))
        digest = identity.hexdigest()
    if _immutable(objects):
        retained[id(objects)] = (objects, digest)
    return digest, objects


def serialize_generated_frame(frame, camera_uniforms, cache=None):
    """Pack a prepared frame; both drivers consume exactly these operations."""
    supersample = getattr(frame, "supersample", 1)
    if type(supersample) is not int or supersample not in (1, 2):
        raise ValueError("supersample must be 1 or 2")
    camera = {key: _jsonable(value) for key, value in camera_uniforms.items()}
    batches, blobs, offset, current_hashes, texture_hashes = [], [], 0, set(), set()
    previous_payloads = getattr(cache, "generated_payloads", {})
    retained_payloads = {}
    previous_paints = getattr(cache, "generated_paints", {})
    retained_paints, paints = {}, {}
    previous_borders = getattr(cache, "generated_borders", {})
    retained_borders, borders = {}, {}
    previous_objects = getattr(cache, "generated_objects", {})
    retained_objects, object_tables = {}, {}
    for draw in frame.draws:
        base = draw.pipeline.removesuffix("_depth")
        if base not in PIPELINE_STRIDES:
            raise ValueError(f"unsupported generated pipeline: {draw.pipeline}")
        vertices = np.ascontiguousarray(draw.vertices)
        if vertices.ndim != 1 or vertices.dtype.itemsize != PIPELINE_STRIDES[base]:
            raise ValueError(f"unexpected vertex layout for {draw.pipeline}")
        for name in ("count", "instances"):
            value = getattr(draw, name)
            if isinstance(value, bool) or not isinstance(value, (int, np.integer)) or value < 0:
                raise ValueError(f"{name} must be a nonnegative integer")
        if draw.count == 0 or draw.instances == 0:
            continue
        border = getattr(draw, "border_sources", None)
        objects = getattr(draw, "fill_objects", None)
        border_hash, capacity, layout, objects_hash = None, None, None, None
        indices = None if draw.indices is None else np.asarray(draw.indices)
        if base == "patch":
            # A patch fill run: curve records, the object table and the
            # (curve count, bordered) layout; no vertices or indices of its own.
            if (border is None or objects is None or indices is not None or draw.instances != 1
                    or len(vertices)):
                raise ValueError("patch fill requires curve records, an object table and no vertices")
            border_hash, border = _border_payload(border, previous_borders, retained_borders)
            borders[border_hash] = border
            capacity = validate_capacity(getattr(draw, "border_capacity", MAX_VERTICES_PER_CURVE))
            layout = validate_patch_layout(getattr(draw, "patch_layout", None), len(border))
            objects_hash, objects = _objects_payload(objects, layout, previous_objects, retained_objects)
            object_tables[objects_hash] = objects
            if draw.count != patch_draw_count(layout, capacity):
                raise ValueError("invalid patch fill draw count")
        elif border is not None:
            if base not in ("surface", "paint") or indices is None or draw.instances != 1:
                raise ValueError("GPU border recipe requires one indexed surface operation")
            border_hash, border = _border_payload(border, previous_borders, retained_borders)
            borders[border_hash] = border
            capacity = validate_capacity(getattr(draw, "border_capacity", MAX_VERTICES_PER_CURVE))
            layout = getattr(draw, "border_layout", None)
            if layout is None:
                raise ValueError("GPU border recipes require their run layout")
            layout = validate_layout(layout, len(indices), len(vertices), len(border))
        elif objects is not None:
            raise ValueError("an object table belongs to a patch fill draw")
        output_vertices = len(vertices) + (0 if border is None else capacity * len(border))
        if indices is not None:
            # A border run's wire indices cover only its fills; the drivers
            # append each object's strip pattern from the layout, so the
            # draw count exceeds the index count by exactly that pattern.
            addressable = len(vertices) if border is not None else output_vertices
            expected_count = (None if border is None
                              else len(indices) + indices_per_curve(capacity) * len(border))
            if (base not in ("surface", "paint") or indices.ndim != 1
                    or not np.issubdtype(indices.dtype, np.integer)
                    or np.any(indices < 0) or np.any(indices >= addressable)
                    or (draw.count > len(indices) if border is None else draw.count != expected_count)
                    or draw.count % 3):
                raise ValueError("invalid generated triangle indices or draw count")
            # An equivalent explicit-endian dtype can produce a fresh view
            # when NumPy normalizes it to native byte order. Preserve the
            # original immutable array so its retained digest remains usable.
            if indices.dtype != np.dtype("<u4") or not indices.flags.c_contiguous:
                indices = np.ascontiguousarray(indices, dtype="<u4")
        elif base == "patch":
            pass  # checked against the layout above
        elif base in ("surface", "paint", "image", "texsurface"):
            if draw.count > len(vertices) or draw.count % 3:
                raise ValueError("invalid generated triangle draw count")
        elif base == "dot":
            if draw.count != 4 or draw.instances > len(vertices):
                raise ValueError("invalid generated dot draw count")
        elif base == "stroke":
            if draw.count < 4 or draw.count > 64 or draw.count % 2 or draw.instances * 3 > len(vertices):
                raise ValueError("invalid generated stroke draw count")
        payload_key = (draw.pipeline, id(vertices), id(indices),
                       None if border is None else (len(border), tuple(map(tuple, layout))),
                       objects_hash)
        retained = previous_payloads.get(payload_key)
        if retained is not None and retained[0] is vertices and retained[1] is indices:
            content_hash = retained[2]
        else:
            identity = hashlib.blake2b(digest_size=16)
            identity.update(draw.pipeline.encode())
            identity.update(b"\0indexed\0" if indices is not None else b"\0plain\0")
            if border is not None:
                # The run layout decides where each object's strips interleave;
                # the reserved capacity does not change what is drawn, so it
                # stays out of the identity and a zoom that raises it resends
                # nothing.
                identity.update(b"\0border\0" + struct.pack("<Q", len(border)))
                identity.update(struct.pack(f"<{len(layout[0]) * len(layout)}Q", *(v for part in layout for v in part)))
            if objects_hash is not None:
                identity.update(b"\0objects\0" + objects_hash.encode())
            # Frame both byte streams, and hash their views without allocating
            # another frame-sized copy. Mutable diagnostic data is always read.
            identity.update(struct.pack("<QQ", vertices.nbytes, 0 if indices is None else indices.nbytes))
            identity.update(memoryview(vertices).cast("B"))
            if indices is not None:
                identity.update(memoryview(indices).cast("B"))
            content_hash = identity.hexdigest()
        if _immutable(vertices) and _immutable(indices):
            retained_payloads[payload_key] = (vertices, indices, content_hash)
        # Shared camera values appear once on the wire, while fixed-frame and
        # per-object overrides remain local to their operation. Production
        # preparation already normalized these values: avoid recursively
        # copying the same camera lists once per object. Diagnostic callers
        # may still provide NumPy arrays or tuples, which need normalization.
        uniforms = {}
        for key, value in draw.uniforms.items():
            if key in camera:
                try:
                    shared = value == camera[key]
                    if type(shared) is bool and shared:
                        continue
                except ValueError:  # Nested NumPy arrays have no scalar truth.
                    pass
            normalized = _jsonable(value)
            if key not in camera or normalized != camera[key]:
                uniforms[key] = normalized
        batch = {"kind": "generated", "pipeline": draw.pipeline,
                 "hash": content_hash, "num_verts": output_vertices,
                 "stride": vertices.dtype.itemsize, "uniforms": uniforms,
                 "count": int(draw.count), "instances": int(draw.instances),
                 "indexed": indices is not None,
                 "index_count": 0 if indices is None else len(indices)}
        if border is not None:
            batch["fill_num_verts"] = len(vertices)
            batch["border"] = {"hash": border_hash, "num_curves": len(border), "capacity": capacity}
        if objects_hash is not None:
            batch["objects"] = {"hash": objects_hash, "count": len(objects)}
        if getattr(draw, "coverage", False):
            if base not in ("surface", "paint"):
                raise ValueError("coverage ownership requires triangle surface geometry")
            batch["coverage"] = True
        if base == "paint" or (base == "patch" and getattr(draw, "paint", None) is not None):
            paint_hash, paint = _paint_payload(getattr(draw, "paint", None),
                                               previous_paints, retained_paints)
            batch["paint_hash"] = paint_hash
            paints[paint_hash] = paint
        textures = getattr(draw, "textures", None)
        if textures:
            batch["textures"] = textures
            texture_hashes.update(textures.values())
        if cache is not None and content_hash in cache.sent:
            batch["cached"] = True
        else:
            # The run layout belongs to the geometry: a receiver that holds
            # the fill bytes holds the layout too, so it travels once.
            if border is not None:
                batch["border"]["layout"] = layout
            batch["offset"] = offset
            raw = vertices.tobytes()
            blobs.append(raw)
            offset += len(raw)
            if indices is not None:
                batch["index_offset"] = offset
                index_raw = indices.tobytes()
                blobs.append(index_raw)
                offset += len(index_raw)
        current_hashes.add(content_hash)
        batches.append(batch)
    paint_data = {}
    for key, paint in paints.items():
        if cache is None or f"paint:{key}" not in cache.sent:
            raw = paint.tobytes()
            paint_data[key] = {"offset": offset, "nbytes": len(raw)}
            blobs.append(raw)
            offset += len(raw)
    border_data = {}
    for key, border in borders.items():
        if cache is None or f"border:{key}" not in cache.sent:
            raw = border.tobytes()
            border_data[key] = {"offset": offset, "nbytes": len(raw)}
            blobs.append(raw)
            offset += len(raw)
    object_data = {}
    for key, objects in object_tables.items():
        if cache is None or f"objects:{key}" not in cache.sent:
            raw = objects.tobytes()
            object_data[key] = {"offset": offset, "nbytes": len(raw)}
            blobs.append(raw)
            offset += len(raw)
    texture_data = {}
    for key in sorted(texture_hashes):
        if cache is None or f"tex:{key}" not in cache.sent:
            raw = getattr(frame, "texture_data", {}).get(key)
            if raw is None:
                raw = _TEXTURE_BY_HASH[key]
            texture_data[key] = {"offset": offset, "nbytes": len(raw)}
            blobs.append(raw)
            offset += len(raw)
    header = {"format_version": GEOMETRY_FORMAT_VERSION, "renderer": "triangles",
              "camera": camera, "background": list(frame.background),
              "resolution": list(frame.resolution), "samples": frame.samples,
              "supersample": supersample,
              "batches": batches, "paint_data": paint_data, "border_data": border_data,
              "object_data": object_data, "texture_data": texture_data,
              "unsupported": [], "limitations": list(frame.limitations)}
    encoded = json.dumps(header).encode()
    message = b"".join((bytes([GEOMETRY_MESSAGE_TYPE]), struct.pack("<I", len(encoded)),
                        encoded, *blobs))
    if cache is not None:
        cache.sent = (current_hashes | {f"tex:{key}" for key in texture_hashes}
                      | {f"paint:{key}" for key in paints})
        cache.sent.update(f"border:{key}" for key in borders)
        cache.sent.update(f"objects:{key}" for key in object_tables)
        cache.generated_payloads = retained_payloads
        cache.generated_paints = retained_paints
        cache.generated_borders = retained_borders
        cache.generated_objects = retained_objects
    return message

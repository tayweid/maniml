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


PIPELINE_STRIDES = {"surface": 40, "stroke": 68, "dot": 32,
                    "image": 24, "texsurface": 36}


def serialize_generated_frame(frame, camera_uniforms, cache=None):
    """Pack a prepared frame; both drivers consume exactly these operations."""
    camera = {key: _jsonable(value) for key, value in camera_uniforms.items()}
    batches, blobs, offset, current_hashes, texture_hashes = [], [], 0, set(), set()
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
        indices = None if draw.indices is None else np.asarray(draw.indices)
        if indices is not None:
            if (base != "surface" or indices.ndim != 1
                    or not np.issubdtype(indices.dtype, np.integer)
                    or np.any(indices < 0) or np.any(indices >= len(vertices))
                    or draw.count > len(indices) or draw.count % 3):
                raise ValueError("invalid generated triangle indices or draw count")
            indices = np.ascontiguousarray(indices, dtype="<u4")
        elif base in ("surface", "image", "texsurface"):
            if draw.count > len(vertices) or draw.count % 3:
                raise ValueError("invalid generated triangle draw count")
        elif base == "dot":
            if draw.count != 4 or draw.instances > len(vertices):
                raise ValueError("invalid generated dot draw count")
        elif base == "stroke":
            if draw.count < 4 or draw.count > 64 or draw.count % 2 or draw.instances * 3 > len(vertices):
                raise ValueError("invalid generated stroke draw count")
        raw = vertices.tobytes()
        index_raw = b"" if indices is None else indices.tobytes()
        identity = hashlib.blake2b(digest_size=16)
        identity.update(draw.pipeline.encode())
        identity.update(b"\0indexed\0" if indices is not None else b"\0plain\0")
        # Frame the two byte streams: a trailing all-zero vertex can otherwise
        # be reinterpreted as leading zero indices without changing the digest.
        identity.update(struct.pack("<QQ", len(raw), len(index_raw)))
        identity.update(raw)
        identity.update(index_raw)
        content_hash = identity.hexdigest()
        uniforms = {key: _jsonable(value) for key, value in draw.uniforms.items()}
        # Shared camera values appear once on the wire, while fixed-frame and
        # per-object overrides remain local to their operation.
        uniforms = {key: value for key, value in uniforms.items()
                    if key not in camera or camera[key] != value}
        batch = {"kind": "generated", "pipeline": draw.pipeline,
                 "hash": content_hash, "num_verts": len(vertices),
                 "stride": vertices.dtype.itemsize, "uniforms": uniforms,
                 "count": int(draw.count), "instances": int(draw.instances),
                 "indexed": indices is not None,
                 "index_count": 0 if indices is None else len(indices)}
        textures = getattr(draw, "textures", None)
        if textures:
            batch["textures"] = textures
            texture_hashes.update(textures.values())
        if cache is not None and content_hash in cache.sent:
            batch["cached"] = True
        else:
            batch["offset"] = offset
            blobs.append(raw)
            offset += len(raw)
            if indices is not None:
                batch["index_offset"] = offset
                blobs.append(index_raw)
                offset += len(index_raw)
        current_hashes.add(content_hash)
        batches.append(batch)
    texture_data = {}
    for key in sorted(texture_hashes):
        if cache is None or f"tex:{key}" not in cache.sent:
            raw = _TEXTURE_BY_HASH[key]
            texture_data[key] = {"offset": offset, "nbytes": len(raw)}
            blobs.append(raw)
            offset += len(raw)
    header = {"format_version": GEOMETRY_FORMAT_VERSION, "renderer": "triangles",
              "camera": camera, "background": list(frame.background),
              "resolution": list(frame.resolution), "samples": frame.samples,
              "batches": batches, "texture_data": texture_data,
              "unsupported": [], "limitations": list(frame.limitations)}
    encoded = json.dumps(header).encode()
    message = b"".join((bytes([GEOMETRY_MESSAGE_TYPE]), struct.pack("<I", len(encoded)),
                        encoded, *blobs))
    if cache is not None:
        # Preserve texture knowledge: both drivers retain textures separately.
        cache.sent = current_hashes | {key for key in cache.sent if key.startswith("tex:")}
        cache.sent.update(f"tex:{key}" for key in texture_hashes)
    return message

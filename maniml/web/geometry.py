"""Geometry snapshot serialization for the Stage-2 client renderer.

Serializes the scene's current draw list into a self-contained binary
message the browser (or the test harness in tests/test_gl_port.py) can
render with its own GPU:

    [0x03][u32le header_len][JSON header][vertex data]

The vertex data is the exact GPU contract the native renderer uses —
each VMobject's expanded `get_shader_data()` array (the interleaved
68-byte-per-vertex struct, already fancy-indexed into consecutive
bezier triples) concatenated in draw order. The header carries the
camera uniforms from `Camera.refresh_uniforms()` verbatim plus
per-batch mobject uniforms, so the consumer reproduces the native
projection arithmetic rather than inventing its own.

Scope (proof-of-concept): 2D VMobjects — fill (winding-number pass) and
stroke. Batches this can't express (images, surfaces, dot clouds,
depth-tested/triangulated fill) are listed in `unsupported` so the
client can fall back to the pixel stream for those scenes.
"""

from __future__ import annotations

import json
import struct

import numpy as np

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from maniml.scene.scene import Scene

GEOMETRY_MESSAGE_TYPE = 0x03


def _jsonable(value):
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, (np.floating, np.integer)):
        return value.item()
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return value


def serialize_scene(scene: Scene) -> bytes:
    """Snapshot the scene's current visual state as a geometry message."""
    from maniml.mobject.types.vectorized_mobject import VMobject
    from maniml.camera.camera_frame import CameraFrame

    camera = scene.camera
    camera.refresh_uniforms()

    batches = []
    unsupported = []
    blobs = []
    offset = 0

    for group in scene.render_groups:
        for sm in group.family_members_with_points():
            if isinstance(sm, CameraFrame):
                continue  # in scene.mobjects but never drawn
            if not isinstance(sm, VMobject):
                name = type(sm).__name__
                if name not in unsupported:
                    unsupported.append(name)
                continue
            if sm.depth_test or getattr(sm, 'use_triangulated_fill', False):
                name = f"{type(sm).__name__} (depth/triangulated fill)"
                if name not in unsupported:
                    unsupported.append(name)
                continue
            data = sm.get_shader_data()
            if len(data) == 0:
                continue
            raw = np.ascontiguousarray(data).tobytes()
            batches.append({
                "kind": "vmobject",
                "offset": offset,
                "num_verts": len(data),
                "uniforms": {k: _jsonable(v) for k, v in sm.uniforms.items()},
                "stroke_behind": bool(sm.stroke_behind),
            })
            blobs.append(raw)
            offset += len(raw)

    header = {
        "camera": {k: _jsonable(v) for k, v in camera.uniforms.items()},
        "background": _jsonable(list(camera.background_rgba)),
        "resolution": list(camera.draw_fbo.size),
        "vertex_stride": 68,
        "batches": batches,
        "unsupported": unsupported,
    }
    header_bytes = json.dumps(header).encode()
    return b"".join([
        bytes([GEOMETRY_MESSAGE_TYPE]),
        struct.pack("<I", len(header_bytes)),
        header_bytes,
        *blobs,
    ])


def parse_geometry_message(message: bytes):
    """Inverse of serialize_scene, for tests and tooling: returns
    (header dict, vertex bytes)."""
    assert message[0] == GEOMETRY_MESSAGE_TYPE
    (header_len,) = struct.unpack_from("<I", message, 1)
    header = json.loads(message[5:5 + header_len].decode())
    return header, message[5 + header_len:]

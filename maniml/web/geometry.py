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


def _triangulated_fill_data(sm):
    """Depth-correct fill triangles, replicating the data build in
    VShaderWrapper.render_triangulated_fill: earclip vertices with a
    flat per-mobject fill color, normals implied by a +z offset point.
    Returns (vertex_bytes, index_bytes, vertex_count, index_count)."""
    from maniml.rendering.shader_wrapper import VShaderWrapper
    from maniml.utils.color import color_to_rgb

    triangulation = VShaderWrapper._get_triangulation(sm)
    if triangulation is None:
        return None
    vertices, indices = triangulation
    surface_dtype = np.dtype([
        ('point', np.float32, (3,)),
        ('d_normal_point', np.float32, (3,)),
        ('rgba', np.float32, (4,)),
    ])
    data = np.zeros(len(vertices), dtype=surface_dtype)
    data['point'][:] = vertices
    data['d_normal_point'][:] = vertices + np.array([0, 0, 0.001])
    rgb = color_to_rgb(sm.get_fill_color())
    data['rgba'][:] = np.array([*rgb, sm.get_fill_opacity()], dtype=np.float32)
    index_bytes = np.ascontiguousarray(indices.astype('u4')).tobytes()
    return data.tobytes(), index_bytes, len(data), len(indices)


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
            triangulated = bool(getattr(sm, 'use_triangulated_fill', False))
            has_fill = sm.get_fill_opacity() > 0
            if sm.depth_test and has_fill and not triangulated:
                # Winding fill under depth test needs the depth pre-pass,
                # which is not ported (parity ledger item 6). Rare:
                # ThreeDScene.add switches fills to triangulated.
                name = f"{type(sm).__name__} (depth-tested winding fill)"
                if name not in unsupported:
                    unsupported.append(name)
                continue
            data = sm.get_shader_data()
            if len(data) == 0:
                continue
            raw = np.ascontiguousarray(data).tobytes()
            batch = {
                "kind": "vmobject",
                "offset": offset,
                "num_verts": len(data),
                "uniforms": {k: _jsonable(v) for k, v in sm.uniforms.items()},
                "stroke_behind": bool(sm.stroke_behind),
                "depth_test": bool(sm.depth_test),
                "fill_mode": "triangulated" if triangulated else "winding",
            }
            blobs.append(raw)
            offset += len(raw)
            if triangulated and has_fill:
                tri = _triangulated_fill_data(sm)
                if tri is not None:
                    tri_bytes, index_bytes, vcount, icount = tri
                    batch["tri"] = {
                        "voffset": offset, "vcount": vcount,
                        "ioffset": offset + len(tri_bytes), "icount": icount,
                    }
                    blobs.append(tri_bytes)
                    blobs.append(index_bytes)
                    offset += len(tri_bytes) + len(index_bytes)
            batches.append(batch)

    header = {
        "camera": {k: _jsonable(v) for k, v in camera.uniforms.items()},
        "background": _jsonable(list(camera.background_rgba)),
        "resolution": list(camera.draw_fbo.size),
        "samples": int(getattr(camera, "samples", 0)),
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

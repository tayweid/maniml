"""Geometry snapshot serialization for the Stage-2 client renderer.

Serializes the scene's current draw list into a self-contained binary
message the browser (or the fidelity harness in tests/test_wgpu_port.py) can
render with its own GPU:

    [0x03][u32le header_len][JSON header][vertex data]

The vertex data is the exact GPU contract the native renderer uses —
each VMobject's expanded `get_shader_data()` array (the interleaved
68-byte-per-vertex struct, already fancy-indexed into consecutive
bezier triples) concatenated in draw order. The header carries the
camera uniforms from `Camera.refresh_uniforms()` verbatim plus
per-batch mobject uniforms, so the consumer reproduces the native
projection arithmetic rather than inventing its own.

Batching mirrors the native renderer: within one render group, family
members are stably sorted by z_index and consecutive submobjects with
identical draw state (kind, uniforms, stroke_behind, depth_test,
fill_mode) merge into one batch — one buffer, one pass sequence. This
is not just a draw-call optimization: the winding-number fill blending
is only native-faithful when a whole batch accumulates in the float
texture before a single composite. Merging never crosses a
render-group boundary (the groups are the scene's z_index draw order),
and — because each batch draws all its fills before any of its strokes
— a member whose fill overlaps an already-merged member's stroke
starts a new batch, exactly as the native flatten does
(assemble_draw_batches in utils/family_ops.py).

Each vmobject batch also carries `stroke_verts`: the largest strip the
batch's curves actually need (the same adaptive-subdivision formula the
stroke shader applies, evaluated at the current frame_scale), so the
client can draw that many vertices per instance instead of the
worst-case 64.

Not expressible here (recorded by type in the header's `unsupported`
list and left out of the picture — there is no server-side frame behind
the browser's render): unknown custom drawables and depth-tested winding
fills that were not triangulated. Images, surfaces,
texture data, dot clouds, triangulated fills, and clip planes are supported.
"""

from __future__ import annotations

import json
import struct

import numpy as np

from maniml.performance import performance
from maniml.utils.family_ops import DrawBatchHazard
from maniml.utils.family_ops import draw_pass_content
from maniml.utils.family_ops import padded_draw_bbox

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from maniml.scene.scene import Scene

GEOMETRY_MESSAGE_TYPE = 0x03
# Increment when a geometry header or payload change is not backward
# compatible. Baked exports copy this into scene.json so the standalone
# player can reject stale data before attempting to render it.
GEOMETRY_FORMAT_VERSION = 1


class GeometryCache:
    """Delta-encoding state: the batch content hashes every connected
    client is known to hold. Owned by the viewer; reset whenever a
    client connects (or asks for a reset), so the next message ships
    every batch in full."""

    def __init__(self):
        self.sent: set[str] = set()

    def reset(self):
        self.sent.clear()

# Constants from quadratic_bezier/stroke/geom.glsl
POLYLINE_FACTOR = 100.0
MAX_STEPS = 32

SURFACE_DTYPE = np.dtype([
    ('point', np.float32, (3,)),
    ('d_normal_point', np.float32, (3,)),
    ('rgba', np.float32, (4,)),
])


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
    Returns (vertex_struct_array, index_array) or None."""
    from maniml.rendering.shader_wrapper import VShaderWrapper
    from maniml.utils.color import color_to_rgb

    triangulation = VShaderWrapper._get_triangulation(sm)
    if triangulation is None:
        return None
    vertices, indices = triangulation
    data = np.zeros(len(vertices), dtype=SURFACE_DTYPE)
    data['point'][:] = vertices
    data['d_normal_point'][:] = vertices + np.array([0, 0, 0.001])
    rgb = color_to_rgb(sm.get_fill_color())
    data['rgba'][:] = np.array([*rgb, sm.get_fill_opacity()], dtype=np.float32)
    return data, indices.astype('u4')


def _stroke_verts(data, frame_scale) -> int:
    """Largest strip any curve in `data` needs, per the adaptive
    subdivision in the stroke shader: n_steps = min(2 + round(
    100*sqrt(area)/frame_scale), 32), two vertices per step."""
    p0 = data['point'][0::3]
    p1 = data['point'][1::3]
    p2 = data['point'][2::3]
    areas = 0.5 * np.linalg.norm(np.cross(p1 - p0, p2 - p0), axis=1)
    counts = np.round(POLYLINE_FACTOR * np.sqrt(areas) / frame_scale)
    max_steps = int(min(2 + counts.max(initial=0), MAX_STEPS))
    return 2 * max(max_steps, 2)


def _texture_refs(sm):
    """Sampler-name -> texture content hash for a textured mobject,
    reading each file once (module-level cache)."""
    refs = {}
    for name, path in sm.texture_paths.items():
        refs[name] = _texture_file(path)[0]
    return refs


_TEXTURE_FILES: dict[str, tuple[str, bytes]] = {}  # path -> (hash, bytes)
_TEXTURE_BY_HASH: dict[str, bytes] = {}


def _texture_file(path: str) -> tuple[str, bytes]:
    import hashlib
    cached = _TEXTURE_FILES.get(path)
    if cached is None:
        with open(path, "rb") as f:
            raw = f.read()
        cached = (hashlib.blake2b(raw, digest_size=8).hexdigest(), raw)
        _TEXTURE_FILES[path] = cached
        _TEXTURE_BY_HASH[cached[0]] = raw
    return cached


def _unsupported_geometry_name(sm) -> str | None:
    """Return the serializer incompatibility for one drawable, if any."""
    from maniml.mobject.types.vectorized_mobject import VMobject
    from maniml.mobject.types.dot_cloud import DotCloud
    from maniml.mobject.types.image_mobject import ImageMobject
    from maniml.mobject.types.surface import Surface
    from maniml.camera.camera_frame import CameraFrame

    if isinstance(sm, CameraFrame):
        return None
    if isinstance(sm, (DotCloud, ImageMobject, Surface)):
        return None
    if not isinstance(sm, VMobject):
        return type(sm).__name__
    triangulated = bool(getattr(sm, 'use_triangulated_fill', False))
    if sm.depth_test and sm.get_fill_opacity() > 0 and not triangulated:
        return f"{type(sm).__name__} (depth-tested winding fill)"
    return None


def _collect_records(scene, unsupported):
    """One record per drawable submobject, in draw order, carrying the
    numpy data and the draw state that decides merge compatibility."""
    from maniml.mobject.types.dot_cloud import DotCloud
    from maniml.mobject.types.image_mobject import ImageMobject
    from maniml.mobject.types.surface import Surface, TexturedSurface
    from maniml.camera.camera_frame import CameraFrame

    def plain_record(sm, kind, stride, textures=None):
        data = sm.get_shader_data()
        if len(data) == 0:
            return None
        return {
            "kind": kind, "stride": stride, "data": data, "group": group_index,
            "uniforms": {k: _jsonable(v) for k, v in sm.uniforms.items()},
            "depth_test": bool(sm.depth_test),
            "stroke_behind": False, "fill_mode": None,
            "tri": None, "textures": textures,
            "_pass_early": False, "_pass_late": False, "_draw_bbox": None,
        }

    records = []
    for group_index, group in enumerate(scene.render_groups):
        # Stable z_index sort within the family — the same order the
        # native flatten uses (Mobject.get_shader_wrapper_list)
        for sm in sorted(group.family_members_with_points(),
                         key=lambda m: m.z_index):
            if isinstance(sm, CameraFrame):
                continue  # in scene.mobjects but never drawn
            unsupported_name = _unsupported_geometry_name(sm)
            if unsupported_name is not None:
                if unsupported_name not in unsupported:
                    unsupported.append(unsupported_name)
                continue
            if isinstance(sm, (DotCloud, ImageMobject, Surface)):
                if isinstance(sm, DotCloud):
                    record = plain_record(sm, "dotcloud", 32)
                elif isinstance(sm, ImageMobject):
                    record = plain_record(sm, "image", 24,
                                          textures=_texture_refs(sm))
                elif isinstance(sm, TexturedSurface):
                    record = plain_record(sm, "texsurface", 36,
                                          textures=_texture_refs(sm))
                else:
                    record = plain_record(sm, "surface", 40)
                if record is not None:
                    records.append(record)
                continue
            triangulated = bool(getattr(sm, 'use_triangulated_fill', False))
            has_fill = sm.get_fill_opacity() > 0
            data = sm.get_shader_data()
            if len(data) == 0:
                continue
            pass_early, pass_late = draw_pass_content(sm)
            records.append({
                "kind": "vmobject", "stride": 68, "data": data,
                "group": group_index,
                "uniforms": {k: _jsonable(v) for k, v in sm.uniforms.items()},
                "stroke_behind": bool(sm.stroke_behind),
                "depth_test": bool(sm.depth_test),
                "fill_mode": "triangulated" if triangulated else "winding",
                "tri": (_triangulated_fill_data(sm)
                        if triangulated and has_fill else None),
                "textures": None,
                "_pass_early": pass_early, "_pass_late": pass_late,
                "_draw_bbox": (padded_draw_bbox(sm)
                               if pass_early or pass_late else None),
            })
    return records


# "group" keeps merging inside one native render group: the groups are
# the z_index/draw-order sort (Scene.assemble_render_groups), and a
# batch is the unit of the fill-accumulate-then-stroke pass sequence,
# so merging across groups would draw one group's strokes over a later
# group's fills (e.g. a z_index=10 Dot behind a z_index=0 line).
_MERGE_KEYS = ("group", "kind", "uniforms", "stroke_behind", "depth_test",
               "fill_mode", "textures")


def _merge_records(records):
    """Merge consecutive records with identical draw state — the
    native renderer's batching (assemble_draw_batches in
    utils/family_ops.py; the split rules here must mirror it, and
    tests/test_wgpu_port.py pixel-diffs the two pipelines). Triangulated
    fill chunks concatenate with re-based indices.

    A record whose early-pass content (fill; stroke when stroke_behind)
    overlaps the open batch's accumulated late-pass content starts a
    new batch instead of merging: a batch draws all its early passes
    before any of its late ones, so merging there would paint the new
    member under an earlier member's stroke — the CE draw-order hazard
    assemble_draw_batches documents.

    Chunks are gathered and joined once per batch rather than folded in
    one at a time. Concatenating on each step reallocates and recopies
    everything accumulated so far, which makes merging n records copy
    O(n**2) vertex bytes — on a scene of a few hundred filled shapes that
    was the single largest cost in producing a frame, and it grew as the
    square of how much you had drawn.
    """
    merged = []
    chunks = []      # per merged batch: the data arrays still to be joined
    tri_chunks = []  # per merged batch: (verts, indices) still to be joined
    hazard_state = None  # late-pass footprint of the open batch
    for record in records:
        prev = merged[-1] if merged else None
        bbox = record["_draw_bbox"]
        hazard = prev is not None and hazard_state.would_invert(
            record["_pass_early"], bbox)
        if prev is not None and not hazard and all(
                prev[k] == record[k] for k in _MERGE_KEYS):
            chunks[-1].append(record["data"])
            if record["tri"] is not None:
                tri_chunks[-1].append(record["tri"])
        else:
            merged.append(dict(record))
            chunks.append([record["data"]])
            tri_chunks.append([record["tri"]] if record["tri"] is not None else [])
            hazard_state = DrawBatchHazard()
        hazard_state.admit(record["_pass_late"], bbox)

    for batch in merged:
        del batch["_pass_early"], batch["_pass_late"], batch["_draw_bbox"]

    for batch, data_parts, tri_parts in zip(merged, chunks, tri_chunks):
        if len(data_parts) > 1:
            batch["data"] = np.concatenate(data_parts)
        if not tri_parts:
            batch["tri"] = None
        elif len(tri_parts) == 1:
            batch["tri"] = tri_parts[0]
        else:
            # Indices are relative to each chunk's own vertices, so they
            # shift by however many vertices precede that chunk.
            offset = 0
            verts, indices = [], []
            for chunk_verts, chunk_indices in tri_parts:
                verts.append(chunk_verts)
                indices.append(chunk_indices + offset)
                offset += len(chunk_verts)
            batch["tri"] = (np.concatenate(verts), np.concatenate(indices))
    return merged


def serialize_scene(scene: Scene, cache: GeometryCache | None = None) -> bytes:
    """Snapshot the scene's current visual state as a geometry message.

    With a GeometryCache, batches whose content the clients already
    hold ship as `"cached": true` + hash only — metadata (uniforms,
    stroke_verts) is still sent fresh, since it can change (e.g. with
    zoom) without the vertex bytes changing."""
    import hashlib

    camera = scene.camera
    with performance.stage("geometry.camera_uniforms"):
        camera.refresh_uniforms()
        frame_scale = float(camera.uniforms["frame_scale"])

    unsupported = []
    batches = []
    blobs = []
    offset = 0
    needed_textures: dict[str, bytes] = {}

    with performance.stage("geometry.collect_shader_data"):
        records = _collect_records(scene, unsupported)
    with performance.stage("geometry.merge_batches"):
        records = _merge_records(records)
    cached_batches = 0
    vertices = 0
    with performance.stage("geometry.pack_and_hash"):
        for record in records:
            data = record["data"]
            vertices += len(data)
            raw = np.ascontiguousarray(data).tobytes()
            tri_bytes = index_bytes = b""
            if record["kind"] == "vmobject" and record["tri"] is not None:
                tri_data, tri_indices = record["tri"]
                tri_bytes = tri_data.tobytes()
                index_bytes = np.ascontiguousarray(tri_indices).tobytes()

            content_hash = hashlib.blake2b(
                raw + tri_bytes, digest_size=8).hexdigest()
            batch = {
                "kind": record["kind"],
                "hash": content_hash,
                "num_verts": len(data),
                "stride": record["stride"],
                "uniforms": record["uniforms"],
                "depth_test": record["depth_test"],
            }
            if record["kind"] == "vmobject":
                batch["stroke_behind"] = record["stroke_behind"]
                batch["fill_mode"] = record["fill_mode"]
                batch["stroke_verts"] = _stroke_verts(data, frame_scale)
            if record["textures"]:
                batch["textures"] = record["textures"]
                for tex_hash in record["textures"].values():
                    if cache is None or f"tex:{tex_hash}" not in cache.sent:
                        needed_textures[tex_hash] = _TEXTURE_BY_HASH[tex_hash]

            if cache is not None and content_hash in cache.sent:
                batch["cached"] = True
                cached_batches += 1
            else:
                batch["offset"] = offset
                blobs.append(raw)
                offset += len(raw)
                if tri_bytes:
                    batch["tri"] = {
                        "voffset": offset, "vcount": len(tri_bytes) // 40,
                        "ioffset": offset + len(tri_bytes),
                        "icount": len(index_bytes) // 4,
                    }
                    blobs.append(tri_bytes)
                    blobs.append(index_bytes)
                    offset += len(tri_bytes) + len(index_bytes)
                if cache is not None:
                    cache.sent.add(content_hash)
            batches.append(batch)

    texture_data = {}
    for tex_hash, raw_tex in needed_textures.items():
        texture_data[tex_hash] = {"offset": offset, "nbytes": len(raw_tex)}
        blobs.append(raw_tex)
        offset += len(raw_tex)
        if cache is not None:
            cache.sent.add(f"tex:{tex_hash}")

    header = {
        "format_version": GEOMETRY_FORMAT_VERSION,
        "camera": {k: _jsonable(v) for k, v in camera.uniforms.items()},
        "background": _jsonable(list(camera.background_rgba)),
        "resolution": list(camera.draw_fbo.size),
        "samples": int(getattr(camera, "samples", 0)),
        "vertex_stride": 68,
        "batches": batches,
        "texture_data": texture_data,
        "unsupported": unsupported,
    }
    with performance.stage("geometry.json_and_join"):
        header_bytes = json.dumps(header).encode()
        message = b"".join([
            bytes([GEOMETRY_MESSAGE_TYPE]),
            struct.pack("<I", len(header_bytes)),
            header_bytes,
            *blobs,
        ])
    performance.increment("geometry.serialize.calls")
    performance.increment("geometry.serialized_bytes", len(message))
    performance.increment("geometry.vertices", vertices)
    performance.increment("geometry.cached_batches", cached_batches)
    performance.gauge("geometry.batch_count", len(batches))
    performance.gauge("geometry.unsupported_count", len(unsupported))
    return message


def parse_geometry_message(message: bytes):
    """Inverse of serialize_scene, for tests and tooling: returns
    (header dict, vertex bytes)."""
    assert message[0] == GEOMETRY_MESSAGE_TYPE
    (header_len,) = struct.unpack_from("<I", message, 1)
    header = json.loads(message[5:5 + header_len].decode())
    return header, message[5 + header_len:]

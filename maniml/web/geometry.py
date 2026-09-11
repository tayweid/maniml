"""Shared triangle scene serialization and geometry-stream utilities.

Source arrays remain in mobjects. Derived meshes, ordered draw operations and
material fields travel in a versioned message consumed by browser and native
WebGPU. Geometry caches belong to the output transport, never checkpoints.
"""
from __future__ import annotations

import json
import os
import struct
from collections import OrderedDict

import numpy as np

from maniml.performance import performance

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from maniml.scene.scene import Scene

GEOMETRY_MESSAGE_TYPE = 0x03
# Increment when a geometry header or payload change is not backward
# compatible. Baked exports copy this into scene.json so the standalone
# player can reject stale data before attempting to render it.
GEOMETRY_FORMAT_VERSION = 7


class GeometryCache:
    """Delta-encoding state: the batch content hashes every connected
    client is known to hold. Owned by the viewer; reset whenever a
    client connects (or asks for a reset), so the next message ships
    every batch in full."""

    def __init__(self):
        self.sent: set[str] = set()
        self.renderer = None
        self.triangle_tessellator = None
        self.triangle_meshes = None
        self.generated_payloads = {}
        self.generated_paints = {}
        self.generated_borders = {}
        self.generated_objects = {}
        self.generated_nets = {}
        self.border_generator = None
        self.fill_generator = None
        self.surface_generator = None

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


def _texture_refs(sm, payloads=None):
    """Sampler-name -> texture content hash for a textured mobject,
    reading each file once (module-level cache)."""
    refs = {}
    for name, path in sm.texture_paths.items():
        key, raw = _texture_file(path)
        refs[name] = key
        if payloads is not None:
            payloads[key] = raw
    return refs


_TEXTURE_FILES = OrderedDict()  # path -> (stat signature, hash, immutable bytes)
_TEXTURE_BY_HASH: dict[str, bytes] = {}
MAX_TEXTURE_CACHE_BYTES = 64 << 20
MAX_TEXTURE_CACHE_FILES = 128


def _texture_file(path: str) -> tuple[str, bytes]:
    import hashlib
    path = os.fspath(path)
    stat = os.stat(path)
    signature = (stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size, stat.st_ino)
    cached = _TEXTURE_FILES.get(path)
    if cached is None or cached[0] != signature:
        with open(path, "rb") as f:
            raw = f.read()
        cached = (signature, hashlib.blake2b(raw, digest_size=16).hexdigest(), raw)
        _TEXTURE_FILES[path] = cached
    _TEXTURE_FILES.move_to_end(path)
    while (len(_TEXTURE_FILES) > MAX_TEXTURE_CACHE_FILES or
           sum(len(item[2]) for item in _TEXTURE_FILES.values()) > MAX_TEXTURE_CACHE_BYTES):
        _TEXTURE_FILES.popitem(last=False)
    # Frames pin their own immutable payloads, independently of this read cache.
    _TEXTURE_BY_HASH.clear()
    _TEXTURE_BY_HASH.update((item[1], item[2]) for item in _TEXTURE_FILES.values())
    return cached[1:]


def serialize_scene(scene: Scene, cache: GeometryCache | None = None, *,
                    renderer: str | None = None) -> bytes:
    """Snapshot ordered triangle operations; cache reuse checks source content.

    The original winding path remains selectable in the viewer for dogfooding.
    """
    selected = renderer if renderer is not None else os.environ.get("MANIML_RENDERER", "triangles")
    if selected not in ("triangles", "winding"):
        raise ValueError("MANIML_RENDERER must be 'triangles' or 'winding'")
    if cache is not None and cache.renderer != selected:
        cache.reset()
        cache.renderer = selected
    if selected == "winding":
        from maniml.web.winding_geometry import serialize_scene as serialize_winding
        return serialize_winding(scene, cache)
    return _serialize_triangle_scene(scene, cache)


def _serialize_triangle_scene(scene, cache):
    """One source-to-operation path for viewer, baked export and native output."""
    from maniml.web.generated_geometry import serialize_generated_frame
    from maniml.web.triangle_geometry import LyonFillTessellator
    from maniml.web.triangle_scene import TriangleMeshCache, prepare_triangle_frame

    state = cache if cache is not None else GeometryCache()
    border_generator = os.environ.get("MANIML_BORDER_GENERATOR", "gpu")
    if border_generator not in ("cpu", "gpu"):
        raise ValueError("MANIML_BORDER_GENERATOR must be 'cpu' or 'gpu'")
    # Phase A's CPU fill meshes stay the default while the patch fill
    # (docs/phase_b1_plan.md) is measured; it draws from the GPU border
    # stage's curve records, so it needs the GPU border generator.
    fill_generator = os.environ.get("MANIML_FILL", "meshes")
    if fill_generator not in ("meshes", "patches"):
        raise ValueError("MANIML_FILL must be 'meshes' or 'patches'")
    if fill_generator == "patches" and border_generator != "gpu":
        raise ValueError("MANIML_FILL=patches requires MANIML_BORDER_GENERATOR=gpu")
    # Phase B2 (docs/phase_b2_plan.md): surfaces as control nets the GPU
    # evaluates at screen density; the CPU-evaluated grid stays the default.
    surface_generator = os.environ.get("MANIML_SURFACE", "grids")
    if surface_generator not in ("grids", "nets"):
        raise ValueError("MANIML_SURFACE must be 'grids' or 'nets'")
    if (state.border_generator != border_generator or state.fill_generator != fill_generator
            or state.surface_generator != surface_generator):
        state.reset()
        state.border_generator = border_generator
        state.fill_generator = fill_generator
        state.surface_generator = surface_generator
        if state.triangle_meshes is not None:
            state.triangle_meshes.gpu_border_cache.clear()
    if state.triangle_tessellator is None:
        state.triangle_tessellator = LyonFillTessellator()
        state.triangle_meshes = TriangleMeshCache()
    with performance.stage("geometry.triangle_prepare"):
        frame = prepare_triangle_frame(scene, state.triangle_tessellator,
                                       mesh_cache=state.triangle_meshes, fill_borders=True,
                                       gpu_borders=border_generator == "gpu",
                                       patch_fills=fill_generator == "patches",
                                       net_surfaces=surface_generator == "nets")
        frame.samples = 4
        frame.supersample = 2
    with performance.stage("geometry.triangle_encode"):
        message = serialize_generated_frame(frame, scene.camera.uniforms, cache)
    performance.increment("geometry.serialize.calls")
    performance.increment("geometry.serialized_bytes", len(message))
    performance.gauge("geometry.batch_count", len(frame.draws))
    performance.gauge("geometry.triangle_retained_bytes", frame.mesh_cache_stats["retained_bytes"])
    return message


def parse_geometry_message(message: bytes):
    """Inverse of serialize_scene, for tests and tooling: returns
    (header dict, vertex bytes)."""
    assert message[0] == GEOMETRY_MESSAGE_TYPE
    (header_len,) = struct.unpack_from("<I", message, 1)
    header = json.loads(message[5:5 + header_len].decode())
    return header, message[5 + header_len:]

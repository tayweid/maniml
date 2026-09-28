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

from maniml.utils import programs

from maniml.performance import performance

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from maniml.scene.scene import Scene

GEOMETRY_MESSAGE_TYPE = 0x03
# Increment when a geometry header or payload change is not backward
# compatible. Format 8 (docs/phase_b4_plan.md, B4.8) is a stream: every
# message carries its epoch and frame number, and after the full frame
# that opens an epoch each is a delta against the one before it, or is not
# sent at all when nothing changed. A receiver announces it in its mode
# message, and only a cache whose receivers all have (GeometryCache.deltas)
# writes it.
GEOMETRY_FORMAT_VERSION = 8
# The full frame every other receiver is sent (native capture, the export
# recorder, a viewer with a tab that has not announced format 8): format 7,
# byte for byte what format 7 always wrote. A format 8 full frame is this
# frame with "format_version": 8 and its "epoch" and "frame" after it.
# Baked exports copy it into scene.json so the standalone player can
# reject stale data before attempting to render it.
FULL_FRAME_FORMAT_VERSION = 7


class GeometryCache:
    """Delta-encoding state: the batch content hashes every connected
    client is known to hold. Owned by the viewer; reset whenever a
    client connects (or asks for a reset), so the next message ships
    every batch in full.

    Under format 8 (``deltas``, set through negotiate when every receiver
    has announced it) the cache is also the stream's state: its ``epoch``,
    the ``frame`` number of the last message sent in it, and ``last``,
    what that message left the receivers holding
    (generated_geometry.SentFrame), which the next delta is taken against;
    None until an epoch's full frame is sent. Every reset starts an epoch."""

    def __init__(self):
        self.sent: set[str] = set()
        self.deltas = False
        self.epoch = 0
        self.frame = 0
        self.last = None
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
        self.patch_source = None
        self.surface_generator = None
        self.program_mode = None
        # The retained frame (docs/phase_b4_plan.md; MANIML_RETAINED_FRAME=0
        # turns it off): the draws kept across frames, which must see every
        # frame this cache serializes.
        self.retained_frame = None

    def reset(self):
        self.sent.clear()
        self.restart()

    def restart(self):
        """Start an epoch: the next message is a full frame. What the
        receivers hold is kept, and the full frame names it cached."""
        self.epoch += 1
        self.frame = 0
        self.last = None

    def negotiate(self, deltas: bool):
        """Whether every receiver reads format 8. A change starts an epoch:
        a receiver that joins without it is sent format 7 full frames from
        the next message on, and the stream that resumes when it leaves
        opens with a full frame."""
        if deltas != self.deltas:
            self.deltas = deltas
            self.restart()

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


def _stroke_sqrt_area(data):
    """The largest sqrt(area) of `data`'s curves, in _stroke_verts's own
    arithmetic (float32 for float32 points): all _stroke_verts needs to
    know of `data` at any other frame_scale (_stroke_verts_at)."""
    p0 = data['point'][0::3]
    p1 = data['point'][1::3]
    p2 = data['point'][2::3]
    areas = 0.5 * np.linalg.norm(np.cross(p1 - p0, p2 - p0), axis=1)
    return np.sqrt(areas).max(initial=0)


def _stroke_verts_at(sqrt_area, frame_scale) -> int:
    """_stroke_verts(data, frame_scale) from _stroke_sqrt_area(data), in
    O(1): for a positive frame_scale, scaling, rounding and the cap are
    each monotone, so the largest curve's count is the largest count, and
    the scalar goes through the same float32 operations as the array.
    Only for a finite positive frame_scale; any other the caller hands to
    _stroke_verts, which refuses or answers it curve by curve."""
    count = np.round(POLYLINE_FACTOR * sqrt_area / frame_scale)
    max_steps = int(min(2 + count, MAX_STEPS))
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
                    renderer: str | None = None) -> bytes | None:
    """Snapshot ordered triangle operations; cache reuse checks source content.

    A cache whose receivers negotiated format 8 (``cache.deltas``) is sent
    a stream: a full frame, then deltas against it, and None for a frame
    that changes nothing, which is not a message. Any other caller gets a
    format 7 full frame. The original winding path remains selectable in
    the viewer for dogfooding; it writes full frames.
    """
    selected = renderer if renderer is not None else os.environ.get("MANIML_RENDERER", "triangles")
    if selected not in RENDERERS:
        raise ValueError("MANIML_RENDERER must be one of " + ", ".join(RENDERERS))
    if cache is not None and cache.renderer != selected:
        cache.reset()
        cache.renderer = selected
        # Original 2D clears the triangle caches the retained frame's
        # draws were read from.
        cache.retained_frame = None
    if selected == "winding":
        from maniml.web.winding_geometry import serialize_scene as serialize_winding
        return serialize_winding(scene, cache)
    return _serialize_triangle_scene(scene, cache, renderer=selected)


# The renderer names the viewer's selector and MANIML_RENDERER speak.
# "triangles" is the default stack: the Phase A driver fed what the
# generators' defaults select (DEFAULT_FILL, DEFAULT_SURFACE and
# programs.DEFAULT_MODE), each overridden by its environment flag
# (MANIML_FILL, MANIML_SURFACE, MANIML_PROGRAMS). Native capture and the
# export recorder draw it, so a default that flips flips there too
# (docs/phase_b4_plan.md, "The flips"). "phase_a" and "phase_b" force the
# two ends whatever the defaults or the environment say — Phase A (meshes,
# grids, programs off) and the whole Phase B stack (patch fills, net
# surfaces, GPU programs; docs/phase_b_plan.md) — so both stay selectable
# from the dropdown, and the golden pin holds them
# (tests/test_retained_frame.py): no flip can move a pinned byte.
# "winding" is Original 2D.
RENDERERS = ("triangles", "phase_a", "phase_b", "winding")
# What a forced renderer draws: (fill, surface, programs).
FORCED_STACKS = {"phase_a": ("meshes", "grids", "off"), "phase_b": ("patches", "nets", "gpu")}
# The generators "triangles" draws where no environment flag says otherwise.
DEFAULT_FILL = "meshes"
DEFAULT_SURFACE = "grids"


def _serialize_triangle_scene(scene, cache, *, renderer: str = "triangles"):
    """One source-to-operation path for viewer, baked export and native output."""
    from maniml.web.generated_geometry import serialize_generated_frame
    from maniml.web.retained_frame import RetainedFrame, retained_frame_enabled
    from maniml.web.triangle_geometry import LyonFillTessellator
    from maniml.web.triangle_scene import TriangleMeshCache, prepare_triangle_frame

    state = cache if cache is not None else GeometryCache()
    border_generator = os.environ.get("MANIML_BORDER_GENERATOR", "gpu")
    if border_generator not in ("cpu", "gpu"):
        raise ValueError("MANIML_BORDER_GENERATOR must be 'cpu' or 'gpu'")
    # Phase A's CPU fill meshes or the patch fill (docs/phase_b1_plan.md),
    # which draws from the GPU border stage's curve records, so it needs the
    # GPU border generator.
    forced = FORCED_STACKS.get(renderer)
    fill_generator = forced[0] if forced else os.environ.get("MANIML_FILL", DEFAULT_FILL)
    if fill_generator not in ("meshes", "patches"):
        raise ValueError("MANIML_FILL must be 'meshes' or 'patches'")
    if fill_generator == "patches" and border_generator != "gpu":
        raise ValueError("MANIML_FILL=patches requires MANIML_BORDER_GENERATOR=gpu")
    # B5.1 (docs/phase_b4_plan.md): what a patch fill's curve records and its
    # path's stroke instances are sent as. "records" (the default) packs
    # them on the CPU; "rows" sends the path's rows and each driver finalizes
    # them (row_finalize.wgsl). Without patches there is nothing to source.
    patch_source = os.environ.get("MANIML_PATCH_SOURCE", "records")
    if patch_source not in ("records", "rows"):
        raise ValueError("MANIML_PATCH_SOURCE must be 'records' or 'rows'")
    if fill_generator != "patches":
        patch_source = "records"
    # Phase B2 (docs/phase_b2_plan.md): surfaces as control nets the GPU
    # evaluates at screen density, or the grid the CPU evaluates from them.
    surface_generator = forced[1] if forced else os.environ.get("MANIML_SURFACE", DEFAULT_SURFACE)
    if surface_generator not in ("grids", "nets"):
        raise ValueError("MANIML_SURFACE must be 'grids' or 'nets'")
    # Phase B3 (docs/phase_b3_plan.md): a supported animation's frames as a
    # program the Phase B stages evaluate; a filled path's draws from the
    # patch fill. Under strokes (B5.3, docs/phase_b4_plan.md) only a path
    # without fill is a program, whose stroke Phase A draws from the
    # program's rows, so it needs no patch fill.
    program_mode = forced[2] if forced else programs.env_mode()
    if program_mode in ("shadow", "gpu") and fill_generator != "patches":
        raise ValueError("MANIML_PROGRAMS=shadow or gpu requires MANIML_FILL=patches")
    if (state.border_generator != border_generator or state.fill_generator != fill_generator
            or state.patch_source != patch_source or state.surface_generator != surface_generator
            or state.program_mode != program_mode):
        state.reset()
        state.border_generator = border_generator
        state.fill_generator = fill_generator
        state.patch_source = patch_source
        state.surface_generator = surface_generator
        state.program_mode = program_mode
        state.retained_frame = None
        if state.triangle_meshes is not None:
            state.triangle_meshes.gpu_border_cache.clear()
    if state.triangle_tessellator is None:
        state.triangle_tessellator = LyonFillTessellator()
        state.triangle_meshes = TriangleMeshCache()
    # The retained frame (docs/phase_b4_plan.md, tier 1) writes the same
    # bytes. Only one that saw every frame of this cache's history can
    # trust its draws, so a frame serialized without it drops it; a frame
    # serialized without a cache has no history to keep draws across.
    if not retained_frame_enabled() or cache is None:
        state.retained_frame = None
    elif getattr(state, "retained_frame", None) is None:
        state.retained_frame = RetainedFrame()
    retained = state.retained_frame
    options = dict(mesh_cache=state.triangle_meshes, fill_borders=True,
                   gpu_borders=border_generator == "gpu",
                   patch_fills=fill_generator == "patches",
                   patch_rows=patch_source == "rows",
                   net_surfaces=surface_generator == "nets",
                   programs=program_mode != "off")
    # The header names the selection that made the frame, so the page's
    # selection drops another's frames across a switch, except that Phase
    # A's frames say "triangles": they are the bytes Phase A has always
    # written, which the golden pin holds and every recording names.
    stamp = "phase_b" if renderer == "phase_b" else "triangles"
    with performance.stage("geometry.triangle_prepare"):
        if retained is None:
            frame = prepare_triangle_frame(scene, state.triangle_tessellator, **options)
        else:
            frame = retained.prepare(scene, state.triangle_tessellator, **options)
        frame.samples = 4
        frame.supersample = 2
    with performance.stage("geometry.triangle_encode"):
        if retained is None:
            message = serialize_generated_frame(frame, scene.camera.uniforms, cache, renderer=stamp)
        else:
            message = retained.encode(frame, scene.camera.uniforms, cache, renderer=stamp)
    performance.increment("geometry.serialize.calls")
    if message is not None:
        performance.increment("geometry.serialized_bytes", len(message))
    performance.gauge("geometry.batch_count", len(frame.draws))
    performance.gauge("geometry.triangle_retained_bytes", frame.mesh_cache_stats["retained_bytes"])
    if retained is not None and performance.enabled:
        performance.gauge("geometry.retained_frame_bytes", retained.retained_bytes())
    return message


def parse_geometry_message(message: bytes):
    """Inverse of serialize_scene, for tests and tooling: returns
    (header dict, vertex bytes)."""
    assert message[0] == GEOMETRY_MESSAGE_TYPE
    (header_len,) = struct.unpack_from("<I", message, 1)
    header = json.loads(message[5:5 + header_len].decode())
    return header, message[5 + header_len:]


# The header fields a delta sends only when they change, and the order a
# full frame lists every field in (generated_geometry.assemble_message).
STREAM_FIELDS = ("camera", "background", "resolution", "samples", "supersample", "limitations")
FULL_FIELDS = ("renderer", "camera", "background", "resolution", "samples", "supersample", "batches",
               "paint_data", "border_data", "object_data", "net_data", "program_data", "texture_data",
               "unsupported", "limitations")


def expand_delta(previous, message):
    """The format 7 full frame a format 8 message stands for, for tests and
    tooling: (header, payload), where json.dumps(header) and the payload
    are the bytes the same cache history writes when its receivers have not
    negotiated format 8. ``previous`` is the header this returned for the
    message before in the stream (None before an epoch's full frame);
    ``message`` is the message's bytes, or None for a frame that changed
    nothing and was not sent.

    A full frame loses its epoch and frame number. A delta's frame is the
    previous one's batches as a receiver holds them (held_batch: no bytes,
    no offsets, no run layout), its splices applied (each replaces
    ``removed`` batches from ``at``, in the previous frame's order, by the
    batches it carries, as sent), its scalars ops written into the
    programs they name (by index in the new frame), each field it omits
    the previous frame's, and the definition tables it carries."""
    from maniml.web.generated_geometry import held_batch

    if message is None:
        header, payload = {"splices": [], "scalars": []}, b""
    else:
        header, payload = parse_geometry_message(message)
        if header["format_version"] != GEOMETRY_FORMAT_VERSION:
            raise ValueError("expand_delta reads format 8 messages")
        if "base" not in header:
            full = {"format_version": FULL_FRAME_FORMAT_VERSION}
            full.update((key, value) for key, value in header.items()
                        if key not in ("format_version", "epoch", "frame"))
            return full, payload
    if previous is None:
        raise ValueError("a delta needs the frame it was taken against")
    batches, read = [], 0
    kept = [held_batch(batch) for batch in previous["batches"]]
    for at, removed, inserted in header["splices"]:
        batches.extend(kept[read:at])
        batches.extend(inserted)
        read = at + removed
    batches.extend(kept[read:])
    for index, scalars in header["scalars"]:
        batch = batches[index]
        batches[index] = {**batch, "program": {**batch["program"], "scalars": scalars}}
    full = {"format_version": FULL_FRAME_FORMAT_VERSION}
    for key in FULL_FIELDS:
        if key == "batches":
            full[key] = batches
        elif key.endswith("_data"):
            full[key] = header.get(key, {})
        else:
            full[key] = header.get(key, previous[key])
    return full, payload

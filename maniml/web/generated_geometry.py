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
from maniml.web import gpu_net_geometry, gpu_program_geometry


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


def _net_payload(draw, previous, retained):
    net = np.asarray(draw.net)
    nu, nv, channels = draw.net_shape
    if (net.ndim != 2 or net.shape != (nu * nv, channels) or net.dtype != np.dtype("<f4")
            or nu < 3 or nv < 3 or nu % 2 == 0 or nv % 2 == 0):
        raise ValueError("invalid generated net layout")
    if not net.flags.c_contiguous:
        net = np.ascontiguousarray(net)
    memo = previous.get(id(net))
    if memo is not None and memo[0] is net:
        digest = memo[1]
    else:
        if not np.isfinite(net).all():
            raise ValueError("net control points must be finite")
        identity = hashlib.blake2b(digest_size=16)
        identity.update(b"maniml.net.f32.v1\0" + struct.pack("<QQ", nu, nv))
        identity.update(memoryview(net).cast("B"))
        digest = identity.hexdigest()
    if _immutable(net):
        retained[id(net)] = (net, digest)
    return digest, net


def _supersample(frame):
    supersample = getattr(frame, "supersample", 1)
    if type(supersample) is not int or supersample not in (1, 2):
        raise ValueError("supersample must be 1 or 2")
    return supersample


class BatchRecord:
    """What encode_draw registered for one batch, for a caller that reuses
    the batch in later messages without encoding it again (the retained
    frame, docs/phase_b4_plan.md): ``names``, what the receiver holds once
    a message carrying the batch is sent (its content hash and the
    prefixed definition names commit records), and ``memos``, the
    (table, key) of each digest memo the batch left for the next message.
    MessageParts.carry registers both again."""

    __slots__ = ("names", "memos")

    def __init__(self):
        self.names = set()
        self.memos = []


class MessageParts:
    """What one message's batches contribute beside their descriptors.

    encode_draw appends the vertex and index bytes of each batch the
    receiver lacks to ``blobs``, in batch order, and records the
    definitions every batch references (paint, curve records, object
    tables, nets, program rows, textures) by content hash;
    assemble_message lays the definitions the receiver lacks after the
    batch bytes; commit then records on ``cache`` what the receiver holds
    and the digest memos the next message reuses. A cache of None is a
    receiver that holds nothing, and nothing is recorded. A batch reused
    from an earlier message without being encoded is named through
    ``carry``.
    """

    def __init__(self, cache=None):
        self.cache = cache
        self.blobs, self.offset = [], 0
        self.current_hashes, self.texture_hashes = set(), set()
        self.previous_payloads = getattr(cache, "generated_payloads", {})
        self.retained_payloads = {}
        self.previous_paints = getattr(cache, "generated_paints", {})
        self.retained_paints, self.paints = {}, {}
        self.previous_borders = getattr(cache, "generated_borders", {})
        self.retained_borders, self.borders = {}, {}
        self.previous_objects = getattr(cache, "generated_objects", {})
        self.retained_objects, self.object_tables = {}, {}
        self.previous_nets = getattr(cache, "generated_nets", {})
        self.retained_nets, self.nets = {}, {}
        self.previous_rows = getattr(cache, "generated_rows", {})
        self.retained_rows, self.row_sources = {}, {}
        self.carried = []

    def carry(self, record):
        """Name a batch this message reuses from an earlier one, as
        encode_draw named it then (``record``). The caller has checked
        that the receiver holds everything the batch names, so it adds no
        bytes and no definitions; commit records its names again, and its
        digest memos, found in the previous message's, stay for the next.
        Without this a batch reused frame after frame would drop out of
        what the receiver is recorded as holding after one message."""
        self.carried.append(record.names)
        for table, key in record.memos:
            previous, retained = self._memo_tables(table)
            entry = previous.get(key)
            if entry is not None:
                retained[key] = entry

    def _memo_tables(self, table):
        """(previous, retained) digest memos of ``table``, a BatchRecord's
        name for one of them."""
        return (getattr(self, "previous_" + table), getattr(self, "retained_" + table))

    def held(self, key):
        """Whether the receiver holds ``key`` from the previous message."""
        return self.cache is not None and key in self.cache.sent

    def append(self, raw):
        """Lay ``raw`` next in the payload; returns its offset."""
        offset = self.offset
        self.blobs.append(raw)
        self.offset += len(raw)
        return offset

    def definitions(self, prefix, table):
        """Append the definitions of ``table`` the receiver lacks; returns
        their offsets and sizes by hash, as the header names them."""
        data = {}
        for key, array in table.items():
            if not self.held(f"{prefix}:{key}"):
                raw = array.tobytes()
                data[key] = {"offset": self.append(raw), "nbytes": len(raw)}
        return data

    def commit(self):
        """Record what the receiver holds once the message is sent: this
        message's hashes and definitions, and nothing it did not name."""
        cache = self.cache
        if cache is None:
            return
        cache.sent = (self.current_hashes | {f"tex:{key}" for key in self.texture_hashes}
                      | {f"paint:{key}" for key in self.paints})
        cache.sent.update(f"border:{key}" for key in self.borders)
        cache.sent.update(f"objects:{key}" for key in self.object_tables)
        cache.sent.update(f"net:{key}" for key in self.nets)
        cache.sent.update(f"rows:{key}" for key in self.row_sources)
        for names in self.carried:
            cache.sent.update(names)
        cache.generated_nets = self.retained_nets
        cache.generated_rows = self.retained_rows
        cache.generated_payloads = self.retained_payloads
        cache.generated_paints = self.retained_paints
        cache.generated_borders = self.retained_borders
        cache.generated_objects = self.retained_objects


def serialize_generated_frame(frame, camera_uniforms, cache=None, *, renderer="triangles"):
    """Pack a prepared frame; both drivers consume exactly these operations.

    ``renderer`` is the name the client selected: it draws only frames
    stamped with its own selection, so a Phase B frame says so."""
    _supersample(frame)
    camera = {key: _jsonable(value) for key, value in camera_uniforms.items()}
    parts = MessageParts(cache)
    batches = [batch for batch in (encode_draw(draw, camera, parts) for draw in frame.draws)
               if batch is not None]
    message = assemble_message(frame, camera, batches, parts, renderer=renderer)
    parts.commit()
    return message


def encode_draw(draw, camera, parts, record=None):
    """One draw's batch descriptor, or None when it draws nothing.

    ``camera`` is the message's normalized camera uniforms, which the batch
    omits where the draw's own agree; ``parts`` is the message's
    MessageParts, which receives the draw's bytes (unless the receiver
    holds them) and every definition the batch names. A ``record`` (a
    BatchRecord) is told the names and digest memos the batch registers,
    for a caller that reuses the batch later through MessageParts.carry.
    """
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
        return None
    border = getattr(draw, "border_sources", None)
    objects = getattr(draw, "fill_objects", None)
    border_hash, capacity, layout, objects_hash = None, None, None, None
    net_hash, net_descriptor = None, None
    indices = None if draw.indices is None else np.asarray(draw.indices)
    net = getattr(draw, "net", None)
    # A program (docs/phase_b3_plan.md): row sources sent once by hash,
    # scalars per frame; the batch's curve records, strokes or net come
    # from the driver's evaluation, so no retained source travels.
    program = getattr(draw, "program", None)
    program_descriptor = None
    if program is not None:
        kind, source_rows, scalars = program["kind"], program["sources"], program["scalars"]
        hashes = []
        for source in source_rows:
            source = np.asarray(source)
            if source.dtype != np.dtype("<f4") or source.ndim != 2 or not source.flags.c_contiguous:
                raise ValueError("program sources must be contiguous float32 rows")
            memo = parts.previous_rows.get(id(source))
            digest = memo[1] if memo is not None and memo[0] is source else gpu_program_geometry.rows_hash(source)
            if _immutable(source):
                parts.retained_rows[id(source)] = (source, digest)
                if record is not None:
                    record.memos.append(("rows", id(source)))
            parts.row_sources[digest] = source
            if record is not None:
                record.names.add(f"rows:{digest}")
            hashes.append(digest)
        shapes = {np.asarray(s).shape for s in source_rows}
        if len(shapes) != 1:
            raise ValueError("program sources must be row-aligned")
        (rows, channels), = shapes
        program_descriptor = {"kind": kind, "sources": hashes, "scalars": [float(v) for v in scalars],
                              "rows": int(rows), "channels": int(channels)}
        gpu_program_geometry.validate_program(
            program_descriptor, PIPELINE_STRIDES[base] if base in ("surface", "texsurface") else None)
        if base == "stroke":
            if len(vertices) or indices is not None or border is not None:
                raise ValueError("a program stroke draw carries no vertices")
            curves = gpu_program_geometry.curve_count(rows)
            if draw.instances != curves:
                raise ValueError("a program stroke draw has one instance per curve")
        elif base == "patch":
            if border is not None or len(vertices):
                raise ValueError("a program patch draw carries no curve records")
            border_hash = gpu_program_geometry.program_key(kind, hashes)
            capacity = validate_capacity(getattr(draw, "border_capacity", MAX_VERTICES_PER_CURVE))
            layout = validate_patch_layout(getattr(draw, "patch_layout", None), gpu_program_geometry.curve_count(rows))
            objects_hash, objects = _objects_payload(objects, layout, parts.previous_objects, parts.retained_objects)
            parts.object_tables[objects_hash] = objects
            if record is not None:
                _note(record, parts, "objects", f"objects:{objects_hash}", objects)
            if draw.count != patch_draw_count(layout, capacity):
                raise ValueError("invalid patch fill draw count")
            border = True  # a curve record source exists, in the driver
        elif base in ("surface", "texsurface"):
            if net is not None or len(vertices):
                raise ValueError("a program net draw carries its net in its program")
            net = True
        else:
            raise ValueError("programs apply to patch, stroke and surface draws")
    if net is not None:
        # A surface net: no vertices of its own; the driver evaluates the
        # net into patches * (capacity + 1)² vertices and builds the index
        # pattern for the capacity.
        if (base not in ("surface", "texsurface") or indices is not None or draw.instances != 1
                or len(vertices) or (border is not None and program is None) or objects is not None):
            raise ValueError("a surface net draw carries only its net")
        if program is not None:
            net_hash = gpu_program_geometry.program_key(program["kind"], program_descriptor["sources"])
        else:
            net_hash, net = _net_payload(draw, parts.previous_nets, parts.retained_nets)
            parts.nets[net_hash] = net
            if record is not None:
                _note(record, parts, "nets", f"net:{net_hash}", net)
        nu, nv, channels = draw.net_shape
        if channels * 4 != PIPELINE_STRIDES[base]:
            raise ValueError("net channels do not match the pipeline's vertex layout")
        net_capacity = gpu_net_geometry.validate_capacity(getattr(draw, "net_capacity", 2))
        density = float(getattr(draw, "net_density", 0.0))
        if not np.isfinite(density) or density < 0:
            raise ValueError("net density must be finite and nonnegative")
        patches = ((nu - 1) // 2) * ((nv - 1) // 2)
        if draw.count != patches * gpu_net_geometry.indices_per_patch(net_capacity):
            raise ValueError("invalid surface net draw count")
        net_descriptor = {"hash": net_hash, "nu": nu, "nv": nv, "channels": channels,
                          "capacity": net_capacity, "density": density}
    if base == "patch" and program is not None:
        pass  # validated with the program above
    elif base == "patch":
        # A patch fill run: curve records, the object table and the
        # (curve count, bordered) layout; no vertices or indices of its own.
        if (border is None or objects is None or indices is not None or draw.instances != 1
                or len(vertices)):
            raise ValueError("patch fill requires curve records, an object table and no vertices")
        border_hash, border = _border_payload(border, parts.previous_borders, parts.retained_borders)
        parts.borders[border_hash] = border
        if record is not None:
            _note(record, parts, "borders", f"border:{border_hash}", border)
        capacity = validate_capacity(getattr(draw, "border_capacity", MAX_VERTICES_PER_CURVE))
        layout = validate_patch_layout(getattr(draw, "patch_layout", None), len(border))
        objects_hash, objects = _objects_payload(objects, layout, parts.previous_objects, parts.retained_objects)
        parts.object_tables[objects_hash] = objects
        if record is not None:
            _note(record, parts, "objects", f"objects:{objects_hash}", objects)
        if draw.count != patch_draw_count(layout, capacity):
            raise ValueError("invalid patch fill draw count")
    elif border is not None and program is None:
        if base not in ("surface", "paint") or indices is None or draw.instances != 1:
            raise ValueError("GPU border recipe requires one indexed surface operation")
        border_hash, border = _border_payload(border, parts.previous_borders, parts.retained_borders)
        parts.borders[border_hash] = border
        if record is not None:
            _note(record, parts, "borders", f"border:{border_hash}", border)
        capacity = validate_capacity(getattr(draw, "border_capacity", MAX_VERTICES_PER_CURVE))
        layout = getattr(draw, "border_layout", None)
        if layout is None:
            raise ValueError("GPU border recipes require their run layout")
        layout = validate_layout(layout, len(indices), len(vertices), len(border))
    elif objects is not None:
        raise ValueError("an object table belongs to a patch fill draw")
    if program is not None and base == "patch":
        output_vertices = capacity * gpu_program_geometry.curve_count(program_descriptor["rows"])
    elif program is not None and base == "stroke":
        output_vertices = 3 * gpu_program_geometry.curve_count(program_descriptor["rows"])
    else:
        output_vertices = len(vertices) + (0 if border is None else capacity * len(border))
    if net_descriptor is not None:
        patches = ((net_descriptor["nu"] - 1) // 2) * ((net_descriptor["nv"] - 1) // 2)
        output_vertices = patches * gpu_net_geometry.vertices_per_patch(net_descriptor["capacity"])
    if net_descriptor is not None:
        pass  # checked above
    elif indices is not None:
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
        if draw.count < 4 or draw.count > 64 or draw.count % 2 or (
                program is None and draw.instances * 3 > len(vertices)):
            raise ValueError("invalid generated stroke draw count")
    payload_key = (draw.pipeline, id(vertices), id(indices),
                   None if border is None or border is True else (len(border), tuple(map(tuple, layout))),
                   objects_hash, net_hash,
                   None if program_descriptor is None else (program_descriptor["kind"], tuple(program_descriptor["sources"])))
    retained = parts.previous_payloads.get(payload_key)
    if retained is not None and retained[0] is vertices and retained[1] is indices:
        content_hash = retained[2]
    else:
        identity = hashlib.blake2b(digest_size=16)
        identity.update(draw.pipeline.encode())
        identity.update(b"\0indexed\0" if indices is not None else b"\0plain\0")
        if border is not None and border is not True:
            # The run layout decides where each object's strips interleave;
            # the reserved capacity does not change what is drawn, so it
            # stays out of the identity and a zoom that raises it resends
            # nothing.
            identity.update(b"\0border\0" + struct.pack("<Q", len(border)))
            identity.update(struct.pack(f"<{len(layout[0]) * len(layout)}Q", *(v for part in layout for v in part)))
        if program_descriptor is not None:
            # Scalars change per frame and stay out of the identity.
            identity.update(b"\0program\0" + program_descriptor["kind"].encode()
                            + b"".join(h.encode() for h in program_descriptor["sources"]))
            if layout is not None:
                identity.update(struct.pack(f"<{len(layout[0]) * len(layout)}Q", *(v for part in layout for v in part)))
        if objects_hash is not None:
            identity.update(b"\0objects\0" + objects_hash.encode())
        if net_hash is not None:
            identity.update(b"\0net\0" + net_hash.encode())
        # Frame both byte streams, and hash their views without allocating
        # another frame-sized copy. Mutable diagnostic data is always read.
        identity.update(struct.pack("<QQ", vertices.nbytes, 0 if indices is None else indices.nbytes))
        identity.update(memoryview(vertices).cast("B"))
        if indices is not None:
            identity.update(memoryview(indices).cast("B"))
        content_hash = identity.hexdigest()
    if _immutable(vertices) and _immutable(indices):
        parts.retained_payloads[payload_key] = (vertices, indices, content_hash)
        if record is not None:
            record.memos.append(("payloads", payload_key))
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
    if program_descriptor is not None:
        batch["program"] = program_descriptor
        if base == "stroke":
            batch["fill_num_verts"] = 0
    if border is True:
        batch["fill_num_verts"] = 0
        batch["border"] = {"hash": border_hash, "num_curves": gpu_program_geometry.curve_count(program_descriptor["rows"]),
                           "capacity": capacity}
    elif border is not None:
        batch["fill_num_verts"] = len(vertices)
        batch["border"] = {"hash": border_hash, "num_curves": len(border), "capacity": capacity}
    if objects_hash is not None:
        batch["objects"] = {"hash": objects_hash, "count": len(objects)}
    if net_descriptor is not None:
        batch["fill_num_verts"] = 0
        batch["net"] = net_descriptor
    if getattr(draw, "coverage", False):
        if base not in ("surface", "paint"):
            raise ValueError("coverage ownership requires triangle surface geometry")
        batch["coverage"] = True
    if base == "paint" or (base == "patch" and getattr(draw, "paint", None) is not None):
        paint_hash, paint = _paint_payload(getattr(draw, "paint", None),
                                           parts.previous_paints, parts.retained_paints)
        batch["paint_hash"] = paint_hash
        parts.paints[paint_hash] = paint
        if record is not None:
            _note(record, parts, "paints", f"paint:{paint_hash}", paint)
    textures = getattr(draw, "textures", None)
    if textures:
        batch["textures"] = textures
        parts.texture_hashes.update(textures.values())
        if record is not None:
            record.names.update(f"tex:{key}" for key in textures.values())
    if parts.held(content_hash):
        batch["cached"] = True
    else:
        # The run layout belongs to the geometry: a receiver that holds
        # the fill bytes holds the layout too, so it travels once.
        if border is not None:
            batch["border"]["layout"] = layout
        batch["offset"] = parts.append(vertices.tobytes())
        if indices is not None:
            batch["index_offset"] = parts.append(indices.tobytes())
    parts.current_hashes.add(content_hash)
    if record is not None:
        record.names.add(content_hash)
    return batch


def _note(record, parts, table, name, array):
    """Tell ``record`` the definition ``name`` a batch names and the digest
    memo the payload helper left for ``array`` in ``table``, if it left one
    (it keeps only immutable arrays)."""
    record.names.add(name)
    if id(array) in getattr(parts, "retained_" + table):
        record.memos.append((table, id(array)))


def held_batch(batch):
    """The descriptor encode_draw writes for ``batch``'s draw once the
    receiver holds its content hash, ``batch`` being either form: no bytes
    of its own, so no offsets, and no run layout, which travelled with the
    bytes; ``cached`` last, where encode_draw sets it."""
    held = {key: value for key, value in batch.items() if key not in ("offset", "index_offset", "cached")}
    border = held.get("border")
    if border is not None and "layout" in border:
        held["border"] = {key: value for key, value in border.items() if key != "layout"}
    held["cached"] = True
    return held


def assemble_message(frame, camera, batches, parts, *, renderer="triangles"):
    """The message: header, then every batch's bytes in batch order, then
    the definitions the receiver lacks. ``batches`` are encode_draw's
    descriptors in draw order, their bytes and definitions in ``parts``;
    or, from a caller that keeps descriptors as JSON text across messages,
    the text json.dumps writes between their list's brackets (each
    descriptor's own text, joined by ", "), which gives the same bytes.
    The receiver's state is untouched until ``parts.commit()``."""
    supersample = _supersample(frame)
    # Definitions follow the batch bytes in this order; the header lists
    # them in its own.
    paint_data = parts.definitions("paint", parts.paints)
    border_data = parts.definitions("border", parts.borders)
    program_data = parts.definitions("rows", parts.row_sources)
    net_data = parts.definitions("net", parts.nets)
    object_data = parts.definitions("objects", parts.object_tables)
    texture_data = {}
    for key in sorted(parts.texture_hashes):
        if not parts.held(f"tex:{key}"):
            raw = getattr(frame, "texture_data", {}).get(key)
            if raw is None:
                raw = _TEXTURE_BY_HASH[key]
            texture_data[key] = {"offset": parts.append(raw), "nbytes": len(raw)}
    joined = isinstance(batches, str)
    header = {"format_version": GEOMETRY_FORMAT_VERSION, "renderer": renderer,
              "camera": camera, "background": list(frame.background),
              "resolution": list(frame.resolution), "samples": frame.samples,
              "supersample": supersample,
              "batches": [] if joined else batches, "paint_data": paint_data, "border_data": border_data,
              "object_data": object_data, "net_data": net_data, "program_data": program_data,
              "texture_data": texture_data,
              "unsupported": [], "limitations": list(frame.limitations)}
    text = json.dumps(header)
    if joined and batches:
        # The empty list's brackets are where the texts go. Outside a
        # string only the key can spell this: json.dumps escapes every
        # quote inside one.
        at = text.index('"batches": [') + len('"batches": [')
        text = text[:at] + batches + text[at:]
    encoded = text.encode()
    return b"".join((bytes([GEOMETRY_MESSAGE_TYPE]), struct.pack("<I", len(encoded)),
                     encoded, *parts.blobs))

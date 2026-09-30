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
    FULL_FRAME_FORMAT_VERSION, GEOMETRY_FORMAT_VERSION, GEOMETRY_MESSAGE_TYPE, STREAM_FIELDS, _jsonable,
    _TEXTURE_BY_HASH,
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


def _net_descriptor(draw, base, parts, record, net_hash=None):
    """A net draw's descriptor (hash, shape, capacity, density), its
    control points put in the message's net table unless ``net_hash``
    names a program's evaluated rows instead."""
    if net_hash is None:
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
    return {"hash": net_hash, "nu": nu, "nv": nv, "channels": channels,
            "capacity": net_capacity, "density": density}


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
        # (previous, retained) digest memos by a BatchRecord's table name:
        # carry reads them for every memo of every batch a message reuses.
        self.memo_tables = {"payloads": (self.previous_payloads, self.retained_payloads),
                            "paints": (self.previous_paints, self.retained_paints),
                            "borders": (self.previous_borders, self.retained_borders),
                            "objects": (self.previous_objects, self.retained_objects),
                            "nets": (self.previous_nets, self.retained_nets),
                            "rows": (self.previous_rows, self.retained_rows)}

    def carry(self, record):
        """Name a batch this message reuses from an earlier one, as
        encode_draw named it then (``record``). The caller has checked
        that the receiver holds everything the batch names, so it adds no
        bytes and no definitions; commit records its names again, and its
        digest memos, found in the previous message's, stay for the next.
        Without this a batch reused frame after frame would drop out of
        what the receiver is recorded as holding after one message."""
        self.carried.append(record.names)
        tables = self.memo_tables
        for table, key in record.memos:
            previous, retained = tables[table]
            entry = previous.get(key)
            if entry is not None:
                retained[key] = entry

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
    stamped with its own selection, so a Phase B frame says so. A cache
    whose receivers negotiated format 8 is sent the stream's next message
    (stream_message), None when the frame changes nothing."""
    _supersample(frame)
    camera = {key: _jsonable(value) for key, value in camera_uniforms.items()}
    parts = MessageParts(cache)
    batches = [batch for batch in (encode_draw(draw, camera, parts) for draw in frame.draws)
               if batch is not None]
    if getattr(cache, "deltas", False):
        texts = [json.dumps(batch) for batch in batches]
        sent = [SentBatch(batch, text if batch.get("cached") else None) for batch, text in zip(batches, texts)]
        message = stream_message(frame, camera, sent, texts, parts, renderer=renderer)
    else:
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
    # A run of nets (docs/phase_b4_plan.md, B5.7): the members' descriptors,
    # in order, one batch drawn in one draw over their evaluated outputs.
    net_members = getattr(draw, "net_members", None)
    # A program (docs/phase_b3_plan.md): row sources sent once by hash,
    # scalars per frame; the batch's curve records, strokes or net come
    # from the driver's evaluation, so no retained source travels.
    program = getattr(draw, "program", None)
    program_descriptor = None
    # Row sources (MANIML_PATCH_SOURCE=rows, docs/phase_b4_plan.md B5.1):
    # each object's rows, sent once by hash in the program sources' table
    # as their geometry (`rows`) and their paint (`row_paints`) since B5.8;
    # the driver finalizes them into the batch's curve records or stroke
    # instances, a frame's in one dispatch, so neither travels.
    row_sources = getattr(draw, "rows", None)
    row_hashes, paint_hashes, num_curves = None, None, None
    if row_sources is not None:
        if (program is not None or base not in ("patch", "stroke") or len(vertices) or indices is not None
                or border is not None or net is not None or net_members is not None):
            raise ValueError("row sources feed a patch or stroke draw that carries nothing else")
        # Each rows travels as its geometry, keyed on it alone, and its
        # paint (B5.8): a change of paint alone sends the paint.
        row_parts = getattr(draw, "row_parts", None)
        if row_parts is None:
            row_parts = [gpu_program_geometry.split_rows(source) for source in row_sources]
        if len(row_parts) != len(row_sources):
            raise ValueError("a row source's geometry and paint go with its rows")
        counts = []
        for source, (geometry, paint) in zip(row_sources, row_parts):
            count = len(source)
            if (source.shape[1] != gpu_program_geometry.ROW_FLOATS or count < 3 or count % 2 == 0
                    or geometry.shape != (count, gpu_program_geometry.GEOMETRY_FLOATS)
                    or paint.shape not in ((1, gpu_program_geometry.PAINT_FLOATS),
                                           (count, gpu_program_geometry.PAINT_FLOATS))):
                raise ValueError("row sources must be VMobject rows, an odd count of at least three")
            counts.append(gpu_program_geometry.curve_count(count))
        row_hashes = _row_digests([geometry for geometry, _ in row_parts], parts, record, "row sources")
        paint_hashes = _row_digests([paint for _, paint in row_parts], parts, record, "row paints")
        num_curves = sum(counts)
        if base == "patch":
            border_hash = gpu_program_geometry.rows_key(row_hashes, paint_hashes)
            capacity = validate_capacity(getattr(draw, "border_capacity", MAX_VERTICES_PER_CURVE))
            layout = validate_patch_layout(getattr(draw, "patch_layout", None), num_curves)
            if [curves for curves, _, _ in layout] != counts:
                raise ValueError("patch run layout does not match its row sources")
            objects_hash, objects = _objects_payload(objects, layout, parts.previous_objects, parts.retained_objects)
            parts.object_tables[objects_hash] = objects
            if record is not None:
                _note(record, parts, "objects", f"objects:{objects_hash}", objects)
            if draw.count != patch_draw_count(layout, capacity):
                raise ValueError("invalid patch fill draw count")
            border = True  # a curve record source exists, in the driver
        elif draw.instances != num_curves:
            raise ValueError("a row-sourced stroke draw has one instance per curve")
    if program is not None and net_members is not None:
        raise ValueError("a program is drawn alone, not in a run of nets")
    if program is not None:
        kind, source_rows, scalars = program["kind"], program["sources"], program["scalars"]
        hashes = _row_digests(source_rows, parts, record, "program sources")
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
    if net_members is not None:
        # A run of nets: each member's control points in the net table and
        # its descriptor in the batch's list; the driver evaluates each into
        # its span of one output, patches * (capacity + 1)² vertices a
        # member after the members before it, and draws the index pattern
        # of each member's steps in one draw.
        if (base != "surface" or indices is not None or draw.instances != 1 or len(vertices)
                or border is not None or objects is not None or net is not None or len(net_members) < 2
                or any(getattr(member, "net", None) is None or getattr(member, "program", None) is not None
                       for member in net_members)):
            raise ValueError("a run of surface nets carries only its members' nets")
        net_descriptor = [_net_descriptor(member, base, parts, record) for member in net_members]
        if draw.count != sum(member.count for member in net_members):
            raise ValueError("invalid surface net run draw count")
        net_hash = tuple(descriptor["hash"] for descriptor in net_descriptor)
    elif net is not None:
        # A surface net: no vertices of its own; the driver evaluates the
        # net into patches * (capacity + 1)² vertices and builds the index
        # pattern of the steps it evaluates at (B5.7).
        if (base not in ("surface", "texsurface") or indices is not None or draw.instances != 1
                or len(vertices) or (border is not None and program is None) or objects is not None):
            raise ValueError("a surface net draw carries only its net")
        net_descriptor = _net_descriptor(
            draw, base, parts, record,
            None if program is None else gpu_program_geometry.program_key(program["kind"],
                                                                           program_descriptor["sources"]))
        net_hash = net_descriptor["hash"]
    if base == "patch" and (program is not None or row_sources is not None):
        pass  # validated with the program or the row sources above
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
    if program is not None:
        num_curves = gpu_program_geometry.curve_count(program_descriptor["rows"])
    if num_curves is not None and base == "patch":
        output_vertices = capacity * num_curves
    elif num_curves is not None and base == "stroke":
        output_vertices = 3 * num_curves
    else:
        output_vertices = len(vertices) + (0 if border is None else capacity * len(border))
    if net_descriptor is not None:
        output_vertices = sum(((member["nu"] - 1) // 2) * ((member["nv"] - 1) // 2)
                              * gpu_net_geometry.vertices_per_patch(member["capacity"])
                              for member in (net_descriptor if net_members is not None else (net_descriptor,)))
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
                num_curves is None and draw.instances * 3 > len(vertices)):
            raise ValueError("invalid generated stroke draw count")
    payload_key = (draw.pipeline, id(vertices), id(indices),
                   None if border is None or border is True else (len(border), tuple(map(tuple, layout))),
                   objects_hash, net_hash,
                   None if program_descriptor is None else (program_descriptor["kind"], tuple(program_descriptor["sources"])),
                   None if row_hashes is None else (tuple(row_hashes),
                                                     None if layout is None else tuple(map(tuple, layout))))
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
        if row_hashes is not None:
            # The geometry names the batch; its paint, like a records run's
            # curve records, is named beside it (row_paints, and the border
            # hash), so a change of paint alone keeps the batch (B5.8).
            identity.update(b"\0rows\0" + b"".join(h.encode() for h in row_hashes))
            if layout is not None:
                identity.update(struct.pack(f"<{len(layout[0]) * len(layout)}Q", *(v for part in layout for v in part)))
        if objects_hash is not None:
            identity.update(b"\0objects\0" + objects_hash.encode())
        if net_members is not None:
            identity.update(b"\0nets\0" + struct.pack("<Q", len(net_hash)) + b"".join(h.encode() for h in net_hash))
        elif net_hash is not None:
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
    if row_hashes is not None:
        batch["rows"] = row_hashes
        batch["row_paints"] = paint_hashes
        if base == "stroke":
            batch["fill_num_verts"] = 0
    if border is True:
        batch["fill_num_verts"] = 0
        batch["border"] = {"hash": border_hash, "num_curves": num_curves, "capacity": capacity}
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


def _row_digests(sources, parts, record, what):
    """The content hash of each of ``sources``, float32 rows, registered on
    ``parts`` as program sources (the one table of rows, sent once by
    hash) and noted on ``record``: a program's endpoints, or a draw's row
    sources."""
    hashes = []
    for source in sources:
        source = np.asarray(source)
        if source.dtype != np.dtype("<f4") or source.ndim != 2 or not source.flags.c_contiguous:
            raise ValueError(f"{what} must be contiguous float32 rows")
        # This message's memo first: an object's fill and stroke name one rows.
        memo = parts.retained_rows.get(id(source)) or parts.previous_rows.get(id(source))
        digest = memo[1] if memo is not None and memo[0] is source else gpu_program_geometry.rows_hash(source)
        if _immutable(source):
            parts.retained_rows[id(source)] = (source, digest)
            if record is not None:
                record.memos.append(("rows", id(source)))
        parts.row_sources[digest] = source
        if record is not None:
            record.names.add(f"rows:{digest}")
        hashes.append(digest)
    return hashes


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


def definition_tables(frame, parts):
    """Append the definitions the receiver lacks after the batch bytes, in
    the order both message forms lay them out, and return their tables as
    the header names them: paint, border, program, net, object, texture."""
    tables = {"paint_data": parts.definitions("paint", parts.paints),
              "border_data": parts.definitions("border", parts.borders),
              "program_data": parts.definitions("rows", parts.row_sources),
              "net_data": parts.definitions("net", parts.nets),
              "object_data": parts.definitions("objects", parts.object_tables)}
    texture_data = {}
    for key in sorted(parts.texture_hashes):
        if not parts.held(f"tex:{key}"):
            raw = getattr(frame, "texture_data", {}).get(key)
            if raw is None:
                raw = _TEXTURE_BY_HASH[key]
            texture_data[key] = {"offset": parts.append(raw), "nbytes": len(raw)}
    tables["texture_data"] = texture_data
    return tables


def _insert_list(text, key, items):
    """``text`` (json.dumps output) with ``items``, JSON text, written
    between the brackets of the empty list at ``key``. Outside a string
    only the key can spell '"key": [': json.dumps escapes every quote
    inside one."""
    if not items:
        return text
    at = text.index(f'"{key}": [') + len(key) + 5
    return text[:at] + items + text[at:]


def _pack(text, parts):
    encoded = text.encode()
    return b"".join((bytes([GEOMETRY_MESSAGE_TYPE]), struct.pack("<I", len(encoded)),
                     encoded, *parts.blobs))


def assemble_message(frame, camera, batches, parts, *, renderer="triangles", stream=None):
    """The message: header, then every batch's bytes in batch order, then
    the definitions the receiver lacks. ``batches`` are encode_draw's
    descriptors in draw order, their bytes and definitions in ``parts``;
    or, from a caller that keeps descriptors as JSON text across messages,
    the text json.dumps writes between their list's brackets (each
    descriptor's own text, joined by ", "), which gives the same bytes.
    ``stream``, the (epoch, frame number) of a format 8 full frame, makes
    it one: the format 7 frame with "format_version": 8 and those two after
    it, nothing else moved. The receiver's state is untouched until
    ``parts.commit()``."""
    supersample = _supersample(frame)
    tables = definition_tables(frame, parts)
    joined = isinstance(batches, str)
    if stream is None:
        header = {"format_version": FULL_FRAME_FORMAT_VERSION}
    else:
        header = {"format_version": GEOMETRY_FORMAT_VERSION, "epoch": stream[0], "frame": stream[1]}
    header.update({"renderer": renderer,
                   "camera": camera, "background": list(frame.background),
                   "resolution": list(frame.resolution), "samples": frame.samples,
                   "supersample": supersample,
                   "batches": [] if joined else batches, "paint_data": tables["paint_data"],
                   "border_data": tables["border_data"], "object_data": tables["object_data"],
                   "net_data": tables["net_data"], "program_data": tables["program_data"],
                   "texture_data": tables["texture_data"],
                   "unsupported": [], "limitations": list(frame.limitations)})
    text = json.dumps(header)
    if joined:
        text = _insert_list(text, "batches", batches)
    return _pack(text, parts)


class SentBatch:
    """A batch of a format 8 message as the next delta compares it: its
    content hash, its program's scalars (their text; None without a
    program) and the text of its held descriptor with the scalars left
    out, which is what a receiver resolves its slot from (made when first
    compared, unless the encoder already wrote the held form)."""

    __slots__ = ("hash", "scalars", "batch", "text")

    def __init__(self, batch, held_text=None):
        self.batch = batch
        self.hash = batch["hash"]
        program = batch.get("program")
        self.scalars = None if program is None else json.dumps(program["scalars"])
        self.text = held_text if program is None else None

    def key(self):
        if self.text is None:
            held = held_batch(self.batch)
            if self.scalars is not None:
                held["program"] = {**held["program"], "scalars": None}
            self.text = json.dumps(held)
        return self.text

    def same(self, other):
        """Whether ``other`` resolves to this batch's slot: one content,
        one held descriptor, its scalars aside. A batch sent with its bytes
        is never one the receiver held: its hash was not in the cache's
        ``sent``, which holds every hash of the message before. A run the
        retained frame kept is compared as the object it was last frame."""
        return other is self or (self.hash == other.hash and self.key() == other.key())


class SentFrame:
    """What a format 8 message left its receivers holding: its batches
    (SentBatch, in order) and the text of each header field a delta sends
    only when it changes (geometry.STREAM_FIELDS)."""

    __slots__ = ("batches", "fields")

    def __init__(self, batches, fields):
        self.batches = batches
        self.fields = fields


def diff_runs(last, runs):
    """The splices and scalars ops that turn the frame a receiver holds
    (``last``) into this one (``runs``), both SentBatch lists in draw
    order, a run being one batch.

    The runs both frames share at either end are kept (SentBatch.same, so
    a run kept across frames compares its identical text for free). Where
    the frames hold as many runs between those ends, each is compared
    with the one in its place and every maximal range that differs is a
    splice; otherwise the range between them is one. A splice is (at,
    removed, first, end): ``removed`` runs of ``last`` from ``at`` are
    replaced by runs[first:end]. A kept program run whose scalars moved
    is a scalars op, (its index in ``runs``, its SentBatch)."""
    m, n = len(last), len(runs)
    limit = min(m, n)
    scalars = []

    def keep(old, new, index):
        if new.scalars is not None and new.scalars != old.scalars:
            scalars.append((index, new))

    head = 0
    while head < limit and last[head].same(runs[head]):
        keep(last[head], runs[head], head)
        head += 1
    tail = 0
    while tail < limit - head and last[m - 1 - tail].same(runs[n - 1 - tail]):
        keep(last[m - 1 - tail], runs[n - 1 - tail], n - 1 - tail)
        tail += 1
    splices = []
    if m == n:
        i, end = head, m - tail
        while i < end:
            if last[i].same(runs[i]):
                keep(last[i], runs[i], i)
                i += 1
                continue
            j = i + 1
            while j < end and not last[j].same(runs[j]):
                j += 1
            splices.append((i, j - i, i, j))
            i = j
    else:
        splices.append((head, m - tail - head, head, n - tail))
    scalars.sort(key=lambda op: op[0])
    return splices, scalars


def stream_message(frame, camera, sent, texts, parts, *, renderer="triangles"):
    """The next message of a format 8 stream (parts.cache, whose receivers
    negotiated it) for a frame encode_draw wrote: ``texts`` are its
    descriptors' text and ``sent`` a SentBatch each.

    An epoch opens with a full frame (assemble_message's, numbered 0).
    Every other message is a delta against the last one sent (its frame
    number ``base``): the splices and scalars ops diff_runs finds, each of
    the header's other fields only where its text changed (camera,
    background, resolution, samples, supersample, limitations), the
    definition tables the receivers lack, and the same payload a full frame
    of this history carries (the bytes of the batches the receivers lack,
    in order, then the definitions), so the batches it carries keep their
    offsets. A delta with nothing in it is None: it is not sent, and the
    frame number does not move. Records on the cache what the receivers
    hold afterwards."""
    cache = parts.cache
    fields = {"camera": camera, "background": list(frame.background), "resolution": list(frame.resolution),
              "samples": frame.samples, "supersample": _supersample(frame),
              "limitations": list(frame.limitations)}
    written = {name: json.dumps(fields[name]) for name in STREAM_FIELDS}
    last = cache.last
    if last is None:
        message = assemble_message(frame, camera, ", ".join(texts), parts, renderer=renderer,
                                   stream=(cache.epoch, 0))
        cache.frame = 0
    else:
        splices, scalars = diff_runs(last.batches, sent)
        changed = {name: fields[name] for name in STREAM_FIELDS if written[name] != last.fields[name]}
        tables = {key: table for key, table in definition_tables(frame, parts).items() if table}
        if splices or scalars or changed or tables:
            number = cache.frame + 1
            header = {"format_version": GEOMETRY_FORMAT_VERSION, "epoch": cache.epoch, "frame": number,
                      "base": cache.frame, "renderer": renderer, **changed, "splices": [],
                      "scalars": [[index, run.batch["program"]["scalars"]] for index, run in scalars], **tables}
            text = _insert_list(json.dumps(header), "splices", ", ".join(
                f"[{at}, {removed}, [{', '.join(texts[first:end])}]]" for at, removed, first, end in splices))
            message = _pack(text, parts)
            cache.frame = number
        else:
            message = None
    cache.last = SentFrame(sent, written)
    return message

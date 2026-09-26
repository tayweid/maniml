// CPU references into a recorded delta stream. Seeking never depends on every
// historical mesh staying in GPU memory. Only the requested frame is repacked.
"use strict";
globalThis.ManimlRecording = (() => {
  const decoder = new TextDecoder(), encoder = new TextEncoder();
  const HASH = /^[0-9a-f]{32}$/;

  function validatePaint(bytes) {
    // Definitions are little-endian float32, but payload offsets need not be
    // aligned. DataView also avoids depending on the host's byte order.
    if (bytes.length < 96 || (bytes.length - 96) % 32 || bytes.length > 96 + 32 * 4096) {
      throw new Error("Invalid recorded paint length");
    }
    const values = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
    for (let offset = 0; offset < bytes.length; offset += 4) {
      if (!Number.isFinite(values.getFloat32(offset, true))) throw new Error("Nonfinite recorded paint");
    }
    const count = values.getFloat32(28, true), mode = values.getFloat32(44, true);
    if (!(values.getFloat32(12, true) > 0) || count !== (bytes.length - 96) / 32
        || (mode !== 0 && mode !== 1) || (mode === 1 && count === 0)) {
      throw new Error("Invalid recorded paint coefficients");
    }
    return bytes;
  }

  function validateInlinePaint(paint) {
    if (!Array.isArray(paint) || paint.length < 24 || (paint.length - 24) % 8
        || paint.length > 24 + 8 * 4096) throw new Error("Invalid recorded inline paint");
    const bytes = new Uint8Array(paint.length * 4), values = new DataView(bytes.buffer);
    paint.forEach((value, index) => {
      if (typeof value !== "number") throw new Error("Invalid recorded inline paint");
      values.setFloat32(index * 4, value, true);
    });
    validatePaint(bytes);
  }

  function validateBorder(bytes) {
    if (!bytes.length || bytes.length % 176 || bytes.length > MAX_BORDER_CURVES * 176) {
      throw new Error("Invalid recorded border length");
    }
    const values = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
    for (let i = 0; i < bytes.length / 4; i++) {
      const value = values.getFloat32(i * 4, true), field = i % 44;
      if (!Number.isFinite(value) || ([7, 19, 31, 36].includes(field) && value < 0)
          || ((field === 37 || field === 38) && value !== 0 && value !== 1)
          || (field === 39 && value !== 0)) {
        throw new Error("Invalid recorded border coefficients");
      }
    }
    return bytes;
  }

  // Sources are 176 bytes per curve and must fit one portable storage binding.
  const MAX_BORDER_CURVES = Math.floor((128 << 20) / 176);

  // The Phase B tables (docs/phase_b1_plan.md, phase_b2_plan.md,
  // phase_b3_plan.md) are float32 rows the driver evaluates on the GPU: an
  // object table of 8 words per patch object, a net's control points, a
  // program's source rows. Their record-level shapes are checked against
  // the batch that references them; here only that the words are finite.
  function validateWords(granule, label) {
    return bytes => {
      if (!bytes.length || bytes.length % granule) throw new Error(`Invalid recorded ${label} length`);
      const values = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
      for (let offset = 0; offset < bytes.length; offset += 4) {
        if (!Number.isFinite(values.getFloat32(offset, true))) throw new Error(`Nonfinite recorded ${label}`);
      }
      return bytes;
    };
  }
  const validateObjects = validateWords(32, "object table");
  const validateNet = validateWords(4, "net");
  const validateRows = validateWords(4, "program source");

  // kind -> [number of sources, number of scalars], as the driver reads them.
  const ROW_FLOATS = 17, PROGRAM_KINDS = {blend: [2, 1], affine: [1, 16], paint: [1, 2], partial: [1, 5]};

  // Format 6 border runs carry only their fill indices; the driver expands
  // each object's strip pattern from this layout at the run's reserved
  // capacity. Format 5 shipped the complete index buffer at capacity 64.
  function borderRun(header, batch) {
    const border = batch.border;
    if (!("capacity" in border)) return {capacity: 64, layout: null};
    const {capacity, layout} = border;
    if (header.format_version < 6 || !Number.isSafeInteger(capacity) || capacity % 2
        || capacity < 4 || capacity > 64 || !Array.isArray(layout) || !layout.length) {
      throw new Error("Invalid recorded border geometry layout");
    }
    let indices = 0, vertices = 0, curves = 0;
    for (const part of layout) {
      if (!Array.isArray(part) || part.length !== 3
          || part.some(value => !Number.isSafeInteger(value) || value < 0) || part[2] < 1) {
        throw new Error("Invalid recorded border geometry layout");
      }
      indices += part[0]; vertices += part[1]; curves += part[2];
    }
    if (indices !== batch.index_count || vertices !== batch.fill_num_verts || curves !== border.num_curves) {
      throw new Error("Invalid recorded border geometry layout");
    }
    return {capacity, layout};
  }

  function borderLayout(header, batch) {
    if (!("border" in batch)) {
      if ("fill_num_verts" in batch) throw new Error("Recorded fill count requires a border descriptor");
      return batch.num_verts;
    }
    const border = batch.border;
    if (!Number.isSafeInteger(header.format_version) || header.format_version < 5
        || !border || typeof border !== "object" || Array.isArray(border)
        || typeof border.hash !== "string" || !HASH.test(border.hash)
        || !Number.isSafeInteger(border.num_curves) || border.num_curves < 1 || border.num_curves > MAX_BORDER_CURVES
        || !Number.isSafeInteger(batch.fill_num_verts) || batch.fill_num_verts < 0
        || !Number.isSafeInteger(batch.index_count) || batch.index_count % 3
        || batch.kind !== "generated" || !["surface", "surface_depth", "paint", "paint_depth"].includes(batch.pipeline)
        || batch.stride !== 40 || batch.indexed !== true || batch.instances !== 1) {
      throw new Error("Invalid recorded border geometry layout");
    }
    const {capacity, layout} = borderRun(header, batch);
    const complete = layout === null
      ? batch.index_count >= 186 * border.num_curves && batch.count === batch.index_count
      : batch.count === batch.index_count + 6 * (capacity / 2 - 1) * border.num_curves;
    if (!complete || !Number.isSafeInteger(batch.num_verts)
        || batch.num_verts !== batch.fill_num_verts + capacity * border.num_curves
        || !Number.isSafeInteger(batch.num_verts * 40) || batch.num_verts > 0xffffffff) {
      throw new Error("Invalid recorded border geometry layout");
    }
    return batch.fill_num_verts;
  }

  // The Phase B batches ship no vertices of their own, so each returns a
  // fill count of zero: a patch run draws the border stage's curve records
  // through its object table, a net is evaluated from its control points,
  // and a program's rows are evaluated then finalized into the records,
  // strokes or net the batch draws. The descriptors are checked as the
  // driver checks them (format 7, no fill, no indices, counts from the
  // reservation), so a frame that indexes is one the driver will draw.
  function isHash(value) { return typeof value === "string" && HASH.test(value); }
  function isRecord(value) { return !!value && typeof value === "object" && !Array.isArray(value); }
  function isPatch(batch) { return batch.pipeline === "patch" || batch.pipeline === "patch_depth"; }

  function patchLayout(header, batch, programCurves = null) {
    const {border, objects} = batch;
    if (!Number.isSafeInteger(header.format_version) || header.format_version < 7
        || !isRecord(border) || !isHash(border.hash) || !isRecord(objects) || !isHash(objects.hash)
        || !Number.isSafeInteger(border.num_curves) || border.num_curves < 1 || border.num_curves > MAX_BORDER_CURVES
        || (programCurves !== null && border.num_curves !== programCurves)
        || batch.kind !== "generated" || batch.stride !== 40 || batch.indexed !== false
        || batch.fill_num_verts !== 0 || batch.index_count !== 0 || batch.instances !== 1 || "net" in batch) {
      throw new Error("Invalid recorded patch geometry layout");
    }
    // The layout is [curve count, bordered, group] per object; a bordered
    // object adds its strip pattern at the run's capacity to the cover.
    const {capacity, layout} = border;
    if (!Number.isSafeInteger(capacity) || capacity % 2 || capacity < 4 || capacity > 64
        || !Array.isArray(layout) || !layout.length) {
      throw new Error("Invalid recorded patch geometry layout");
    }
    let curves = 0, count = 0;
    for (const part of layout) {
      if (!Array.isArray(part) || part.length !== 3 || part.some(value => !Number.isSafeInteger(value))
          || part[0] < 1 || (part[1] !== 0 && part[1] !== 1) || part[2] < 0) {
        throw new Error("Invalid recorded patch geometry layout");
      }
      curves += part[0]; count += part[0] * (6 + (part[1] ? 6 * (capacity / 2 - 1) : 0));
    }
    if (curves !== border.num_curves || objects.count !== layout.length
        || batch.count !== count || batch.num_verts !== capacity * border.num_curves) {
      throw new Error("Invalid recorded patch geometry layout");
    }
    return 0;
  }

  function netLayout(header, batch, program = null) {
    const net = batch.net;
    if (!Number.isSafeInteger(header.format_version) || header.format_version < 7 || !isRecord(net)) {
      throw new Error("Invalid recorded net geometry layout");
    }
    const {hash, nu, nv, channels, capacity, density} = net;
    if (!isHash(hash) || [nu, nv, channels, capacity].some(value => !Number.isSafeInteger(value))
        || nu < 3 || nv < 3 || nu % 2 === 0 || nv % 2 === 0 || capacity < 2 || capacity > 32
        || typeof density !== "number" || !Number.isFinite(density) || density < 0
        || !["surface", "surface_depth", "texsurface", "texsurface_depth"].includes(batch.pipeline)
        || batch.kind !== "generated" || channels * 4 !== batch.stride || batch.indexed !== false
        || batch.fill_num_verts !== 0 || batch.index_count !== 0 || batch.instances !== 1
        || "border" in batch || "objects" in batch) {
      throw new Error("Invalid recorded net geometry layout");
    }
    const patches = ((nu - 1) / 2) * ((nv - 1) / 2);
    if (batch.num_verts !== patches * (capacity + 1) ** 2 || batch.count !== patches * 6 * capacity * capacity) {
      throw new Error("Invalid recorded net geometry layout");
    }
    // A program's evaluated rows stand in for the net's control points.
    if (program && program.rows * program.channels !== nu * nv * channels) {
      throw new Error("Recorded program rows do not match its net");
    }
    return 0;
  }

  function programLayout(header, batch) {
    const program = batch.program;
    if (!Number.isSafeInteger(header.format_version) || header.format_version < 7 || !isRecord(program)) {
      throw new Error("Invalid recorded program descriptor");
    }
    const {kind, sources, scalars, rows, channels} = program;
    if (!Object.hasOwn(PROGRAM_KINDS, kind) || !Array.isArray(sources) || sources.length !== PROGRAM_KINDS[kind][0]
        || !sources.every(isHash) || !Array.isArray(scalars) || scalars.length !== PROGRAM_KINDS[kind][1]
        || scalars.some(value => typeof value !== "number" || !Number.isFinite(value))
        || !Number.isSafeInteger(rows) || rows < 1 || !Number.isSafeInteger(channels) || channels < 1
        || (kind !== "blend" && channels !== ROW_FLOATS)) {
      throw new Error("Invalid recorded program descriptor");
    }
    if (kind === "partial") {
      const [lower, lowerResidue, upper, upperResidue, full] = scalars, curves = Math.floor(rows / 2);
      if (![lower, upper, full].every(Number.isInteger) || (full !== 0 && full !== 1)
          || lower < 0 || lower >= Math.max(1, curves) || upper < 0 || upper >= Math.max(1, curves)
          || lowerResidue < 0 || lowerResidue > 1 || upperResidue < 0 || upperResidue > 1) {
        throw new Error("Invalid recorded program descriptor");
      }
    }
    // The finalized curves of VMobject rows: the outer-vertex pattern's count.
    const curves = Math.max(0, Math.floor((rows - 1) / 2));
    if (batch.pipeline === "stroke" || batch.pipeline === "stroke_depth") {
      // Three finalized rows per curve, one instance each, no upload.
      if (batch.kind !== "generated" || batch.stride !== 68 || batch.indexed !== false
          || batch.fill_num_verts !== 0 || batch.index_count !== 0 || batch.instances !== curves
          || batch.num_verts !== 3 * curves || !Number.isSafeInteger(batch.count)
          || batch.count < 4 || batch.count > 64 || batch.count % 2
          || "border" in batch || "net" in batch || "objects" in batch) {
        throw new Error("Invalid recorded program stroke layout");
      }
      return 0;
    }
    if (isPatch(batch)) return patchLayout(header, batch, curves);
    if ("net" in batch) return netLayout(header, batch, program);
    throw new Error("Invalid recorded program descriptor");
  }

  function vertexLayout(header, batch) {
    if ("program" in batch) return programLayout(header, batch);
    if ("net" in batch) return netLayout(header, batch);
    if (isPatch(batch)) return patchLayout(header, batch);
    return borderLayout(header, batch);
  }

  // The object table against the run it draws: a record per object with
  // its curve offset, count, border flag and winding sign, in draw order.
  function validateObjectRecords(bytes, layout) {
    if (bytes.length !== 32 * layout.length) throw new Error("Recorded object table does not match its run layout");
    const values = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
    let offset = 0;
    layout.forEach(([curves, bordered], index) => {
      const word = i => values.getFloat32(32 * index + 4 * i, true);
      if (word(3) !== offset || word(4) !== curves || word(5) !== bordered
          || ![-1, 0, 1].includes(word(6)) || word(7) !== 0) {
        throw new Error("Recorded object table does not match its run layout");
      }
      offset += curves;
    });
  }

  function index(messages) {
    const geometry = new Map(), textures = new Map(), paints = new Map(), borders = new Map();
    const tables = new Map(), nets = new Map(), rows = new Map();
    const frames = messages.map(message => {
      const bytes = message instanceof Uint8Array ? message : new Uint8Array(message);
      if (bytes.length < 5 || bytes[0] !== 3) throw new Error("Invalid recorded geometry frame");
      const length = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength).getUint32(1, true);
      if (length > bytes.length - 5) throw new Error("Truncated recorded geometry header");
      const header = JSON.parse(decoder.decode(bytes.subarray(5, 5 + length)));
      const payload = bytes.subarray(5 + length);
      function span(offset, size) {
        if (!Number.isSafeInteger(offset) || !Number.isSafeInteger(size) || offset < 0 || size < 0
            || offset > payload.length - size) throw new Error("Truncated recorded geometry payload");
        return payload.subarray(offset, offset + size);
      }
      for (const [hash, info] of Object.entries(header.texture_data || {})) {
        textures.set(hash, span(info.offset, info.nbytes));
      }
      // Every definition table is keyed by content hash and sent once; the
      // first definition stands, and a later frame may not redefine it.
      function define(name, label, validate, definitions) {
        const records = header[name];
        if (records !== undefined && !isRecord(records)) throw new Error(`Invalid recorded ${label} definitions`);
        for (const [hash, info] of Object.entries(records || {})) {
          if (!HASH.test(hash) || !isRecord(info)) throw new Error(`Invalid recorded ${label} definition`);
          const bytes = validate(span(info.offset, info.nbytes));
          const previous = definitions.get(hash);
          if (previous && (previous.length !== bytes.length || previous.some((value, i) => value !== bytes[i]))) {
            throw new Error(`Conflicting recorded ${label} definition: ${hash}`);
          }
          definitions.set(hash, bytes);
        }
      }
      define("paint_data", "paint", validatePaint, paints);
      define("border_data", "border", validateBorder, borders);
      define("object_data", "object table", validateObjects, tables);
      define("net_data", "net", validateNet, nets);
      define("program_data", "program source", validateRows, rows);
      const batches = header.batches.map(batch => {
        // A cached format 6 border batch omits its run layout; the geometry
        // it refers to carries it, and a rehydrated frame must carry it too.
        if (batch.cached && batch.border && "capacity" in batch.border && !("layout" in batch.border)) {
          const retained = geometry.get(batch.hash);
          if (!retained || !retained.layout) throw new Error(`Missing recorded geometry: ${batch.hash}`);
          batch = {...batch, border: {...batch.border, layout: retained.layout}};
        }
        const vertexCount = vertexLayout(header, batch);
        if (!batch.cached) {
          const content = {vertices: span(batch.offset, vertexCount * batch.stride)};
          if (batch.kind === "generated" && batch.indexed) {
            content.indices = span(batch.index_offset, batch.index_count * 4);
          }
          if (batch.border && "layout" in batch.border) content.layout = batch.border.layout;
          if (batch.tri) {
            content.triVertices = span(batch.tri.voffset, batch.tri.vcount * 40);
            content.triIndices = span(batch.tri.ioffset, batch.tri.icount * 4);
          }
          geometry.set(batch.hash, content);
        }
        const content = geometry.get(batch.hash);
        if (!content) throw new Error(`Missing recorded geometry: ${batch.hash}`);
        const material = Object.fromEntries(Object.values(batch.textures || {}).map(hash => {
          const bytes = textures.get(hash);
          if (!bytes) throw new Error(`Missing recorded texture: ${hash}`);
          return [hash, bytes];
        }));
        let paint = null;
        if (batch.paint_hash !== undefined) {
          if (!isHash(batch.paint_hash)) throw new Error("Invalid recorded paint hash");
          paint = paints.get(batch.paint_hash);
          if (!paint) throw new Error(`Missing recorded paint: ${batch.paint_hash}`);
        } else if (batch.pipeline === "paint" || batch.pipeline === "paint_depth") {
          validateInlinePaint(batch.paint);
        }
        // A program's sources are what the driver evaluates; its patch or
        // net batch names the program, not a record, in its border or net
        // hash, so no border or net definition is looked up for it.
        let sources = null;
        if ("program" in batch) {
          const {rows: count, channels} = batch.program;
          sources = batch.program.sources.map(hash => {
            const bytes = rows.get(hash);
            if (!bytes) throw new Error(`Missing recorded program source: ${hash}`);
            if (bytes.length !== count * channels * 4) throw new Error("Recorded program source does not match its descriptor");
            return [hash, bytes];
          });
        }
        let objects = null;
        if (isPatch(batch)) {
          objects = tables.get(batch.objects.hash);
          if (!objects) throw new Error(`Missing recorded object table: ${batch.objects.hash}`);
          validateObjectRecords(objects, batch.border.layout);
        }
        let net = null;
        if ("net" in batch && sources === null) {
          net = nets.get(batch.net.hash);
          if (!net) throw new Error(`Missing recorded net: ${batch.net.hash}`);
          const {nu, nv, channels} = batch.net;
          if (net.length !== nu * nv * channels * 4) throw new Error("Recorded net does not match its descriptor");
        }
        let border = null;
        if (batch.border && sources === null) {
          border = borders.get(batch.border.hash);
          if (!border) throw new Error(`Missing recorded border: ${batch.border.hash}`);
          if (border.length !== batch.border.num_curves * 176) {
            throw new Error("Recorded border geometry or source count mismatch");
          }
        }
        if (border && !isPatch(batch)) {
          if (content.vertices.length !== vertexCount * 40
              || !content.indices || content.indices.length !== batch.index_count * 4) {
            throw new Error("Recorded border geometry or source count mismatch");
          }
          const vertices = new DataView(content.vertices.buffer, content.vertices.byteOffset, content.vertices.byteLength);
          for (let i = 0; i < vertices.byteLength; i += 4) {
            if (!Number.isFinite(vertices.getFloat32(i, true))) throw new Error("Nonfinite recorded border fill vertices");
          }
          // Format 6 wire indices cover only the fills; format 5 addressed the tail too.
          const addressable = "layout" in batch.border ? batch.fill_num_verts : batch.num_verts;
          const indices = new DataView(content.indices.buffer, content.indices.byteOffset, content.indices.byteLength);
          for (let i = 0; i < indices.byteLength; i += 4) {
            if (indices.getUint32(i, true) >= addressable) throw new Error("Recorded border index exceeds output vertex count");
          }
        }
        // Capture the definition now. A reverse seek must not resolve through
        // whichever material happened to be most recently sent to the GPU.
        return {batch, content, material, paint, border, objects, net, sources};
      });
      return {header, batches};
    });

    return {
      frame(index) {
        const source = frames[index];
        if (!source) throw new RangeError("Recorded frame is out of range");
        const blobs = [], materials = new Map(), paints = new Map(), borders = new Map();
        const tables = new Map(), nets = new Map(), rows = new Map();
        let offset = 0;
        function append(bytes) {
          const start = offset;
          blobs.push(bytes); offset += bytes.length;
          return start;
        }
        const batches = source.batches.map(({batch, content, material, paint, border, objects, net, sources}) => {
          const full = {...batch, offset: append(content.vertices)};
          delete full.cached;
          if (content.indices) full.index_offset = append(content.indices);
          if (content.triVertices) {
            full.tri = {voffset: append(content.triVertices), vcount: content.triVertices.length / 40,
                        ioffset: append(content.triIndices), icount: content.triIndices.length / 4};
          }
          for (const [hash, bytes] of Object.entries(material)) materials.set(hash, bytes);
          if (paint) paints.set(batch.paint_hash, paint);
          if (border) borders.set(batch.border.hash, border);
          if (objects) tables.set(batch.objects.hash, objects);
          if (net) nets.set(batch.net.hash, net);
          for (const [hash, bytes] of sources || []) rows.set(hash, bytes);
          return full;
        });
        // Only what this frame's batches reference travels, at fresh offsets.
        function table(definitions) {
          const data = {};
          for (const [hash, bytes] of definitions) data[hash] = {offset: append(bytes), nbytes: bytes.length};
          return data;
        }
        const texture_data = table(materials), paint_data = table(paints), border_data = table(borders);
        const object_data = table(tables), net_data = table(nets), program_data = table(rows);
        const header = encoder.encode(JSON.stringify({...source.header, batches, texture_data, paint_data, border_data,
                                                      object_data, net_data, program_data}));
        const output = new Uint8Array(5 + header.length + offset);
        output[0] = 3;
        new DataView(output.buffer).setUint32(1, header.length, true);
        output.set(header, 5);
        offset = 5 + header.length;
        for (const blob of blobs) { output.set(blob, offset); offset += blob.length; }
        return output.buffer;
      },
    };
  }
  return {index};
})();

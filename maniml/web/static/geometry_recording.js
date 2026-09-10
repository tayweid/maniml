// CPU references into a recorded delta stream. Seeking never depends on every
// historical mesh staying in GPU memory. Only the requested frame is repacked.
"use strict";
globalThis.ManimlRecording = (() => {
  const decoder = new TextDecoder(), encoder = new TextEncoder();

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
        || typeof border.hash !== "string" || !/^[0-9a-f]{32}$/.test(border.hash)
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

  function index(messages) {
    const geometry = new Map(), textures = new Map(), paints = new Map(), borders = new Map();
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
      if (header.paint_data !== undefined && (!header.paint_data
          || typeof header.paint_data !== "object" || Array.isArray(header.paint_data))) {
        throw new Error("Invalid recorded paint definitions");
      }
      for (const [hash, info] of Object.entries(header.paint_data || {})) {
        if (!/^[0-9a-f]{32}$/.test(hash) || !info || typeof info !== "object") {
          throw new Error("Invalid recorded paint definition");
        }
        const bytes = validatePaint(span(info.offset, info.nbytes));
        const previous = paints.get(hash);
        if (previous && (previous.length !== bytes.length || previous.some((value, i) => value !== bytes[i]))) {
          throw new Error(`Conflicting recorded paint definition: ${hash}`);
        }
        paints.set(hash, bytes);
      }
      if (header.border_data !== undefined && (!header.border_data
          || typeof header.border_data !== "object" || Array.isArray(header.border_data))) {
        throw new Error("Invalid recorded border definitions");
      }
      for (const [hash, info] of Object.entries(header.border_data || {})) {
        if (!/^[0-9a-f]{32}$/.test(hash) || !info || typeof info !== "object" || Array.isArray(info)) {
          throw new Error("Invalid recorded border definition");
        }
        const bytes = validateBorder(span(info.offset, info.nbytes));
        const previous = borders.get(hash);
        if (previous && (previous.length !== bytes.length || previous.some((value, i) => value !== bytes[i]))) {
          throw new Error(`Conflicting recorded border definition: ${hash}`);
        }
        borders.set(hash, bytes);
      }
      const batches = header.batches.map(batch => {
        // A cached format 6 border batch omits its run layout; the geometry
        // it refers to carries it, and a rehydrated frame must carry it too.
        if (batch.cached && batch.border && "capacity" in batch.border && !("layout" in batch.border)) {
          const retained = geometry.get(batch.hash);
          if (!retained || !retained.layout) throw new Error(`Missing recorded geometry: ${batch.hash}`);
          batch = {...batch, border: {...batch.border, layout: retained.layout}};
        }
        const vertexCount = borderLayout(header, batch);
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
          if (typeof batch.paint_hash !== "string" || !/^[0-9a-f]{32}$/.test(batch.paint_hash)) {
            throw new Error("Invalid recorded paint hash");
          }
          paint = paints.get(batch.paint_hash);
          if (!paint) throw new Error(`Missing recorded paint: ${batch.paint_hash}`);
        } else if (batch.pipeline === "paint" || batch.pipeline === "paint_depth") {
          validateInlinePaint(batch.paint);
        }
        let border = null;
        if (batch.border) {
          border = borders.get(batch.border.hash);
          if (!border) throw new Error(`Missing recorded border: ${batch.border.hash}`);
          if (border.length !== batch.border.num_curves * 176
              || content.vertices.length !== vertexCount * 40
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
        return {batch, content, material, paint, border};
      });
      return {header, batches};
    });

    return {
      frame(index) {
        const source = frames[index];
        if (!source) throw new RangeError("Recorded frame is out of range");
        const blobs = [], materials = new Map(), paints = new Map(), borders = new Map();
        let offset = 0;
        function append(bytes) {
          const start = offset;
          blobs.push(bytes); offset += bytes.length;
          return start;
        }
        const batches = source.batches.map(({batch, content, material, paint, border}) => {
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
          return full;
        });
        const texture_data = {};
        for (const [hash, bytes] of materials) texture_data[hash] = {offset: append(bytes), nbytes: bytes.length};
        const paint_data = {};
        for (const [hash, bytes] of paints) paint_data[hash] = {offset: append(bytes), nbytes: bytes.length};
        const border_data = {};
        for (const [hash, bytes] of borders) border_data[hash] = {offset: append(bytes), nbytes: bytes.length};
        const header = encoder.encode(JSON.stringify({...source.header, batches, texture_data, paint_data, border_data}));
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

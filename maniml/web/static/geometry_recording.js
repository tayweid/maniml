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

  function index(messages) {
    const geometry = new Map(), textures = new Map(), paints = new Map();
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
      const batches = header.batches.map(batch => {
        if (!batch.cached) {
          const content = {vertices: span(batch.offset, batch.num_verts * batch.stride)};
          if (batch.kind === "generated" && batch.indexed) {
            content.indices = span(batch.index_offset, batch.index_count * 4);
          }
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
        // Capture the definition now. A reverse seek must not resolve through
        // whichever material happened to be most recently sent to the GPU.
        return {batch, content, material, paint};
      });
      return {header, batches};
    });

    return {
      frame(index) {
        const source = frames[index];
        if (!source) throw new RangeError("Recorded frame is out of range");
        const blobs = [], materials = new Map(), paints = new Map();
        let offset = 0;
        function append(bytes) {
          const start = offset;
          blobs.push(bytes); offset += bytes.length;
          return start;
        }
        const batches = source.batches.map(({batch, content, material, paint}) => {
          const full = {...batch, offset: append(content.vertices)};
          delete full.cached;
          if (content.indices) full.index_offset = append(content.indices);
          if (content.triVertices) {
            full.tri = {voffset: append(content.triVertices), vcount: content.triVertices.length / 40,
                        ioffset: append(content.triIndices), icount: content.triIndices.length / 4};
          }
          for (const [hash, bytes] of Object.entries(material)) materials.set(hash, bytes);
          if (paint) paints.set(batch.paint_hash, paint);
          return full;
        });
        const texture_data = {};
        for (const [hash, bytes] of materials) texture_data[hash] = {offset: append(bytes), nbytes: bytes.length};
        const paint_data = {};
        for (const [hash, bytes] of paints) paint_data[hash] = {offset: append(bytes), nbytes: bytes.length};
        const header = encoder.encode(JSON.stringify({...source.header, batches, texture_data, paint_data}));
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

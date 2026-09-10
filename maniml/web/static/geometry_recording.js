// CPU references into a recorded delta stream. Seeking never depends on every
// historical mesh staying in GPU memory. Only the requested frame is repacked.
"use strict";
globalThis.ManimlRecording = (() => {
  const decoder = new TextDecoder(), encoder = new TextEncoder();

  function index(messages) {
    const geometry = new Map(), textures = new Map();
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
        return {batch, content, material};
      });
      return {header, batches};
    });

    return {
      frame(index) {
        const source = frames[index];
        if (!source) throw new RangeError("Recorded frame is out of range");
        const blobs = [], materials = new Map();
        let offset = 0;
        function append(bytes) {
          const start = offset;
          blobs.push(bytes); offset += bytes.length;
          return start;
        }
        const batches = source.batches.map(({batch, content, material}) => {
          const full = {...batch, offset: append(content.vertices)};
          delete full.cached;
          if (content.indices) full.index_offset = append(content.indices);
          if (content.triVertices) {
            full.tri = {voffset: append(content.triVertices), vcount: content.triVertices.length / 40,
                        ioffset: append(content.triIndices), icount: content.triIndices.length / 4};
          }
          for (const [hash, bytes] of Object.entries(material)) materials.set(hash, bytes);
          return full;
        });
        const texture_data = {};
        for (const [hash, bytes] of materials) texture_data[hash] = {offset: append(bytes), nbytes: bytes.length};
        const header = encoder.encode(JSON.stringify({...source.header, batches, texture_data}));
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

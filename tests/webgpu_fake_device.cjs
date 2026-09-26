// The fake WebGPU device the browser-driver harnesses share. It records the
// driver's commands and validates resource lifetimes at submission for the
// command tests (tests/generated_webgpu_commands.cjs builds its payloads on
// it), and it tallies every call for the frame benchmark
// (benchmarks/browser_frames.cjs), which runs it with validate: false so the
// per-frame cost it times is the driver's own work rather than the fake's
// bookkeeping. It simulates no pixels.
"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const STATIC = path.join(__dirname, "..", "maniml", "web", "static");
const CAMERA = {
  view: [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1],
  frame_rescale_factors: [1, 1, 1], camera_position: [0, 0, 10],
  light_position: [0, 0, 10],
};
const STRIDE = { surface: 40, paint: 40, stroke: 68, dot: 32, image: 24, texsurface: 36 };
const constantPaint = color => [0, 0, 0, 1, 1, 0, 0, 0, 0, 1, 0, 0, ...color, ...Array(8).fill(0)];

function payload(specs, overrides = {}) {
  let offset = 0;
  const parts = [];
  const batches = specs.map((spec, i) => {
    const base = (spec.pipeline || "surface").replace(/_depth$/, "");
    const batch = { kind: "generated", pipeline: "surface", hash: `shape-${i}`,
      num_verts: 3, stride: STRIDE[base], count: 3, instances: 1,
      indexed: false, index_count: 0, uniforms: {}, ...spec };
    if (base === "paint" && !("paint" in batch) && !batch.paint_hash) batch.paint = constantPaint([1, 0, 0, .5]);
    if (!batch.cached) {
      batch.offset = offset;
      const data = Buffer.alloc((batch.fill_num_verts ?? batch.num_verts) * batch.stride, i % 255);
      parts.push(data); offset += data.length;
      if (batch.indexed) {
        batch.index_offset = offset;
        const indices = new Uint32Array(spec.index_values || Array.from({ length: batch.index_count }, (_, j) => j));
        delete batch.index_values;
        parts.push(Buffer.from(indices.buffer)); offset += indices.byteLength;
      }
    }
    return batch;
  });
  const {paint_definitions, border_definitions, paint_padding = 0, ...headerOverrides} = overrides;
  const paint_data = {};
  if (paint_padding) { parts.push(Buffer.alloc(paint_padding)); offset += paint_padding; }
  for (const [hash, values] of Object.entries(paint_definitions || {})) {
    const data = Buffer.isBuffer(values) ? values : Buffer.from(new Float32Array(values).buffer);
    paint_data[hash] = {offset, nbytes: data.length};
    parts.push(data); offset += data.length;
  }
  const border_data = {};
  for (const [hash, values] of Object.entries(border_definitions || {})) {
    const data = Buffer.isBuffer(values) ? values : Buffer.from(new Float32Array(values).buffer);
    border_data[hash] = {offset, nbytes: data.length};
    parts.push(data); offset += data.length;
  }
  const header = { renderer: "triangles", resolution: [320, 180], samples: 1, supersample: 1,
    background: [0.2, 0.4, 0.6, 0.5], camera: CAMERA, batches,
    ...(paint_definitions ? {paint_data} : {}), ...(border_definitions ? {border_data} : {}), ...headerOverrides };
  const json = Buffer.from(JSON.stringify(header));
  const out = Buffer.alloc(5 + json.length + offset);
  out[0] = 3; out.writeUInt32LE(json.length, 1); json.copy(out, 5);
  let position = 5 + json.length;
  for (const part of parts) { part.copy(out, position); position += part.length; }
  return out.buffer.slice(out.byteOffset, out.byteOffset + out.byteLength);
}

const BUFFER_USAGE = { VERTEX: 1, INDEX: 2, UNIFORM: 4, STORAGE: 8, COPY_SRC: 16, COPY_DST: 32 };

// Every WebGPU call the driver makes, tallied since the device was made;
// the benchmark differences consecutive snapshots per frame. A "pipeline
// switch" is a setPipeline naming a pipeline other than the pass's current
// one; a "uniform write" is a uniform buffer created with its data or a
// queue.writeBuffer into one; "bytes uploaded" are the mapped-at-creation
// bytes plus writeBuffer bytes, as against buffer_bytes_created, which
// also counts outputs the GPU fills.
function newCounts() {
  return {
    buffers_created: 0, buffers_destroyed: 0, buffer_bytes_created: 0, bytes_uploaded: 0,
    uniform_buffers_created: 0, write_buffer_calls: 0, uniform_writes: 0,
    bind_groups_created: 0, render_pipelines_created: 0, compute_pipelines_created: 0,
    command_encoders: 0, render_passes: 0, compute_passes: 0,
    set_pipeline_calls: 0, pipeline_switches: 0, set_bind_group_calls: 0,
    set_vertex_buffer_calls: 0, set_index_buffer_calls: 0, set_stencil_reference_calls: 0,
    draws: 0, compute_dispatches: 0, buffer_copies: 0, texture_uploads: 0, submits: 0,
  };
}

// options.validate (default true) keeps the command records and asserts
// resource lifetimes at submission; false only counts, so a timed frame
// pays nothing but the driver.
async function driver(options = {}) {
  const validate = options.validate !== false;
  const counts = newCounts();
  const buffers = [], textures = [], submissions = [], events = [];
  let cacheMisses = 0, sequence = 0;
  const makeTexture = descriptor => {
    const texture = { descriptor, destroyed: false,
      createView() { return { texture: this }; },
      destroy() {
        if (validate) assert.ok(!this.destroyed);
        this.destroyed = true;
        if (validate) events.push(["texture", this]);
      },
    };
    if (validate) textures.push(texture);
    return texture;
  };
  const device = {
    limits: options.limits || {},
    destroy() { events.push(["device_destroy"]); },
    createShaderModule: descriptor => descriptor,
    createRenderPipeline(descriptor) {
      counts.render_pipelines_created++;
      const pipeline = { descriptor, id: ++sequence,
        getBindGroupLayout(index) { return { pipeline: this, index }; } };
      return pipeline;
    },
    createComputePipeline(descriptor) {
      counts.compute_pipelines_created++;
      return {descriptor, id: ++sequence, getBindGroupLayout(index) { return {pipeline: this, index}; }};
    },
    // Explicit layouts, as the patch pipelines use: a bind group made from
    // one is compatible with every pipeline whose layout lists it.
    createBindGroupLayout: descriptor => ({explicit: true, descriptor}),
    createPipelineLayout: descriptor => ({explicit: true, descriptor}),
    createSampler: descriptor => ({ descriptor }),
    createBindGroup(descriptor) { counts.bind_groups_created++; return descriptor; },
    createTexture: makeTexture,
    createBuffer(descriptor) {
      counts.buffers_created++;
      counts.buffer_bytes_created += descriptor.size;
      const uniform = (descriptor.usage & BUFFER_USAGE.UNIFORM) !== 0;
      if (uniform) counts.uniform_buffers_created++;
      if (descriptor.mappedAtCreation) {
        counts.bytes_uploaded += descriptor.size;
        if (uniform) counts.uniform_writes++;
      }
      const buffer = { descriptor, bytes: new ArrayBuffer(descriptor.size), destroyed: false,
        getMappedRange() { return this.bytes; }, unmap() {},
        destroy() {
          if (validate) assert.ok(!this.destroyed);
          this.destroyed = true;
          counts.buffers_destroyed++;
          if (validate) events.push(["buffer", this]);
        },
      };
      if (validate) buffers.push(buffer);
      return buffer;
    },
    createCommandEncoder() {
      counts.command_encoders++;
      const passes = [];
      return {
        copyBufferToBuffer(source, sourceOffset, target, targetOffset, size) {
          counts.buffer_copies++;
          passes.push({copy: [source, sourceOffset, target, targetOffset, size], ended: true});
        },
        beginComputePass() {
          counts.compute_passes++;
          const pass = {compute: true, draws: [], bindings: new Map(), ended: false};
          passes.push(pass);
          return {
            setPipeline(pipeline) {
              counts.set_pipeline_calls++;
              if (pipeline !== pass.pipeline) counts.pipeline_switches++;
              pass.pipeline = pipeline;
            },
            setBindGroup(index, binding) { counts.set_bind_group_calls++; pass.bindings.set(index, binding); },
            dispatchWorkgroups(count, rows = 1) {
              counts.compute_dispatches++;
              if (!validate) return;
              assert.equal(pass.bindings.get(0).layout.pipeline, pass.pipeline);
              assert.equal(pass.bindings.get(1).layout.pipeline, pass.pipeline);
              pass.draws.push({bindings: new Map(pass.bindings), count, rows, pipeline: pass.pipeline});
            },
            end() { pass.ended = true; },
          };
        },
        beginRenderPass(descriptor) {
          counts.render_passes++;
          const pass = { descriptor, draws: [], bindings: new Map(), vertices: [], ended: false };
          passes.push(pass);
          return {
            setPipeline(pipeline) {
              counts.set_pipeline_calls++;
              if (pipeline !== pass.pipeline) counts.pipeline_switches++;
              pass.pipeline = pipeline;
            },
            setStencilReference(reference) { counts.set_stencil_reference_calls++; pass.stencil = reference; },
            setBindGroup(index, binding) { counts.set_bind_group_calls++; pass.bindings.set(index, binding); },
            setVertexBuffer(index, buffer) { counts.set_vertex_buffer_calls++; pass.vertices[index] = buffer; },
            setIndexBuffer(buffer, format) { counts.set_index_buffer_calls++; pass.index = { buffer, format }; },
            draw(...args) { counts.draws++; if (validate) record(false, args); },
            drawIndexed(...args) { counts.draws++; if (validate) record(true, args); },
            end() { pass.ended = true; },
          };
          function record(indexed, args) {
            // Automatic layouts are specific to the concrete pipeline, even
            // when two shader entry points declare the same uniform struct;
            // an explicit layout must be one the pipeline's layout lists.
            // A group the pipeline's layout does not list is ignored, as
            // WebGPU ignores it; one it lists must be that layout.
            const layout = pass.pipeline.descriptor.layout;
            for (const [index, binding] of pass.bindings) {
              if (layout.explicit) {
                const listed = layout.descriptor.bindGroupLayouts[index];
                if (listed !== undefined) assert.equal(binding.layout, listed, "bind group layout is not the pipeline's at group " + index);
              } else if (!binding.layout.explicit && index === 0) {
                assert.equal(binding.layout.pipeline, pass.pipeline);
              }
            }
            pass.draws.push({ pipeline: pass.pipeline, bindings: new Map(pass.bindings),
              stencil: pass.stencil, vertices: [...pass.vertices], index: indexed ? pass.index : null, indexed, args });
          }
        },
        finish() { assert.ok(passes.every(p => p.ended)); return passes; },
      };
    },
    queue: {
      onSubmittedWorkDone: async () => { events.push(["completed"]); },
      copyExternalImageToTexture() { counts.texture_uploads++; },
      writeBuffer(buffer, offset, data, dataOffset = 0, size) {
        // dataOffset and size are in elements of a typed array, bytes of
        // an ArrayBuffer, as WebGPU reads them.
        const element = ArrayBuffer.isView(data) ? data.BYTES_PER_ELEMENT || 1 : 1;
        const bytes = ArrayBuffer.isView(data) ? new Uint8Array(data.buffer, data.byteOffset, data.byteLength)
          : new Uint8Array(data);
        const start = dataOffset * element;
        const length = size === undefined ? bytes.byteLength - start : size * element;
        if (validate) {
          // What Dawn rejects: the target needs COPY_DST, the offset and
          // the size are multiples of 4, and the write stays in the buffer.
          assert.ok(!buffer.destroyed, "write into a destroyed buffer");
          assert.ok(buffer.descriptor.usage & BUFFER_USAGE.COPY_DST, "writeBuffer target lacks COPY_DST usage");
          assert.equal(offset % 4, 0, "writeBuffer offset is not a multiple of 4");
          assert.equal(length % 4, 0, "writeBuffer size is not a multiple of 4");
          assert.ok(start + length <= bytes.byteLength, "writeBuffer reads past its data");
          assert.ok(offset + length <= buffer.descriptor.size, "writeBuffer extends beyond the buffer");
        }
        counts.write_buffer_calls++;
        counts.bytes_uploaded += length;
        if (buffer.descriptor.usage & BUFFER_USAGE.UNIFORM) counts.uniform_writes++;
        if (!validate) return;
        new Uint8Array(buffer.bytes, offset, length).set(bytes.subarray(start, start + length));
      },
      submit(commands) {
        counts.submits++;
        if (!validate) return;
        for (const passes of commands) {
          for (const pass of passes) {
            if (pass.copy) {
              const [source, from, target, to, size] = pass.copy;
              assert.ok(!source.destroyed && !target.destroyed, "copy uses live buffers");
              new Uint8Array(target.bytes, to, size).set(new Uint8Array(source.bytes, from, size));
              continue;
            }
            if (pass.compute) {
              for (const draw of pass.draws) {
                for (const binding of draw.bindings.values()) {
                  for (const {resource} of binding.entries) assert.ok(!resource.buffer.destroyed, "compute buffer destroyed before submit");
                }
                const group0 = draw.bindings.get(0).entries;
                if (group0.length === 1) {
                  // A program kernel: params alone in group 0, 16 bytes.
                  const words = new Uint32Array(group0[0].resource.buffer.bytes);
                  const buffers = draw.bindings.get(1).entries.map(entry => entry.resource);
                  const code = draw.pipeline.descriptor.compute.module.code;
                  if (code.includes("BlendParams")) {
                    assert.equal(group0[0].resource.size, 16);
                    assert.equal(buffers.length, 3);
                    assert.ok(buffers.every(buffer => words[0] * 4 <= buffer.size), "blend within its rows");
                    assert.equal(draw.count, Math.ceil(words[0] / 256));
                  } else if (code.includes("AffineParams") || code.includes("PaintParams") || code.includes("PartialParams")) {
                    // A row kernel: rows first, one source and one output of 17 floats per row.
                    assert.equal(group0[0].resource.size, code.includes("AffineParams") ? 80 : code.includes("PaintParams") ? 16 : 32);
                    assert.equal(buffers.length, 2);
                    assert.ok(buffers.every(buffer => words[0] * 17 * 4 <= buffer.size), "row kernel within its rows");
                    assert.equal(draw.count, Math.ceil(words[0] / 64));
                    if (code.includes("PartialParams")) {
                      const [rows, curves, lower, upper] = words;
                      assert.equal(curves, Math.floor(rows / 2));
                      assert.ok(lower < curves && upper < curves);
                    }
                  } else {
                    assert.equal(group0[0].resource.size, 16);
                    const [curves, channels] = words, [rows, records, strokes] = buffers;
                    assert.equal(channels, 17);
                    assert.ok((2 * curves + 1) * channels * 4 <= rows.size, "finalize within its rows");
                    assert.ok(curves * 176 <= records.size && curves * 204 <= strokes.size);
                    assert.equal(draw.count, Math.ceil(curves / 64));
                  }
                  continue;
                }
                const paramsResource = group0[1].resource;
                const params = new Uint32Array(paramsResource.buffer.bytes);
                const [source, output] = draw.bindings.get(1).entries.map(entry => entry.resource);
                if (paramsResource.size === 48) {
                  // A surface net: [_, nu, nv, channels, capacity, output base, patch offset, patch count].
                  const [, nu, nv, channels, capacity, base, patchOffset, patchCount] = params;
                  const side = capacity + 1;
                  assert.ok(nu * nv * channels * 4 <= source.size);
                  assert.ok(capacity >= 2 && capacity <= 32);
                  assert.ok((base + patchCount * side * side) * channels * 4 <= output.size);
                  assert.ok(patchOffset + patchCount <= ((nu - 1) / 2) * ((nv - 1) / 2));
                  assert.equal(draw.count, patchCount);
                  assert.equal(draw.rows, Math.ceil(side * side / 64));
                  continue;
                }
                assert.ok((params[0] + params[1]) * 176 <= source.size);
                assert.ok(params[4] % 2 === 0 && params[4] >= 4 && params[4] <= 64, "capacity is an even vertex count");
                assert.ok((params[2] + params[1] * params[4]) * 40 <= output.size);
                assert.equal(output.offset % (device.limits.minStorageBufferOffsetAlignment ?? 256), 0);
                assert.ok(output.size <= (device.limits.maxStorageBufferBindingSize ?? 128 * 1024 ** 2));
                assert.equal(draw.count, params[1]);
                assert.ok(draw.count <= (device.limits.maxComputeWorkgroupsPerDimension ?? 65535));
              }
              continue;
            }
            for (const attachment of pass.descriptor.colorAttachments) {
              assert.ok(!attachment.view.texture.destroyed, "attachment destroyed before submission");
            }
            for (const draw of pass.draws) {
              for (const buffer of draw.vertices) assert.ok(!buffer.destroyed, "early vertex eviction");
              if (draw.index) assert.ok(!draw.index.buffer.destroyed, "early index eviction");
              for (const binding of draw.bindings.values()) {
                for (const { resource } of binding.entries) {
                  if (resource.buffer) assert.ok(!resource.buffer.destroyed, "early uniform eviction");
                  if (resource.texture) assert.ok(!resource.texture.destroyed, "early texture eviction");
                }
              }
            }
          }
          submissions.push(passes); events.push(["submit", submissions.length]);
        }
      },
    },
  };
  const canvas = { getContext: () => ({ configure() {}, unconfigure() { events.push(["unconfigure"]); },
    getCurrentTexture: () => makeTexture({ format: "canvas", size: [canvas.width, canvas.height] }),
  }) };
  const context = {
    navigator: { gpu: { requestAdapter: async () => ({ requestDevice: async () => device }),
      getPreferredCanvasFormat: () => "bgra8unorm" } },
    GPUBufferUsage: BUFFER_USAGE,
    GPUTextureUsage: { RENDER_ATTACHMENT: 1, TEXTURE_BINDING: 2, COPY_DST: 4 },
    GPUShaderStage: { VERTEX: 1, FRAGMENT: 2, COMPUTE: 4 },
    fetch: async name => ({ ok: true, text: async () => fs.readFileSync(path.join(STATIC, name), "utf8") }),
    createImageBitmap: options.decode || (async () => ({ width: 2, height: 2, close() {} })),
    Blob, TextDecoder, ArrayBuffer, Uint8Array, Uint32Array, Float32Array, DataView,
  };
  vm.runInNewContext(fs.readFileSync(path.join(STATIC, options.legacy ? "winding_webgpu.js" : "webgpu.js"), "utf8")
    + "\nglobalThis.renderer = " + (options.legacy ? "ManimlWindingWGPU" : "ManimlWGPU") + ";", context);
  await context.renderer.init(canvas);
  context.renderer.onCacheMiss = () => { cacheMisses++; };
  return { buffers, textures, submissions, events, cacheMisses: () => cacheMisses,
    counts: () => ({...counts}), renderer: context.renderer,
    destroy: () => context.renderer.destroy(), init: () => context.renderer.init(canvas),
    async render(specs, overrides) {
      await context.renderer.render(payload(specs, overrides)); return submissions.at(-1);
    },
    async renderBytes(bytes) { await context.renderer.render(bytes); return submissions.at(-1); },
  };
}

module.exports = {STATIC, CAMERA, STRIDE, constantPaint, payload, driver, newCounts};

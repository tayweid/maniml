// Record the shipped generated-geometry browser path without a GPU. Resource
// validation runs at submission, so early destruction is an actual test error.
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

async function driver(options = {}) {
  const buffers = [], textures = [], submissions = [], events = [];
  let cacheMisses = 0, sequence = 0;
  const makeTexture = descriptor => {
    const texture = { descriptor, destroyed: false,
      createView() { return { texture: this }; },
      destroy() { assert.ok(!this.destroyed); this.destroyed = true; events.push(["texture", this]); },
    };
    textures.push(texture); return texture;
  };
  const device = {
    limits: options.limits || {},
    destroy() { events.push(["device_destroy"]); },
    createShaderModule: descriptor => descriptor,
    createRenderPipeline(descriptor) {
      const pipeline = { descriptor, id: ++sequence,
        getBindGroupLayout(index) { return { pipeline: this, index }; } };
      return pipeline;
    },
    createComputePipeline(descriptor) {
      return {descriptor, id: ++sequence, getBindGroupLayout(index) { return {pipeline: this, index}; }};
    },
    // Explicit layouts, as the patch pipelines use: a bind group made from
    // one is compatible with every pipeline whose layout lists it.
    createBindGroupLayout: descriptor => ({explicit: true, descriptor}),
    createPipelineLayout: descriptor => ({explicit: true, descriptor}),
    createSampler: descriptor => ({ descriptor }),
    createBindGroup: descriptor => descriptor,
    createTexture: makeTexture,
    createBuffer(descriptor) {
      const buffer = { descriptor, bytes: new ArrayBuffer(descriptor.size), destroyed: false,
        getMappedRange() { return this.bytes; }, unmap() {},
        destroy() { assert.ok(!this.destroyed); this.destroyed = true; events.push(["buffer", this]); },
      };
      buffers.push(buffer); return buffer;
    },
    createCommandEncoder() {
      const passes = [];
      return {
        copyBufferToBuffer(source, sourceOffset, target, targetOffset, size) {
          passes.push({copy: [source, sourceOffset, target, targetOffset, size], ended: true});
        },
        beginComputePass() {
          const pass = {compute: true, draws: [], bindings: new Map(), ended: false};
          passes.push(pass);
          return {
            setPipeline(pipeline) { pass.pipeline = pipeline; },
            setBindGroup(index, binding) { pass.bindings.set(index, binding); },
            dispatchWorkgroups(count, rows = 1) {
              assert.equal(pass.bindings.get(0).layout.pipeline, pass.pipeline);
              assert.equal(pass.bindings.get(1).layout.pipeline, pass.pipeline);
              pass.draws.push({bindings: new Map(pass.bindings), count, rows, pipeline: pass.pipeline});
            },
            end() { pass.ended = true; },
          };
        },
        beginRenderPass(descriptor) {
          const pass = { descriptor, draws: [], bindings: new Map(), vertices: [], ended: false };
          passes.push(pass);
          return {
            setPipeline(pipeline) { pass.pipeline = pipeline; },
            setStencilReference(reference) { pass.stencil = reference; },
            setBindGroup(index, binding) { pass.bindings.set(index, binding); },
            setVertexBuffer(index, buffer) { pass.vertices[index] = buffer; },
            setIndexBuffer(buffer, format) { pass.index = { buffer, format }; },
            draw(...args) { record(false, args); },
            drawIndexed(...args) { record(true, args); },
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
      copyExternalImageToTexture() {},
      submit(commands) {
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
                  assert.equal(group0[0].resource.size, 16);
                  if (draw.pipeline.descriptor.compute.module.code.includes("BlendParams")) {
                    assert.equal(buffers.length, 3);
                    assert.ok(buffers.every(buffer => words[0] * 4 <= buffer.size), "blend within its rows");
                    assert.equal(draw.count, Math.ceil(words[0] / 256));
                  } else {
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
    GPUBufferUsage: { VERTEX: 1, INDEX: 2, UNIFORM: 4, STORAGE: 8, COPY_SRC: 16, COPY_DST: 32 },
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
    destroy: () => context.renderer.destroy(), init: () => context.renderer.init(canvas),
    async render(specs, overrides) {
      await context.renderer.render(payload(specs, overrides)); return submissions.at(-1);
    },
    async renderBytes(bytes) { await context.renderer.render(bytes); return submissions.at(-1); },
  };
}

const uniformBuffer = draw => draw.bindings.get(0).entries[0].resource.buffer;
const uniform = draw => new Float32Array(uniformBuffer(draw).bytes);
const near = (actual, expected) => expected.forEach((v, i) => assert.ok(Math.abs(actual[i] - v) < 1e-6));

function borderFixture(count = 3, fillCount = 40, hash = "c".repeat(32)) {
  const records = [];
  for (let i = 0; i < count; i++) {
    const curve = Array(44).fill(0);
    for (let point = 0; point < 3; point++) {
      curve[12 * point] = point - 1;
      curve[12 * point + 7] = 20;
      curve[12 * point + 11] = 1;
    }
    curve[37] = 1; curve[40] = 1; curve[43] = .5; records.push(...curve);
  }
  const indices = [0, 1, 2, 0, 2, 3];
  for (let curve = 0; curve < count; curve++) {
    for (let i = 0; i < 31; i++) {
      const base = fillCount + curve * 64 + i * 2;
      indices.push(base, base + 1, base + 2, base + 1, base + 2, base + 3);
    }
  }
  return {spec: {pipeline: "surface", hash: "fill", indexed: true, coverage: true,
    fill_num_verts: fillCount, num_verts: fillCount + 64 * count, count: indices.length,
    index_count: indices.length, index_values: indices, border: {hash, num_curves: count}},
    options: {format_version: 5, border_definitions: {[hash]: records}, paint_padding: 1}, records};
}

// The format 6 wire: fill indices plus the run layout, at a reserved
// capacity the driver expands the strip pattern for locally.
function borderRunFixture(count = 3, fillCount = 40, hash = "c".repeat(32), capacity = 8) {
  const legacy = borderFixture(count, fillCount, hash);
  const indices = [0, 1, 2, 0, 2, 3];
  const spec = {...legacy.spec, num_verts: fillCount + capacity * count,
    count: indices.length + 6 * (capacity / 2 - 1) * count, index_count: indices.length,
    index_values: indices, border: {hash, num_curves: count, capacity, layout: [[indices.length, fillCount, count]]}};
  return {spec, options: {...legacy.options, format_version: 6}, records: legacy.records};
}

function expectedRunIndices(fillCount, count, capacity) {
  const indices = [0, 1, 2, 0, 2, 3];
  for (let curve = 0; curve < count; curve++) {
    for (let strip = 0; strip < capacity / 2 - 1; strip++) {
      const base = fillCount + curve * capacity + strip * 2;
      indices.push(base, base + 1, base + 2, base + 1, base + 2, base + 3);
    }
  }
  return indices;
}

const cases = {
  async borderRuns() {
    const d = await driver();
    const fixture = borderRunFixture();
    const scene = passes => passes.find(pass => pass.descriptor && pass.descriptor.depthStencilAttachment);
    const first = await d.render([fixture.spec], fixture.options);
    const draw = scene(first).draws[0];
    assert.equal(draw.args[0], fixture.spec.count);
    assert.deepEqual(Array.from(new Uint32Array(draw.index.buffer.bytes)), expectedRunIndices(40, 3, 8));
    const compute = first.filter(pass => pass.compute);
    assert.equal(compute.length, 1);
    const params = compute[0].draws[0].bindings.get(0).entries[1].resource;
    assert.equal(params.size, 32);
    assert.equal(new Uint32Array(params.buffer.bytes)[4], 8, "the compute stage learns the reserved capacity");
    const view = compute[0].draws[0].bindings.get(1).entries[1].resource;
    assert.equal(view.offset + view.size, (40 + 8 * 3) * 40);
    const output = draw.vertices[0], fillBuffer = first.find(pass => pass.copy).copy[0];
    assert.equal(output.bytes.byteLength, (40 + 8 * 3) * 40);
    // A larger reservation on a cached batch uploads nothing: fill bytes are
    // reused, the index buffer and output are rebuilt, and the old ones are
    // destroyed only after the frame is submitted.
    const grown = {...fixture.spec, cached: true, num_verts: 40 + 16 * 3, count: 6 + 6 * 7 * 3,
      border: {...fixture.spec.border, capacity: 16}};
    const destroyedBefore = d.events.length;
    const second = await d.render([grown], {format_version: 6});
    const draw2 = scene(second).draws[0];
    assert.deepEqual(Array.from(new Uint32Array(draw2.index.buffer.bytes)), expectedRunIndices(40, 3, 16));
    assert.notEqual(draw2.index.buffer, draw.index.buffer);
    assert.ok(draw.index.buffer.destroyed && output.destroyed);
    assert.notEqual(draw2.vertices[0], output);
    assert.equal(draw2.vertices[0].bytes.byteLength, (40 + 16 * 3) * 40);
    assert.equal(second.find(pass => pass.copy).copy[0], fillBuffer, "fill bytes are reused, not re-uploaded");
    assert.ok(!fillBuffer.destroyed);
    const retired = d.events.slice(destroyedBefore).filter(event => event[0] === "buffer");
    assert.ok(retired.some(event => event[1] === draw.index.buffer) && retired.some(event => event[1] === output));
    // Outputs are keyed by occurrence of the same geometry, so an unrelated
    // object inserted earlier in the frame rekeys nothing.
    const third = await d.render([{pipeline: "surface", hash: "plain"}, grown], {format_version: 6});
    assert.equal(scene(third).draws[1].vertices[0], draw2.vertices[0]);
    assert.equal(scene(third).draws[1].index.buffer, draw2.index.buffer);
    assert.equal(third.filter(pass => pass.compute || pass.copy).length, 0);
    // Layout and capacity are validated before any resource is touched.
    const resident = () => d.buffers.filter(buffer => !buffer.destroyed).length;
    const before = resident();
    for (const border of [{capacity: 66}, {capacity: "16"}, {layout: [[6, 40]]}, {layout: [[3, 40, 3]]},
                         {layout: [[6, 40, 0]]}, {layout: []}]) {
      await assert.rejects(d.render([{...grown, border: {...grown.border, ...border}}], {format_version: 6}), /border/i);
      assert.equal(resident(), before);
    }
    await assert.rejects(d.render([{...grown, count: grown.count - 3}], {format_version: 6}), /border/i);
    await assert.rejects(d.render([{...grown, num_verts: grown.num_verts + 1}], {format_version: 6}), /border/i);
    await d.render([], {format_version: 6});
    assert.ok(draw2.index.buffer.destroyed && draw2.vertices[0].destroyed && fillBuffer.destroyed);
    await d.destroy();
    assert.ok(d.buffers.every(buffer => buffer.destroyed));
  },
  async lifecycle() {
    for (const legacy of [false, true]) {
      let release;
      const d = await driver({legacy, decode: () => new Promise(resolve => { release = resolve; })});
      const specs = [{kind: legacy ? "image" : "generated", pipeline: "image", textures: {Texture: "light"}}];
      const options = {renderer: legacy ? "winding" : "triangles", texture_data: {light: {offset: 0, nbytes: 4}}};
      const drawing = d.render(specs, options);
      await new Promise(resolve => setImmediate(resolve));
      const stopping = d.destroy();
      const duplicate = d.destroy();
      assert.equal(stopping, duplicate, "concurrent shutdown shares one drain");
      await assert.rejects(d.render([], options), /not active/);
      assert.equal(d.events.filter(([kind]) => kind === "device_destroy").length, 0);
      release({width: 2, height: 2, close() {}});
      await drawing;
      await stopping;
      assert.equal(d.events.filter(([kind]) => kind === "device_destroy").length, 1);
      assert.ok(d.buffers.every(buffer => buffer.destroyed));
      assert.ok(d.textures.filter(texture => texture.descriptor.format !== "canvas").every(texture => texture.destroyed));
      await d.destroy();
      assert.equal(d.events.filter(([kind]) => kind === "device_destroy").length, 1);
      await d.init();
      const restarting = d.render(specs, options);
      await new Promise(resolve => setImmediate(resolve));
      release({width: 2, height: 2, close() {}});
      const restarted = await restarting;
      assert.equal(restarted[legacy ? 1 : 0].draws.length, 1);
      await d.destroy();
      assert.equal(d.events.filter(([kind]) => kind === "device_destroy").length, 2);
    }
  },
  async coverage() {
    const d = await driver();
    const specs = Array.from({length: 256}, () => ({pipeline: "paint_depth", coverage: true, hash: "same"}));
    const passes = await d.render(specs, {samples: 4, supersample: 2});
    assert.equal(passes.length, 3, "255 ownership values then stencil-clear restart, then presentation");
    assert.equal(passes[0].draws.length, 510);
    assert.equal(passes[1].draws.length, 2);
    assert.equal(passes[1].descriptor.colorAttachments[0].loadOp, "load");
    assert.equal(passes[1].descriptor.depthStencilAttachment.depthLoadOp, "load");
    assert.equal(passes[1].descriptor.depthStencilAttachment.stencilLoadOp, "clear");
    for (const [i, pass] of passes.slice(0, 2).entries()) {
      for (let j = 0; j < pass.draws.length; j += 2) {
        const color = pass.draws[j], depth = pass.draws[j + 1];
        assert.equal(color.stencil, j / 2 + 1);
        assert.equal(color.pipeline.descriptor.depthStencil.stencilFront.compare, "not-equal");
        assert.equal(color.pipeline.descriptor.depthStencil.stencilFront.passOp, "replace");
        assert.equal(color.pipeline.descriptor.depthStencil.stencilFront.depthFailOp, "keep");
        assert.equal(color.pipeline.descriptor.depthStencil.depthWriteEnabled, false);
        assert.equal(depth.pipeline.descriptor.fragment.targets[0].writeMask, 0);
        assert.equal(depth.pipeline.descriptor.depthStencil.depthWriteEnabled, true);
        assert.equal(depth.pipeline.descriptor.depthStencil.stencilFront.compare, "always");
        assert.equal(color.vertices[0], depth.vertices[0]);
        assert.notEqual(color.bindings.get(0), depth.bindings.get(0));
        assert.notEqual(color.bindings.get(1), depth.bindings.get(1));
      }
    }
  },
  async paint() {
    const d = await driver();
    const red = {pipeline: 'paint', hash: 'geometry', paint: constantPaint([1, 0, 0, .5])};
    const blue = {...red, paint: constantPaint([0, 0, 1, .75])};
    const draws = (await d.render([red, blue]))[0].draws;
    assert.equal(draws[0].vertices[0], draws[1].vertices[0]);
    const materials = draws.map(draw => draw.bindings.get(1).entries[0].resource.buffer);
    assert.notEqual(materials[0], materials[1]);
    near(Array.from(new Float32Array(materials[0].bytes)).slice(12, 16), [1, 0, 0, .5]);
    const updated = (await d.render([{...blue, cached: true}]))[0].draws[0];
    assert.equal(updated.vertices[0], draws[0].vertices[0]);
    assert.equal(updated.bindings.get(1), draws[1].bindings.get(1));
    assert.ok(materials[0].destroyed);
    assert.ok(!materials[1].destroyed);
    await d.render([]);
    assert.ok(materials[1].destroyed);
  },
  async supersample() {
    const d = await driver();
    const specs = [{ uniforms: {pixel_size: .02, anti_alias_width: 1.25} }];
    const passes = await d.render(specs, {supersample: 2, samples: 4});
    assert.equal(passes.length, 2, "scene MSAA resolve followed by spatial resolve/presentation");
    assert.deepEqual(Array.from(passes[0].descriptor.colorAttachments[0].view.texture.descriptor.size), [640, 360]);
    assert.deepEqual(Array.from(passes[1].descriptor.colorAttachments[0].view.texture.descriptor.size), [320, 180]);
    assert.equal(passes[1].draws[0].bindings.get(0).entries.length, 1, "exact textureLoad resolve needs no sampler");
    assert.ok(passes[1].draws[0].pipeline.descriptor.fragment.module.code.includes('textureLoad'));
    near([uniform(passes[0].draws[0])[27], uniform(passes[0].draws[0])[31]], [.01, 2.5]);
    assert.equal(specs[0].uniforms.pixel_size, .02);
    assert.equal(specs[0].uniforms.anti_alias_width, 1.25);
    const restored = await d.render(specs, {supersample: 1, samples: 1, resolution: [640, 360]});
    assert.deepEqual(Array.from(restored[1].descriptor.colorAttachments[0].view.texture.descriptor.size), [640, 360]);
    assert.equal(restored[1].draws[0].bindings.get(0).entries.length, 2);
  },
  async ordering() {
    const d = await driver();
    const specs = Object.keys(STRIDE).flatMap(base => ["", "_depth"].map(suffix => ({
      pipeline: base + suffix, count: base === "dot" ? 4 : 3, instances: 2,
      num_verts: base === "stroke" ? 6 : 3,
      indexed: base === "surface", index_count: base === "surface" ? 3 : 0,
      uniforms: { is_fixed_in_frame: 1, anti_alias_width: 0.75, premultiplied_output: 0 },
    })));
    for (const samples of [1, 4]) {
      const passes = await d.render(specs, { samples });
      assert.equal(passes.length, 2, "one scene pass followed by one blit");
      assert.equal(passes[0].draws.length, specs.length);
      const clear = passes[0].descriptor.colorAttachments[0].clearValue;
      near([clear.r, clear.g, clear.b, clear.a], [0.1, 0.2, 0.3, 0.5]);
      specs.forEach((spec, i) => {
        const draw = passes[0].draws[i], pipeline = draw.pipeline.descriptor;
        assert.deepEqual(draw.args, [spec.count, spec.instances]);
        assert.equal(draw.indexed, spec.indexed);
        if (draw.index) {
          assert.equal(draw.index.format, "uint32");
          assert.deepEqual(Array.from(new Uint32Array(draw.index.buffer.bytes)), [0, 1, 2]);
        }
        assert.equal(pipeline.multisample.count, samples);
        assert.equal(pipeline.depthStencil.depthWriteEnabled, spec.pipeline.endsWith("_depth"));
        assert.equal(pipeline.depthStencil.depthCompare, spec.pipeline.endsWith("_depth") ? "less" : "always");
        for (const component of ["color", "alpha"]) {
          assert.equal(pipeline.fragment.targets[0].blend[component].srcFactor, "one");
          assert.equal(pipeline.fragment.targets[0].blend[component].dstFactor, "one-minus-src-alpha");
        }
        assert.equal(uniform(draw).length, 48);
        assert.equal(uniform(draw)[19], 1);
        assert.equal(uniform(draw)[31], 0.75);
        assert.equal(uniform(draw)[42], 1, "generated alpha convention cannot be overridden");
        near(uniform(draw).slice(44), [1, 1, 0, 0]);
      });
      assert.equal(Boolean(passes[0].descriptor.colorAttachments[0].resolveTarget), samples === 4);
    }
    assert.equal(d.textures.filter(t => t.descriptor.format === "rgba16float").length, 0);
  },
  async reuse() {
    const d = await driver();
    const same = { pipeline: "surface", hash: "shared", indexed: true, index_count: 3 };
    const first = (await d.render([same, { ...same, uniforms: { frame_scale: 2 } }]))[0].draws;
    assert.equal(first[0].vertices[0], first[1].vertices[0]);
    assert.notEqual(uniformBuffer(first[0]), uniformBuffer(first[1]));
    const n = d.buffers.length;
    const cached = [{ ...same, cached: true }, { ...same, cached: true, uniforms: { frame_scale: 2 } }];
    const second = (await d.render(cached))[0].draws;
    assert.equal(d.buffers.length, n, "warm geometry and uniform bindings allocate no buffers");
    first.forEach((draw, i) => assert.equal(draw.bindings.get(0), second[i].bindings.get(0)));
    const third = (await d.render([{ ...same, cached: true, uniforms: { frame_scale: 3 } }]))[0].draws[0];
    assert.equal(third.vertices[0], first[0].vertices[0]);
    assert.ok(first.every(draw => uniformBuffer(draw).destroyed));
    const submission = d.events.findIndex(([event, n]) => event === "submit" && n === 3);
    assert.ok(d.events.findIndex(([event, b]) => event === "buffer" && b === uniformBuffer(first[0])) > submission);
  },
  async lifetime() {
    const d = await driver();
    const specs = Array.from({ length: 600 }, (_, i) => ({ hash: `mesh-${i}`, indexed: true, index_count: 3 }));
    const first = (await d.render(specs))[0].draws;
    const created = d.buffers.length;
    await d.render(specs.map(spec => ({ ...spec, cached: true })));
    assert.equal(d.buffers.length, created, "large frames must not evict their own active geometry");
    await d.render([{ ...specs[0], cached: true }]);
    assert.equal(first[0].vertices[0].destroyed, false);
    assert.ok(first.slice(1).every(draw => draw.vertices[0].destroyed && draw.index.buffer.destroyed));
    const missed = await d.render([{ ...specs[1], cached: true }]);
    assert.equal(missed[0].draws.length, 0);
    assert.equal(d.cacheMisses(), 1);
    assert.equal((await d.render([specs[1]]))[0].draws.length, 1, "resent geometry recovers after retirement");
  },
  async textures() {
    const d = await driver();
    const specs = [{ pipeline: "image", textures: { Texture: "light" } },
      { pipeline: "texsurface_depth", textures: { LightTexture: "light" } }];
    const first = (await d.render(specs, { texture_data: { light: { offset: 0, nbytes: 4 } } }))[0].draws;
    assert.equal(first[0].bindings.get(1).entries.length, 2);
    const bindings = first[1].bindings.get(1).entries;
    assert.equal(bindings.length, 3);
    assert.equal(bindings[0].resource.texture, bindings[1].resource.texture);
    const second = (await d.render(specs.map(s => ({ ...s, cached: true }))))[0].draws;
    first.forEach((draw, i) => assert.equal(draw.bindings.get(1), second[i].bindings.get(1)));
    const original = first[0].bindings.get(1).entries[0].resource.texture;
    await d.render([]);
    assert.ok(original.destroyed, "empty frame retires texture storage");
    const submitted = d.events.findIndex(([event, n]) => event === "submit" && n === 3);
    assert.ok(d.events.findIndex(([event, texture]) => event === "texture" && texture === original) > submitted);
    const returning = (await d.render(specs, { texture_data: { light: { offset: 0, nbytes: 4 } } }))[0].draws;
    const recreated = returning[0].bindings.get(1).entries[0].resource.texture;
    assert.notEqual(recreated, original);
    assert.notEqual(returning[0].bindings.get(1), first[0].bindings.get(1), "retired texture binding must be recreated");
    assert.ok(!recreated.destroyed);
    const missing = await d.render([{ pipeline: "image", textures: { Texture: "unknown" } }]);
    assert.equal(missing[0].draws.length, 0);
    assert.equal(d.cacheMisses(), 1);
  },
  async borderCompute() {
    const d = await driver({limits: {maxComputeWorkgroupsPerDimension: 2}});
    const fixture = borderFixture();
    const specs = [fixture.spec, {...fixture.spec, uniforms: {camera_position: [0, -10, 10]}}];
    const first = await d.render(specs, fixture.options);
    const compute = first.filter(pass => pass.compute);
    assert.deepEqual(compute.flatMap(pass => pass.draws.map(draw => draw.count)), [2, 1, 2, 1]);
    const scene = first.find(pass => pass.descriptor && pass.descriptor.depthStencilAttachment);
    assert.ok(first.indexOf(compute.at(-1)) < first.indexOf(scene));
    assert.equal(first.filter(pass => pass.copy).length, 2);
    const outputs = scene.draws.map(draw => draw.vertices[0]);
    assert.notEqual(...outputs, "same source with distinct uniforms needs distinct writable outputs");
    const views = compute.map(pass => pass.draws[0].bindings.get(1).entries[1].resource);
    views.forEach(view => { assert.equal(view.offset, 1280); assert.equal(view.size, (8 + 64 * 3) * 40); });
    assert.equal(compute[0].draws[0].bindings.get(1).entries[0].resource.buffer,
      compute[1].draws[0].bindings.get(1).entries[0].resource.buffer, "immutable source storage is shared");
    const cached = specs.map(spec => ({...spec, cached: true}));
    const same = await d.render(cached, {format_version: 5});
    assert.ok(same.every(pass => !pass.compute && !pass.copy), "static frames need no generation or fill copies");
    const zoom = await d.render(cached, {format_version: 5, camera: {...CAMERA, frame_scale: .95}});
    assert.equal(zoom.filter(pass => pass.compute).length, 2);
    assert.equal(zoom.filter(pass => pass.copy).length, 0);
    assert.deepEqual(zoom.find(pass => pass.descriptor && pass.descriptor.depthStencilAttachment).draws.map(draw => draw.vertices[0]), outputs);
    await d.render([], {format_version: 5});
    outputs.forEach(output => assert.ok(output.destroyed));
    const returning = await d.render([fixture.spec], fixture.options);
    assert.notEqual(returning.find(pass => pass.descriptor && pass.descriptor.depthStencilAttachment).draws[0].vertices[0], outputs[0]);
    const missing = await d.render([{...fixture.spec, cached: true,
      border: {...fixture.spec.border, hash: "f".repeat(32)}}], {format_version: 5});
    assert.equal(missing[0].draws.length, 0);
    assert.equal(d.cacheMisses(), 1);
    await d.destroy();
    assert.ok(d.buffers.every(buffer => buffer.destroyed));
  },
  async borderComputeFailures() {
    const d = await driver({limits: {maxStorageBufferBindingSize: 3000, maxBufferSize: 5000}});
    const fixture = borderFixture(1);
    await d.render([fixture.spec], fixture.options);
    const retained = () => d.buffers.filter(buffer => !buffer.destroyed);
    const previous = retained();
    for (let i = 0; i < 6; i++) {
      const next = borderFixture(1, 40, (i + 1).toString(16).repeat(32));
      await assert.rejects(d.render([{...next.spec, hash: `failed-fill-${i}`}, {pipeline: "invalid", stride: 40}], next.options),
        /unsupported generated pipeline/);
      assert.deepEqual(retained(), previous, "failed late batches must not accumulate source/output/fill/uniform storage");
    }
    for (const [field, value] of [[7, -1], [36, -1], [37, .5], [38, .5], [39, 1], [0, NaN]]) {
      const bad = [...fixture.records]; bad[field] = value;
      await assert.rejects(d.render([fixture.spec], {format_version: 5,
        border_definitions: {[fixture.spec.border.hash]: bad}}), /border/);
      assert.deepEqual(retained(), previous);
    }
    const malformed = [null, [], 1, true];
    for (const border_data of malformed) {
      await assert.rejects(d.render([fixture.spec], {format_version: 5, border_data}), /border/);
    }
    // A failed frame must not record changed camera generation as complete.
    const changed = {...fixture.options, camera: {...CAMERA, frame_scale: .95}};
    await assert.rejects(d.render([fixture.spec, {pipeline: "invalid", stride: 40}], changed), /unsupported/);
    const retry = await d.render([fixture.spec], changed);
    assert.equal(retry.filter(pass => pass.compute).length, 1);
    assert.equal(retry.filter(pass => pass.copy).length, 0);
    const capped = borderFixture(1, 40, "d".repeat(32));
    capped.records[38] = 1;
    const cappedFrame = await d.render([capped.spec], capped.options);
    assert.equal(cappedFrame.filter(pass => pass.compute).length, 1, "finite capped-density records are accepted");
    const large = borderFixture(2, 40, "e".repeat(32));
    await assert.rejects(d.render([large.spec], large.options), /output exceeds/);
    await d.destroy();
    assert.ok(d.buffers.every(buffer => buffer.destroyed));
  },
  async paintDefinitions() {
    const d = await driver();
    const red = "a".repeat(32), blue = "b".repeat(32);
    const specs = [{pipeline: "paint", hash: "shared", paint_hash: red},
      {pipeline: "paint", hash: "shared", paint_hash: blue},
      {pipeline: "paint_depth", hash: "depth", coverage: true, paint_hash: red}];
    const options = {format_version: 4, samples: 4, paint_padding: 1,
      paint_definitions: {[red]: constantPaint([1, 0, 0, .5]), [blue]: constantPaint([0, 0, 1, .75])}};
    const first = (await d.render(specs, options))[0].draws;
    const storage = draw => draw.bindings.get(1).entries[0].resource.buffer;
    const redBuffer = storage(first[0]), blueBuffer = storage(first[1]);
    assert.equal(first[0].vertices[0], first[1].vertices[0], "geometry identity is independent of material");
    assert.notEqual(redBuffer, blueBuffer);
    assert.equal(storage(first[2]), redBuffer);
    assert.equal(storage(first[3]), redBuffer, "depth replay shares coefficient storage across layouts");
    assert.deepEqual(Array.from(new Float32Array(redBuffer.bytes)).slice(12, 16), [1, 0, 0, .5]);
    assert.equal(d.buffers.filter(b => b.descriptor.usage === 8 && !b.destroyed).length, 2);
    const same = (await d.render(specs.map(s => ({...s, cached: true})), {format_version: 4, samples: 4}))[0].draws;
    first.forEach((draw, i) => assert.equal(draw.bindings.get(1), same[i].bindings.get(1)));
    const changedSamples = (await d.render([{...specs[0], cached: true}], {format_version: 4, samples: 1}))[0].draws[0];
    assert.equal(storage(changedSamples), redBuffer, "sample changes do not duplicate material buffers");
    assert.notEqual(changedSamples.bindings.get(1), first[0].bindings.get(1));
    assert.ok(blueBuffer.destroyed);
    await d.render([], {format_version: 4});
    assert.ok(redBuffer.destroyed);
    const recreated = (await d.render([specs[0]], options))[0].draws[0];
    assert.notEqual(storage(recreated), redBuffer);
    assert.ok(!storage(recreated).destroyed);
    const missing = await d.render([{...specs[0], cached: true, paint_hash: "c".repeat(32)}], {format_version: 4});
    assert.equal(missing[0].draws.length, 0, "a missing definition cannot reuse the last material");
    assert.equal(d.cacheMisses(), 1);
    assert.equal(d.buffers.filter(b => b.descriptor.usage === 8 && !b.destroyed).length, 0);
    await d.destroy();
    await d.init();
    await d.render([specs[0]], options);
    assert.equal(d.buffers.filter(b => b.descriptor.usage === 8 && !b.destroyed).length, 1);
    await d.destroy();
  },
  async paintDefinitionFailures() {
    const d = await driver();
    const old = "a".repeat(32), next = "b".repeat(32);
    const original = constantPaint([1, 0, 0, .5]);
    const spec = {pipeline: "paint", paint_hash: old};
    const first = (await d.render([spec], {format_version: 4, paint_definitions: {[old]: original}}))[0].draws[0];
    const material = first.bindings.get(1).entries[0].resource.buffer;
    const failures = [original.slice(0, -1), [...original, 0],
      ...[[3, 0], [3, -1], [3, Infinity], [7, .5], [7, 4097], [11, 2], [11, 1], [15, NaN]]
        .map(([index, value]) => { const changed = [...original]; changed[index] = value; return changed; })];
    for (const values of failures) {
      await assert.rejects(d.render([{...spec, paint_hash: next}],
        {format_version: 4, paint_definitions: {[next]: values}}), /paint/);
      assert.ok(!material.destroyed);
      assert.equal(d.buffers.filter(b => b.descriptor.usage === 8 && !b.destroyed).length, 1);
    }
    for (const ref of [{offset: -1, nbytes: 96}, {offset: .5, nbytes: 96},
      {offset: 0, nbytes: 10000}, {offset: 0, nbytes: -1}]) {
      await assert.rejects(d.render([spec], {format_version: 4, paint_data: {[next]: ref}}), /paint.*payload/);
    }
    for (const paint_data of [null, [], 1, true, "definitions"]) {
      await assert.rejects(d.render([spec], {format_version: 4, paint_data}), /paint definitions/);
    }
    for (const ref of [null, [], 1, true, "span"]) {
      await assert.rejects(d.render([spec], {format_version: 4, paint_data: {[old]: ref}}), /paint definition span/);
    }
    for (const paint of [null, 1, true, "paint", {}, [original],
      original.map((v, i) => i === 12 ? "1" : v), original.map((v, i) => i === 12 ? true : v)]) {
      await assert.rejects(d.render([{pipeline: "paint", paint}], {format_version: 3}), /paint/);
    }
    await assert.rejects(d.render([spec], {format_version: 4,
      paint_definitions: {[old]: constantPaint([0, 0, 1, .5])}}), /redefined/);
    await assert.rejects(d.render([{...spec, paint_hash: "bad"}], {format_version: 4}), /paint hash/);
    // A later encoding failure rolls back already-created storage and bindings.
    await assert.rejects(d.render([{...spec, paint_hash: next}, {pipeline: "invalid", stride: 40}],
      {format_version: 4, paint_definitions: {[next]: original}}), /unsupported generated pipeline/);
    assert.equal(d.submissions.length, 1);
    assert.equal(d.buffers.filter(b => b.descriptor.usage === 8 && !b.destroyed).length, 1);
    const recovered = (await d.render([{...spec, cached: true}], {format_version: 4}))[0].draws[0];
    assert.equal(recovered.bindings.get(1), first.bindings.get(1));
    await d.render([{...spec, cached: true, paint_hash: next}],
      {format_version: 4, paint_definitions: {[next]: original}});
    await d.destroy();

    const pending = [];
    const asyncDriver = await driver({decode: () => new Promise((resolve, reject) => pending.push({resolve, reject}))});
    const failed = asyncDriver.render([spec, {pipeline: "image", textures: {Texture: "broken"}}],
      {format_version: 4, paint_definitions: {[old]: original}, texture_data: {broken: {offset: 0, nbytes: 4}}});
    const rejected = assert.rejects(failed, /decode failed/);
    const recovery = asyncDriver.render([spec], {format_version: 4, paint_definitions: {[old]: original}});
    await new Promise(resolve => setImmediate(resolve));
    pending.shift().reject(new Error("decode failed"));
    await rejected; await recovery;
    assert.equal(asyncDriver.submissions.length, 1);
    assert.equal(asyncDriver.buffers.filter(b => b.descriptor.usage === 8 && !b.destroyed).length, 1);
    await asyncDriver.destroy();
  },
  async windingTextures() {
    const d = await driver({legacy: true});
    const options = {renderer: "winding"};
    const image = hash => ({kind: "image", pipeline: "image", hash: "same-vertices",
      textures: {Texture: hash}});
    const bytes = hash => ({...options, texture_data: {[hash]: {offset: 0, nbytes: 4}}});
    const storage = () => d.textures.filter(t => t.descriptor.usage & 4);
    const retained = () => storage().filter(t => !t.destroyed);
    let previous;
    for (let i = 0; i < 24; i++) {
      const spec = {...image(`image-${i}`), cached: i > 0};
      const frame = await d.render([spec], bytes(`image-${i}`));
      const current = frame[1].draws[0].bindings.get(1).entries[0].resource.texture;
      assert.deepEqual(retained(), [current], "unique images retain only current-frame storage");
      if (previous) {
        assert.ok(previous.destroyed);
        const submit = d.events.findIndex(([kind, n]) => kind === "submit" && n === i + 1);
        assert.ok(d.events.findIndex(([kind, t]) => kind === "texture" && t === previous) > submit,
          "retirement must follow submission");
      }
      previous = current;
    }
    const created = storage().length;
    await d.render([{...image("image-23"), cached: true}], options);
    assert.deepEqual(retained(), [previous], "cached batches keep textures absent from texture_data");
    assert.equal(storage().length, created);
    await d.render([], options);
    assert.equal(retained().length, 0, "an empty frame retires all image storage");
    const returning = await d.render([image("image-23")], bytes("image-23"));
    const reinstalled = returning[1].draws[0].bindings.get(1).entries[0].resource.texture;
    assert.notEqual(reinstalled, previous);
    assert.deepEqual(retained(), [reinstalled]);
    assert.equal(d.cacheMisses(), 0);
    await d.destroy();
    assert.equal(retained().length, 0);
  },
  async windingSharedTextures() {
    const d = await driver({legacy: true});
    const options = {renderer: "winding"};
    const surface = {kind: "texsurface", pipeline: "texsurface", hash: "surface",
      textures: {LightTexture: "light", DarkTexture: "dark"}};
    const image = {kind: "image", pipeline: "image", hash: "image", textures: {Texture: "dark"}};
    const first = await d.render([surface, image], {...options, texture_data: {
      light: {offset: 0, nbytes: 4}, dark: {offset: 4, nbytes: 4}}});
    const entries = first[1].draws[0].bindings.get(1).entries;
    const light = entries[0].resource.texture, dark = entries[1].resource.texture;
    assert.notEqual(light, dark);
    assert.equal(first[2].draws[0].bindings.get(1).entries[0].resource.texture, dark);
    await d.render([{...image, cached: true}], options);
    assert.ok(light.destroyed);
    assert.ok(!dark.destroyed, "a texture shared by another object remains live");
    const fallback = await d.render([{...surface, cached: true,
      textures: {LightTexture: "dark"}}], options);
    const views = fallback[1].draws[0].bindings.get(1).entries;
    assert.equal(views[0].resource.texture, dark);
    assert.equal(views[1].resource.texture, dark, "one light texture also supplies the dark channel");
    assert.equal(d.textures.filter(t => (t.descriptor.usage & 4) && !t.destroyed).length, 1);
    await d.destroy();
  },
  async windingTextureFailures() {
    const pending = [];
    let closed = 0;
    const d = await driver({legacy: true,
      decode: () => new Promise((resolve, reject) => pending.push({resolve, reject}))});
    const tick = () => new Promise(resolve => setImmediate(resolve));
    const bitmap = () => ({width: 2, height: 2, close() { closed++; }});
    const options = {renderer: "winding"};
    const spec = {kind: "image", pipeline: "image", hash: "original", textures: {Texture: "old"}};
    const first = d.render([spec], {...options, texture_data: {old: {offset: 0, nbytes: 4}}});
    await tick(); pending.shift().resolve(bitmap()); await first;
    const original = d.submissions[0][1].draws[0].bindings.get(1).entries[0].resource.texture;
    const failed = d.render([{...spec, textures: {Texture: "new"}}], {...options, texture_data: {
      new: {offset: 0, nbytes: 4}, broken: {offset: 0, nbytes: 4}}});
    const rejection = assert.rejects(failed, /decode failed/);
    const recovery = d.render([{...spec, cached: true}], options);
    await tick(); pending.shift().resolve(bitmap()); await tick();
    assert.equal(d.submissions.length, 1, "a following cached frame waits for the pending decode");
    pending.shift().reject(new Error("decode failed"));
    await rejection; await recovery;
    const uploads = d.textures.filter(t => t.descriptor.usage & 4);
    assert.equal(uploads.length, 2);
    assert.ok(!original.destroyed, "failure preserves the last submitted frame's textures");
    assert.ok(uploads[1].destroyed, "failure rolls back already-decoded new textures");
    assert.equal(closed, 2, "all successfully decoded bitmaps close, including rolled-back uploads");
    assert.equal(d.submissions.length, 2);
    assert.equal(d.cacheMisses(), 0);
    const retry = d.render([{...spec, cached: true, textures: {Texture: "new"}}],
      {...options, texture_data: {new: {offset: 0, nbytes: 4}}});
    await tick(); assert.equal(pending.length, 1, "a rolled-back hash must decode again");
    pending.shift().resolve(bitmap()); await retry;
    assert.ok(original.destroyed);
    assert.equal(closed, 3);
    await d.destroy();

    // Encoding can fail after a texture bind group was created. Reinstalling
    // the same hash must not reuse a view of the rolled-back GPU texture.
    const generated = await driver({legacy: true});
    const textured = {pipeline: "image", textures: {Texture: "new"}};
    const data = {texture_data: {new: {offset: 0, nbytes: 4}}};
    await assert.rejects(generated.render([textured, {pipeline: "invalid", stride: 40}], data),
      /unsupported generated pipeline/);
    assert.equal(generated.submissions.length, 0);
    assert.ok(generated.textures.filter(t => t.descriptor.usage & 4).every(t => t.destroyed));
    const retried = await generated.render([textured], data);
    assert.ok(!retried[0].draws[0].bindings.get(1).entries[0].resource.texture.destroyed);
    await generated.destroy();
  },
  async modes() {
    const d = await driver();
    await assert.rejects(d.render([], { renderer: "winding", samples: 0 }), /requires generated triangle/);
    assert.equal(d.submissions.length, 0);
    await assert.rejects(d.render([], { samples: 0 }), /sample count/);
    await assert.rejects(d.render([{ pipeline: "fill", stride: 40 }]), /unsupported generated pipeline/);
    assert.equal((await d.render([])).length, 2, "a rejected frame must not poison the render queue");
  },
  async overlap() {
    const pending = [];
    const d = await driver({ decode: () => new Promise(resolve => pending.push(resolve)) });
    const first = d.render([{ pipeline: "image", textures: { Texture: "light" } }], {
      texture_data: { light: { offset: 0, nbytes: 4 } }, resolution: [320, 180], samples: 1,
    });
    const second = d.render([{ hash: "later-frame" }], { resolution: [640, 360], samples: 4 });
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(pending.length, 1);
    assert.equal(d.submissions.length, 0, "later frames wait for earlier texture decoding");
    pending[0]({ width: 2, height: 2, close() {} });
    await Promise.all([first, second]);
    assert.equal(d.submissions.length, 2);
    for (const [i, resolution] of [[0, [320, 180]], [1, [640, 360]]]) {
      const pass = d.submissions[i][0];
      assert.deepEqual(Array.from(pass.descriptor.colorAttachments[0].view.texture.descriptor.size), resolution);
      assert.equal(pass.draws[0].pipeline.descriptor.multisample.count, i ? 4 : 1);
    }
  },
  // A real patch fill frame from the Python encoder (tests.test_generated_webgpu_commands):
  // three red squares and a blue one, so one instanced group of three and one alone.
  async patchWire() {
    const d = await driver();
    const file = fs.readFileSync(process.argv[3]);
    const passes = await d.renderBytes(file.buffer.slice(file.byteOffset, file.byteOffset + file.byteLength));
    const compute = passes.filter(pass => pass.compute);
    assert.equal(compute.length, 1, "the border stage runs once for the run");
    const scene = passes.find(pass => pass.descriptor && pass.descriptor.depthStencilAttachment);
    const kinds = scene.draws.map(draw => draw.pipeline.descriptor.vertex.entryPoint
      + (draw.pipeline.descriptor.vertex.buffers.length ? ":strip" : ""));
    // Per group: fan mark, patch mark, strip mark, cover, strip cover.
    const perGroup = ["vs_fan", "vs_patch", "vs_main:strip", "vs_cover", "vs_main:strip"];
    assert.deepEqual(kinds, [...perGroup, ...perGroup]);
    const [fanA, patchA, stripMarkA, coverA, stripCoverA, fanB] = scene.draws;
    assert.deepEqual(fanA.args, [12, 3, 0, 0], "three instances of a four-curve square");
    assert.deepEqual(patchA.args, [12, 3, 0, 0]);
    assert.deepEqual(coverA.args, [24, 3, 0, 0]);
    assert.deepEqual(fanB.args, [12, 1, 0, 3]);
    assert.equal(stripMarkA.stencil, 0x80);
    assert.equal(coverA.stencil, 0);
    assert.equal(stripMarkA.pipeline.descriptor.fragment.targets[0].writeMask, 0);
    assert.equal(stripMarkA.pipeline.descriptor.depthStencil.stencilWriteMask, 0x80);
    assert.equal(stripCoverA.pipeline.descriptor.depthStencil.stencilFront.passOp, "zero");
    assert.equal(fanA.pipeline.descriptor.depthStencil.stencilFront.passOp, "increment-wrap");
    assert.equal(fanA.pipeline.descriptor.depthStencil.stencilBack.passOp, "decrement-wrap");
    assert.equal(fanA.pipeline.descriptor.depthStencil.stencilWriteMask, 0x7F);
    assert.equal(fanA.pipeline.descriptor.fragment.targets[0].writeMask, 0);
    assert.equal(coverA.pipeline.descriptor.fragment.targets[0].writeMask, 15);
    assert.equal(coverA.pipeline.descriptor.depthStencil.stencilFront.compare, "not-equal");
    // The strips draw the border stage's output through the surface pipeline
    // with the run's strip pattern; the fan draws pull from the records and
    // the object table.
    const output = compute[0].draws[0].bindings.get(1).entries[1].resource.buffer;
    assert.equal(stripMarkA.vertices[0], output);
    assert.equal(stripMarkA.args[2], 0);
    assert.equal(stripCoverA.args[2], 0);
    const strips = new Uint32Array(stripMarkA.index.buffer.bytes);
    assert.equal(strips.length, stripMarkA.args[0] + fanB.args[0] / 12 * stripMarkA.args[0] / 3);
    const objects = fanA.bindings.get(1).entries[1].resource.buffer;
    assert.equal(objects.bytes.byteLength, 4 * 32, "eight words per object");
    const words = new Float32Array(objects.bytes);
    assert.deepEqual([words[3], words[4], words[5], words[11], words[12]], [0, 4, 1, 4, 4]);
    // The same frame again reuses everything; an empty frame retires it.
    const again = await d.renderBytes(file.buffer.slice(file.byteOffset, file.byteOffset + file.byteLength));
    assert.equal(again.filter(pass => pass.compute).length, 0, "the border stage's state is unchanged");
    const resident = () => d.buffers.filter(buffer => !buffer.destroyed).length;
    const before = resident();
    await d.render([], {format_version: 7});
    assert.ok(resident() < before - 3, "records, table, output and index pattern retire");
    await d.destroy();
    assert.ok(d.buffers.every(buffer => buffer.destroyed));
  },
  // Two real surface net frames: the port's surfaces scene, then the same
  // scene after a zoom, whose batches are cached at a larger reservation.
  async netWire() {
    const d = await driver();
    const load = file => { const bytes = fs.readFileSync(file); return bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength); };
    const first = await d.renderBytes(load(process.argv[3]));
    const compute = first.filter(pass => pass.compute);
    assert.equal(compute.length, 2, "one evaluation per net");
    const scene = first.find(pass => pass.descriptor && pass.descriptor.depthStencilAttachment);
    assert.equal(scene.draws.length, 2);
    const [sphere, textured] = scene.draws;
    for (const [draw, pass] of [[sphere, compute[0]], [textured, compute[1]]]) {
      assert.ok(draw.indexed);
      assert.equal(draw.vertices[0], pass.draws[0].bindings.get(1).entries[1].resource.buffer, "draws the evaluated output");
      const params = new Uint32Array(pass.draws[0].bindings.get(0).entries[1].resource.buffer.bytes);
      const [, nu, nv, , capacity] = params;
      const patches = ((nu - 1) / 2) * ((nv - 1) / 2);
      assert.equal(draw.args[0], patches * 6 * capacity * capacity);
      const indices = new Uint32Array(draw.index.buffer.bytes);
      assert.equal(indices.length, draw.args[0]);
      assert.deepEqual(Array.from(indices.slice(0, 6)), [0, capacity + 1, 1, 1, capacity + 1, capacity + 2]);
    }
    assert.equal(sphere.pipeline.descriptor.vertex.buffers[0].arrayStride, 40);
    assert.equal(textured.pipeline.descriptor.vertex.buffers[0].arrayStride, 36);
    assert.ok(textured.bindings.get(1).entries.some(entry => entry.resource.texture), "the texture binds as before");
    const outputs = compute.map(pass => pass.draws[0].bindings.get(1).entries[1].resource.buffer);
    const sources = compute.map(pass => pass.draws[0].bindings.get(1).entries[0].resource.buffer);
    const second = await d.renderBytes(load(process.argv[4]));
    const again = second.filter(pass => pass.compute);
    assert.equal(again.length, 2, "a zoom re-evaluates both nets");
    const grown = second.find(pass => pass.descriptor && pass.descriptor.depthStencilAttachment).draws;
    assert.ok(grown[0].args[0] > sphere.args[0], "the reservation grew with the zoom");
    assert.deepEqual(again.map(pass => pass.draws[0].bindings.get(1).entries[0].resource.buffer), sources, "sources are reused");
    assert.ok(outputs.every(output => output.destroyed), "the old reservations retire after the frame");
    assert.ok(sphere.index.buffer.destroyed);
    await d.destroy();
    assert.ok(d.buffers.every(buffer => buffer.destroyed));
  },
  // Three real program frames (docs/phase_b3_plan.md): a path and a net
  // under a blend, then the same play at another alpha with nothing but
  // the scalar on the wire, then that frame again.
  async programWire() {
    const d = await driver();
    const load = file => { const bytes = fs.readFileSync(file); return bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength); };
    const first = await d.renderBytes(load(process.argv[3]));
    const compute = first.filter(pass => pass.compute);
    // The path's blend and finalize share a pass; the net's blend is one;
    // then the border stage and the net stage read the outputs.
    assert.deepEqual(compute.map(pass => pass.draws.length), [2, 1, 1, 1]);
    const [pathProgram, netProgram, border, net] = compute;
    // The fake records a pass's last pipeline: the path's pass ends in the
    // finalize kernel, the net's is the blend alone.
    const code = pass => pass.pipeline.descriptor.compute.module.code;
    assert.ok(code(pathProgram).includes("FinalizeParams") && code(netProgram).includes("BlendParams"));
    assert.ok(!code(border).includes("BlendParams") && !code(net).includes("BlendParams"));
    const rows = pathProgram.draws[0].bindings.get(1).entries[2].resource.buffer;
    const records = pathProgram.draws[1].bindings.get(1).entries[1].resource.buffer;
    const strokes = pathProgram.draws[1].bindings.get(1).entries[2].resource.buffer;
    assert.equal(pathProgram.draws[1].bindings.get(1).entries[0].resource.buffer, rows, "finalize reads the blended rows");
    assert.equal(border.draws[0].bindings.get(1).entries[0].resource.buffer, records, "the border stage reads the finalized records");
    const netRows = netProgram.draws[0].bindings.get(1).entries[2].resource.buffer;
    assert.equal(net.draws[0].bindings.get(1).entries[0].resource.buffer, netRows, "the net stage reads the blended net");
    const alpha = pass => new Float32Array(pass.draws[0].bindings.get(0).entries[0].resource.buffer.bytes)[1];
    // The scalar is the play's eased alpha, the same for both animations.
    const first_alpha = alpha(pathProgram);
    assert.ok(first_alpha > 0 && first_alpha < 1 && alpha(netProgram) === first_alpha);
    const scene = first.find(pass => pass.descriptor && pass.descriptor.depthStencilAttachment);
    const kinds = scene.draws.map(draw => draw.pipeline.descriptor.vertex.entryPoint);
    assert.deepEqual(kinds, ["vs_fan", "vs_patch", "vs_main", "vs_cover", "vs_main", "vs_main", "vs_main"]);
    const [fan, , stripMark, , , stroke, surface] = scene.draws;
    assert.equal(fan.bindings.get(1).entries[0].resource.buffer, records, "the fan pulls from the finalized records");
    assert.equal(stripMark.vertices[0], border.draws[0].bindings.get(1).entries[1].resource.buffer);
    assert.equal(stroke.vertices[0], strokes, "the stroke draws the finalized instances");
    assert.equal(stroke.pipeline.descriptor.vertex.buffers[0].arrayStride, 204, "three rows per instance");
    assert.equal(stroke.args[1], records.bytes.byteLength / 176, "one instance per curve");
    assert.equal(surface.vertices[0], net.draws[0].bindings.get(1).entries[1].resource.buffer);
    const sources = [...pathProgram.draws[0].bindings.get(1).entries.slice(0, 2), ...netProgram.draws[0].bindings.get(1).entries.slice(0, 2)]
      .map(entry => entry.resource.buffer);
    // Another alpha: every stage re-evaluates from the same sources and outputs.
    const second = await d.renderBytes(load(process.argv[4]));
    const again = second.filter(pass => pass.compute);
    assert.deepEqual(again.map(pass => pass.draws.length), [2, 1, 1, 1]);
    assert.ok(alpha(again[0]) > first_alpha && alpha(again[1]) === alpha(again[0]));
    assert.deepEqual([...again[0].draws[0].bindings.get(1).entries.slice(0, 2), ...again[1].draws[0].bindings.get(1).entries.slice(0, 2)]
      .map(entry => entry.resource.buffer), sources, "sources are reused");
    assert.equal(again[0].draws[0].bindings.get(1).entries[2].resource.buffer, rows, "outputs are reused");
    assert.equal(d.cacheMisses(), 0);
    // The same alpha again: nothing to evaluate, nothing to regenerate.
    const third = await d.renderBytes(load(process.argv[5]));
    assert.equal(third.filter(pass => pass.compute).length, 0);
    const resident = () => d.buffers.filter(buffer => !buffer.destroyed).length;
    const before = resident();
    await d.render([], {format_version: 7});
    assert.ok(resident() < before - 6, "sources, outputs, records and strokes retire");
    assert.ok([rows, records, strokes, netRows, ...sources].every(buffer => buffer.destroyed));
    await d.destroy();
    assert.ok(d.buffers.every(buffer => buffer.destroyed));
  },
  async wire() {
    const d = await driver();
    const file = fs.readFileSync(process.argv[3]);
    const passes = await d.renderBytes(file.buffer.slice(file.byteOffset, file.byteOffset + file.byteLength));
    assert.equal(passes.length, 2);
    const [surface, dot] = passes[0].draws;
    assert.equal(surface.indexed, true);
    assert.deepEqual(Array.from(new Uint32Array(surface.index.buffer.bytes)), [2, 0, 1]);
    assert.deepEqual(surface.args, [3, 1]);
    assert.deepEqual(dot.args, [4, 2]);
    assert.equal(surface.vertices[0].bytes.byteLength, 120);
    assert.equal(dot.vertices[0].bytes.byteLength, 64);
    assert.equal(uniform(surface)[42], 1);
  },
};

cases[process.argv[2]]().catch(error => { console.error(error); process.exitCode = 1; });

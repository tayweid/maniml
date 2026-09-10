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
    if (base === "paint" && !batch.paint) batch.paint = constantPaint([1, 0, 0, .5]);
    if (!batch.cached) {
      batch.offset = offset;
      const data = Buffer.alloc(batch.num_verts * batch.stride, i % 255);
      parts.push(data); offset += data.length;
      if (batch.indexed) {
        batch.index_offset = offset;
        const indices = new Uint32Array(Array.from({ length: batch.index_count }, (_, j) => j));
        parts.push(Buffer.from(indices.buffer)); offset += indices.byteLength;
      }
    }
    return batch;
  });
  const header = { renderer: "triangles", resolution: [320, 180], samples: 1, supersample: 1,
    background: [0.2, 0.4, 0.6, 0.5], camera: CAMERA, batches, ...overrides };
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
    destroy() { events.push(["device_destroy"]); },
    createShaderModule: descriptor => descriptor,
    createRenderPipeline(descriptor) {
      const pipeline = { descriptor, id: ++sequence,
        getBindGroupLayout(index) { return { pipeline: this, index }; } };
      return pipeline;
    },
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
            // when two shader entry points declare the same uniform struct.
            assert.equal(pass.bindings.get(0).layout.pipeline, pass.pipeline);
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
    GPUBufferUsage: { VERTEX: 1, INDEX: 2, UNIFORM: 4, STORAGE: 8 },
    GPUTextureUsage: { RENDER_ATTACHMENT: 1, TEXTURE_BINDING: 2, COPY_DST: 4 },
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

const cases = {
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

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
const STRIDE = { surface: 40, stroke: 68, dot: 32, image: 24, texsurface: 36 };

function payload(specs, overrides = {}) {
  let offset = 0;
  const parts = [];
  const batches = specs.map((spec, i) => {
    const base = (spec.pipeline || "surface").replace(/_depth$/, "");
    const batch = { kind: "generated", pipeline: "surface", hash: `shape-${i}`,
      num_verts: 3, stride: STRIDE[base], count: 3, instances: 1,
      indexed: false, index_count: 0, uniforms: {}, ...spec };
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
  const header = { renderer: "triangles", resolution: [320, 180], samples: 1,
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
              vertices: [...pass.vertices], index: indexed ? pass.index : null, indexed, args });
          }
        },
        finish() { assert.ok(passes.every(p => p.ended)); return passes; },
      };
    },
    queue: {
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
  const canvas = { getContext: () => ({ configure() {},
    getCurrentTexture: () => makeTexture({ format: "canvas", size: [canvas.width, canvas.height] }),
  }) };
  const context = {
    navigator: { gpu: { requestAdapter: async () => ({ requestDevice: async () => device }),
      getPreferredCanvasFormat: () => "bgra8unorm" } },
    GPUBufferUsage: { VERTEX: 1, INDEX: 2, UNIFORM: 4 },
    GPUTextureUsage: { RENDER_ATTACHMENT: 1, TEXTURE_BINDING: 2, COPY_DST: 4 },
    fetch: async name => ({ ok: true, text: async () => fs.readFileSync(path.join(STATIC, name), "utf8") }),
    createImageBitmap: options.decode || (async () => ({ width: 2, height: 2, close() {} })),
    Blob, TextDecoder, ArrayBuffer, Uint8Array, Uint32Array, Float32Array, DataView,
  };
  vm.runInNewContext(fs.readFileSync(path.join(STATIC, "webgpu.js"), "utf8")
    + "\nglobalThis.renderer = ManimlWGPU;", context);
  await context.renderer.init(canvas);
  context.renderer.onCacheMiss = () => { cacheMisses++; };
  return { buffers, textures, submissions, events, cacheMisses: () => cacheMisses,
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
    const missing = await d.render([{ pipeline: "image", textures: { Texture: "unknown" } }]);
    assert.equal(missing[0].draws.length, 0);
    assert.equal(d.cacheMisses(), 1);
  },
  async modes() {
    const d = await driver();
    const spec = { kind: "surface", pipeline: "surface", hash: "same-hash" };
    const legacy = await d.render([spec], { renderer: "legacy", samples: 0 });
    const old = legacy[1].draws[0];
    assert.equal(uniform(old)[42], 0);
    const generated = (await d.render([{ ...spec, kind: "generated" }]))[0].draws[0];
    assert.notEqual(generated.vertices[0], old.vertices[0]);
    await d.render([{ ...spec, cached: true }], { renderer: "legacy", samples: 0 });
    assert.ok(generated.vertices[0].destroyed);
    assert.equal(old.vertices[0].destroyed, false);
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

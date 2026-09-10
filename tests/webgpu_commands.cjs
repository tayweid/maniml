// Execute the preserved winding browser driver with a recording WebGPU device. This
// validates commands and resource lifetimes; it does not simulate pixels.
"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const STATIC = path.join(__dirname, "..", "maniml", "web", "static");
const source = fs.readFileSync(path.join(__dirname, "winding_reference_webgpu.js"), "utf8");

function shaderName(code) {
  if (code.includes("struct FillIn")) return "fill";
  if (code.includes("struct StrokeIn")) return "stroke";
  if (code.includes("var fill_texture")) return "composite";
  return "other";
}

async function driver() {
  const textures = [], submissions = [], events = [];
  let serial = 0;
  const makeTexture = descriptor => {
    const texture = {
      id: ++serial, descriptor, destroyed: false,
      createView() { return { texture: this }; },
      destroy() {
        assert.equal(this.destroyed, false, "texture destroyed twice");
        this.destroyed = true;
        events.push({ type: "destroy", texture: this });
      },
    };
    textures.push(texture);
    return texture;
  };
  const device = {
    createShaderModule: descriptor => descriptor,
    createRenderPipeline: descriptor => ({
      descriptor, name: shaderName(descriptor.vertex.module.code),
      getBindGroupLayout: index => ({ index }),
    }),
    createSampler: descriptor => ({ descriptor }),
    createBindGroup: descriptor => descriptor,
    createTexture: makeTexture,
    createBuffer(descriptor) {
      return {
        bytes: new ArrayBuffer(descriptor.size), destroyed: false,
        getMappedRange() { return this.bytes; },
        unmap() {},
        destroy() { this.destroyed = true; },
      };
    },
    createCommandEncoder() {
      const passes = [];
      return {
        beginRenderPass(descriptor) {
          const pass = { descriptor, draws: [], viewport: null, scissor: null,
                         bindings: new Map(), buffers: [], ended: false };
          passes.push(pass);
          return {
            setPipeline(pipeline) { pass.pipeline = pipeline; },
            setBindGroup(index, binding) { pass.bindings.set(index, binding); },
            setVertexBuffer(index, buffer) { pass.buffers[index] = buffer; },
            setIndexBuffer(buffer) { pass.indexBuffer = buffer; },
            setViewport(...values) {
              const [x, y, w, h] = values;
              const [tw, th] = descriptor.colorAttachments[0].view.texture.descriptor.size;
              assert.ok(x >= 0 && y >= 0 && w >= 0 && h >= 0);
              assert.ok(x + w <= tw && y + h <= th, "viewport exceeds target");
              pass.viewport = values;
            },
            setScissorRect(...values) {
              const [x, y, w, h] = values;
              const [tw, th] = descriptor.colorAttachments[0].view.texture.descriptor.size;
              assert.ok(values.every(Number.isSafeInteger));
              assert.ok(x >= 0 && y >= 0 && w >= 0 && h >= 0);
              assert.ok(x + w <= tw && y + h <= th, "scissor exceeds target");
              pass.scissor = values;
            },
            draw(...args) {
              pass.draws.push({ pipeline: pass.pipeline,
                bindings: new Map(pass.bindings), buffers: [...pass.buffers],
                viewport: pass.viewport, scissor: pass.scissor, args });
            },
            drawIndexed(...args) { this.draw(...args); },
            end() { pass.ended = true; },
          };
        },
        finish() {
          assert.ok(passes.every(pass => pass.ended), "unfinished render pass");
          return { passes };
        },
      };
    },
    queue: {
      submit(commands) {
        for (const { passes } of commands) {
          for (const pass of passes) {
            for (const attachment of pass.descriptor.colorAttachments) {
              assert.equal(attachment.view.texture.destroyed, false,
                "attachment destroyed before submission");
            }
            for (const draw of pass.draws) {
              for (const binding of draw.bindings.values()) {
                for (const { resource } of binding.entries) {
                  if (resource.texture) assert.equal(resource.texture.destroyed, false,
                    "sampled texture destroyed before submission");
                  if (resource.buffer) assert.equal(resource.buffer.destroyed, false,
                    "uniform destroyed before submission");
                }
              }
              for (const buffer of draw.buffers) {
                assert.equal(buffer.destroyed, false, "vertex buffer destroyed before submission");
              }
            }
          }
          submissions.push(passes);
          events.push({ type: "submit", number: submissions.length });
        }
      },
    },
  };
  const canvas = {
    getContext() {
      return {
        configure() {},
        getCurrentTexture: () => makeTexture({
          size: [canvas.width, canvas.height], format: "canvas",
        }),
      };
    },
  };
  const context = {
    navigator: { gpu: {
      requestAdapter: async () => ({ requestDevice: async () => device }),
      getPreferredCanvasFormat: () => "bgra8unorm",
    } },
    GPUBufferUsage: { VERTEX: 1, UNIFORM: 2, INDEX: 4 },
    GPUTextureUsage: { RENDER_ATTACHMENT: 1, TEXTURE_BINDING: 2, COPY_DST: 4 },
    fetch: async name => ({ ok: true,
      text: async () => fs.readFileSync(path.join(__dirname, name.replace("wgsl/", "winding_wgsl/")), "utf8") }),
    TextDecoder, ArrayBuffer, Uint8Array, Float32Array, DataView, console,
  };
  vm.runInNewContext(source + "\nglobalThis.renderer = ManimlWGPU;", context);
  await context.renderer.init(canvas);
  return {
    textures, submissions, events,
    scratch: () => textures.filter(t => t.descriptor.format === "rgba16float"),
    async render(batches, resolution = [320, 180]) {
      await context.renderer.render(payload(batches, resolution));
      return submissions.at(-1);
    },
  };
}

function payload(batches, resolution) {
  const header = {
    resolution, samples: 0, background: [0, 0, 0, 1],
    camera: {
      view: [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1],
      frame_rescale_factors: [1, 1, 1],
      camera_position: [0, 0, 10], light_position: [0, 0, 10],
    },
    batches: batches.map((batch, index) => ({
      kind: "vmobject", hash: `batch-${index}`, offset: 0,
      num_verts: 3, stride: 68, uniforms: {}, ...batch,
    })),
  };
  const json = Buffer.from(JSON.stringify(header));
  const buffer = new ArrayBuffer(5 + json.length + 204);
  new Uint8Array(buffer)[0] = 3;
  new DataView(buffer).setUint32(1, json.length, true);
  new Uint8Array(buffer, 5, json.length).set(json);
  return buffer;
}

const draws = (passes, name) => passes.flatMap(p => p.draws)
  .filter(d => d.pipeline.name === name);
const scratchPasses = passes => passes.filter(p =>
  p.descriptor.colorAttachments[0].view.texture.descriptor.format === "rgba16float");
const uniform = (draw, binding = 0) => new Float32Array(
  draw.bindings.get(0).entries.find(e => e.binding === binding).resource.buffer.bytes);
const near = (actual, expected) => {
  assert.equal(actual.length, expected.length);
  expected.forEach((value, i) => assert.ok(Math.abs(actual[i] - value) < 1e-6,
    `component ${i}: ${actual[i]} != ${value}`));
};

const cases = {
  async uniforms() {
    const d = await driver();
    const passes = await d.render([{ fill_rect: [11, 13, 21, 10] }]);
    const fill = draws(passes, "fill")[0];
    const strokes = draws(passes, "stroke");
    const composite = draws(passes, "composite")[0];
    assert.deepEqual(Array.from(d.scratch()[0].descriptor.size), [64, 32]);
    assert.deepEqual(fill.viewport, [0, 0, 42, 20, 0, 1]);
    assert.deepEqual(composite.viewport, [11, 13, 21, 10, 0, 1]);
    assert.deepEqual(composite.scissor, [11, 13, 21, 10]);
    for (const draw of [fill, ...strokes]) assert.equal(uniform(draw).byteLength, 192);
    const transform = [320 / 21, 18, (320 - 22 - 21) / 21, (26 + 10 - 180) / 10];
    near(uniform(fill).slice(44), transform);
    near(uniform(strokes[0]).slice(44), transform);
    assert.equal(uniform(strokes[0])[41], 1, "border mode must survive packing");
    near(uniform(strokes[1]).slice(44), [1, 1, 0, 0]);
    assert.equal(strokes[1].viewport, null, "ordinary stroke uses the full output viewport");
    assert.equal(uniform(composite, 2).byteLength, 16);
    near(uniform(composite, 2), [42 / 64, 20 / 32, 0, 0]);
  },

  async bounds() {
    const d = await driver();
    const invalid = [undefined, null, [], [1, 2, 3], [-1, 0, 2, 2],
      [1.5, 0, 2, 2], [true, 0, 2, 2], [319, 0, 2, 1], [0, 0, -1, 1]];
    const empty = [[0, 0, 0, 0], [10, 20, 0, 5], [10, 20, 5, 0]];
    const passes = await d.render([...invalid, ...empty].map(fill_rect => ({ fill_rect })));
    assert.equal(draws(passes, "fill").length, invalid.length);
    assert.equal(draws(passes, "composite").length, invalid.length);
    assert.equal(draws(passes, "stroke").length, 2 * invalid.length + empty.length);
    assert.equal(d.scratch().length, 1, "full fallback shares one target");
    assert.deepEqual(Array.from(d.scratch()[0].descriptor.size), [640, 360]);
    for (const draw of draws(passes, "composite")) {
      assert.deepEqual(draw.viewport, [0, 0, 320, 180, 0, 1]);
      near(uniform(draw, 2), [1, 1, 0, 0]);
    }
  },

  async pool() {
    const d = await driver();
    await d.render([{ fill_rect: [0, 0, 17, 9] }, { fill_rect: [30, 20, 20, 10] },
      { fill_rect: [100, 40, 40, 20] }]);
    assert.equal(d.scratch().length, 2, "same bucket must be reused within a frame");
    const [small, large] = d.scratch();
    assert.equal(small.destroyed, false);
    assert.equal(large.destroyed, false);
    await d.render([{ fill_rect: [50, 20, 21, 10] }]);
    assert.equal(d.scratch().length, 2, "live bucket must persist across frames");
    assert.equal(small.destroyed, false);
    assert.equal(large.destroyed, true);
    const submitted = d.events.findIndex(e => e.type === "submit" && e.number === 2);
    const retired = d.events.findIndex(e => e.type === "destroy" && e.texture === large);
    assert.ok(retired > submitted, "unused target must retire after submission");
    await d.render([{ fill_rect: [0, 0, 0, 0] }]);
    assert.equal(small.destroyed, true);
    const third = d.events.findIndex(e => e.type === "submit" && e.number === 3);
    assert.ok(d.events.findIndex(e => e.type === "destroy" && e.texture === small) > third);
  },

  async shrink() {
    const d = await driver();
    const large = scratchPasses(await d.render([{ fill_rect: [30, 20, 31, 15] }]))[0];
    const small = scratchPasses(await d.render([{ fill_rect: [100, 80, 17, 9] }]))[0];
    const a = large.descriptor.colorAttachments[0], b = small.descriptor.colorAttachments[0];
    assert.equal(a.view.texture, b.view.texture, "shrinking bounds reuse the bucket");
    for (const attachment of [a, b]) {
      assert.equal(attachment.loadOp, "clear", "stale pixels must be cleared before reuse");
      assert.deepEqual({ ...attachment.clearValue }, { r: 0, g: 0, b: 0, a: 0 });
      assert.equal(attachment.storeOp, "store");
    }
    assert.deepEqual(small.draws[0].viewport, [0, 0, 34, 18, 0, 1]);
    assert.deepEqual(draws(d.submissions.at(-1), "composite")[0].viewport,
      [100, 80, 17, 9, 0, 1]);
  },

  async resize() {
    const d = await driver();
    await d.render([{ fill_rect: [0, 0, 17, 9] }]);
    const old = d.scratch()[0];
    const passes = await d.render([{}], [17, 9]);
    assert.equal(old.destroyed, true, "resize releases old scratch allocations");
    assert.deepEqual(Array.from(d.scratch().at(-1).descriptor.size), [34, 18]);
    assert.deepEqual(draws(passes, "fill")[0].viewport, [0, 0, 34, 18, 0, 1]);
    near(uniform(draws(passes, "composite")[0], 2), [1, 1, 0, 0]);
  },
};

const selected = process.argv[2];
if (!Object.hasOwn(cases, selected)) throw new Error(`unknown case: ${selected}`);
cases[selected]().then(() => console.log(`PASS ${selected}`)).catch(error => {
  console.error(error);
  process.exitCode = 1;
});

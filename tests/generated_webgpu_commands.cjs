// Record the shipped generated-geometry browser path without a GPU. Resource
// validation runs at submission, so early destruction is an actual test error.
"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const {STATIC, CAMERA, STRIDE, constantPaint, payload, driver} = require("./webgpu_fake_device.cjs");

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

// A format 7 message from batches and definition tables ({table: {hash:
// bytes}}): the batches' vertex and index bytes (uncached ones) first, then
// the tables, as the Python encoder lays them out. A batch's vertex bytes
// are its fill_value (3 unless given), which does not travel.
function formatSeven(batches, tables = {}, header = {}) {
  let offset = 0;
  const parts = [];
  batches = batches.map(spec => {
    const batch = {kind: "generated", stride: 40, uniforms: {}, instances: 1, indexed: false, index_count: 0, ...spec};
    if (!batch.cached) {
      batch.offset = offset;
      const data = Buffer.alloc((batch.fill_num_verts ?? batch.num_verts) * batch.stride, batch.fill_value ?? 3);
      parts.push(data); offset += data.length;
      if (batch.indexed) {
        batch.index_offset = offset;
        const indices = Buffer.from(new Uint32Array(batch.index_values).buffer);
        parts.push(indices); offset += indices.length;
      }
    }
    delete batch.index_values;
    delete batch.fill_value;
    return batch;
  });
  const data = {};
  for (const [table, entries] of Object.entries(tables)) {
    data[table] = {};
    for (const [hash, bytes] of Object.entries(entries)) {
      data[table][hash] = {offset, nbytes: bytes.length};
      parts.push(bytes); offset += bytes.length;
    }
  }
  const json = Buffer.from(JSON.stringify({renderer: "triangles", format_version: 7, resolution: [320, 180], samples: 4,
    supersample: 2, background: [0, 0, 0, 1], camera: CAMERA, batches, ...data, ...header}));
  const out = Buffer.alloc(5 + json.length + offset);
  out[0] = 3; out.writeUInt32LE(json.length, 1); json.copy(out, 5);
  let position = 5 + json.length;
  for (const part of parts) { part.copy(out, position); position += part.length; }
  return out.buffer.slice(out.byteOffset, out.byteOffset + out.byteLength);
}

// A format 8 message (docs/phase_b4_plan.md, B4.8) from a format 7 one:
// its header rewritten by `rewrite`, its payload as it was. A full frame is
// the format 7 header with its epoch and frame; a delta carries the
// batches formatSeven laid out in its splices, whose offsets stay good.
function restream(message, rewrite) {
  const bytes = Buffer.from(message), length = bytes.readUInt32LE(1);
  const json = Buffer.from(JSON.stringify(rewrite(JSON.parse(bytes.subarray(5, 5 + length).toString()))));
  const out = Buffer.concat([Buffer.from([3, 0, 0, 0, 0]), json, bytes.subarray(5 + length)]);
  out.writeUInt32LE(json.length, 1);
  return out.buffer.slice(out.byteOffset, out.byteOffset + out.byteLength);
}
const fullEight = (message, epoch) => restream(message, ({format_version, ...header}) =>
  ({format_version: 8, epoch, frame: 0, ...header}));
// A delta of `epoch` numbered `frame` against `base`: splices [at, removed,
// count] take their batches from the message's, in order; other fields as given.
function deltaEight(message, epoch, frame, base, splices, fields = {}) {
  return restream(message, header => {
    const batches = header.batches;
    let read = 0;
    const carried = splices.map(([at, removed, count]) => [at, removed, batches.slice(read, read += count)]);
    const tables = Object.fromEntries(Object.entries(header).filter(([key]) => key.endsWith("_data")));
    return {format_version: 8, epoch, frame, base, renderer: header.renderer, splices: carried, scalars: [],
            ...tables, ...fields};
  });
}

const H = character => character.repeat(32);
const floats = (count, value) => {
  const bytes = Buffer.alloc(count * 4);
  for (let i = 0; i < count; i++) bytes.writeFloatLE(value + i / 1024, 4 * i);
  return bytes;
};
// Border curve records (active, finite, no density cap) and one patch
// object record per run of curves: [x, y, z, curve offset, curves,
// bordered, sign, 0].
function curveRecords(count) {
  const bytes = Buffer.alloc(176 * count);
  for (let curve = 0; curve < count; curve++) bytes.writeFloatLE(1, (44 * curve + 37) * 4);
  return bytes;
}
function objectTable(runs) {
  const bytes = Buffer.alloc(32 * runs.length);
  let offset = 0;
  runs.forEach(([curves, bordered], index) => {
    [offset, curves, bordered].forEach((value, i) => bytes.writeFloatLE(value, 32 * index + 12 + 4 * i));
    offset += curves;
  });
  return bytes;
}
const CAPACITY = 8, STRIP = 6 * (CAPACITY / 2 - 1);
// A patch run of one bordered object, its curves from border_data or, under
// a program, from the program's records.
const patchRun = (hash, curves, objects, border = H("b"), extra = {}) => ({pipeline: "patch", hash, fill_num_verts: 0,
  num_verts: CAPACITY * curves, count: curves * (6 + STRIP),
  border: {hash: border, num_curves: curves, capacity: CAPACITY, layout: [[curves, 1, 0]]},
  objects: {hash: objects, count: 1}, ...extra});
const netBatch = (hash, net, extra = {}) => ({pipeline: "surface", hash, num_verts: 9, count: 24, fill_num_verts: 0,
  net: {hash: net, nu: 3, nv: 3, channels: 10, capacity: 2, density: 0}, ...extra});
const blend = (sources, alpha, rows, channels) => ({kind: "blend", sources, scalars: [alpha], rows, channels});
// Cached copies of batches, as the encoder sends them once the client holds
// their bytes: no offsets and no run layout.
const cached = batches => batches.map(batch => {
  const out = {...batch, cached: true};
  if (out.border) { out.border = {...out.border}; delete out.border.layout; }
  delete out.index_values;
  return out;
});
const scenePasses = passes => passes.filter(pass => pass.descriptor && pass.descriptor.depthStencilAttachment);
const sceneDraws = passes => scenePasses(passes).flatMap(pass => pass.draws);
const kernel = pass => ["BorderParams", "NetParams", "BlendParams", "FinalizeParams"]
  .find(name => pass.draws.some(draw => draw.pipeline.descriptor.compute.module.code.includes("struct " + name)));
const computePasses = (passes, name) => passes.filter(pass => pass.compute && kernel(pass) === name);
const countsDelta = (before, after) => Object.fromEntries(Object.keys(after).map(key => [key, after[key] - before[key]]));

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
    // An unrelated object inserted earlier in the frame leaves the run's
    // slot, its output and its index pattern where they are.
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
  // One frame with every row program (docs/phase_b3_plan.md, B3b): a
  // rotation, a fade and a partial path, each finalized and drawn.
  async programKindsWire() {
    const d = await driver();
    const file = fs.readFileSync(process.argv[3]);
    const passes = await d.renderBytes(file.buffer.slice(file.byteOffset, file.byteOffset + file.byteLength));
    const compute = passes.filter(pass => pass.compute);
    const code = pass => pass.pipeline.descriptor.compute.module.code;
    const programs = compute.filter(pass => code(pass).includes("FinalizeParams"));
    assert.equal(programs.length, 3, "three programs, each ending in the finalize kernel");
    const kinds = programs.map(pass => {
      const first = pass.draws[0].pipeline.descriptor.compute.module.code;
      return first.includes("AffineParams") ? "affine" : first.includes("PaintParams") ? "paint" : first.includes("PartialParams") ? "partial" : "?";
    });
    assert.deepEqual(kinds.sort(), ["affine", "paint", "partial"]);
    for (const pass of programs) {
      assert.equal(pass.draws.length, 2, "the row kernel, then finalize");
      const rows = pass.draws[0].bindings.get(1).entries[1].resource.buffer;
      assert.equal(pass.draws[1].bindings.get(1).entries[0].resource.buffer, rows, "finalize reads the kernel's rows");
    }
    const affine = programs[kinds.indexOf("affine")] ?? programs.find(pass => pass.draws[0].pipeline.descriptor.compute.module.code.includes("AffineParams"));
    const matrix = new Float32Array(affine.draws[0].bindings.get(0).entries[0].resource.buffer.bytes, 16, 16);
    assert.ok(Math.abs(matrix[15] - 1) < 1e-6 && Math.abs(matrix[0] * matrix[0] + matrix[1] * matrix[1] - 1) < 1e-5, "a rotation with a unit first column");
    const scene = passes.find(pass => pass.descriptor && pass.descriptor.depthStencilAttachment);
    const strokes = scene.draws.filter(draw => draw.pipeline.descriptor.vertex.buffers.length && draw.pipeline.descriptor.vertex.buffers[0].arrayStride === 204);
    const finalized = new Set(programs.map(pass => pass.draws[1].bindings.get(1).entries[2].resource.buffer));
    assert.ok(strokes.length >= 3 && strokes.every(draw => finalized.has(draw.vertices[0])), "every stroke draws finalized instances");
    await d.destroy();
    assert.ok(d.buffers.every(buffer => buffer.destroyed));
  },
  // A real Phase B export (tests.test_export) through the recording indexer
  // and this driver: every reconstructed frame, forward, back and out of
  // order, draws with nothing missing, because the indexer put each frame's
  // object tables, nets and program sources back into its own payload.
  async recordingReplay() {
    const zlib = require("node:zlib"), dir = process.argv[3];
    vm.runInThisContext(fs.readFileSync(path.join(STATIC, "geometry_recording.js"), "utf8"));
    const meta = JSON.parse(fs.readFileSync(path.join(dir, "scene.json"), "utf8"));
    const data = zlib.gunzipSync(fs.readFileSync(path.join(dir, "scene.bin.gz")));
    const frames = [];
    let offset = 0;
    for (const frame of meta.frames) {
      frames.push(new Uint8Array(data.buffer, data.byteOffset + offset, frame.len));
      offset += frame.len;
    }
    const recording = globalThis.ManimlRecording.index(frames);
    const d = await driver();
    const indices = [...frames.keys()];
    const order = [...indices, ...indices.slice().reverse(), ...indices.filter(i => i % 3 === 1), 0, indices.at(-1)];
    const stages = new Set();
    for (const i of order) {
      const passes = await d.renderBytes(recording.frame(i));
      assert.equal(d.cacheMisses(), 0, `frame ${i} drew from what its own message carried`);
      const scene = passes.find(pass => pass.descriptor && pass.descriptor.depthStencilAttachment);
      for (const draw of scene.draws) stages.add(draw.pipeline.descriptor.vertex.entryPoint);
    }
    // Patch fans, patch covers and the strips, strokes and nets all drew.
    assert.deepEqual([...stages].sort(), ["vs_cover", "vs_fan", "vs_main", "vs_patch"]);
    await d.destroy();
    assert.ok(d.buffers.every(buffer => buffer.destroyed));
    process.stdout.write(JSON.stringify({frames: frames.length, rendered: order.length}));
  },
  // The retained frame (docs/phase_b4_plan.md, B4.7): a full frame the
  // driver already holds creates nothing. The frame mixes plain, stroke and
  // paint batches and a format 6 border run with a patch run, a net and a
  // program drawn three ways (a patch run's records, a stroke's instances, a
  // net's rows). The same message again, the same frame with every batch
  // cached, and then a camera move draw the same draws from the same
  // resources; the move rewrites the uniform sets in place.
  async slotsReuseAcrossFullFrames() {
    const d = await driver();
    const run = borderRunFixture(3, 40, H("c"));
    const program = blend([H("1"), H("2")], .25, 9, 17), netProgram = blend([H("5"), H("6")], .25, 9, 10);
    const batches = [
      {pipeline: "surface", hash: "plain", num_verts: 3, count: 3},
      {pipeline: "surface", hash: "plain-2", num_verts: 3, count: 3},
      {pipeline: "stroke", hash: "stroke", stride: 68, num_verts: 6, count: 4, instances: 2},
      {pipeline: "paint", hash: "painted", num_verts: 3, count: 3, paint_hash: H("a")},
      run.spec,
      patchRun("patch", 4, H("d")),
      netBatch("net", H("e")),
      patchRun("patch-program", 4, H("f"), H("9"), {program}),
      {pipeline: "stroke", hash: "stroke-program", stride: 68, num_verts: 6, count: 4, instances: 4, fill_num_verts: 0, program},
      netBatch("net-program", H("8"), {program: netProgram}),
    ];
    const tables = {paint_data: {[H("a")]: Buffer.from(new Float32Array(constantPaint([1, 0, 0, .5])).buffer)},
      border_data: {[H("c")]: curveRecords(3), [H("b")]: curveRecords(4)},
      object_data: {[H("d")]: objectTable([[4, 1]]), [H("f")]: objectTable([[4, 1]])},
      net_data: {[H("e")]: floats(90, 1)},
      program_data: {[H("1")]: floats(153, 1), [H("2")]: floats(153, 2), [H("5")]: floats(90, 1), [H("6")]: floats(90, 2)}};
    const counted = async message => {
      const before = d.counts(), passes = await d.renderBytes(message);
      return {passes, delta: countsDelta(before, d.counts())};
    };
    const first = await counted(formatSeven(batches, tables));
    const drawn = sceneDraws(first.passes);
    assert.equal(d.cacheMisses(), 0);
    assert.equal(drawn.length, 18, "one draw per plain batch, five per patch run of one bordered object");
    assert.ok(first.delta.compute_dispatches >= 7 && first.delta.buffers_created > 0);
    assert.equal(computePasses(first.passes, "BlendParams").length, 2, "the patch run and the stroke share one evaluation");
    assert.equal(first.delta.set_pipeline_calls, first.delta.pipeline_switches,
      "a pipeline is set once per run of draws that share it (the two plain surfaces)");
    const sameDraws = (label, passes) => {
      const draws = sceneDraws(passes);
      assert.equal(draws.length, drawn.length, label);
      draws.forEach((draw, i) => {
        const was = drawn[i];
        assert.equal(draw.pipeline, was.pipeline, `${label}: draw ${i} pipeline`);
        assert.deepEqual(draw.args, was.args);
        assert.equal(draw.stencil, was.stencil);
        assert.deepEqual(draw.vertices, was.vertices, `${label}: draw ${i} vertices`);
        assert.equal(draw.index && draw.index.buffer, was.index && was.index.buffer);
        for (const [index, group] of was.bindings) assert.equal(draw.bindings.get(index), group, `${label}: draw ${i} group ${index}`);
      });
    };
    const nothingMade = ["buffers_created", "buffers_destroyed", "bind_groups_created", "uniform_buffers_created",
                         "write_buffer_calls", "compute_dispatches", "buffer_copies", "compute_passes"];
    for (const [label, message] of [["the same message", formatSeven(batches, tables)],
                                    ["the frame cached", formatSeven(cached(batches))]]) {
      const frame = await counted(message);
      for (const key of nothingMade) assert.equal(frame.delta[key], 0, `${label}: ${key}`);
      assert.equal(frame.delta.draws, first.delta.draws, label);
      sameDraws(label, frame.passes);
    }
    // A camera move: every border and net output is evaluated again at the
    // new scale, the program is not, and nothing is made.
    const moved = await counted(formatSeven(cached(batches), {}, {camera: {...CAMERA, frame_scale: .9}}));
    for (const key of ["buffers_created", "buffers_destroyed", "bind_groups_created", "uniform_buffers_created"]) {
      assert.equal(moved.delta[key], 0, `camera move: ${key}`);
    }
    assert.ok(moved.delta.write_buffer_calls > 0 && moved.delta.write_buffer_calls === moved.delta.uniform_writes,
      "the uniform sets and the nets' parameters are rewritten in place");
    assert.equal(computePasses(moved.passes, "BorderParams").length, 3);
    assert.equal(computePasses(moved.passes, "NetParams").length, 2);
    assert.equal(computePasses(moved.passes, "BlendParams").length, 0);
    sameDraws("camera move", moved.passes);
    for (const draw of sceneDraws(moved.passes)) {
      const buffer = draw.bindings.get(0).entries[0].resource.buffer;
      near([new Float32Array(buffer.bytes)[23]], [.9]);
    }
    assert.equal(d.cacheMisses(), 0);
    await d.render([], {format_version: 7});
    assert.equal(d.buffers.filter(buffer => !buffer.destroyed).length, 0, "an empty frame retires every slot");
    await d.destroy();
  },
  // A batch inserted before a bordered one, or before a net, moves nothing:
  // the later slot keeps its output, evaluated and filled, and the
  // inserted batches get their own. Among the inserted is the same geometry
  // under other overrides, which a (geometry, occurrence) key would have
  // handed the later batch's output.
  async outputsSurviveInsertion() {
    const d = await driver();
    const run = borderRunFixture(3, 40, H("c"));
    const tables = {border_data: {[H("c")]: curveRecords(3)}, net_data: {[H("e")]: floats(90, 1)}};
    const bordered = run.spec, net = netBatch("net", H("e"));
    const moved = {uniforms: {frame_scale: 2}};
    const first = await d.renderBytes(formatSeven([bordered, net], tables));
    const [runOutput, netOutput] = sceneDraws(first).map(draw => draw.vertices[0]);
    assert.equal(computePasses(first, "BorderParams")[0].draws[0].bindings.get(1).entries[1].resource.buffer, runOutput);
    const before = d.counts();
    const second = await d.renderBytes(formatSeven([{pipeline: "surface", hash: "inserted", num_verts: 3, count: 3},
      {...cached([bordered])[0], ...moved}, cached([bordered])[0], {...cached([net])[0], ...moved}, cached([net])[0]]));
    const draws = sceneDraws(second);
    assert.equal(draws.length, 5);
    assert.equal(draws[2].vertices[0], runOutput, "the run keeps its output");
    assert.equal(draws[4].vertices[0], netOutput, "the net keeps its output");
    assert.ok(draws[1].vertices[0] !== runOutput && draws[3].vertices[0] !== netOutput);
    const written = second.flatMap(pass => pass.copy ? [pass.copy[2]]
      : pass.compute ? pass.draws.map(draw => draw.bindings.get(1).entries[1].resource.buffer) : []);
    assert.ok(!written.includes(runOutput) && !written.includes(netOutput), "nothing is evaluated into a kept output");
    assert.equal(computePasses(second, "BorderParams").length, 1, "only the inserted run is evaluated");
    assert.equal(computePasses(second, "NetParams").length, 1, "only the inserted net is evaluated");
    assert.equal(countsDelta(before, d.counts()).buffers_destroyed, 0);
    const [insertedRun, insertedNet] = [draws[1].vertices[0], draws[3].vertices[0]];
    const third = await d.renderBytes(formatSeven(cached([bordered, net])));
    assert.deepEqual(sceneDraws(third).map(draw => draw.vertices[0]), [runOutput, netOutput]);
    assert.equal(third.filter(pass => pass.compute || pass.copy).length, 0);
    assert.ok(insertedRun.destroyed && insertedNet.destroyed && !runOutput.destroyed && !netOutput.destroyed);
    await d.destroy();
    assert.ok(d.buffers.every(buffer => buffer.destroyed));
  },
  // Two objects under one program (the same sources) whose scalars differ,
  // coincide for a frame, then differ again: a patch run pair and a net
  // pair. When they coincide one evaluation serves both; when they part,
  // each draws its own output again, which it kept. A (program, occurrence)
  // key retired the second output while the second object's border and net
  // bindings still named it, so the third frame read a destroyed buffer.
  async programOutputsSurviveCoincidence() {
    const d = await driver();
    const patchProgram = alpha => blend([H("1"), H("2")], alpha, 9, 17);
    const netProgram = alpha => blend([H("5"), H("6")], alpha, 9, 10);
    const frame = ([a, b], tables) => formatSeven(
      [patchRun("a", 4, H("c"), H("b"), {program: patchProgram(a)}), patchRun("b", 4, H("d"), H("b"), {program: patchProgram(b)}),
       netBatch("net-a", H("e"), {program: netProgram(a)}), netBatch("net-b", H("f"), {program: netProgram(b)})]
        .map(batch => tables ? batch : cached([batch])[0]), tables || {});
    const tables = {object_data: {[H("c")]: objectTable([[4, 1]]), [H("d")]: objectTable([[4, 1]])},
      program_data: {[H("1")]: floats(153, 1), [H("2")]: floats(153, 2), [H("5")]: floats(90, 1), [H("6")]: floats(90, 2)}};
    const reads = (passes, name) => computePasses(passes, name).map(pass => pass.draws[0].bindings.get(1).entries[0].resource.buffer);
    const first = await d.renderBytes(frame([.3, .6], tables));
    assert.equal(computePasses(first, "BlendParams").length, 4, "four states, four evaluations");
    const [recordsA, recordsB] = reads(first, "BorderParams"), [rowsA, rowsB] = reads(first, "NetParams");
    assert.ok(recordsA !== recordsB && rowsA !== rowsB);
    let before = d.counts();
    const second = await d.renderBytes(frame([.5, .5]));
    assert.equal(computePasses(second, "BlendParams").length, 2, "one evaluation per program serves both objects");
    assert.deepEqual(reads(second, "BorderParams"), [recordsA, recordsA]);
    assert.deepEqual(reads(second, "NetParams"), [rowsA, rowsA]);
    assert.ok(!recordsB.destroyed && !rowsB.destroyed, "the second object's outputs are kept while it borrows");
    const third = await d.renderBytes(frame([.3, .7]));
    assert.equal(computePasses(third, "BlendParams").length, 4);
    assert.deepEqual(reads(third, "BorderParams"), [recordsA, recordsB], "each object reads its own records again");
    assert.deepEqual(reads(third, "NetParams"), [rowsA, rowsB]);
    const fourth = await d.renderBytes(frame([.3, .7]));
    assert.equal(fourth.filter(pass => pass.compute).length, 0);
    const made = countsDelta(before, d.counts());
    assert.equal(made.buffers_created, 0, "evaluations write their parameters in place");
    assert.equal(made.buffers_destroyed, 0);
    assert.equal(d.cacheMisses(), 0);
    await d.destroy();
    assert.ok(d.buffers.every(buffer => buffer.destroyed));
  },
  // A frame that fails after it rewrote, for its own camera, the uniform
  // sets it shares with the retained slots leaves nothing of that camera
  // behind: the next frame at the camera last submitted, cached or resent
  // byte for byte, draws and generates with that camera's values, and a
  // camera the border stage rejects is not remembered either.
  async failedFramesKeepTheCamera() {
    const tables = {border_data: {[H("c")]: curveRecords(3)}};
    const plain = {pipeline: "surface", hash: "plain", num_verts: 3, count: 3};
    const run = borderRunFixture(3, 40, H("c")).spec;
    const halved = {...CAMERA, frame_scale: .5};
    const frameScale = buffer => new Float32Array(buffer.bytes)[23];
    const drawnScales = passes => sceneDraws(passes).map(draw => frameScale(uniformBuffer(draw)));
    const generatedScales = passes => computePasses(passes, "BorderParams")
      .map(pass => frameScale(pass.draws[0].bindings.get(0).entries[0].resource.buffer));
    const retained = d => d.buffers.filter(buffer => !buffer.destroyed);
    {
      // The sets repacked for the failed frame's camera before its border
      // stage refused another batch's overrides.
      const d = await driver();
      const first = formatSeven([plain, run], tables);
      await d.renderBytes(first);
      const bad = {...run, hash: "fill-2", uniforms: {joint_type: 7}};
      await assert.rejects(d.renderBytes(formatSeven([...cached([plain, run]), bad], {}, {camera: halved})),
        /border generation uniforms/);
      const back = await d.renderBytes(formatSeven(cached([plain, run])));
      assert.deepEqual(drawnScales(back), [1, 1], "the committed camera, not the failed frame's");
      assert.equal(computePasses(back, "BorderParams").length, 0, "the border evaluated at that camera still stands");
      assert.deepEqual(drawnScales(await d.renderBytes(first)), [1, 1], "and the first message again draws as it did");
      await d.render([], {format_version: 7});
      assert.equal(retained(d).length, 0);
      await d.destroy();
    }
    {
      // A camera the border stage rejects fails its frame and only its frame.
      const d = await driver();
      const first = formatSeven([plain, run], tables);
      await d.renderBytes(first);
      await assert.rejects(d.renderBytes(formatSeven(cached([plain, run]), {}, {camera: {...CAMERA, frame_scale: 0}})),
        /border generation uniforms/);
      for (let i = 0; i < 2; i++) assert.deepEqual(drawnScales(await d.renderBytes(first)), [1, 1]);
      await d.destroy();
    }
    {
      // The failed frame made the first border slot on a retained set, so
      // the set's generation view was packed at its camera, and then failed
      // in its batches: the next frame at the committed camera generates
      // with the committed camera.
      const d = await driver();
      await d.renderBytes(formatSeven([plain]));
      await assert.rejects(d.renderBytes(formatSeven([...cached([plain]), run,
        {pipeline: "invalid", hash: "invalid", num_verts: 3, count: 3}], tables, {camera: halved})), /unsupported generated pipeline/);
      const back = await d.renderBytes(formatSeven([...cached([plain]), run], tables));
      assert.deepEqual(generatedScales(back), [1]);
      assert.deepEqual(drawnScales(back), [1, 1]);
      const still = await d.renderBytes(formatSeven(cached([plain, run])));
      assert.equal(computePasses(still, "BorderParams").length, 0);
      await d.destroy();
      assert.ok(d.buffers.every(buffer => buffer.destroyed));
    }
  },
  // A border's generation reads the camera position unless its stroke is
  // flat, and a net's reads its density: moving either evaluates the output
  // again with the new value, and moving what an output does not read
  // evaluates nothing.
  async generationFollowsItsInputs() {
    const d = await driver();
    const tables = {border_data: {[H("c")]: curveRecords(3)}, net_data: {[H("e")]: floats(90, 1)}};
    const run = borderRunFixture(3, 40, H("c")).spec, flat = {...run, uniforms: {flat_stroke: 1}};
    const net = density => netBatch("net", H("e"), {net: {hash: H("e"), nu: 3, nv: 3, channels: 10, capacity: 2, density}});
    const frame = (camera, density) => formatSeven(cached([run, flat, net(density)]), {}, {camera});
    const first = await d.renderBytes(formatSeven([run, flat, net(0)], tables));
    const [output, flatOutput, netOutput] = sceneDraws(first).map(draw => draw.vertices[0]);
    assert.equal(computePasses(first, "BorderParams").length, 2);
    const written = (passes, name) => computePasses(passes, name).map(pass => pass.draws[0].bindings.get(1).entries[1].resource.buffer);
    const read = (passes, name, offset, count) => computePasses(passes, name)
      .map(pass => Array.from(new Float32Array(pass.draws[0].bindings.get(0).entries[offset].resource.buffer.bytes)).slice(...count));
    const moved = {...CAMERA, camera_position: [1, 0, 10]};
    const position = await d.renderBytes(frame(moved, 0));
    assert.deepEqual(written(position, "BorderParams"), [output], "the run whose stroke is not flat, alone");
    assert.deepEqual(read(position, "BorderParams", 0, [20, 23]), [[1, 0, 10]]);
    assert.equal(computePasses(position, "NetParams").length, 0, "a net does not read the camera position");
    const denser = await d.renderBytes(frame(moved, 1));
    assert.deepEqual(written(denser, "NetParams"), [netOutput]);
    assert.deepEqual(read(denser, "NetParams", 1, [8, 9]), [[1]], "the net's parameters carry the density");
    assert.equal(computePasses(denser, "BorderParams").length, 0);
    assert.equal((await d.renderBytes(frame(moved, 1))).filter(pass => pass.compute).length, 0);
    const back = await d.renderBytes(frame(moved, 0));
    assert.deepEqual(read(back, "NetParams", 1, [8, 9]), [[0]]);
    assert.ok(!flatOutput.destroyed);
    assert.equal(d.cacheMisses(), 0);
    await d.destroy();
    assert.ok(d.buffers.every(buffer => buffer.destroyed));
  },
  // The retained frame draws what a driver with nothing retained draws from
  // the same frame whole. Over full frames that resend a message byte for
  // byte, replace a bordered mover's geometry in place (its slot and output
  // taken over, its new fill copied in), move the camera (its scale, its
  // position, which a flat stroke's border does not read), change a net's
  // density and programs' scalars (differing, coinciding, parting), insert
  // a batch and the same geometry under other overrides, fail after
  // rewriting the uniform sets and return to the camera last submitted,
  // change the sample count and remove batches, every frame's render passes
  // trace by content as a fresh driver's do (tests/webgpu_trace.cjs: an
  // output as a token of what its kernel read, so a stale or borrowed one
  // shows), and a frame that fails fails alike. What a fresh driver would
  // get wrong too is the other cases' to catch.
  async retainedFramesDrawWhatFreshDriversDraw() {
    const {tracedDriver, renderPasses, drawnCold, firstDifference} = require("./webgpu_trace.cjs");
    const tables = {paint_data: {[H("a")]: Buffer.from(new Float32Array(constantPaint([1, 0, 0, .5])).buffer)},
      border_data: {[H("c")]: curveRecords(3), [H("b")]: curveRecords(4)},
      object_data: {[H("d")]: objectTable([[4, 1]]), [H("f")]: objectTable([[4, 1]])},
      net_data: {[H("e")]: floats(90, 1)}, texture_data: {texture: Buffer.alloc(4, 7)},
      program_data: {[H("1")]: floats(153, 1), [H("2")]: floats(153, 2), [H("5")]: floats(90, 1), [H("6")]: floats(90, 2)}};
    const run = borderRunFixture(3, 40, H("c")).spec;
    const patchProgram = (hash, alpha) => patchRun(hash, 4, H("f"), H("9"), {program: blend([H("1"), H("2")], alpha, 9, 17)});
    const netProgram = (hash, alpha) => netBatch(hash, H("8"), {program: blend([H("5"), H("6")], alpha, 9, 10)});
    const everything = ([a, b], density, step = 0) => [
      {pipeline: "surface", hash: "plain", num_verts: 3, count: 3},
      {...run, hash: `mover-${step}`, fill_value: 10 + step},
      {pipeline: "stroke", hash: "stroke", stride: 68, num_verts: 6, count: 4, instances: 2},
      {pipeline: "paint", hash: "painted", num_verts: 3, count: 3, paint_hash: H("a")},
      {pipeline: "image", hash: "image", stride: 24, num_verts: 3, count: 3, textures: {Texture: "texture"}},
      run, {...run, uniforms: {flat_stroke: 1}}, patchRun("patch", 4, H("d")),
      netBatch("net", H("e"), {net: {hash: H("e"), nu: 3, nv: 3, channels: 10, capacity: 2, density}}),
      patchProgram("patch-a", a), patchProgram("patch-b", b),
      {pipeline: "stroke", hash: "stroke-program", stride: 68, num_verts: 6, count: 4, instances: 4, fill_num_verts: 0,
       program: blend([H("1"), H("2")], a, 9, 17)},
      netProgram("net-a", a), netProgram("net-b", b)];
    const scaled = {...CAMERA, frame_scale: .9}, moved = {...scaled, camera_position: [1, 0, 10]};
    const inserted = [{pipeline: "surface", hash: "inserted", num_verts: 3, count: 3}, {...run, uniforms: {frame_scale: 2}},
                      ...everything([.3, .7], 1, 2)];
    // [batches, header, the batches sent whole (the rest cached), or true
    // for every batch with the definitions]
    const frames = [
      [everything([.25, .6], 0), {}, true],
      [everything([.25, .6], 0), {}, true],
      [everything([.25, .6], 0), {}, []],
      [everything([.25, .6], 0, 1), {}, ["mover-1"]],
      [everything([.25, .6], 0, 1), {camera: scaled}, []],
      [everything([.25, .6], 0, 2), {camera: moved}, ["mover-2"]],
      [everything([.25, .6], 1, 2), {camera: moved}, []],
      [everything([.5, .5], 1, 2), {camera: moved}, []],
      [everything([.3, .7], 1, 2), {camera: moved}, []],
      [inserted, {camera: moved}, ["inserted"]],
      [[...inserted, {...run, hash: "refused", uniforms: {joint_type: 7}}], {camera: {...CAMERA, frame_scale: .5}}, ["refused"]],
      [inserted, {camera: moved}, []],
      [inserted, {camera: moved, samples: 1, resolution: [640, 360]}, []],
      [inserted.filter((_, i) => i % 3 === 0), {camera: moved, samples: 1, resolution: [640, 360]}, []],
      [[], {}, []],
    ];
    const d = await tracedDriver();
    let failed = 0;
    for (const [index, [batches, header, whole]] of frames.entries()) {
      const message = whole === true ? formatSeven(batches, tables, header)
        : formatSeven(batches.map(batch => whole.includes(batch.hash) ? batch : cached([batch])[0]), {}, header);
      let warm;
      try {
        await d.renderer.render(message);
        warm = {drawn: renderPasses(d.trace())};
      } catch (error) {
        warm = {error: error.message};
        failed++;
      }
      const cold = await drawnCold(formatSeven(batches, tables, header));
      assert.equal(warm.error, cold.error, `frame ${index} fails alike`);
      if (!warm.error) {
        assert.equal(cold.misses, 0);
        const found = firstDifference(warm.drawn, cold.drawn);
        assert.equal(found, null, `frame ${index} draws what a fresh driver draws: ${found}`);
      }
    }
    assert.equal(failed, 1);
    assert.equal(d.cacheMisses(), 0);
    await d.destroy();
    assert.ok(d.buffers.every(buffer => buffer.destroyed));
  },
  // A recorded stream (tests.test_browser_frames' episode fixture) played in
  // order draws, frame by frame, what a fresh driver draws from the same
  // frame rebuilt whole by the recording indexer.
  async streamDrawsWhatFreshDriversDraw() {
    const zlib = require("node:zlib"), dir = process.argv[3];
    const {tracedDriver, renderPasses, drawnCold, firstDifference} = require("./webgpu_trace.cjs");
    vm.runInThisContext(fs.readFileSync(path.join(STATIC, "geometry_recording.js"), "utf8"));
    const meta = JSON.parse(fs.readFileSync(path.join(dir, "scene.json"), "utf8"));
    const data = zlib.gunzipSync(fs.readFileSync(path.join(dir, "scene.bin.gz")));
    const frames = [];
    let offset = 0;
    for (const frame of meta.frames) {
      frames.push(new Uint8Array(data.buffer, data.byteOffset + offset, frame.len));
      offset += frame.len;
    }
    const recording = globalThis.ManimlRecording.index(frames);
    const d = await tracedDriver();
    for (const [index, bytes] of frames.entries()) {
      await d.renderer.render(bytes.slice().buffer);
      const cold = await drawnCold(recording.frame(index));
      assert.equal(cold.error, undefined, `frame ${index} draws whole`);
      const found = firstDifference(renderPasses(d.trace()), cold.drawn);
      assert.equal(found, null, `frame ${index} draws what a fresh driver draws: ${found}`);
    }
    assert.equal(d.cacheMisses(), 0);
    await d.destroy();
    assert.ok(d.buffers.every(buffer => buffer.destroyed));
    process.stdout.write(JSON.stringify({frames: frames.length}));
  },
  // Format 8 (B4.8): a delta is applied only to the frame it was taken
  // against. It keeps the retained slots it does not splice, resolves the
  // batches it carries as a full frame's that differ, takes the scalars its
  // ops name and the stream's camera where it sends none. A delta against
  // another frame (another base or epoch, or no stream at all) draws
  // nothing and asks for a full frame once per epoch (the cache-miss
  // callback, the viewer's geometry_reset); one that fails is rolled back,
  // leaving the retained frame and the stream as they were, and asks the
  // same; a full frame of any format recovers. A full frame that fails asks
  // nothing, as a format 7 frame's failure does (the full frame it would be
  // answered with fails alike, so the page and the engine would ask and
  // answer without end at rest); the epoch's first delta asks instead.
  async deltasApplyOnlyToTheirBase() {
    const d = await driver();
    const plain = (hash, value) => ({pipeline: "surface", hash, num_verts: 3, count: 3, fill_value: value});
    const program = (hash, alpha) => patchRun(hash, 4, H("f"), H("9"), {program: blend([H("1"), H("2")], alpha, 9, 17)});
    const tables = {object_data: {[H("f")]: objectTable([[4, 1]])},
      program_data: {[H("1")]: floats(153, 1), [H("2")]: floats(153, 2)}};
    const drawn = passes => sceneDraws(passes).length;
    const first = [plain("a", 1), plain("b", 2), program("p", .25), plain("c", 3)];
    let passes = await d.renderBytes(fullEight(formatSeven(first, tables), 1));
    const draws = drawn(passes);
    assert.ok(draws > 4);
    let before = d.counts();
    // b replaced by d in place: one upload, the retained slots kept.
    passes = await d.renderBytes(deltaEight(formatSeven([plain("d", 4)]), 1, 1, 0, [[1, 1, 1]]));
    let delta = countsDelta(before, d.counts());
    assert.equal(drawn(passes), draws);
    assert.equal(delta.buffers_created, 1);
    assert.equal(delta.buffers_destroyed, 1, "b's geometry is released after the submit");
    assert.equal(delta.compute_dispatches, 0);
    // The program's scalars move: one evaluation, nothing made.
    before = d.counts();
    passes = await d.renderBytes(deltaEight(formatSeven([]), 1, 2, 1, [], {scalars: [[2, [.75]]]}));
    delta = countsDelta(before, d.counts());
    assert.equal(drawn(passes), draws);
    assert.equal(delta.buffers_created, 0);
    assert.ok(delta.compute_dispatches > 0, "the moved program is evaluated again");
    const params = passes.find(pass => pass.compute).draws[0].bindings.get(0).entries[0].resource.buffer;
    assert.equal(new Float32Array(params.bytes)[1], .75);
    // The camera, sent alone, rewrites the uniform sets in place.
    before = d.counts();
    passes = await d.renderBytes(deltaEight(formatSeven([]), 1, 3, 2, [], {camera: {...CAMERA, frame_scale: .5}}));
    delta = countsDelta(before, d.counts());
    assert.equal(delta.buffers_created, 0);
    assert.equal(delta.bind_groups_created, 0);
    assert.ok(delta.uniform_writes > 0);
    assert.equal(uniform(sceneDraws(passes)[0])[23], .5);
    // Against another base: nothing drawn, one request for a full frame
    // however many follow in the epoch.
    const submits = d.submissions.length;
    for (const base of [5, 2]) {
      assert.equal(await d.renderer.render(deltaEight(formatSeven([]), 1, base + 1, base, [])), null);
    }
    assert.equal(d.cacheMisses(), 1);
    assert.equal(d.submissions.length, submits);
    // A delta that fails leaves the frame and the stream where they were:
    // a splice past the end, then scalars for a batch without a program.
    for (const [fields, splices] of [[{}, [[9, 1, 0]]], [{scalars: [[0, [.5]]]}, []]]) {
      await assert.rejects(d.renderer.render(deltaEight(formatSeven([]), 1, 4, 3, splices, fields)), /geometry delta/);
    }
    assert.equal(d.cacheMisses(), 1, "the epoch's full frame was already asked for");
    passes = await d.renderBytes(deltaEight(formatSeven([plain("e", 5)]), 1, 4, 3, [[3, 1, 1]]));
    assert.equal(drawn(passes), draws, "the stream resumes where it stood");
    // A new epoch opens with a full frame; its first delta that fails asks again.
    passes = await d.renderBytes(fullEight(formatSeven(cached([plain("a", 1)])), 2));
    assert.equal(drawn(passes), 1);
    await assert.rejects(d.renderer.render(deltaEight(formatSeven([]), 2, 1, 0, [], {scalars: [[0, [.5]]]})), /scalars/);
    assert.equal(d.cacheMisses(), 2);
    // A format 7 frame ends the stream: no delta applies after it.
    await d.renderBytes(formatSeven(cached([plain("a", 1)])));
    assert.equal(await d.renderer.render(deltaEight(formatSeven([]), 3, 1, 0, [])), null);
    assert.equal(d.cacheMisses(), 3);
    // Nor after the driver is destroyed and made again.
    await d.renderBytes(fullEight(formatSeven(cached([plain("a", 1)])), 4));
    await d.destroy();
    await d.init();
    assert.equal(await d.renderer.render(deltaEight(formatSeven([]), 4, 1, 0, [])), null);
    assert.equal(d.cacheMisses(), 4);
    await d.destroy();
    assert.ok(d.buffers.every(buffer => buffer.destroyed));
    // Full frames that fail the same way every time (an image the browser
    // cannot decode, as Chrome cannot a TIFF): neither epoch's asks.
    const failing = await driver({decode: async () => { throw new Error("The source image could not be decoded."); }});
    const image = {pipeline: "image", hash: "img", num_verts: 6, count: 6, textures: {Texture: H("7")}};
    const undecodable = {texture_data: {[H("7")]: Buffer.alloc(4)}};
    for (const epoch of [1, 2]) {
      await assert.rejects(failing.renderer.render(fullEight(formatSeven([plain("a", 1), image], undecodable), epoch)),
                           /could not be decoded/);
    }
    assert.equal(failing.cacheMisses(), 0, "a failed full frame asks nothing");
    assert.equal(failing.submissions.length, 0);
    // The epoch's deltas find no frame to apply to: the first asks, once.
    for (const number of [1, 2]) {
      assert.equal(await failing.renderer.render(deltaEight(formatSeven([]), 2, number, number - 1, [])), null);
    }
    assert.equal(failing.cacheMisses(), 1, "the epoch's first delta asks for a full frame");
    // The full frame that answers, without the image, opens a stream that applies.
    await failing.renderBytes(fullEight(formatSeven([plain("a", 1)]), 3));
    passes = await failing.renderBytes(deltaEight(formatSeven([plain("b", 2)]), 3, 1, 0, [[1, 0, 1]]));
    assert.equal(drawn(passes), 2);
    assert.equal(failing.cacheMisses(), 1);
    await failing.destroy();
    assert.ok(failing.buffers.every(buffer => buffer.destroyed));
  },
  // Format 8 (docs/phase_b4_plan.md, B4.8): a stream of deltas draws what
  // the same frames sent whole draw. Two recordings of one history
  // (tests.test_browser_frames writes them: the format 7 full frames a
  // receiver that has not negotiated is sent, and the format 8 stream, where
  // a frame that changed nothing is no message, length 0), each played in
  // order on a driver of its own, a renderer switch destroying both and
  // initializing them again as the page's selection does. After every
  // message the two hold the same slots (their batches as a receiver holds
  // them) and the same live buffers (size, usage and bytes), and a message
  // of both made the same submission, compute passes included; where the
  // stream sent nothing, the full frame drew the picture already on screen.
  async deltaEqualsFull() {
    const zlib = require("node:zlib"), [fullDir, deltaDir] = process.argv.slice(3);
    const {tracedDriver, renderPasses, firstDifference} = require("./webgpu_trace.cjs");
    const crypto = require("node:crypto");
    const read = dir => {
      const meta = JSON.parse(fs.readFileSync(path.join(dir, "scene.json"), "utf8"));
      const data = zlib.gunzipSync(fs.readFileSync(path.join(dir, "scene.bin.gz")));
      let offset = 0;
      return meta.frames.map(({len}) => {
        const bytes = len ? data.buffer.slice(data.byteOffset + offset, data.byteOffset + offset + len) : null;
        offset += len;
        return bytes;
      });
    };
    const headerOf = bytes => JSON.parse(Buffer.from(bytes, 5, new DataView(bytes).getUint32(1, true)).toString());
    const held = batch => {
      const {offset, index_offset, cached, ...rest} = batch;
      if (rest.border) { const {layout, ...border} = rest.border; rest.border = border; }
      return JSON.stringify(rest);
    };
    const live = d => d.buffers.filter(buffer => !buffer.destroyed).map(buffer => [buffer.descriptor.size,
      buffer.descriptor.usage, crypto.createHash("sha1").update(new Uint8Array(buffer.bytes)).digest("hex")].join(":")).sort();
    const full = read(fullDir), stream = read(deltaDir);
    assert.equal(full.length, stream.length);
    const f = await tracedDriver(), d = await tracedDriver();
    let renderer = null, onScreen = null, headers = [null, null], deltas = 0, skipped = 0;
    for (const [index, bytes] of full.entries()) {
      const header = headerOf(bytes);
      if (renderer !== null && header.renderer !== renderer) {
        for (const driver of [f, d]) { await driver.destroy(); await driver.init(); driver.trace(); }
        onScreen = null;
      }
      renderer = header.renderer;
      headers[0] = await f.renderer.render(bytes.slice(0));
      const drawn = f.trace();
      assert.equal(drawn.length, 1, `frame ${index}: one submission of the full frame`);
      if (stream[index] === null) {
        skipped++;
        assert.notEqual(onScreen, null, `frame ${index}: a stream opens with a full frame`);
        assert.equal(d.trace().length, 0);
        assert.ok(drawn[0].every(pass => pass[0] === "render"), `frame ${index}: nothing to evaluate`);
        const found = firstDifference(renderPasses(drawn), onScreen);
        assert.equal(found, null, `frame ${index}: the stream sent nothing, and the full frame redrew: ${found}`);
      } else {
        const message = headerOf(stream[index]);
        assert.equal(message.format_version, 8);
        if ("base" in message) deltas++;
        headers[1] = await d.renderer.render(stream[index].slice(0));
        assert.ok(headers[1], `frame ${index}: the delta applied`);
        const found = firstDifference(d.trace(), drawn);
        assert.equal(found, null, `frame ${index}: the stream's message made the full frame's submission: ${found}`);
      }
      onScreen = renderPasses(drawn);
      // Each driver has a realm of its own: the lists are made in this one.
      const slots = headers.map(header => Array.from(header.batches, held));
      assert.deepEqual(slots[1], slots[0], `frame ${index}: the same slots`);
      assert.deepEqual(live(d), live(f), `frame ${index}: the same live buffers`);
    }
    assert.equal(f.cacheMisses() + d.cacheMisses(), 0);
    for (const driver of [f, d]) {
      await driver.destroy();
      assert.ok(driver.buffers.every(buffer => buffer.destroyed));
    }
    process.stdout.write(JSON.stringify({frames: full.length, deltas, skipped}));
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

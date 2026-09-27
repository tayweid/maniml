// What the browser driver asks of the GPU, traced by content for the
// command tests. Each submission is its passes; every draw is its pipeline's
// descriptor, the content of each bound group, vertex and index buffer, its
// stencil reference and arguments, rather than the identity of those
// objects; every compute dispatch is its kernel and what the kernel reads.
// Compute writes are simulated: each range a dispatch writes takes a token
// derived from its inputs, so a draw that reads an output evaluated from
// other inputs (a stale one, or another object's) traces differently. Two
// drivers, or one driver with its retained frame and a fresh one given the
// same frame whole, that trace a frame's render passes alike ask the GPU
// for the same pixels.
"use strict";
const crypto = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");
const {STATIC, driver} = require("./webgpu_fake_device.cjs");

const digest = (...parts) => {
  const hash = crypto.createHash("sha1");
  for (const part of parts) {
    hash.update(part instanceof Uint8Array ? part : JSON.stringify(part));
    hash.update("\0");
  }
  return hash.digest("hex").slice(0, 20);
};

const wgsl = name => fs.readFileSync(path.join(STATIC, "wgsl", name), "utf8");

// struct Uniforms (common.wgsl) in floats, laid out without padding: every
// vec3f is followed by one f32.
const UNIFORM_OFFSETS = (() => {
  const sizes = {mat4x4f: 16, vec4f: 4, vec3f: 3, f32: 1}, offsets = {};
  let cursor = 0;
  for (const [, name, type] of wgsl("common.wgsl").match(/struct Uniforms \{([^}]*)\}/)[1].matchAll(/(\w+)\s*:\s*(\w+)/g)) {
    offsets[name] = Array.from({length: sizes[type]}, (_, i) => cursor + i);
    cursor += sizes[type];
  }
  return offsets;
})();

// The uniform fields a generation kernel reads: its output depends on these
// and on nothing else of its uniform set, so a camera move that changes only
// the view leaves it valid. Checked against the kernel's own source (not
// common.wgsl's helpers, which it does not call), so a kernel that starts
// reading another field fails here instead of tracing as equal.
// border_compute.wgsl reads camera_position only for a stroke that is not
// flat (flat_stroke or is_fixed_in_frame).
const KERNEL_READS = {
  BorderParams: ["border_compute.wgsl", ["camera_position", "flat_stroke", "frame_scale", "is_fixed_in_frame",
                                         "joint_type", "scale_stroke_with_zoom"]],
  NetParams: ["net_compute.wgsl", ["frame_scale"]],
};
for (const [kernel, [file, fields]] of Object.entries(KERNEL_READS)) {
  const read = [...new Set([...wgsl(file).matchAll(/\bu\.(\w+)/g)].map(match => match[1]))].sort();
  if (read.join() !== fields.join()) throw new Error(`${file} reads ${read}; the trace of ${kernel} knows ${fields}`);
}

function uniformReads(kernel, resource) {
  const offset = (resource.offset ?? 0) / 4;
  const floats = new Float32Array(resource.buffer.bytes), bits = new Uint32Array(resource.buffer.bytes);
  const at = name => UNIFORM_OFFSETS[name].map(i => offset + i);
  const flat = floats[at("flat_stroke")[0]] !== 0 || floats[at("is_fixed_in_frame")[0]] !== 0;
  return KERNEL_READS[kernel][1].filter(name => !(flat && name === "camera_position"))
    .flatMap(name => at(name).map(i => bits[i]));
}

// The kernel a compute pipeline runs, by its parameter struct, and the
// group 1 bindings it writes (its read_write storage).
const KERNELS = new Map();
function kernelOf(module) {
  if (!KERNELS.has(module.code)) {
    const name = (module.code.match(/struct (\w+Params)\b/g) || []).map(text => text.slice(7)).at(-1) || "unknown";
    const outputs = [...module.code.matchAll(/@group\(1\) @binding\((\d+)\) var<storage, read_write>/g)].map(match => +match[1]);
    KERNELS.set(module.code, {name, outputs, code: digest(module.code)});
  }
  return KERNELS.get(module.code);
}

// A tracer keeps the simulated writes of one device's buffers.
function tracer() {
  const writes = new WeakMap(), contents = new WeakMap(), pipelines = new WeakMap();

  // A buffer's content: its bytes (as the fake device holds them) and the
  // tokens the simulated kernels wrote into it, by range.
  function content(buffer) {
    let cached = contents.get(buffer);
    if (!cached || cached.version !== buffer.version) {
      cached = {version: buffer.version, bytes: digest(new Uint8Array(buffer.bytes))};
      contents.set(buffer, cached);
    }
    const ranges = writes.get(buffer);
    return ranges ? digest(cached.bytes, [...ranges].sort()) : cached.bytes;
  }

  function pipeline(object) {
    if (!pipelines.has(object)) {
      pipelines.set(object, digest(JSON.stringify(object.descriptor, (key, value) =>
        value && typeof value === "object" && typeof value.code === "string" ? "module:" + digest(value.code) : value)));
    }
    return pipelines.get(object);
  }

  const layout = object => object.explicit ? ["explicit", digest(JSON.stringify(object.descriptor))]
    : ["auto", pipeline(object.pipeline), object.index];
  const texture = object => [object.descriptor.format, Array.from(object.descriptor.size || []),
    object.descriptor.sampleCount || 1, object.descriptor.usage || 0, object.image ? object.image.content : null];
  const resource = object => object.buffer
    ? ["buffer", content(object.buffer), object.offset ?? 0, object.size ?? object.buffer.descriptor.size]
    : object.texture ? ["texture", texture(object.texture)] : ["sampler", digest(object.descriptor || {})];
  const group = object => [layout(object.layout), object.entries.map(entry => [entry.binding, resource(entry.resource)])];
  const groups = bindings => [...bindings.entries()].sort((a, b) => a[0] - b[0]).map(([index, bound]) => [index, group(bound)]);

  function dispatch(draw) {
    const kernel = kernelOf(draw.pipeline.descriptor.compute.module);
    const inputs = [];
    for (const [index, bound] of [...draw.bindings.entries()].sort((a, b) => a[0] - b[0])) {
      for (const {binding, resource: target} of bound.entries) {
        if (index === 1 && kernel.outputs.includes(binding)) {
          inputs.push([index, binding, "out", target.offset ?? 0, target.size ?? target.buffer.descriptor.size]);
        } else if (index === 0 && binding === 0 && kernel.name in KERNEL_READS) {
          inputs.push([index, binding, "uniforms", uniformReads(kernel.name, target)]);
        } else {
          inputs.push([index, binding, resource(target)]);
        }
      }
    }
    const traced = [kernel.name, kernel.code, inputs, draw.count, draw.rows];
    const token = digest(traced);
    // The ranges it writes: a border or net dispatch covers a chunk of its
    // output (the chunk's first curve and count, or first patch and count),
    // a program kernel the whole binding.
    const params = draw.bindings.get(0).entries;
    const words = params.length > 1 ? new Uint32Array(params[1].resource.buffer.bytes) : null;
    for (const {binding, resource: target} of draw.bindings.get(1).entries) {
      if (!kernel.outputs.includes(binding)) continue;
      const range = kernel.name === "BorderParams" ? `border:${words[0]}:${words[1]}:${target.offset ?? 0}`
        : kernel.name === "NetParams" ? `net:${words[6]}:${words[7]}` : `${kernel.name}:${binding}`;
      if (!writes.has(target.buffer)) writes.set(target.buffer, new Map());
      writes.get(target.buffer).set(range, digest(token, range));
    }
    return traced;
  }

  function pass(object) {
    if (object.copy) {
      const [source, from, target, to, size] = object.copy;
      return ["copy", content(source), from, to, size, target.descriptor.size];
    }
    if (object.compute) return ["compute", object.draws.map(dispatch)];
    const {colorAttachments, depthStencilAttachment: depth} = object.descriptor;
    return ["render",
      colorAttachments.map(color => [color.loadOp, color.storeOp, color.clearValue ?? null, texture(color.view.texture),
                                     color.resolveTarget ? texture(color.resolveTarget.texture) : null]),
      depth ? [texture(depth.view.texture), depth.depthLoadOp, depth.depthStoreOp, depth.depthClearValue,
               depth.stencilLoadOp, depth.stencilStoreOp, depth.stencilClearValue] : null,
      object.draws.map(draw => [pipeline(draw.pipeline), groups(draw.bindings),
        draw.vertices.map(buffer => buffer ? content(buffer) : null),
        draw.index ? [content(draw.index.buffer), draw.index.format] : null, draw.stencil ?? null, draw.args, draw.indexed])];
  }

  // A submission's passes in order: the compute passes first record the
  // writes that the render passes' draws then read.
  return {submission: passes => passes.map(pass)};
}

// A fake device (validation on) whose submissions can be traced, with each
// decoded texture tagged by the content of its image. trace() returns the
// submissions made since it was last called, traced in order.
async function tracedDriver(options = {}) {
  const d = await driver({...options, decode: async blob => ({width: 2, height: 2, close() {},
    content: digest(new Uint8Array(await blob.arrayBuffer()))})});
  const traced = tracer();
  let seen = 0;
  d.trace = () => {
    const out = d.submissions.slice(seen).map(traced.submission);
    seen = d.submissions.length;
    return out;
  };
  return d;
}

// What was drawn: the render passes of each submission. What the compute
// passes wrote is in the tokens the draws read, and a driver that kept an
// output from an earlier frame has no compute pass for it.
const renderPasses = submissions => submissions.map(passes => passes.filter(pass => pass[0] === "render"));

// A message drawn by a fresh driver: its render passes, or the error.
async function drawnCold(message, options = {}) {
  const d = await tracedDriver(options);
  try {
    await d.renderer.render(message);
    return {drawn: renderPasses(d.trace()), misses: d.cacheMisses()};
  } catch (error) {
    return {error: error.message};
  } finally {
    await d.destroy();
  }
}

// The first place two traces differ, or null.
function firstDifference(a, b, at = "") {
  if (Array.isArray(a) && Array.isArray(b)) {
    if (a.length !== b.length) return `${at}: ${a.length} entries != ${b.length}`;
    for (let i = 0; i < a.length; i++) {
      const found = firstDifference(a[i], b[i], `${at}[${i}]`);
      if (found) return found;
    }
    return null;
  }
  const [x, y] = [JSON.stringify(a), JSON.stringify(b)];
  return x === y ? null : `${at}: ${x.slice(0, 160)} != ${y.slice(0, 160)}`;
}

module.exports = {tracedDriver, renderPasses, drawnCold, firstDifference, UNIFORM_OFFSETS};

// WebGPU browser driver — the JS mirror of maniml/web/wgpu_renderer.py.
// Same WGSL (fetched from wgsl/), same pipeline specs, same pass
// structure; keep the two in sync. Presents via a blit pass because
// the canvas swapchain format is platform-preferred (bgra8unorm on
// macOS) while the scene target stays rgba8unorm like the reference.
"use strict";

const ManimlWGPU = (() => {
  const VERTEX_STRIDE = 68;
  const INSTANCE_STRIDE = 3 * VERTEX_STRIDE;
  const UNIFORM_FLOATS = 48;  // must match UNIFORM_FIELDS / struct Uniforms
  const DEPTH_FORMAT = "depth24plus-stencil8";

  // Field order mirrors wgpu_renderer.UNIFORM_FIELDS
  const UNIFORM_LAYOUT = [
    ["view", 16, null],
    ["frame_rescale_factors", 3, null], ["is_fixed_in_frame", 1, 0],
    ["camera_position", 3, null], ["frame_scale", 1, 1],
    ["light_position", 3, null], ["pixel_size", 1, 1],
    ["shading", 3, [0, 0, 0]], ["anti_alias_width", 1, 1.5],
    ["clip_plane", 4, [0, 0, 0, 0]],
    ["joint_type", 1, 1], ["flat_stroke", 1, 0],
    ["scale_stroke_with_zoom", 1, 1], ["glow_factor", 1, 0],
    ["num_textures", 1, 0], ["border_mode", 1, 0],
    ["premultiplied_output", 1, 0], ["_pad1", 1, 0],
    ["clip_transform", 4, [1, 1, 0, 0]],
  ];

  const attr = (format, offset, shaderLocation) =>
    ({ format, offset, shaderLocation });
  const layout = (arrayStride, stepMode, attributes) =>
    [{ arrayStride, stepMode, attributes }];

  const STROKE_LAYOUT = layout(INSTANCE_STRIDE, "instance", [
    attr("float32x3", 0, 0), attr("float32x3", 68, 1),
    attr("float32x3", 136, 2),
    attr("float32x4", 12, 3), attr("float32x4", 80, 4),
    attr("float32x4", 148, 5),
    attr("float32", 28, 6), attr("float32", 96, 7),
    attr("float32", 164, 8),
    attr("float32", 32, 9), attr("float32", 168, 10),
    attr("float32x3", 120, 11),
  ]);
  const SURFACE_LAYOUT = layout(40, "vertex", [
    attr("float32x3", 0, 0), attr("float32x3", 12, 1),
    attr("float32x4", 24, 2),
  ]);
  const DOT_LAYOUT = layout(32, "instance", [
    attr("float32x3", 0, 0), attr("float32", 12, 1),
    attr("float32x4", 16, 2),
  ]);
  const IMAGE_LAYOUT = layout(24, "vertex", [
    attr("float32x3", 0, 0), attr("float32x2", 12, 1),
    attr("float32", 20, 2),
  ]);
  const TEXSURFACE_LAYOUT = layout(36, "vertex", [
    attr("float32x3", 0, 0), attr("float32x3", 12, 1),
    attr("float32x2", 24, 2), attr("float32", 32, 3),
  ]);

  const PREMULTIPLIED_BLEND = {
    color: { srcFactor: "one", dstFactor: "one-minus-src-alpha",
             operation: "add" },
    alpha: { srcFactor: "one", dstFactor: "one-minus-src-alpha",
             operation: "add" },
  };

  // All operations share a premultiplied scene target, with explicit depth.
  const PIPELINE_SPECS = {};
  for (const [module, buffers, topology] of [
    ["stroke", STROKE_LAYOUT, "triangle-strip"],
    ["surface", SURFACE_LAYOUT, "triangle-list"],
    ["paint", SURFACE_LAYOUT, "triangle-list"],
    ["dot", DOT_LAYOUT, "triangle-strip"],
    ["image", IMAGE_LAYOUT, "triangle-list"],
    ["texsurface", TEXSURFACE_LAYOUT, "triangle-list"],
  ]) {
    for (const depth of [false, true]) {
      PIPELINE_SPECS["generated_" + module + (depth ? "_depth" : "")] =
        [module, buffers, topology, "out", PREMULTIPLIED_BLEND, depth];
    }
  }

  for (const [name, spec] of Object.entries(PIPELINE_SPECS)) {
    if (spec[0] === "surface" || spec[0] === "paint") {
      PIPELINE_SPECS[name + "_coverage"] = spec;
      if (spec[5]) PIPELINE_SPECS[name + "_depth_only"] = spec;
    }
  }

  const MODULE_SOURCES = {
    stroke: ["common.wgsl", "stroke.wgsl"],
    surface: ["common.wgsl", "surface.wgsl"],
    paint: ["common.wgsl", "paint_field.wgsl", "paint.wgsl"],
    dot: ["common.wgsl", "dot.wgsl"],
    image: ["common.wgsl", "image.wgsl"],
    texsurface: ["common.wgsl", "texsurface.wgsl"],
    blit: ["blit.wgsl"],
    resolve2: ["resolve2.wgsl"],
    border_compute: ["common.wgsl", "border_compute.wgsl"],
  };

  let canvas = null, context = null, device = null, canvasFormat = null;
  let modules = {}, pipelines = new Map(), blitPipeline = null, resolve2Pipeline = null;
  let sampler;
  let outTexture, resolveTexture, depthTexture;
  let outView, resolveView, depthView;
  let targetKey = null;
  const textureCache = new Map();
  const generatedGeometry = new Map();
  const generatedUniforms = new Map();
  const generatedTextures = new Map();
  const generatedPaints = new Map();  // paint identity -> immutable storage
  const generatedPaintBindings = new Map();
  const borderSources = new Map(), borderOutputs = new Map();
  let borderPipeline = null;
  // Index buffers superseded by a run's new reservation; destroyed with the
  // other retired resources after the frame's commands are submitted.
  let staleIndexBuffers = [];
  // Sources are 176 bytes per curve and must fit one portable storage binding.
  const MAX_BORDER_CURVES = Math.floor((128 << 20) / 176);
  let usedGeneratedGeometry = new Set();
  let usedGeneratedUniforms = new Set();
  let usedGeneratedTextures = new Set();
  let usedGeneratedPaints = new Set();
  let usedGeneratedPaintBindings = new Set();
  let cacheMissed = false;
  let renderQueue = Promise.resolve();
  let closing = false;
  let teardown = null;

  async function fetchWgsl(names) {
    const parts = [];
    for (const name of names) {
      const resp = await fetch("wgsl/" + name);
      if (!resp.ok) throw new Error("failed to fetch " + name);
      parts.push(await resp.text());
    }
    return parts.join("\n");
  }

  async function init(canvasEl) {
    if (device) throw new Error("renderer is already initialized");
    closing = false;
    teardown = null;
    if (!navigator.gpu) throw new Error("WebGPU unavailable");
    const adapter = await navigator.gpu.requestAdapter(
      { powerPreference: "high-performance" });
    if (!adapter) throw new Error("no WebGPU adapter");
    device = await adapter.requestDevice();
    canvas = canvasEl;
    context = canvas.getContext("webgpu");
    canvasFormat = navigator.gpu.getPreferredCanvasFormat();
    context.configure({ device, format: canvasFormat, alphaMode: "opaque" });

    for (const [key, sources] of Object.entries(MODULE_SOURCES)) {
      modules[key] = device.createShaderModule({
        code: await fetchWgsl(sources) });
    }
    blitPipeline = device.createRenderPipeline({
      layout: "auto",
      vertex: { module: modules.blit, entryPoint: "vs_main" },
      primitive: { topology: "triangle-list" },
      fragment: { module: modules.blit, entryPoint: "fs_main",
                  targets: [{ format: canvasFormat }] },
    });
    resolve2Pipeline = device.createRenderPipeline({
      layout: "auto",
      vertex: { module: modules.resolve2, entryPoint: "vs_main" },
      primitive: { topology: "triangle-list" },
      fragment: { module: modules.resolve2, entryPoint: "fs_main",
                  targets: [{ format: canvasFormat }] },
    });
    sampler = device.createSampler({
      magFilter: "linear", minFilter: "linear",
      addressModeU: "repeat", addressModeV: "repeat" });
  }

  function makeBuffer(arrayBufferLike, usage) {
    const bytes = arrayBufferLike instanceof Uint8Array
      ? arrayBufferLike : new Uint8Array(arrayBufferLike);
    const size = Math.max(4, Math.ceil(bytes.byteLength / 4) * 4);
    const buffer = device.createBuffer(
      { size, usage, mappedAtCreation: true });
    new Uint8Array(buffer.getMappedRange()).set(bytes);
    buffer.unmap();
    return buffer;
  }

  function getPipeline(name, samples) {
    const key = name + "@" + samples;
    if (pipelines.has(key)) return pipelines.get(key);
    const [moduleKey, buffers, topology, target, blend, depthTest] =
      PIPELINE_SPECS[name];
    const descriptor = {
      layout: "auto",
      vertex: { module: modules[moduleKey], entryPoint: "vs_main", buffers },
      primitive: { topology },
    };
    const coverage = name.endsWith("_coverage");
    const depthOnly = name.endsWith("_depth_only");
    descriptor.fragment = {
      module: modules[moduleKey], entryPoint: "fs_main",
      targets: [{ format: "rgba8unorm", blend, writeMask: depthOnly ? 0 : 15 }] };
    descriptor.depthStencil = {
      format: DEPTH_FORMAT,
      depthWriteEnabled: depthTest && !coverage,
      depthCompare: depthTest ? "less" : "always",
      stencilFront: { compare: coverage ? "not-equal" : "always",
        failOp: "keep", depthFailOp: "keep", passOp: coverage ? "replace" : "keep" },
      stencilBack: { compare: coverage ? "not-equal" : "always",
        failOp: "keep", depthFailOp: "keep", passOp: coverage ? "replace" : "keep" },
      stencilReadMask: 255, stencilWriteMask: coverage ? 255 : 0,
    };
    descriptor.multisample = { count: samples };
    const pipeline = device.createRenderPipeline(descriptor);
    pipelines.set(key, pipeline);
    return pipeline;
  }

  function ensureTargets(width, height, samples, outputWidth = width, outputHeight = height) {
    const key = width + "x" + height + "@" + samples + ":" + outputWidth + "x" + outputHeight;
    if (targetKey === key) return;
    targetKey = key;
    canvas.width = outputWidth;
    canvas.height = outputHeight;
    for (const t of [outTexture, resolveTexture, depthTexture]) {
      if (t) t.destroy();
    }
    const attach = GPUTextureUsage.RENDER_ATTACHMENT;
    resolveTexture = null; resolveView = null;
    if (samples > 1) {
      outTexture = device.createTexture({
        size: [width, height], format: "rgba8unorm", sampleCount: samples,
        usage: attach });
      resolveTexture = device.createTexture({
        size: [width, height], format: "rgba8unorm",
        usage: attach | GPUTextureUsage.TEXTURE_BINDING });
      resolveView = resolveTexture.createView();
    } else {
      outTexture = device.createTexture({
        size: [width, height], format: "rgba8unorm",
        usage: attach | GPUTextureUsage.TEXTURE_BINDING });
    }
    outView = outTexture.createView();
    depthTexture = device.createTexture({
      size: [width, height], format: DEPTH_FORMAT, sampleCount: samples,
      usage: attach });
    depthView = depthTexture.createView();
  }

  function outPass(encoder, clearColor, clearStencil = false) {
    const color = {
      view: outView,
      loadOp: clearColor ? "clear" : "load",
      storeOp: "store",
    };
    if (clearColor) {
      color.clearValue = { r: clearColor[0], g: clearColor[1],
                          b: clearColor[2], a: clearColor[3] };
    }
    if (resolveView) color.resolveTarget = resolveView;
    return encoder.beginRenderPass({
      colorAttachments: [color],
      depthStencilAttachment: {
        view: depthView,
        depthLoadOp: clearColor ? "clear" : "load",
        depthStoreOp: "store",
        depthClearValue: 1.0,
        stencilLoadOp: clearColor || clearStencil ? "clear" : "load",
        stencilStoreOp: "store", stencilClearValue: 0,
      },
    });
  }

  function packUniforms(values, borderMode) {
    const out = new Float32Array(UNIFORM_FLOATS);
    let cursor = 0;
    for (const [name, n, fallback] of UNIFORM_LAYOUT) {
      let value = name in values ? values[name] : fallback;
      if (name === "border_mode") value = borderMode;
      if (value === null || value === undefined) {
        throw new Error("uniform " + name + " missing");
      }
      if (n === 1) out[cursor] = value;
      else out.set(value, cursor);
      cursor += n;
    }
    return out.buffer;
  }

  // [capacity, layout] of a GPU border batch. Format 6 runs carry only their
  // fill indices and the per-object layout the driver expands at the run's
  // reserved capacity; format 5 shipped the complete buffer at capacity 64.
  // A cached format 6 batch omits its layout: the retained geometry holds
  // it, and a batch that has neither is a cache miss (layout undefined).
  function borderRun(batch) {
    const border = batch.border;
    if (!border) return [null, null];
    if (!("capacity" in border)) return [64, null];
    const capacity = border.capacity;
    if (!Number.isSafeInteger(capacity) || capacity % 2 || capacity < 4 || capacity > 64) {
      throw new Error("invalid GPU border geometry layout or draw count");
    }
    if ("layout" in border) return [capacity, border.layout];
    const res = generatedGeometry.get(batch.hash);
    return [capacity, res && res.runLayout ? res.runLayout : undefined];
  }

  function validateRunLayout(layout, indexCount, fillCount, curveCount) {
    if (!Array.isArray(layout) || !layout.length) throw new Error("invalid GPU border run layout");
    let indices = 0, vertices = 0, curves = 0;
    for (const part of layout) {
      if (!Array.isArray(part) || part.length !== 3
          || part.some(value => !Number.isSafeInteger(value) || value < 0) || part[2] < 1) {
        throw new Error("invalid GPU border run layout");
      }
      indices += part[0]; vertices += part[1]; curves += part[2];
    }
    if (indices !== indexCount || vertices !== fillCount || curves !== curveCount) {
      throw new Error("GPU border run layout does not match its fill and source arrays");
    }
  }

  function expandRunIndices(fillIndices, layout, fillCount, capacity) {
    const strips = capacity / 2 - 1;
    let total = 0;
    for (const [indices, , curves] of layout) total += indices + 6 * strips * curves;
    const out = new Uint32Array(total);
    let write = 0, read = 0, curveOffset = 0;
    for (const [indices, , curves] of layout) {
      out.set(fillIndices.subarray(read, read + indices), write);
      write += indices; read += indices;
      for (let curve = 0; curve < curves; curve++) {
        const base = fillCount + capacity * (curveOffset + curve);
        for (let strip = 0; strip < strips; strip++) {
          const v = base + 2 * strip;
          out[write++] = v; out[write++] = v + 1; out[write++] = v + 2;
          out[write++] = v + 1; out[write++] = v + 2; out[write++] = v + 3;
        }
      }
      curveOffset += curves;
    }
    return out;
  }

  function generatedResources(batch, vertexBytes) {
    usedGeneratedGeometry.add(batch.hash);
    let res = generatedGeometry.get(batch.hash);
    const [, runLayout] = borderRun(batch);
    if (runLayout === undefined) { cacheMissed = true; return null; }
    // A run's reserved capacity changes its output size but not what was
    // uploaded, so it stays out of the retained layout identity.
    const descriptor = JSON.stringify([batch.pipeline, batch.stride, runLayout ? null : batch.num_verts,
      !!batch.indexed, batch.index_count || 0, batch.fill_num_verts ?? batch.num_verts, runLayout ?? null]);
    if (res) {
      if (res.descriptor !== descriptor) throw new Error("cached generated geometry layout changed");
      return res;
    }
    if (batch.cached) { cacheMissed = true; return null; }
    const vertex = makeBuffer(vertexBytes.subarray(
      batch.offset, batch.offset + (batch.fill_num_verts ?? batch.num_verts) * batch.stride),
      GPUBufferUsage.VERTEX | (batch.border ? GPUBufferUsage.COPY_SRC : 0));
    const buffers = [vertex];
    let index = null, fillIndices = null, indexBuffers = null;
    if (batch.indexed && runLayout) {
      // Only the fill indices travel. Keep them to expand the ordered
      // fill/strip buffer for whatever capacity is drawn.
      const copy = vertexBytes.slice(batch.index_offset, batch.index_offset + batch.index_count * 4);
      fillIndices = new Uint32Array(copy.buffer, 0, batch.index_count);
      indexBuffers = new Map();
    } else if (batch.indexed) {
      index = makeBuffer(vertexBytes.subarray(
        batch.index_offset, batch.index_offset + batch.index_count * 4), GPUBufferUsage.INDEX);
      buffers.push(index);
    }
    res = { vertex, index, buffers, descriptor, fillIndices, indexBuffers, runLayout: runLayout ?? null };
    generatedGeometry.set(batch.hash, res);
    return res;
  }

  function runIndexBuffer(batch, res) {
    const [capacity, layout] = borderRun(batch);
    let buffer = res.indexBuffers.get(capacity);
    if (!buffer) {
      const expanded = expandRunIndices(res.fillIndices, layout, batch.fill_num_verts, capacity);
      if (expanded.length !== batch.count) throw new Error("invalid GPU border geometry layout or draw count");
      buffer = makeBuffer(expanded.buffer, GPUBufferUsage.INDEX);
      for (const old of res.indexBuffers.values()) staleIndexBuffers.push(old);
      res.indexBuffers.clear();
      res.indexBuffers.set(capacity, buffer);
      res.buffers = [res.vertex, buffer];
    }
    return buffer;
  }

  function generatedUniformBinding(name, samples, pipeline, uniforms) {
    const packed = packUniforms({ ...uniforms, premultiplied_output: 1 },
                                uniforms.border_mode || 0);
    // Compare actual uploaded bits, including per-object overrides. A shared
    // vertex buffer can occur with different uniforms in the same submission.
    const key = name + "@" + samples + ":" + new Uint32Array(packed).join(",");
    usedGeneratedUniforms.add(key);
    let res = generatedUniforms.get(key);
    if (!res) {
      const buffer = makeBuffer(packed, GPUBufferUsage.UNIFORM);
      const binding = device.createBindGroup({
        layout: pipeline.getBindGroupLayout(0),
        entries: [{ binding: 0, resource: { buffer } }],
      });
      res = { binding, buffers: [buffer] };
      generatedUniforms.set(key, res);
    }
    return res.binding;
  }

  function generatedTextureBinding(name, samples, pipeline, batch) {
    const hashes = Object.values(batch.textures);
    if (hashes.length === 1 && batch.pipeline.startsWith("texsurface")) {
      hashes.push(hashes[0]);  // DarkTexture falls back to light.
    }
    const key = name + "@" + samples + ":" + JSON.stringify(hashes);
    usedGeneratedTextures.add(key);
    if (generatedTextures.has(key)) return generatedTextures.get(key);
    const textures = hashes.map(hash => textureCache.get(hash));
    if (textures.some(texture => !texture)) { cacheMissed = true; return null; }
    const entries = textures.map((texture, i) => ({ binding: i, resource: texture.createView() }));
    entries.push({ binding: textures.length, resource: sampler });
    const binding = device.createBindGroup({
      layout: pipeline.getBindGroupLayout(1), entries,
    });
    generatedTextures.set(key, binding);
    return binding;
  }

  function prepareBorders(header, payload, encoder, temporary) {
    const records = "border_data" in header ? header.border_data : {};
    if (records === null || typeof records !== "object" || Array.isArray(records)) {
      throw new Error("border definitions must be an object");
    }
    const validHash = hash => typeof hash === "string" && /^[0-9a-f]{32}$/.test(hash);
    const definitions = new Map();
    for (const [key, ref] of Object.entries(records)) {
      if (!validHash(key)) throw new Error("invalid border hash");
      if (ref === null || typeof ref !== "object" || Array.isArray(ref)) {
        throw new Error("invalid border definition span");
      }
      const {offset, nbytes} = ref;
      if (!Number.isSafeInteger(offset) || !Number.isSafeInteger(nbytes)
          || offset < 0 || nbytes <= 0 || nbytes % 176 || nbytes > MAX_BORDER_CURVES * 176
          || offset > payload.length || nbytes > payload.length - offset) {
        throw new Error("invalid border definition span or curve count");
      }
      const bytes = payload.slice(offset, offset + nbytes);
      const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
      for (let i = 0; i < nbytes / 4; i++) {
        const value = view.getFloat32(4 * i, true), field = i % 44;
        if (!Number.isFinite(value) || ([7, 19, 31, 36].includes(field) && value < 0)
            || ((field === 37 || field === 38) && value !== 0 && value !== 1)
            || (field === 39 && value !== 0)) {
          throw new Error("invalid border coefficients, widths, density or active flags");
        }
      }
      const previous = borderSources.get(key);
      if (previous && (previous.bytes.length !== bytes.length
          || previous.bytes.some((value, i) => value !== bytes[i]))) {
        throw new Error("border hash redefined with different coefficients");
      }
      definitions.set(key, bytes);
    }
    const limits = device.limits || {};
    const maxBuffer = limits.maxBufferSize ?? 256 * 1024 ** 2;
    const maxStorage = limits.maxStorageBufferBindingSize ?? 128 * 1024 ** 2;
    const maxDispatch = limits.maxComputeWorkgroupsPerDimension ?? 65535;
    const alignment = limits.minStorageBufferOffsetAlignment ?? 256;
    const gcd = (a, b) => b ? gcd(b, a % b) : a;
    const vertexAlignment = 40 * alignment / gcd(40, alignment);
    const outputs = new Map(), usedSources = new Set(), usedOutputs = new Set(), completed = [];
    const cameras = new Map(), occurrences = new Map();
    for (const batch of header.batches) {
      if (!("border" in batch)) continue;
      const border = batch.border;
      if ((header.format_version ?? 0) < 5 || border === null
          || typeof border !== "object" || Array.isArray(border)) {
        throw new Error("GPU border requires a format 5 border descriptor");
      }
      const key = border.hash, count = border.num_curves, fillCount = batch.fill_num_verts;
      if (!validHash(key) || !Number.isSafeInteger(count) || count < 1 || count > MAX_BORDER_CURVES
          || !Number.isSafeInteger(fillCount) || fillCount < 0
          || !Number.isSafeInteger(batch.num_verts)
          || !["surface", "surface_depth", "paint", "paint_depth"].includes(batch.pipeline)
          || batch.stride !== 40 || batch.indexed !== true
          || !Number.isSafeInteger(batch.index_count) || batch.index_count % 3
          || !Number.isSafeInteger(batch.count) || batch.instances !== 1) {
        throw new Error("invalid GPU border geometry layout or draw count");
      }
      const [capacity, runLayout] = borderRun(batch);
      if (runLayout === undefined) { cacheMissed = true; outputs.set(batch, null); continue; }
      if (runLayout) validateRunLayout(runLayout, batch.index_count, fillCount, count);
      // Format 5 shipped the complete ordered index buffer; format 6 ships
      // the fills and the driver appends each object's strip pattern.
      const addressable = runLayout ? fillCount : batch.num_verts;
      const complete = runLayout
        ? batch.count === batch.index_count + 6 * (capacity / 2 - 1) * count
        : batch.index_count >= 186 * count && batch.count === batch.index_count;
      if (!complete || batch.num_verts !== fillCount + capacity * count) {
        throw new Error("invalid GPU border geometry layout or draw count");
      }
      const size = batch.num_verts * 40;
      const storageOffset = Math.floor(fillCount * 40 / vertexAlignment) * vertexAlignment;
      const storageSize = size - storageOffset;
      if (!Number.isSafeInteger(size) || size > maxBuffer || storageSize > maxStorage) {
        throw new Error("GPU border output exceeds device buffer limits");
      }
      let source = borderSources.get(key);
      const bytes = source ? source.bytes : definitions.get(key);
      if (!bytes) { cacheMissed = true; outputs.set(batch, null); continue; }
      if (bytes.length !== count * 176 || bytes.length > maxStorage) {
        throw new Error("border definition curve count does not match geometry");
      }
      if (!batch.cached) {
        const offset = batch.index_offset, vertexOffset = batch.offset;
        if (!Number.isSafeInteger(offset) || offset < 0 || offset > payload.length
            || batch.index_count * 4 > payload.length - offset
            || !Number.isSafeInteger(vertexOffset) || vertexOffset < 0 || vertexOffset > payload.length
            || fillCount * 40 > payload.length - vertexOffset) {
          throw new Error("border geometry extends beyond payload");
        }
        const indices = new DataView(payload.buffer, payload.byteOffset + offset, batch.index_count * 4);
        for (let i = 0; i < batch.index_count; i++) {
          if (indices.getUint32(4 * i, true) >= addressable) {
            throw new Error("border index exceeds generated vertex count");
          }
        }
        const vertices = new DataView(payload.buffer, payload.byteOffset + vertexOffset, fillCount * 40);
        for (let i = 0; i < fillCount * 10; i++) {
          if (!Number.isFinite(vertices.getFloat32(4 * i, true))) {
            throw new Error("border fill vertices must be finite");
          }
        }
      }
      const values = {...header.camera, ...batch.uniforms};
      const packed = packUniforms(values, values.border_mode || 0);
      const floats = new Float32Array(packed), bits = new Uint32Array(packed);
      const factor = floats[23] * (1 - floats[38]) + floats[38];
      if (floats.some(value => !Number.isFinite(value)) || floats[23] <= 0 || factor < 0
          || ![0, 1, 2, 3].includes(floats[36])) {
        throw new Error("invalid GPU border generation uniforms");
      }
      const flat = floats[37] !== 0 || floats[19] !== 0;
      const state = [23, 38, 36, 37, 19, ...(flat ? [] : [20, 21, 22])].map(i => bits[i]).join(",");
      const resources = generatedResources(batch, payload);
      if (!resources) { outputs.set(batch, null); continue; }
      if (!source) {
        source = {bytes, buffer: makeBuffer(bytes, GPUBufferUsage.STORAGE)};
        borderSources.set(key, source);
      }
      usedSources.add(key);
      // Outputs belong to draw occurrences: the same geometry drawn twice
      // with different uniforms needs two. Number occurrences of the same
      // geometry rather than every batch, so inserting an unrelated object
      // earlier in the frame rekeys nothing.
      const occurrenceKey = batch.hash + ":" + key;
      const occurrence = occurrences.get(occurrenceKey) ?? 0;
      occurrences.set(occurrenceKey, occurrence + 1);
      const outputKey = JSON.stringify([batch.hash, key, capacity, occurrence]);
      usedOutputs.add(outputKey);
      let output = borderOutputs.get(outputKey);
      if (!borderPipeline) borderPipeline = device.createComputePipeline({layout: "auto",
        compute: {module: modules.border_compute, entryPoint: "cs_main"}});
      if (!output) {
        const buffer = device.createBuffer({size,
          usage: GPUBufferUsage.STORAGE | GPUBufferUsage.VERTEX | GPUBufferUsage.COPY_DST});
        output = {buffer, state: null};
        borderOutputs.set(outputKey, output);
        output.binding = device.createBindGroup({layout: borderPipeline.getBindGroupLayout(1), entries: [
          {binding: 0, resource: {buffer: source.buffer, size: bytes.length}},
          {binding: 1, resource: {buffer, offset: storageOffset, size: storageSize}}]});
        if (fillCount) encoder.copyBufferToBuffer(resources.vertex, 0, buffer, 0, fillCount * 40);
      }
      outputs.set(batch, output.buffer);
      if (output.state === state) continue;
      const cameraKey = bits.join(",");
      let camera = cameras.get(cameraKey);
      if (!camera) {
        camera = makeBuffer(packed, GPUBufferUsage.UNIFORM);
        cameras.set(cameraKey, camera); temporary.push(camera);
      }
      const compute = encoder.beginComputePass();
      compute.setPipeline(borderPipeline);
      compute.setBindGroup(1, output.binding);
      for (let offset = 0; offset < count; offset += maxDispatch) {
        const chunk = Math.min(maxDispatch, count - offset);
        const data = new ArrayBuffer(32), view = new DataView(data);
        view.setUint32(0, offset, true); view.setUint32(4, chunk, true);
        view.setUint32(8, fillCount - storageOffset / 40 + capacity * offset, true);
        view.setFloat32(12, .0001, true);
        view.setUint32(16, capacity, true);
        const params = makeBuffer(data, GPUBufferUsage.UNIFORM); temporary.push(params);
        compute.setBindGroup(0, device.createBindGroup({layout: borderPipeline.getBindGroupLayout(0), entries: [
          {binding: 0, resource: {buffer: camera, size: 192}},
          {binding: 1, resource: {buffer: params, size: 32}}]}));
        compute.dispatchWorkgroups(chunk);
      }
      compute.end();
      completed.push([output, state]);
    }
    return {outputs, usedSources, usedOutputs, completed};
  }

  function validatePaint(bytes) {
    if (bytes.byteLength < 96 || bytes.byteLength > (24 + 8 * 4096) * 4 || bytes.byteLength % 4) {
      throw new Error("invalid paint coefficient length");
    }
    // Packet JSON can leave the binary payload unaligned. DataView also makes
    // the wire's little-endian representation explicit on every platform.
    const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
    for (let offset = 0; offset < bytes.byteLength; offset += 4) {
      if (!Number.isFinite(view.getFloat32(offset, true))) {
        throw new Error("paint coefficients must be finite");
      }
    }
    const count = view.getFloat32(28, true), mode = view.getFloat32(44, true);
    if (view.getFloat32(12, true) <= 0 || !Number.isInteger(count)
        || count < 0 || count > 4096 || bytes.byteLength !== (24 + 8 * count) * 4
        || (mode !== 0 && mode !== 1) || (mode === 1 && count === 0)) {
      throw new Error("invalid paint coefficient layout, scale, node count or mode");
    }
    return bytes;
  }

  function paintHashKey(hash) {
    if (typeof hash !== "string" || !/^[0-9a-f]{32}$/.test(hash)) {
      throw new Error("invalid paint hash");
    }
    return "hash:" + hash;
  }

  function preparePaints(header, payload) {
    const definitions = new Map();
    const records = "paint_data" in header ? header.paint_data : {};
    if (records === null || typeof records !== "object" || Array.isArray(records)) {
      throw new Error("paint definitions must be an object");
    }
    for (const [hash, ref] of Object.entries(records)) {
      const key = paintHashKey(hash);
      if (ref === null || typeof ref !== "object" || Array.isArray(ref)) {
        throw new Error("invalid paint definition span");
      }
      const {offset, nbytes} = ref;
      if (!Number.isSafeInteger(offset) || !Number.isSafeInteger(nbytes)
          || offset < 0 || nbytes < 0 || offset > payload.byteLength
          || nbytes > payload.byteLength - offset) {
        throw new Error("paint definition extends beyond payload");
      }
      const bytes = validatePaint(payload.slice(offset, offset + nbytes));
      const previous = generatedPaints.get(key);
      if (previous && (previous.bytes.length !== bytes.length
          || previous.bytes.some((value, i) => value !== bytes[i]))) {
        throw new Error("paint hash redefined with different coefficients");
      }
      definitions.set(key, bytes);
    }
    const keys = new Map();
    for (const batch of header.batches) {
      if (batch.pipeline !== "paint" && batch.pipeline !== "paint_depth") continue;
      let key;
      if ("paint_hash" in batch) {
        key = paintHashKey(batch.paint_hash);
        if (!generatedPaints.has(key) && !definitions.has(key)) {
          cacheMissed = true;
          keys.set(batch, null);
          continue;
        }
      } else if ((header.format_version ?? 3) < 4 && "paint" in batch) {
        if (!Array.isArray(batch.paint) || batch.paint.some(value => typeof value !== "number")) {
          throw new Error("inline paint coefficients must be a numeric array");
        }
        const packed = new Float32Array(batch.paint);
        const bytes = validatePaint(new Uint8Array(packed.buffer));
        key = "inline:" + new Uint32Array(packed.buffer).join(",");
        definitions.set(key, bytes);
      } else {
        throw new Error("paint operation requires a paint hash");
      }
      keys.set(batch, key);
    }
    for (const key of new Set(keys.values())) {
      if (key !== null && !generatedPaints.has(key)) {
        const bytes = definitions.get(key);
        const buffer = makeBuffer(bytes, GPUBufferUsage.STORAGE);
        generatedPaints.set(key, {buffer, bytes, buffers: [buffer]});
      }
    }
    return keys;
  }

  function encodeGenerated(pass, header, batch, vertexBytes, samples, supersample, paintKeys, borderBuffers, depthOnly = false) {
    const name = "generated_" + batch.pipeline + (depthOnly ? "_depth_only" : batch.coverage ? "_coverage" : "");
    if (batch.kind !== "generated" || !(name in PIPELINE_SPECS)) {
      throw new Error("unsupported generated pipeline " + batch.pipeline);
    }
    if (borderBuffers.get(batch) === null) return;
    const painted = batch.pipeline === "paint" || batch.pipeline === "paint_depth";
    const paintKey = paintKeys.get(batch);
    if (painted && paintKey === null) return;  // Request resend; never reuse another material.
    const res = generatedResources(batch, vertexBytes);
    if (!res) return;
    const pipeline = getPipeline(name, samples);
    let textureBinding = null;
    if (batch.textures) {
      textureBinding = generatedTextureBinding(name, samples, pipeline, batch);
      if (!textureBinding) return;
    }
    pass.setPipeline(pipeline);
    const uniforms = { ...header.camera, ...batch.uniforms };
    uniforms.pixel_size = (uniforms.pixel_size ?? 1) / supersample;
    uniforms.anti_alias_width = (uniforms.anti_alias_width ?? 1.5) * supersample;
    pass.setBindGroup(0, generatedUniformBinding(name, samples, pipeline, uniforms));
    if (painted) {
      const key = name + "@" + samples + ":" + paintKey;
      usedGeneratedPaintBindings.add(key);
      let binding = generatedPaintBindings.get(key);
      if (!binding) {
        binding = device.createBindGroup({
          layout: pipeline.getBindGroupLayout(1),
          entries: [{ binding: 0, resource: { buffer: generatedPaints.get(paintKey).buffer } }],
        });
        generatedPaintBindings.set(key, binding);
      }
      pass.setBindGroup(1, binding);
    }
    if (textureBinding) pass.setBindGroup(1, textureBinding);
    pass.setVertexBuffer(0, borderBuffers.get(batch) || res.vertex);
    if (batch.indexed) {
      pass.setIndexBuffer(res.index || runIndexBuffer(batch, res), "uint32");
      pass.drawIndexed(batch.count, batch.instances);
    } else {
      pass.draw(batch.count, batch.instances);
    }
  }

  function retireGeneratedResources(textureHashes) {
    for (const buffer of staleIndexBuffers) buffer.destroy();
    staleIndexBuffers = [];
    for (const [cache, used] of [
      [generatedGeometry, usedGeneratedGeometry],
      [generatedUniforms, usedGeneratedUniforms],
      [generatedPaints, usedGeneratedPaints],
    ]) {
      for (const [key, res] of cache) {
        if (!used.has(key)) {
          for (const buffer of res.buffers) buffer.destroy();
          cache.delete(key);
        }
      }
    }
    for (const key of generatedPaintBindings.keys()) {
      if (!usedGeneratedPaintBindings.has(key)) generatedPaintBindings.delete(key);
    }
    for (const key of generatedTextures.keys()) {
      if (!usedGeneratedTextures.has(key)) generatedTextures.delete(key);
    }
    for (const [key, texture] of textureCache) {
      if (!textureHashes.has(key)) { texture.destroy(); textureCache.delete(key); }
    }
  }

  function render(arrayBuffer) {
    if (closing || !device) return Promise.reject(new Error("renderer is not active"));
    // Texture decoding yields to the event loop. Serialize complete frames so
    // a later resize or cache retirement cannot replace an earlier frame's
    // targets/resources before it submits, or present frames out of order.
    const rendered = renderQueue.then(() => renderFrame(arrayBuffer));
    renderQueue = rendered.catch(() => {});
    return rendered;
  }

  async function renderFrame(arrayBuffer) {
    const bytes = new Uint8Array(arrayBuffer);
    const headerLen = new DataView(arrayBuffer, 1, 4).getUint32(0, true);
    const header = JSON.parse(
      new TextDecoder().decode(bytes.subarray(5, 5 + headerLen)));
    const vertexBytes = bytes.subarray(5 + headerLen);

    const [width, height] = header.resolution;
    if (header.renderer !== "triangles") {
      throw new Error("browser renderer requires generated triangle geometry");
    }
    const samples = header.samples;
    if (samples !== 1 && samples !== 4) {
      throw new Error("generated sample count must be 1 or 4");
    }
    const supersample = header.supersample ?? 2;
    if (supersample !== 1 && supersample !== 2) {
      throw new Error("generated supersample factor must be 1 or 2");
    }
    ensureTargets(width * supersample, height * supersample, samples, width, height);
    cacheMissed = false;

    const previousPaints = new Set(generatedPaints.keys());
    const previousPaintBindings = new Set(generatedPaintBindings.keys());
    const previousSources = new Set(borderSources.keys()), previousOutputs = new Set(borderOutputs.keys());
    const previousGeometry = new Set(generatedGeometry.keys()), previousUniforms = new Set(generatedUniforms.keys());
    const temporary = [];
    let borders;
    let submitted = false;
    try {
      const paintKeys = preparePaints(header, vertexBytes);
      for (const [texHash, ref] of Object.entries(header.texture_data || {})) {
        if (textureCache.has(texHash)) continue;
        const blob = new Blob([vertexBytes.subarray(
          ref.offset, ref.offset + ref.nbytes)]);
        const bitmap = await createImageBitmap(blob);
        const texture = device.createTexture({
          size: [bitmap.width, bitmap.height], format: "rgba8unorm",
          usage: GPUTextureUsage.TEXTURE_BINDING | GPUTextureUsage.COPY_DST
            | GPUTextureUsage.RENDER_ATTACHMENT });
        device.queue.copyExternalImageToTexture(
          { source: bitmap }, { texture }, [bitmap.width, bitmap.height]);
        bitmap.close();
        textureCache.set(texHash, texture);
      }

      usedGeneratedGeometry = new Set();
      usedGeneratedUniforms = new Set();
      usedGeneratedTextures = new Set();
      usedGeneratedPaints = new Set(paintKeys.values());
      usedGeneratedPaintBindings = new Set();
      const encoder = device.createCommandEncoder();
      borders = prepareBorders(header, vertexBytes, encoder, temporary);
      const [r, g, b, a] = header.background;
      let pass = outPass(encoder, [r * a, g * a, b * a, a]);
      let coverageRef = 0;
      for (const batch of header.batches) {
        if (batch.coverage) {
          if (coverageRef === 255) {
            pass.end();
            pass = outPass(encoder, null, true);
            coverageRef = 0;
          }
          pass.setStencilReference(++coverageRef);
        }
        encodeGenerated(pass, header, batch, vertexBytes, samples, supersample, paintKeys, borders.outputs);
        if (batch.coverage && batch.pipeline.endsWith("_depth")) {
          encodeGenerated(pass, header, batch, vertexBytes, samples, supersample, paintKeys, borders.outputs, true);
        }
      }
      pass.end();

      // Present: blit the (resolved) scene target onto the canvas
      const blitPass = encoder.beginRenderPass({ colorAttachments: [{
        view: context.getCurrentTexture().createView(),
        loadOp: "clear", storeOp: "store",
        clearValue: { r: 0, g: 0, b: 0, a: 1 },
      }] });
      // The exact box resolve is also the presentation pass. Native rendering
      // uses this same shader with an rgba8 output texture for file readback.
      const presentPipeline = supersample === 2 ? resolve2Pipeline : blitPipeline;
      blitPass.setPipeline(presentPipeline);
      const entries = [{ binding: 0, resource: (resolveView || outView) }];
      if (supersample === 1) entries.push({ binding: 1, resource: sampler });
      blitPass.setBindGroup(0, device.createBindGroup({
        layout: presentPipeline.getBindGroupLayout(0), entries,
      }));
      blitPass.draw(3);
      blitPass.end();

      device.queue.submit([encoder.finish()]);
      submitted = true;
      for (const [output, state] of borders.completed) output.state = state;
    } finally {
      if (!submitted) {
        for (const key of generatedPaintBindings.keys()) {
          if (!previousPaintBindings.has(key)) generatedPaintBindings.delete(key);
        }
        for (const [key, material] of generatedPaints) {
          if (!previousPaints.has(key)) {
            material.buffer.destroy();
            generatedPaints.delete(key);
          }
        }
        for (const [key, output] of borderOutputs) {
          if (!previousOutputs.has(key)) { output.buffer.destroy(); borderOutputs.delete(key); }
        }
        for (const [key, source] of borderSources) {
          if (!previousSources.has(key)) { source.buffer.destroy(); borderSources.delete(key); }
        }
        for (const [cache, previous] of [[generatedGeometry, previousGeometry], [generatedUniforms, previousUniforms]]) {
          for (const [key, resource] of cache) {
            if (!previous.has(key)) {
              for (const buffer of resource.buffers) buffer.destroy();
              cache.delete(key);
            }
          }
        }
      }
      for (const buffer of temporary) buffer.destroy();
    }
    for (const [key, output] of borderOutputs) {
      if (!borders.usedOutputs.has(key)) { output.buffer.destroy(); borderOutputs.delete(key); }
    }
    for (const [key, source] of borderSources) {
      if (!borders.usedSources.has(key)) { source.buffer.destroy(); borderSources.delete(key); }
    }
    // The sender also retains only current-frame geometry. Do not enforce an
    // LRU bound here: even the first draw in a large frame is live until submit.
    retireGeneratedResources(new Set(header.batches.flatMap(
      batch => Object.values(batch.textures || {}))));
    if (cacheMissed && ManimlWGPU.onCacheMiss) ManimlWGPU.onCacheMiss();
    return header;
  }

  function destroy() {
    if (teardown) return teardown;
    closing = true;
    teardown = (async () => {
      await renderQueue;
      if (!device) return;
      try { await device.queue.onSubmittedWorkDone(); }
      finally {
        for (const cache of [generatedGeometry, generatedUniforms, generatedPaints]) {
          for (const res of cache.values()) for (const buffer of res.buffers) buffer.destroy();
          cache.clear();
        }
        generatedTextures.clear();
        generatedPaintBindings.clear();
        for (const cache of [borderOutputs, borderSources]) {
          for (const resource of cache.values()) resource.buffer.destroy();
          cache.clear();
        }
        for (const buffer of staleIndexBuffers) buffer.destroy();
        staleIndexBuffers = [];
        borderPipeline = null;
        for (const texture of textureCache.values()) texture.destroy();
        textureCache.clear();
        for (const texture of [outTexture, resolveTexture, depthTexture]) {
          if (texture) texture.destroy();
        }
        context.unconfigure();
        device.destroy();
        device = canvas = context = null;
        outTexture = resolveTexture = depthTexture = null;
        outView = resolveView = depthView = targetKey = null;
        modules = {}; pipelines.clear();
        blitPipeline = resolve2Pipeline = sampler = null;
        renderQueue = Promise.resolve();
      }
    })();
    return teardown;
  }

  return { init, render, destroy, onCacheMiss: null };
})();

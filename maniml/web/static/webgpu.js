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
    paint: ["common.wgsl", "paint.wgsl"],
    dot: ["common.wgsl", "dot.wgsl"],
    image: ["common.wgsl", "image.wgsl"],
    texsurface: ["common.wgsl", "texsurface.wgsl"],
    blit: ["blit.wgsl"],
    resolve2: ["resolve2.wgsl"],
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
    const size = Math.ceil(bytes.byteLength / 4) * 4;
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

  function generatedResources(batch, vertexBytes) {
    usedGeneratedGeometry.add(batch.hash);
    let res = generatedGeometry.get(batch.hash);
    if (res) return res;
    if (batch.cached) { cacheMissed = true; return null; }
    const vertex = makeBuffer(vertexBytes.subarray(
      batch.offset, batch.offset + batch.num_verts * batch.stride), GPUBufferUsage.VERTEX);
    const buffers = [vertex];
    let index = null;
    if (batch.indexed) {
      index = makeBuffer(vertexBytes.subarray(
        batch.index_offset, batch.index_offset + batch.index_count * 4), GPUBufferUsage.INDEX);
      buffers.push(index);
    }
    res = { vertex, index, buffers };
    generatedGeometry.set(batch.hash, res);
    return res;
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

  function encodeGenerated(pass, header, batch, vertexBytes, samples, supersample, paintKeys, depthOnly = false) {
    const name = "generated_" + batch.pipeline + (depthOnly ? "_depth_only" : batch.coverage ? "_coverage" : "");
    if (batch.kind !== "generated" || !(name in PIPELINE_SPECS)) {
      throw new Error("unsupported generated pipeline " + batch.pipeline);
    }
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
    pass.setVertexBuffer(0, res.vertex);
    if (batch.indexed) {
      pass.setIndexBuffer(res.index, "uint32");
      pass.drawIndexed(batch.count, batch.instances);
    } else {
      pass.draw(batch.count, batch.instances);
    }
  }

  function retireGeneratedResources(textureHashes) {
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
        encodeGenerated(pass, header, batch, vertexBytes, samples, supersample, paintKeys);
        if (batch.coverage && batch.pipeline.endsWith("_depth")) {
          encodeGenerated(pass, header, batch, vertexBytes, samples, supersample, paintKeys, true);
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
      }
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

// Original browser winding renderer retained for viewer dogfooding.
// WebGPU browser driver — the JS mirror of maniml/web/wgpu_renderer.py.
// Same WGSL (fetched from wgsl/), same pipeline specs, same pass
// structure; keep the two in sync. Presents via a blit pass because
// the canvas swapchain format is platform-preferred (bgra8unorm on
// macOS) while the scene target stays rgba8unorm like the reference.
"use strict";

const ManimlWindingWGPU = (() => {
  const VERTEX_STRIDE = 68;
  const INSTANCE_STRIDE = 3 * VERTEX_STRIDE;
  const UNIFORM_FLOATS = 48;  // must match UNIFORM_FIELDS / struct Uniforms
  const DEPTH_FORMAT = "depth24plus";

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

  const FILL_LAYOUT = layout(INSTANCE_STRIDE, "instance", [
    attr("float32x3", 0, 0), attr("float32x3", 68, 1),
    attr("float32x3", 136, 2),
    attr("float32x4", 36, 3), attr("float32x4", 104, 4),
    attr("float32x4", 172, 5),
    attr("float32x3", 52, 6), attr("float32x3", 120, 7),
  ]);
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
  const BORDER_LAYOUT = layout(INSTANCE_STRIDE, "instance", [
    attr("float32x3", 0, 0), attr("float32x3", 68, 1),
    attr("float32x3", 136, 2),
    attr("float32x4", 36, 3), attr("float32x4", 104, 4),
    attr("float32x4", 172, 5),
    attr("float32", 64, 6), attr("float32", 132, 7),
    attr("float32", 200, 8),
    attr("float32", 32, 9), attr("float32", 168, 10),
    attr("float32x3", 120, 11),
  ]);
  const COMPOSITE_LAYOUT = layout(8, "vertex", [attr("float32x2", 0, 0)]);
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

  const ALPHA_BLEND = {
    color: { srcFactor: "src-alpha", dstFactor: "one-minus-src-alpha",
             operation: "add" },
    alpha: { srcFactor: "src-alpha", dstFactor: "one-minus-src-alpha",
             operation: "add" },
  };
  const FILL_ACCUMULATE_BLEND = {
    color: { srcFactor: "src-alpha", dstFactor: "one-minus-src-alpha",
             operation: "add" },
    alpha: { srcFactor: "one-minus-dst-alpha", dstFactor: "one",
             operation: "add" },
  };
  const MAX_BLEND = {
    color: { srcFactor: "one", dstFactor: "one", operation: "max" },
    alpha: { srcFactor: "one", dstFactor: "one", operation: "max" },
  };
  const COMPOSITE_BLEND = {
    color: { srcFactor: "one", dstFactor: "one-minus-src-alpha",
             operation: "add" },
    alpha: { srcFactor: "one", dstFactor: "one-minus-src-alpha",
             operation: "add" },
  };

  // name -> [module, layout, topology, target, blend, depthTest]
  const PIPELINE_SPECS = {
    fill: ["fill", FILL_LAYOUT, "triangle-list", "fill",
           FILL_ACCUMULATE_BLEND, false],
    border: ["stroke", BORDER_LAYOUT, "triangle-strip", "fill",
             MAX_BLEND, false],
    composite: ["composite", COMPOSITE_LAYOUT, "triangle-strip", "out",
                COMPOSITE_BLEND, false],
    stroke: ["stroke", STROKE_LAYOUT, "triangle-strip", "out",
             ALPHA_BLEND, false],
    stroke_depth: ["stroke", STROKE_LAYOUT, "triangle-strip", "out",
                   ALPHA_BLEND, true],
    surface: ["surface", SURFACE_LAYOUT, "triangle-list", "out",
              ALPHA_BLEND, false],
    surface_depth: ["surface", SURFACE_LAYOUT, "triangle-list", "out",
                    ALPHA_BLEND, true],
    dot: ["dot", DOT_LAYOUT, "triangle-strip", "out", ALPHA_BLEND, false],
    dot_depth: ["dot", DOT_LAYOUT, "triangle-strip", "out",
                ALPHA_BLEND, true],
    image: ["image", IMAGE_LAYOUT, "triangle-list", "out",
            ALPHA_BLEND, false],
    image_depth: ["image", IMAGE_LAYOUT, "triangle-list", "out",
                  ALPHA_BLEND, true],
    texsurface: ["texsurface", TEXSURFACE_LAYOUT, "triangle-list", "out",
                 ALPHA_BLEND, false],
    texsurface_depth: ["texsurface", TEXSURFACE_LAYOUT, "triangle-list",
                       "out", ALPHA_BLEND, true],
  };
  // Generated geometry draws directly into one premultiplied scene target.
  // Keep the legacy shaders/layouts, with separate output and blend state.
  for (const base of ["stroke", "surface", "dot", "image", "texsurface"]) {
    for (const suffix of ["", "_depth"]) {
      const name = base + suffix;
      const [module, buffers, topology, target, , depth] = PIPELINE_SPECS[name];
      PIPELINE_SPECS["generated_" + name] =
        [module, buffers, topology, target, COMPOSITE_BLEND, depth];
    }
  }

  const MODULE_SOURCES = {
    fill: ["common.wgsl", "fill.wgsl"],
    stroke: ["common.wgsl", "stroke.wgsl"],
    composite: ["composite.wgsl"],
    surface: ["common.wgsl", "surface.wgsl"],
    dot: ["common.wgsl", "dot.wgsl"],
    image: ["common.wgsl", "image.wgsl"],
    texsurface: ["common.wgsl", "texsurface.wgsl"],
    blit: ["blit.wgsl"],
  };

  let canvas = null, context = null, device = null, canvasFormat = null;
  let modules = {}, pipelines = new Map(), blitPipeline = null;
  let quadBuffer, sampler;
  let outTexture, resolveTexture, depthTexture;
  let outView, resolveView, depthView;
  let targetKey = null;
  const fillTargets = new Map();
  let usedFillTargets = new Set();
  const textureCache = new Map();
  const batchCache = new Map();
  const generatedGeometry = new Map();
  const generatedUniforms = new Map();
  const generatedTextures = new Map();
  let usedGeneratedGeometry = new Set();
  let usedGeneratedUniforms = new Set();
  let usedGeneratedTextures = new Set();
  const CACHE_MAX = 512;
  let cacheMissed = false;
  let frameBuffers = [];  // per-frame uniform buffers, destroyed post-submit
  let renderQueue = Promise.resolve();
  let closing = false;
  let teardown = null;

  async function fetchWgsl(names) {
    const parts = [];
    for (const name of names) {
      const resp = await fetch("winding_wgsl/" + name);
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
    quadBuffer = makeBuffer(
      new Float32Array([0, 0, 0, 1, 1, 0, 1, 1]).buffer, GPUBufferUsage.VERTEX);
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
    if (target === "fill") {
      descriptor.fragment = {
        module: modules[moduleKey], entryPoint: "fs_main",
        targets: [{ format: "rgba16float", blend }] };
    } else {
      descriptor.fragment = {
        module: modules[moduleKey], entryPoint: "fs_main",
        targets: [{ format: "rgba8unorm", blend }] };
      descriptor.depthStencil = {
        format: DEPTH_FORMAT,
        depthWriteEnabled: depthTest,
        depthCompare: depthTest ? "less" : "always",
      };
      descriptor.multisample = { count: samples };
    }
    const pipeline = device.createRenderPipeline(descriptor);
    pipelines.set(key, pipeline);
    return pipeline;
  }

  function ensureTargets(width, height, samples) {
    const key = width + "x" + height + "@" + samples;
    if (targetKey === key) return;
    targetKey = key;
    canvas.width = width;
    canvas.height = height;
    for (const t of [outTexture, resolveTexture, depthTexture]) {
      if (t) t.destroy();
    }
    for (const target of fillTargets.values()) target.texture.destroy();
    fillTargets.clear();
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

  function fillRect(batch, width, height) {
    const rect = batch.fill_rect;
    if (!Array.isArray(rect) || rect.length !== 4
        || !rect.every(Number.isSafeInteger)) return [0, 0, width, height];
    const [x, y, w, h] = rect;
    if (x < 0 || y < 0 || w < 0 || h < 0
        || x + w > width || y + h > height) return [0, 0, width, height];
    return w === 0 || h === 0 ? null : rect;
  }

  function fillTarget(width, height, outputWidth, outputHeight) {
    // Keep the original 2x sampling grid, while sharing small scratch
    // allocations among batches whose bounds fit the same bucket.
    const bucketWidth = Math.min(2 * outputWidth,
      2 ** Math.ceil(Math.log2(width)));
    const bucketHeight = Math.min(2 * outputHeight,
      2 ** Math.ceil(Math.log2(height)));
    const key = bucketWidth + "x" + bucketHeight;
    usedFillTargets.add(key);
    let target = fillTargets.get(key);
    if (!target) {
      const texture = device.createTexture({
        size: [bucketWidth, bucketHeight], format: "rgba16float",
        usage: GPUTextureUsage.RENDER_ATTACHMENT | GPUTextureUsage.TEXTURE_BINDING });
      target = { texture, view: texture.createView(),
                 width: bucketWidth, height: bucketHeight };
      fillTargets.set(key, target);
    }
    return target;
  }

  function outPass(encoder, clearColor) {
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

  function uniformBindGroup(pipeline, uniforms, borderMode = 0) {
    const buffer = makeBuffer(packUniforms(uniforms, borderMode),
                              GPUBufferUsage.UNIFORM);
    frameBuffers.push(buffer);
    return device.createBindGroup({
      layout: pipeline.getBindGroupLayout(0),
      entries: [{ binding: 0, resource: { buffer } }],
    });
  }

  function getResources(batch, builder) {
    let res = batchCache.get(batch.hash);
    if (res) {
      batchCache.delete(batch.hash);
      batchCache.set(batch.hash, res);
      return res;
    }
    if (batch.cached) { cacheMissed = true; return null; }
    res = builder();
    batchCache.set(batch.hash, res);
    while (batchCache.size > CACHE_MAX) {
      const [oldHash, old] = batchCache.entries().next().value;
      batchCache.delete(oldHash);
      for (const b of old.buffers) b.destroy();
    }
    return res;
  }

  function batchPipelineName(batch) {
    const base = { dotcloud: "dot", image: "image", surface: "surface",
                   texsurface: "texsurface" }[batch.kind];
    return base + (batch.depth_test ? "_depth" : "");
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

  function encodeGenerated(pass, header, batch, vertexBytes, samples) {
    const name = "generated_" + batch.pipeline;
    if (batch.kind !== "generated" || !(name in PIPELINE_SPECS)) {
      throw new Error("unsupported generated pipeline " + batch.pipeline);
    }
    const res = generatedResources(batch, vertexBytes);
    if (!res) return;
    const pipeline = getPipeline(name, samples);
    let textureBinding = null;
    if (batch.textures) {
      textureBinding = generatedTextureBinding(name, samples, pipeline, batch);
      if (!textureBinding) return;
    }
    pass.setPipeline(pipeline);
    pass.setBindGroup(0, generatedUniformBinding(name, samples, pipeline,
      { ...header.camera, ...batch.uniforms }));
    if (textureBinding) pass.setBindGroup(1, textureBinding);
    pass.setVertexBuffer(0, res.vertex);
    if (batch.indexed) {
      pass.setIndexBuffer(res.index, "uint32");
      pass.drawIndexed(batch.count, batch.instances);
    } else {
      pass.draw(batch.count, batch.instances);
    }
  }

  function retireGeneratedResources() {
    for (const [cache, used] of [
      [generatedGeometry, usedGeneratedGeometry],
      [generatedUniforms, usedGeneratedUniforms],
    ]) {
      for (const [key, res] of cache) {
        if (!used.has(key)) {
          for (const buffer of res.buffers) buffer.destroy();
          cache.delete(key);
        }
      }
    }
    for (const key of generatedTextures.keys()) {
      if (!usedGeneratedTextures.has(key)) generatedTextures.delete(key);
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
    const generated = header.renderer === "triangles";
    const samples = generated ? header.samples : (header.samples ? 4 : 1);
    if (generated && samples !== 1 && samples !== 4) {
      throw new Error("generated sample count must be 1 or 4");
    }
    ensureTargets(width, height, samples);
    cacheMissed = false;

    // Cached batches still name their textures. Payloads only carry newly
    // transmitted bytes, so they cannot determine the live texture set.
    const textureHashes = new Set(header.batches.flatMap(
      batch => Object.values(batch.textures || {})));
    const addedTextures = [];
    let submitted = false;
    try {
      for (const [texHash, ref] of Object.entries(header.texture_data || {})) {
        if (textureCache.has(texHash)) continue;
        const blob = new Blob([vertexBytes.subarray(
          ref.offset, ref.offset + ref.nbytes)]);
        const bitmap = await createImageBitmap(blob);
        try {
          const texture = device.createTexture({
            size: [bitmap.width, bitmap.height], format: "rgba8unorm",
            usage: GPUTextureUsage.TEXTURE_BINDING | GPUTextureUsage.COPY_DST
              | GPUTextureUsage.RENDER_ATTACHMENT });
          addedTextures.push(texHash);
          textureCache.set(texHash, texture);
          device.queue.copyExternalImageToTexture(
            { source: bitmap }, { texture }, [bitmap.width, bitmap.height]);
        } finally {
          bitmap.close();
        }
      }

      usedFillTargets = new Set();
      usedGeneratedGeometry = new Set();
      usedGeneratedUniforms = new Set();
      usedGeneratedTextures = new Set();
      const encoder = device.createCommandEncoder();
      if (generated) {
        const [r, g, b, a] = header.background;
        const pass = outPass(encoder, [r * a, g * a, b * a, a]);
        for (const batch of header.batches) {
          encodeGenerated(pass, header, batch, vertexBytes, samples);
        }
        pass.end();
      } else {
        outPass(encoder, header.background).end();
        for (const batch of header.batches) {
          if (batch.kind === "vmobject") {
            encodeVMobject(encoder, header, batch, vertexBytes, samples);
          } else {
            encodePlain(encoder, header, batch, vertexBytes, samples);
          }
        }
      }

      // Present: blit the (resolved) scene target onto the canvas
      const blitPass = encoder.beginRenderPass({ colorAttachments: [{
        view: context.getCurrentTexture().createView(),
        loadOp: "clear", storeOp: "store",
        clearValue: { r: 0, g: 0, b: 0, a: 1 },
      }] });
      blitPass.setPipeline(blitPipeline);
      blitPass.setBindGroup(0, device.createBindGroup({
        layout: blitPipeline.getBindGroupLayout(0),
        entries: [
          { binding: 0, resource: (resolveView || outView) },
          { binding: 1, resource: sampler },
        ],
      }));
      blitPass.draw(3);
      blitPass.end();

      device.queue.submit([encoder.finish()]);
      submitted = true;
    } finally {
      if (!submitted) {
        // A failed frame must not evict the last submitted frame's textures,
        // or retain uploads that no submitted frame has ever referenced.
        for (const hash of addedTextures) {
          textureCache.get(hash).destroy();
          textureCache.delete(hash);
        }
        // Bind groups made while encoding may refer to rolled-back uploads.
        if (addedTextures.length) generatedTextures.clear();
      }
    }
    // The sender also retains only current-frame geometry. Do not enforce an
    // LRU bound here: even the first draw in a large frame is live until submit.
    retireGeneratedResources();
    for (const [hash, texture] of textureCache) {
      if (!textureHashes.has(hash)) {
        texture.destroy();
        textureCache.delete(hash);
      }
    }
    // Never destroy a target while this frame's unsubmitted commands
    // may still refer to it. Retain only buckets used by the new frame.
    for (const [key, target] of fillTargets) {
      if (!usedFillTargets.has(key)) {
        target.texture.destroy();
        fillTargets.delete(key);
      }
    }
    for (const b of frameBuffers) b.destroy();
    frameBuffers = [];
    if (cacheMissed && ManimlWindingWGPU.onCacheMiss) ManimlWindingWGPU.onCacheMiss();
    return header;
  }

  function encodePlain(encoder, header, batch, vertexBytes, samples) {
    const name = batchPipelineName(batch);
    const pipeline = getPipeline(name, samples);
    const uniforms = { ...header.camera, ...batch.uniforms };
    const res = getResources(batch, () => ({
      buffers: [makeBuffer(vertexBytes.subarray(
        batch.offset, batch.offset + batch.num_verts * batch.stride),
        GPUBufferUsage.VERTEX)],
    }));
    if (!res) return;

    const pass = outPass(encoder);
    pass.setPipeline(pipeline);
    pass.setBindGroup(0, uniformBindGroup(pipeline, uniforms));
    if (batch.textures) {
      const hashes = Object.values(batch.textures);
      const views = hashes.map((h) => {
        const t = textureCache.get(h);
        return t ? t.createView() : null;
      });
      if (views.some((v) => !v)) { cacheMissed = true; pass.end(); return; }
      if (views.length === 1 && batch.kind === "texsurface") {
        views.push(views[0]);  // DarkTexture falls back to light
      }
      const entries = views.map((v, i) => ({ binding: i, resource: v }));
      entries.push({ binding: views.length, resource: sampler });
      pass.setBindGroup(1, device.createBindGroup({
        layout: pipeline.getBindGroupLayout(1), entries }));
    }
    pass.setVertexBuffer(0, res.buffers[0]);
    if (batch.kind === "dotcloud") pass.draw(4, batch.num_verts);
    else pass.draw(batch.num_verts);
    pass.end();
  }

  function encodeVMobject(encoder, header, batch, vertexBytes, samples) {
    const uniforms = { ...header.camera, ...batch.uniforms };
    const instances = batch.num_verts / 3;
    const strokeVerts = batch.stroke_verts || 64;
    const depth = !!batch.depth_test;

    const res = getResources(batch, () => {
      const out = { buffers: [makeBuffer(vertexBytes.subarray(
        batch.offset, batch.offset + batch.num_verts * VERTEX_STRIDE),
        GPUBufferUsage.VERTEX)] };
      const tri = batch.tri;
      if (tri) {
        out.triVbo = makeBuffer(vertexBytes.subarray(
          tri.voffset, tri.voffset + tri.vcount * 40),
          GPUBufferUsage.VERTEX);
        out.triIbo = makeBuffer(vertexBytes.subarray(
          tri.ioffset, tri.ioffset + tri.icount * 4),
          GPUBufferUsage.INDEX);
        out.triCount = tri.icount;
        out.buffers.push(out.triVbo, out.triIbo);
      }
      return out;
    });
    if (!res) return;
    const buffer = res.buffers[0];

    const drawWindingFill = () => {
      const [width, height] = header.resolution;
      const rect = fillRect(batch, width, height);
      if (rect === null) return;
      const [x, y, w, h] = rect;
      const target = fillTarget(2 * w, 2 * h, width, height);
      const fillUniforms = { ...uniforms, clip_transform: [
        width / w, height / h,
        (width - 2 * x - w) / w, (2 * y + h - height) / h,
      ] };
      const fillPipeline = getPipeline("fill", 1);
      const borderPipeline = getPipeline("border", 1);
      const fillPass = encoder.beginRenderPass({ colorAttachments: [{
        view: target.view, loadOp: "clear", storeOp: "store",
        clearValue: { r: 0, g: 0, b: 0, a: 0 },
      }] });
      fillPass.setViewport(0, 0, 2 * w, 2 * h, 0, 1);
      fillPass.setPipeline(fillPipeline);
      fillPass.setBindGroup(0, uniformBindGroup(fillPipeline, fillUniforms));
      fillPass.setVertexBuffer(0, buffer);
      fillPass.draw(6, instances);
      fillPass.setPipeline(borderPipeline);
      fillPass.setBindGroup(0, uniformBindGroup(borderPipeline, fillUniforms, 1));
      fillPass.setVertexBuffer(0, buffer);
      fillPass.draw(strokeVerts, instances);
      fillPass.end();

      const compositePipeline = getPipeline("composite", samples);
      const uvScale = makeBuffer(new Float32Array([
        2 * w / target.width, 2 * h / target.height, 0, 0,
      ]).buffer, GPUBufferUsage.UNIFORM);
      frameBuffers.push(uvScale);
      const pass = outPass(encoder);
      pass.setViewport(x, y, w, h, 0, 1);
      pass.setScissorRect(x, y, w, h);
      pass.setPipeline(compositePipeline);
      pass.setBindGroup(0, device.createBindGroup({
        layout: compositePipeline.getBindGroupLayout(0),
        entries: [
          { binding: 0, resource: target.view },
          { binding: 1, resource: sampler },
          { binding: 2, resource: { buffer: uvScale } },
        ],
      }));
      pass.setVertexBuffer(0, quadBuffer);
      pass.draw(4);
      pass.end();
    };

    const drawTriangulatedFill = () => {
      if (!res.triVbo) return;
      const pipeline = getPipeline("surface_depth", samples);
      const pass = outPass(encoder);
      pass.setPipeline(pipeline);
      pass.setBindGroup(0, uniformBindGroup(pipeline, uniforms));
      pass.setVertexBuffer(0, res.triVbo);
      pass.setIndexBuffer(res.triIbo, "uint32");
      pass.drawIndexed(res.triCount);
      pass.end();
    };

    const drawFill = () => {
      if (batch.fill_mode === "triangulated") drawTriangulatedFill();
      else drawWindingFill();
    };

    const drawStroke = () => {
      const pipeline = getPipeline(depth ? "stroke_depth" : "stroke", samples);
      const pass = outPass(encoder);
      pass.setPipeline(pipeline);
      pass.setBindGroup(0, uniformBindGroup(pipeline, uniforms));
      pass.setVertexBuffer(0, buffer);
      pass.draw(strokeVerts, instances);
      pass.end();
    };

    if (batch.stroke_behind) { drawStroke(); drawFill(); }
    else { drawFill(); drawStroke(); }
  }

  function destroy() {
    if (teardown) return teardown;
    closing = true;
    teardown = (async () => {
      await renderQueue;
      if (!device) return;
      try { await device.queue.onSubmittedWorkDone(); }
      finally {
        for (const cache of [batchCache, generatedGeometry, generatedUniforms]) {
          for (const res of cache.values()) for (const buffer of res.buffers) buffer.destroy();
          cache.clear();
        }
        for (const buffer of frameBuffers) buffer.destroy();
        frameBuffers = [];
        generatedTextures.clear();
        for (const texture of textureCache.values()) texture.destroy();
        textureCache.clear();
        for (const target of fillTargets.values()) target.texture.destroy();
        fillTargets.clear();
        for (const texture of [outTexture, resolveTexture, depthTexture]) {
          if (texture) texture.destroy();
        }
        if (quadBuffer) quadBuffer.destroy();
        context.unconfigure();
        device.destroy();
        device = canvas = context = null;
        outTexture = resolveTexture = depthTexture = null;
        outView = resolveView = depthView = targetKey = null;
        modules = {}; pipelines.clear();
        blitPipeline = quadBuffer = sampler = null;
        renderQueue = Promise.resolve();
      }
    })();
    return teardown;
  }

  return { init, render, destroy, onCacheMiss: null };
})();

// WebGPU browser driver — the JS mirror of maniml/web/wgpu_renderer.py.
// Same WGSL (fetched from wgsl/), same pipeline specs, same pass
// structure; keep the two in sync. Presents via a blit pass because
// the canvas swapchain format is platform-preferred (bgra8unorm on
// macOS) while the scene target stays rgba8unorm like the reference.
"use strict";

const ManimlWGPU = (() => {
  const VERTEX_STRIDE = 68;
  const INSTANCE_STRIDE = 3 * VERTEX_STRIDE;
  const UNIFORM_FLOATS = 44;  // must match UNIFORM_FIELDS / struct Uniforms
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
    ["_pad0", 1, 0], ["_pad1", 1, 0],
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
  let outTexture, resolveTexture, depthTexture, fillTexture;
  let outView, resolveView, depthView, fillView;
  let targetKey = null;
  const textureCache = new Map();
  const batchCache = new Map();
  const CACHE_MAX = 512;
  let cacheMissed = false;
  let frameBuffers = [];  // per-frame uniform buffers, destroyed post-submit

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
    for (const t of [outTexture, resolveTexture, depthTexture, fillTexture]) {
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
    fillTexture = device.createTexture({
      size: [2 * width, 2 * height], format: "rgba16float",
      usage: attach | GPUTextureUsage.TEXTURE_BINDING });
    fillView = fillTexture.createView();
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

  async function render(arrayBuffer) {
    const bytes = new Uint8Array(arrayBuffer);
    const headerLen = new DataView(arrayBuffer, 1, 4).getUint32(0, true);
    const header = JSON.parse(
      new TextDecoder().decode(bytes.subarray(5, 5 + headerLen)));
    const vertexBytes = bytes.subarray(5 + headerLen);

    const [width, height] = header.resolution;
    const samples = header.samples ? 4 : 1;
    ensureTargets(width, height, samples);
    cacheMissed = false;

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

    const encoder = device.createCommandEncoder();
    outPass(encoder, header.background).end();

    for (const batch of header.batches) {
      if (batch.kind === "vmobject") {
        encodeVMobject(encoder, header, batch, vertexBytes, samples);
      } else {
        encodePlain(encoder, header, batch, vertexBytes, samples);
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
    for (const b of frameBuffers) b.destroy();
    frameBuffers = [];
    if (cacheMissed && ManimlWGPU.onCacheMiss) ManimlWGPU.onCacheMiss();
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
      const fillPipeline = getPipeline("fill", 1);
      const borderPipeline = getPipeline("border", 1);
      const fillPass = encoder.beginRenderPass({ colorAttachments: [{
        view: fillView, loadOp: "clear", storeOp: "store",
        clearValue: { r: 0, g: 0, b: 0, a: 0 },
      }] });
      fillPass.setPipeline(fillPipeline);
      fillPass.setBindGroup(0, uniformBindGroup(fillPipeline, uniforms));
      fillPass.setVertexBuffer(0, buffer);
      fillPass.draw(6, instances);
      fillPass.setPipeline(borderPipeline);
      fillPass.setBindGroup(0, uniformBindGroup(borderPipeline, uniforms, 1));
      fillPass.setVertexBuffer(0, buffer);
      fillPass.draw(strokeVerts, instances);
      fillPass.end();

      const compositePipeline = getPipeline("composite", samples);
      const pass = outPass(encoder);
      pass.setPipeline(compositePipeline);
      pass.setBindGroup(0, device.createBindGroup({
        layout: compositePipeline.getBindGroupLayout(0),
        entries: [
          { binding: 0, resource: fillView },
          { binding: 1, resource: sampler },
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

  return { init, render, onCacheMiss: null };
})();

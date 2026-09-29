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
  // The patch fill (docs/phase_b1_plan.md): fan and patch triangles pulled
  // from storage, counted on the stencil, then covered; explicit layouts and
  // stencil states in patchPipeline. An object's border strips go through
  // the surface and paint pipelines with the strip stencil states.
  for (const depth of [false, true]) {
    PIPELINE_SPECS["generated_patch" + (depth ? "_depth" : "")] =
      ["patch_fill", [], "triangle-list", "out", PREMULTIPLIED_BLEND, depth];
  }
  for (const [name, spec] of Object.entries(PIPELINE_SPECS)) {
    if ((spec[0] === "surface" || spec[0] === "paint") && /(surface|paint|_depth)$/.test(name)) {
      PIPELINE_SPECS[name + "_strip_cover"] = spec;
      if (spec[0] === "surface") PIPELINE_SPECS[name + "_strip_mark"] = spec;
    }
  }
  const PATCH_STRIP_REFERENCE = 0x80, PATCH_COUNT_MASK = 0x7F, PATCH_VERTICES_PER_CURVE = 6;
  const STENCIL_STRIP_MARK = { compare: "always", failOp: "keep", depthFailOp: "keep", passOp: "replace" };
  const STENCIL_COVER = { compare: "not-equal", failOp: "keep", depthFailOp: "zero", passOp: "zero" };
  // Surface nets (docs/phase_b2_plan.md): steps per patch edge between the
  // construction's samples and the cap, output bounded per object.
  const MIN_NET_STEPS = 2, MAX_NET_STEPS = 32;

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
    patch_fill: ["common.wgsl", "paint_field.wgsl", "patch_fill.wgsl"],
    net_compute: ["net_compute.wgsl"],
    row_blend: ["row_blend.wgsl"],
    row_affine: ["row_affine.wgsl"],
    row_paint: ["row_paint.wgsl"],
    row_partial: ["row_partial.wgsl"],
    row_finalize: ["row_finalize.wgsl"],
  };

  let canvas = null, context = null, device = null, canvasFormat = null;
  let modules = {}, pipelines = new Map(), blitPipeline = null, resolve2Pipeline = null;
  let sampler;
  let outTexture, resolveTexture, depthTexture;
  let outView, resolveView, depthView;
  let targetKey = null;
  // The present pass's bind group per present pipeline, for the current targets.
  const presentBindings = new Map();
  // The retained frame (docs/phase_b4_plan.md, B4.7): the last submitted
  // frame's batches as an ordered list of slots, each resolved once to its
  // pipelines, bind groups and buffers. A full frame is diffed against it
  // (applyFull), so a batch that did not change keeps its slot and costs
  // its draws. serial numbers the frames tried; samples and format are what
  // the slots were resolved for; environment is the camera and supersample
  // every uniform set holds; message and header are the message the frame
  // was drawn from (the caller's buffer, handed over with render) and its
  // parse, kept while the frame drew every batch and the message is small
  // (a still frame's is its header), so the same message again is a redraw.
  // Under format 8 (B4.8) the frame is also a stream's: stream holds its
  // epoch, the number of the frame drawn and the header fields a delta
  // sends only when they change, and a delta is applied to the slots
  // (applyDelta) only when it was taken against that frame; resync is the
  // epoch a full frame was last asked for.
  const frame = { slots: [], serial: 0, samples: null, format: null, environment: null,
                  message: null, header: null, stream: null, resync: null };
  // Resources the slots share, each counted per holding slot (hold,
  // releaseSlot): geometry and its index patterns by hash, uniform sets by
  // their overrides, paint storage and its bindings, textures and theirs,
  // and the sources the compute stages read. A border, net or program
  // output belongs to one slot.
  const textureCache = new Map(), textureBindings = new Map(), looseTextures = new Set();
  const generatedGeometry = new Map(), indexPatterns = new Map();
  const uniformSets = new Map();
  const generatedPaints = new Map();  // paint identity -> immutable storage
  const paintBindings = new Map();
  const borderSources = new Map(), objectTables = new Map(), netSources = new Map();
  let borderPipeline = null, netPipeline = null;
  // Programs (docs/phase_b3_plan.md): row sources by content hash and the
  // kernels. An evaluated output (rows, and for VMobject rows the finalized
  // curve records and stroke instances) belongs to a slot; the slots whose
  // program is at the same state in a frame draw from one evaluation.
  const programSources = new Map(), programPipelines = new Map();
  // kind -> [sources, scalars on the wire]
  const ROW_FLOATS = 17, PROGRAM_KINDS = {blend: [2, 1], affine: [1, 16], paint: [1, 2], partial: [1, 5]};
  // Row sources (MANIML_PATCH_SOURCE=rows, docs/phase_b4_plan.md B5.1): a
  // patch or stroke batch names its objects' rows, which travel as program
  // sources; each rows is finalized once into curve records and stroke
  // instances (row_finalize.wgsl), shared by the slots that name it, and a
  // run of several objects copies its objects' into a buffer of its own.
  const ROW_BYTES = 4 * ROW_FLOATS, RECORD_BYTES = 176;
  const finalizedRows = new Map();
  // The finalize's parameters are its curve count alone: one uniform
  // buffer and binding per count, kept while the device lives.
  const finalizeParams = new Map();
  // The explicit layouts every patch pipeline shares, and the pipelines of
  // a patch run by sample count, depth and paint.
  let patchLayouts = null;
  const patchPipelineSets = new Map();
  // Sources are 176 bytes per curve and must fit one portable storage binding.
  const MAX_BORDER_CURVES = Math.floor((128 << 20) / 176);
  const REDRAW_BYTES = 1 << 20;
  // The net stage's scratch (docs/phase_b4_plan.md, B5.5): a frame's
  // dispatch tables, and for a dispatch of several nets their gathered
  // control points and evaluated vertices, grown by powers of two and kept
  // while frames draw nets; the bind groups that name them, by table offset
  // and one for the pair. A dispatch of several nets stays within the budget.
  const NET_SCRATCH_BUDGET = 32 << 20, NET_TABLE_HEADER = 16, NET_ENTRY_BYTES = 32;
  const netScratch = { buffers: {}, sizes: {}, tables: new Map(), io: null };
  // The index patterns net batches draw at the steps they are evaluated at
  // (B5.7), by their members' patches, capacity and steps, each stamped
  // with the last frame that drew it; a commit retires the ones its frame
  // did not draw.
  const netPatterns = new Map();
  // Buffers let go of while a frame is prepared, destroyed after its submit.
  let retired = [];
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
    const stripMark = name.endsWith("_strip_mark"), stripCover = name.endsWith("_strip_cover");
    descriptor.fragment = {
      module: modules[moduleKey], entryPoint: "fs_main",
      targets: [{ format: "rgba8unorm", blend, writeMask: depthOnly || stripMark ? 0 : 15 }] };
    if (stripMark || stripCover) {
      // A patch object's strips: the mark sets the border bit; the cover
      // paints where the byte is nonzero and zeroes it (patch_fill.wgsl).
      const face = stripMark ? STENCIL_STRIP_MARK : STENCIL_COVER;
      descriptor.depthStencil = {
        format: DEPTH_FORMAT,
        depthWriteEnabled: depthTest && stripCover,
        depthCompare: depthTest && stripCover ? "less" : "always",
        stencilFront: face, stencilBack: face,
        stencilReadMask: 255, stencilWriteMask: stripMark ? PATCH_STRIP_REFERENCE : 255,
      };
    } else {
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
    }
    descriptor.multisample = { count: samples };
    const pipeline = device.createRenderPipeline(descriptor);
    pipelines.set(key, pipeline);
    return pipeline;
  }

  // Explicit layouts for the patch pipelines: group 0 the uniforms, group 1
  // the curve records and object table, group 2 a paint field.
  function patchBindLayouts() {
    if (patchLayouts) return patchLayouts;
    const both = GPUShaderStage.VERTEX | GPUShaderStage.FRAGMENT;
    const group0 = device.createBindGroupLayout({ entries: [
      { binding: 0, visibility: both, buffer: { type: "uniform" } }] });
    const group1 = device.createBindGroupLayout({ entries: [0, 1].map(binding =>
      ({ binding, visibility: GPUShaderStage.VERTEX, buffer: { type: "read-only-storage" } })) });
    const group2 = device.createBindGroupLayout({ entries: [
      { binding: 0, visibility: GPUShaderStage.FRAGMENT, buffer: { type: "read-only-storage" } }] });
    patchLayouts = { group0, group1, group2,
      plain: device.createPipelineLayout({ bindGroupLayouts: [group0, group1] }),
      withPaint: device.createPipelineLayout({ bindGroupLayouts: [group0, group1, group2] }) };
    return patchLayouts;
  }

  // mark_fan and mark_patch count winding in the stencil's low seven bits
  // (the patch draw per sample, with the curve test); cover and cover_paint
  // paint where the byte is nonzero and zero it (patch_fill.wgsl).
  function patchPipeline(kind, depth, samples) {
    const key = "patch:" + kind + ":" + depth + "@" + samples;
    if (pipelines.has(key)) return pipelines.get(key);
    const layouts = patchBindLayouts();
    const cover = kind.startsWith("cover");
    const vertexEntry = { mark_fan: "vs_fan", mark_patch: "vs_patch", cover: "vs_cover", cover_paint: "vs_cover" }[kind];
    const fragmentEntry = { mark_fan: "fs_mark_fan", mark_patch: "fs_mark_patch", cover: "fs_surface", cover_paint: "fs_paint" }[kind];
    const stencil = cover
      ? { front: "zero", back: "zero", compare: "not-equal", depthFail: "zero", write: 255 }
      : { front: "increment-wrap", back: "decrement-wrap", compare: "always", depthFail: "keep", write: PATCH_COUNT_MASK };
    const face = passOp => ({ compare: stencil.compare, failOp: "keep", depthFailOp: stencil.depthFail, passOp });
    const pipeline = device.createRenderPipeline({
      layout: kind === "cover_paint" ? layouts.withPaint : layouts.plain,
      vertex: { module: modules.patch_fill, entryPoint: vertexEntry, buffers: [] },
      primitive: { topology: "triangle-list" },
      fragment: { module: modules.patch_fill, entryPoint: fragmentEntry,
        targets: [{ format: "rgba8unorm", blend: PREMULTIPLIED_BLEND, writeMask: cover ? 15 : 0 }] },
      depthStencil: {
        format: DEPTH_FORMAT,
        depthWriteEnabled: depth && cover,
        depthCompare: depth && cover ? "less" : "always",
        stencilFront: face(stencil.front), stencilBack: face(stencil.back),
        stencilReadMask: 255, stencilWriteMask: stencil.write },
      multisample: { count: samples },
    });
    pipelines.set(key, pipeline);
    return pipeline;
  }

  // The patch run layout: [curve count, bordered, group] per object; and
  // its groups of consecutive objects sharing a stencil count.
  function validatePatchLayout(layout, curveCount) {
    if (!Array.isArray(layout) || !layout.length) throw new Error("invalid patch run layout");
    let curves = 0;
    for (const part of layout) {
      if (!Array.isArray(part) || part.length !== 3 || part.some(value => !Number.isSafeInteger(value))
          || part[0] < 1 || (part[1] !== 0 && part[1] !== 1) || part[2] < 0) {
        throw new Error("invalid patch run layout");
      }
      curves += part[0];
    }
    if (curves !== curveCount) throw new Error("patch run layout does not match its source array");
  }

  function patchGroups(layout) {
    const groups = [];
    let curveOffset = 0;
    layout.forEach(([curves, bordered, group], index) => {
      const last = groups[groups.length - 1];
      if (last && last.group === group) {
        last.count += 1; last.curves += curves; last.bordered = last.bordered || !!bordered;
        last.most = Math.max(last.most, curves);
      } else {
        groups.push({ first: index, count: 1, firstCurve: curveOffset, curves, bordered: !!bordered, group, most: curves });
      }
      curveOffset += curves;
    });
    return groups;
  }

  function patchDrawCount(layout, capacity) {
    const strip = 6 * (capacity / 2 - 1);
    return layout.reduce((total, [curves, bordered]) => total + curves * (PATCH_VERTICES_PER_CURVE + (bordered ? strip : 0)), 0);
  }

  function validateObjects(bytes, layout) {
    const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
    if (bytes.byteLength !== 32 * layout.length) throw new Error("invalid patch object table");
    let offset = 0;
    layout.forEach(([curves, bordered], index) => {
      const word = i => view.getFloat32(32 * index + 4 * i, true);
      for (let i = 0; i < 8; i++) if (!Number.isFinite(word(i))) throw new Error("invalid patch object table");
      if (word(3) !== offset || word(4) !== curves || word(5) !== bordered || ![-1, 0, 1].includes(word(6)) || word(7) !== 0) {
        throw new Error("patch object table does not match its run layout");
      }
      offset += curves;
    });
  }

  // Surface nets: the reservation's vertex and index counts per patch, and
  // the triangle pattern both drivers build locally.
  function validateNetCapacity(capacity) {
    if (!Number.isSafeInteger(capacity) || capacity < MIN_NET_STEPS || capacity > MAX_NET_STEPS) {
      throw new Error("net capacity must be a step count between 2 and 32");
    }
    return capacity;
  }

  // The steps a net is evaluated at (docs/phase_b4_plan.md, B5.5), decided
  // here rather than in the kernel so that an output depends on its control
  // points, its capacity and this integer alone, and a camera move that
  // leaves it unchanged evaluates nothing. In double precision from the
  // descriptor's density and the uniforms as packed (float32 y rescale
  // factor and frame scale), as gpu_net_geometry.evaluation_steps computes
  // it, so both drivers reach the same integer.
  function netSteps(density, rescaleY, height, frameScale, capacity) {
    const pixels = density * (rescaleY * height / 2) / frameScale;
    if (!(pixels > 4)) return MIN_NET_STEPS;
    const root = Math.sqrt(pixels);
    if (root >= capacity) return capacity;
    return Math.max(MIN_NET_STEPS, Math.min(capacity, Math.ceil(root)));
  }

  // The nets a frame evaluates grouped into dispatches, in order, as
  // gpu_net_geometry.plan_evaluation groups them: each source gathered once
  // per dispatch, offsets in floats, a dispatch of several within the
  // budget in both scratch buffers; a dispatch of one net reads and writes
  // in place.
  function planNets(nets, budget) {
    const dispatches = [];
    let current = null;
    nets.forEach((net, index) => {
      const fresh = !current || !current.offsets.has(net.source);
      if (current && (current.inputBytes + (fresh ? net.sourceBytes : 0) > budget
                      || current.outputBytes + net.size > budget)) current = null;
      if (!current) {
        current = { entries: [], sources: [], offsets: new Map(), inputBytes: 0, outputBytes: 0, patches: 0 };
        dispatches.push(current);
      }
      let offset = current.offsets.get(net.source);
      if (offset === undefined) {
        offset = current.inputBytes;
        current.offsets.set(net.source, offset);
        current.sources.push([net.source, offset, net.sourceBytes]);
        current.inputBytes += net.sourceBytes;
      }
      current.entries.push([index, offset / 4, current.outputBytes / 4, current.patches]);
      current.outputBytes += net.size;
      current.patches += net.patches;
    });
    return dispatches;
  }

  // The triangles of a run of nets at the steps they are evaluated at
  // (B5.7), as gpu_net_geometry.run_indices lays them out: per member
  // [patches, capacity, steps], each patch's steps² quads over its
  // (capacity + 1)² vertices, after the members before it. The kernel
  // repeats the rows and columns past the steps, so the capacity's pattern
  // draws these triangles in this order and the rest with zero area.
  function netIndices(members) {
    let total = 0;
    for (const [patches, , steps] of members) total += patches * 6 * steps * steps;
    const out = new Uint32Array(total);
    let write = 0, base = 0;
    for (const [patches, capacity, steps] of members) {
      const side = capacity + 1;
      for (let patch = 0; patch < patches; patch++, base += side * side) {
        for (let a = 0; a < steps; a++) {
          for (let b = 0; b < steps; b++) {
            const topLeft = base + a * side + b;
            out[write++] = topLeft; out[write++] = topLeft + side; out[write++] = topLeft + 1;
            out[write++] = topLeft + 1; out[write++] = topLeft + side; out[write++] = topLeft + side + 1;
          }
        }
      }
    }
    return out;
  }


  function ensureTargets(width, height, samples, outputWidth = width, outputHeight = height) {
    const key = width + "x" + height + "@" + samples + ":" + outputWidth + "x" + outputHeight;
    if (targetKey === key) return;
    targetKey = key;
    presentBindings.clear();
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

  const validHash = hash => typeof hash === "string" && /^[0-9a-f]{32}$/.test(hash);

  // Shared resources. A slot holds what it draws with; a resource is made
  // by the first slot that needs it and retired when the last one lets go.
  // Retired buffers are destroyed after the next submit, so no frame in
  // flight loses one. A texture no slot holds waits for the next submitted
  // frame, as one decoded for a failed frame always has.
  function hold(slot, cache, key, make) {
    let entry = cache.get(key);
    if (!entry) {
      entry = make();
      entry.cache = cache; entry.key = key; entry.refs = 0;
      cache.set(key, entry);
    }
    entry.refs++;
    slot.holds.push(entry);
    return entry;
  }

  // Let go of what a slot holds, and retire the outputs it owns (an output
  // a later slot took over is that slot's by now).
  function releaseSlot(slot) {
    for (const entry of slot.holds) {
      if (--entry.refs) continue;
      if (entry.texture) { looseTextures.add(entry); continue; }
      entry.cache.delete(entry.key);
      retired.push(...entry.buffers);
    }
    slot.holds = [];
    for (const output of [slot.border, slot.net, slot.program, slot.rowsRun]) {
      if (output && output.owner === slot) retired.push(...output.buffers);
    }
    slot.border = slot.net = slot.program = slot.rowsRun = null;
  }

  function destroyRetired() {
    for (const buffer of retired) buffer.destroy();
    retired = [];
  }

  function holdStorage(slot, cache, key, bytes, usage = GPUBufferUsage.STORAGE) {
    return hold(slot, cache, key, () => {
      const buffer = makeBuffer(bytes, usage);
      return { buffer, bytes, buffers: [buffer] };
    });
  }

  function holdBinding(slot, cache, key, describe) {
    return hold(slot, cache, key, () => ({ binding: device.createBindGroup(describe()), buffers: [] })).binding;
  }

  // Uniform values into a persistent buffer: made with them, then rewritten
  // in place only when their bits move.
  function writeUniforms(target, packed) {
    const bits = new Uint32Array(packed);
    if (!target.buffer) {
      target.buffer = makeBuffer(packed, GPUBufferUsage.UNIFORM | GPUBufferUsage.COPY_DST);
    } else if (bits.some((value, i) => value !== target.bits[i])) {
      device.queue.writeBuffer(target.buffer, 0, packed);
    }
    target.bits = bits;
  }

  // A uniform set: the camera merged with one set of per-object overrides,
  // packed once for every slot drawn with them and bound once per pipeline
  // layout. Its buffer is rewritten in place when the camera moves; the
  // border and net stages read the same values unscaled from a second one.
  function makeUniformSet(overrides, incoming) {
    const set = { overrides, buffer: null, bits: null, compute: null, environment: null,
                  bindings: new Map(), buffers: [] };
    packSet(set, incoming);
    return set;
  }

  function packSet(set, incoming) {
    const values = { ...incoming.header.camera, ...set.overrides };
    const uniforms = { ...values, premultiplied_output: 1 };
    uniforms.pixel_size = (uniforms.pixel_size ?? 1) / incoming.supersample;
    uniforms.anti_alias_width = (uniforms.anti_alias_width ?? 1.5) * incoming.supersample;
    const packed = packUniforms(uniforms, uniforms.border_mode || 0);
    const created = !set.buffer;
    writeUniforms(set, packed);
    if (created) set.buffers.push(set.buffer);
    if (set.compute) packCompute(set, values);
    set.environment = incoming.environment;
  }

  // The generation stages' view of a set, with what they check of it and
  // the bits a border's output depends on.
  function packCompute(set, values) {
    const compute = set.compute, created = !compute.buffer;
    const packed = packUniforms(values, values.border_mode || 0);
    writeUniforms(compute, packed);
    if (created) set.buffers.push(compute.buffer);
    const floats = new Float32Array(packed), bits = compute.bits;
    const finite = floats.every(value => Number.isFinite(value));
    const factor = floats[23] * (1 - floats[38]) + floats[38];
    compute.floats = floats;
    compute.borderValid = finite && floats[23] > 0 && factor >= 0 && [0, 1, 2, 3].includes(floats[36]);
    compute.netValid = finite && floats[23] > 0;
    const flat = floats[37] !== 0 || floats[19] !== 0;
    compute.borderState = [23, 38, 36, 37, 19, ...(flat ? [] : [20, 21, 22])].map(i => bits[i]).join(",");
  }

  function computeUniforms(set, incoming) {
    if (!set.compute) {
      set.compute = { buffer: null, bits: null };
      packCompute(set, { ...incoming.header.camera, ...set.overrides });
    }
    return set.compute;
  }

  // The camera and supersample every uniform set packs besides its
  // overrides: when they move, each set the frame draws with is rewritten
  // in place (a set made this frame was packed with them). The retained
  // frame records them once it is submitted; a failed frame clears them
  // (rollback), so the next one repacks every set.
  function updateEnvironment(incoming, slots) {
    if (frame.environment === incoming.environment) return;
    for (const slot of slots) {
      const set = slot.set;
      if (set && set.environment !== incoming.environment) packSet(set, incoming);
    }
  }

  function setBinding(set, pipeline) {
    let binding = set.bindings.get(pipeline);
    if (!binding) {
      binding = device.createBindGroup({
        layout: pipeline.getBindGroupLayout(0),
        entries: [{ binding: 0, resource: { buffer: set.buffer } }],
      });
      set.bindings.set(pipeline, binding);
    }
    return binding;
  }

  function patchSetBinding(set) {
    const layout = patchBindLayouts().group0;
    let binding = set.bindings.get(layout);
    if (!binding) {
      binding = device.createBindGroup({ layout,
        entries: [{ binding: 0, resource: { buffer: set.buffer, size: 192 } }] });
      set.bindings.set(layout, binding);
    }
    return binding;
  }

  // What a batch's uploaded geometry is laid out as. A run's reserved
  // capacity changes its output size but not what was uploaded, so it
  // stays out of the retained layout identity.
  function geometryDescriptor(batch, runLayout) {
    return JSON.stringify([batch.pipeline, batch.stride, runLayout || "net" in batch ? null : batch.num_verts,
      !!batch.indexed, batch.index_count || 0, batch.fill_num_verts ?? batch.num_verts, runLayout ?? null]);
  }

  // A batch's geometry by content hash, uploaded by the first slot that
  // draws it.
  function holdGeometry(slot, batch, payload, runLayout) {
    const descriptor = geometryDescriptor(batch, runLayout);
    const resident = generatedGeometry.get(batch.hash);
    if (resident && resident.descriptor !== descriptor) throw new Error("cached generated geometry layout changed");
    return hold(slot, generatedGeometry, batch.hash, () => {
      const vertex = makeBuffer(payload.subarray(
        batch.offset, batch.offset + (batch.fill_num_verts ?? batch.num_verts) * batch.stride),
        GPUBufferUsage.VERTEX | (batch.border ? GPUBufferUsage.COPY_SRC : 0));
      const buffers = [vertex];
      let index = null, fillIndices = null;
      if (batch.indexed && runLayout) {
        // Only the fill indices travel. Keep them to expand the ordered
        // fill/strip buffer for whatever capacity is drawn.
        const copy = payload.slice(batch.index_offset, batch.index_offset + batch.index_count * 4);
        fillIndices = new Uint32Array(copy.buffer, 0, batch.index_count);
      } else if (batch.indexed) {
        index = makeBuffer(payload.subarray(
          batch.index_offset, batch.index_offset + batch.index_count * 4), GPUBufferUsage.INDEX);
        buffers.push(index);
      }
      return { vertex, index, fillIndices, descriptor, runLayout: runLayout ?? null, buffers };
    });
  }

  // An index pattern the driver builds for a geometry at a reserved
  // capacity (a run's fills and strips, a patch run's strips, a net's
  // triangles), shared by the slots that draw it there.
  function holdPattern(slot, geometry, capacity, build) {
    return hold(slot, indexPatterns, geometry.key + "@" + capacity, () => {
      const buffer = makeBuffer(build().buffer, GPUBufferUsage.INDEX);
      return { buffer, buffers: [buffer] };
    }).buffer;
  }

  function holdTextureBinding(slot, name, samples, pipeline, hashes) {
    const textures = hashes.map(hash => hold(slot, textureCache, hash, null).texture);
    return holdBinding(slot, textureBindings, name + "@" + samples + ":" + JSON.stringify(hashes), () => {
      const entries = textures.map((texture, i) => ({ binding: i, resource: texture.createView() }));
      entries.push({ binding: textures.length, resource: sampler });
      return { layout: pipeline.getBindGroupLayout(1), entries };
    });
  }

  function programPipeline(name) {
    let pipeline = programPipelines.get(name);
    if (!pipeline) {
      pipeline = device.createComputePipeline({layout: "auto", compute: {module: modules[name], entryPoint: "cs_main"}});
      programPipelines.set(name, pipeline);
    }
    return pipeline;
  }

  // The row sources, border curves, object tables and net control points a
  // message carries, validated; a definition of something already held
  // must carry the same bytes. One reader per table, each check of the
  // values its own function, as the stages kept them: V8 optimizes the
  // per-value loops far better apart than in one body.
  function sourceDefinitions(header, payload) {
    return { programs: programDefinitions(header, payload), borders: borderDefinitions(header, payload),
             tables: objectDefinitions(header, payload), nets: netDefinitions(header, payload) };
  }

  function redefined(previous, bytes) {
    return previous && (previous.bytes.length !== bytes.length || previous.bytes.some((value, i) => value !== bytes[i]));
  }

  // The per-value loops below look their builtins up once per call: a
  // global read per value is an interceptor call in a sandboxed realm (Node's
  // vm, where the command harnesses and browser_frames.cjs run this file).
  function finiteFloats(bytes) {
    const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength), finite = Number.isFinite;
    for (let i = 0; i < bytes.byteLength; i += 4) {
      if (!finite(view.getFloat32(i, true))) return false;
    }
    return true;
  }

  function programDefinitions(header, payload) {
    const records = "program_data" in header ? header.program_data : {};
    if (records === null || typeof records !== "object" || Array.isArray(records)) {
      throw new Error("program sources must be an object");
    }
    const definitions = new Map();
    for (const [key, ref] of Object.entries(records)) {
      if (!validHash(key)) throw new Error("invalid program source hash");
      if (ref === null || typeof ref !== "object" || Array.isArray(ref)) throw new Error("invalid program source span");
      const {offset, nbytes} = ref;
      if (!Number.isSafeInteger(offset) || !Number.isSafeInteger(nbytes) || nbytes <= 0 || nbytes % 4
          || offset < 0 || offset > payload.length || nbytes > payload.length - offset) {
        throw new Error("invalid program source span");
      }
      const bytes = payload.slice(offset, offset + nbytes);
      if (!finiteFloats(bytes)) throw new Error("program source rows must be finite");
      if (redefined(programSources.get(key), bytes)) throw new Error("program source hash redefined with different rows");
      definitions.set(key, bytes);
    }
    return definitions;
  }

  function validateCurves(bytes) {
    const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength), finite = Number.isFinite;
    for (let i = 0; i < bytes.byteLength / 4; i++) {
      const value = view.getFloat32(4 * i, true), field = i % 44;
      if (!finite(value) || ((field === 7 || field === 19 || field === 31 || field === 36) && value < 0)
          || ((field === 37 || field === 38) && value !== 0 && value !== 1)
          || (field === 39 && value !== 0)) {
        throw new Error("invalid border coefficients, widths, density or active flags");
      }
    }
  }

  function borderDefinitions(header, payload) {
    const records = "border_data" in header ? header.border_data : {};
    if (records === null || typeof records !== "object" || Array.isArray(records)) {
      throw new Error("border definitions must be an object");
    }
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
      validateCurves(bytes);
      if (redefined(borderSources.get(key), bytes)) throw new Error("border hash redefined with different coefficients");
      definitions.set(key, bytes);
    }
    return definitions;
  }

  function objectDefinitions(header, payload) {
    const tables = "object_data" in header ? header.object_data : {};
    if (tables === null || typeof tables !== "object" || Array.isArray(tables)) {
      throw new Error("object table definitions must be an object");
    }
    const definitions = new Map();
    for (const [key, ref] of Object.entries(tables)) {
      if (!validHash(key)) throw new Error("invalid object table hash");
      if (ref === null || typeof ref !== "object" || Array.isArray(ref)) throw new Error("invalid object table span");
      const {offset, nbytes} = ref;
      if (!Number.isSafeInteger(offset) || !Number.isSafeInteger(nbytes) || nbytes <= 0 || nbytes % 32
          || offset < 0 || offset > payload.length || nbytes > payload.length - offset) {
        throw new Error("invalid object table span");
      }
      const bytes = payload.slice(offset, offset + nbytes);
      if (redefined(objectTables.get(key), bytes)) throw new Error("object table hash redefined with different records");
      definitions.set(key, bytes);
    }
    return definitions;
  }

  function netDefinitions(header, payload) {
    const records = "net_data" in header ? header.net_data : {};
    if (records === null || typeof records !== "object" || Array.isArray(records)) {
      throw new Error("net definitions must be an object");
    }
    const definitions = new Map();
    for (const [key, ref] of Object.entries(records)) {
      if (!validHash(key)) throw new Error("invalid net hash");
      if (ref === null || typeof ref !== "object" || Array.isArray(ref)) throw new Error("invalid net definition span");
      const {offset, nbytes} = ref;
      if (!Number.isSafeInteger(offset) || !Number.isSafeInteger(nbytes) || nbytes <= 0 || nbytes % 4
          || offset < 0 || offset > payload.length || nbytes > payload.length - offset) {
        throw new Error("invalid net definition span");
      }
      const bytes = payload.slice(offset, offset + nbytes);
      if (!finiteFloats(bytes)) throw new Error("net control points must be finite");
      if (redefined(netSources.get(key), bytes)) throw new Error("net hash redefined with different control points");
      definitions.set(key, bytes);
    }
    return definitions;
  }

  // A program descriptor, scalars included, as the program stage has always
  // checked it; its rows in bytes.
  function validateProgram(batch, incoming) {
    if ((incoming.header.format_version ?? 0) < 7) throw new Error("a program requires a format 7 descriptor");
    const program = batch.program;
    if (program === null || typeof program !== "object" || Array.isArray(program)) {
      throw new Error("invalid program descriptor");
    }
    const {kind, sources, rows, channels} = program;
    if (!(kind in PROGRAM_KINDS) || !Array.isArray(sources) || sources.length !== PROGRAM_KINDS[kind][0]
        || !sources.every(validHash) || !Number.isSafeInteger(rows) || rows < 1
        || !Number.isSafeInteger(channels) || channels < 1 || (kind !== "blend" && channels !== ROW_FLOATS)) {
      throw new Error("invalid program descriptor");
    }
    validateScalars(program);
    const rowBytes = rows * channels * 4;
    if (rowBytes > incoming.maxStorage) throw new Error("program rows exceed the device's storage binding limit");
    return rowBytes;
  }

  // A program's scalars, the part of its descriptor that moves per frame.
  function validateScalars(program) {
    const {kind, scalars, rows} = program;
    if (!Array.isArray(scalars) || scalars.length !== PROGRAM_KINDS[kind][1]
        || scalars.some(value => typeof value !== "number" || !Number.isFinite(value))) {
      throw new Error("invalid program descriptor");
    }
    if (kind === "partial") {
      const [lower, lowerResidue, upper, upperResidue, full] = scalars, curves = Math.floor(rows / 2);
      if (![lower, upper, full].every(Number.isInteger) || (full !== 0 && full !== 1)
          || lower < 0 || lower >= Math.max(1, curves) || upper < 0 || upper >= Math.max(1, curves)
          || lowerResidue < 0 || lowerResidue > 1 || upperResidue < 0 || upperResidue > 1) {
        throw new Error("invalid partial program scalars");
      }
    }
  }

  // A batch's row sources, each rows checked as the finalize reads it (an
  // odd count of seventeen-float rows, whose outputs fit a storage
  // binding; a patch's fill border widths nonnegative): [{key, bytes,
  // curves}], or null when a definition is neither in the message nor held.
  function resolveRows(batch, incoming) {
    const keys = batch.rows, patch = batch.pipeline === "patch" || batch.pipeline === "patch_depth";
    if ((incoming.header.format_version ?? 0) < 7 || !isArray(keys) || !keys.length || !keys.every(validHash)
        || !(patch || batch.pipeline === "stroke" || batch.pipeline === "stroke_depth")
        || batch.program !== undefined || batch.net !== undefined) {
      throw new Error("invalid row sources");
    }
    const members = [];
    for (const key of keys) {
      const source = programSources.get(key), bytes = source ? source.bytes : incoming.programs.get(key);
      if (!bytes) return null;
      const rows = bytes.length / ROW_BYTES, curves = Math.floor((rows - 1) / 2);
      if (!Number.isInteger(rows) || rows < 3 || rows % 2 === 0 || bytes.length > incoming.maxStorage
          || curves * INSTANCE_STRIDE > incoming.maxStorage) {
        throw new Error("invalid row source");
      }
      if (patch) validateRowWidths(bytes);
      members.push({ key, bytes, curves });
    }
    return members;
  }

  function validateRowWidths(bytes) {
    const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
    for (let offset = 64; offset < bytes.byteLength; offset += ROW_BYTES) {
      if (view.getFloat32(offset, true) < 0) throw new Error("fill border widths must be nonnegative");
    }
  }

  // A border batch's layout, checked as the border stage has always checked
  // it; null when its run layout, object table or curves are not held. A
  // program's or a run of row sources' curves are finalized, not sent.
  function resolveBorder(batch, payload, incoming, patch, program, rows = null) {
    const border = batch.border, format = incoming.header.format_version ?? 0;
    if (format < 5 || border === null || typeof border !== "object" || Array.isArray(border)) {
      throw new Error("GPU border requires a format 5 border descriptor");
    }
    const key = border.hash, count = border.num_curves, fillCount = batch.fill_num_verts;
    if (!validHash(key) || !Number.isSafeInteger(count) || count < 1 || count > MAX_BORDER_CURVES
        || !Number.isSafeInteger(fillCount) || fillCount < 0
        || !Number.isSafeInteger(batch.num_verts)
        || batch.stride !== 40
        || !Number.isSafeInteger(batch.index_count) || batch.index_count % 3
        || !Number.isSafeInteger(batch.count) || batch.instances !== 1
        || (!patch && (batch.indexed !== true
            || !["surface", "surface_depth", "paint", "paint_depth"].includes(batch.pipeline)))
        || (patch && (batch.indexed !== false || fillCount || batch.index_count || format < 7))) {
      throw new Error("invalid GPU border geometry layout or draw count");
    }
    const [capacity, runLayout] = borderRun(batch);
    if (runLayout === undefined) return null;
    let tableKey = null, tableBytes = null;
    if (patch) {
      validatePatchLayout(runLayout, count);
      const objects = batch.objects;
      if (objects === null || typeof objects !== "object" || Array.isArray(objects)
          || objects.count !== runLayout.length || !validHash(objects.hash)) {
        throw new Error("invalid patch object table reference");
      }
      tableKey = objects.hash;
      const table = objectTables.get(tableKey);
      tableBytes = table ? table.bytes : incoming.tables.get(tableKey);
      if (!tableBytes) return null;
      validateObjects(tableBytes, runLayout);
    } else if (runLayout) {
      validateRunLayout(runLayout, batch.index_count, fillCount, count);
    }
    // Format 5 shipped the complete ordered index buffer; format 6 ships
    // the fills and the driver appends each object's strip pattern; a
    // patch run has no fill and draws its strips from the pattern alone.
    const complete = patch
      ? batch.count === patchDrawCount(runLayout, capacity)
      : runLayout
        ? batch.count === batch.index_count + 6 * (capacity / 2 - 1) * count
        : batch.index_count >= 186 * count && batch.count === batch.index_count;
    if (!complete || batch.num_verts !== fillCount + capacity * count) {
      throw new Error("invalid GPU border geometry layout or draw count");
    }
    const size = batch.num_verts * 40;
    const storageOffset = Math.floor(fillCount * 40 / incoming.vertexAlignment) * incoming.vertexAlignment;
    const storageSize = size - storageOffset;
    if (!Number.isSafeInteger(size) || size > incoming.maxBuffer || storageSize > incoming.maxStorage) {
      throw new Error("GPU border output exceeds device buffer limits");
    }
    let definition = null, length;
    if (program) {
      // The records a program finalizes are the run's curves.
      const curves = Math.max(0, Math.floor((program.rows - 1) / 2));
      if (!patch || program.channels !== ROW_FLOATS || !curves || curves !== count) {
        throw new Error("a program's curve records do not match its patch batch");
      }
      length = count * 176;
    } else if (rows) {
      // So are its objects' rows, one object each, in the layout's order.
      if (!patch || rows.length !== runLayout.length || rows.some((member, i) => member.curves !== runLayout[i][0])) {
        throw new Error("row sources do not match their patch run");
      }
      length = count * RECORD_BYTES;
    } else {
      const source = borderSources.get(key);
      definition = source ? source.bytes : incoming.borders.get(key);
      if (!definition) return null;
      length = definition.length;
    }
    if (length !== count * 176 || length > incoming.maxStorage) {
      throw new Error("border definition curve count does not match geometry");
    }
    if (!batch.cached && !patch) validateBorderPayload(batch, payload, fillCount, runLayout ? fillCount : batch.num_verts);
    return { key, count, fillCount, capacity, runLayout, size, storageOffset, storageSize, tableKey, tableBytes,
             definition, length };
  }

  // The fill indices and vertices a border batch sends, which index only
  // the fill (or the complete buffer, format 5) and must be finite.
  function validateBorderPayload(batch, payload, fillCount, addressable) {
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
    const finite = Number.isFinite;
    for (let i = 0; i < fillCount * 10; i++) {
      if (!finite(vertices.getFloat32(4 * i, true))) {
        throw new Error("border fill vertices must be finite");
      }
    }
  }

  // A net descriptor, density included, as the net stage has always
  // checked it; a batch's net is one descriptor or, for a run of nets
  // (docs/phase_b4_plan.md, B5.7), a list of them, each member evaluated
  // into its span of the batch's one output after the members before it.
  // Returns the members (with their first vertex) and the output's size.
  function validateNet(batch, incoming) {
    const net = batch.net, run = isArray(net), members = run ? net : [net];
    if ((incoming.header.format_version ?? 0) < 7 || !members.length || (run && members.length < 2)
        || members.some(member => member === null || typeof member !== "object" || isArray(member))) {
      throw new Error("a surface net requires a format 7 net descriptor");
    }
    if (!["surface", "surface_depth", "texsurface", "texsurface_depth"].includes(batch.pipeline)
        || (run && (!["surface", "surface_depth"].includes(batch.pipeline) || batch.program !== undefined))
        || batch.indexed !== false || batch.fill_num_verts !== 0 || batch.index_count !== 0 || batch.instances !== 1) {
      throw new Error("invalid surface net descriptor");
    }
    let vertices = 0, count = 0;
    const parsed = members.map(member => {
      const {hash: key, nu, nv, channels, capacity, density} = member;
      if (!validHash(key) || [nu, nv, channels, capacity].some(value => !Number.isSafeInteger(value))
          || nu < 3 || nv < 3 || nu % 2 === 0 || nv % 2 === 0
          || typeof density !== "number" || !Number.isFinite(density) || density < 0
          || channels * 4 !== batch.stride) {
        throw new Error("invalid surface net descriptor");
      }
      validateNetCapacity(capacity);
      const patches = ((nu - 1) / 2) * ((nv - 1) / 2), perPatch = (capacity + 1) * (capacity + 1);
      const first = vertices;
      vertices += patches * perPatch;
      count += patches * 6 * capacity * capacity;
      return { key, nu, nv, channels, capacity, patches, first, size: patches * perPatch * batch.stride,
               bytes: nu * nv * channels * 4 };
    });
    if (batch.num_verts !== vertices || batch.count !== count) {
      throw new Error("invalid surface net vertex or draw count");
    }
    const size = batch.num_verts * batch.stride;
    if (!Number.isSafeInteger(size) || size > incoming.maxBuffer || size > incoming.maxStorage) {
      throw new Error("surface net output exceeds device buffer limits");
    }
    return { members: parsed, size };
  }

  function validatePaint(bytes) {
    if (bytes.byteLength < 96 || bytes.byteLength > (24 + 8 * 4096) * 4 || bytes.byteLength % 4) {
      throw new Error("invalid paint coefficient length");
    }
    // Packet JSON can leave the binary payload unaligned. DataView also makes
    // the wire's little-endian representation explicit on every platform.
    const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength), finite = Number.isFinite;
    for (let offset = 0; offset < bytes.byteLength; offset += 4) {
      if (!finite(view.getFloat32(offset, true))) {
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

  // The paint definitions a message carries, validated; a definition of a
  // paint already held must carry the same coefficients.
  function paintDefinitions(header, payload) {
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
    return definitions;
  }

  // The paint a batch draws with: null for none, undefined when neither
  // the message nor the driver holds it, else its key and coefficients.
  function paintOf(batch, incoming) {
    const patchPaint = (batch.pipeline === "patch" || batch.pipeline === "patch_depth") && "paint_hash" in batch;
    if (batch.pipeline !== "paint" && batch.pipeline !== "paint_depth" && !patchPaint) return null;
    if ("paint_hash" in batch) {
      const key = paintHashKey(batch.paint_hash);
      const resident = generatedPaints.get(key);
      const bytes = resident ? resident.bytes : incoming.paints.get(key);
      return bytes ? { key, bytes } : undefined;
    }
    if ((incoming.header.format_version ?? 3) < 4 && "paint" in batch) {
      if (!Array.isArray(batch.paint) || batch.paint.some(value => typeof value !== "number")) {
        throw new Error("inline paint coefficients must be a numeric array");
      }
      const packed = new Float32Array(batch.paint);
      const bytes = validatePaint(new Uint8Array(packed.buffer));
      return { key: "inline:" + new Uint32Array(packed.buffer).join(","), bytes };
    }
    throw new Error("paint operation requires a paint hash");
  }

  // What a slot's outputs are made for, so a batch that changed can take
  // over the slot it replaces: its pipeline, coverage and stages.
  function shapeOf(batch) {
    return batch.pipeline + (batch.coverage ? ":coverage" : ":") + ("border" in batch ? ":border" : ":")
      + (batch.net !== undefined ? ":net" : ":") + (batch.program !== undefined ? ":program" : ":")
      + (batch.rows !== undefined ? ":rows" : ":");
  }

  // Batches that resolve to the same slot: equal in every field a slot is
  // resolved from (makeSlot, resolveBorder, validateNet, validateProgram;
  // a field the driver reads belongs here), except what changes per frame
  // (a program's scalars, a net's density) or travels only with the bytes
  // (cached, the offsets, a run's layout), which are checked per frame.
  const BORDER_FIELDS = ["hash", "num_curves", "capacity"], OBJECT_FIELDS = ["hash", "count"];
  const NET_FIELDS = ["hash", "nu", "nv", "channels", "capacity"], PROGRAM_FIELDS = ["kind", "sources", "rows", "channels"];
  // Bound once: the comparison runs per batch per frame, and a global looked
  // up there costs an interceptor call in a sandboxed realm (Node's vm, as
  // the command harnesses and browser_frames.cjs run this file).
  const isArray = Array.isArray;

  function sameBatch(a, b) {
    return a.hash === b.hash && a.pipeline === b.pipeline && a.kind === b.kind && a.count === b.count
      && a.instances === b.instances && a.num_verts === b.num_verts && a.stride === b.stride
      && a.indexed === b.indexed && a.index_count === b.index_count && a.fill_num_verts === b.fill_num_verts
      && a.coverage === b.coverage && a.paint_hash === b.paint_hash
      && sameValue(a.uniforms, b.uniforms) && sameValue(a.textures, b.textures) && sameValue(a.paint, b.paint)
      && sameValue(a.rows, b.rows)
      && sameFields(a.border, b.border, BORDER_FIELDS) && sameFields(a.objects, b.objects, OBJECT_FIELDS)
      && sameNet(a.net, b.net) && sameFields(a.program, b.program, PROGRAM_FIELDS);
  }

  // A net descriptor, or a run's list of them member by member (B5.7).
  function sameNet(a, b) {
    if (!isArray(a) && !isArray(b)) return sameFields(a, b, NET_FIELDS);
    if (!isArray(a) || !isArray(b) || a.length !== b.length) return false;
    for (let i = 0; i < a.length; i++) if (!sameFields(a[i], b[i], NET_FIELDS)) return false;
    return true;
  }

  function sameFields(a, b, fields) {
    if (a === b) return true;
    if (a === null || b === null || typeof a !== "object" || typeof b !== "object"
        || isArray(a) !== isArray(b)) return false;
    for (const field of fields) if (!sameValue(a[field], b[field])) return false;
    return true;
  }

  function sameValue(a, b) {
    if (a === b) return true;
    if (typeof a !== "object" || typeof b !== "object" || a === null || b === null) return false;
    if (isArray(a)) {
      if (!isArray(b) || a.length !== b.length) return false;
      for (let i = 0; i < a.length; i++) if (!sameValue(a[i], b[i])) return false;
      return true;
    }
    if (isArray(b)) return false;
    let keys = 0;
    for (const key in a) {
      if (!sameValue(a[key], b[key])) return false;
      keys++;
    }
    for (const key in b) keys--;
    return keys === 0;
  }

  function miss(slot) {
    cacheMissed = true;
    slot.missing = true;
    return slot;
  }

  function inherit(slot, stage, output, incoming) {
    slot[stage] = output;
    incoming.inherited.push([slot, output]);
  }

  // A batch resolved once to what it draws with: its pipelines for the
  // sample count, its uniform set's binding per pipeline layout, its
  // geometry and index pattern, its paint or texture binding, and the
  // border, net and program outputs it owns. A predecessor (the slot this
  // batch replaces in place) hands over each output whose layout still
  // fits. The batch is checked as the stages have always checked it; one
  // that needs what neither the message nor the driver holds is a missing
  // slot, drawn as nothing, and a resend is asked for.
  function makeSlot(batch, payload, incoming, predecessor) {
    const patch = batch.pipeline === "patch" || batch.pipeline === "patch_depth";
    const slot = { batch, shape: shapeOf(batch), created: incoming.serial, frame: incoming.serial, holds: [], missing: false,
      coverage: !!batch.coverage, patch, count: batch.count, instances: batch.instances,
      set: null, geometry: null, paint: null, indexBuffer: null, draws: [], patchDraw: null,
      border: null, net: null, program: null, programKey: null, sources: null, strokes: false,
      borderSource: null, netSources: null, table: null, programOutput: null, programState: null,
      rows: null, rowsKey: null, rowsRun: null, rowBuffer: null, rowStrokes: null };
    incoming.created.push(slot);
    const name = "generated_" + batch.pipeline + (batch.coverage ? "_coverage" : "");
    const depthOnly = batch.coverage && typeof batch.pipeline === "string" && batch.pipeline.endsWith("_depth")
      ? "generated_" + batch.pipeline + "_depth_only" : null;
    if (batch.kind !== "generated" || !(name in PIPELINE_SPECS) || (depthOnly && !(depthOnly in PIPELINE_SPECS))) {
      throw new Error("unsupported generated pipeline " + batch.pipeline);
    }
    if (patch && batch.coverage) throw new Error("a patch fill owns its samples without a coverage reference");
    // What the batch needs, checked before anything is made: paint,
    // program sources, border curves and table, net points, geometry and
    // textures. Request a resend rather than reuse another material.
    const paint = paintOf(batch, incoming);
    if (paint === undefined) return miss(slot);
    let program = null;
    if (batch.program !== undefined) {
      const rowBytes = validateProgram(batch, incoming);
      program = batch.program;
      for (const key of program.sources) {
        const source = programSources.get(key), bytes = source ? source.bytes : incoming.programs.get(key);
        if (!bytes) return miss(slot);
        if (bytes.length !== rowBytes) throw new Error("program source does not match the descriptor's rows");
      }
    }
    let rows = null;
    if (batch.rows !== undefined) {
      rows = resolveRows(batch, incoming);
      if (!rows) return miss(slot);
      const curves = rows.reduce((total, member) => total + member.curves, 0);
      if (!patch && (batch.instances !== curves || batch.num_verts !== 3 * curves || batch.fill_num_verts !== 0
          || batch.indexed !== false || batch.stride !== VERTEX_STRIDE || "border" in batch)) {
        throw new Error("row sources do not match their stroke");
      }
    }
    let border = null;
    if ("border" in batch) {
      border = resolveBorder(batch, payload, incoming, patch, program, rows);
      if (!border) return miss(slot);
    }
    let net = null;
    if (batch.net !== undefined) {
      net = validateNet(batch, incoming);
      for (const member of net.members) {
        let length = member.bytes;
        if (program) {
          if (program.rows * program.channels * 4 !== member.bytes) throw new Error("a program's rows do not match its net batch");
        } else {
          const source = netSources.get(member.key);
          member.definition = source ? source.bytes : incoming.nets.get(member.key);
          if (!member.definition) return miss(slot);
          length = member.definition.length;
        }
        if (length !== member.bytes || length > incoming.maxStorage) {
          throw new Error("net definition does not match its descriptor");
        }
      }
    }
    if (batch.cached && !generatedGeometry.has(batch.hash)) return miss(slot);
    let textures = null;
    if (batch.textures) {
      textures = Object.values(batch.textures);
      if (textures.length === 1 && batch.pipeline.startsWith("texsurface")) {
        textures.push(textures[0]);  // DarkTexture falls back to light.
      }
      if (textures.some(hash => !textureCache.has(hash))) return miss(slot);
    }

    const samples = incoming.samples;
    slot.geometry = holdGeometry(slot, batch, payload, border ? border.runLayout : null);
    slot.set = hold(slot, uniformSets, JSON.stringify(batch.uniforms ?? {}),
                    () => makeUniformSet(batch.uniforms, incoming));
    if (paint) slot.paint = holdStorage(slot, generatedPaints, paint.key, paint.bytes);
    if (program) {
      slot.programKey = [program.kind, program.sources.join(","), program.rows, program.channels].join(":");
      slot.sources = program.sources.map(key => holdStorage(slot, programSources, key, incoming.programs.get(key)));
      slot.strokes = batch.pipeline === "stroke" || batch.pipeline === "stroke_depth";
      if (predecessor && predecessor.program && predecessor.programKey === slot.programKey) {
        inherit(slot, "program", predecessor.program, incoming);
      }
    }
    if (rows) {
      // Each rows finalized once, into outputs the slots naming it share;
      // a run of several objects draws a buffer of its own, copied from
      // theirs in order (prepareCompute), which it hands over as a border
      // output is handed over.
      slot.rows = rows.map(({key, bytes, curves}) => ({ curves,
        source: holdStorage(slot, programSources, key, bytes),
        output: hold(slot, finalizedRows, key, () => makeFinalizedRows(curves)) }));
      slot.rowsKey = batch.rows.join(",");
      const name = patch ? "records" : "strokes";
      if (rows.length === 1) {
        slot.rowBuffer = slot.rows[0].output[name];
      } else {
        const curves = rows.reduce((total, member) => total + member.curves, 0);
        const size = curves * (patch ? RECORD_BYTES : INSTANCE_STRIDE);
        const shape = name + ":" + size;
        if (predecessor && predecessor.rowsRun && predecessor.rowsRun.shape === shape) {
          inherit(slot, "rowsRun", predecessor.rowsRun, incoming);
        } else {
          if (size > (patch ? incoming.maxStorage : incoming.maxBuffer)) {
            throw new Error("row sources exceed device buffer limits");
          }
          const buffer = device.createBuffer({size,
            usage: GPUBufferUsage.STORAGE | GPUBufferUsage.VERTEX | GPUBufferUsage.COPY_DST});
          slot.rowsRun = { shape, name, buffer, owner: slot, state: null, buffers: [buffer] };
        }
        slot.rowBuffer = slot.rowsRun.buffer;
      }
      if (!patch) slot.rowStrokes = slot.rowBuffer;
    }
    if (border) {
      if (!program && !rows) slot.borderSource = holdStorage(slot, borderSources, border.key, border.definition);
      if (patch) slot.table = holdStorage(slot, objectTables, border.tableKey, border.tableBytes);
      computeUniforms(slot.set, incoming);
      if (!borderPipeline) borderPipeline = device.createComputePipeline({layout: "auto",
        compute: {module: modules.border_compute, entryPoint: "cs_main"}});
      const shape = [border.size, border.fillCount, border.capacity, border.count, patch].join(":");
      if (predecessor && predecessor.border && predecessor.border.shape === shape) {
        inherit(slot, "border", predecessor.border, incoming);
      } else {
        const buffer = device.createBuffer({size: border.size,
          usage: GPUBufferUsage.STORAGE | GPUBufferUsage.VERTEX | GPUBufferUsage.COPY_DST});
        slot.border = { shape, buffer, owner: slot, fillCount: border.fillCount, capacity: border.capacity,
          count: border.count, storageOffset: border.storageOffset, storageSize: border.storageSize,
          sourceBytes: border.length, binding: null, patchBinding: null, bound: null, table: null,
          chunks: null, camera: null, state: null, fill: null, source: null, buffers: [buffer] };
      }
      if (!patch) {
        slot.indexBuffer = slot.geometry.index || holdPattern(slot, slot.geometry, border.capacity, () => {
          const expanded = expandRunIndices(slot.geometry.fillIndices, border.runLayout, batch.fill_num_verts, border.capacity);
          if (expanded.length !== batch.count) throw new Error("invalid GPU border geometry layout or draw count");
          return expanded;
        });
      }
    }
    if (net) {
      // COPY_SRC: a dispatch of several nets gathers their control points (B5.5).
      if (!program) {
        slot.netSources = net.members.map(member => holdStorage(slot, netSources, member.key, member.definition,
                                                                 GPUBufferUsage.STORAGE | GPUBufferUsage.COPY_SRC));
      }
      computeUniforms(slot.set, incoming);
      if (!netPipeline) netPipeline = device.createComputePipeline({layout: "auto",
        compute: {module: modules.net_compute, entryPoint: "cs_main"}});
      // An output taken over keeps each member's vertices where its span,
      // source and steps are the same (prepareCompute): the layout decides.
      const shape = net.size + "=" + net.members.map(member =>
        [member.nu, member.nv, member.channels, member.capacity].join(":")).join(",");
      if (predecessor && predecessor.net && predecessor.net.shape === shape) {
        inherit(slot, "net", predecessor.net, incoming);
      } else {
        const buffer = device.createBuffer({size: net.size,
          usage: GPUBufferUsage.STORAGE | GPUBufferUsage.VERTEX | GPUBufferUsage.COPY_DST});
        slot.net = { shape, buffer, owner: slot, size: net.size,
          members: net.members.map(({nu, nv, channels, capacity, patches, first, size, bytes}) =>
            ({ nu, nv, channels, capacity, patches, offset: first * batch.stride, size, sourceBytes: bytes })),
          binding: null, bound: null, states: null, sources: null, buffers: [buffer] };
      }
    }
    if (!border && !net && batch.indexed) slot.indexBuffer = slot.geometry.index;

    if (patch) {
      slot.patchDraw = makePatchDraw(slot, batch, samples, paint, border);
      return slot;
    }
    const material = (pipeline, drawName) => textures
      ? holdTextureBinding(slot, drawName, samples, pipeline, textures)
      : paint ? holdBinding(slot, paintBindings, drawName + "@" + samples + ":" + paint.key, () => ({
          layout: pipeline.getBindGroupLayout(1),
          entries: [{ binding: 0, resource: { buffer: slot.paint.buffer } }] }))
      : null;
    for (const drawName of depthOnly ? [name, depthOnly] : [name]) {
      const pipeline = getPipeline(drawName, samples);
      slot.draws.push({ pipeline, uniform: setBinding(slot.set, pipeline), material: material(pipeline, drawName) });
    }
    return slot;
  }

  // Mark, strip mark, cover and strip cover, per group of one patch run:
  // consecutive objects sharing a stencil count draw as one instanced
  // group, the rest one object each.
  // The pipelines of a patch run, by sample count, depth and paint.
  function patchPipelines(samples, depth, painted) {
    const key = samples + (depth ? ":depth" : ":") + (painted ? ":paint" : ":");
    let set = patchPipelineSets.get(key);
    if (!set) {
      const suffix = depth ? "_depth" : "";
      const stripMark = "generated_surface" + suffix + "_strip_mark";
      const stripCover = "generated_" + (painted ? "paint" : "surface") + suffix + "_strip_cover";
      set = { markFan: patchPipeline("mark_fan", depth, samples), markPatch: patchPipeline("mark_patch", depth, samples),
              cover: patchPipeline(painted ? "cover_paint" : "cover", depth, samples),
              strips: [["mark", stripMark, getPipeline(stripMark, samples)],
                       ["cover", stripCover, getPipeline(stripCover, samples)]] };
      patchPipelineSets.set(key, set);
    }
    return set;
  }

  function makePatchDraw(slot, batch, samples, paint, border) {
    const depth = batch.pipeline.endsWith("_depth"), painted = "paint_hash" in batch;
    const layouts = patchBindLayouts(), set = patchPipelines(samples, depth, painted);
    const draw = { groups: patchGroups(border.runLayout), stripIndices: 6 * (border.capacity / 2 - 1),
      markFan: set.markFan, markPatch: set.markPatch, cover: set.cover,
      uniform: patchSetBinding(slot.set), paint: null, strips: null, index: null };
    if (painted) {
      draw.paint = holdBinding(slot, paintBindings, "patch:" + paint.key, () => ({ layout: layouts.group2,
        entries: [{ binding: 0, resource: { buffer: slot.paint.buffer } }] }));
    }
    if (border.runLayout.some(([, bordered]) => bordered)) {
      draw.strips = {};
      for (const [role, name, pipeline] of set.strips) {
        draw.strips[role] = { pipeline, uniform: setBinding(slot.set, pipeline),
          paint: role === "cover" && painted ? holdBinding(slot, paintBindings, name + "@" + samples + ":" + paint.key,
            () => ({ layout: pipeline.getBindGroupLayout(1),
                     entries: [{ binding: 0, resource: { buffer: slot.paint.buffer } }] })) : null };
      }
      draw.index = holdPattern(slot, slot.geometry, border.capacity, () => {
        const count = batch.border.num_curves, strips = border.capacity / 2 - 1;
        const out = new Uint32Array(6 * strips * count);
        let write = 0;
        for (let curve = 0; curve < count; curve++) {
          for (let strip = 0; strip < strips; strip++) {
            const v = border.capacity * curve + 2 * strip;
            out[write++] = v; out[write++] = v + 1; out[write++] = v + 2;
            out[write++] = v + 1; out[write++] = v + 2; out[write++] = v + 3;
          }
        }
        return out;
      });
    }
    return draw;
  }

  // Format 8 batches are format 7's (it adds the stream around them), so
  // slots resolved from either are kept across a change between them.
  const slotFormat = format => (format === 8 ? 7 : format ?? null);

  // The retained slots a frame may keep: none when they were resolved for
  // another sample count or format.
  function retainedSlots(header, incoming) {
    return frame.samples === incoming.samples && slotFormat(frame.format) === slotFormat(header.format_version)
      ? frame.slots : [];
  }

  // Diff a full frame against the retained slots, in order. A batch equal
  // to the slot at its position, or else to a retained slot of its hash,
  // keeps that slot; a batch that matches none takes over the next
  // unclaimed slot of its shape in place, keeping the outputs whose layout
  // still fits; the rest are new. Slots nothing claimed are released after
  // the submit (commit). The staging list it returns is swapped in only
  // once the frame is submitted; what it changes of the retained frame
  // meanwhile is a compute view made on a shared uniform set, which a
  // failed frame's rollback repacks.
  function applyFull(header, payload, incoming) {
    const batches = header.batches, serial = incoming.serial;
    const previous = retainedSlots(header, incoming);
    const slots = new Array(batches.length);
    let unmatched = null;
    for (let i = 0; i < batches.length; i++) {
      const old = previous[i];
      if (old !== undefined && !old.missing && sameBatch(batches[i], old.batch)) {
        old.frame = serial;
        slots[i] = old;
      } else {
        if (!unmatched) unmatched = [];
        unmatched.push(i);
      }
    }
    return resolveSlots(batches, previous, slots, unmatched, payload, incoming);
  }

  // A format 8 delta's frame against the retained slots (B4.8): a batch the
  // delta keeps (expandDelta's kept, the index of its retained slot) keeps
  // that slot without a comparison, since the engine sent nothing for it;
  // the batches its splices carry are matched as applyFull matches the
  // batches that differ from the slot in their place. Staged and rolled
  // back as a full frame is.
  function applyDelta(header, kept, payload, incoming) {
    const batches = header.batches, serial = incoming.serial;
    const previous = retainedSlots(header, incoming);
    const slots = new Array(batches.length);
    let unmatched = null;
    for (let i = 0; i < batches.length; i++) {
      const old = kept[i] >= 0 ? previous[kept[i]] : undefined;
      if (old !== undefined && !old.missing) {
        old.frame = serial;
        slots[i] = old;
      } else {
        if (!unmatched) unmatched = [];
        unmatched.push(i);
      }
    }
    return resolveSlots(batches, previous, slots, unmatched, payload, incoming);
  }

  // The slots of the batches the first pass left unmatched (a retained slot
  // of the same hash that is equal, else the next unclaimed one of the
  // same shape taken over, else a new one), then the per-frame checks of
  // every retained slot and the lists the compute stages walk.
  function resolveSlots(batches, previous, slots, unmatched, payload, incoming) {
    const serial = incoming.serial;
    if (unmatched) {
      const byHash = new Map(), byShape = new Map(), rest = [];
      for (const old of previous) {
        if (old.frame === serial || old.missing) continue;
        const list = byHash.get(old.batch.hash);
        if (list) list.push(old); else byHash.set(old.batch.hash, [old]);
      }
      for (const i of unmatched) {
        const list = byHash.get(batches[i].hash);
        const old = list && list.find(slot => slot.frame !== serial && sameBatch(batches[i], slot.batch));
        if (old) { old.frame = serial; slots[i] = old; } else rest.push(i);
      }
      for (const old of previous) {
        if (old.frame === serial || old.missing) continue;
        const list = byShape.get(old.shape);
        if (list) list.push(old); else byShape.set(old.shape, [old]);
      }
      for (const i of rest) {
        const list = byShape.get(shapeOf(batches[i]));
        slots[i] = makeSlot(batches[i], payload, incoming, list && list.length ? list.shift() : null);
      }
    }
    incoming.programSlots = []; incoming.borderSlots = []; incoming.netSlots = []; incoming.rowSlots = [];
    for (let i = 0; i < slots.length; i++) {
      const slot = slots[i], batch = batches[i];
      if (slot.missing) continue;
      if (slot.created !== serial) {
        // A retained slot takes this frame's scalars and density (the rest
        // of its descriptor is the one it was resolved from); a border
        // batch that resends its bytes or its run layout is checked again,
        // and must be laid out as the geometry it was resolved from.
        if (slot.programKey) validateScalars(batch.program);
        if (slot.net) {
          for (const member of isArray(batch.net) ? batch.net : [batch.net]) {
            const density = member.density;
            if (typeof density !== "number" || !Number.isFinite(density) || density < 0) {
              throw new Error("invalid surface net descriptor");
            }
          }
        }
        if (slot.border && (!batch.cached || "layout" in batch.border)) {
          const border = resolveBorder(batch, payload, incoming, slot.patch, slot.programKey ? batch.program : null,
                                       slot.rows);
          if (border && geometryDescriptor(batch, border.runLayout) !== slot.geometry.descriptor) {
            throw new Error("cached generated geometry layout changed");
          }
        }
      }
      if (slot.rows) incoming.rowSlots.push(i);
      if (slot.programKey) incoming.programSlots.push(i);
      if (slot.border) incoming.borderSlots.push(i);
      if (slot.net) incoming.netSlots.push(i);
    }
    return slots;
  }

  // A batch as a receiver holds it once its bytes were sent: no bytes of its
  // own, so no offsets, and no run layout, which travelled with the bytes
  // (generated_geometry.held_batch). Copied field by field rather than
  // spread and deleted from: a deleted property leaves V8 an object in
  // dictionary mode, and a slot's batch is read field by field every
  // frame a batch is matched against it (sameBatch).
  function heldBatch(batch) {
    if (batch.cached && !("offset" in batch) && !(batch.border && "layout" in batch.border)) return batch;
    const held = {};
    for (const key in batch) {
      if (key !== "offset" && key !== "index_offset" && key !== "cached") held[key] = batch[key];
    }
    held.cached = true;
    if (held.border && "layout" in held.border) {
      const border = {};
      for (const key in held.border) if (key !== "layout") border[key] = held.border[key];
      held.border = border;
    }
    return held;
  }

  // The frame a format 8 delta stands for (B4.8): the retained slots'
  // batches as a receiver holds them, the delta's splices applied (each
  // replaces `removed` batches from `at`, in the retained order, with the
  // batches it carries, whose offsets are into this message's payload),
  // its scalars ops written into the programs they name (by index in the
  // new frame, a batch the delta keeps), and each header field it leaves
  // out the stream's. Returns that header and, per batch, the index of the
  // retained slot it keeps, or -1 for a batch a splice carries.
  function expandDelta(delta, stream) {
    const previous = frame.slots, splices = delta.splices, ops = delta.scalars;
    if (!isArray(splices) || !isArray(ops) || delta.renderer !== stream.renderer) {
      throw new Error("invalid geometry delta");
    }
    const batches = [], kept = [];
    let read = 0;
    const keep = end => {
      for (; read < end; read++) { batches.push(heldBatch(previous[read].batch)); kept.push(read); }
    };
    for (const splice of splices) {
      if (!isArray(splice) || splice.length !== 3) throw new Error("invalid geometry delta splice");
      const [at, removed, inserted] = splice;
      if (!Number.isSafeInteger(at) || !Number.isSafeInteger(removed) || at < read || removed < 0
          || removed > previous.length - at || !isArray(inserted)) {
        throw new Error("invalid geometry delta splice");
      }
      keep(at);
      for (const batch of inserted) {
        if (batch === null || typeof batch !== "object" || isArray(batch)) throw new Error("invalid geometry delta splice");
        batches.push(batch);
        kept.push(-1);
      }
      read = at + removed;
    }
    keep(previous.length);
    for (const op of ops) {
      const [index, scalars] = isArray(op) && op.length === 2 ? op : [];
      const batch = Number.isSafeInteger(index) && kept[index] >= 0 ? batches[index] : null;
      if (!batch || batch.program === null || typeof batch.program !== "object" || isArray(batch.program)) {
        throw new Error("invalid geometry delta scalars");
      }
      batches[index] = {...batch, program: {...batch.program, scalars}};
    }
    const field = name => (name in delta ? delta[name] : stream[name]);
    const header = {format_version: delta.format_version, epoch: delta.epoch, frame: delta.frame,
      renderer: delta.renderer, camera: field("camera"), background: field("background"),
      resolution: field("resolution"), samples: field("samples"), supersample: field("supersample"), batches,
      paint_data: delta.paint_data ?? {}, border_data: delta.border_data ?? {}, object_data: delta.object_data ?? {},
      net_data: delta.net_data ?? {}, program_data: delta.program_data ?? {}, texture_data: delta.texture_data ?? {},
      unsupported: stream.unsupported, limitations: field("limitations")};
    return {header, kept};
  }

  // Ask the engine for a full frame (the geometry_reset a cache miss sends),
  // once per epoch: a delta taken against a frame this driver did not draw
  // (another epoch, another base), or one that failed, leaves every later
  // delta of its epoch unappliable.
  function resync(epoch) {
    if (frame.resync === epoch) return;
    frame.resync = epoch;
    if (ManimlWGPU.onCacheMiss) ManimlWGPU.onCacheMiss();
  }

  // A program's evaluated output, made for the slot that first evaluates
  // it: the rows, and for VMobject rows the curve records and stroke
  // instances row_finalize.wgsl writes.
  function makeProgramOutput(slot, program) {
    // COPY_SRC: the net stage gathers a program's rows (B5.5).
    const usage = GPUBufferUsage.STORAGE | GPUBufferUsage.VERTEX | GPUBufferUsage.COPY_DST | GPUBufferUsage.COPY_SRC;
    const rowBytes = program.rows * program.channels * 4;
    const curves = Math.max(0, Math.floor((program.rows - 1) / 2));
    const output = { rows: device.createBuffer({size: rowBytes, usage}), records: null, strokes: null,
      curves, rowBytes, finalize: program.channels === ROW_FLOATS && curves > 0, owner: slot, state: null,
      params: null, paramsBinding: null, io: null, sources: null, finalizeBindings: null, buffers: [] };
    output.buffers.push(output.rows);
    if (output.finalize) {
      output.records = device.createBuffer({size: curves * 176, usage});
      output.strokes = device.createBuffer({size: curves * 204, usage});
      output.buffers.push(output.records, output.strokes);
    }
    return output;
  }

  // A row source's finalized curve records and stroke instances, made by
  // the first slot that names the rows and finalized once (prepareCompute).
  function makeFinalizedRows(curves) {
    const usage = GPUBufferUsage.STORAGE | GPUBufferUsage.VERTEX | GPUBufferUsage.COPY_SRC;
    const records = device.createBuffer({size: curves * RECORD_BYTES, usage});
    const strokes = device.createBuffer({size: curves * INSTANCE_STRIDE, usage});
    return { records, strokes, curves, finalized: false, buffers: [records, strokes] };
  }

  // Blend the rows (one float per invocation, over two sources) or map one
  // source (one row per invocation), then finalize VMobject rows into curve
  // records and stroke instances. The kernel's parameters are rewritten in
  // place; its bindings are made once per output.
  function evaluateProgram(output, slot, program, encoder) {
    const {kind, scalars, rows, channels} = program, rowBytes = output.rowBytes;
    let params;
    if (kind === "blend") {
      params = new ArrayBuffer(16);
      const view = new DataView(params);
      view.setUint32(0, rows * channels, true); view.setFloat32(4, scalars[0], true);
    } else if (kind === "affine") {
      params = new ArrayBuffer(80);
      const view = new DataView(params);
      view.setUint32(0, rows, true); view.setUint32(4, channels, true);
      scalars.forEach((value, i) => view.setFloat32(16 + 4 * i, value, true));
    } else if (kind === "paint") {
      params = new ArrayBuffer(16);
      const view = new DataView(params);
      view.setUint32(0, rows, true); view.setFloat32(4, scalars[0], true); view.setFloat32(8, scalars[1], true);
    } else {
      params = new ArrayBuffer(32);
      const view = new DataView(params);
      const [lower, lowerResidue, upper, upperResidue, full] = scalars;
      [rows, Math.floor(rows / 2), lower, upper].forEach((value, i) => view.setUint32(4 * i, value, true));
      view.setFloat32(16, lowerResidue, true); view.setFloat32(20, upperResidue, true);
      view.setUint32(24, full, true);
    }
    const pipeline = programPipeline(kind === "blend" ? "row_blend" : "row_" + kind);
    if (!output.params) {
      output.params = makeBuffer(params, GPUBufferUsage.UNIFORM | GPUBufferUsage.COPY_DST);
      output.buffers.push(output.params);
      output.paramsBinding = device.createBindGroup({layout: pipeline.getBindGroupLayout(0), entries: [
        {binding: 0, resource: {buffer: output.params, size: params.byteLength}}]});
    } else {
      device.queue.writeBuffer(output.params, 0, params);
    }
    const sources = slot.sources.map(source => source.buffer);
    if (!output.sources || sources.some((buffer, i) => buffer !== output.sources[i])) {
      const entries = sources.map((buffer, binding) => ({binding, resource: {buffer, size: rowBytes}}));
      entries.push({binding: sources.length, resource: {buffer: output.rows, size: rowBytes}});
      output.io = device.createBindGroup({layout: pipeline.getBindGroupLayout(1), entries});
      output.sources = sources;
    }
    const compute = encoder.beginComputePass();
    compute.setPipeline(pipeline);
    compute.setBindGroup(0, output.paramsBinding);
    compute.setBindGroup(1, output.io);
    compute.dispatchWorkgroups(kind === "blend" ? Math.ceil(rows * channels / 256) : Math.ceil(rows / 64));
    if (output.finalize) {
      const finalize = programPipeline("row_finalize");
      if (!output.finalizeBindings) {
        const data = new ArrayBuffer(16), view = new DataView(data);
        view.setUint32(0, output.curves, true); view.setUint32(4, channels, true);
        const finalizeParams = makeBuffer(data, GPUBufferUsage.UNIFORM);
        output.buffers.push(finalizeParams);
        output.finalizeBindings = [
          device.createBindGroup({layout: finalize.getBindGroupLayout(0), entries: [
            {binding: 0, resource: {buffer: finalizeParams, size: 16}}]}),
          device.createBindGroup({layout: finalize.getBindGroupLayout(1), entries: [
            {binding: 0, resource: {buffer: output.rows, size: rowBytes}},
            {binding: 1, resource: {buffer: output.records, size: output.curves * 176}},
            {binding: 2, resource: {buffer: output.strokes, size: output.curves * 204}}]})];
      }
      compute.setPipeline(finalize);
      compute.setBindGroup(0, output.finalizeBindings[0]);
      compute.setBindGroup(1, output.finalizeBindings[1]);
      compute.dispatchWorkgroups(Math.ceil(output.curves / 64));
    }
    compute.end();
  }

  // Evaluate what changed before the ordered render pass: programs first,
  // whose outputs the border and net stages read, then borders, then nets,
  // each only where its state moved. States are recorded after the submit.
  function prepareCompute(incoming, slots, encoder, completed) {
    const batches = incoming.header.batches;
    // Row sources: every rows not yet finalized, in one pass, then each run
    // of several objects copied from its objects' outputs where it holds
    // other rows. A rows' outputs never change (it is named by content).
    let finalizing = null;
    for (const i of incoming.rowSlots) {
      for (const member of slots[i].rows) {
        if (member.output.finalized) continue;
        if (!finalizing) finalizing = new Map();
        finalizing.set(member.output, member.source);
      }
    }
    if (finalizing) {
      const pipeline = programPipeline("row_finalize");
      const compute = encoder.beginComputePass();
      compute.setPipeline(pipeline);
      for (const [output, source] of finalizing) {
        let params = finalizeParams.get(output.curves);
        if (!params) {
          const data = new ArrayBuffer(16), view = new DataView(data);
          view.setUint32(0, output.curves, true); view.setUint32(4, ROW_FLOATS, true);
          const buffer = makeBuffer(data, GPUBufferUsage.UNIFORM);
          params = { buffer, binding: device.createBindGroup({layout: pipeline.getBindGroupLayout(0), entries: [
            {binding: 0, resource: {buffer, size: 16}}]}) };
          finalizeParams.set(output.curves, params);
        }
        compute.setBindGroup(0, params.binding);
        compute.setBindGroup(1, device.createBindGroup({layout: pipeline.getBindGroupLayout(1), entries: [
          {binding: 0, resource: {buffer: source.buffer, size: source.bytes.length}},
          {binding: 1, resource: {buffer: output.records, size: output.curves * RECORD_BYTES}},
          {binding: 2, resource: {buffer: output.strokes, size: output.curves * INSTANCE_STRIDE}}]}));
        compute.dispatchWorkgroups(Math.ceil(output.curves / 64));
        completed.push([output, { finalized: true }]);
      }
      compute.end();
    }
    for (const i of incoming.rowSlots) {
      const slot = slots[i], run = slot.rowsRun;
      if (!run || run.state === slot.rowsKey) continue;
      const size = run.name === "records" ? RECORD_BYTES : INSTANCE_STRIDE;
      let offset = 0;
      for (const member of slot.rows) {
        encoder.copyBufferToBuffer(member.output[run.name], 0, run.buffer, offset, member.curves * size);
        offset += member.curves * size;
      }
      completed.push([run, { state: slot.rowsKey }]);
    }
    // The slots whose program is at the same state share one evaluation (an
    // object's fill and stroke, or objects moving alike), in the output of
    // a slot that already holds that state, or else of one that has an
    // output, or else of the first, which makes one.
    const groups = new Map();
    for (const i of incoming.programSlots) {
      const slot = slots[i], program = batches[i].program;
      const state = program.kind + ":" + program.scalars.join(",");
      const key = slot.programKey + "@" + state;
      let group = groups.get(key);
      if (!group) groups.set(key, group = { state, program, members: [] });
      group.members.push(slot);
    }
    for (const { state, program, members } of groups.values()) {
      const evaluator = members.find(slot => slot.program && slot.program.state === state)
        ?? members.find(slot => slot.program) ?? members[0];
      if (!evaluator.program) evaluator.program = makeProgramOutput(evaluator, program);
      const output = evaluator.program;
      for (const slot of members) { slot.programOutput = output; slot.programState = state; }
      if (output.state === state) continue;
      evaluateProgram(output, evaluator, program, encoder);
      completed.push([output, { state }]);
    }
    for (const i of incoming.borderSlots) {
      const slot = slots[i], output = slot.border, uniforms = slot.set.compute;
      if (!uniforms.borderValid) throw new Error("invalid GPU border generation uniforms");
      // A program-fed run reads the records of this frame's evaluation, a
      // run of row sources the records finalized from its rows.
      const source = slot.programKey ? slot.programOutput.records : slot.rows ? slot.rowBuffer
        : slot.borderSource.buffer;
      const state = slot.programKey ? uniforms.borderState + ";" + slot.programState
        : slot.rows ? uniforms.borderState + ";" + slot.rowsKey : uniforms.borderState;
      if (output.bound !== source || output.table !== slot.table) {
        output.binding = device.createBindGroup({layout: borderPipeline.getBindGroupLayout(1), entries: [
          {binding: 0, resource: {buffer: source, size: output.sourceBytes}},
          {binding: 1, resource: {buffer: output.buffer, offset: output.storageOffset, size: output.storageSize}}]});
        if (slot.patch) {
          // The patch vertex stage reads the curve records and the object
          // table; the strips draw this output as vertices.
          output.patchBinding = device.createBindGroup({layout: patchBindLayouts().group1, entries: [
            {binding: 0, resource: {buffer: source, size: output.sourceBytes}},
            {binding: 1, resource: {buffer: slot.table.buffer, size: slot.table.bytes.length}}]});
        }
        output.bound = source;
        output.table = slot.table;
      }
      const fill = slot.geometry.vertex;
      if (output.state === state && output.fill === fill && output.source === source) continue;
      if (output.fillCount && output.fill !== fill) {
        encoder.copyBufferToBuffer(fill, 0, output.buffer, 0, output.fillCount * 40);
      }
      if (!output.chunks) {
        output.chunks = [];
        for (let offset = 0; offset < output.count; offset += incoming.maxDispatch) {
          const chunk = Math.min(incoming.maxDispatch, output.count - offset);
          const data = new ArrayBuffer(32), view = new DataView(data);
          view.setUint32(0, offset, true); view.setUint32(4, chunk, true);
          view.setUint32(8, output.fillCount - output.storageOffset / 40 + output.capacity * offset, true);
          view.setFloat32(12, .0001, true);
          view.setUint32(16, output.capacity, true);
          const params = makeBuffer(data, GPUBufferUsage.UNIFORM);
          output.buffers.push(params);
          output.chunks.push({ params, count: chunk, binding: null });
        }
      }
      if (output.camera !== uniforms.buffer) {
        for (const chunk of output.chunks) {
          chunk.binding = device.createBindGroup({layout: borderPipeline.getBindGroupLayout(0), entries: [
            {binding: 0, resource: {buffer: uniforms.buffer, size: 192}},
            {binding: 1, resource: {buffer: chunk.params, size: 32}}]});
        }
        output.camera = uniforms.buffer;
      }
      const compute = encoder.beginComputePass();
      compute.setPipeline(borderPipeline);
      compute.setBindGroup(1, output.binding);
      for (const chunk of output.chunks) {
        compute.setBindGroup(0, chunk.binding);
        compute.dispatchWorkgroups(chunk.count);
      }
      compute.end();
      completed.push([output, { state, fill, source }]);
    }
    // Nets: every member whose steps or source moved, in one dispatch, and
    // each batch drawn with the pattern of the steps it is evaluated at
    // (B5.7), not its capacity's.
    const changed = [], height = incoming.header.resolution[1];
    for (const i of incoming.netSlots) {
      const slot = slots[i], output = slot.net, uniforms = slot.set.compute, net = batches[i].net;
      if (!uniforms.netValid) throw new Error("invalid surface net uniforms");
      const descriptors = isArray(net) ? net : [net], held = output.states, heldSources = output.sources;
      const states = [], sources = [], pattern = [];
      let moved = !held;
      output.members.forEach((member, m) => {
        const source = slot.programKey ? slot.programOutput.rows : slot.netSources[m].buffer;
        // A member depends on the camera through its steps alone: a pan, an
        // orbit or a zoom that moves no step count evaluates nothing.
        const steps = netSteps(descriptors[m].density, uniforms.floats[17], height, uniforms.floats[23],
                               member.capacity);
        const state = slot.programKey ? steps + ";" + slot.programState : String(steps);
        states.push(state); sources.push(source); pattern.push([member.patches, member.capacity, steps]);
        if (held && held[m] === state && heldSources[m] === source) return;
        moved = true;
        changed.push({ output, member, offset: member.offset, source, steps, sourceBytes: member.sourceBytes,
                       size: member.size, patches: member.patches });
      });
      if (moved) completed.push([output, { states, sources }]);
      const drawn = netPattern(pattern, incoming.serial);
      slot.indexBuffer = drawn.buffer;
      slot.count = drawn.count;
    }
    if (changed.length) evaluateNets(changed, encoder, incoming);
    else if (!incoming.netSlots.length) releaseNetScratch();
  }

  // The index buffer of a net batch's [patches, capacity, steps] members
  // (B5.7), shared by the batches drawn with the same members, stamped with
  // the frame that draws it (commit retires the ones its frame did not).
  function netPattern(members, serial) {
    const key = members.join(";");
    let entry = netPatterns.get(key);
    if (!entry) {
      const indices = netIndices(members);
      entry = { buffer: makeBuffer(indices.buffer, GPUBufferUsage.INDEX), count: indices.length, serial };
      netPatterns.set(key, entry);
    }
    entry.serial = serial;
    return entry;
  }

  // A scratch buffer of at least `size` bytes, grown by powers of two (never
  // past `limit`, the budget, but to `size`); one it outgrew is destroyed
  // after the submit, with the bind groups that named it.
  function netScratchBuffer(name, size, usage, limit = Infinity) {
    const held = netScratch.buffers[name];
    if (held && netScratch.sizes[name] >= size) return held;
    if (held) retired.push(held);
    if (name === "table") netScratch.tables.clear(); else netScratch.io = null;
    let bytes = 1 << 16;
    while (bytes < size) bytes *= 2;
    bytes = Math.max(size, Math.min(bytes, limit));
    netScratch.sizes[name] = bytes;
    return netScratch.buffers[name] = device.createBuffer({size: bytes, usage});
  }

  // The scratch belongs to frames that draw nets.
  function releaseNetScratch() {
    for (const buffer of Object.values(netScratch.buffers)) retired.push(buffer);
    netScratch.buffers = {};
    netScratch.sizes = {};
    netScratch.tables.clear();
    netScratch.io = null;
  }

  // Evaluate every changed net in one dispatch (docs/phase_b4_plan.md,
  // B5.5), as the native driver's _evaluate_nets does: their control points
  // gathered into one scratch buffer, the kernel evaluating every patch of
  // every net into another, and each net's vertices copied into its span of
  // the output its slot owns (a run's member after the members before it,
  // B5.7). A net alone in its dispatch (the one changed net, or one
  // larger than the budget) is read and written in place. The tables of a
  // frame's dispatches share one buffer, each at an aligned offset.
  function evaluateNets(changed, encoder, incoming) {
    const alignment = (device.limits || {}).minStorageBufferOffsetAlignment ?? 256;
    const budget = Math.min(NET_SCRATCH_BUDGET, incoming.maxStorage);
    const dispatches = planNets(changed, budget);
    let cursor = 0;
    for (const dispatch of dispatches) {
      dispatch.offset = cursor;
      dispatch.bytes = NET_TABLE_HEADER + NET_ENTRY_BYTES * dispatch.entries.length;
      cursor += Math.ceil(dispatch.bytes / alignment) * alignment;
    }
    const table = new ArrayBuffer(cursor), words = new Uint32Array(table);
    for (const dispatch of dispatches) {
      let at = dispatch.offset / 4;
      words[at] = dispatch.entries.length; words[at + 1] = dispatch.patches;
      at += 4;
      // A net alone in its dispatch writes in place, at its span of the
      // output it binds whole (a run's member after the members before it,
      // B5.7); the others write into the scratch.
      const direct = dispatch.entries.length === 1;
      for (const [index, sourceOffset, outputOffset, first] of dispatch.entries) {
        const {member, offset, steps} = changed[index];
        words.set([sourceOffset, direct ? offset / 4 : outputOffset, member.nu, member.nv, member.channels,
                   member.capacity, steps, first], at);
        at += 8;
      }
    }
    const tableBuffer = netScratchBuffer("table", cursor, GPUBufferUsage.STORAGE | GPUBufferUsage.COPY_DST);
    const gathered = dispatches.filter(dispatch => dispatch.entries.length > 1);
    let input = null, output = null;
    if (gathered.length) {
      input = netScratchBuffer("input", Math.max(...gathered.map(dispatch => dispatch.inputBytes)),
                               GPUBufferUsage.STORAGE | GPUBufferUsage.COPY_DST, budget);
      output = netScratchBuffer("output", Math.max(...gathered.map(dispatch => dispatch.outputBytes)),
                                GPUBufferUsage.STORAGE | GPUBufferUsage.COPY_SRC, budget);
      if (!netScratch.io) {
        netScratch.io = device.createBindGroup({layout: netPipeline.getBindGroupLayout(1), entries: [
          {binding: 0, resource: {buffer: input, size: netScratch.sizes.input}},
          {binding: 1, resource: {buffer: output, size: netScratch.sizes.output}}]});
      }
    }
    device.queue.writeBuffer(tableBuffer, 0, table);
    for (const dispatch of dispatches) {
      const width = Math.max(1, Math.min(dispatch.patches, incoming.maxDispatch));
      const rows = Math.ceil(dispatch.patches / width);
      if (rows > incoming.maxDispatch) throw new Error("surface nets exceed the device's dispatch limits");
      let group = netScratch.tables.get(dispatch.offset);
      if (!group) {
        group = device.createBindGroup({layout: netPipeline.getBindGroupLayout(0), entries: [
          {binding: 0, resource: {buffer: tableBuffer, offset: dispatch.offset, size: netScratch.sizes.table - dispatch.offset}}]});
        netScratch.tables.set(dispatch.offset, group);
      }
      const direct = dispatch.entries.length === 1;
      let binding = netScratch.io;
      if (direct) {
        const net = changed[dispatch.entries[0][0]], target = net.output;
        if (target.bound !== net.source) {
          target.binding = device.createBindGroup({layout: netPipeline.getBindGroupLayout(1), entries: [
            {binding: 0, resource: {buffer: net.source, size: net.sourceBytes}},
            {binding: 1, resource: {buffer: target.buffer, size: target.size}}]});
          target.bound = net.source;
        }
        binding = target.binding;
      } else {
        for (const [source, offset, size] of dispatch.sources) encoder.copyBufferToBuffer(source, 0, input, offset, size);
      }
      const compute = encoder.beginComputePass();
      compute.setPipeline(netPipeline);
      compute.setBindGroup(0, group);
      compute.setBindGroup(1, binding);
      compute.dispatchWorkgroups(width, rows);
      compute.end();
      if (!direct) {
        for (const [index, , outputOffset] of dispatch.entries) {
          const net = changed[index];
          encoder.copyBufferToBuffer(output, outputOffset * 4, net.output.buffer, net.offset, net.size);
        }
      }
    }
  }

  // What the encode loop has bound in the current pass: a call is made only
  // where it changes that.
  function passState() {
    return { pipeline: null, groups: [], vertex: null, index: null };
  }

  function usePipeline(pass, bound, pipeline) {
    if (bound.pipeline !== pipeline) { pass.setPipeline(pipeline); bound.pipeline = pipeline; }
  }

  function useGroup(pass, bound, index, group) {
    if (bound.groups[index] !== group) { pass.setBindGroup(index, group); bound.groups[index] = group; }
  }

  function useVertices(pass, bound, buffer) {
    if (bound.vertex !== buffer) { pass.setVertexBuffer(0, buffer); bound.vertex = buffer; }
  }

  function useIndices(pass, bound, buffer) {
    if (bound.index !== buffer) { pass.setIndexBuffer(buffer, "uint32"); bound.index = buffer; }
  }

  function encodePatch(pass, bound, slot) {
    const draw = slot.patchDraw, output = slot.border, strips = draw.strips, stripIndices = draw.stripIndices;
    if (strips) {
      useVertices(pass, bound, output.buffer);
      useIndices(pass, bound, draw.index);
    }
    for (const group of draw.groups) {
      const most = group.most;
      usePipeline(pass, bound, draw.markFan);
      useGroup(pass, bound, 0, draw.uniform);
      useGroup(pass, bound, 1, output.patchBinding);
      pass.draw(3 * most, group.count, 0, group.first);
      usePipeline(pass, bound, draw.markPatch);
      pass.draw(3 * most, group.count, 0, group.first);
      if (group.bordered) {
        usePipeline(pass, bound, strips.mark.pipeline);
        useGroup(pass, bound, 0, strips.mark.uniform);
        pass.setStencilReference(PATCH_STRIP_REFERENCE);
        pass.drawIndexed(stripIndices * group.curves, 1, stripIndices * group.firstCurve);
      }
      usePipeline(pass, bound, draw.cover);
      useGroup(pass, bound, 0, draw.uniform);
      useGroup(pass, bound, 1, output.patchBinding);
      if (draw.paint) useGroup(pass, bound, 2, draw.paint);
      pass.setStencilReference(0);
      pass.draw(PATCH_VERTICES_PER_CURVE * most, group.count, 0, group.first);
      if (group.bordered) {
        usePipeline(pass, bound, strips.cover.pipeline);
        useGroup(pass, bound, 0, strips.cover.uniform);
        if (strips.cover.paint) useGroup(pass, bound, 1, strips.cover.paint);
        pass.drawIndexed(stripIndices * group.curves, 1, stripIndices * group.firstCurve);
      }
    }
  }

  function encodeSlot(pass, bound, slot) {
    if (slot.patch) { encodePatch(pass, bound, slot); return; }
    // A program's stroke draws the instances it finalized, three rows per
    // curve, as a stroke of row sources draws theirs; a net or border draws
    // its evaluated output.
    const vertex = slot.strokes ? slot.programOutput.strokes : slot.rowStrokes ? slot.rowStrokes
      : slot.net ? slot.net.buffer : slot.border ? slot.border.buffer : slot.geometry.vertex;
    const index = slot.strokes || slot.rowStrokes ? null : slot.indexBuffer;
    for (const draw of slot.draws) {
      usePipeline(pass, bound, draw.pipeline);
      useGroup(pass, bound, 0, draw.uniform);
      if (draw.material) useGroup(pass, bound, 1, draw.material);
      useVertices(pass, bound, vertex);
      if (index) {
        useIndices(pass, bound, index);
        pass.drawIndexed(slot.count, slot.instances);
      } else {
        pass.draw(slot.count, slot.instances);
      }
    }
  }

  // After the submit: the staging list becomes the retained frame, the
  // slots it no longer has are released, the compute stages' states are
  // recorded, and what nothing holds is destroyed.
  function commit(incoming, slots, completed, message) {
    for (const [slot, output] of incoming.inherited) output.owner = slot;
    for (const slot of frame.slots) if (slot.frame !== incoming.serial) releaseSlot(slot);
    const batches = incoming.header.batches;
    for (let i = 0; i < slots.length; i++) slots[i].batch = batches[i];
    frame.slots = slots;
    frame.samples = incoming.samples;
    frame.format = incoming.header.format_version ?? null;
    frame.environment = incoming.environment;
    // A format 8 message is never sent twice (its frame number moves), and
    // a delta must not be redrawn past its base check: only a format 7
    // frame is kept for a redraw.
    const header = incoming.header, numbered = "epoch" in header;
    const redraw = !numbered && message.byteLength <= REDRAW_BYTES && slots.every(slot => !slot.missing);
    frame.message = redraw ? message : null;
    frame.header = redraw ? header : null;
    frame.stream = numbered ? {epoch: header.epoch, frame: header.frame, renderer: header.renderer,
      camera: header.camera, background: header.background, resolution: header.resolution, samples: header.samples,
      supersample: header.supersample, unsupported: header.unsupported, limitations: header.limitations} : null;
    for (const [output, state] of completed) Object.assign(output, state);
    for (const [key, entry] of netPatterns) {
      if (entry.serial === incoming.serial) continue;
      retired.push(entry.buffer);
      netPatterns.delete(key);
    }
    destroyRetired();
    for (const entry of looseTextures) {
      if (entry.refs) continue;
      textureCache.delete(entry.key);
      entry.texture.destroy();
    }
    looseTextures.clear();
  }

  // A frame that failed before its submit: the slots it made are released
  // (an output one took over is still its predecessor's), and the retained
  // slots are the last submitted frame's. The uniform sets they share are
  // not: the failed frame may have rewritten them for its own camera
  // (updateEnvironment, or a compute view made for a new slot), and those
  // writes reach the queue with the next submit. So no set is taken to
  // hold any camera, and the next frame repacks each set it draws with
  // (writeUniforms writes only the bits that differ from what was written).
  function rollback(incoming) {
    for (const slot of incoming.created) releaseSlot(slot);
    destroyRetired();
    frame.message = frame.header = null;
    frame.environment = null;
    for (const set of uniformSets.values()) set.environment = null;
  }

  function sameBytes(a, b) {
    if (a.byteLength !== b.byteLength) return false;
    const words = a.byteLength >> 2, x = new Uint32Array(a, 0, words), y = new Uint32Array(b, 0, words);
    for (let i = 0; i < words; i++) if (x[i] !== y[i]) return false;
    const tailA = new Uint8Array(a, words << 2), tailB = new Uint8Array(b, words << 2);
    for (let i = 0; i < tailA.length; i++) if (tailA[i] !== tailB[i]) return false;
    return true;
  }

  // The ordered render pass over the slots, then the present pass.
  function encodeFrame(encoder, slots, header) {
    const [r, g, b, a] = header.background;
    let pass = outPass(encoder, [r * a, g * a, b * a, a]), bound = passState();
    let coverageRef = 0;
    for (const slot of slots) {
      if (slot.coverage) {
        if (coverageRef === 255) {
          pass.end();
          pass = outPass(encoder, null, true);
          bound = passState();
          coverageRef = 0;
        }
        pass.setStencilReference(++coverageRef);
      }
      if (slot.patch && coverageRef) {
        // The count starts from zero; a coverage reference left by an
        // earlier object would be counted. Start clean.
        pass.end();
        pass = outPass(encoder, null, true);
        bound = passState();
        coverageRef = 0;
      }
      if (!slot.missing) encodeSlot(pass, bound, slot);
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
    const supersample = header.supersample ?? 2;
    const presentPipeline = supersample === 2 ? resolve2Pipeline : blitPipeline;
    let presentBinding = presentBindings.get(presentPipeline);
    if (!presentBinding) {
      const entries = [{ binding: 0, resource: (resolveView || outView) }];
      if (supersample === 1) entries.push({ binding: 1, resource: sampler });
      presentBinding = device.createBindGroup({
        layout: presentPipeline.getBindGroupLayout(0), entries,
      });
      presentBindings.set(presentPipeline, presentBinding);
    }
    blitPass.setPipeline(presentPipeline);
    blitPass.setBindGroup(0, presentBinding);
    blitPass.draw(3);
    blitPass.end();
  }

  // Draw one geometry message. The buffer is handed over: the driver keeps
  // the last one it drew to recognise the same message sent again, so a
  // caller does not write into it afterwards (the viewer and the player
  // hand over a fresh buffer per message).
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
    // The message the retained frame was drawn from, sent again (an idle
    // tick that changed no bytes): the full path would parse it, match every
    // batch to its slot and find nothing to evaluate, so the slots are
    // encoded as they stand.
    if (frame.message && sameBytes(arrayBuffer, frame.message)) {
      const encoder = device.createCommandEncoder();
      encodeFrame(encoder, frame.slots, frame.header);
      device.queue.submit([encoder.finish()]);
      return frame.header;
    }
    const bytes = new Uint8Array(arrayBuffer);
    const headerLen = new DataView(arrayBuffer, 1, 4).getUint32(0, true);
    const message = JSON.parse(
      new TextDecoder().decode(bytes.subarray(5, 5 + headerLen)));
    const vertexBytes = bytes.subarray(5 + headerLen);
    // Format 8 (docs/phase_b4_plan.md, B4.8): every message is numbered in
    // its epoch, and a delta applies only to the frame it was taken
    // against. One that was not, or a delta that fails, asks for a full
    // frame: every later delta of the epoch would fail with it. A full
    // frame that fails asks nothing, as a format 7 frame's failure does:
    // the full frame the engine would answer with is the same frame, so a
    // failure that repeats (an image the browser cannot decode, a device
    // limit) would have the two ask and answer for as long as the scene
    // rests. The stream stays where it stood, so the epoch's first delta
    // asks instead, once.
    const delta = "base" in message;
    if (delta && !(frame.stream && message.epoch === frame.stream.epoch && message.base === frame.stream.frame)) {
      resync(message.epoch);
      return null;
    }
    try {
      return await drawMessage(message, delta, vertexBytes, arrayBuffer);
    } catch (error) {
      if (delta) resync(message.epoch);
      throw error;
    }
  }

  async function drawMessage(message, delta, vertexBytes, arrayBuffer) {
    if ("epoch" in message && ![message.epoch, message.frame, delta ? message.base : 0].every(Number.isSafeInteger)) {
      throw new Error("invalid geometry stream numbering");
    }
    const {header, kept} = delta ? expandDelta(message, frame.stream) : {header: message, kept: null};
    const [width, height] = header.resolution;
    // "triangles" is the default stack, and Phase A's frames too (the engine
    // stamps its forced "phase_a" so, the bytes Phase A always wrote);
    // "phase_b" is the same format from the whole Phase B stack (patch
    // fills sent as rows, net surfaces, programs). This driver draws all
    // three.
    if (header.renderer !== "triangles" && header.renderer !== "phase_b") {
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

    const limits = device.limits || {};
    const alignment = limits.minStorageBufferOffsetAlignment ?? 256;
    const gcd = (a, b) => b ? gcd(b, a % b) : a;
    const incoming = { header, samples, supersample, serial: ++frame.serial,
      environment: JSON.stringify(header.camera) + "@" + supersample,
      maxBuffer: limits.maxBufferSize ?? 256 * 1024 ** 2,
      maxStorage: limits.maxStorageBufferBindingSize ?? 128 * 1024 ** 2,
      maxDispatch: limits.maxComputeWorkgroupsPerDimension ?? 65535,
      vertexAlignment: 40 * alignment / gcd(40, alignment),
      paints: null, programs: null, borders: null, tables: null, nets: null,
      created: [], inherited: [], programSlots: [], borderSlots: [], netSlots: [], rowSlots: [] };
    let submitted = false;
    try {
      incoming.paints = paintDefinitions(header, vertexBytes);
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
        const entry = { texture, buffers: [], cache: textureCache, key: texHash, refs: 0 };
        textureCache.set(texHash, entry);
        looseTextures.add(entry);
      }
      Object.assign(incoming, sourceDefinitions(header, vertexBytes));
      const slots = delta ? applyDelta(header, kept, vertexBytes, incoming) : applyFull(header, vertexBytes, incoming);
      updateEnvironment(incoming, slots);
      const encoder = device.createCommandEncoder();
      const completed = [];
      prepareCompute(incoming, slots, encoder, completed);
      encodeFrame(encoder, slots, header);
      device.queue.submit([encoder.finish()]);
      submitted = true;
      commit(incoming, slots, completed, arrayBuffer);
    } finally {
      if (!submitted) rollback(incoming);
    }
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
        for (const slot of frame.slots) releaseSlot(slot);
        frame.slots = [];
        frame.samples = frame.format = frame.environment = frame.message = frame.header = null;
        frame.stream = frame.resync = null;
        releaseNetScratch();
        for (const entry of netPatterns.values()) retired.push(entry.buffer);
        netPatterns.clear();
        destroyRetired();
        for (const entry of textureCache.values()) entry.texture.destroy();
        textureCache.clear();
        looseTextures.clear();
        // Every shared resource went with the slots that held it; anything
        // left is destroyed with the device.
        for (const cache of [generatedGeometry, indexPatterns, uniformSets, generatedPaints, paintBindings,
                             textureBindings, borderSources, objectTables, netSources, programSources,
                             finalizedRows]) {
          for (const entry of cache.values()) for (const buffer of entry.buffers) buffer.destroy();
          cache.clear();
        }
        for (const params of finalizeParams.values()) params.buffer.destroy();
        finalizeParams.clear();
        programPipelines.clear();
        borderPipeline = netPipeline = null;
        patchLayouts = null;
        patchPipelineSets.clear();
        presentBindings.clear();
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

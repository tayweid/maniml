// Stage-2 experimental client renderer: draws geometry snapshots
// (message type 0x03) with WebGL2 using the shared shaders in glsl/.
// This file mirrors maniml/web/reference_renderer.py — same buffer
// layouts, same pass sequence; keep the two in sync.
"use strict";

const ManimlGL = (() => {
  const VERTEX_STRIDE = 68;
  const INSTANCE_STRIDE = 3 * VERTEX_STRIDE; // one instance per bezier triple

  // [name, components, byte offset] — matches reference_renderer.py
  const FILL_ATTRS = [
    ["p0", 3, 0], ["c0", 4, 36], ["base_point", 3, 52],
    ["p1", 3, 68], ["c1", 4, 104], ["unit_normal", 3, 120],
    ["p2", 3, 136], ["c2", 4, 172],
  ];
  const STROKE_ATTRS = [
    ["p0", 3, 0], ["rgba0", 4, 12], ["width0", 1, 28], ["ja0", 1, 32],
    ["p1", 3, 68], ["rgba1", 4, 80], ["width1", 1, 96],
    ["unit_normal1", 3, 120],
    ["p2", 3, 136], ["rgba2", 4, 148], ["width2", 1, 164], ["ja2", 1, 168],
  ];
  const BORDER_ATTRS = [
    ["p0", 3, 0], ["ja0", 1, 32], ["rgba0", 4, 36], ["width0", 1, 64],
    ["p1", 3, 68], ["rgba1", 4, 104], ["unit_normal1", 3, 120],
    ["p2", 3, 136], ["ja2", 1, 168], ["rgba2", 4, 172], ["width2", 1, 200],
  ];

  const DOT_ATTRS = [["dot_point", 3, 0], ["dot_radius", 1, 12],
                     ["dot_rgba", 4, 16]];

  // Plain (non-instanced) TRIANGLES kinds: attributes + stride
  const PLAIN_ATTRS = {
    image: { stride: 24, attrs: [["point", 3, 0], ["im_coords", 2, 12],
                                 ["opacity", 1, 20]] },
    surface: { stride: 40, attrs: [["point", 3, 0],
                                   ["d_normal_point", 3, 12],
                                   ["rgba", 4, 24]] },
    texsurface: { stride: 36, attrs: [["point", 3, 0],
                                      ["d_normal_point", 3, 12],
                                      ["im_coords", 2, 24],
                                      ["opacity", 1, 32]] },
  };

  const UNIFORM_SETTERS = {
    glow_factor: (gl, loc, v) => gl.uniform1f(loc, v),
    num_textures: (gl, loc, v) => gl.uniform1f(loc, v),
    clip_plane: (gl, loc, v) => gl.uniform4fv(loc, v),
    view: (gl, loc, v) => gl.uniformMatrix4fv(loc, false, v),
    frame_rescale_factors: (gl, loc, v) => gl.uniform3fv(loc, v),
    camera_position: (gl, loc, v) => gl.uniform3fv(loc, v),
    light_position: (gl, loc, v) => gl.uniform3fv(loc, v),
    shading: (gl, loc, v) => gl.uniform3fv(loc, v),
    frame_scale: (gl, loc, v) => gl.uniform1f(loc, v),
    pixel_size: (gl, loc, v) => gl.uniform1f(loc, v),
    is_fixed_in_frame: (gl, loc, v) => gl.uniform1f(loc, v),
    anti_alias_width: (gl, loc, v) => gl.uniform1f(loc, v),
    joint_type: (gl, loc, v) => gl.uniform1f(loc, v),
    flat_stroke: (gl, loc, v) => gl.uniform1f(loc, v),
    scale_stroke_with_zoom: (gl, loc, v) => gl.uniform1f(loc, v),
  };

  let canvas = null, gl = null;
  let fillProgram, strokeProgram, compositeProgram, surfaceProgram, dotProgram;
  let plainPrograms = {};  // image / surface / texsurface
  const textureCache = new Map();  // texture content hash -> WebGLTexture
  let quadBuffer, fillTexture, fillFbo;
  let renderFbo, colorRb, depthRb;  // scene target: depth + optional MSAA
  let targetSize = null;

  async function fetchSource(...names) {
    const parts = ["#version 300 es", "precision highp float;",
                   "precision highp int;"];
    for (const name of names) {
      const resp = await fetch("glsl/" + name);
      if (!resp.ok) throw new Error("failed to fetch " + name);
      parts.push(await resp.text());
    }
    return parts.join("\n");
  }

  function compile(vertSource, fragSource) {
    const make = (type, source) => {
      const shader = gl.createShader(type);
      gl.shaderSource(shader, source);
      gl.compileShader(shader);
      if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
        throw new Error(gl.getShaderInfoLog(shader) + "\n" + source);
      }
      return shader;
    };
    const program = gl.createProgram();
    gl.attachShader(program, make(gl.VERTEX_SHADER, vertSource));
    gl.attachShader(program, make(gl.FRAGMENT_SHADER, fragSource));
    gl.linkProgram(program);
    if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
      throw new Error(gl.getProgramInfoLog(program));
    }
    return program;
  }

  async function init(canvasEl) {
    canvas = canvasEl;
    gl = canvas.getContext("webgl2", { antialias: false, alpha: false });
    if (!gl) throw new Error("WebGL2 unavailable");
    // Float render target for the winding-number fill pass
    if (!gl.getExtension("EXT_color_buffer_float")) {
      throw new Error("EXT_color_buffer_float unavailable");
    }
    gl.enable(gl.BLEND);

    const [fillVert, fillFrag, strokeVert, strokeFrag, compVert, compFrag,
           surfVert, surfFrag] =
      await Promise.all([
        fetchSource("common.glsl", "vfill.vert"), fetchSource("vfill.frag"),
        fetchSource("common.glsl", "vstroke.vert"),
        fetchSource("vstroke.frag"),
        fetchSource("composite.vert"), fetchSource("composite.frag"),
        fetchSource("common.glsl", "vsurface.vert"),
        fetchSource("vsurface.frag"),
      ]);
    const [dotVert, dotFrag, imgVert, imgFrag, tsVert, tsFrag] =
      await Promise.all([
        fetchSource("common.glsl", "vdot.vert"),
        fetchSource("common.glsl", "vdot.frag"),
        fetchSource("common.glsl", "vimage.vert"),
        fetchSource("vimage.frag"),
        fetchSource("common.glsl", "vtexsurface.vert"),
        fetchSource("common.glsl", "vtexsurface.frag"),
      ]);
    fillProgram = compile(fillVert, fillFrag);
    strokeProgram = compile(strokeVert, strokeFrag);
    compositeProgram = compile(compVert, compFrag);
    surfaceProgram = compile(surfVert, surfFrag);
    dotProgram = compile(dotVert, dotFrag);
    plainPrograms = {
      image: compile(imgVert, imgFrag),
      surface: surfaceProgram,
      texsurface: compile(tsVert, tsFrag),
    };

    quadBuffer = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, quadBuffer);
    gl.bufferData(gl.ARRAY_BUFFER,
      new Float32Array([0, 0, 0, 1, 1, 0, 1, 1]), gl.STATIC_DRAW);
  }

  function ensureTargets(width, height, samples) {
    const key = width + "x" + height + "@" + samples;
    if (targetSize === key) return;
    targetSize = key;
    canvas.width = width;
    canvas.height = height;
    for (const rb of [colorRb, depthRb]) if (rb) gl.deleteRenderbuffer(rb);
    for (const fb of [fillFbo, renderFbo]) if (fb) gl.deleteFramebuffer(fb);
    if (fillTexture) gl.deleteTexture(fillTexture);
    fillTexture = gl.createTexture();
    gl.bindTexture(gl.TEXTURE_2D, fillTexture);
    gl.texStorage2D(gl.TEXTURE_2D, 1, gl.RGBA16F, 2 * width, 2 * height);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    fillFbo = gl.createFramebuffer();
    gl.bindFramebuffer(gl.FRAMEBUFFER, fillFbo);
    gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0,
      gl.TEXTURE_2D, fillTexture, 0);
    // Scene target: depth always present; multisampled when the native
    // camera is (ThreeDCamera: samples=4). Blitted to the canvas at end.
    const storage = (rb, format) => {
      gl.bindRenderbuffer(gl.RENDERBUFFER, rb);
      if (samples > 0) {
        gl.renderbufferStorageMultisample(gl.RENDERBUFFER, samples, format,
          width, height);
      } else {
        gl.renderbufferStorage(gl.RENDERBUFFER, format, width, height);
      }
    };
    colorRb = gl.createRenderbuffer();
    storage(colorRb, gl.RGBA8);
    depthRb = gl.createRenderbuffer();
    storage(depthRb, gl.DEPTH_COMPONENT24);
    renderFbo = gl.createFramebuffer();
    gl.bindFramebuffer(gl.FRAMEBUFFER, renderFbo);
    gl.framebufferRenderbuffer(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0,
      gl.RENDERBUFFER, colorRb);
    gl.framebufferRenderbuffer(gl.FRAMEBUFFER, gl.DEPTH_ATTACHMENT,
      gl.RENDERBUFFER, depthRb);
    gl.bindFramebuffer(gl.FRAMEBUFFER, null);
  }

  function setUniforms(program, values) {
    for (const [name, setter] of Object.entries(UNIFORM_SETTERS)) {
      if (!(name in values)) continue;
      const loc = gl.getUniformLocation(program, name);
      if (loc !== null) setter(gl, loc, values[name]);
    }
  }

  function makeVao(program, buffer, attrs) {
    const vao = gl.createVertexArray();
    gl.bindVertexArray(vao);
    gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
    for (const [name, size, offset] of attrs) {
      const loc = gl.getAttribLocation(program, name);
      if (loc < 0) continue;
      gl.enableVertexAttribArray(loc);
      gl.vertexAttribPointer(loc, size, gl.FLOAT, false, INSTANCE_STRIDE,
        offset);
      gl.vertexAttribDivisor(loc, 1);
    }
    gl.bindVertexArray(null);
    return vao;
  }

  function parseMessage(arrayBuffer) {
    const bytes = new Uint8Array(arrayBuffer);
    const headerLen = new DataView(arrayBuffer, 1, 4).getUint32(0, true);
    const header = JSON.parse(
      new TextDecoder().decode(bytes.subarray(5, 5 + headerLen)));
    return { header, vertexBytes: bytes.subarray(5 + headerLen) };
  }

  // Delta-encoding cache: batch content hash -> GPU resources.
  // LRU-capped; a "cached" batch we no longer hold triggers onCacheMiss
  // (index.html wires it to a geometry_reset request) and is skipped
  // for one frame.
  const batchCache = new Map();
  const CACHE_MAX = 512;
  let cacheMissed = false;

  function freeResources(res) {
    for (const b of res.buffers) gl.deleteBuffer(b);
    for (const v of res.vaos) gl.deleteVertexArray(v);
  }

  function getResources(batch, builder) {
    let res = batchCache.get(batch.hash);
    if (res) {  // refresh recency
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
      freeResources(old);
    }
    return res;
  }

  async function render(arrayBuffer) {
    const { header, vertexBytes } = parseMessage(arrayBuffer);
    const [width, height] = header.resolution;
    ensureTargets(width, height, header.samples || 0);
    cacheMissed = false;

    // Decode any texture bytes shipped with this message (raw file
    // bytes — the browser's own decoder handles PNG/JPEG)
    for (const [texHash, ref] of Object.entries(header.texture_data || {})) {
      if (textureCache.has(texHash)) continue;
      const blob = new Blob([vertexBytes.subarray(
        ref.offset, ref.offset + ref.nbytes)]);
      const bitmap = await createImageBitmap(blob);
      const texture = gl.createTexture();
      gl.bindTexture(gl.TEXTURE_2D, texture);
      gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA,
        gl.UNSIGNED_BYTE, bitmap);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.REPEAT);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.REPEAT);
      bitmap.close();
      textureCache.set(texHash, texture);
    }

    gl.bindFramebuffer(gl.FRAMEBUFFER, renderFbo);
    gl.viewport(0, 0, width, height);
    gl.clearColor(...header.background);
    gl.clearDepth(1.0);
    gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
    gl.disable(gl.DEPTH_TEST);

    for (const batch of header.batches) {
      if (batch.kind === "vmobject") {
        renderVMobject(header, batch, vertexBytes, width, height);
      } else if (batch.kind === "dotcloud") {
        renderDotCloud(header, batch, vertexBytes, width, height);
      } else if (batch.kind in PLAIN_ATTRS) {
        renderPlain(header, batch, vertexBytes, width, height);
      }
    }
    gl.disable(gl.DEPTH_TEST);

    // Resolve/copy the scene target onto the canvas
    gl.bindFramebuffer(gl.READ_FRAMEBUFFER, renderFbo);
    gl.bindFramebuffer(gl.DRAW_FRAMEBUFFER, null);
    gl.blitFramebuffer(0, 0, width, height, 0, 0, width, height,
      gl.COLOR_BUFFER_BIT, gl.NEAREST);
    gl.bindFramebuffer(gl.FRAMEBUFFER, null);
    if (cacheMissed && ManimlGL.onCacheMiss) ManimlGL.onCacheMiss();
    return header;
  }

  function renderPlain(header, batch, vertexBytes, width, height) {
    // image / surface / texsurface: plain TRIANGLES over an
    // already-expanded vertex stream, optionally textured
    const program = plainPrograms[batch.kind];
    const { stride, attrs } = PLAIN_ATTRS[batch.kind];
    const res = getResources(batch, () => {
      const buffer = gl.createBuffer();
      gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
      gl.bufferData(gl.ARRAY_BUFFER, vertexBytes.subarray(
        batch.offset, batch.offset + batch.num_verts * stride),
        gl.STATIC_DRAW);
      const vao = gl.createVertexArray();
      gl.bindVertexArray(vao);
      for (const [name, size, off] of attrs) {
        const loc = gl.getAttribLocation(program, name);
        if (loc < 0) continue;
        gl.enableVertexAttribArray(loc);
        gl.vertexAttribPointer(loc, size, gl.FLOAT, false, stride, off);
      }
      gl.bindVertexArray(null);
      return { buffers: [buffer], vaos: [vao], vao };
    });
    if (!res) return;
    gl.bindFramebuffer(gl.FRAMEBUFFER, renderFbo);
    gl.viewport(0, 0, width, height);
    gl.useProgram(program);
    setUniforms(program, { ...header.camera, ...batch.uniforms });
    // Bind textures by sampler name, units in declaration order
    let unit = 0;
    for (const [name, texHash] of Object.entries(batch.textures || {})) {
      const texture = textureCache.get(texHash);
      if (!texture) { cacheMissed = true; return; }
      gl.activeTexture(gl.TEXTURE0 + unit);
      gl.bindTexture(gl.TEXTURE_2D, texture);
      const loc = gl.getUniformLocation(program, name);
      if (loc !== null) gl.uniform1i(loc, unit);
      unit += 1;
    }
    gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);
    gl.blendEquation(gl.FUNC_ADD);
    if (batch.depth_test) gl.enable(gl.DEPTH_TEST);
    else gl.disable(gl.DEPTH_TEST);
    gl.bindVertexArray(res.vao);
    gl.drawArrays(gl.TRIANGLES, 0, batch.num_verts);
    gl.bindVertexArray(null);
    gl.activeTexture(gl.TEXTURE0);
  }

  function renderDotCloud(header, batch, vertexBytes, width, height) {
    const res = getResources(batch, () => {
      const buffer = gl.createBuffer();
      gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
      gl.bufferData(gl.ARRAY_BUFFER, vertexBytes.subarray(
        batch.offset, batch.offset + batch.num_verts * 32), gl.STATIC_DRAW);
      const vao = gl.createVertexArray();
      gl.bindVertexArray(vao);
      for (const [name, size, off] of DOT_ATTRS) {
        const loc = gl.getAttribLocation(dotProgram, name);
        if (loc < 0) continue;
        gl.enableVertexAttribArray(loc);
        gl.vertexAttribPointer(loc, size, gl.FLOAT, false, 32, off);
        gl.vertexAttribDivisor(loc, 1);
      }
      gl.bindVertexArray(null);
      return { buffers: [buffer], vaos: [vao], vao };
    });
    if (!res) return;
    gl.bindFramebuffer(gl.FRAMEBUFFER, renderFbo);
    gl.viewport(0, 0, width, height);
    gl.useProgram(dotProgram);
    setUniforms(dotProgram, { ...header.camera, ...batch.uniforms });
    gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);
    gl.blendEquation(gl.FUNC_ADD);
    if (batch.depth_test) gl.enable(gl.DEPTH_TEST);
    else gl.disable(gl.DEPTH_TEST);
    gl.bindVertexArray(res.vao);
    gl.drawArraysInstanced(gl.TRIANGLE_STRIP, 0, 4, batch.num_verts);
    gl.bindVertexArray(null);
  }

  function renderVMobject(header, batch, vertexBytes, width, height) {
    const uniforms = { ...header.camera, ...batch.uniforms };
    const instances = batch.num_verts / 3;
    // The batch's tightest strip; the shader clamps per curve anyway
    const strokeVerts = batch.stroke_verts || 64;
    const res = getResources(batch, () => {
      const buffer = gl.createBuffer();
      gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
      gl.bufferData(gl.ARRAY_BUFFER, vertexBytes.subarray(
        batch.offset, batch.offset + batch.num_verts * VERTEX_STRIDE),
        gl.STATIC_DRAW);
      const out = {
        buffers: [buffer],
        vaos: [],
        fillVao: makeVao(fillProgram, buffer, FILL_ATTRS),
        strokeVao: makeVao(strokeProgram, buffer, STROKE_ATTRS),
        borderVao: makeVao(strokeProgram, buffer, BORDER_ATTRS),
        triVao: null, triCount: 0,
      };
      out.vaos.push(out.fillVao, out.strokeVao, out.borderVao);
      const tri = batch.tri;
      if (tri) {
        const vao = gl.createVertexArray();
        gl.bindVertexArray(vao);
        const vbo = gl.createBuffer();
        gl.bindBuffer(gl.ARRAY_BUFFER, vbo);
        gl.bufferData(gl.ARRAY_BUFFER, vertexBytes.subarray(
          tri.voffset, tri.voffset + tri.vcount * 40), gl.STATIC_DRAW);
        const surfAttrs = [["point", 3, 0], ["d_normal_point", 3, 12],
                           ["rgba", 4, 24]];
        for (const [name, size, off] of surfAttrs) {
          const loc = gl.getAttribLocation(surfaceProgram, name);
          if (loc < 0) continue;
          gl.enableVertexAttribArray(loc);
          gl.vertexAttribPointer(loc, size, gl.FLOAT, false, 40, off);
        }
        const ibo = gl.createBuffer();
        gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, ibo);
        gl.bufferData(gl.ELEMENT_ARRAY_BUFFER, vertexBytes.subarray(
          tri.ioffset, tri.ioffset + tri.icount * 4), gl.STATIC_DRAW);
        gl.bindVertexArray(null);
        out.buffers.push(vbo, ibo);
        out.vaos.push(vao);
        out.triVao = vao;
        out.triCount = tri.icount;
      }
      return out;
    });
    if (!res) return;
    const borderLoc = gl.getUniformLocation(strokeProgram, "border_mode");

    const drawTriangulatedFill = () => {
      // Port of render_triangulated_fill: real triangles with real z,
      // depth test forced on (as in the native path)
      if (!res.triVao) return;
      gl.bindFramebuffer(gl.FRAMEBUFFER, renderFbo);
      gl.viewport(0, 0, width, height);
      gl.useProgram(surfaceProgram);
      setUniforms(surfaceProgram, uniforms);
      gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);
      gl.blendEquation(gl.FUNC_ADD);
      gl.enable(gl.DEPTH_TEST);
      gl.bindVertexArray(res.triVao);
      gl.drawElements(gl.TRIANGLES, res.triCount, gl.UNSIGNED_INT, 0);
      gl.bindVertexArray(null);
    };

    const drawFill = () => {
      if (batch.fill_mode === "triangulated") { drawTriangulatedFill(); return; }
      // Pass sequence from VShaderWrapper.render_fill (2D branch);
      // the winding passes never depth-test
      gl.disable(gl.DEPTH_TEST);
      gl.bindFramebuffer(gl.FRAMEBUFFER, fillFbo);
      gl.viewport(0, 0, 2 * width, 2 * height);
      gl.clearColor(0, 0, 0, 0);
      gl.clear(gl.COLOR_BUFFER_BIT);
      gl.useProgram(fillProgram);
      setUniforms(fillProgram, uniforms);
      gl.blendFuncSeparate(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA,
        gl.ONE_MINUS_DST_ALPHA, gl.ONE);
      gl.bindVertexArray(res.fillVao);
      gl.drawArraysInstanced(gl.TRIANGLES, 0, 6, instances);
      // Fill border (stroke program over fill color/border width)
      gl.useProgram(strokeProgram);
      setUniforms(strokeProgram, uniforms);
      gl.uniform1f(borderLoc, 1.0);
      gl.blendFunc(gl.ONE, gl.ONE);
      gl.blendEquation(gl.MAX);
      gl.bindVertexArray(res.borderVao);
      gl.drawArraysInstanced(gl.TRIANGLE_STRIP, 0, strokeVerts, instances);
      // Composite onto the scene target
      gl.bindFramebuffer(gl.FRAMEBUFFER, renderFbo);
      gl.viewport(0, 0, width, height);
      gl.blendFunc(gl.ONE, gl.ONE_MINUS_SRC_ALPHA);
      gl.blendEquation(gl.FUNC_ADD);
      gl.useProgram(compositeProgram);
      gl.activeTexture(gl.TEXTURE0);
      gl.bindTexture(gl.TEXTURE_2D, fillTexture);
      gl.uniform1i(gl.getUniformLocation(compositeProgram, "Texture"), 0);
      gl.bindBuffer(gl.ARRAY_BUFFER, quadBuffer);
      const loc = gl.getAttribLocation(compositeProgram, "texcoord");
      gl.bindVertexArray(null);
      gl.enableVertexAttribArray(loc);
      gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);
      gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
      gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);
    };

    const drawStroke = () => {
      gl.bindFramebuffer(gl.FRAMEBUFFER, renderFbo);
      gl.viewport(0, 0, width, height);
      gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);
      gl.blendEquation(gl.FUNC_ADD);
      if (batch.depth_test) gl.enable(gl.DEPTH_TEST);
      else gl.disable(gl.DEPTH_TEST);
      gl.useProgram(strokeProgram);
      setUniforms(strokeProgram, uniforms);
      gl.uniform1f(borderLoc, 0.0);
      gl.bindVertexArray(res.strokeVao);
      gl.drawArraysInstanced(gl.TRIANGLE_STRIP, 0, strokeVerts, instances);
    };

    if (batch.stroke_behind) { drawStroke(); drawFill(); }
    else { drawFill(); drawStroke(); }

    gl.bindVertexArray(null);
  }

  return { init, render, onCacheMiss: null };
})();

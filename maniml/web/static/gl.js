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

  const UNIFORM_SETTERS = {
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
  let fillProgram, strokeProgram, compositeProgram;
  let quadBuffer, fillTexture, fillFbo;
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

    const [fillVert, fillFrag, strokeVert, strokeFrag, compVert, compFrag] =
      await Promise.all([
        fetchSource("common.glsl", "vfill.vert"), fetchSource("vfill.frag"),
        fetchSource("common.glsl", "vstroke.vert"),
        fetchSource("vstroke.frag"),
        fetchSource("composite.vert"), fetchSource("composite.frag"),
      ]);
    fillProgram = compile(fillVert, fillFrag);
    strokeProgram = compile(strokeVert, strokeFrag);
    compositeProgram = compile(compVert, compFrag);

    quadBuffer = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, quadBuffer);
    gl.bufferData(gl.ARRAY_BUFFER,
      new Float32Array([0, 0, 0, 1, 1, 0, 1, 1]), gl.STATIC_DRAW);
  }

  function ensureTargets(width, height) {
    const key = width + "x" + height;
    if (targetSize === key) return;
    targetSize = key;
    canvas.width = width;
    canvas.height = height;
    if (fillTexture) { gl.deleteTexture(fillTexture); }
    if (fillFbo) { gl.deleteFramebuffer(fillFbo); }
    fillTexture = gl.createTexture();
    gl.bindTexture(gl.TEXTURE_2D, fillTexture);
    gl.texStorage2D(gl.TEXTURE_2D, 1, gl.RGBA16F, 2 * width, 2 * height);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    fillFbo = gl.createFramebuffer();
    gl.bindFramebuffer(gl.FRAMEBUFFER, fillFbo);
    gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0,
      gl.TEXTURE_2D, fillTexture, 0);
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

  function render(arrayBuffer) {
    const { header, vertexBytes } = parseMessage(arrayBuffer);
    const [width, height] = header.resolution;
    ensureTargets(width, height);

    gl.bindFramebuffer(gl.FRAMEBUFFER, null);
    gl.viewport(0, 0, width, height);
    gl.clearColor(...header.background);
    gl.clear(gl.COLOR_BUFFER_BIT);

    for (const batch of header.batches) {
      if (batch.kind !== "vmobject") continue;
      renderVMobject(header, batch, vertexBytes, width, height);
    }
    return header;
  }

  function renderVMobject(header, batch, vertexBytes, width, height) {
    const uniforms = { ...header.camera, ...batch.uniforms };
    const instances = batch.num_verts / 3;
    const slice = vertexBytes.subarray(
      batch.offset, batch.offset + batch.num_verts * VERTEX_STRIDE);
    const buffer = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
    gl.bufferData(gl.ARRAY_BUFFER, slice, gl.STREAM_DRAW);

    const fillVao = makeVao(fillProgram, buffer, FILL_ATTRS);
    const strokeVao = makeVao(strokeProgram, buffer, STROKE_ATTRS);
    const borderVao = makeVao(strokeProgram, buffer, BORDER_ATTRS);
    const borderLoc = gl.getUniformLocation(strokeProgram, "border_mode");

    const drawFill = () => {
      // Pass sequence from VShaderWrapper.render_fill (2D branch)
      gl.bindFramebuffer(gl.FRAMEBUFFER, fillFbo);
      gl.viewport(0, 0, 2 * width, 2 * height);
      gl.clearColor(0, 0, 0, 0);
      gl.clear(gl.COLOR_BUFFER_BIT);
      gl.useProgram(fillProgram);
      setUniforms(fillProgram, uniforms);
      gl.blendFuncSeparate(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA,
        gl.ONE_MINUS_DST_ALPHA, gl.ONE);
      gl.bindVertexArray(fillVao);
      gl.drawArraysInstanced(gl.TRIANGLES, 0, 6, instances);
      // Fill border (stroke program over fill color/border width)
      gl.useProgram(strokeProgram);
      setUniforms(strokeProgram, uniforms);
      gl.uniform1f(borderLoc, 1.0);
      gl.blendFunc(gl.ONE, gl.ONE);
      gl.blendEquation(gl.MAX);
      gl.bindVertexArray(borderVao);
      gl.drawArraysInstanced(gl.TRIANGLE_STRIP, 0, 64, instances);
      // Composite onto the canvas
      gl.bindFramebuffer(gl.FRAMEBUFFER, null);
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
      gl.bindFramebuffer(gl.FRAMEBUFFER, null);
      gl.viewport(0, 0, width, height);
      gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);
      gl.blendEquation(gl.FUNC_ADD);
      gl.useProgram(strokeProgram);
      setUniforms(strokeProgram, uniforms);
      gl.uniform1f(borderLoc, 0.0);
      gl.bindVertexArray(strokeVao);
      gl.drawArraysInstanced(gl.TRIANGLE_STRIP, 0, 64, instances);
    };

    if (batch.stroke_behind) { drawStroke(); drawFill(); }
    else { drawFill(); drawStroke(); }

    gl.bindVertexArray(null);
    gl.deleteVertexArray(fillVao);
    gl.deleteVertexArray(strokeVao);
    gl.deleteVertexArray(borderVao);
    gl.deleteBuffer(buffer);
  }

  return { init, render };
})();

// Play a recorded frame stream through the shipped browser driver
// (maniml/web/static/webgpu.js) in Node on the counting fake device, and
// print what every frame cost in JavaScript and in WebGPU calls.
// benchmarks/browser_frames.py records the stream and reads this output;
// nothing here touches a GPU.
//
//     node benchmarks/browser_frames.cjs <stream directory> [--realm main]
//
// The directory is the export recorder's folder (scene.json + scene.bin.gz).
// A format 8 stream's (docs/phase_b4_plan.md, B4.8) holds a delta per
// message and a length-0 entry where the engine sent nothing: the page
// does nothing then, and its row is zeros. The frames are rendered in
// order, as the viewer receives them: through the
// viewer's renderer selection (renderer_selection.js), which routes each
// message by its header's renderer, into the driver. Each frame is timed
// twice with performance.now: js_ms around the driver's render (the header
// parse, the match against the retained slots, the compute stages, the
// encode loop, the fake submission and the release of what the frame no
// longer holds) and page_ms around the selection's, which adds the
// selection's own header parse (or, for a message the same as the one
// before, its comparison): what the page pays per message. The fake device
// validates nothing here (tests/webgpu_fake_device.cjs, validate: false), so
// the time is the page's own work. --realm main runs the driver and the
// selection in Node's own realm rather than a vm sandbox, where a global
// lookup costs what a browser's does (the device's options.realm).
"use strict";
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const zlib = require("node:zlib");
const {STATIC, driver} = require("../tests/webgpu_fake_device.cjs");

function loadStream(directory) {
  const meta = JSON.parse(fs.readFileSync(path.join(directory, "scene.json"), "utf8"));
  const data = zlib.gunzipSync(fs.readFileSync(path.join(directory, "scene.bin.gz")));
  const frames = [];
  let offset = 0;
  for (const frame of meta.frames) {
    if (!Number.isInteger(frame.len) || frame.len < 0 || offset + frame.len > data.length) {
      throw new Error("invalid frame length in the stream");
    }
    frames.push(frame.len ? data.buffer.slice(data.byteOffset + offset, data.byteOffset + offset + frame.len) : null);
    offset += frame.len;
  }
  if (offset !== data.length) throw new Error("incomplete stream");
  return frames;
}

// The viewer's renderer selection over the driver, in the driver's realm.
function selection(realm, drivers) {
  const source = fs.readFileSync(path.join(STATIC, "renderer_selection.js"), "utf8");
  const window = {};
  if (realm === "main") new Function("window", source)(window);
  else vm.runInNewContext(source, {window, TextDecoder});
  return new window.ManimlRendererSelection({}, drivers);
}

async function main(directory, realm) {
  const frames = loadStream(directory);
  const started = performance.now();
  const d = await driver({validate: false, realm});
  const init_ms = performance.now() - started;
  // The driver as the selection holds it (already initialized), timed.
  let js_ms = null;
  const timed = {init: async () => {}, destroy: async () => {}, async render(bytes) {
    const began = performance.now();
    try { return await d.renderer.render(bytes); } finally { js_ms = performance.now() - began; }
  }};
  const page = selection(realm, {triangles: timed, phase_b: timed});
  const headerOf = bytes => JSON.parse(new TextDecoder().decode(
    new Uint8Array(bytes, 5, new DataView(bytes, 1, 4).getUint32(0, true))));
  await page.select(headerOf(frames.find(bytes => bytes !== null)).renderer);
  const rows = [];
  let before = d.counts(), misses = d.cacheMisses(), shown = null;
  for (const [index, bytes] of frames.entries()) {
    if (bytes === null) {
      // Nothing was sent: the frame on screen stays, and the page runs no
      // JavaScript for it.
      const row = {index, js_ms: 0, page_ms: 0, wire_bytes: 0, header_bytes: 0, sent: false, ...shown,
        cache_misses: 0};
      for (const key of Object.keys(before)) row[key] = 0;
      rows.push(row);
      continue;
    }
    const began = performance.now();
    const header = await page.render(bytes);
    const page_ms = performance.now() - began;
    if (!header) throw new Error(`the renderer selection dropped frame ${index}`);
    const after = d.counts();
    shown = {batches: header.batches.length, cached_batches: header.batches.filter(batch => batch.cached).length};
    const row = {index, js_ms, page_ms, wire_bytes: bytes.byteLength,
      header_bytes: new DataView(bytes, 1, 4).getUint32(0, true), sent: true, ...shown,
      cache_misses: d.cacheMisses() - misses};
    const sent = headerOf(bytes);
    if ("base" in sent) {
      // A delta: its splices, the batches they carry, its scalars ops.
      Object.assign(row, {splices: sent.splices.length,
        spliced_batches: sent.splices.reduce((total, splice) => total + splice[2].length, 0),
        scalars_ops: sent.scalars.length});
    }
    for (const key of Object.keys(after)) row[key] = after[key] - before[key];
    before = after; misses = d.cacheMisses();
    rows.push(row);
  }
  await d.destroy();
  process.stdout.write(JSON.stringify({node: process.version, realm, init_ms, frames: rows}));
}

const realm = process.argv[3] === "--realm" ? process.argv[4] : "sandbox";
if (realm !== "sandbox" && realm !== "main") throw new Error("--realm is sandbox or main");
main(process.argv[2], realm).catch(error => { console.error(error); process.exitCode = 1; });

// Play a recorded frame stream through the shipped browser driver
// (maniml/web/static/webgpu.js) in Node on the counting fake device, and
// print what every frame cost in JavaScript and in WebGPU calls.
// benchmarks/browser_frames.py records the stream and reads this output;
// nothing here touches a GPU.
//
//     node benchmarks/browser_frames.cjs <stream directory>
//
// The directory is the export recorder's folder (scene.json + scene.bin.gz).
// The frames are rendered in order, as the viewer receives them, each timed
// with performance.now around the driver's render: the header parse, the
// prepare stages, the encode loop, the fake submission and the retirement
// sweeps. The fake device validates nothing here (tests/webgpu_fake_device.cjs,
// validate: false), so the time is the driver's own work.
"use strict";
const fs = require("node:fs");
const path = require("node:path");
const zlib = require("node:zlib");
const {driver} = require("../tests/webgpu_fake_device.cjs");

function loadStream(directory) {
  const meta = JSON.parse(fs.readFileSync(path.join(directory, "scene.json"), "utf8"));
  const data = zlib.gunzipSync(fs.readFileSync(path.join(directory, "scene.bin.gz")));
  const frames = [];
  let offset = 0;
  for (const frame of meta.frames) {
    if (!Number.isInteger(frame.len) || frame.len <= 0 || offset + frame.len > data.length) {
      throw new Error("invalid frame length in the stream");
    }
    frames.push(data.buffer.slice(data.byteOffset + offset, data.byteOffset + offset + frame.len));
    offset += frame.len;
  }
  if (offset !== data.length) throw new Error("incomplete stream");
  return frames;
}

async function main(directory) {
  const frames = loadStream(directory);
  const started = performance.now();
  const d = await driver({validate: false});
  const init_ms = performance.now() - started;
  const rows = [];
  let before = d.counts(), misses = d.cacheMisses();
  for (const [index, bytes] of frames.entries()) {
    const began = performance.now();
    const header = await d.renderer.render(bytes);
    const js_ms = performance.now() - began;
    const after = d.counts();
    const row = {index, js_ms, wire_bytes: bytes.byteLength,
      header_bytes: new DataView(bytes, 1, 4).getUint32(0, true),
      batches: header.batches.length,
      cached_batches: header.batches.filter(batch => batch.cached).length,
      cache_misses: d.cacheMisses() - misses};
    for (const key of Object.keys(after)) row[key] = after[key] - before[key];
    before = after; misses = d.cacheMisses();
    rows.push(row);
  }
  await d.destroy();
  process.stdout.write(JSON.stringify({node: process.version, init_ms, frames: rows}));
}

main(process.argv[2]).catch(error => { console.error(error); process.exitCode = 1; });

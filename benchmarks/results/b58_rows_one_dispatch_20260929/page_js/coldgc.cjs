// browser_frames.cjs's replay loop (the header parse and counts between
// frames included), recording the GC events that fall inside each cold
// message. Prints JSON {checkpoint: [ms, [[kind, ms], ...]]}.
"use strict";
const fs = require("node:fs"), path = require("node:path"), zlib = require("node:zlib");
const {PerformanceObserver, performance} = require("node:perf_hooks");
const {STATIC, driver} = require(process.env.FAKE);
const directory = process.argv[2];
const meta = JSON.parse(fs.readFileSync(path.join(directory, "scene.json"), "utf8"));
const data = zlib.gunzipSync(fs.readFileSync(path.join(directory, "scene.bin.gz")));
const frames = []; let offset = 0;
for (const f of meta.frames) { frames.push(f.len ? data.buffer.slice(data.byteOffset + offset, data.byteOffset + offset + f.len) : null); offset += f.len; }
const gcs = [];
new PerformanceObserver(list => { for (const e of list.getEntries()) gcs.push([e.startTime, e.duration, e.detail ? e.detail.kind : e.kind]); }).observe({entryTypes: ["gc"]});
(async () => {
  const d = await driver({validate: false, realm: "main"});
  const source = fs.readFileSync(path.join(STATIC, "renderer_selection.js"), "utf8"); const window = {};
  new Function("window", source)(window);
  const timed = {init: async () => {}, destroy: async () => {}, render: bytes => d.renderer.render(bytes)};
  const page = new window.ManimlRendererSelection({}, {triangles: timed, phase_a: timed, phase_b: timed});
  const headerOf = bytes => JSON.parse(new TextDecoder().decode(new Uint8Array(bytes, 5, new DataView(bytes, 1, 4).getUint32(0, true))));
  await page.select(headerOf(frames.find(b => b !== null)).renderer);
  const spans = [];
  for (const [i, bytes] of frames.entries()) {
    if (!bytes) continue;
    const t = performance.now();
    await page.render(bytes);
    const dt = performance.now() - t;
    d.counts(); headerOf(bytes);
    if (meta.frames[i].cold) spans.push([meta.frames[i].checkpoint, t, t + dt]);
  }
  await d.destroy();
  await new Promise(r => setTimeout(r, 50));
  const out = {};
  for (const [cp, a, b] of spans) out[cp] = [+(b - a).toFixed(2), gcs.filter(([s, dur]) => s >= a && s < b).map(([s, dur, kind]) => [kind, +dur.toFixed(2)])];
  process.stdout.write(JSON.stringify(out));
})();

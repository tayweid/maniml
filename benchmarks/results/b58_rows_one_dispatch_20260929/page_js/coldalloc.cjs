// Allocation sampling around a stream's cold messages, one pass (a fresh
// process). Prints the bytes allocated per function (self), in KB.
"use strict";
const fs = require("node:fs"), path = require("node:path"), zlib = require("node:zlib"), inspector = require("node:inspector");
const {STATIC, driver} = require(process.env.FAKE);
const directory = process.argv[2];
const meta = JSON.parse(fs.readFileSync(path.join(directory, "scene.json"), "utf8"));
const data = zlib.gunzipSync(fs.readFileSync(path.join(directory, "scene.bin.gz")));
const frames = []; let offset = 0;
for (const f of meta.frames) { frames.push(f.len ? data.buffer.slice(data.byteOffset + offset, data.byteOffset + offset + f.len) : null); offset += f.len; }
const session = new inspector.Session(); session.connect();
const post = (m, p) => new Promise((res, rej) => session.post(m, p || {}, (e, r) => e ? rej(e) : res(r)));
(async () => {
  await post("HeapProfiler.enable");
  const d = await driver({validate: false, realm: "main"});
  const source = fs.readFileSync(path.join(STATIC, "renderer_selection.js"), "utf8"); const window = {};
  new Function("window", source)(window);
  const timed = {init: async () => {}, destroy: async () => {}, render: bytes => d.renderer.render(bytes)};
  const page = new window.ManimlRendererSelection({}, {triangles: timed, phase_a: timed, phase_b: timed});
  const headerOf = bytes => JSON.parse(new TextDecoder().decode(new Uint8Array(bytes, 5, new DataView(bytes, 1, 4).getUint32(0, true))));
  await page.select(headerOf(frames.find(b => b !== null)).renderer);
  const self = new Map();
  const walk = node => {
    const key = `${node.callFrame.functionName || '(anon)'} ${node.callFrame.url.split('/').pop()}:${node.callFrame.lineNumber + 1}`;
    self.set(key, (self.get(key) || 0) + node.selfSize);
    for (const child of node.children) walk(child);
  };
  for (const [i, bytes] of frames.entries()) {
    if (!bytes) continue;
    const target = meta.frames[i].cold;
    if (target) await post("HeapProfiler.startSampling", {samplingInterval: 128, includeObjectsCollectedByMajorGC: true, includeObjectsCollectedByMinorGC: true});
    await page.render(bytes);
    if (target) { const {profile} = await post("HeapProfiler.stopSampling"); walk(profile.head); }
  }
  await d.destroy();
  let total = 0; for (const v of self.values()) total += v;
  console.log("total KB", (total / 1024).toFixed(0));
  [...self.entries()].sort((a, b) => b[1] - a[1]).slice(0, 22).forEach(([k, v]) => console.log((v / 1024).toFixed(0).padStart(8), k));
})();

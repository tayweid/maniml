// One pass of a stream in this process, as browser_frames.cjs plays a round
// (a fresh process, the driver behind renderer_selection.js), profiling only
// its cold messages. Prints JSON {wall, self: {function: ms}}.
"use strict";
const fs = require("node:fs"), path = require("node:path"), zlib = require("node:zlib"), inspector = require("node:inspector");
const {STATIC, driver} = require(process.env.FAKE);
const directory = process.argv[2], only = process.argv[3] ? new Set(process.argv[3].split(",").map(Number)) : null;
const meta = JSON.parse(fs.readFileSync(path.join(directory, "scene.json"), "utf8"));
const data = zlib.gunzipSync(fs.readFileSync(path.join(directory, "scene.bin.gz")));
const frames = []; let offset = 0;
for (const f of meta.frames) { frames.push(f.len ? data.buffer.slice(data.byteOffset + offset, data.byteOffset + offset + f.len) : null); offset += f.len; }
const session = new inspector.Session(); session.connect();
const post = (m, p) => new Promise((res, rej) => session.post(m, p || {}, (e, r) => e ? rej(e) : res(r)));
(async () => {
  await post("Profiler.enable"); await post("Profiler.setSamplingInterval", {interval: 25});
  const d = await driver({validate: false, realm: "main"});
  const source = fs.readFileSync(path.join(STATIC, "renderer_selection.js"), "utf8"); const window = {};
  new Function("window", source)(window);
  const timed = {init: async () => {}, destroy: async () => {}, render: bytes => d.renderer.render(bytes)};
  const page = new window.ManimlRendererSelection({}, {triangles: timed, phase_a: timed, phase_b: timed});
  const headerOf = bytes => JSON.parse(new TextDecoder().decode(new Uint8Array(bytes, 5, new DataView(bytes, 1, 4).getUint32(0, true))));
  await page.select(headerOf(frames.find(b => b !== null)).renderer);
  const self = {}; let wall = 0; const walls = {};
  for (const [i, bytes] of frames.entries()) {
    if (!bytes) continue;
    const f = meta.frames[i], target = f.cold && (!only || only.has(f.checkpoint));
    if (target && !process.env.NOPROF) await post("Profiler.start");
    const t = performance.now();
    await page.render(bytes);
    const dt = performance.now() - t;
    if (target) {
      wall += dt; walls[f.checkpoint] = dt;
      if (process.env.NOPROF) continue;
      const {profile} = await post("Profiler.stop");
      const counts = new Map(); profile.samples.forEach((id, k) => counts.set(id, (counts.get(id) || 0) + (profile.timeDeltas[k] || 0)));
      for (const n of profile.nodes) {
        const c = counts.get(n.id) || 0; if (!c) continue;
        const key = `${n.callFrame.functionName || '(anon)'} ${n.callFrame.url.split('/').pop()}:${n.callFrame.lineNumber + 1}`;
        self[key] = (self[key] || 0) + c / 1000;
      }
    }
  }
  await d.destroy();
  process.stdout.write(JSON.stringify({wall, walls, self}));
})();

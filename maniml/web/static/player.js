// The baked-scene player: replays a recorded geometry stream
// (scene.json + scene.bin, written by `maniml scene.py Scene --export`)
// through the same client renderers the live viewer uses. WebGPU when
// available, WebGL2 otherwise.
"use strict";

(async () => {
  const stage = document.getElementById("stage");
  const chipsEl = document.getElementById("chips");
  const playBtn = document.getElementById("playbtn");
  const statusEl = document.getElementById("status");

  const meta = await (await fetch("scene.json")).json();
  document.title = meta.scene;
  document.getElementById("scene-name").textContent = meta.scene;
  const compressed = await fetch("scene.bin.gz");
  const stream = compressed.body.pipeThrough(
    new DecompressionStream("gzip"));
  const data = new Uint8Array(await new Response(stream).arrayBuffer());

  // Split the container into per-frame messages
  const frames = [];
  let offset = 0;
  for (const frame of meta.frames) {
    frames.push({
      bytes: data.buffer.slice(offset, offset + frame.len),
      segment: frame.segment,
    });
    offset += frame.len;
  }
  // Segment k spans frames [starts[k], ends[k])
  const starts = [], ends = [];
  frames.forEach((frame, i) => {
    if (frame.segment >= 0 && starts[frame.segment] === undefined) {
      starts[frame.segment] = i;
    }
    if (frame.segment >= 0) ends[frame.segment] = i + 1;
  });

  // Pick a renderer: WebGPU, falling back to WebGL2
  const canvas = document.createElement("canvas");
  stage.appendChild(canvas);
  let renderer = null, backendName = "";
  try {
    await ManimlWGPU.init(canvas);
    renderer = ManimlWGPU; backendName = "WebGPU";
  } catch (err) {
    await ManimlGL.init(canvas);
    renderer = ManimlGL; backendName = "WebGL2";
  }
  statusEl.textContent = backendName;

  // Delta encoding means messages must be processed in order once so
  // every batch's buffers are cached; afterwards any frame renders
  // directly. Process everything up front (buffer uploads, fast).
  let processed = -1;
  async function show(i) {
    while (processed < i) {
      processed += 1;
      await renderer.render(frames[processed].bytes);
    }
    if (processed > i) await renderer.render(frames[i].bytes);
  }

  let current = 0;
  let playing = null;

  function stop() {
    if (playing) { clearInterval(playing); playing = null; }
    playBtn.textContent = "▶";
    refreshChips();
  }

  function playFrom(i, stopAt) {
    stop();
    playBtn.textContent = "⏸";
    current = i;
    playing = setInterval(async () => {
      if (current >= (stopAt ?? frames.length) - 1) { stop(); return; }
      current += 1;
      await show(current);
      refreshChips();
    }, 1000 / meta.fps);
  }

  function playSegment(k) {
    playFrom(starts[k] ?? 0, ends[k]);
  }

  function segmentOf(i) {
    return frames[i].segment;
  }

  function refreshChips() {
    chipsEl.replaceChildren();
    for (let k = 0; k < meta.segments; k++) {
      const chip = document.createElement("div");
      chip.className = "chip"
        + (segmentOf(current) === k ? " current" : "");
      chip.title = meta.lines[k] ? "line " + meta.lines[k] : "part " + (k + 1);
      chip.onclick = () => playSegment(k);
      chipsEl.appendChild(chip);
    }
  }

  playBtn.onclick = () => {
    if (playing) stop();
    else playFrom(current === frames.length - 1 ? 0 : current, null);
  };
  document.addEventListener("keydown", async (e) => {
    const seg = Math.max(0, segmentOf(current));
    if (e.key === "ArrowRight") {
      e.preventDefault();
      if (seg + 1 < meta.segments || segmentOf(current) === -1) {
        playSegment(segmentOf(current) === -1 ? 0 : seg + 1);
      }
    } else if (e.key === "ArrowLeft") {
      e.preventDefault();
      stop();
      current = Math.max(0, (starts[seg] ?? 1) - 1);
      await show(current);
      refreshChips();
    } else if (e.key === " ") {
      e.preventDefault();
      playBtn.onclick();
    }
  });

  await show(0);
  refreshChips();
})();

// The presentation player seeks to the frame that shows a checkpoint's
// state. The table's time is the scene's clock at the checkpoint, which is
// the time AFTER the checkpoint's last frame (each written frame advances
// the clock by one step), so a seek to the time itself lands one frame
// into the next animation; the player goes half a frame back (the rule
// test_present_bundle pins for ffmpeg's extraction). Driven on a fake
// video: the frame each seek lands on, at 24 fps, for checkpoints at 0, 1,
// 2 and 3 seconds, and the loop's lap range.
"use strict";
const path = require("path");
const assert = require("assert");
const ManimlPresentation = require(path.join(__dirname, "..", "maniml", "web", "static", "presentation.js"));

const video = { currentTime: 0 };
const meta = { fps: 24, checkpoints: [
  { index: 0, time: 0, stop: true },
  { index: 1, time: 1, stop: true },
  { index: 2, time: 2, stop: true },
  { index: 3, time: 3, stop: true, loop: true },
] };
ManimlPresentation.load(video, meta, {});
const frame = () => Math.floor(video.currentTime * meta.fps + 1e-9);
const landed = [];
for (const i of [0, 1, 2, 3]) { ManimlPresentation.seekCheckpoint(i); landed.push(frame()); }
assert.deepStrictEqual(landed, [0, 23, 47, 71], "each seek lands on the last frame of its play: " + landed);
assert.ok(video.currentTime < 3 && video.currentTime > 2.95, "half a frame before the clock, not a whole one");
ManimlPresentation.unload();
console.log("presentation seeks: ok " + JSON.stringify(landed));

// The presentation player: a <video> stepped by pausepoints.
//
// This is t1-web's Present.js model with generated inputs: instead of a
// hand-marked Pause_Points array, the pausepoints table carries every
// checkpoint's timestamp (from the states the checkpoint system already
// keeps), with stop/loop flags from pause() and the same chip mapping the
// live rail uses. Playback in BOTH directions is stepped scrubbing toward
// a target time — one file, no reversed encode, no play() drift — which
// the render's dense keyframes (-g fps) keep instant per seek.
//
// Position is a TRACKED INDEX, never derived from the clock: several
// checkpoints can share one timestamp (two pause() calls back to back),
// and deriving from time would land on whichever came last.
"use strict";

const ManimlPresentation = (() => {
  const STEP = 1 / 30;          // scrub step in seconds, and tick interval

  let video = null;
  let meta = null;
  let index = 0;                // the checkpoint we are at or leaving
  let targetIndex = 0;          // the checkpoint we are moving to
  let target = 0;               // its time
  let ticker = null;
  let loopRange = null;         // [from, to] while lapping a loop pause
  let callbacks = {};           // { onUpdate(i), onMove(from,to,back,unit), onRest(i) }

  function checkpoints() { return meta ? meta.checkpoints : []; }

  function nextStop() {
    return checkpoints().find((cp) => cp.stop && cp.index > index) || null;
  }

  function prevStop() {
    const before = checkpoints().filter((cp) => cp.stop && cp.index < index);
    return before.length ? before[before.length - 1] : null;
  }

  function tick() {
    if (!video || !meta) return;
    const now = video.currentTime;
    if (loopRange) {
      const [from, to] = loopRange;
      video.currentTime = now + STEP > to ? from : now + STEP;
      return;   // the rail holds at the loop pausepoint while lapping
    }
    if (index === targetIndex) return;   // parked
    const delta = target - now;
    if (Math.abs(delta) <= STEP) {
      if (now !== target) video.currentTime = target;
      arrive();
    } else {
      video.currentTime = now + Math.sign(delta) * STEP;
      // Deliberately no state report mid-move: the rail keeps the origin
      // chip held with the link lit, exactly like the live viewer — the
      // state lands only on arrival.
    }
  }

  function arrive() {
    index = targetIndex;
    const cp = checkpoints()[index];
    if (callbacks.onRest) callbacks.onRest(index);
    if (cp && cp.loop) {
      const from = prevStop();
      loopRange = [from ? from.time : 0, cp.time];
    }
  }

  function moveTo(cp, back) {
    if (!cp || !video) return;
    loopRange = null;
    targetIndex = cp.index;
    target = cp.time;
    if (callbacks.onMove) {
      callbacks.onMove(index, cp.index, back, cp.chip_unit);
    }
  }

  function park(newIndex) {
    const list = checkpoints();
    if (!list.length || !video) return;
    loopRange = null;
    index = targetIndex = Math.max(0, Math.min(list.length - 1, newIndex));
    target = list[index].time;
    video.currentTime = target;
    if (callbacks.onUpdate) callbacks.onUpdate(index);
  }

  return {
    load(videoElement, presentMeta, cb) {
      video = videoElement;
      meta = presentMeta;
      callbacks = cb || {};
      index = targetIndex = 0;
      target = 0;
      if (ticker === null) ticker = setInterval(tick, STEP * 1000);
    },
    unload() {
      if (ticker !== null) { clearInterval(ticker); ticker = null; }
      loopRange = null;
      video = null;
      meta = null;
    },
    playToNextStop() { moveTo(nextStop(), false); },
    playToPreviousStop() { moveTo(prevStop(), true); },
    stepCheckpoint(direction) { park(index + direction); },
    seekCheckpoint(checkpointIndex) { park(checkpointIndex); },
    togglePause() {
      // Space: freeze a scrub in place (the rail returns to the origin;
      // the frame stays where it stopped), or nothing when parked.
      if (!video) return;
      if (loopRange) { loopRange = null; return; }
      if (index !== targetIndex) {
        targetIndex = index;
        target = checkpoints()[index] ? checkpoints()[index].time : 0;
        if (callbacks.onRest) callbacks.onRest(index);
      }
    },
    currentIndex() { return index; },
  };
})();

// Node (the simulation harness) imports this file as CommonJS.
if (typeof module !== "undefined" && module.exports) {
  module.exports = ManimlPresentation;
}

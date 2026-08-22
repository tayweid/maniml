// The presentation player: a <video> stepped by pausepoints.
//
// This is t1-web's Present.js model with generated inputs: instead of a
// hand-marked Pause_Points array, present.json carries every checkpoint's
// timestamp (from the states the checkpoint system already keeps), with
// stop/loop flags from pause() and the same chip mapping the live rail
// uses. Playback in BOTH directions is stepped scrubbing toward a target
// time — one file, no reversed encode, no play() drift — which the
// render's dense keyframes (-g fps) keep instant per seek.
"use strict";

const ManimlPresentation = (() => {
  const STEP = 1 / 30;          // scrub step in seconds, and tick interval

  let video = null;
  let meta = null;
  let target = 0;
  let ticker = null;
  let loopRange = null;         // [from, to] while lapping a loop pause
  let callbacks = {};           // { onUpdate(index), onMove(from,to,back), onRest() }

  function checkpoints() { return meta ? meta.checkpoints : []; }

  function indexAt(t) {
    // The checkpoint in effect at time t: the last one at or before it.
    const list = checkpoints();
    let found = 0;
    for (const cp of list) {
      if (cp.time <= t + STEP / 2) found = cp.index;
      else break;
    }
    return found;
  }

  function nextStop(t) {
    return checkpoints().find((cp) => cp.stop && cp.time > t + STEP / 2) || null;
  }

  function prevStop(t) {
    const before = checkpoints().filter(
      (cp) => cp.stop && cp.time < t - STEP / 2);
    return before.length ? before[before.length - 1] : null;
  }

  function tick() {
    if (!video || !meta) return;
    const now = video.currentTime;
    if (loopRange) {
      const [from, to] = loopRange;
      video.currentTime = now + STEP > to ? from : now + STEP;
      report();
      return;
    }
    const delta = target - now;
    if (Math.abs(delta) <= STEP) {
      if (now !== target) video.currentTime = target;
      arrive();
    } else {
      video.currentTime = now + Math.sign(delta) * STEP;
    }
    report();
  }

  function arrive() {
    const cp = checkpoints()[indexAt(target)];
    if (callbacks.onMove) callbacks.onMove(null);       // stretch crossed
    if (cp && cp.loop) {
      const from = prevStop(cp.time);
      loopRange = [from ? from.time : 0, cp.time];
    } else if (callbacks.onRest) {
      callbacks.onRest(cp ? cp.index : 0);
    }
  }

  function report() {
    if (callbacks.onUpdate) callbacks.onUpdate(indexAt(video.currentTime));
  }

  function moveTo(cp, back) {
    if (!cp) return;
    loopRange = null;
    const fromIndex = indexAt(video.currentTime);
    target = cp.time;
    if (callbacks.onMove) {
      callbacks.onMove(fromIndex, cp.index, back, cp.chip_unit);
    }
  }

  return {
    load(videoElement, presentMeta, cb) {
      video = videoElement;
      meta = presentMeta;
      callbacks = cb || {};
      target = video.currentTime || 0;
      if (ticker === null) ticker = setInterval(tick, STEP * 1000);
    },
    unload() {
      if (ticker !== null) { clearInterval(ticker); ticker = null; }
      loopRange = null;
      video = null;
      meta = null;
    },
    playToNextStop() { moveTo(nextStop(target), false); },
    playToPreviousStop() { moveTo(prevStop(target), true); },
    stepCheckpoint(direction) {
      // UP/DOWN fine navigation: instant jump one checkpoint
      loopRange = null;
      const list = checkpoints();
      const index = Math.max(
        0, Math.min(list.length - 1, indexAt(target) + direction));
      target = list[index].time;
      if (video) video.currentTime = target;
      report();
    },
    seekCheckpoint(index) {
      loopRange = null;
      const cp = checkpoints()[index];
      if (!cp || !video) return;
      target = cp.time;
      video.currentTime = target;
      report();
    },
    togglePause() {
      // Space: freeze a scrub in place, or resume toward the target
      if (!video) return;
      if (loopRange) { loopRange = null; target = video.currentTime; return; }
      if (Math.abs(target - video.currentTime) > STEP) {
        target = video.currentTime;   // freeze
      }
    },
    currentIndex() { return video ? indexAt(video.currentTime) : 0; },
  };
})();

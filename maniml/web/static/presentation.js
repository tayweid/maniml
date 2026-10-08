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
//
// An arrow pressed while a stretch is being crossed acts at once rather
// than waiting for the move to land (Taylor, 2026-10-07: "pause the
// animation, skip ahead or back interrupting the animation while it
// runs ... i just don't want a forward arrow for example to pile up"):
// the arrow the move is going lands it on its pausepoint now, the other
// one returns it to the pausepoint it left. Either way the press ends the
// move on a pausepoint the move was between, so presses never pile up
// past the next one; a press after it lands is an ordinary move.
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
  let callbacks = {};           // { onUpdate(i), onMove(from,to,back,unit), onRest(i), onTime(t) }

  function checkpoints() { return meta ? meta.checkpoints : []; }

  // The frame that shows a checkpoint's state. The table's time is the
  // scene's clock at the checkpoint, which every frame advances by one
  // step as it is written — so it is the time AFTER the checkpoint's last
  // frame, and a seek to it lands on the next animation's first frame,
  // one frame ahead (Taylor, 2026-10-04). Half a frame back picks the
  // frame before that boundary whatever the rounding; the first
  // checkpoint stays at the movie's start.
  function frameTime(time) {
    const fps = (meta && meta.fps) || 30;
    return Math.max(0, time - 0.5 / fps);
  }

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
      // No state report mid-move: the rail keeps the origin held with the
      // stretch lit, exactly like the live viewer, and the state lands
      // only on arrival. The clock is reported, for the rail's head.
      if (callbacks.onTime) callbacks.onTime(video.currentTime);
    }
  }

  // A move in flight, ended now by an arrow: `forward` says which arrow.
  // The move's own direction lands it on its destination; the other
  // returns it to its origin. False when nothing is moving.
  function interrupt(forward) {
    if (!video || index === targetIndex) return false;
    const going = targetIndex > index;
    if (forward !== going) {
      targetIndex = index;
      target = checkpoints()[index] ? frameTime(checkpoints()[index].time) : 0;
    }
    video.currentTime = target;
    arrive();
    return true;
  }

  function arrive() {
    index = targetIndex;
    const cp = checkpoints()[index];
    if (callbacks.onRest) callbacks.onRest(index);
    if (cp && cp.loop) {
      const from = prevStop();
      loopRange = [from ? frameTime(from.time) : 0, frameTime(cp.time)];
    }
  }

  function moveTo(cp, back) {
    if (!cp || !video) return;
    loopRange = null;
    targetIndex = cp.index;
    target = frameTime(cp.time);
    if (callbacks.onMove) {
      callbacks.onMove(index, cp.index, back, cp.chip_unit);
    }
  }

  function park(newIndex) {
    const list = checkpoints();
    if (!list.length || !video) return;
    loopRange = null;
    // A seek mid-move (a click on the rail, UP/DOWN) ends the move: it
    // lands where it seeks, or the rail would hold the move open.
    const moving = index !== targetIndex;
    index = targetIndex = Math.max(0, Math.min(list.length - 1, newIndex));
    target = frameTime(list[index].time);
    video.currentTime = target;
    if (moving && callbacks.onRest) callbacks.onRest(index);
    else if (callbacks.onUpdate) callbacks.onUpdate(index);
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
    playToNextStop() { if (!interrupt(true)) moveTo(nextStop(), false); },
    playToPreviousStop() { if (!interrupt(false)) moveTo(prevStop(), true); },
    stepCheckpoint(direction) { park(index + direction); },
    // The mouse scrubbing the rail: the picture at any time, a move in
    // flight ended where it stood (the release parks with
    // seekCheckpoint, on the pausepoint the rail chose).
    scrubTo(time) {
      if (!video || !meta) return;
      loopRange = null;
      if (index !== targetIndex) {
        targetIndex = index;
        if (callbacks.onRest) callbacks.onRest(index);
      }
      video.currentTime = Math.max(0, time);
    },
    seekCheckpoint(checkpointIndex) { park(checkpointIndex); },
    togglePause() {
      // Space: freeze a scrub in place (the rail returns to the origin;
      // the frame stays where it stopped), or nothing when parked.
      if (!video) return;
      if (loopRange) { loopRange = null; return; }
      if (index !== targetIndex) {
        targetIndex = index;
        target = checkpoints()[index] ? frameTime(checkpoints()[index].time) : 0;
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

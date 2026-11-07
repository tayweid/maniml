// The presentation player: a <video> stepped by pausepoints.
//
// This is t1-web's Present.js model with generated inputs: instead of a
// hand-marked Pause_Points array, the pausepoints table carries every
// checkpoint's timestamp (from the states the checkpoint system already
// keeps), with stop/loop flags from pause() and the same chip mapping the
// live rail uses.
//
// A forward move PLAYS the video (play(), then pause() at the target); a
// reverse move scrubs it, one seek per tick, toward the target. Until
// 2026-11-06 both directions were stepped scrubbing — 30 seeks a second —
// which a desktop browser with the file buffered hides, and a phone does
// not: mobile WebKit fetches no media for a video no gesture has played
// (preload is ignored), so seeks drew nothing and the course pages' stage
// stayed blank, and once playing a seek costs it ~100 ms, so the picture
// froze or stuttered. play() from the tap is the gesture it wants, and
// the scrub now waits for each seek to land (`seeking`) and advances by
// the wall clock, so a slow device drops frames instead of piling seeks.
// A video without play() (the simulation's fake) is scrubbed both ways.
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
  const STEP = 1 / 30;          // tick interval in seconds (and the scrub's nominal step)

  let video = null;
  let meta = null;
  let index = 0;                // the checkpoint we are at or leaving
  let targetIndex = 0;          // the checkpoint we are moving to
  let target = 0;               // its time
  let ticker = null;
  let loopRange = null;         // [from, to] while lapping a loop pause
  let playing = false;          // the video is playing natively toward `target`
  let lastTick = 0;             // wall clock of the previous scrub tick (ms)
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

  function now() {
    return (typeof performance !== "undefined" && performance.now)
      ? performance.now() : Date.now();
  }

  function canPlay() { return !!video && typeof video.play === "function"; }

  // Start native playback toward `target`. A rejected play() (a browser
  // wanting a gesture it did not get) falls back to the scrub.
  function startPlaying() {
    if (!canPlay()) return false;
    playing = true;
    try {
      const p = video.play();
      if (p && typeof p.catch === "function") p.catch(() => { playing = false; });
    } catch (err) {
      playing = false;
    }
    return playing;
  }

  function stopPlaying() {
    if (playing && canPlay() && typeof video.pause === "function") video.pause();
    playing = false;
  }

  // One scrub step: the clock advanced by the wall time since the last
  // tick (so a device that lands seeks slowly still crosses the stretch
  // at speed), issued only once the previous seek has landed.
  function scrubStep(sign, limit) {
    const t = now();
    const elapsed = lastTick ? Math.min((t - lastTick) / 1000, 0.25) : STEP;
    lastTick = t;
    if (video.seeking) return video.currentTime;   // the last seek is still landing
    const next = video.currentTime + sign * elapsed;
    return sign > 0 ? Math.min(next, limit) : Math.max(next, limit);
  }

  function tick() {
    if (!video || !meta) return;
    const current = video.currentTime;
    if (loopRange) {
      const [from, to] = loopRange;
      if (playing) {
        if (current >= to || video.ended) { video.currentTime = from; startPlaying(); }
        else if (video.paused && !video.seeking) startPlaying();
      } else {
        video.currentTime = current + STEP > to ? from : scrubStep(1, to);
      }
      return;   // the rail holds at the loop pausepoint while lapping
    }
    if (index === targetIndex) return;   // parked
    const delta = target - current;
    if (playing) {
      if (delta <= 0 || video.ended) {
        stopPlaying();
        video.currentTime = target;
        arrive();
      } else {
        if (video.paused && !video.seeking) startPlaying();   // a stall, or a browser that paused us
        if (callbacks.onTime) callbacks.onTime(current);
      }
      return;
    }
    if (Math.abs(delta) <= STEP) {
      if (current !== target) video.currentTime = target;
      arrive();
    } else {
      video.currentTime = scrubStep(Math.sign(delta), target);
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
    stopPlaying();
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
      startPlaying();
    }
  }

  function moveTo(cp, back) {
    if (!cp || !video) return;
    stopPlaying();
    loopRange = null;
    targetIndex = cp.index;
    target = frameTime(cp.time);
    lastTick = now();
    // No state report mid-move: the rail keeps the origin held with the
    // stretch lit, exactly like the live viewer, and the state lands
    // only on arrival. The clock is reported, for the rail's head.
    if (callbacks.onMove) {
      callbacks.onMove(index, cp.index, back, cp.chip_unit);
    }
    // Forward plays; a target already behind the clock, or a reverse
    // move, is left to the scrub.
    if (!back && target > video.currentTime) startPlaying();
  }

  function park(newIndex) {
    const list = checkpoints();
    if (!list.length || !video) return;
    stopPlaying();
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
      playing = false;
      lastTick = 0;
      if (ticker === null) ticker = setInterval(tick, STEP * 1000);
    },
    unload() {
      if (ticker !== null) { clearInterval(ticker); ticker = null; }
      stopPlaying();
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
      stopPlaying();
      loopRange = null;
      if (index !== targetIndex) {
        targetIndex = index;
        if (callbacks.onRest) callbacks.onRest(index);
      }
      video.currentTime = Math.max(0, time);
    },
    seekCheckpoint(checkpointIndex) { park(checkpointIndex); },
    togglePause() {
      if (!video) return;
      // Space: freeze a move in place (the rail returns to the origin;
      // the frame stays where it stopped), or nothing when parked.
      if (loopRange) { stopPlaying(); loopRange = null; return; }
      if (index !== targetIndex) {
        stopPlaying();
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

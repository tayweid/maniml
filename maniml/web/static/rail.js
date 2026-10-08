// The rail, and the presenter that authors it.
//
// Extracted from viewer.html so the discipline is testable: a Node
// simulation (tests/rail_sim.cjs) replays message sequences against a
// DOM stub and asserts the classes. The rail has exactly one author —
// the presenter — and whichever frame source is active (the live engine
// or the recorded video) feeds it through the same methods, so live and
// playback modes cannot drift.
//
// The rail is Plass's and Knuth's scroll rail laid on its side (Taylor,
// 2026-10-07: "basically look exactly like the scrollbar in knuth and
// plass, but horizontal"): a hairline track, a band, and marks placed by
// one fraction each, `left: calc(var(--f) * 100%)`. The fraction is
// time: a pausepoint is a dot at the scene's clock when it was saved,
// the start and the end are upright dashes, and the plays between
// pausepoints (UP/DOWN's steps) are faint ticks. What has not run yet
// has no time, and none is guessed: those units stand at a small fixed
// interval after the last one that ran.
//
// The engine (or source) says which stretch is being crossed, and nothing
// about how far along it is: an animation's own progress is already on
// screen at full size. What the rail must do is stop claiming the
// position it is leaving, light the stretch for the whole move, and land
// only on arrival. A recording is the exception that proves it: its clock
// is the video's, so there the head rides the stretch (presenter.time).
"use strict";

const ManimlRail = (() => {

// px between the marks of units not yet run: nothing says how long they
// take, so they stand at a small fixed interval after the last one that
// ran (Taylor, 2026-10-07: "just place them at some small fixed
// interval"), and may take at most this share of the track.
const FUTURE_PX = 14;
const FUTURE_SHARE = 0.5;
// px either side of a mark, along the rail, within which the pointer
// takes it (Plass's rail hit-tests by the nearest mark the same way).
const HIT = 8;
// px a press moves along the rail before it is a scrub and not a click.
const DRAG = 3;

const fmt = (f) => String(Math.round(Math.max(0, Math.min(1, f)) * 1e6) / 1e6);
// The scene's clock as the preview card says it: 0:03.5, 1:12.0.
function clock(t) {
  const m = Math.floor(t / 60), s = t - 60 * m;
  return m + ":" + (s < 10 ? "0" : "") + s.toFixed(1);
}

function create(config) {
  const doc = config.document;
  const railEl = config.railEl;
  const body = config.body;
  const get = (id) => doc.getElementById(id);
  const env = config.env || (() => {});
  // The track's length in px: what the not-yet-run marks' fixed interval
  // is a share of. Read on every draw (a resize calls relayout).
  const width = config.width || (() => railEl.clientWidth || 400);

  const MIN_LIT_MS = 250;
  let move = null;
  let moveSince = 0;
  let moveClear = null;
  let playhead = null;   // a recording's clock while it crosses a stretch
  let scrubbed = null;   // the time under the pointer while it scrubs
  let shown = null;      // the drawn state, as the rail reads it (read())
  let names = [];        // checkpoint index -> pause('Title') name, or null
  let serials = [];      // checkpoint index -> the engine's checkpoint serial

  // -- The presenter --
  // hold the position while a stretch is being crossed (mid-move states
  // are pended, applied on arrival), light the stretch, lift the
  // position, land only when the move ends.
  const presenter = {
    moving: false,
    pending: null,
    stateChanged(state) {
      if (this.moving) {
        this.pending = state;
        env(state);    // badges and pickers may refresh mid-move
        return;
      }
      handleState(state);
    },
    moveStarted(from, to, back, unit) {
      this.moving = true;
      this.pending = null;
      handleMove({ from, to, back, unit });
    },
    moveEnded(landingState) {
      this.moving = false;
      playhead = null;
      handleMove({ from: null });
      const landing = landingState || this.pending;
      this.pending = null;
      if (landing) handleState(landing);
    },
    // A recording's clock, while it moves: the head follows it.
    time(t) {
      playhead = this.moving ? t : null;
      drawHead();
    },
    reset() { this.moving = false; this.pending = null; playhead = null; },
  };

  function handleState(state) {
    env(state);

    const future = state.future || [];
    const total = state.count + future.length;
    const current = Math.max(0, state.current);
    get("position-now").textContent = String(current + 1);
    get("position-total").textContent = " / " + Math.max(1, total);
    // Start (the Start chip's jump as a control, and the Home key) and
    // Back have nowhere to go from the start.
    get("start").disabled = current <= 0;
    get("previous").disabled = current <= 0;
    get("next").disabled = current >= total - 1;

    names = state.names || [];
    serials = state.serials || [];
    shown = read(state, future, current);
    draw();
  }

  // -- Reading a state --
  // Each checkpoint's time on the scene's clock, never decreasing; a
  // state without times (or a scene whose plays all took none) is spaced
  // by index instead, so the marks still stand apart.
  function read(state, future, current) {
    const count = Math.max(1, state.count);
    const given = state.times || [];
    let times = [];
    let last = 0;
    for (let i = 0; i < count; i++) {
      const t = Number(given[i]);
      last = Math.max(last, Number.isFinite(t) ? t : (given.length ? last : i));
      times.push(last);
    }
    if (count > 1 && times[count - 1] <= 0) times = times.map((_, i) => i);
    const stops = [];
    for (let i = 0; i < count; i++) {
      stops.push(i === 0 || !state.stops || state.stops[i] === undefined
        || !!state.stops[i]);
    }
    return { count, current: Math.min(current, count - 1), times, stops,
             lines: state.lines || [], future, T: times[count - 1] };
  }

  // -- One fraction maps everything --
  // A checkpoint that ran stands at its time over the last one's, within
  // the part of the track the run scene takes; the units not yet run
  // follow at FUTURE_PX apiece, and the run part gives them that room
  // (all of it while nothing has taken any time).
  function scale() {
    const W = Math.max(1, width());
    const n = shown.future.length;
    let room = 0;
    if (n) room = shown.T > 0 ? Math.min(n * FUTURE_PX, W * FUTURE_SHARE) : W;
    const ran = (W - room) / W;
    return {
      at: (t) => (shown.T > 0 ? Math.min(1, t / shown.T) * ran : 0),
      // The inverse, for a scrub: the time a fraction of the track stands
      // for (past the run part, the last checkpoint's).
      time: (f) => (shown.T > 0 && ran > 0
        ? Math.max(0, Math.min(1, f / ran)) * shown.T : 0),
      future: (j) => ran + (j + 1) * (room / W) / n,
      step: FUTURE_PX / W,
    };
  }

  // -- The DOM --
  // A span inset from the rail's ends holds the track (a hairline end to
  // end), the band, the head and the marks. The marks are pooled by their
  // order and rewritten in place, so a redraw moves each straight to its
  // new place (a CSS transition on left) instead of rebuilding the rail;
  // a unit that runs is the same element before and after, gliding from
  // its fixed slot to its time.
  let span = null, band = null, head = null;
  const marks = [];   // the ends, the pausepoints and the units not yet run
  const ticks = [];   // the plays between pausepoints
  let hot = null;     // the mark under the pointer
  const hotListeners = [];

  function setVar(el, name, value) {
    if (el.style.getPropertyValue(name) !== value) el.style.setProperty(name, value);
  }
  function drop(el) {
    if (el.remove) el.remove();
    else span.removeChild(el);
  }
  function build() {
    span = doc.createElement("div");
    span.className = "rail-span";
    span.setAttribute("role", "presentation");
    span.appendChild(doc.createElement("div")).className = "rail-track";
    band = span.appendChild(doc.createElement("div"));
    band.className = "rail-band";
    head = span.appendChild(doc.createElement("div"));
    head.className = "rail-head off";
    railEl.replaceChildren(span);
  }

  function draw() {
    if (!span) build();
    const s = scale();
    const { count, times, stops, future } = shown;
    const specs = [];
    const tickAt = [];
    let plays = 0;
    for (let i = 0; i < count; i++) {
      if (stops[i]) {
        specs.push({ index: i, f: s.at(times[i]), plays });
        plays = 0;
      } else {
        tickAt.push(s.at(times[i]));
        plays += 1;
      }
    }
    future.forEach((u, j) => specs.push(
      { unit: u.unit, line: u.line, many: !!u.many, f: s.future(j) }));

    while (marks.length < specs.length) {
      const mark = doc.createElement("button");
      mark.type = "button";
      mark.setAttribute("role", "listitem");
      span.appendChild(mark);
      marks.push(mark);
    }
    while (marks.length > specs.length) drop(marks.pop());
    if (hot && !marks.includes(hot)) setHot(null);
    specs.forEach((spec, k) => updateMark(marks[k], spec,
      k === 0 ? "start" : k === specs.length - 1 ? "end" : null));

    while (ticks.length < tickAt.length) {
      const tick = span.appendChild(doc.createElement("i"));
      tick.className = "tick";
      ticks.push(tick);
    }
    while (ticks.length > tickAt.length) drop(ticks.pop());
    tickAt.forEach((f, k) => setVar(ticks[k], "--f", fmt(f)));

    // The rail's length follows what it holds (the page's CSS reads it).
    setVar(railEl, "--marks", String(specs.length));
    drawBand();
    drawHead();
  }

  function updateMark(mark, spec, end) {
    const known = spec.index !== undefined;
    const current = known && spec.index === shown.current;
    mark.className = "mark" + (end ? " " + end : "") + (known ? "" : " future")
      + (current ? " current" : "") + (spec.many ? " many" : "")
      + (mark === hot ? " hot" : "");
    setVar(mark, "--f", fmt(spec.f));
    // The words go to the preview card (attachPreview), not a title
    // attribute: the browser's own tooltip would stand over the card.
    const label = describeSpec(spec);
    mark.dataset.detail = label;
    if (known) {
      mark.dataset.index = String(spec.index);
      delete mark.dataset.unit;
    } else {
      delete mark.dataset.index;
      mark.dataset.unit = String(spec.unit);
    }
    const name = known ? names[spec.index] : null;
    mark.setAttribute("aria-label", name ? name + " \u2014 " + label : label);
    if (current) mark.setAttribute("aria-current", "step");
    else mark.removeAttribute("aria-current");
    // A click parks browser focus on the button, and the mark survives
    // every redraw, so drop it: position feedback is the presenter's job.
    mark.onclick = () => {
      if (mark.blur) mark.blur();
      if (known) config.onChipClick(spec.index);
      else config.onFutureChipClick(spec.unit);
    };
  }

  function describeSpec(spec) {
    if (spec.index === undefined) {
      return spec.many
        ? "Runs to line " + spec.line + " \u00b7 a loop or branch, so how many "
          + "pausepoints it holds is not known until it runs"
        : "Runs to line " + spec.line;
    }
    if (spec.index === 0) return "Start";
    return "Pausepoint \u00b7 line " + shown.lines[spec.index]
      + " \u00b7 " + clock(shown.times[spec.index])
      + (spec.plays ? " \u00b7 " + spec.plays + " play step"
         + (spec.plays > 1 ? "s" : "") + " before it (\u2191\u2193)" : "");
  }

  // -- The band --
  // The stretch in question. At rest, the one the next RIGHT plays, faint,
  // as Plass's band is at rest; while a move crosses a stretch, that one,
  // lit, whichever way it runs.
  function drawBand() {
    if (!band || !shown) return;
    const s = scale();
    const { times, current } = shown;
    let a, b;
    if (move) {
      a = s.at(times[Math.min(move.from, shown.count - 1)]);
      b = destination(s);
    } else {
      a = s.at(times[current]);
      b = nextStop(s);
      if (b === null) b = a;
    }
    setVar(band, "--a", fmt(Math.min(a, b)));
    setVar(band, "--b", fmt(Math.max(a, b)));
    band.className = "rail-band" + (move ? " lit" : "")
      + (move && move.back ? " back" : "") + (a === b ? " empty" : "");
  }

  // Where the stretch after the position ends: the next pausepoint that
  // ran, else the first unit not yet run.
  function nextStop(s) {
    for (let i = shown.current + 1; i < shown.count; i++) {
      if (shown.stops[i]) return s.at(shown.times[i]);
    }
    return shown.future.length ? s.future(0) : null;
  }

  // Where a move lands. Forward through history, the pausepoint at or
  // after the play it names; at the frontier the destination does not
  // exist yet, which is what the unit answers: the mark of the unit
  // being run (or, a loop's next lap, one interval past the last).
  function destination(s) {
    const { count, stops, times, future } = shown;
    if (move.to < count) {
      let i = Math.max(0, move.to);
      if (move.back) { while (i > 0 && !stops[i]) i--; }
      else { while (i < count - 1 && !stops[i]) i++; }
      return s.at(times[i]);
    }
    const j = future.findIndex((u) => u.unit === move.unit);
    if (j >= 0) return s.future(j);
    if (future.length) return s.future(0);
    return Math.min(1, s.at(times[count - 1]) + s.step);
  }

  // -- The head --
  // The position where no pausepoint stands for it: parked between
  // pausepoints (UP/DOWN), a recording crossing a stretch, whose clock is
  // the video's, or the pointer scrubbing one.
  function drawHead() {
    if (!head || !shown) return;
    let f = null;
    if (scrubbed !== null) f = scale().at(scrubbed);
    else if (move && playhead !== null) f = scale().at(playhead);
    else if (!move && !shown.stops[shown.current]) {
      f = scale().at(shown.times[shown.current]);
    }
    head.className = "rail-head" + (f === null ? " off" : "");
    if (f !== null) setVar(head, "--f", fmt(f));
  }

  function applyMove() {
    body.classList.toggle("moving", !!move);
    drawBand();
    drawHead();
  }

  function handleMove(data) {
    clearTimeout(moveClear);
    if (data.from === null || data.from === undefined) {
      // Hold a short move lit long enough to be seen: a 0.3s play would
      // otherwise flicker the band on and off in one blink.
      const held = Math.max(0, MIN_LIT_MS - (performance.now() - moveSince));
      moveClear = setTimeout(() => { move = null; applyMove(); }, held);
      return;
    }
    move = { from: data.from, to: data.to, back: !!data.back, unit: data.unit };
    moveSince = performance.now();
    applyMove();
  }

  // -- The pointer --
  // The rail hit-tests by the nearest mark, as Plass's does: a 5 px dot
  // takes HIT px either side and the rail's whole height, and the marks
  // themselves take no pointer events. A key on a focused mark is the
  // mark's own click.
  function nearest(x) {
    let best = null, bestD = HIT;
    for (const mark of marks) {
      const box = mark.getBoundingClientRect();
      const d = Math.abs(box.left + box.width / 2 - x);
      if (d <= bestD) { best = mark; bestD = d; }   // a tie goes to the later
    }
    return best;
  }
  function setHot(mark) {
    if (mark === hot) return;
    if (hot) hot.classList.remove("hot");
    hot = mark;
    if (hot) hot.classList.add("hot");
    for (const listener of hotListeners) listener(hot);
  }
  // -- Scrubbing --
  // Where the page can seek to any time (a recording; config.scrub), a
  // press dragged along the rail scrubs it (Taylor, 2026-10-07: "the
  // ability to scrub through with the mouse in present mode"): the head
  // follows the pointer and the picture follows the head, and the
  // release lands on the checkpoint nearest in time, so the position is
  // a checkpoint again, as every other way of moving leaves it. A press
  // that moves less than DRAG px is a click.
  const scrub = config.scrub || null;
  let press = null;   // { x, id, dragging } from pointerdown to pointerup
  let swallowClick = false;
  function timeAt(x) {
    const box = span.getBoundingClientRect();
    return scale().time(box.width > 0 ? (x - box.left) / box.width : 0);
  }
  function scrubTo(x) {
    scrubbed = timeAt(x);
    scrub.to(scrubbed);
    drawHead();
  }
  if (railEl.addEventListener) {
    railEl.addEventListener("pointerdown", (e) => {
      if (!scrub || !scrub.enabled() || !shown || e.button !== 0) return;
      press = { x: e.clientX, id: e.pointerId, dragging: false };
    });
    railEl.addEventListener("pointermove", (e) => {
      if (press && e.pointerId === press.id) {
        if (!press.dragging && Math.abs(e.clientX - press.x) >= DRAG) {
          press.dragging = true;
          railEl.setPointerCapture(press.id);
          railEl.classList.add("scrubbing");
          setHot(null);
        }
        if (press.dragging) { scrubTo(e.clientX); return; }
      }
      setHot(nearest(e.clientX));
    });
    const release = (e, cancelled) => {
      if (!press || e.pointerId !== press.id) return;
      const dragged = press.dragging;
      press = null;
      if (!dragged) return;
      railEl.classList.remove("scrubbing");
      swallowClick = true;   // the click that follows a drag is not one
      const t = cancelled ? scrubbed : timeAt(e.clientX);
      scrubbed = null;
      scrub.end(t);
      drawHead();
    };
    railEl.addEventListener("pointerup", (e) => release(e, false));
    railEl.addEventListener("pointercancel", (e) => release(e, true));
    railEl.addEventListener("pointerleave", () => { if (!press) setHot(null); });
    railEl.addEventListener("click", (e) => {
      if (swallowClick) { swallowClick = false; return; }
      if (e.target && e.target.closest && e.target.closest(".mark")) return;
      const mark = nearest(e.clientX);
      if (mark) mark.onclick();
    });
  }

  // What the preview card says about a mark: the checkpoint it rests on
  // (null for a unit not yet run), its pause('Title') name, the serial
  // that identifies this run of it, and the rail's own words for it.
  function describe(mark) {
    const index = mark.dataset.index === undefined ? null : Number(mark.dataset.index);
    return {
      index,
      name: index === null ? null : (names[index] || null),
      serial: index === null ? null : (serials[index] === undefined ? null : serials[index]),
      detail: mark.dataset.detail || "",
    };
  }

  return {
    presenter,
    handleState,
    handleMove,
    describe,
    // The track changed length (a resize): every fraction is read again.
    relayout() { if (shown) draw(); },
    onHot(listener) { hotListeners.push(listener); },
  };
}

// -- The preview card --
// Hovering (or focusing) a mark raises a small card above it: the still
// of that pausepoint, its pause('Title') name when it has one, and the
// rail's line for it (Taylor, 2026-10-06). Where the picture comes from
// is the page's business — `still(info)` returns an image URL or a
// canvas, a promise of one, or null — so the live viewer (canvas snapshots of pausepoints
// it has stood on) and a recording (frames read from the video) share it.
function attachPreview(rail, config) {
  const doc = config.document;
  const railEl = config.railEl;
  const card = doc.createElement("div");
  card.className = "rail-preview";
  card.setAttribute("aria-hidden", "true");
  const frame = card.appendChild(doc.createElement("div"));
  frame.className = "rail-preview-frame";
  const img = doc.createElement("img");
  img.alt = "";
  const title = card.appendChild(doc.createElement("div"));
  title.className = "rail-preview-title";
  const detail = card.appendChild(doc.createElement("div"));
  detail.className = "rail-preview-detail";
  doc.body.appendChild(card);

  let shown = null;   // the mark the card stands over
  let ask = 0;        // the latest still request; older answers are dropped

  function place(mark) {
    const box = mark.getBoundingClientRect();
    const rail = railEl.getBoundingClientRect();
    const width = card.offsetWidth;
    const view = doc.documentElement.clientWidth;
    const centre = box.left + box.width / 2;
    const left = Math.max(8, Math.min(view - width - 8, centre - width / 2));
    card.style.left = left + "px";
    card.style.bottom = (doc.documentElement.clientHeight - rail.top + 10) + "px";
  }

  function setStill(still) {
    if (typeof still === "string") { img.src = still; still = img; }
    if (still) frame.replaceChildren(still);
    else frame.replaceChildren();
    frame.classList.toggle("has-still", !!still);
  }

  function show(mark) {
    const info = rail.describe(mark);
    shown = mark;
    title.textContent = info.name || "";
    title.hidden = !info.name;
    detail.textContent = info.detail;
    const mine = ++ask;
    const answer = info.index === null ? null : config.still(info);
    if (answer && typeof answer.then === "function") {
      setStill(null);
      answer.then((url) => { if (mine === ask && shown === mark) setStill(url); },
                  () => {});
    } else {
      setStill(answer);
    }
    card.classList.add("shown");
    place(mark);
  }

  function hide() {
    shown = null;
    ask++;
    card.classList.remove("shown");
  }

  const markAt = (target) => (target && target.closest ? target.closest(".mark") : null);
  rail.onHot((mark) => (mark ? show(mark) : hide()));
  railEl.addEventListener("focusin", (e) => {
    const mark = markAt(e.target);
    if (mark && mark.matches(":focus-visible")) show(mark);
  });
  railEl.addEventListener("focusout", hide);
  railEl.addEventListener("pointerdown", hide);
  return {
    // The rail redraws under a resting pointer (a move lands, a unit
    // runs): refresh the card's words and still in place.
    refresh() { if (shown) { if (shown.isConnected) show(shown); else hide(); } },
    hide,
  };
}

// Stills read from a recording: a second, hidden video seeks to each
// pausepoint's frame on request and the frame is kept on a small canvas
// (a canvas, not a data URL: a bundle opened from file:// taints it, and
// a tainted canvas still shows).
// One seek at a time; a request superseded while it waits is dropped.
function videoStills(doc, src, meta, width) {
  const video = doc.createElement("video");
  video.muted = true;
  video.preload = "auto";
  video.playsInline = true;
  video.src = src;
  const cache = new Map();   // checkpoint index -> still canvas
  let chain = Promise.resolve();
  let latest = null;        // the most recent request, the one worth a seek
  const fps = (meta && meta.fps) || 30;
  function grab(index) {
    return new Promise((resolve) => {
      const cp = meta.checkpoints[index];
      if (!cp) return resolve(null);
      const go = () => {
        video.addEventListener("seeked", () => {
          const w = width, h = Math.round(width * video.videoHeight / video.videoWidth);
          const canvas = doc.createElement("canvas");
          canvas.width = w; canvas.height = h;
          const context = canvas.getContext("2d");
          context.imageSmoothingQuality = "high";   // thin strokes survive
          context.drawImage(video, 0, 0, w, h);
          resolve(canvas);
        }, { once: true });
        video.currentTime = Math.max(0, cp.time - 0.5 / fps);
      };
      if (video.readyState >= 1) go();
      else video.addEventListener("loadedmetadata", go, { once: true });
    });
  }
  return {
    get(index) {
      if (cache.has(index)) return cache.get(index);
      if (video.error) return null;
      latest = index;
      const pending = chain.then(() => {
        if (cache.has(index)) return cache.get(index);
        if (latest !== index) return null;
        return grab(index).then((url) => { if (url) cache.set(index, url); return url; });
      });
      chain = pending.catch(() => null);
      return pending;
    },
    dispose() { video.removeAttribute("src"); video.load(); cache.clear(); },
  };
}

return { create, attachPreview, videoStills };
})();

// Node (the simulation harness) imports this file as CommonJS.
if (typeof module !== "undefined" && module.exports) {
  module.exports = ManimlRail;
}

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
// plass, but horizontal"): marks placed by
// one fraction each, `left: calc(var(--f) * 100%)`. The fraction is
// time: a pausepoint is a dot at the scene's clock when it was saved,
// the start and the end are upright dashes, and the plays between
// pausepoints (UP/DOWN's steps) are faint ticks. What has not run yet
// has no time, and none is guessed: those units stand at a small fixed
// interval after the last one that ran. Over the timeline rides a lens
// centred on the head, the position, which magnifies the marks round it
// so a long scene stays navigable (below, "The DOM").
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
// The lens: at most this many px wide (and never more than half the
// track), opening pausepoints that stand close to about LENS_GAP px
// apart; one magnification for the whole scene, so nothing in it
// changes scale as the head moves.
const LENS_PX = 176;
const LENS_GAP = 14;
const LENS_MIN = 1.6;
const LENS_MAX = 16;
// The head's glide to a new rest: ms per px travelled, within bounds.
const GLIDE_MS_PER_PX = 6;
const GLIDE_MIN_MS = 180;
const GLIDE_MAX_MS = 500;

const fmt = (f) => String(Math.round(Math.max(0, Math.min(1, f)) * 1e6) / 1e6);
const px = (x) => Math.round(x * 100) / 100 + "px";
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
  const width = config.width || (() => railEl.clientWidth || 400);
  const scrub = config.scrub || null;
  const animate = typeof requestAnimationFrame === "function";

  const MIN_LIT_MS = 250;
  let move = null;
  let moveSince = 0;
  let moveClear = null;
  let playhead = null;   // a recording's clock while it crosses a stretch
  let scrubbed = null;   // the time under the pointer while it scrubs
  let headT = 0;         // where the head stands, on the scene's clock
  let glide = 0;         // the head's glide in flight (a frame request)
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
    // A recording's clock, while it moves: the head rides it.
    time(t) {
      if (!this.moving || scrubbed !== null) return;
      playhead = t;
      stopGlide();
      headT = t;
      drawLens();
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
    const first = shown === null;
    shown = read(state, future, current);
    drawMarks();
    // The head goes to the position it lands on, gliding there, unless
    // the pointer is scrubbing: then it is the pointer's.
    if (scrubbed === null) setHead(shown.times[shown.current], !first);
    else drawLens();
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
    const W = trackWidth();
    const n = shown.future.length;
    let room = 0;
    if (n) room = shown.T > 0 ? Math.min(n * FUTURE_PX, W * FUTURE_SHARE) : W;
    const ran = (W - room) / W;
    return {
      W,
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
  // A span inset from the rail's ends holds the timeline (every mark at
  // its place, never moving as the head does), the lens over it and the
  // head. The lens is Plass's band made a magnifier (Taylor, 2026-10-08):
  // it sits over the timeline, hides what is under it, and shows the
  // marks round the head opened up, every play step's dash included, so
  // the head — the precise point, a tall dash in the accent — stands at
  // its true place on the whole timeline and at the lens's centre at
  // once (only at the very ends does the lens stop short and the head
  // move off its centre). Marks are pooled by their order and rewritten
  // in place, a timeline copy and a lens copy each.
  let span = null, timeline = null, lens = null, bubble = null, head = null;
  let specs = [];
  const backMarks = [];   // the timeline's copies
  const lensMarks = [];   // the lens's copies: buttons for the pausepoints
  let lensK = LENS_MIN;   // the lens's magnification, one per scene
  let hot = null;         // the mark under the pointer
  const hotListeners = [];

  const trackWidth = () => Math.max(1, (span && span.clientWidth) || width());
  function setVar(el, name, value) {
    if (el.style.getPropertyValue(name) !== value) el.style.setProperty(name, value);
  }
  function drop(el, parent) {
    if (el.remove) el.remove();
    else parent.removeChild(el);
  }
  function build() {
    span = doc.createElement("div");
    span.className = "rail-span";
    span.setAttribute("role", "presentation");
    timeline = span.appendChild(doc.createElement("div"));
    timeline.className = "rail-timeline";
    timeline.setAttribute("aria-hidden", "true");
    lens = span.appendChild(doc.createElement("div"));
    lens.className = "rail-lens";
    bubble = lens.appendChild(doc.createElement("div"));
    bubble.className = "rail-bubble";
    head = span.appendChild(doc.createElement("div"));
    head.className = "rail-head";
    railEl.replaceChildren(span);
  }

  const isDot = (spec) => spec.kind !== "tick";

  function drawMarks() {
    if (!span) build();
    const s = scale();
    const { count, times, stops, future } = shown;
    specs = [];
    let plays = 0;
    for (let i = 0; i < count; i++) {
      if (stops[i]) {
        specs.push({ kind: "stop", index: i, f: s.at(times[i]), plays });
        plays = 0;
      } else {
        specs.push({ kind: "tick", index: i, f: s.at(times[i]) });
        plays += 1;
      }
    }
    future.forEach((u, j) => specs.push(
      { kind: "future", unit: u.unit, line: u.line, many: !!u.many, f: s.future(j) }));
    const dots = specs.filter(isDot);
    if (dots.length) dots[0].end = "start";
    if (dots.length > 1) dots[dots.length - 1].end = "end";

    // The magnification: what opens the closer pausepoints (the first
    // quarter of the gaps between them) to LENS_GAP.
    const gaps = [];
    for (let k = 1; k < dots.length; k++) {
      const gap = (dots[k].f - dots[k - 1].f) * s.W;
      if (gap > 0.25) gaps.push(gap);
    }
    gaps.sort((x, y) => x - y);
    const q = gaps.length ? gaps[Math.floor(gaps.length / 4)] : s.W;
    lensK = Math.min(LENS_MAX, Math.max(LENS_MIN, LENS_GAP / q));
    // A crowded timeline draws its pausepoints small and its play steps
    // not at all; the lens always has room for both.
    const small = (dots.length - 1) * 8 > s.W;
    const bare = (specs.length - 1) * 6 > s.W;

    pool(backMarks, specs.length, timeline, "i");
    pool(lensMarks, specs.length, lens, "button");
    if (hot && !backMarks.includes(hot) && !lensMarks.includes(hot)) setHot(null);
    specs.forEach((spec, k) => {
      const back = backMarks[k];
      back.className = markClass(spec) + (small && spec.kind === "stop" && !spec.end ? " small" : "")
        + (back === hot ? " hot" : "");
      back.hidden = bare && spec.kind === "tick";
      setVar(back, "--f", fmt(spec.f));
      label(back, spec);
      updateLensMark(lensMarks[k], spec);
    });
    // The rail's length follows what it holds, where the page lets it.
    setVar(railEl, "--marks", String(dots.length));
  }

  function pool(list, n, parent, tag) {
    while (list.length < n) {
      const el = parent.appendChild(doc.createElement(tag));
      if (tag === "button") { el.type = "button"; el.setAttribute("role", "listitem"); }
      list.push(el);
    }
    while (list.length > n) drop(list.pop(), parent);
  }

  function markClass(spec) {
    return "mark " + (spec.kind === "tick" ? "tick" : "dot")
      + (spec.end ? " " + spec.end : "") + (spec.kind === "future" ? " future" : "")
      + (spec.many ? " many" : "");
  }

  // What the preview card reads off a mark (describe()).
  function label(el, spec) {
    const detail = describeSpec(spec);
    el.dataset.detail = detail;
    if (spec.index !== undefined && spec.kind !== "tick") {
      el.dataset.index = String(spec.index);
    } else delete el.dataset.index;
    return detail;
  }

  function updateLensMark(mark, spec) {
    mark.className = markClass(spec) + (mark === hot ? " hot" : "");
    const detail = label(mark, spec);
    if (spec.kind === "tick") {
      // A play step is seen in the lens, and reached with UP/DOWN.
      mark.tabIndex = -1;
      mark.setAttribute("aria-hidden", "true");
      mark.onclick = () => config.onChipClick(spec.index);
      return;
    }
    mark.removeAttribute("aria-hidden");
    mark.removeAttribute("tabindex");
    const name = spec.index !== undefined ? names[spec.index] : null;
    mark.setAttribute("aria-label", name ? name + " — " + detail : detail);
    // A click parks browser focus on the button, and the mark survives
    // every redraw, so drop it: position feedback is the presenter's job.
    mark.onclick = () => {
      if (mark.blur) mark.blur();
      if (spec.kind === "future") config.onFutureChipClick(spec.unit);
      else config.onChipClick(spec.index);
    };
  }

  function describeSpec(spec) {
    if (spec.kind === "future") {
      return spec.many
        ? "Runs to line " + spec.line + " · a loop or branch, so how many "
          + "pausepoints it holds is not known until it runs"
        : "Runs to line " + spec.line;
    }
    if (spec.index === 0) return "Start";
    const where = "line " + shown.lines[spec.index] + " · " + clock(shown.times[spec.index]);
    if (spec.kind === "tick") return "Play step · " + where;
    return "Pausepoint · " + where
      + (spec.plays ? " · " + spec.plays + " play step"
         + (spec.plays > 1 ? "s" : "") + " before it (↑↓)" : "");
  }

  // -- The head and the lens --
  // The head's time, the pausepoint it stands for and the stretch round
  // it decide everything the lens shows. The lens is centred on the head
  // and magnifies about it, so the head keeps its true place.
  function lensWidth(W) { return Math.min(LENS_PX, W / 2); }

  // The pausepoint lit in the accent: the one the position rests on;
  // while scrubbing, the one nearest the head (where a release lands);
  // nothing while a move crosses a stretch.
  function litIndex() {
    if (scrubbed !== null) return nearestStop(scrubbed);
    if (move || glide) return -1;
    return shown.stops[shown.current] ? shown.current : -1;
  }

  // The stretch the bubble lights: a live move's whole stretch (the
  // engine says which, not how far along); otherwise the stretch round
  // the head, between the pausepoints either side of it.
  function bubbleRange(s) {
    if (move && playhead === null && scrubbed === null) {
      return [s.at(shown.times[Math.min(move.from, shown.count - 1)]), destination(s)];
    }
    const { count, stops, times, future } = shown;
    let a = 0;
    for (let i = 0; i < count; i++) if (stops[i] && times[i] <= headT + 1e-9) a = i;
    let b = null;
    for (let i = a + 1; i < count; i++) if (stops[i] && times[i] > headT + 1e-9) { b = s.at(times[i]); break; }
    if (b === null) b = future.length ? s.future(0) : s.at(times[a]);
    return [s.at(times[a]), b];
  }

  function drawLens() {
    if (!span || !shown) return;
    const s = scale();
    const W = s.W;
    const LW = lensWidth(W);
    const h = s.at(headT) * W;
    const left = Math.max(-2, Math.min(W - LW + 2, h - LW / 2));
    lens.style.left = px(left);
    lens.style.width = px(LW);
    const place = (f) => h + (f * W - h) * lensK - left;
    const lit = litIndex();
    specs.forEach((spec, k) => {
      const mark = lensMarks[k];
      const x = place(spec.f);
      const inside = x > -8 && x < LW + 8;
      if (mark.hidden !== !inside) mark.hidden = !inside;
      if (inside) mark.style.left = px(x);
      const on = spec.kind === "stop" && spec.index === lit;
      if (mark.classList.contains("current") !== on) {
        mark.classList.toggle("current", on);
        if (on) mark.setAttribute("aria-current", "step");
        else mark.removeAttribute("aria-current");
      }
    });
    head.style.left = px(h);
    const crossing = !!move || scrubbed !== null || !!glide;
    if (crossing) {
      const [a, b] = bubbleRange(s);
      const xa = place(Math.min(a, b)), xb = place(Math.max(a, b));
      bubble.style.left = px(xa - 4);
      bubble.style.width = px(Math.max(0, xb - xa) + 8);
    }
    bubble.className = "rail-bubble" + (crossing ? " lit" : "");
  }

  function stopGlide() {
    if (glide && typeof cancelAnimationFrame === "function") cancelAnimationFrame(glide);
    glide = 0;
  }
  // The head to a time: at once, or gliding there (one clean move,
  // longer for a longer way, eased at both ends).
  function setHead(t, glideThere) {
    stopGlide();
    const from = headT;
    const way = shown ? Math.abs(scale().at(t) - scale().at(from)) * trackWidth() : 0;
    if (!glideThere || !animate || way < 0.5) { headT = t; drawLens(); return; }
    const ms = Math.min(GLIDE_MAX_MS, GLIDE_MIN_MS + way * GLIDE_MS_PER_PX);
    const start = performance.now();
    const step = (now) => {
      const e = Math.min(1, (now - start) / ms);
      const k = e < 0.5 ? 2 * e * e : 1 - Math.pow(-2 * e + 2, 2) / 2;
      headT = from + (t - from) * k;
      glide = e < 1 ? requestAnimationFrame(step) : 0;
      drawLens();
    };
    glide = requestAnimationFrame(step);
  }

  // The pausepoint that ran nearest a time (of several at one time, the
  // last: the pause after its play).
  function nearestStop(t) {
    let best = 0;
    for (let i = 0; i < shown.count; i++) {
      if (shown.stops[i] && Math.abs(shown.times[i] - t) <= Math.abs(shown.times[best] - t)) best = i;
    }
    return best;
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

  function applyMove() {
    body.classList.toggle("moving", !!move);
    drawLens();
  }

  function handleMove(data) {
    clearTimeout(moveClear);
    if (data.from === null || data.from === undefined) {
      // Hold a short move lit long enough to be seen: a 0.3s play would
      // otherwise flicker the bubble on and off in one blink.
      const held = Math.max(0, MIN_LIT_MS - (performance.now() - moveSince));
      moveClear = setTimeout(() => { move = null; applyMove(); }, held);
      return;
    }
    move = { from: data.from, to: data.to, back: !!data.back, unit: data.unit };
    moveSince = performance.now();
    applyMove();
  }

  // -- The pointer --
  // Inside the lens the nearest of its marks takes the pointer; outside
  // it, the nearest timeline mark within HIT px. The marks take no
  // pointer events themselves; a key on a focused mark is its own click.
  function markNear(x, within) {
    let best = null, bestD = within;
    const consider = (mark) => {
      if (mark.hidden) return;
      const box = mark.getBoundingClientRect();
      const d = Math.abs(box.left + box.width / 2 - x);
      if (d <= bestD) { best = mark; bestD = d; }   // a tie goes to the later
    };
    if (inLens(x)) {
      specs.forEach((spec, k) => { if (isDot(spec)) consider(lensMarks[k]); });
    } else {
      specs.forEach((spec, k) => { if (isDot(spec)) consider(backMarks[k]); });
    }
    return best;
  }
  function inLens(x) {
    const box = lens.getBoundingClientRect();
    return x >= box.left && x <= box.right;
  }
  function setHot(mark) {
    if (mark === hot) return;
    if (hot) hot.classList.remove("hot");
    hot = mark;
    if (hot) hot.classList.add("hot");
    for (const listener of hotListeners) listener(hot);
  }

  // -- Scrubbing --
  // A press dragged along the rail scrubs (Taylor, 2026-10-07/08): the
  // head is the pointer's time, the lens rides centred on it, the
  // pausepoint nearest it is lit and the bubble lights the stretch it is
  // in; the release glides the head to that pausepoint, the position the
  // page then parks on. Dragged from the lens, the head moves with the
  // pointer one for one along the whole timeline (a scrollbar's thumb);
  // pressed elsewhere, it jumps under the pointer first. The page says
  // what a scrub shows (config.scrub.to and end: a recording seeks to the
  // time, the live engine jumps to each pausepoint as it is crossed).
  let press = null;   // { x, id, fromLens, t0, dragging }
  let swallowClick = false;
  function scrubTo(x) {
    const s = scale();
    const box = span.getBoundingClientRect();
    const f = press.fromLens
      ? s.at(press.t0) + (x - press.x) / s.W
      : (x - box.left) / s.W;
    scrubbed = s.time(f);
    headT = scrubbed;
    scrub.to(scrubbed, nearestStop(scrubbed));
    drawLens();
  }
  if (railEl.addEventListener) {
    railEl.addEventListener("pointerdown", (e) => {
      if (!shown || e.button !== 0) return;
      press = { x: e.clientX, id: e.pointerId, fromLens: inLens(e.clientX),
                t0: headT, dragging: false };
    });
    railEl.addEventListener("pointermove", (e) => {
      if (press && e.pointerId === press.id) {
        if (!press.dragging && Math.abs(e.clientX - press.x) >= DRAG
            && scrub && scrub.enabled() && shown.count > 1) {
          press.dragging = true;
          railEl.setPointerCapture(press.id);
          railEl.classList.add("scrubbing");
          setHot(null);
          stopGlide();
        }
        if (press.dragging) { scrubTo(e.clientX); return; }
      }
      setHot(markNear(e.clientX, inLens(e.clientX) ? Infinity : HIT));
    });
    const release = (e) => {
      if (!press || e.pointerId !== press.id) return;
      const dragged = press.dragging;
      press = null;
      if (!dragged) return;
      railEl.classList.remove("scrubbing");
      swallowClick = true;   // the click that follows a drag is not one
      const index = nearestStop(scrubbed);
      const t = scrubbed;
      scrubbed = null;
      scrub.end(t, index);
      setHead(shown.times[index], true);
    };
    railEl.addEventListener("pointerup", release);
    railEl.addEventListener("pointercancel", release);
    railEl.addEventListener("pointerleave", () => { if (!press) setHot(null); });
    railEl.addEventListener("click", (e) => {
      if (swallowClick) { swallowClick = false; return; }
      if (e.target && e.target.closest && e.target.closest(".mark")) return;
      // In the lens, its nearest mark; on the timeline, the nearest mark
      // within reach, else the pausepoint nearest that time.
      const mark = markNear(e.clientX, inLens(e.clientX) ? Infinity : HIT);
      if (mark) { mark.onclick(); return; }
      const box = span.getBoundingClientRect();
      config.onChipClick(nearestStop(scale().time((e.clientX - box.left) / trackWidth())));
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
    // The track changed length (a resize): every place is read again.
    relayout() { if (shown) { drawMarks(); drawLens(); } },
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

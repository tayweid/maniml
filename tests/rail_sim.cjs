// The rail simulation: replay presenter sequences against rail.js with a
// DOM stub and assert the classes and places. These scripted scenes ARE
// the claims about rail behavior — marks at their times, what has not run
// at a fixed interval, hold at the pausepoint, light the stretch, lift the
// position, land on arrival, an arrow mid-move acting at once — executable
// instead of asserted in prose. Run by tests/test_rail_sim.py.
"use strict";
const path = require("path");
const STATIC = path.join(__dirname, "..", "maniml", "web", "static");
const ManimlRail = require(path.join(STATIC, "rail.js"));
const ManimlPresentation = require(path.join(STATIC, "presentation.js"));

// ---- a minimal DOM ----
class Style {
  constructor() { this.props = {}; }
  getPropertyValue(k) { return this.props[k] === undefined ? "" : this.props[k]; }
  setProperty(k, v) { this.props[k] = v; }
}
class El {
  constructor(tag) {
    this.tag = tag;
    this.children = [];
    this.dataset = {};
    this.attrs = {};
    this.cls = new Set();
    this.style = new Style();
    this.textContent = "";
    this.disabled = false;
    const el = this;
    this.classList = {
      add: (...cs) => cs.forEach((c) => el.cls.add(c)),
      remove: (...cs) => cs.forEach((c) => el.cls.delete(c)),
      toggle: (c, force) => {
        const on = force === undefined ? !el.cls.has(c) : !!force;
        on ? el.cls.add(c) : el.cls.delete(c);
      },
      contains: (c) => el.cls.has(c),
    };
  }
  get className() { return [...this.cls].join(" "); }
  set className(v) { this.cls = new Set(v.split(/\s+/).filter(Boolean)); }
  setAttribute(k, v) { this.attrs[k] = v; }
  removeAttribute(k) { delete this.attrs[k]; }
  appendChild(c) { this.children.push(c); return c; }
  removeChild(c) { this.children = this.children.filter((x) => x !== c); return c; }
  replaceChildren(...cs) { this.children = cs; }
  walk(out = []) {
    for (const c of this.children) { out.push(c); c.walk(out); }
    return out;
  }
  matches(sel) {
    // supports: .cls  and  .cls[data-key="val"]
    const m = sel.match(/^\.([\w-]+)(?:\[data-([\w-]+)="([^"]*)"\])?$/);
    if (!m) return false;
    if (!this.cls.has(m[1])) return false;
    if (m[2] !== undefined && this.dataset[m[2]] !== m[3]) return false;
    return true;
  }
  querySelector(sel) { return this.walk().find((e) => e.matches(sel)) || null; }
  querySelectorAll(sel) { return this.walk().filter((e) => e.matches(sel)); }
}

function makeDom() {
  const byId = {};
  for (const id of ["start", "previous", "next", "position-now", "position-total"]) {
    byId[id] = new El("div");
  }
  const doc = {
    createElement: (tag) => new El(tag),
    getElementById: (id) => byId[id],
    querySelector: (sel) => null,
  };
  return {
    doc,
    railEl: new El("div"),
    body: new El("body"),
    byId,
  };
}

// ---- assertions ----
let failures = 0;
function check(label, actual, expected) {
  const ok = JSON.stringify(actual) === JSON.stringify(expected);
  if (!ok) {
    failures += 1;
    console.error(`FAIL ${label}: got ${JSON.stringify(actual)}, `
      + `expected ${JSON.stringify(expected)}`);
  } else {
    console.log(`ok   ${label}`);
  }
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const f = (el) => Number(el.style.getPropertyValue("--f"));
const round = (x) => Math.round(x * 1000) / 1000;
function railState(dom) {
  const marks = dom.railEl.querySelectorAll(".mark");
  const band = dom.railEl.querySelector(".rail-band");
  const head = dom.railEl.querySelector(".rail-head");
  return {
    position: dom.byId["position-now"].textContent + dom.byId["position-total"].textContent,
    moving: dom.body.classList.contains("moving"),
    current: marks.findIndex((m) => m.cls.has("current")),
    band: [round(Number(band.style.getPropertyValue("--a"))),
           round(Number(band.style.getPropertyValue("--b"))),
           band.cls.has("lit") ? (band.cls.has("back") ? "back" : "lit") : "-"],
    head: head.cls.has("off") ? null : round(f(head)),
  };
}
const places = (dom, sel) => dom.railEl.querySelectorAll(sel).map((m) => round(f(m)));
const kinds = (dom) => dom.railEl.querySelectorAll(".mark").map((m) =>
  (m.cls.has("start") ? "start" : m.cls.has("end") ? "end" : "dot")
  + (m.cls.has("future") ? "?" : "") + (m.cls.has("many") ? "*" : ""));
function makeRail(dom, clicks = [], futureClicks = []) {
  return ManimlRail.create({
    document: dom.doc, railEl: dom.railEl, body: dom.body,
    env: () => {}, width: () => 400,
    onChipClick: (i) => clicks.push(i),
    onFutureChipClick: (u) => futureClicks.push(u),
  });
}

(async () => {
  // ---- Scene 1: a live stretch — the band lit, position held ----
  {
    const dom = makeDom();
    const chipClicks = [];
    const rail = makeRail(dom, chipClicks);
    // cp0 Start; cp1..3 interior plays; cp4 the pause: two marks (the
    // ends) and three ticks, each at its time.
    const table = {
      count: 5,
      lines: [null, 10, 11, 12, 13],
      units: [-1, 2, 2, 2, 2],
      times: [0, 1, 2, 3, 3],
      stops: [true, false, false, false, true],
      future: [],
    };
    rail.presenter.stateChanged({ ...table, current: 0 });
    check("stretch: the ends are dashes, the plays ticks, each at its time",
      { kinds: kinds(dom), marks: places(dom, ".mark"), ticks: places(dom, ".tick") },
      { kinds: ["start", "end"], marks: [0, 1], ticks: [0.333, 0.667, 1] });
    check("stretch: at rest on Start, the band over the stretch ahead",
      railState(dom),
      { position: "1 / 5", moving: false, current: 0, band: [0, 1, "-"], head: null });
    const firstMark = dom.railEl.querySelectorAll(".mark")[0];
    // Start and Back have nowhere to go from the start.
    check("stretch: Start and Back disabled at the start",
      [dom.byId.start.disabled, dom.byId.previous.disabled], [true, true]);

    rail.presenter.moveStarted(0, 1, false, 2);
    check("stretch: move opens — the band lights to the pausepoint, the position lifts",
      railState(dom),
      { position: "1 / 5", moving: true, current: 0, band: [0, 1, "lit"], head: null });

    // interior checkpoints save mid-stretch: display must not change
    rail.presenter.stateChanged({ ...table, current: 2 });
    rail.presenter.stateChanged({ ...table, current: 3 });
    check("stretch: interior states pend — display unchanged",
      railState(dom),
      { position: "1 / 5", moving: true, current: 0, band: [0, 1, "lit"], head: null });

    // arrival: landing state pends, then the move closes and lands it
    rail.presenter.stateChanged({ ...table, current: 4 });
    rail.presenter.moveEnded(null);
    await sleep(300);   // MIN_LIT_MS clears the band
    check("stretch: landing — position advances, band at rest",
      railState(dom),
      { position: "5 / 5", moving: false, current: 1, band: [1, 1, "-"], head: null });
    check("stretch: Start and Back enabled once off the start",
      [dom.byId.start.disabled, dom.byId.previous.disabled], [false, false]);
    check("stretch: marks are updated in place (transitions possible)",
      dom.railEl.querySelectorAll(".mark")[0] === firstMark, true);

    // Parked between pausepoints (UP/DOWN lands on an interior play
    // checkpoint): the head stands at the play's time, and no mark
    // claims the position.
    rail.presenter.stateChanged({ ...table, current: 2 });
    check("park mid-stretch: the head at the play, no mark current",
      { current: railState(dom).current, head: railState(dom).head },
      { current: -1, head: 0.667 });
    rail.presenter.stateChanged({ ...table, current: 4 });
    check("park mid-stretch: back at the pausepoint the head goes",
      { current: railState(dom).current, head: railState(dom).head },
      { current: 1, head: null });

    // A click parks browser focus on the mark, which survives every
    // redraw, so the handler drops focus itself.
    let blurred = false;
    firstMark.blur = () => { blurred = true; };
    firstMark.onclick();
    check("stretch: a click drops focus (no stuck ring)", blurred, true);
    dom.railEl.querySelectorAll(".mark")[1].onclick();
    check("stretch: a mark's click lands on its pausepoint",
      chipClicks, [0, 4]);
  }

  // ---- Scene 2: what has not run stands at a fixed interval ----
  {
    const dom = makeDom();
    const futureClicks = [];
    const rail = makeRail(dom, [], futureClicks);
    const table = {
      count: 2, lines: [null, 10], units: [-1, 1], times: [0, 2],
      stops: [true, true],
      future: [{ unit: 5, line: 30, many: false }, { unit: 6, line: 40, many: true }],
    };
    rail.presenter.stateChanged({ ...table, current: 1 });
    // 400 px of track, 14 px a unit not yet run: the run part is 372 px.
    check("future: the run part by time, the rest 14 px apart",
      { kinds: kinds(dom), marks: places(dom, ".mark") },
      { kinds: ["start", "dot", "dot?", "end?*"], marks: [0, 0.93, 0.965, 1] });
    check("future: the band at rest reaches the next unit",
      railState(dom).band, [0.93, 0.965, "-"]);
    rail.presenter.moveStarted(1, 2, false, 5);
    check("future: a move at the frontier lights to the unit being run",
      railState(dom).band, [0.93, 0.965, "lit"]);
    rail.presenter.moveEnded(null);
    const runMark = dom.railEl.querySelectorAll(".mark")[2];
    runMark.onclick();
    check("future: a not-yet-run mark's click names its unit", futureClicks, [5]);
    await sleep(300);
    rail.presenter.stateChanged({
      count: 3, lines: [null, 10, 30], units: [-1, 1, 5], times: [0, 2, 3],
      stops: [true, true, true], future: [{ unit: 6, line: 40, many: true }],
      current: 2 });
    check("future: the unit that ran is the same mark, now at its time",
      { same: dom.railEl.querySelectorAll(".mark")[2] === runMark,
        kinds: kinds(dom), marks: places(dom, ".mark") },
      { same: true, kinds: ["start", "dot", "dot", "end?*"], marks: [0, 0.643, 0.965, 1] });
  }

  // ---- Scene 3: nothing has run yet — the track is the units' ----
  {
    const dom = makeDom();
    const rail = makeRail(dom);
    rail.presenter.stateChanged({
      count: 1, lines: [null], units: [-1], times: [0], stops: [true], current: 0,
      future: [{ unit: 1, line: 5 }, { unit: 2, line: 6 }, { unit: 3, line: 7 }] });
    check("unrun: the units spread over the whole track",
      places(dom, ".mark"), [0, 0.333, 0.667, 1]);
  }

  // ---- Scene 4: playback tracks its index; duplicate timestamps ----
  {
    const events = [];
    const video = { currentTime: 0, readyState: 4 };
    const meta = {
      format: 1, fps: 30,
      checkpoints: [
        { index: 0, time: 0.0, stop: true, loop: false, chip_unit: -1 },
        { index: 1, time: 0.0, stop: true, loop: false, chip_unit: 1 },
        { index: 2, time: 0.12, stop: true, loop: false, chip_unit: 2 },
      ],
    };
    ManimlPresentation.load(video, meta, {
      onUpdate: (i) => events.push(["update", i]),
      onMove: (from, to, back) => events.push(["move", from, to, back]),
      onRest: (i) => events.push(["rest", i]),
    });
    ManimlPresentation.seekCheckpoint(0);
    check("playback: seek(0) stays at 0 despite a duplicate timestamp",
      ManimlPresentation.currentIndex(), 0);

    ManimlPresentation.playToNextStop();
    check("playback: RIGHT targets the NEXT stop, not the twin at t=0",
      events[events.length - 1], ["move", 0, 1, false]);
    await sleep(250);   // the tick loop arrives (same timestamp: instant)
    check("playback: arrival lands exactly on index 1",
      [ManimlPresentation.currentIndex(),
       events[events.length - 1]], [1, ["rest", 1]]);

    ManimlPresentation.playToNextStop();   // 1 -> 2, a real scrub
    await sleep(500);
    check("playback: scrub forward arrives at 2",
      ManimlPresentation.currentIndex(), 2);

    ManimlPresentation.playToPreviousStop();  // back to 1, back=true
    const backMove = events.filter((e) => e[0] === "move").pop();
    check("playback: LEFT announces back=true",
      backMove.slice(0, 4), ["move", 2, 1, true]);
    await sleep(500);
    check("playback: reverse arrives at 1",
      ManimlPresentation.currentIndex(), 1);
    ManimlPresentation.unload();
  }

  // ---- Scene 5: an arrow mid-move acts now, and never piles up ----
  {
    const events = [];
    const times = [];
    const video = { currentTime: 0, readyState: 4 };
    const meta = {
      format: 1, fps: 30,
      checkpoints: [0, 1, 2, 3].map((i) =>
        ({ index: i, time: i, stop: true, loop: false, chip_unit: i })),
    };
    ManimlPresentation.load(video, meta, {
      onUpdate: (i) => events.push(["update", i]),
      onMove: (from, to, back) => events.push(["move", from, to, back]),
      onRest: (i) => events.push(["rest", i]),
      onTime: (t) => times.push(t),
    });
    ManimlPresentation.seekCheckpoint(0);
    ManimlPresentation.playToNextStop();         // 0 -> 1, a second long
    await sleep(150);
    check("interrupt: the clock is reported while it moves",
      times.length > 0 && times[times.length - 1] > 0 && times[times.length - 1] < 1, true);
    ManimlPresentation.playToNextStop();         // RIGHT mid-move: land now
    check("interrupt: RIGHT mid-move lands on the pausepoint it was going to",
      [ManimlPresentation.currentIndex(), events[events.length - 1]], [1, ["rest", 1]]);
    await sleep(100);
    check("interrupt: and stays there — no second move queued",
      [ManimlPresentation.currentIndex(), events.filter((e) => e[0] === "move").length],
      [1, 1]);

    ManimlPresentation.playToNextStop();         // 1 -> 2
    await sleep(150);
    ManimlPresentation.playToPreviousStop();     // LEFT mid-move: back to 1
    check("interrupt: LEFT mid-move returns to the pausepoint it left",
      [ManimlPresentation.currentIndex(), events[events.length - 1],
       video.currentTime < 1], [1, ["rest", 1], true]);

    ManimlPresentation.playToNextStop();         // 1 -> 2 again
    await sleep(150);
    ManimlPresentation.seekCheckpoint(3);        // a click on the rail mid-move
    check("interrupt: a seek mid-move ends the move where it seeks",
      [ManimlPresentation.currentIndex(), events[events.length - 1]], [3, ["rest", 3]]);

    // The mouse scrubbing the rail: the picture at any time, the release
    // on the checkpoint nearest it.
    ManimlPresentation.playToPreviousStop();     // 3 -> 2
    await sleep(150);
    ManimlPresentation.scrubTo(1.3);
    check("scrub: a scrub mid-move ends the move, the picture at the time",
      [ManimlPresentation.currentIndex(), events[events.length - 1], video.currentTime],
      [3, ["rest", 3], 1.3]);
    await sleep(100);
    check("scrub: the ticker leaves a scrubbed picture alone", video.currentTime, 1.3);
    ManimlPresentation.scrubEnd(1.3);
    check("scrub: the release parks on the nearest checkpoint",
      [ManimlPresentation.currentIndex(), events[events.length - 1]], [1, ["update", 1]]);
    ManimlPresentation.unload();
  }

  if (failures > 0) {
    console.error(`${failures} rail simulation check(s) failed`);
    process.exit(1);
  }
  console.log("rail simulation: all checks passed");
})();

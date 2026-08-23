// The rail simulation: replay presenter sequences against rail.js with a
// DOM stub and assert the classes. These scripted scenes ARE the claims
// about rail behavior — hold at the pausepoint, one steady link per
// stretch, lift the ring, pulse only true stacks, land on arrival —
// executable instead of asserted in prose. Run by tests/test_rail_sim.py.
"use strict";
const path = require("path");
const STATIC = path.join(__dirname, "..", "maniml", "web", "static");
const ManimlRail = require(path.join(STATIC, "rail.js"));
const ManimlPresentation = require(path.join(STATIC, "presentation.js"));

// ---- a minimal DOM ----
class El {
  constructor(tag) {
    this.tag = tag;
    this.children = [];
    this.dataset = {};
    this.attrs = {};
    this.cls = new Set();
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
  replaceChildren() { this.children = []; }
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
  for (const id of ["previous", "next", "position-now", "position-total"]) {
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

function railState(dom) {
  const chips = dom.railEl.querySelectorAll(".chip");
  return {
    position: dom.byId["position-now"].textContent + dom.byId["position-total"].textContent,
    moving: dom.body.classList.contains("moving"),
    current: chips.findIndex((c) => c.cls.has("current")),
    lit: dom.railEl.querySelectorAll(".link").map(
      (l) => l.cls.has("lit") ? (l.cls.has("back") ? "back" : "lit") : "-"),
    working: chips.findIndex((c) => c.cls.has("working")),
    arriving: chips.findIndex((c) => c.cls.has("arriving")),
    stacks: chips.map((c) => c.cls.has("many")),
  };
}

(async () => {
  // ---- Scene 1: a live stretch — one steady link, position held ----
  {
    const dom = makeDom();
    const rail = ManimlRail.create({
      document: dom.doc, railEl: dom.railEl, body: dom.body,
      env: () => {}, onChipClick: () => {}, onFutureChipClick: () => {},
    });
    // cp0 Start; cp1..3 interior plays; cp4 the pause — all one stretch,
    // so one chip holds cp1..4 (a single pausepooint => NOT a stack)
    const table = {
      count: 5,
      lines: [null, 10, 11, 12, 13],
      units: [-1, 2, 2, 2, 2],
      stops: [true, false, false, false, true],
      future: [],
    };
    rail.presenter.stateChanged({ ...table, current: 0 });
    check("stretch: at rest on Start",
      railState(dom),
      { position: "1 / 5", moving: false, current: 0, lit: ["-"],
        working: -1, arriving: -1, stacks: [false, false] });
    const firstChip = dom.railEl.querySelectorAll(".chip")[0];

    rail.presenter.moveStarted(0, 1, false, 2);
    check("stretch: move opens — link lit, ring held, no pulse",
      railState(dom),
      { position: "1 / 5", moving: true, current: 0, lit: ["lit"],
        working: -1, arriving: 1, stacks: [false, false] });

    // interior checkpoints save mid-stretch: display must not change
    rail.presenter.stateChanged({ ...table, current: 2 });
    rail.presenter.stateChanged({ ...table, current: 3 });
    check("stretch: interior states pend — display unchanged",
      railState(dom),
      { position: "1 / 5", moving: true, current: 0, lit: ["lit"],
        working: -1, arriving: 1, stacks: [false, false] });

    // arrival: landing state pends, then the move closes and lands it
    rail.presenter.stateChanged({ ...table, current: 4 });
    rail.presenter.moveEnded(null);
    await sleep(300);   // MIN_LIT_MS clears the link
    check("stretch: landing — position advances, link cleared",
      railState(dom),
      { position: "5 / 5", moving: false, current: 1, lit: ["-"],
        working: -1, arriving: -1, stacks: [false, false] });

    const sameChip = dom.railEl.querySelectorAll(".chip")[0] === firstChip;
    if (sameChip) {
      console.log("ok   stretch: chips are updated in place (transitions possible)");
    } else {
      failures += 1;
      console.error("FAIL stretch: chips are updated in place (transitions possible): "
        + "chip identity changed across handleState calls");
    }

    // In-place updates mean a clicked chip's node — and the browser focus a
    // click parks on it — survives every later paint, so the handler must
    // drop focus itself or the chip wears the focus ring forever.
    let blurred = false;
    firstChip.blur = () => { blurred = true; };
    firstChip.onclick();
    check("stretch: a click drops focus (no stuck ring)", blurred, true);
  }

  // ---- Scene 2: a true stack (pause in a loop) pulses, no link ----
  {
    const dom = makeDom();
    const rail = ManimlRail.create({
      document: dom.doc, railEl: dom.railEl, body: dom.body,
      env: () => {}, onChipClick: () => {}, onFutureChipClick: () => {},
    });
    const table = {
      count: 3,
      lines: [null, 20, 20],
      units: [-1, 7, 7],
      stops: [true, true, true],   // two pausepoints share the chip
      future: [],
    };
    rail.presenter.stateChanged({ ...table, current: 1 });
    check("stack: two pausepoints in one chip draw stacked",
      railState(dom).stacks, [false, true]);

    rail.presenter.moveStarted(1, 2, false, 7);
    const s = railState(dom);
    check("stack: within-stack move pulses the stack, lights no link",
      { lit: s.lit, working: s.working }, { lit: ["-"], working: 1 });
  }

  // ---- Scene 3: playback tracks its index; duplicate timestamps ----
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

  if (failures > 0) {
    console.error(`${failures} rail simulation check(s) failed`);
    process.exit(1);
  }
  console.log("rail simulation: all checks passed");
})();

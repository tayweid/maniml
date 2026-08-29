// The rail, and the presenter that authors it.
//
// Extracted from viewer.html so the discipline is testable: a Node
// simulation (tests/rail_sim.mjs) replays message sequences against a
// DOM stub and asserts the classes. The rail has exactly one author —
// the presenter — and whichever frame source is active (the live engine
// or the recorded video) feeds it through three methods, so live and
// playback modes cannot drift.
//
// The engine (or source) says which stretch is being crossed, and nothing
// about how far along it is: an animation's own progress is already on
// screen at full size. What the rail must do is stop claiming the
// position it is leaving, hold the one lit link for the whole stretch,
// and land only on arrival.
"use strict";

const ManimlRail = (() => {

function create(config) {
  const doc = config.document;
  const railEl = config.railEl;
  const body = config.body;
  const get = (id) => doc.getElementById(id);
  const raf = config.raf || ((fn) => fn());
  const env = config.env || (() => {});

  const MIN_LIT_MS = 250;
  let move = null;
  let moveSince = 0;
  let moveClear = null;
  let groups = [];
  let groupOf = [];   // checkpoint index -> chip index
  let midGroup = null; // chip whose entering dash is lit: parked mid-stretch

  // -- The presenter --
  // hold the position while a stretch is being crossed (mid-move states
  // are pended, applied on arrival), light the crossing link or pulse a
  // true stack, lift the ring, land only when the move ends.
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
      handleMove({ from: null });
      const landing = landingState || this.pending;
      this.pending = null;
      if (landing) handleState(landing);
    },
    reset() { this.moving = false; this.pending = null; },
  };

  function handleState(state) {
    env(state);

    const future = state.future || [];
    const total = state.count + future.length;
    const current = Math.max(0, state.current);
    get("position-now").textContent = String(current + 1);
    get("position-total").textContent = " / " + Math.max(1, total);
    get("previous").disabled = current <= 0;
    get("next").disabled = current >= total - 1;

    drawRail(state, future, current);
    applyMove();
    raf(() => {
      const active = railEl.querySelector(".current")
        || railEl.querySelector(".mid");
      if (active && active.scrollIntoView) {
        active.scrollIntoView({ behavior: "smooth", block: "nearest", inline: "center" });
      }
    });
  }

  // -- The rail --
  // A chip is one source statement's worth of scene, not one checkpoint.
  function buildGroups(state, future) {
    const units = state.units || [];
    const stops = state.stops || [];
    const built = [];
    groupOf = [];
    for (let i = 0; i < state.count; i++) {
      const unit = units[i] === undefined ? null : units[i];
      const isStop = stops[i] === undefined ? true : !!stops[i];
      const last = built[built.length - 1];
      // A checkpoint with no unit (checkpoint 0, or a play with no anchor)
      // never merges: nothing says it belongs with its neighbour.
      if (last && last.known && unit !== null && last.unit === unit) {
        last.indices.push(i);
        if (isStop) last.stopCount += 1;
      } else {
        built.push({ known: true, unit, indices: [i],
                     stopCount: isStop ? 1 : 0, line: state.lines[i] });
      }
      groupOf[i] = built.length - 1;
    }
    for (const unit of future) {
      built.push({ known: false, unit: unit.unit, indices: [],
                   line: unit.line, many: unit.many });
    }
    return built;
  }

  // A stack means several PAUSEPOINTS share this chip (a pause in a
  // loop) — interior play steps between pauses never make one.
  function chipFlags(group, current) {
    const holds = group.known ? group.indices.length : 0;
    const many = (group.known ? group.stopCount > 1 : group.many);
    const isCurrent = group.known && group.indices.includes(current)
      && midGroup === null;
    const past = group.known && group.indices[holds - 1] < current;
    return { holds, many, isCurrent, past };
  }

  function chipClassName(group, current) {
    const { many, isCurrent, past } = chipFlags(group, current);
    return "chip" + (group.known ? (past ? " past" : "") : " future")
      + (isCurrent ? " current" : "") + (many ? " many" : "");
  }

  function chipTitle(group, flags) {
    const { holds, many } = flags;
    if (group.known) {
      const first = group.indices[0], last = group.indices[holds - 1];
      return many
        ? "Pausepoints " + first + "–" + last + " · line " + group.line
          + " · one statement, stepped through with the arrow keys"
        : (first === 0 ? "Start"
           : "Pausepoint · line " + group.line
             + (holds > 1
                ? " · " + (holds - 1) + " play steps inside (↑↓)"
                : ""));
    }
    return group.many
      ? "Runs to line " + group.line + " · a loop or branch, so how many "
        + "pausepoints it holds is not known until it runs"
      : "Runs to line " + group.line;
  }

  function linkClassName(from, to, current) {
    const before = groups[from], after = groups[to];
    const past = before.known && after.known
      && after.indices[after.indices.length - 1] <= current;
    return "link" + (past ? " past" : !before.known ? " future" : "")
      + (to === midGroup ? " mid" : "");
  }

  // Refresh everything about a chip that can change from one draw to the
  // next: class, title, aria state, and the click closure (cheap, and
  // keeps it bound to the current group/current values).
  function updateChip(chip, group, current) {
    const flags = chipFlags(group, current);
    chip.className = chipClassName(group, current);
    chip.title = chipTitle(group, flags);
    chip.setAttribute("aria-label", chip.title);
    if (flags.isCurrent) chip.setAttribute("aria-current", "step");
    else chip.removeAttribute("aria-current");
    // A click parks browser focus on the button, and since the rail stopped
    // rebuilding on every paint the node — and its focus ring — now survives
    // navigation. Position feedback is the presenter's job, so drop it.
    chip.onclick = () => {
      if (chip.blur) chip.blur();
      // A chip is the resting state at the END of its stretch: interior
      // plays (and loop iterations) collapse into it and are reached with
      // UP/DOWN. Clicking must land on that rest — the group's last
      // checkpoint — not the first interior play, or the scene parks one
      // or more plays short of the pausepoint the chip stands for.
      if (group.known) {
        config.onChipClick(group.indices[group.indices.length - 1]);
      } else {
        config.onFutureChipClick(group.unit);
      }
    };
  }

  function makeChip(group, g, current) {
    const chip = doc.createElement("button");
    chip.type = "button";
    chip.dataset.group = String(g);
    chip.setAttribute("role", "listitem");
    updateChip(chip, group, current);
    return chip;
  }

  function makeLink(from, to, current) {
    const link = doc.createElement("span");
    link.className = linkClassName(from, to, current);
    link.dataset.from = String(from);
    link.appendChild(doc.createElement("i")).className = "fill";
    return link;
  }

  // True when the rail's existing DOM has exactly the shape the new
  // groups need: same chip/link count, and each chip already known vs.
  // future the way the corresponding new group is. When it holds, drawRail
  // updates classes/labels in place instead of tearing the DOM down —
  // that's what lets CSS transitions run instead of teleporting.
  function canUpdateInPlace(prevGroups, newGroups) {
    if (prevGroups.length !== newGroups.length) return false;
    if (railEl.children.length !== 2 * newGroups.length - 1) return false;
    for (let g = 0; g < newGroups.length; g++) {
      const chip = railEl.children[2 * g];
      if (!chip) return false;
      const isFuture = chip.classList.contains("future");
      if (newGroups[g].known === isFuture) return false;
    }
    return true;
  }

  function updateRailInPlace(current) {
    groups.forEach((group, g) => {
      updateChip(railEl.children[2 * g], group, current);
      if (g > 0) {
        railEl.children[2 * g - 1].className = linkClassName(g - 1, g, current);
      }
    });
  }

  function drawRail(state, future, current) {
    const prevGroups = groups;
    groups = buildGroups(state, future);
    // Parked between pausepoints (UP/DOWN): the position is a place ON a
    // stretch, not a pausepoint, so the dash entering the chip lights and
    // no dot claims the ring. In a plain file every checkpoint is a stop
    // and this never engages.
    const stops = state.stops || [];
    const atStop = stops[current] === undefined ? true : !!stops[current];
    midGroup = (atStop || groupOf[current] === undefined)
      ? null : groupOf[current];
    if (canUpdateInPlace(prevGroups, groups)) {
      updateRailInPlace(current);
      return;
    }
    railEl.replaceChildren();
    groups.forEach((group, g) => {
      if (g > 0) railEl.appendChild(makeLink(g - 1, g, current));
      railEl.appendChild(makeChip(group, g, current));
    });
  }

  // Where a move lands, in chips. The destination checkpoint may not exist
  // yet, which is exactly the case the unit index answers: a play from the
  // same statement stays inside its stack, anything else crosses to the
  // chip standing for that statement.
  function destinationGroup(from) {
    if (groupOf[move.to] !== undefined) return groupOf[move.to];
    if (groups[from] && groups[from].unit === move.unit) return from;
    for (let g = from + 1; g < groups.length; g++) {
      if (groups[g].unit === move.unit) return g;
    }
    return from + 1;
  }

  function applyMove() {
    for (const link of railEl.querySelectorAll(".link")) {
      link.classList.remove("lit", "back");
    }
    for (const chip of railEl.querySelectorAll(".chip")) {
      chip.classList.remove("working");
    }
    body.classList.toggle("moving", !!move);
    if (!move) return;
    const from = groupOf[move.from];
    if (from === undefined) return;
    const to = destinationGroup(from);
    const chip = (g) => railEl.querySelector('.chip[data-group="' + g + '"]');
    if (to === from) {
      // Moving inside a collapsed stack: there is no stretch between two
      // chips to light, so the stack itself shows that it is working.
      const stack = chip(from);
      if (stack) stack.classList.add("working");
      return;
    }
    // The lit dash is the whole story of a crossing: no outline on the
    // destination chip — its dot lights only on arrival.
    const link = railEl.querySelector(
      '.link[data-from="' + Math.min(from, to) + '"]');
    if (link) {
      link.classList.add("lit");
      if (move.back) link.classList.add("back");
    }
  }

  function handleMove(data) {
    clearTimeout(moveClear);
    if (data.from === null || data.from === undefined) {
      // Hold a short move lit long enough to be seen: a 0.3s play would
      // otherwise flicker the link on and off in one blink.
      const held = Math.max(0, MIN_LIT_MS - (performance.now() - moveSince));
      moveClear = setTimeout(() => { move = null; applyMove(); }, held);
      return;
    }
    move = { from: data.from, to: data.to, back: !!data.back, unit: data.unit };
    moveSince = performance.now();
    applyMove();
  }

  return {
    presenter,
    handleState,
    handleMove,
    groupOfCheckpoint: (i) => groupOf[i],
  };
}

return { create };
})();

// Node (the simulation harness) imports this file as CommonJS.
if (typeof module !== "undefined" && module.exports) {
  module.exports = ManimlRail;
}

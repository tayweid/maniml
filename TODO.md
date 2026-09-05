# TODO

The forward roadmap, pruned on 2026-09-04 to what is actually planned.
What was decided, shipped, or dropped — and why — lives in
`DECISIONS.md`; the architecture as it stands lives in `CLAUDE.md`;
`PERFORMANCE.md` is the 2026-08 measurement record. The target
architecture after the beeline lives beside this repo in
`../simlab/ARCHITECTURE.md`, sequenced in
`../simlab/INSTRUCTION_STREAM_PLAN.md`.

## Where things stand

One live surface: the browser, rendering every frame itself with
WebGPU from the geometry stream. The pyglet window, the pixel stream,
and WebGL2 are gone (2026-09-02). Native GL remains for exactly two
things: headless `--render` / `--export-checkpoints`, and the oracle
the fidelity tests diff the WebGPU port against. The suite is clean
except the two long-standing `test_app.AppShellE2E` failures.

## Now: the dogfood pause

Course production on the browser as the only surface is the burn-in
signal. What it has surfaced so far, and what is ready regardless:

1. **The hitch at every play boundary.** The one thing that keeps
   coming up in dogfood (Taylor, 2026-09-04): a visible stall at the
   start of every animation. The audit put it at roughly 37 ms per
   play — `begin_animations` plus the checkpoint deep copy — and 8 to
   14 ms per copy in the boids run; it does not shrink for small
   scenes. Measure first on a real course scene with
   `MANIML_PERF_PATH` (`checkpoint.*` stages). Possible measures, in
   the order they pay off if the instruction-stream architecture
   (`../simlab/ARCHITECTURE.md`) is the destination — the first two
   are prerequisite work for it, so nothing here is thrown away:
   - **Freeze the data, count revisions.** The 2026-08 revision store
     (tag `archive/perf-systematic-viewer`) foundered on the change
     signal: partial hooks missed writes silently, and hashing arrays
     cost as much as copying. The cheap signal forbids unsanctioned
     writes instead of detecting them. Freeze `mobject.data` and the
     array uniforms with numpy's `flags.writeable = False` (field
     views inherit it; verified on numpy 2.5); the `affects_data` /
     family / updater mutators unfreeze, bump a per-mobject
     `revision`, and refreeze, so a bypassing write fails loudly in
     the suite (about 29 such sites outside `mobject.py`, mostly in
     `vectorized_mobject.py` and `surface.py`) instead of going stale.
     Derived caches (joint angles, bounding boxes, triangulation,
     shader wrappers) stay outside the frozen region and the
     revision. Compatibility cost: user code that writes into
     `get_points()` breaks and needs a clear error naming the
     sanctioned method. Serves item 2 below and the architecture's
     handle model directly.
   - **The checkpoint ledger** (from JAnim, `../simlab/JANIM.md`).
     Keep `deepcopy_namespace`, but pre-seed its memo so a mobject
     whose revision is unchanged since its last frozen copy reuses
     that copy; only changed mobjects are copied, and a play costs
     what moved. Deep copies come back writeable, so ledger entries
     are frozen explicitly. A day on top of the freeze; the interim
     payoff until the architecture makes checkpoints free by
     construction, and not worth elaborating beyond that.
   - **Copy less.** Anything render-only or derived is dead weight in
     a checkpoint and is rebuilt on restore anyway; anything immutable
     (module objects, functions already handled by
     `_rebind_functions`) can be shared. Cheap regardless; add byte
     and time accounting per checkpoint so every win is visible.
   - **Copy later** — only if the two above do not land. Take the
     copy after the first frame has been sent, or defer interior
     (non-pausepoint) copies to idle time while keeping the
     pausepoint copy eager. It works around a cost the architecture
     deletes, so it is the fallback, not the plan.
   - **Do not** build copy-on-write checkpoints on this engine: the
     instruction-stream architecture makes checkpoints free, so the
     redesign lands there.
2. **Skip the per-frame walk of unchanged batches.** The serializer
   walks, packs, and hashes every batch every frame even when nothing
   moved — about 9 ms at 1,000 objects. Key batches by
   `(id, geometry_revision)` and skip the work when the revision is
   unchanged. A day or two, no shader changes (`simlab/AGENT_SIMS.md`,
   "What actually makes simple scenes lag").
3. **Read instrumentation.** `performance` counters for raw point reads
   (`get_points`, direct `data["point"]` sites) versus reduction reads
   (bounding box, centre, endpoints, tracker values), tagged by
   whether they happen inside a play, inside an updater, or between
   plays. A day; it is the plan's stated prerequisite and decides its
   sync policy.

Also: fix or delete the two `AppShellE2E` failures
(`missing_module_hint`, `open_scene_from_landing`); they have been red
since before 2026-08-26 and make every full run need a caveat.

Profile anything that lags with `MANIML_PERF_PATH` before choosing:
the two engine costs show up in different stages (`checkpoint.*`
versus `geometry.*`).

## Held: native GL removal (beeline step 4)

Move `--render` onto wgpu-py, fold 2x supersampling into that render,
then delete the native GL pipeline (`rendering/`, the GL parts of
`camera/`, the geometry shaders). Offline output, the browser, and the
fidelity reference become literally the same WGSL, and the fidelity
tests turn into golden-image regression plus CE conformance. **Held by
Taylor on 2026-09-04** until the pause has produced confidence. It is
also the instruction-stream plan's first prerequisite (compute shaders
have to exist in both mirrors), so nothing in that plan starts before
it. Windows/Linux CI and packaging return after it.

## After: the instruction stream

`../simlab/ARCHITECTURE.md`: points live on the GPU permanently, every
operation is an instruction (map / reduce over immutable row buffers,
a scalar table, a clock, a draw list), Python sends instructions at
play boundaries and is idle between them. Checkpoints and true reverse
playback fall out of immutable buffers plus a clock. Phased in
`../simlab/INSTRUCTION_STREAM_PLAN.md`: engine core in shadow, flip the
truth, updaters, the clock owns playback, stateful ops.

It supersedes three things that used to be planned here and are now
removed: the `PERFORMANCE.md` delivery order (revision store, delta
checkpoints, bounded geometry chunks — all of it is what the engine
core is), the geometry-stream recorded-playback layer (reverse
playback is the clock running backward over immutable buffers), and
the parked-scene streaming question (the GPU clock owns updaters, so
Python has nothing to stream for a parked scene).

## Still open, small

- **z_index across top-level groups.** CE sorts one flattened list, so
  a z_index=10 child of group A still draws under group B added after
  A; and a top-level mobject's z_index change after add() reorders only
  on its next add. Within a family it is CE's since 2026-09-02.
- **3D fills.** Triangulated fill flattens each submobject to one
  colour (no gradients), and a mobject morphing under depth test
  re-triangulates every frame (measurable for large Text).
- **`AddTextWordByWord`** groups label/isolate spans rather than words.
  Fix if a course scene uses it; diagnosis in `PERFORMANCE.md`.
- **Typography drift vs CE** for multi-part `MathTex` joins. Cosmetic.
- **Test debt** (2026-08-18 review, still true): `web/cli.py`'s
  `hand_off_to_a_running_engine` restart/reuse branches; `agent`
  `status`/`restart`/`uninstall`/`serve` against the mocked launchctl;
  relay failure paths in `web/app.py`; recents/choose over the real
  control socket; log messages through the app relay.

## Design questions, not scheduled

- **Cell-marked scene files.** Stepping runs a whole unit (a `for` loop
  of plays is one press) and a scene opens on an empty frame because
  its `self.add(...)` preamble shares the first play's unit. Both
  dissolve if authors mark pausepoints with `# %%` cells (Knuth's
  percent format): boundaries stop being an AST guess, the preamble
  gets its own cell, the `many` stacked chip becomes unnecessary. The
  engine already execs units flat against the module namespace, so the
  class is vestigial. Blocks: a script-style file runs on import (exec
  only the preamble, hand the rest to the unit machinery); CE files
  must stay the front door; one file would be one scene unless a cell
  can name one. Not while course production runs on the checkpoint
  engine.
- **Typst text backend** for Tex/MathTex via mitex: kills the texlive
  install burden, faster builds, the same engine as Plass. Independent
  of everything above; do whenever. Watch the conformance drift.

Dropped on 2026-09-04 (see DECISIONS.md, "The roadmap is pruned"): the
snapshot function-rebinding redesign (the instruction stream removes
copy-on-execute, so it lands there), the student-bundle notes track,
and the baked geometry player's restyle and site demo (the player has
no user; the mp4 bundle is the distribution format).

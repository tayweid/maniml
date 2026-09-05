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

1. **The stall at every play boundary.** The one thing that keeps
   coming up in dogfood (Taylor, 2026-09-04). Measured 2026-09-05 on
   the real episodes, headless, `skip_animations`, per unit:

   | scene | early units | late units | on screen late |
   |---|---|---|---|
   | A1 The PPF | 70–120 ms | 400–950 ms | 9–150 members |
   | A3 Trade | 80–180 ms | 900–1,480 ms | often 0 |

   Three facts decide the fix:
   - **It is the copier, not the data.** Copying every point array raw
     in the benchmark scene costs 0.35 ms; the generic `copy.deepcopy`
     of the same 236-object graph costs 22 ms. A mobject carries 47
     attributes, and `parents`/`family` links drag the whole graph in,
     so one leaf costs 5.9 ms through deepcopy and 0.01 ms through the
     project's own `Mobject.copy()`.
   - **It scales with the episode, not the frame.** A checkpoint copies
     everything reachable from the namespace. At A3's last checkpoint
     nothing is on screen, 2,366 family members (38 `Tex`, 28 `VGroup`,
     …) are reachable from 643 names, and one copy costs 429 ms — 400 ms
     of it off-screen objects that have not changed in minutes.
   - **Every unit pays twice.** `run_next_animation` deep-copies the
     current checkpoint before exec (`checkpoint.execution_copy`) and
     `_save_checkpoint` deep-copies again after (`checkpoint.save_copy`).

   The plan, in order, each step measurable on the table above:
   - **A fast, memo-aware `Mobject.__deepcopy__`.** Structural copy in
     the shape of `Mobject.copy()` (data and uniforms by numpy copy,
     submobjects recursively, render-only state — shader wrappers,
     triangulation and bounding-box caches, `_data_has_changed` —
     dropped) that registers itself in the memo so namespace identity
     and `_rebind_functions` keep working. 7–11x on everything, no
     prerequisites. Measured upper bound: `Mobject.copy()` over A3's
     whole namespace is 37 ms against 429.
   - **Skip the execution copy at the frontier.** After a save, the live
     scene and `_live_namespace` already agree and the stored checkpoint
     already holds its own copies; the pre-exec copy only earns its keep
     after a navigation. A flag set by `_save_checkpoint` and cleared by
     any restore halves the remaining cost.
   - **The ledger.** Per-mobject revision counter driven by freezing the
     numpy arrays read-only and unfreezing inside the change-marking
     decorators (design and the history of the failed hashing attempt in
     `../simlab/JANIM.md`, "a ledger, not a deep copy"); pre-seed the
     deepcopy memo so an unchanged mobject maps to its previous frozen
     copy. Per-play cost becomes proportional to what changed, and the
     off-screen 2,366 cost nothing. This is the piece that survives into
     the instruction stream unchanged.
   - **Do not** build copy-on-write checkpoints beyond that: the
     instruction-stream architecture makes checkpoints free.

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

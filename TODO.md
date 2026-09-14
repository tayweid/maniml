# TODO

The forward roadmap, pruned on 2026-09-04 to what is actually planned.
What was decided, shipped, or dropped — and why — lives in
`DECISIONS.md`; the architecture as it stands lives in `CLAUDE.md`;
`docs/performance_2026-08.md` is the 2026-08 measurement record. The target
architecture after the beeline lives beside this repo in
`../simlab/ARCHITECTURE.md`, sequenced in
`../simlab/INSTRUCTION_STREAM_PLAN.md`.

## Where things stand

The browser and native movie/checkpoint output share the Phase A triangle
WebGPU backend. Source points and general fill generation remain on the CPU;
fill-border expansion now runs on the GPU. The
viewer retains **Original 2D** for dogfood comparison, as Taylor requested on
2026-09-10; **Phase A** is the default. Native GL is restored to the package
as the explicit `NativeGLCamera` reference, including its original shaders,
public `ShaderWrapper` and runtime dependencies. See the
[cutover record](docs/unified_triangle_renderer_phase_a.md) for validation and
explicit limits.

## Now: the dogfood pause

Course production on the browser as the only surface is the burn-in
signal. What it has surfaced so far, and what is ready regardless:

1. **The stall at every play boundary.** The one thing that kept
   coming up in dogfood (Taylor, 2026-09-04). Measured 2026-09-05 on
   EpisodeA3 (62 plays, 112 checkpoints, `--render`): the checkpoint
   copy after every play was 192 ms at the median and 2.9 s at worst,
   and the thaw before every unit the same again. Three facts decided
   the fix (the full record is `docs/checkpoint_ledger_plan.md`):
   - **It is the copier, not the data.** `copy.deepcopy` costs about
     27 µs per mobject and nothing per byte; a 13 MB circle copies in
     0.4 ms, a thousand squares in 27 ms.
   - **It scales with the episode, not the frame.** The namespace keeps
     every mobject ever made (31 → 122 variables over A3, all off
     screen by the end) and copied each of them at every play.
   - **Every unit paid twice**: the thaw before exec and the save
     after.

   Landed 2026-09-05 (DECISIONS.md, "Checkpoints are a ledger"):
   - Glyphs share their parsed svg path across copies (it was two
     thirds of the objects visited).
   - **The ledger.** A per-mobject `revision`, bumped by every
     mutation a checkpoint must see; a save pre-seeds the deep copy's
     memo so an unchanged mobject — and everything it references —
     hands back its previous frozen copy. Frozen copies carry no parent
     links and read-only arrays; a thaw rebuilds the links. Per-play
     cost is what moved; history is objects + changes.
   - **No thaw at the frontier.** Stepping forward runs the next unit
     against the live graph; the thaw happens only after a navigation.
   - `MANIML_VERIFY_LEDGER=1` compares every reuse against the live
     object and raises naming the attribute a missed bump left stale.
     The suite runs clean under it; run the course episodes with it
     on during the pause before trusting it unattended.

   **Reuse on thaw landed 2026-09-11** (DECISIONS.md, "A step back
   copies what changed"): a live mobject that is still exactly the
   frozen copy being thawed is handed back instead of copied, so a
   navigation costs what changed between here and there. Still open in
   this item: the optional live-array freeze (plan, Phase 4). **Do not**
   build copy-on-write checkpoints beyond that: the instruction-stream
   architecture replaces large array copies with retained source handles
   and replay recipes under a memory budget.

   **Field-report fixes, 2026-09-10** (DECISIONS.md, "The 2026-09-09
   dogfood report"): the edit-time ghost was a state-only thaw that left
   restored updaters pointing at frozen history; the event queue evicts
   pointer samples instead of closing the socket; `AddTextLetterByLetter`
   is real and exported; the 359 ms `always_redraw` rebuild had already
   dropped to 5 ms with the batched curve construction. Still unverified
   from that report: the uneven appearance of simultaneous fade-ins
   (needs a live repro on the current build).

2. **The per-frame walk of unchanged objects.** Source reads are now
   keyed by `Mobject.revision` (2026-09-10, DECISIONS.md "The renderer
   trusts the revision counter"), and immutable payloads keep their
   digests, so an unchanged 101-glyph frame prepares in about 1.3 ms.
   What remains is the walk itself: per-object uniform conversion, dict
   merges and coalescing, roughly a microsecond-scale cost per object
   that still adds up at a thousand objects. Measure before touching it
   (`simlab/AGENT_SIMS.md`, "What actually makes simple scenes lag").
3. **Read instrumentation.** `performance` counters for raw point reads
   (`get_points`, direct `data["point"]` sites) versus reduction reads
   (bounding box, centre, endpoints, tracker values), tagged by
   whether they happen inside a play, inside an updater, or between
   plays. A day; it is the plan's stated prerequisite and decides its
   sync policy.

**B1 render follow-up, 2026-09-13:** the animation editor's reported
missing-letter artifact was not reproduced in the retained movie frames;
the earlier diagnosis is withdrawn. The [field note](docs/dogfood_2026-09-13_b1_render.md)
records the source/build, 15 fps render recipe, checkpoint/cache comparison,
and verification limits. A complete 60 fps run and browser parity remain
unchecked. Require a captured failing frame before treating this as a
confirmed renderer/cache bug.

The two longstanding `AppShellE2E` failures are fixed: tests bind their own
ephemeral app port and announce geometry mode before waiting for frames, so
they cannot hand off to an unrelated running user engine.

Profile anything that lags with `MANIML_PERF_PATH` before choosing:
the two engine costs show up in different stages (`checkpoint.*`
versus `geometry.*`).

**Selected renderer follow-up (2026-09-09): one triangle backend for 2D
and 3D.** Taylor selected replacing winding fills with generated fill meshes,
using painter order with depth testing/writes disabled for 2D. First preserve
the supported vector appearance with CPU-generated fills, shared output
passes, and resource reuse; then move supported point updates and correct
triangle generation onto the GPU. The existing 3D implementation needs work
on borders, gradients, general paths, and coverage before it can replace 2D.
The architecture, compatibility specification, research, and staged plan are in
[the unified renderer plan](docs/unified_triangle_renderer_plan.md).
It supersedes the earlier atlas proposal; those experiments remain evidence,
not measurements of this new renderer. The [A0 results](docs/unified_triangle_renderer_a0_results.md)
preserve the earlier experiments. The [A1 integration checkpoint](docs/unified_triangle_renderer_a1_integration.md)
records the former opt-in route. [Phase A](docs/unified_triangle_renderer_phase_a.md)
adds shared native output, default 2×/4× AA, stencil fill-border ownership,
source-space fill paint and bounded generated-resource retention. The old
browser winding implementation remains a deliberate dogfood option; do not
remove it without Taylor's direction. Detailed GPU source/geometry work is in
[the separate Phase B specification](docs/gpu_geometry_generation_plan.md).

## Native GL cutover (beeline step 4)

The sixth review corrects the earlier interpretation of Taylor's direction:
**restore native GL to the package as a runnable reference**, keep Phase A
default, and retain Original 2D in the browser. The camera-owned GL reference,
`ShaderWrapper`, original GLSL assets and runtime dependencies are restored.
The wheel check now requires these assets and offers an extracted-wheel GL
capture with tests unavailable. The public-name baseline includes the real
wrapper again. The shared-renderer default stays unchanged.

Indexed-digest normalization, authoritative renderer negotiation, Original 2D
GPU texture retirement, explicit fixed-frame ordering and reusable binary
paint definitions are implemented. General GPU fill borders are implemented
and compared against packaged GL, Original 2D and CPU-border Phase A.
The seventh review's border findings landed 2026-09-10 (DECISIONS.md, "Border
runs reserve from step counts"): capacity from step counts, the strip pattern
built by the drivers (wire format 6), the CPU triangle budget off the GPU
path, occurrence-keyed outputs. The revision-keyed cache and the zoom-step
leftover (both 2026-09-10) bring text within 5% of Original 2D on every
harness control; what a zoom step still pays is mesh refinement, which
only zoom-independent fills remove (Phase B).

**Phase A gates, as of 2026-09-11** (the status list is in the response
document, "Phase A gates: status"):

- Text performance against Original 2D: met, within 5% on every control
  against a 25% gate.
- Zero-border zoomed-text AA: closed by Taylor on 2026-09-11 at 0.88% of
  pixels over the 24/255 threshold against the old 0.5% limit ("AA is
  close enough"), on the independent coverage evidence that favours the
  chosen sampler. No threshold was widened; the harness still reports the
  metric. B1 measures it again on patch edges (`docs/phase_b_plan.md`).
- Nonplanar closed contours: decided, not open. They are refused, and B1
  keeps refusing them; B2's control-net surfaces are the defined interior a
  nonplanar fill would need.
- Large non-affine paint: open, not scheduled, and not a Phase B
  prerequisite. Its per-fragment loop over up to 800 nodes is slow, and its
  interior differs visibly from the historical fan interpolation; the 800-node
  case is a synthetic control, not something a course scene draws. Take it
  when a scene with a large non-affine colour field looks wrong or slow, and
  decide the field's semantics with Taylor first.
The [sixth-round response](docs/unified_triangle_renderer_review_response.md#sixth-round-response-retain-native-gl-and-target-the-measured-regressions)
records verified findings and validation requirements.
Windows/Linux packaging remains separate follow-up work.

## After: the instruction stream

Decided 2026-09-11 (DECISIONS.md, "Everything is Bézier control points"):
one representation for paths and surfaces, evaluated on the GPU at screen
density, no tracer and no fallback representation. The increments, in
order, are in [the Phase B plan](docs/phase_b_plan.md): B1 fills that never
depend on zoom (a prototype week decides winding-on-stencil against
interior-mesh), B2 surfaces as control nets, B3 animations as GPU programs.
The paragraphs below are the earlier framing and remain the contracts for
resources, counts and recovery.

[GPU architecture](/Users/taylorjweidman/Projects/ManimLive/simlab/ARCHITECTURE.md):
source points and supported operations live on the GPU. Map/reduce operations
feed a variable-count geometry-generation stage; coherent vertices and indices
feed the shared renderer. Python sends instructions at play boundaries and is
idle between them for supported work. Source handles and replay recipes reduce
checkpoint copying; a clock permits reverse evaluation of stateless operations.
[The sequence](/Users/taylorjweidman/Projects/ManimLive/simlab/INSTRUCTION_STREAM_PLAN.md)
now includes GPU geometry feasibility and generation before flipping ownership,
then updaters, playback, and stateful operations. Fixed connectivity during
arbitrary morphs is no longer an accepted compromise. The unified renderer
plan supplies the generated-resource and recovery contracts.

It supersedes three things that used to be planned here and are now
removed: the `docs/performance_2026-08.md` delivery order (revision store, delta
checkpoints, bounded geometry chunks — all of it is what the engine
core is), the geometry-stream recorded-playback layer (reverse
playback is the clock running backward over immutable buffers), and
the parked-scene streaming question (the GPU clock owns updaters, so
Python has nothing to stream for a parked scene).

## Still open, small

- **Edit button in the viewer** (Taylor, 2026-09-14). A button that opens
  the scene's `.py` file in the system default editor (`open` on macOS,
  `xdg-open`/`os.startfile` elsewhere), so the edit → hot-reload loop
  starts from the viewer. The page sends an op; the engine opens only
  the file it is serving (never a path from the page), consistent with
  `web/security.py` and the app's recents gate.
- **z_index across top-level groups.** CE sorts one flattened list, so
  a z_index=10 child of group A still draws under group B added after
  A; and a top-level mobject's z_index change after add() reorders only
  on its next add. Within a family it is CE's since 2026-09-02.
- **GPU geometry generation.** General changing paths still rebuild fills on
  the CPU. Phase B owns moving source evaluation and correct variable topology
  onto the GPU. Nonplanar closed contours are refused by design until B2's
  control-net surfaces give them a defined interior (`docs/phase_b_plan.md`).
- **`AddTextWordByWord`** groups label/isolate spans rather than words.
  Fix if a course scene uses it; diagnosis in `docs/performance_2026-08.md`.
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

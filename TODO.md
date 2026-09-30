# TODO

The forward roadmap, pruned on 2026-09-04 to what is actually planned.
What was decided, shipped, or dropped — and why — lives in
`DECISIONS.md`; the architecture as it stands lives in `CLAUDE.md`;
`docs/performance_2026-08.md` is the 2026-08 measurement record. The target
architecture after the beeline lives beside this repo in
`../simlab/ARCHITECTURE.md`, sequenced in
`../simlab/INSTRUCTION_STREAM_PLAN.md`.

## Where things stand

As of 2026-09-28, on `b4-integration` (not merged: `main` stays as Taylor
teaches from it until he runs `git -C
/Users/taylorjweidman/Projects/ManimLive/maniml merge --no-ff
b4-integration`). The browser and native movie/checkpoint output share the
Phase A triangle WebGPU backend, and the **Default** renderer draws Phase A's
stack (Lyon meshes, surface grids, no GPU programs): no Phase B default
passed its gate ([the B4 plan](docs/phase_b4_plan.md), "The flips"; B5.5's
nets passed on the gate's three scenes and failed on scenes that are mostly
surfaces, and B5.7's, drawn as grids are, still fail those two). The
viewer's selector keeps **Default**, **Phase A**, **Phase B** and **Original
2D** (the last for dogfood comparison, as Taylor asked on 2026-09-10). Python
retains the frame and prepares only what changed (tier 1), and a page that
negotiates format 8 is sent only what changed (tier 2): a frame that changes
nothing sends nothing and the page draws nothing. Source points, updaters
and general fill generation remain on the CPU; fill-border expansion runs on
the GPU. Native GL is the explicit `NativeGLCamera` reference. See the
[cutover record](docs/unified_triangle_renderer_phase_a.md) for Phase A's
validation and limits.

**The final test point** (the B4 plan's section of that name, 2026-09-28)
measured what a lecture frame costs the page, against today's `main`: a
still pausepoint 11.10 → 0.78 ms (EpisodeB2) and 8.26 → 0.78
(PriceDiscovery), nothing sent; a pausepoint whose updaters tick 31.24 →
3.02 and 12.29 → 1.05, nothing sent; a play frame 22.75 → 14.83 and 13.52
→ 7.86 ms (the GPU part the native driver's, as the gate defines it; the
page's GPU pays less, the plan's reading). Found there: the forced Phase B's
GPU programs draw a PriceDiscovery play wrong (2.02% of the pixels, measured
before the fix), being fixed in a session of its own.

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
density, no tracer and no fallback representation. Taylor's end state, as
the B4 plan quotes it: Python sends the control points once and only directs
the GPU what to change; if nothing changes, Python is silent. Where that
stands (the plans hold the record: [Phase B](docs/phase_b_plan.md), [B1](docs/phase_b1_plan.md),
[B2](docs/phase_b2_plan.md), [B3](docs/phase_b3_plan.md),
[B4 and after](docs/phase_b4_plan.md)):

- **Built behind flags, measured, not the default.** B1's patch fill
  (`MANIML_FILL=patches`: a fan and a count, no mesh), B2's surfaces as
  control nets (`MANIML_SURFACE=nets`), B3's animations as GPU programs
  (`MANIML_PROGRAMS=shadow|gpu`, and B5.3's `strokes` on Phase A). Both
  drivers draw all of them and the recording player reads them. The
  viewer's **Phase B** selection runs them together on any scene, its
  patches sent as rows: B5.1's rows on the wire are the patch source
  wherever patches are drawn since B5.6 (`MANIML_PATCH_SOURCE=records` the
  override), pixels identical, the golden pin untouched (it states
  records). B6's test point retaken with both: 8.a's play 127.3 → 80.5 ms,
  every class's median within 0.5 ms; navigations +15-28% natively, until
  B5.8 took item 2's two levers for rows (EpisodeB2 now below records,
  PriceDiscovery above by its render).
- **Shipped.** B4's retained frame (Python prepares only what changed,
  byte-identical on the wire) and format 8 (a negotiated page is sent a
  delta per change, and nothing at rest).
- **Gated and not flipped** (B5.4, "The flips"): patches on both episodes'
  plays and ticked frames (1.15× and 1.48× Phase A's plays), strokes
  programs on Python no lower than programs off.
- **Flipped: surfaces are nets** (B5.9, 2026-09-29). Nets failed on camera
  moves (1.25-1.34× grids); B5.5 evaluated a frame's changed nets in one
  dispatch keyed on their step counts and passed the gate's three scenes
  (camera moves 0.997-1.046×), then failed on scenes that are mostly
  surfaces (70 spheres 1.16-1.31× on still and camera frames, 480 spheres
  1.37-1.52× and 0.98% of the pixels). B5.7 drew each net's steps (a
  quarter of the triangles) and coalesced nets as grids are, and judged
  the gate over a timed set holding those two scenes: 1.06-1.15× and
  1.11-1.24×, the lattice's pixels unchanged (silhouettes where nets are
  the rounder). Taylor then made the pixel gate accuracy against the true
  surface, which nets pass everywhere (the lattice 0.67% of its pixels off
  against grids' 1.38%), and accepted the still and camera cost, so
  `geometry.DEFAULT_SURFACE` is `nets`; Phase A keeps grids. Left: the
  cost itself (the page's per-member walk of a run on a camera move, the
  serializer's per-net `keep` and reservation check, B5.7's levers), the
  draw-order bands of a translucent surface that overlaps itself, which
  nets put patch by patch where grids put them row by row, and
  `sort_faces_back_to_front` / `always_sort_to_camera`, which reorder the
  grid's triangles and nothing a net draws (no course or dogfood scene
  sorts; a net drawing its patches in the sorted order, or a sorted
  surface falling back to its grid on the Default, would restore it).
- **Measured as the default, not flipped: the whole Phase B stack**
  (B5.10, 2026-09-30, the plan's "Phase B as the default"). Taylor's
  condition: nowhere above 1.25× Phase A, more than half at or below
  1.0×, the page and the GPU on the device (Chrome's Dawn). EpisodeB2 and
  PriceDiscovery pass every class (worst 1.087×, plays 0.64× and 1.07×);
  the surface scenes' camera moves and navigations fail (orbs 2.74× and
  1.74×, lattice 1.63× and 1.55×: the nets' draw and evaluation on the
  device, which the Default already pays since B5.9, where B5.7 measured
  1.06-1.24× with the native GPU) and so do EpisodeB3's ticked frames
  (1.38×); 9 of 23 cells at or below 1.0×. Whether a default is judged
  against Phase A or against the Default it replaces, and whether the
  nets' device cost stands, are Taylor's. Levers: the page's buffer a
  net on a navigation (70 `createBuffer`s on the orbs' navigation, ~30 µs
  each through Dawn's wire) and the nets' triangles; EpisodeB3's dashes
  (item 5); the walk at rest (item 6). Taylor, 2026-09-30: "Keep Phase A default for
  now." Open from the review, before the gate is taken again: repeat the
  device cells and give them an interval (they were measured once); the
  navigation class judges revisits only (first visits are measured beside
  it); apply the GPU-idle check to the device runs, not only the serialize
  runs; an unsplit stream's play fetches a missing `parts.json` (a 404 in
  the console).
- **Measured whole** (B6, "The final test point"): the numbers under
  "Where things stand" above.

What is left, from B6's reading, each with its measured size (the plan's
reading has the rest):

1. **Fixed 2026-09-28 (c787d9d1): Phase B's GPU programs drew a
   PriceDiscovery play wrong**: the rays of a lagged fade-in drawn opaque
   in a neighbouring dashed line's paint, 2.02% of the pixels as B6
   measured it, where the CPU path draws them nearly transparent.
   `pack_rows` now writes a source's base-point rows from its first point,
   as the CPU path's read does; the GPU path against the CPU path on the
   plays into 48, 58, 68, 86 and 109 is 0 pixels. B6's Phase B play pixels
   predate the fix; B5.6's retake of the test point has them after it.
2. **One dispatch per kernel** for a frame's programs, in both drivers,
   as B5.5 made it for nets and B5.8 for rows (a table the kernel reads,
   the inputs gathered and the outputs copied into what their slots own,
   the state keyed on exactly what the output reads). It stands in front
   of the programs flip: Phase B's plays pay 1.5-2.4 ms of program passes
   and 1.7-1.9 ms of border passes a frame (GPU 9.4-9.7 ms against Phase
   A's 4.3-5.4). **Rows: done by B5.8** (the plan's "The flips"): a frame's
   rows in one dispatch of `row_finalize_table.wgsl`, and a path's rows
   sent as their geometry (keyed on it alone) and their paint, so a dim
   sends paints and no rows. A navigation natively is below records on
   EpisodeB2 and above on PriceDiscovery (its render, +0.4 to +1.6 ms;
   B5.6: +15-28% on both), the page's dispatches for it 74 and 26 where
   they were 206 and 107. Its gate was not met as written; what is left:
   the page's median JavaScript on a navigation in format 8 (2.33 → 2.6 and
   1.5 → 2.05 ms, PriceDiscovery's worse than B5.6's rows' 1.73), whose
   cause is not isolated: it is the delta path's (format 7 sends the same
   definitions and reads close to records), the harness moves it (one
   message reads 2.6 or 1.0 ms by whether Node's stderr is a pipe), and the
   candidates are the delta path's allocations (the row staging
   reallocated after `releaseRowScratch` drops it, a member object a slot,
   the completed-state objects); PriceDiscovery's native render on a
   navigation; the serializer's split of a mover's rows, 4.2 ms a frame of
   8.a's play (the paint extracted and checked every frame though it
   rarely moves, the paints' digests and names in every batch); and the
   `row_paints` every batch names, 13 KB of a format 7 still message on
   EpisodeB2 (98.4 KB against records' 71.7), which native capture and
   every recorded export frame pay (a batch could name a paint only where
   it differs from what its geometry last carried). The
   nets flip is B5.7's to read: its redraw levers are taken (each net's
   steps' pattern, runs as grids have), and on the surface-heavy scenes
   it still fails by the GPU of the triangles that make a net round
   (+0.2-0.4 ms), the page's per-member walk of a run on a camera move
   (+0.1-0.25 ms), the serializer's per-net `keep` and reservation check
   (+0.03-0.4 ms), and the lattice's pixels, which the gate measures
   against the grid. Whether that pixel test should measure against a
   reference surface, and whether a surface-heavy frame may cost 6-25%
   more for no facets at any zoom, are Taylor's (the plan's B5.7, "What
   would flip it").
3. **A mover's batch keeping its identity**, its program scalars or rows an
   op: a program is a batch of its own, encoded and diffed every frame
   (5.a's play under Phase B: 18.7 ms of encode and 3.3 of diff of 26.5).
4. **Updaters on the GPU's clock.** The episode's own updaters are now the
   largest Python cost at rest: 20.7 ms a tick at 8.a against 4.6 ms of
   serialize; 1.45 ms on PriceDiscovery. This is the instruction stream's
   step (below).
5. **The revision counter's over-signalling**: a tick at 8.a bumps 415 of
   531 leaves and changes no byte, 1.83 ms of its 4.59 ms serialize to
   compare and keep them. The fix is upstream in the mutators and changes
   the contract the ledger relies on. A worse case (B5.10): EpisodeB3's
   ticks leave 40 dashes of a `DashedVMobject` with the joint-angle flag
   set and their subpath ends cached, a state `compare_rows` refuses
   without a refresh's own ends (`entry.ends`, recorded only where both
   flags were set and the ends uncached), so the retained frame prepares
   them again every tick with the same bytes: Phase A into 10 runs, Phase
   B into 73, which is EpisodeB3's ticked 1.38×.
6. **The walk that finds nothing changed**: 0.8-2.4 ms a still frame,
   which the viewer runs for every prompted frame (input, at most 45 a
   second). Silence in Python means not walking at all. B5.10 took the
   coalescing and the encode out of a frame whose draws are the last
   frame's (the runs reused, the idle message returned): EpisodeB2's
   still frames 0.44 ms on either stack, 3.i's ticks 0.82-0.84; the walk
   and the keeps remain.
7. **A Phase A mover**: Lyon's 11 ms and ~200 µs a leaf besides on 8.a's
   play (84.6 ms of preparation); the retained frame's bookkeeping where
   every leaf moves (5.a's play 85.2 → 93.3 ms against today; tier 1's
   named fast path). B5.1's rows halve 8.a's play under patches. Taylor's
   call, still open: whether the retained frame's flip stands for
   `--render`, where a render made mostly of whole-scene moves pays that
   bookkeeping (5.a's play +16%).
8. **B3c, the declarative updaters** (`always_shift`, `always_rotate`,
   `f_always`, and the reductions streamed back with an evaluation stamp;
   [the B3 plan](docs/phase_b3_plan.md)), the next B3 step and still
   unbuilt: it is what puts item 4's updaters on the GPU where they are the
   library's. Open beside it: `MoveAlongPath`, `Homotopy` and the other
   per-point functions stay on the CPU.

B5.2, the patch run rule, is not warranted by its condition (B6: the draw
count costs ~0.8 ms of native GPU and of page per drawn Phase B frame, none
at rest). The condition of B4.9, render bundles, is not shown either way: a
redraw of 911 slots on this machine's WebGPU costs the page 0.89 ms of
JavaScript at the median (rounds 0.64-1.19 ms, taken at load 5-9, the
renderer side of Dawn's wire only), and Dawn's GPU-process side was not
isolated; a quiet retake with it isolated (a redraw at a tiny resolution,
or a Chrome trace) settles it. Nothing is redrawn at rest under format 8
either way. Open from B4.8 and tier 1, as the plan records them:
EpisodeB2's dearest play frames stay over B4.8's play gates (their uploads),
its Phase A seeks cost the page ~0.1 ms more under format 8, and the 8.a
seek-up gate (≤ 8 ms) is unverified until it runs on a quiet machine.

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

## Handles: what shipped 2026-09-25, and what is left

`Mobject.set_draggable(along=, on_drag=)` shipped on the `orbit` branch
with the orbit gesture (CHANGELOG, "The viewer"; the demo is
`econ-0100/DragDemo.py`). Left open:

- **Picking in 3D.** The hit test compares world bounding boxes with a
  point on the camera plane, which is wrong once the view turns (it is
  why a plain press does not grab where a drag orbits; alt does). A
  handle in a `ThreeDScene` needs the boxes projected to the screen and
  a drag plane at the mobject's depth. A day or two, when a 3D episode
  wants one.
- **Exports stay still.** The mp4, the student bundle and the baked
  player have no Python in the loop, so no updaters and no handles.
  Interactive handles there wait for the instruction stream, where a
  follower is an instruction the page can evaluate.
- **A pointer round trip in `tests/test_web_viewer.py`** for the hover
  message and a present-mode drag; today the handlers are unit-tested on
  window=None scenes (`TestHandles` in `tests/test_modes.py`) and the
  page was driven by hand.

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

- **ManimLive.app** (`docs/app_plan.md`): built (step 1): a launcher script,
  the shape of Edit <course>.app, that starts the engine and opens the page
  as the installed Chromium browser's app window; the engine stops three
  minutes after its last window. Next: retire the agent and the PWA, a
  one-line install for others (deploy-built wheel + uv), Windows with Edge.
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
  of everything above; do whenever — except that the app above needs it
  before it is for anyone without a TeX install. Watch the conformance
  drift.

Dropped on 2026-09-04 (see DECISIONS.md, "The roadmap is pruned"): the
snapshot function-rebinding redesign (the instruction stream removes
copy-on-execute, so it lands there), the student-bundle notes track,
and the baked geometry player's restyle and site demo (the player has
no user; the mp4 bundle is the distribution format).

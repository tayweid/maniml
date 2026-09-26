# Phase B3 plan: animations as GPU programs over control points

Written 2026-09-11 at the start of B3, from `phase_b_plan.md`, the
instruction-stream contract (`../simlab/INSTRUCTION_STREAM_PLAN.md`, Phases
1 and 2, and `../simlab/ARCHITECTURE.md`), the read tables
(`read_instrumentation_2026-09-11.md`) and a survey of the play loop.
Status: B3a (the blend) and B3b (affine, paint, partial) built
2026-09-11 in both drivers, behind `MANIML_PROGRAMS`; results at the end. Taylor's direction: "ok lets move on
to B3", then "go ahead and start B3a". Phase A stays the default renderer;
programs feed the Phase B patch and net stages, so they land behind their
own switch and only with those on.

## What a play costs today, and what a program removes

`Scene.play` runs one Python frame per tick: for every animation,
`interpolate(alpha)` rewrites the animated mobject's data from its two
endpoints, then `update_frame` serializes the scene, where the renderer
re-reads every object whose revision moved. The read tables say what that
is on the course: inside a play, every top raw-read site is the engine's
own, `Transform.interpolate_submobject` and the renderer's re-read
(`triangle_scene.py:read`), 700,000 raw reads on EpisodeA3 between them;
no scene code reads points during a play. Between plays the scene reads
little, and only reductions (bounding boxes, endpoints, tracker values).

So the target is exact and small: for a supported animation, Python stops
rewriting rows every frame and sends the GPU a **program** once, with a
scalar per frame; the GPU evaluates the rows, and the Phase B stages draw
them from there. What Python keeps doing per frame is the cheap part it
already does beside the rows: lerp the uniforms and the 3×3 bounding box
from the endpoints' boxes, so every reduction a reader might make between
frames stays correct without the rows.

## The representation, and why the first program is a lerp

A VMobject's data is one float32 row per control point, seventeen floats:
`point`, `stroke_rgba`, `stroke_width`, `joint_angle`, `fill_rgba`,
`base_normal`, `fill_border_width`. `Mobject.interpolate` lerps **every
column** of it between the two endpoints (the point column through the
path function, which is a straight lerp for every animation but arcs),
lerps the uniforms, and lerps the bounding box. The derived columns, the
joint angles and the unit normals, are computed at `Transform.begin` for
both endpoints and lerped too; nothing is recomputed mid-play. A GPU
program that lerps the same seventeen floats per row therefore reproduces
the CPU's rows to float32, and the survey found no per-frame recomputation
to mirror. The renderer's own derivations from the rows, the curve records
of the border stage and the stroke instances, are gathers plus a density
per curve, which is one small kernel.

Rows are the source: authoritative, one blob per endpoint per play,
content-addressed like border and net sources today. Everything the
renderer draws for a VMobject comes from rows: the 68-byte stroke instance
is three consecutive rows, and the 44-word curve record of the border and
patch stages is a 12-word subset of the same three rows plus a density and
flags (`gpu_border_geometry.pack_source`). A `finalize` kernel produces both
from evaluated rows; the border compute, the patch fill and the stroke
pipeline then bind those buffers instead of uploaded ones. Nothing
downstream changes.

## Programs

Each is a WGSL map over rows, shared by both drivers, with its scalars on
the wire per frame (a few floats; the frame loop stays in Python, see
"The clock" below).

| Program | Animations | Rows in | Scalars | Notes |
| --- | --- | --- | --- | --- |
| `blend(a, b, alpha)` | `Transform`, `ReplacementTransform`, `.animate`, `MoveToTarget`, `FadeIn`/`FadeOut` (they are transforms), `Transform` of surfaces (nets) | two aligned sources | alpha | straight path only; `path_along_arc` stays on the CPU until an `arc` program exists |
| `affine(M, about)` | `Rotate`, `Rotating`, `MoveAlongPath` (a shift per frame), `.animate.shift/scale/rotate` when the target is exactly affine | one source | 16 + 3 | the matrix is computed on the CPU per frame from the animation's own state |
| `paint(rgba, which)` | `VFadeIn`, `VFadeOut`, opacity-only `.animate.set_opacity` | one source | 4 | writes the fill or stroke colour columns |
| `partial(a, b)` | `ShowCreation`, `Uncreate`, `Write`'s border phase, `DrawBorderThenFill` | one source | 2 | the per-curve split `pointwise_become_partial` does, with the joint-angle zeroing outside the span |

Lag ratios (`LaggedStart`, `Write`) become a per-row `(start, end)` pair
computed once at `begin`, so a lagged play is still one program with one
alpha. `AnimationGroup` and `Succession` are several programs. Anything
without a program keeps today's path, per animation: a play can mix.

**The clock.** The instruction-stream plan puts a clock with rate tables
in the engine so that it paces itself. That buys nothing until Python
stops ticking frames, which is Phase 4 (reverse playback and scrubbing).
Until then Python evaluates the rate function and lag on the CPU and sends
the resulting alpha per frame, a scalar. The clock is deferred with the
frame loop, not dropped.

## Shadow first, then the flip

1. **Shadow.** Under `MANIML_PROGRAMS=shadow`, a supported animation
   still rewrites rows on the CPU exactly as today, and the frame also
   carries the program (sources once, scalars per frame). The renderer
   draws from the CPU rows; a test renders each frame both ways and holds
   the pixel gate (0.5% of pixels over 24 of 255) at every alpha, on the
   fixture corpus, the dogfood scene and one course episode.
2. **The flip.** Under `MANIML_PROGRAMS=gpu`, `interpolate_submobject`
   for a supported animation records the program on the mobject and lerps
   only the uniforms and the bounding box; the rows are not written. The
   renderer draws the program's output. Two guarantees keep this honest:
   - **A raw read materializes.** `get_points` (and any direct row read
     through the accessors) on a mobject with a pending program evaluates
     it on the CPU first, so a reader that does ask for rows mid-play gets
     the same rows the GPU is drawing. The read tables say the course
     never does; the guarantee is for correctness, and it is instrumented.
   - **The play ends exactly.** `finish` writes the final rows on the
     CPU as today, so the state after the play, and the checkpoint the
     ledger takes from it, are byte-identical to today's.
   Reductions never see a stale box because the box is lerped as today.
   Updaters on the animated mobject are suspended for the play as today;
   updaters on other objects that read this one read reductions, which are
   fresh.
3. **Both mirrors, then measure.** `webgpu.js` follows the native driver
   as in B1 and B2; the Node harness checks the command sequence on real
   frames. Then the plan's numbers: per-frame Python during a `Transform`
   of the 101-glyph text and of a 1,000-square group (the instruction
   stream's proposed target is under a millisecond), raw reads in the play
   phase (should fall by the two engine sites), and complete frames against
   today in the two-variant harness.

## Data and wire

- **Sources.** `program_data` spans beside `border_data`: a mobject's rows
  as float32, hashed by content, sent once and retained while referenced,
  as border and net sources are.
- **Program batches.** A batch of pipeline `patch`, `stroke` or a net
  pipeline carries `program: {kind, sources: [hash…], scalars: […]}`
  instead of, or beside, its retained source; the driver evaluates rows,
  finalizes, and binds the finalized buffers where the retained ones went.
  Outputs are keyed by (batch, program, occurrence) and re-evaluated when
  scalars or sources change, so a still frame after a play evaluates
  nothing.
- **Grouping.** Patch runs of program objects draw ungrouped (a morph can
  change an object's winding sign), one object per group; text is not a
  blend, so this costs nothing where grouping matters.
- **Format** 7 is extended in place: nothing already on the wire changes,
  and the recording player's indexing of program batches is the same open
  item as for patch and net batches.

## Sequence

1. **B3a, the blend.** The `finalize` kernel and the `blend` kernel in the
   native driver; `Transform.program()` on VMobjects and nets; shadow
   mode; the pixel gate at ten alphas on the corpus; then the flip with
   the materialize-on-read guarantee; then the browser mirror. This is
   `.animate` too, which is most of what the course plays. One to two
   weeks.
2. **B3b, the rest of the library.** `affine`, `paint`, `partial`, in
   that order, each shadow-then-flip with the same gate; `Write` last,
   since it composes `partial` and `blend` with a per-row lag. One to two
   weeks.
3. **B3c, the declarative updaters.** `always_shift`, `always_rotate`,
   `f_always` over the library, and the reductions (bounding box,
   endpoints, tracker value) computed on the GPU and streamed back with an
   evaluation stamp, which is what lets `next_to` a moving thing stay on
   the GPU. This is the instruction stream's Phase 3a and is planned after
   B3b is measured, not before.

## Acceptance

Pixels within the existing gate against the CPU path at every alpha in
both mirrors; the state after every play byte-identical to today's (the
ledger's verify mode is the check); per-frame Python during a supported
Transform measured against the target; play-phase raw reads down by the
two engine sites; the full suite green under `MANIML_VERIFY_LEDGER=1`.

## What to watch

- **float32.** The CPU lerps in float64 and casts; the GPU lerps in
  float32. The pixel gate is the arbiter; a last-digit difference in a
  control point is not visible, and CE conformance tolerances already
  allow it.
- **Structure changes at the play's end.** `Transform.finish` may drop
  alignment padding (`_adopt_target_structure`); it happens after the last
  frame, on the CPU, as today.
- **Locked keys.** `lock_matching_data` marks columns equal at both ends;
  a lerp of equal columns is the column, so the program needs no
  special case, and the survey found no other use of the lock in the play
  loop.
- **Mixed plays.** A play with one supported and one unsupported
  animation runs both paths in one frame; the ordered draw list already
  mixes retained and generated sources per batch.
- **Reads that bypass the accessors.** A direct `data["point"]` write or
  read on an animated mobject mid-play does not go through the
  materialize guarantee; the ledger's verify mode names such writes today,
  and the same audit lists the read sites (nine files, per the matrix
  research) to route through the accessor.

## B3a results (2026-09-11)

Built as sequenced: the two kernels, the shadow, the flip, both mirrors.

**What landed.** `row_blend.wgsl` (mix over every float of two row-aligned
sources) and `row_finalize.wgsl` (44-word curve records and 51-float
stroke instances from evaluated VMobject rows, the density per curve
computed as the CPU computes it). `MANIML_PROGRAMS=off|shadow|gpu`
(`maniml/utils/programs.py`), which needs `MANIML_FILL=patches`.
`Transform.interpolate_submobject` records a blend program on each
submobject for the straight path when the endpoints' rows align
(`Mobject.blend_program`); an arc, or any endpoint pair that does not
align, interpolates on the CPU as before. In `gpu` mode the rows are not
written: the uniforms and the bounding box are lerped as today, the
revision is bumped so the ledger and the renderer see a change, and the
program is drawn. `Transform.finish` writes the final rows
(`finish_program`), so the state after a play is the rows in every mode.

**Materialize on read.** `Mobject.data` is a property: a read while a
program is pending evaluates it on the CPU first (the same expression
`interpolate` uses, so the rows match what the GPU draws to float32) and
counts `program.materialize`. That covers every accessor and every direct
`data[...]` read, not only `get_points`, so the audit of read sites the
plan anticipated was not needed. Counts read no rows (`get_num_points`,
`has_points`, `family_members_with_points` use the array behind the
property), copies and checkpoints materialize first and carry rows only,
and assigning `data` supersedes the program. The renderer's program path
reads counts, dtypes and the endpoints' rows, never the animated rows: a
test renders a whole play with materialization forbidden.

**Wire and drivers.** A program batch (`patch`, `stroke`, or a net
pipeline) carries `program: {kind, sources, scalars, rows, channels}`;
`program_data` spans send a mobject's rows once per play by content hash.
After the first frame nothing but the scalar travels. Each driver
evaluates changed programs before any other stage; outputs are keyed by
(program, occurrence of its scalars in the frame), so an object's fill and
stroke batches share one evaluation and an output stays in place as its
alpha moves; the border stage binds the finalized records where retained
ones went, the net stage the blended net, the stroke pipeline the
finalized instances. A program's draw needs are summarized once per source
set (`ProgramRecipe`: curve count, which stages apply, the larger
endpoint's density, the object record); per frame only the zoom-dependent
counts are evaluated, and the border reservation is kept across frames.
A program net's reservation follows the larger endpoint's density, so its
step count can differ from the CPU path's for the same net; the pixel gate
is the arbiter there, as for every zoom.

**Parity.** Circle→Square (fill, border, stroke) and text→text: every
mode draws the same pixels at six alphas (maximum difference 1 of 255 in
the native driver), and the state after the play is byte-identical
across modes. Sphere→Torus nets hold the pixel gate at every alpha (the
reservation differs, above). The browser mirror: the Node harness checks
the command sequence on real frames (blend and finalize share a pass, the
border stage reads the finalized records, the stroke draws the finalized
instances, sources and outputs are reused across alphas, nothing is
evaluated when the scalar repeats, everything retires); live in the
preview browser, four frames (two alphas, a repeat, a 4× zoom) matched
the native renders on a 32×18 cell-mean grid to 0.03 of 255.

**Per-frame Python during a `Transform`** (1920×1080, interpolate +
serialize, medians over 30 frames, `MANIML_FILL=patches` in both):

| Case | off | gpu | Wire per frame, off → gpu | Raw reads per frame, off → gpu |
| --- | --- | --- | --- | --- |
| 86-glyph text | 23.6 ms | 2.4 ms | 802 kB → 66 kB | 181 → 9 |
| 1,000 squares | 257 ms | 50 ms | 2.7 MB → 1.3 MB | 2009 → 9 |

`Transform.interpolate` itself: 1.2 → 0.3 ms (text), 10 → 4 ms (squares).
What remains in the squares case is the serializer's per-batch cost, two
batches per object (about 23 µs each, JSON descriptors); the wire is those
descriptors. The play-phase raw reads fell by the two engine sites the
read tables named; the nine that remain are the camera's. The instruction
stream's target of under a millisecond is not met on the text case; it
needs batching program objects, which B3's grouping note leaves for after
the library is covered.

**Open.** The paint field over blended rows (per-vertex fill colour) and
shading fall back to the CPU path (B3b's `paint`); `path_arc` transforms
stay on the CPU until an `arc` program exists; `FadeIn`/`FadeOut` and the
other subclasses that override `interpolate_submobject` keep their CPU
path for now; the recording player does not index program batches, as for
patch and net batches; the default stays `off`, Taylor's call with the
other Phase B switches.

## B3b results (2026-09-11)

The rest of the library as planned, each program shadow-then-flip with
the same gate, and the browser mirror of all three.

**Programs.** `affine` (`row_affine.wgsl`, 16 scalars: the 4×4 map,
column-major) for `Rotating` and `Rotate`: the start's points through the
matrix, the base point rows with them, the unit normal as a direction.
`paint` (`row_paint.wgsl`, 2 scalars) for `VFadeIn` and `VFadeOut`: the
start's rows with every row's stroke and fill opacity set. `partial`
(`row_partial.wgsl`, 5 scalars) for `ShowCreation`, `Uncreate`,
`ShowPassingFlash` and the border phase of `DrawBorderThenFill` and
`Write`: the curve indices and residues come from the CPU
(`integer_interpolate` in float64, `wire_scalars`), so the kernel's only
arithmetic is the Bézier evaluation; the fill phase of `Write` is the
blend with the same path function on the CPU side. Each has a CPU
evaluation that is the CPU path's own arithmetic (`Mobject.record_program`
takes it), so materialized rows and the state after a play are
byte-identical to the CPU path's; `pointwise_become_partial` and the
`partial` evaluation share `partial_points`. `MoveAlongPath` stays on the
CPU: its CPU path accumulates a shift per frame from the current box, and
a program from the start would end an ulp away. `.animate` is the blend
already.

**Composition.** A CPU mutation supersedes a pending program
(`note_changed_data` drops it after the read behind the mutation
materialized it), so a `VFadeIn` on top of a `Transform` in one play, or
an updater's write, composes as the CPU path does; a `VFadeIn` records
its program only when no updater runs on the family and no other
animation's program is pending on the member. Recording a program bumps
the revision without dropping it (`_bump_revision`); a child's change
bumps its parents the same way. A program's source has its derived
columns computed once at `begin` (`programs.freshen`: joint angles, unit
normal, base point rows), since the renderer refreshes them on the
animated rows when it reads them and a program's rows are never read.

**Two fixes to the fill itself, found by the gate.** The patch fill's
fan now takes each curve's base point from its own record (its path's
first point) rather than the object's anchor centroid: a closed subpath
counts the same from any base, and an open one then closes through its
start, the chord Phase A's fill closes it with; the centroid of a partial
path closed it through a point that moved with the path. And a partial
path now carries its source's unit normal, as it already carried its
joint angles: `DrawBorderThenFill`'s `set_data(outline.data)` dirties the
normal flag, the renderer then computed the normal from the frame-0
points, which are one point, and cached DOWN for the whole border phase,
so the outline of every `Write` was drawn edge-on. That is on `main` too;
it is fixed at the root in `pointwise_become_partial`.

**Parity.** Native: rotate (about OUT and about an oblique axis), fade in
and out, creation, uncreation, a passing flash all draw the same pixels as
the CPU path at eight alphas (maximum difference 1 of 255); `Write` holds
the gate (0.003% of pixels over 24, the float32 blend of its fill phase);
the state after every play is byte-identical across modes; a gpu-mode play
materializes nothing until `finish`. Browser: the Node harness runs every
row kernel on a real frame (`programKindsWire`); four frames in the
preview browser (a rotation, a fade, a creation and a write at two alphas,
a repeat, a 4× zoom) matched the native renders on a 32×18 cell-mean grid
exactly.

**Per-frame Python** (1920×1080, interpolate + serialize, medians over 30
frames, `MANIML_FILL=patches` in both):

| Case | off | gpu | Wire per frame, off → gpu | Raw reads per frame, off → gpu |
| --- | --- | --- | --- | --- |
| `Write`, 86-glyph text | 8.3 ms | 3.7 ms | 963 kB → 109 kB | 109 → 44 |
| `ShowCreation`, 86-glyph text | 5.4 ms | 2.4 ms | 802 kB → 63 kB | 106 → 16 |
| `VFadeIn`, 86-glyph text | 23.1 ms | 2.3 ms | 798 kB → 64 kB | 98 → 15 |
| `Rotate`, 1,000 squares | 265 ms | 65 ms | 2.7 MB → 1.6 MB | 2076 → 109 |

`Write`'s remaining reads are its index transitions (`match_style`,
`set_data`, once per glyph) and its completion cache; the squares are the
serializer's per-batch cost, as in B3a.

**Open.** `MoveAlongPath`, `Homotopy` and the other per-point functions
stay on the CPU; `ShowIncreasingSubsets` and the submobject-list
animations write no rows and need nothing; the recording player does not
index program batches; the default stays `off`. B3c (declarative updaters
and the streamed reductions) is planned after this is measured on the
course.

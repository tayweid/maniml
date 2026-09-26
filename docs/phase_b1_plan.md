# Phase B1 plan: fills as fan and patch geometry on the stencil

Written 2026-09-11 at the start of B1, from `phase_b_plan.md` and a
mechanism probe on this machine (`benchmarks/probes/fan_stencil_probe.py`);
the mechanism section was revised the same day as the prototype was built
and measured (the "Prototype results" section at the end). Taylor chose the
fan over a CPU mesh on 2026-09-11 (`DECISIONS.md`, "Fills are a fan and a
count, not a mesh"). Nothing here changes a default; the patch fill is
behind `MANIML_FILL=patches` and the verdict on it is Taylor's, on the
measurements below.

## What the probe showed (2026-09-11, Apple M3, wgpu 0.32, Metal)

The B1-fan construction was run standalone on the fixture corpus's winding
cases, drawn as fan and patch triangles straight from quadratic control
points, counted on the stencil, and covered:

| Case | Result |
| --- | --- |
| annulus_hole, nested_contours (three alternating contours) | every coverage probe correct |
| quad_convex, quad_concave (the morph endpoints) | correct, no triangulation anywhere |
| repeated_winding (×2), reversed_winding, 127-fold winding | correct |
| 128-fold winding | wraps to zero: the documented limit of a 7-bit count |
| a self-overlapping border ribbon beside a fill | painted exactly once |
| two objects in sequence | the second sees no leftover count from the first |

Antialiasing, 4× MSAA on a 1× target, the sixteen-curve circle of radius
1.2 against its analytic coverage: with the patch test evaluated at the
pixel centre, max error 124/255 and 136 pixels off by more than 24; with
`@interpolate(perspective, sample)` on the patch coordinates, max error
62/255 and 76 pixels off. Sample-rate shading works on this wgpu and is
required; production adds the 2× supersample on top, so sixteen effective
samples per output pixel, the same quantization the mesh edges get today.

## The mechanism

Every closed path is drawn in one ordered pass, in draw order, with four
draws per **group** (an object, or a run of objects allowed to share a
count, below) and no geometry that depends on zoom:

1. **Mark.** For each curve `(p0, p1, p2)` of the object, the fan triangle
   `(base, p0, p2)` and the patch triangle `(p0, p1, p2)`, pulled by
   `vertex_index` from the curve records already on the GPU, one instance
   per object. No colour writes. Stencil: `increment-wrap` for front faces,
   `decrement-wrap` for back faces, write mask `0x7F`. The rasterizer's
   facing supplies the sign that `fill.wgsl` computes from a determinant,
   and the patch's fragment shader discards where `y − x² < 0` in the
   triangle's own coordinates, evaluated per sample. Sentinel curves
   (`p0 == p1`) emit nothing, as in `fill.wgsl`; a straight curve's patch
   has zero area. The clip-plane discard applies here too, so a clipped
   region counts as outside.
2. **Mark strips** (bordered objects only). The border strips the compute
   stage already writes, drawn through the ordinary `surface` pipeline
   from the format 6 index pattern, with `replace` of reference `0x80`
   under write mask `0x80` and no colour. Strips overlap at joints and on
   tight curves with arbitrary facing, so they cannot take part in the
   count; a bit of their own makes them order-independent instead.
3. **Cover.** The fan and patch triangles again with the colour fragment
   (`surface` or `paint`, lit by the object's plane normal), then the
   strips again through the ordinary `surface` or `paint` pipeline.
   Stencil compare `not-equal 0` against reference 0, `pass_op: zero`,
   `depth_fail_op: zero`, write mask `0xFF`. The first fragment at a sample
   paints and zeroes; every later one is rejected, so a translucent object
   paints each sample once whatever overlaps inside it, and the stencil is
   returned to zero exactly where it was touched. Depth-tested objects test
   and write depth in this draw; the depth-only replay is not needed
   because the painted fragment's own depth is written.

So the stencil byte is: low seven bits the winding count (nonzero for
|winding| < 128), high bit border coverage. The coverage-ownership
references (1–255, rollover pass) stay in the code for the CPU-mesh path;
an object on the patch path never sets one, so a frame drawn entirely with
patches never rolls over.

**Why the strips stay on the ordinary pipelines.** The first build pulled
the strips through the patch vertex stage too, and that stage runs its
fragment shader per sample for the patch test. The strips are thousands of
small triangles, drawn twice, and shading them per sample cost about 3 ms
on the text control; on the surface pipeline, where nothing needs a
per-sample decision, they cost what they cost today.

**Groups: when objects share a count.** Per-object draws proved cheap on
the GPU but not free to encode: about 1 ms of command encoding for the
101-glyph text, and the pipeline switches between them. Objects share a
stencil count, and so one instanced mark and one cover, when the sum of
their counts is nonzero exactly on their union: every object's count must
keep one sign everywhere (a glyph's hole is inside its outer contour; a
lone clockwise contour beside a counterclockwise one is not), all objects
in the group must share that sign in one plane, and they must be opaque,
uniformly coloured, unshaded painter objects of one colour, so first-wins
painting is painter order. `winding_sign` decides the sign per object per
source revision from the sampled contour polygons in a canonical frame
(the object's own normal follows its winding); the run assembly gives
consecutive objects with the same (sign, colour, normal) one group id,
which travels in the layout. A text paragraph is one group; anything the
rule cannot vouch for draws alone, which is only slower.

Why not the bounding rectangle the plan sketched for the cover: it needs a
per-frame margin for the border width and the miter length, it paints
off-plane border samples at the plane's depth, and a margin that falls
short leaks counts into the next object. Redrawing the mark geometry has
none of those and costs one more pass over triangles that are mostly
stencil-rejected before shading.

## Data

- **Curve records.** The 44-word record of `gpu_border_geometry.py` keeps
  its layout unchanged; the object is the draw's instance, so no word is
  spent on it. Word 37 stays the border-active flag. The fill packs
  **every** curve of a filled path, not only border-active ones: a
  zero-width or invisible curve still bounds the fill. For text nothing
  changes in size, since every glyph curve is border-active; objects with
  no border at all gain records they do not have today, 176 bytes per
  curve, which is less than the mesh vertices and indices they upload now.
- **Object table.** Eight words per object in a run: base point (3), curve
  offset, curve count, bordered, winding sign, one reserved. The base point
  is the centroid of the anchors; any fixed point per object gives the same
  count, the centroid keeps the fan's slivers small (one base for a whole
  paragraph made every fan triangle span it, and doubled the frame). The
  normal and colour come from the curve records. Uploaded once per source
  revision as a hashed blob beside `border_data`, cached the same way.
  *2026-09-11, B3b:* the fan's base is now each curve's own record base
  point (its path's first point), not the table's centroid: "any fixed
  point" holds for closed subpaths only, and an open subpath must close
  through its start, the chord, as Phase A's fill closes it
  (DECISIONS.md, "The fan closes an open subpath through its own start").
  The table keeps its base words; nothing reads them.
- **Plane.** `planar_coordinates` still runs per source revision, for the
  normal and to refuse nonplanar closed contours exactly as today.
- **Wire.** Format 7: a batch with pipeline `patch` or `patch_depth`,
  `fill_num_verts` 0, the `border` descriptor as today with the run layout
  carrying each object's (curve count, bordered, group), an `objects`
  reference and an `object_data` span. Formats 5 and 6 parse unchanged;
  the new pipeline name is only emitted under the switch.

## What the CPU does per frame

Under `MANIML_FILL=patches`, `prepare_triangle_frame` takes a new branch
for every `VMobject` with a fill: the revision-trusted curve source from
`BorderRecipeCache` (constant time on an unchanged object), the cached
object record, and a `TriangleDraw` of kind `patch` with no vertices and
no indices. No mesh, no Lyon call, no `bound_errors` projection per camera
state. `coalesce_draws` joins consecutive patch draws with equal uniforms
into one run, as it joins border runs, and the run layout tells the driver
where each object's draws begin. On a camera change nothing regenerates:
the border compute re-runs for a changed zoom as it does today, and the
fill needs nothing at all.

## The prototype week

1. **Days 1–2, native mirror.** `patch_mark.wgsl` and the cover vertex
   stage (surface and paint fragments reused), the three pipelines with
   their stencil states in `wgpu_renderer.py`, the per-object draw loop from
   the run layout, and format 7 parsing. Frames hand-assembled from
   `renderer_fixtures.py` render through `WgpuRenderer.render`.
2. **Days 2–3, preparation and switch.** The `prepare_triangle_frame`
   branch, the object table in `gpu_border_geometry.py`, the serializer,
   `MANIML_FILL` read beside `MANIML_BORDER_GENERATOR` in `geometry.py`.
   A pixel comparison over the whole fixture corpus and the quality
   fixtures (tex, perspective, hairlines, border, at normal and zoom) of
   patches against CPU-border Phase A and Original 2D at the existing gate:
   at most 0.5% of pixels over 24 of 255, and the zero-border AA control
   measured on its own.
3. **Day 4, cost.** A `patch_fill` variant in `benchmarks/gpu_borders.py`;
   the four text controls against Original 2D on the two-variant harness;
   draws, pipeline switches and overdrawn samples counted per frame.
4. **Day 5, the verdict.** A dated section in
   `unified_triangle_renderer_review_response.md` with the pixel tables, the
   pass and draw counts, and the completion times; the summary archived
   under `benchmarks/results/patch_fill_<date>/` with source hashes.

After the verdict, if it holds: the browser mirror in `webgpu.js`,
`test_wgpu_port` parity between mirrors, the full suite under
`MANIML_TEST_GPU=1 MANIML_VERIFY_LEDGER=1`, the motion tests, a course
episode under the switch, then the default flip. One to two weeks.

## What to watch

- **Draw count.** Two or three draws and as many pipeline switches per
  object, where today a paragraph of text is one draw per run. The
  101-glyph control is about three hundred draws. If that is what the
  harness shows, the remedy is to merge runs of opaque, uniformly coloured
  objects whose outer contours share an orientation: the sum of their
  counts is nonzero exactly on their union, so one mark and one cover
  serve the run. Decided per source revision from the signed area. Not
  built until measured.
- **Overdraw.** Fan triangles cover a hull that can be several times the
  interior, twice. Glyphs are small; the text controls decide.
- **Depth of borders in 3D.** The cover writes the first painted fragment's
  depth, which matches today's first-wins ownership but not the depth-only
  replay's nearest depth where a camera-facing strip is nearer than the
  plane. `mixed_depth` and the perspective fixtures will show whether that
  moves a pixel.
- **The count limit.** A path wound 128 times or more over a sample
  renders it as outside. Lyon has no such limit. Documented, not defended.
- **The browser.** Sample interpolation is standard WGSL; confirming it in
  Chrome is the first thing the browser week does.

## Where this departs from `phase_b_plan.md`

- The cover redraws the mark geometry instead of a bounding rectangle
  (reasons above).
- "A fill adds no new upload" holds for text and nearly everywhere else;
  precisely, the record stream becomes all fill curves rather than
  border-active ones, plus 48 bytes per object.
- Draws are per object, not per run, until the draw count is measured.

## Prototype results (2026-09-11, native mirror)

Built and measured the same day, on the M3 over Metal, behind
`MANIML_FILL=patches`. The archive is
`benchmarks/results/patch_fill_20260911/` (harness reports, summary and
source hashes); the tests are `tests/test_patch_fill.py`.

**Pixels.** Every fixture of `renderer_fixtures.py` and every quality
fixture (tex, perspective, hairlines, border; normal and zoom; default and
zero border) renders within the gate against CPU-border Phase A. The worst
case is the zero-border zoomed text at 0.046% of pixels over 24 of 255; the
next are the annulus (0.043%) and the plain circle (0.031%), and the rest
are below 0.02%, most at zero. Where pixels differ they lie on curved
edges, where Lyon's quarter-pixel flattening sits slightly inside the true
curve; the patch edge is exact. Against Original 2D the patch fill differs
by exactly what Phase A differs by (worst 0.62% on one frame of the 1→4→1
zoom, a pre-existing Phase A gap at 4×; 0.21% to 0.29% on the other three
text controls), since the two fills agree. The zero-border AA control is
therefore measured at 0.02% (normal) and 0.05% (zoom) of pixels; nothing
was widened.

**Complete frames**, warmed medians / minima in ms, two renderers in
rotation per run (`--variants patch_fill original_2d`, then
`--variants gpu_border original_2d` for today's Phase A on the same tree;
Original 2D's column is from the patch run, and agrees with the other run
within 0.15 ms):

| Control | Patch fill | Phase A today | Original 2D |
| --- | ---: | ---: | ---: |
| Static 101-glyph text | 5.71 / 5.43 | 4.14 / 3.94 | 5.84 / 5.43 |
| Text pan | 5.87 / 5.46 | 4.68 / 4.40 | 5.78 / 5.47 |
| Repeated 5% zoom | 5.86 / 5.61 | 6.26 / 3.94 | 5.81 / 5.35 |
| Text 1→4→1 zoom | 5.92 / 5.44 | 6.40 / 3.94 | 5.81 / 5.45 |
| Concave quad morph + changing circle | 3.82 / 3.16 | 4.19 / 3.01 | 3.34 / 2.81 |

Against the plan's gate, Original 2D: at or below it on the still frame,
within 2% on the pan and both zooms. Against today's Phase A the picture
is plainer and less flattering: Phase A's minimum is 3.94 ms on every text
control, the patch fill's 5.4 to 5.6, so on a frame where nothing
re-tessellates Phase A is about 1.5 ms faster. Phase A's zoom medians are
above the patch fill's because some frames of a zoom step do re-tessellate
and because of the harness's alternation effect recorded on 2026-09-10 (an
earlier Phase A run that day, archived beside this one, showed that effect
on the still frame too: 6.75 ms median, 4.24 minimum). On the morph the
two are level.

Where the time goes on the text (patch fill vs Phase A vs Original 2D):
preparation 1.25 / 1.34 / 2.25 ms, and the patch fill's no longer varies
between still, pan and zoom, since nothing is re-meshed (Phase A's rises
to 1.8 on pan and zoom); wire encoding 0.15 / 0.12 / 0.67; command
encoding 0.34 / 0.29 / 0.41 for four draws; submission through full
readback 3.5 / 1.9 / 1.9. The GPU side is what the patch fill pays and the
CPU side is what it saves, and on text the CPU saving is small because
Phase A's retained meshes already cost little there. Memory for the text:
3.2 MB of border output (as today), 880 KB of strip indices (as today),
3.2 KB of object table, and no fill vertices or indices at all (Phase A
retains 175 KB of fill vertices and 895 KB of indices for the same
paragraph).

**What the prototype week changed in the design, and why** (measured in
`benchmarks/probes/` style isolation, single renderer, same frame):

1. The strips were first pulled through the patch vertex stage, at sample
   rate. That cost about 3 ms per text frame: thousands of small triangles
   drawn twice and shaded per sample. Moving them to the ordinary surface
   pipelines (the format 6 index pattern, as today) removed it. Fans and
   patches keep sample-rate shading; their area on text equals the painted
   area (fan area 1.01× the painted samples), so they cost little.
2. Per-object draws cost about 1 ms of command encoding and their pipeline
   switches for 101 glyphs. Objects that can share a count (opaque, one
   colour, one plane, one winding sign) now draw as one instanced group:
   the paragraph is four draws. The sign rule is `winding_sign`; the
   probe that motivated it drew the merged paragraph pixel-identical to
   per-object draws.
3. One shared base point for a whole run was measured too, and doubled
   the frame: fan triangles spanned the paragraph. The base stays per
   object.

**Open after the week.**

- The GPU side: 3.5 ms submission-through-readback against 1.9 for both
  Phase A and Original 2D on text. The patch fill draws the fan and patch
  triangles twice (mark and cover, the second mostly stencil-rejected),
  the strips twice by design, and the fans at sample rate. The candidates
  are known and unmeasured: drawing the strip pattern at the steps a run
  needs rather than its reservation (halves the strip vertices at the
  usual 2× headroom, in Phase A's path too), and a cover for opaque groups
  that skips the patch test where the mark already decided it.
- The browser mirror draws `patch` batches since 2026-09-11 (`webgpu.js`:
  the same explicit layouts, stencil states, instanced groups and strip
  pipelines; `patchWire` in `tests/generated_webgpu_commands.cjs` checks the
  command sequence on a real frame, and the live viewer's canvas matched the
  native render exactly on a 32×18 grid of cell means over a frame of text,
  translucent fills, a sphere and a square). The recording player indexes
  `patch` batches since 2026-09-26 (`geometry_recording.js` carries the
  object table and curve records into every reconstructed frame), so an
  `--export` made with the switch on plays; the default flip waits on Taylor.
- The count wraps at 128-fold winding; recorded, not defended.

The verdict on B1-fan against these numbers is Taylor's.

## Second measurement (2026-09-11, after two of the candidates)

Taylor's direction, quoted: "ok try the first two and measure again." The
two: the cover no longer evaluates the curve test and runs at pixel rate,
since the stencil count already holds the answer per sample and a patch
fragment outside its curve lands on a zero count; and the mark draws its
fan triangles at pixel rate, with only the patch triangles (a tenth of the
fan's area on text) shaded per sample. Five draws per group now. Pixels are
unchanged on the whole corpus.

| Control | Patch fill | Phase A today | Original 2D |
| --- | ---: | ---: | ---: |
| Static 101-glyph text | 5.11 / 4.83 | 5.28 / 3.99 | 5.41 / 5.14 |
| Text pan | 5.24 / 4.76 | 5.59 / 4.87 | 5.33 / 5.04 |
| Repeated 5% zoom | 5.42 / 4.91 | 5.73 / 5.42 | 5.30 / 5.12 |
| Text 1→4→1 zoom | 5.32 / 4.81 | 6.06 / 4.88 | 5.42 / 5.05 |
| Concave quad morph + changing circle | 4.58 / 2.71 | 5.19 / 2.90 | 2.84 / 2.62 |

About 0.6 ms per text frame gained: submission through readback 2.9 ms
against 3.5 before, with Phase A at 1.7 on the still frame and 2.7 to 2.9
on the zooms in this run. Below Original 2D on every text median now. Against
Phase A: level on pan and both zooms at the minimum, ahead on the medians,
and 0.85 ms behind on the still frame's minimum (4.83 against 3.99), which is
the remaining structural cost of the second pass over the strips. The third
candidate, strips at the steps a run needs rather than its reservation, is
still unmeasured and applies to both renderers. Archive:
`benchmarks/results/patch_fill_20260911/` (`summary.json` is this build,
`summary_first_build.json` the first).

## Third candidate: measured, no gain (2026-09-11)

Taylor's direction, quoted: "ok try the third one and measure again." The
strip pattern sized to the steps the run needs (5 quads per curve instead
of 11 at the normal view, 10 instead of 21 zoomed) was measured before
being built, against today's pattern and against no strips at all, in
`benchmarks/probes/patch_pass_probe.py`.

The first attempt, each variant alone for forty frames, put the no-strip
frame 1.5 ms *slower* than the full one. That is the M3's GPU clock
following the load, not the strips: a lighter frame alone is not a faster
frame here, and the harness's "alternation effect" of 2026-09-10 is the same
thing seen from the other side. Every figure below is therefore from
variants interleaved frame by frame with rotating order, medians / minima in
ms of wall-clock around the render call.

| Text frame, 1× / 2× zoom | Median | Minimum |
| --- | ---: | ---: |
| Pattern at the reservation (today) | 3.92 / 4.07 | 2.15 / 3.68 |
| Pattern at the needed steps | 3.98 / 4.05 | 2.16 / 3.65 |
| No strips at all | 3.85 / 3.97 | 2.11 / 3.60 |

Nothing to gain: the degenerate tail costs nothing measurable, and even
the whole strip pass is within 0.1 ms. Not built. Skipping each patch draw
in turn was likewise invisible against the frame's floor when only patch
variants were interleaved.

Interleaving Phase A with the patch path in one session gives the residual
its size and its rough attribution (minima, 1× / 2×): Phase A 2.45 / 3.57,
the patch path 3.50 / 3.64, the patch path with only its strip draws
2.81 / 3.81. So at the normal view the patch path costs about 1 ms more at
the minimum, of which the second strip pass is about a third and the fan
and patch passes the rest; zoomed, the two are level. A CPU profile of the
cached frame agrees: command encoding differs by 0.1 ms, and the rest of
the difference is time waiting for the GPU inside the readback.

What this says about going further: the remaining gap on a still text
frame is the two passes a count-then-cover design makes over geometry that
Phase A's mesh draws once, and the wall clock on this machine cannot
resolve changes smaller than a few tenths of a millisecond against its
moving floor. The next instrument is GPU timestamp queries in the harness,
which measure pass time rather than completion latency; until then, the
patch fill is level with Phase A on pan and zoom and about 1 ms behind on
a still text frame, and Phase A stays the default.

## GPU timestamps, and the gate on two course episodes (2026-09-26)

Taylor's direction, quoted: "start with the timestamp queries", and, asked
what the flip must beat, "complete frame, per the plan" — CPU preparation,
encoding and GPU together, at or below Phase A on the five controls *and*
a course episode, pixels within the 0.5% gate; the timestamps are the
diagnostic, not the gate. Two episodes were named: `B2_Supply/03_Code.py`
(`EpisodeB2`, text-heavy 2D) and `B3_Equilibrium/Animate.py`
(`PriceDiscovery`, 3D). Scope for the day: measure and report; no design
change without a fresh decision.

**The instrument.** `MANIML_GPU_TIMESTAMPS=1` stamps every GPU pass of the
native mirror (`_PassTimestamps` in `wgpu_renderer.py`; `gpu_timings` after
each frame). Two Metal facts shape it and are recorded in `CLAUDE.md`: the
last pass's end stamp cannot be resolved in the frame's own command buffer,
so the resolve is a separate submission after the readback, outside every
timed interval; and a render pass's begin stamp is its vertex-stage start,
overlapping the previous pass's fragments, so only the frame total and the
per-label *exclusive* times are costs. The flag perturbs what it measures
(~30 µs per stamped pass), so gate numbers come from flag-off two-variant
runs and attribution from a separate flag-on run. The harness for episodes
is `benchmarks/episode_frames.py` (pausepoint frames, `--tick-updaters`,
`--play-frames`); the archive is `benchmarks/results/gpu_timestamps_20260926/`.

### The controls: the "~1 ms" was never GPU time

The five controls of `patch_fill_20260911`, quiet GPU (0–12% device
utilization, WindowServer's baseline), twelve samples after three warmups,
two variants rotating frame by frame, flag off (complete frame, ms,
median / minimum; then the GPU total from the flag-on attribution run):

| Control | Patch fill | Phase A | GPU total, patch / Phase A |
| --- | ---: | ---: | ---: |
| Static 101-glyph text | 5.66 / 4.23 | 4.15 / 3.87 | 1.33 / 1.02 |
| Text pan | 5.77 / 5.33 | 4.63 / 3.90 | 1.32 / 1.02 |
| Repeated 5% zoom | 5.80 / 5.03 | 6.22 / 3.87 | 1.46 / 1.14 |
| Text 1→4→1 zoom | 5.85 / 5.36 | 6.36 / 4.09 | 1.91 / 1.39 |
| Concave quad morph + circle | 3.72 / 3.32 | 4.06 / 3.06 | 1.07 / 0.93 |

On the still text frame the patch fill's GPU time is +0.30 ms, at the
median and at the minimum alike, all of it in the output pass (+0.30
exclusive; the border and resolve passes are equal), of which the five
patch draws are ~0.16 ms and the strips and stencil state the rest; the
probe puts the same difference at +0.29 interleaved, +0.44 zoomed. The CPU
columns net to +0.04 ms. The +1.51 ms median gap in the complete frame is
one quantum of the readback wait, which on this machine sits in ~1.9 and
~3.45 ms modes: the patch fill's extra 0.30 ms of GPU work tips the wait
into the slower mode on 11 of 12 frames against Phase A's 2, and the
minima (+0.36) say the same. So the "~1 ms" the third candidate could not
resolve was the readback quantum seen from the render call, not GPU
execution; the GPU figure is 0.3 ms. The zoom medians favour the patch
fill because Phase A re-tessellates on some zoom frames, as before.
Pixels are identical to 2026-09-11 (0.00% against Phase A; 0.21–0.62%
against Original 2D, the 1→4→1 zoom's 0.62% being Phase A's own gap).

A first pass of the same runs, taken while a leftover viewer held the GPU
at 35–42%, is superseded and kept in the archive for the record: the patch
fill's numbers did not move between the two (5.66 / 4.34 loaded), Phase
A's did (4.79 / 3.98 loaded), which is the GPU clock following the load.

Against the plan's gate as Taylor stated it — complete frame at or below
Phase A — the still frame and the pan fail by the readback quantum, the two
zooms and the morph pass at the median and fail at the minimum. In the
browser there is no readback: the difference a viewer would feel on these
controls is the 0.30 ms of GPU work, unmeasured there.

### The episodes: the gate is not met, and the reason is not the GPU

Twelve pausepoint frames per episode at the episodes' own 2160×1080, twelve
samples after three warmups, two variants rotating frame by frame, flag off
(complete frame, ms, median; Δ = patch fill − Phase A):

| Episode | Frames at/below Phase A | Median of frame medians | Largest deficit |
| --- | ---: | ---: | ---: |
| B2 `EpisodeB2` | 4 of 12 | 21.77 vs 19.83 | **+27.77** (8.a, line 1016: 64.65 vs 36.88) |
| B3 `PriceDiscovery` | 2 of 12 (three more within +0.1) | 18.18 vs 16.95 | +2.46 (3.a.3, line 1179: 19.25 vs 16.79) |

Against Original 2D the patch fill is below on 24 of 24 frames (Original
2D's readback at this resolution is 10–69 ms). Pixels: 0.000% over 24/255
against Phase A on every frame (max single-channel difference 27); worst
0.114% (B2 3.i) and 0.269% (B3 2.b.i) against Original 2D — under the gate
everywhere. The live rows (updaters ticking; the play into each pausepoint)
are worse for the patch fill where the frame is heavy: B2 8.a +52.5 ms
ticking, +106.8 ms mid-play; B3 at most +5.1 (3.a.4 ticking) and +7.1
(3.a.9 play).

Where the deficit is, on B2 8.a (patch fill / Phase A): serialize 27.31 /
19.96, prepare 17.40 / 15.49, **command encoding 24.32 / 7.09**, submit
through readback 9.39 / 7.78. The wire carried 911 batches and 1840 draws
against Phase A's 444 and 444. The attribution run (flag on, six frames)
puts the GPU's share at +0.9 to +2.1 ms per frame on B2 and −0.6 to +1.3
on B3, all of it in the output pass; every frame of both variants encoded
exactly two passes (out, resolve). So on a real diagram the patch fill
loses on the CPU, in proportion to its draw count, and the GPU difference
is a small fraction of the gap.

Why the draw count: a patch run joins only *consecutive* draws with equal
uniforms, texture and pipeline (`triangle_scene.py`, the run builder), a
painted patch stays a run of its own, and a translucent fill's coverage
reference belongs to one object; each group in a run is five draws (mark
fan, mark patch, strip mark, cover, strip cover). A course diagram
interleaves colours, opacities and dashed strokes, so its runs are short:
on the light bar-chart beats (4.b–4.d, 79–132 mobjects) the patch fill has
8–12 batches to Phase A's 45–62 and wins by 1–3 ms; on 8.a (531 mobjects)
it has twice the batches and four times the draws and loses by 28. The
controls did not show this because the 101-glyph paragraph is one run of
one group.

Left open, not decided: the lever the numbers point at is the run rule —
per-object colour and opacity are already in the object record's reach
(eight words per object), so a run could span uniform changes and a frame's
opaque patch objects become one group of five draws; whether translucent
and painted objects can join, and what the browser (which pays per draw in
JavaScript, unmeasured here) does with it, are the questions. The verdict,
and whether to spend the week, are Taylor's.

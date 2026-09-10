# Shared fill atlas and ordered rendering

**Superseded proposal — 2026-09-09.** The selected direction is now
[one triangle renderer for 2D and 3D, followed by GPU geometry generation](/Users/taylorjweidman/Projects/ManimLive/maniml-perf/docs_unified_triangle_renderer_plan.md).
This document preserves the earlier proposal and its experimental evidence;
its atlas-specific requirements are no longer the implementation plan.

Original implementation proposal, 2026-09-09. Based on `2b5aeeba`;
implementation had not started when the direction changed.

Prepare fills in separate regions of a shared temporary GPU image (an
**atlas**), then draw the scene in its existing order through a shared output
pass. This reduces repeated setup while preserving overlapping fills and
outlines. Reuse GPU resources so command preparation becomes cheaper too.

The atlas is a sheet of independent working regions. Packing two fills next
to each other in that sheet does not combine their colors or change where
they appear in the scene.

## Outcome and scope

The original B0 wordmark should retain its 211 squares, 135 logical batches,
and appearance while using a few rendering passes. A logical batch remains
the existing unit of winding-fill calculation; a render pass is a period of
drawing into one target. Several ordered draw commands can share a pass.

Keep the current geometry payload and drawing sequence. Within an ordinary
batch, output remains fill then stroke; `stroke_behind` retains its reverse
sequence. Plain objects and depth-tested objects stay in their existing
positions in that sequence. Existing safe merges remain useful.

Work is concentrated in the browser WebGPU driver, its native WebGPU mirror,
and the composite shader. The current serializer's `fill_rect`, vertex
buffers, camera data, and winding calculations supply the inputs.

This plan does not add the experimental 13-batch spatial reorder, change
scene object order, or redefine `z_index`. The existing limitation on
`z_index` across top-level groups remains a separate issue. Python geometry
caching and the future GPU instruction stream are separate work; measure
their remaining costs when judging viewer performance.

## Fit with the GPU instruction stream

This improves the drawing stage that the longer-term GPU engine will still
need. The instruction-stream plan moves point updates, animation evaluation,
and supported simulation work from Python onto the GPU. It still produces
geometry buffers and an ordered draw list, as described in
`../simlab/ARCHITECTURE.md`. Those outputs can feed this atlas renderer.

Keep payload decoding and CPU geometry inspection outside the atlas/pass
encoder. Its inputs should be GPU resource references, the ordered drawing
operations, conservative fill rectangles, and draw-state values. Atlas
packing, isolated fill preparation, ordered output, sampling rules, and the
bounded scratch pool can then carry forward as the geometry producer changes.
Atlas pixels and placements remain disposable renderer state. Checkpoints
and instruction-stream revisions reference geometry, styles, and draw order;
they must not retain atlas pages or depend on particular tile placements.

The main future adaptation is bounds: today's rectangles are calculated
from CPU point arrays. GPU-generated geometry will need conservative bounds
from GPU reductions, known transforms, or another conservative strategy that
does not force a synchronous GPU-to-CPU readback each frame. GPU-produced
uniform/scalar data may also replace parts of today's CPU uniform packing.
The integration work belongs to the instruction-stream migration; this plan
must not embed a requirement to download points in the drawing stage.

The two changes address distinct costs and can coexist. Faster point updates
alone would leave today's repeated render passes, and fewer render passes
alone leave Python's animation/serialization work. The atlas is useful now
and remains useful within the planned architecture. It adds no prerequisite
to, and does not lift the existing hold on, native GL removal.

## Evidence and target

Five warmed, alternating native WebGPU samples on Apple M3 at 2160 × 1080:

| Experiment | Logical batches | Render passes | Command preparation | Submission through completion |
| --- | ---: | ---: | ---: | ---: |
| Current bounded renderer | 135 | 406 | 29.61 ms | 27.47 ms |
| Separate prepared fills, then ordered output | 135 | 136 | 22.16 ms | 10.60 ms |

The second experiment reproduced the original opaque wordmark with zero
changed pixels. It is evidence for separating preparation from output;
**it did not implement an atlas** and therefore still prepared each fill in
its own pass. Atlas performance and general fidelity are still unmeasured.

Completion timing includes a synchronous one-pixel readback. Both columns
exclude Python animation, serialization, transport, and browser presentation.
A live B0 process remained open at approximately 6% CPU. Use the paired
comparison, not these absolute values as a browser frame-rate claim.

Current allocation calculations for the same camera and wordmark:

| Arrangement | Temporary fill-image allocation |
| --- | ---: |
| Current touching squares, reusable small scratch pool | 0.97 MiB |
| Separated squares, one bounded batch | 16.00 MiB |
| Prototype retaining separate fills | 21.75 MiB |

The touching wordmark's tightly sized fill rectangles total 8.55 MiB at the
existing 2× sampling resolution, before gutters and packing waste. Aim to
fit B0 in at most 16 MiB of atlas allocation; confirm this with the packer.
The earlier full-frame renderer used a 71.19 MiB fill texture at this output
resolution, so its memory figures are not the bounded pool's figures.

Engineering targets, to be checked against a fresh same-run baseline:

- B0 fits in one or two atlas pages and one ordered output pass: two or
  three native render passes, plus the browser's final canvas blit.
- At least 2× lower B0 command-preparation time and 2× lower submission-
  through-completion time than the current bounded renderer.
- No material regression on separated one-batch shapes, a large single
  fill, stroke-only content, or a DotCloud. Investigate a repeatable slowdown
  exceeding both 10% and 0.2 ms in a renderer timing column.
- GPU allocations stabilize after warmup when scene size is stable; changing
  sizes and long animations remain within the documented resource limits.

The historical roughly 1.5 ms single-batch result is an aspiration, not an
acceptance promise. This design retains multiple ordered draw commands even
when it uses very few render passes. The full viewer has additional costs.

## Implementation sequence

### 1. Establish a reproducible baseline

Extend `benchmarks/vector_fill.py` to retain the original wordmark and add
separated squares, stroke-only content, and a mixed scene control. Measure
planning, command encoding, and submission-through-completion separately.
Report batch/pass/draw counts, GPU buffer and bind-group creation counts,
atlas bytes, dedicated scratch bytes, and peak retained/retiring resources.

Save baseline pixels and measurements before changing the driver. Use a
temporary test reference to the current bounded implementation for direct
new-versus-current comparisons; keep native GL as the existing independent
fidelity oracle. Do not introduce a permanent public renderer selector.

Exit: identical inputs and separate timing stages are available for all
later comparisons. The plan's evidence is copied above so it does not depend
on the earlier scratch scripts surviving in `/private/tmp`.

### 2. Separate frame preparation from ordered drawing

Refactor each renderer into preparation and encoding stages. Preparation
resolves vertex/image resources, the current fill rectangle, pipeline state,
and required uniforms for each existing batch. It produces a small ordered
list of output operations referring to those resources.

Retain operation order exactly, including fill/stroke interleaving,
`stroke_behind`, images, DotClouds, surfaces, and triangulated fills. Finish
asynchronous image decoding before encoding the passes that use it. Preserve
cache-miss/reset behavior and the handling of unsupported content.

Use an explicit preparation structure in production rather than the
prototype's proxy objects that record arbitrary method calls. This stage is
the seam for atlas placement and shared uniform storage.

Exit: the refactored path matches current output before atlas changes.

### 3. Pack and prepare fills in atlas pages

Use a deterministic shelf packer with integer coordinates. Pack one tile per
nonempty winding-fill batch. For a `fill_rect` of width `w`, height `h`, its
content region is `2w × 2h` texels, with two transparent scratch texels of
gutter on every side. Empty fills allocate nothing; their strokes still draw.

Page size grows to suit the requested tiles, subject to device texture limits
and the memory policy below. A single batch uses a page sized close to its
tile, preserving the bounded renderer's small-scene behavior. Layout may be
recomputed when rectangles change; any layout reuse must compare all relevant
rectangles and limits. Camera-only frames can change these despite cached
vertex bytes.

Clear each page once. In one preparation pass per page, draw each tile's
winding fill followed by its fill-border operation using the existing shaders
and blend modes. Preserve each existing batch's complete fill draw followed
by its complete border draw. Never combine separate logical batches into one
tile: their independent winding calculations must stay independent.

Use the existing `clip_transform` with the tile's integer viewport and
scissor, starting at the content origin after its gutters. Preserve the 2×
sampling grid, lighting, stroke widths, clip planes,
and original scene projection. The scissor confines writes to the tile's
content region; cleared gutters isolate filtering from neighboring tiles.
Finish all preparation passes before sampling those pages.

Exit: atlas tiles match the current separate scratch results, including
their edges. Packing can change storage placement but not scene pixels.

### 4. Composite and draw through the ordered output pass

Extend the composite shader's existing UV scale to a scale-and-offset vector
so each composite samples its own atlas region. Its scale is
`(2w / pageWidth, 2h / pageHeight)` and its offset is the tile's content origin
divided by the page dimensions; preserve the existing Y flip. This is
renderer-internal data and requires no geometry protocol version change.
Keep shader definitions and both driver layouts synchronized.

Open one scene output pass and execute the prepared operations in their
existing order. A fill composite uses its original screen rectangle and its
atlas sampling coordinates; the following outline uses the normal scene
projection. Reset viewport and scissor before every operation that requires
the full output viewport, including plain and triangulated draws.

Clear scene color/depth once at frame start. Preserve depth-write and
depth-compare settings per pipeline. With memory chunks, retain color and
depth between output passes; preserve MSAA and perform the final resolve
before presentation/readback. The browser retains its canvas blit.

Exit: the full wordmark and mixed scenes match the current renderer, and
pass counts scale with atlas pages/chunks rather than logical batch count.

### 5. Reuse uniforms and bindings

Replace per-draw GPU uniform-buffer allocation with a reusable uniform buffer
containing aligned slots. Keep the current 192-byte ordinary uniform payload;
composite coordinates occupy their own slot. Query the device's uniform
offset alignment instead of assuming a fixed value.

Use explicit compatible binding layouts and dynamic offsets. Bind a
slot-sized range (192 bytes ordinary, 16 bytes composite), not the whole
arena, so bindings remain within the device's uniform binding-size limit.
Reuse bind groups per required layout/page rather than creating four new
groups for every batch on every frame. Pack values on the CPU and upload in
a small number of writes before submission.

Every draw needing distinct values must have its own slot within that
submission. Rewriting a single slot while encoding several chunks would make
earlier draws read the final values. Reuse across submitted frames must
respect queue ordering; no unconditional GPU wait is added to the frame loop.
Start with an 8 MiB arena capacity ceiling, reduced if device limits require
it, allocated on demand. If a frame needs more slots, submit completed
contiguous chunks before queue-writing the reused slots for the next
submission. Keep scene color/depth and atlas dependencies intact across
submissions. Do not overwrite slots still referenced by unsubmitted commands.

Exit: warmed stable frames reuse their GPU uniform buffers and bind groups.
Measure the remaining CPU preparation cost; an atlas alone does not prove
that command encoding has become cheap.

### 6. Validate and enable in both renderers

Develop the native path first for fast pixel comparisons, then complete the
matching browser path and exercise the actual viewer. Keep changes in the
performance worktree until both mirrors pass the checks below. Inspect the
browser with the real B0 animation, including color changes and movement.

Record the final paired results, update `CLAUDE.md`, `DECISIONS.md`, and
`benchmarks/README.md`, and remove temporary diagnostic alternatives. The
memory fallback is a supported part of the design and remains available.

## Memory and resource policy

Start with a **64 MiB retained atlas-pool budget**, allocated on demand. This
is a ceiling, not an up-front allocation. The B0 target remains at most
16 MiB. Count actual page allocations, including gutters and unused space.

When a frame cannot fit, divide the original draw list into contiguous
chunks: prepare a chunk's fills, draw that chunk in order, then reuse the
pages for the next chunk. Page reuse is ordered after the operations that
sample the previous contents. Packing may rearrange preparation tiles; it
must never rearrange output operations or split a logical winding fill.

A single tile too large for the normal atlas budget, or whose added gutters
would exceed the device's texture dimensions, uses the existing dedicated
scratch path, processed alone. Missing/invalid bounds retain the existing
full-frame behavior. Allow at most one such dedicated working
target, bounded by the supported full-frame scratch dimensions; do not
silently lower resolution. Report this separately: the normal atlas budget
plus one dedicated target is the explicit scratch ceiling, excluding the
output/depth targets and existing vertex/image caches. Honor device texture
limits; this work does not expand the renderer's supported resolution range.

Reuse or release unused resources on resize and budget pressure. Account
for replaced resources awaiting GPU completion when enforcing the bound;
repeated resizing must not build an unbounded retirement queue. Prefer queue-
ordered reuse. Wait for completion only if growth/retirement would otherwise
exceed the bound, not on every normal frame. Uniform-buffer capacity and
retiring buffers also need bounded growth and explicit accounting.

## Verification

Use existing fidelity tolerances unchanged. Require exact equality for B0 and
the fixtures that currently require it; keep the narrowly documented glyph
rounding tolerance. Do not broaden thresholds to make the atlas pass.

| Concern | Required coverage |
| --- | --- |
| Drawing order | Overlapping colored/translucent shapes, fill over earlier outline, `stroke_behind`, and mixed winding/image/DotCloud/triangulated output |
| Fill math and edges | Holes, curves, gradient colors/alpha, large fill borders, sharp joins, clip planes, and tiles adjacent in the atlas but distant in the scene |
| Sampling | 2× grid alignment, page edges and gutters, offscreen geometry, fixed overlays, zoom/tilt/pan, and MSAA |
| Changing frames | Fade/color/movement, shrinking rectangles, atlas repacking, cached geometry with fresh camera bounds, navigation, and geometry reset |
| Capacity | Forced tiny budgets, multiple chunks/pages, oversized and missing-bounds fallback, empty fills, repeated resize, and many frames queued before completion |
| Lifetime | Clear-before-reuse, no sampling a page during its preparation pass, no premature resource destruction, stable allocation counts, and bounded retiring resources |

Extend `tests/test_webgpu_commands.py` and `tests/webgpu_commands.cjs` to
record operation order, sampling coordinates, dynamic offsets, allocation
bytes, and lifetimes. Mock-command tests cannot establish pixel correctness;
use actual GPU image comparisons as well.

Extend `tests/test_fill_bounds.py` and `tests/test_wgpu_port.py`, or introduce
a focused `tests/test_fill_atlas.py` when it makes the allocator and pixel
cases clearer. Register new modules in the appropriate CI jobs. Exercise
`tests/test_static_assets.py`, the streaming cases in `tests/test_web_viewer.py`,
and export/player compatibility in `tests/test_export.py` and
`tests/test_viewer_exports.py`.

Verify the installed checkout and GPU-capable interpreter before running
measurements. Warm pipelines/resources, alternate baseline and atlas runs,
and collect enough samples to report median and p95. Run GPU benchmarks
serially and record other active rendering work; avoid concurrent renders or
test suites during viewer measurements.

Use `MANIML_PERF_PATH` and `benchmarks/live_profile.py` for engine stages and
socket arrival. Measure browser command preparation and display cadence
separately in the actual viewer. A queue submission timestamp is not GPU
completion, and the live-profile harness alone does not measure browser
presentation. If GPU timestamp queries are unavailable or invalid, state the
timing boundary rather than relabeling wall time as pure GPU time.

Browser acceptance includes improved B0 motion/cadence without growing frame
backlog, stable resource use, and working camera/navigation/cache behavior.
Compare against the same scene frame rate and display setup. Investigate any
remaining lag by stage; the measured roughly 6.2 ms B0 Python serialization
cost remains outside this renderer change.

## File map and completion

| Area | Files |
| --- | --- |
| Native planning, packing, passes, resource reuse | `maniml/web/wgpu_renderer.py`; extract a small internal atlas helper if needed |
| Browser implementation and resource lifecycle | `maniml/web/static/webgpu.js` |
| Atlas sampling coordinates | `maniml/web/static/wgsl/composite.wgsl` |
| Input rectangles and camera invariants | `maniml/web/fill_bounds.py`, `maniml/web/geometry.py` — expected to need no protocol change |
| Regression and command coverage | `tests/test_fill_bounds.py`, `tests/test_wgpu_port.py`, `tests/test_webgpu_commands.py`, `tests/webgpu_commands.cjs`, optional new atlas module |
| Benchmarks and record | `benchmarks/vector_fill.py`, `benchmarks/README.md`, `CLAUDE.md`, `DECISIONS.md`, `TODO.md` |

Completion means both renderers use the shared atlas and ordered output,
uniform/binding reuse is measured, memory is bounded including the documented
fallback, fidelity passes, and actual viewer results are recorded. If a
performance target is missed, identify the measured remaining cost before
deciding on further work; do not describe fewer passes alone as completion.

The earlier 2–4 focused-day estimate covered a robust version with separate
prepared fill targets. This fuller plan includes atlas packing and resource
reuse; allow several additional focused days for implementation and visual
verification. Edge sampling and queued-resource lifetime are the largest
uncertainties. These are engineering effort estimates, not a delivery promise.

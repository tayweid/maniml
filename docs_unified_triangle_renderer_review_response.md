# Unified renderer review: author decisions and changes

2026-09-09. This is the changelog for the plan reviews, zoom addition, and
the [third-round code review](docs_unified_triangle_renderer_code_review.md).
The [shared renderer plan](docs_unified_triangle_renderer_plan.md)
now carries the operative requirements; [Phase B research](docs_gpu_geometry_generation_plan.md)
has its own specification. The original reviewer block and A0 note remain
verbatim as historical feedback.

Review is a second opinion, not an automatic expansion of scope. The chosen
direction remains one general triangle backend for 2D and 3D, followed by GPU
source updates and required geometry generation. Use the review to improve the
checks and choose the simplest general, correct, fast implementation. Analytic
patches and avoiding Rust are candidates/tradeoffs, not mandated architecture.

## Third-round code review disposition

Checked against the latest code and archived reports, then reproduced the
applicable findings. The review's timing table used the earlier B0 run, before
projection-bound memoization. The [new results](docs_unified_triangle_renderer_a0_results.md#code-review-follow-up)
preserve both the gains and remaining gaps. The reviewer document is unchanged.

| Finding | Decision and evidence |
|---|---|
| 1. Earcut binding / center fans | Confirmed and fixed on the working branch. The native boundary now passes float32 vertices and uint32 ring ends. Fixing it exposed another bug: x/y projection collapses vertical planar fills. `VMobject3D` now chooses a nonsingular coordinate plane while retaining world vertices. Regression tests cover concavities and holes in XY, XZ and YZ, forbid the fan fallback, and check unchanged source points. No merge into `main` occurred. General nonplanar fill semantics and existing lighting limitations are separate. |
| 2. Analytic rejection predicates | Adapted with explicit bounds. Both reported counts were reproducible: direct world-XY input accepted 80/101; the actual SVD scene-preparation path accepted 5/101. This was missing provenance, not a stale count. Bounded near-collinear approximation and exact-zero-only triangle removal now let 100/101 glyphs prepare. Nonzero slivers remain. One true overlap still rejects full TeX frames; six other quality cases now have real GPU image/timing data. This does not select analytic geometry as the general renderer. |
| 3. Completion timing | Accepted the reporting improvement. All revised reports include minimum and fractions below 3 ms / above 10 ms, alongside existing medians and retained samples. One-pixel completion includes GPU work and host readback/waiting. The observed modes do not prove a particular polling quantum; installed wgpu uses a blocking poll thread. Timestamp isolation remains needed before calling a number pure GPU execution time. |
| 4. Cache validation cost | Confirmed the remaining cost and made its scope explicit. The earlier memoization already roughly halved unchanged-camera preparation; moving-camera checks still cost time. Declined revision-only reuse for this prototype: public point/style arrays can change without bumping `Mobject.revision`, and regression tests require those changes to render. A trusted revision fast path needs an enforced mutation contract first. |
| 5. Fill borders | Agreed; this was already the leading appearance gap in the final results. Supersampling's zero-border control cannot establish default-style text parity. Border coverage remains the next major geometry/appearance experiment. |
| 6. Rust evidence | Agreed with the qualified conclusion. Rerunning the actual fixed production wrapper still gives ten wrapper failures and five direct-Earcut failures; Lyon passes all 34 sampled cases. This supports retaining Lyon for general paths, with packaging/material/memory gates still open. |
| 7. Write / paint invalidation | Fixed uniform paint-only invalidation, but corrected the diagnosis of Write. The isolated opacity control now records 608 paint refreshes and zero rebuilds. Real Write still has 95 rebuilds: 38 newly visible fills, 56 point-byte changes and one paint/normal change. Its interpolation changes float32 source points slightly, so those are not solely paint invalidations. Nonuniform diagnostic paint still requires regeneration; a separate general paint representation is unfinished. |
| 8. Zoom headroom | Accepted the stronger stress case. Retained the 1–2× reuse control and added 1–4×–1× zoom. It triggers 101 refinements, then reuses the fine meshes on zoom-out. Existing unit tests crossed the headroom, and the earlier perspective scenario already recorded six refinements; the finding did not apply to every camera test. |
| 9. Baseline retention | Accepted the timing qualification. Current production caching retains old batch geometry; the candidate retires buffers inside the measured window. The baseline therefore avoids that retirement cost. Reports now explain both timing and memory asymmetry; they compare existing lifecycle policies rather than claiming equal memory bounds. |
| 10. Crop thresholds | Fixed. Crops retain numerical errors without a full-frame acceptance label. The final pre-review report already contained populated crops; its broad gate was still inappropriate for their much smaller area. |

Validation after these changes: **128 focused CPU tests and 33 native GPU/fidelity
tests pass**. The square benchmark recheck is 81.32 ms current, 46.93 ms ordered,
and 18.42/21.96 ms flattened at one/four samples. These remain local timings
through readback, with the existing alpha difference reported separately. Text
performance, full border coverage and the other A0 gates remain incomplete.

## Changes adopted into the plan

| Review topic | Author disposition and plan change |
|---|---|
| Curve tradeoff and analytic patches | State flattening's camera-dependent detail cost upfront. Compare bounded analytic patches as a candidate; the selected route must handle required content. The interior and patch domains must avoid double coverage. |
| Ordered-output control | Compare current winding, ordered-output-only winding, flattened meshes, and analytic patches where feasible. Include source evaluation, CPU generation, uploads, and completion. No Phase A speed claim from the small-fixture pilot. |
| Zoom and per-object quality | Use an output-pixel budget converted through each control hull's projection bound. Add continuous zoom, pan/rotation/resize, depth/tilt, small text, and simultaneous Transform/Write. Reuse meshes while their stored quality still suffices. |
| Text and hairline AA | Prioritize comparisons against native GL and current WebGPU, with local crops, subpixel motion, and temporal checks. Compare 4× MSAA, specified analytic AA, and a defined 2×-dimension resolve; document feasibility rather than building a second general renderer for comparison alone. |
| Earcut, Lyon, and Rust | Compare the already-shipped Earcut dependency with the isolated Lyon helper. The primary correctness case for added Rust cost is a reproducible required-path/morph failure in Earcut that Lyon passes. Also weigh measured simplicity, speed, full appearance, memory, and OS/architecture/Python/WASM distribution costs. Evidence does not automatically authorize adoption. |
| Gradients | Treat the historic fan seam as a known defect. The author's recommended smoother-field direction is an intentional-change candidate, not assumed user approval of arbitrary visual differences. Require stable source/boundary paint under camera changes, refinement, and diagonal changes before a production compatibility decision. |
| Fill borders | Strengthen the fixture: translucent fill, wide border, contrasting background, and differently colored overlaps. Inspect border/interior crops and RGBA probes. The pilot's broad RGB threshold missed an omitted border and is insufficient alone. |
| Alpha and goldens | Record the shared GL/WebGPU opacity adjustment and direct-draw alpha-squaring defect. Capture both historical renderers; independent geometry, paint, and RGBA tests define semantics. Keep corrections separate from geometry-fidelity claims. |
| Phase B split | Move detailed GPU algorithms, count/scan/emit, memory/recovery, fresh reads, and playback into the dedicated specification. Preserve source/generated coherency and the approved GPU objective. Phase A must stand on demonstrated current benefits. |
| Status and portability | A0 has started and remains incomplete. Author-owned repository links are relative; sibling roadmap links are marked workspace-only. Work is uncommitted on `plan/ordered-fill-atlas`, not detached. No commit or default-renderer switch occurred. |

## Technical clarifications retained

Analytic patches choose their covered side; they do not subtract alpha from an
already-painted output. An inward-bulging segment needs the excess anchor
interior excluded before rendering, and overlapping control hulls may require
subdivision. This is the relevant correction to the second round's word
“subtract.” [Loop–Blinn, §3.1](https://www.microsoft.com/en-us/research/wp-content/uploads/2005/01/p1000-loop.pdf)

The existing GPU stroke heuristic uses frame scale and a subdivision cap; it is
not a demonstrated perspective pixel-error bound. Likewise, GPU curve
flattening alone does not establish that general changing-path generation is
one cheap pass. Intersections, coverage classification, connectivity, bounded
storage, and valid draw counts still belong to Phase B.

Native GL also uses the `0.95`/`1.06` adjustment, in
[fill fragment output](tests/gl_reference_glsl/quadratic_bezier/fill/frag.glsl#L32)
and [compositing](tests/gl_reference_shader_wrapper.py#L635). Its goldens therefore
record that artifact too. Direct stroke/triangulated-fill alpha `0.25` for
styled opacity `0.5` over transparency is a separate blend-state defect.

## Fourth-round code review disposition

The [A1 integration record](docs_unified_triangle_renderer_a1_integration.md#fourth-round-review-disposition)
responds to the latest three findings, including the production Write fix and
the retained exact-array renderer contract. It records shared-driver, border,
packaging and playback changes, plus the open text AA gate. This supersedes
the implementation status in the historical section below.

## Current implementation evidence (A0 checkpoint)

The index-content cache correction, isolated Lyon adapter, independent source
fixtures, opt-in ordered triangle renderer, and retained mesh-quality cache
have focused validation. The cache checks actual source/contour/paint/normal
content and a fresh projection bound, retains immutable meshes within declared
array-byte/entry limits, and refines with headroom. Its tests cover camera and
source invalidation, output quality, memory retention, and failure handling.
Cache hits still scan source bytes; its retention cap is not a total transient,
frame, or GPU-memory bound.

The subsequent [A0 results](docs_unified_triangle_renderer_a0_results.md) now
include native goldens, the stronger border/text comparisons, camera and real
Transform/Write measurements, Earcut-versus-Lyon coverage, and the original B0
comparison of current output, ordered output, and two flattened AA settings.
The broader current/ordered/flattened/analytic architecture gate remains open.
B0 improves, while text frames and default-style
border coverage remain explicit gaps. Unchanged-camera bounds are now memoized
under their actual inputs; changed cameras still check projected quality.

The initial pilot rendered 20 fixtures at 384 × 216; 19 met its broad RGB
threshold. The gradient difference remains visible in the record as the reviewed
intentional-change candidate above, not a blanket pass. The missed border and
small-scene timings prevent treating that pilot as general fidelity or speed
acceptance. Text/hairline AA, full border/material behavior, representative
animated-frame performance, packaging, and the selected route's remaining
quality gates were still open at this checkpoint. Native GL retirement
remained held. The sixth-round correction below supersedes the fifth round's
interpretation of the removal authorization.

## Fifth-round disposition and Phase A cutover

Historical cutover disposition. The sixth-round response below corrects its
native GL authorization claim and qualifies the digest-reuse implementation.

The [fifth code review](docs_unified_triangle_renderer_code_review.md) audited
`a7eb644b`, before the cutover work. The [Phase A record](docs_unified_triangle_renderer_phase_a.md)
owns the final specification and validation. This disposition records the
decisions separately from the reviewer's document.

1. **Plain-2D antialiasing mismatch — accepted and fixed.** The production
   serializer chooses its own 4× MSAA plus 2× spatial resolve, independently
   of `Camera.samples`. Benchmarks call that public default directly.
2. **Rust adoption — explicit decision.** The helper is required by the
   default renderer, so it remains a required build. Source/editable installs
   need Cargo/linker; compatible wheels need neither. The README states this.
   An optional extension would leave a successful install unable to render.
3. **Border union geometry explosion — accepted, technique adapted.** Borders
   use per-sample stencil ownership and actual world-space border triangles.
   They share the final AA policy, so they need no separate winding image or
   CPU polygon union. The hard border emitter preserves Manim's own join,
   width, partial-path and camera-facing geometry. Depth-only replay preserves
   the nearest border depth for later objects.
4. **Repeated hashing — accepted.** Immutable bytes-backed derived arrays
   cache digests. Mutable arrays still hash actual contents. Public source
   validation retains the direct-array-write contract; a revision alone
   cannot establish renderer cache validity.
5. **Recording versions — accepted.** The player accepts versions 1/2/3,
   selects the renderer from the validated recording, and reports corrupt
   recordings visibly. Playback errors stop playback and permit a later seek.
6. **Write — retained.** No change to the validated exact-endpoint fix.

Generated textures retire with the active frame. Both live renderer modes
share bounded, replacement-aware CPU image reads. The original viewer
renderer remains selectable because Taylor requested it for dogfooding.
The native GL camera/wrappers/GLSL and the old native winding driver are
test-only references, excluded from the package.

The AA evidence preserves one specific disagreement with the old sampler:
zero-border zoom misses its former full-frame threshold, while exact pixel
area and 8×/16× convergence controls favor the selected AA. No threshold was
broadened to hide it. All five production-style fixtures pass. Vectorized
border emission and exact source caches replace the expensive scalar path.
An additional exact opaque/unshaded painter fast path reduces the 101-glyph
control to one draw; real GPU tests match separate stencil draws pixel for
pixel. Translucent, gradient, shaded and depth paths retain ownership.

The final complete-frame medians are B0 **80.57 → 25.31 ms** and moving-camera
TeX **6.87 → 15.91 ms**. Text remains slower, primarily in CPU preparation;
the proposed no-regression gate is not reported as passed. The cutover record
explicitly accepts that case for the requested default-renderer dogfood
rollout, records its payload cost and preserves Original 2D for comparison.
This decision rests on current shared-renderer/ordered-output benefits, not
an assumed Phase B speedup.

## Sixth-round response: retain native GL and target the measured regressions

2026-09-10, checked against `67f779dc` and the review in `10e5020b`.
This round verifies findings and records the implementation order. No renderer
code changed during this response. GPU border generation has been discussed
but **has not started**; it is not work already running in the background.

### Native GL direction and correction to the record

My earlier statement that Taylor explicitly authorized native GL retirement
was too strong. The clarified direction carried by the sixth review is to
keep native GL **packaged and runnable as a reference**, keep Phase A as the
default, and retain the separate Original 2D browser option. I accept that
direction and have corrected the plan, decision and cutover records. Native
GL is still test-only in the current code; restoration is the first next
implementation task, not a completed change claimed by this document.

The smallest restoration can promote the existing adapted GL reference
camera, wrapper, shader helpers and GLSL into package modules. The adapted
camera owns its wrappers and already consumes current mobjects through
`get_shader_data`; it does not need GPU resources put back into mobjects or
checkpoint graphs. The wrapper differs from the previous production version
only in imports/docstring, and all 29 GLSL assets match it byte for byte.
Restore `ShaderWrapper` as a packaged/public symbol, runtime `moderngl` and
`PyOpenGL`, shader package data, and wheel checks requiring those assets.
Keep the default camera as WebGPU and expose an explicit native GL camera.

Copying the old camera alone would fail because it calls removed
`Mobject.render` and render-batch methods. Conversely, blindly restoring all
old methods would revive an invalid `StringMobject.get_shader_wrapper_list`
override whose signature omitted `ctx`. The camera-owned reference avoids
both problems. Validate packaged GL without importing `tests`, its pixels
against the frozen reference/goldens, and depth/style changes after capture.

### Findings and decisions

| Finding | Verified result and disposition |
|---|---|
| 1. Fixed-frame order | **Confirmed browser behavior change, with an important qualification.** Before the cutover, our native `Camera.capture` already partitioned fixed-frame groups last; the old browser serializer did not. Moving the partition into `Scene.assemble_render_groups` preserved our native behavior but changed both browser modes. Upstream ManimGL's add-order behavior is a third reference. A global revert would therefore change our old native behavior. Recommend preserving the original browser's stable z/add ordering for Original 2D and making Phase A's native-aligned overlay policy explicit in its own preparation path. Test mixed fixed/world groups with conflicting z values, ties, clipping and depth. |
| 2. Text zoom and transport | **Accepted; performance gate remains open.** Static squares and zooming text are different workloads. Pan can reuse border data; zoom changes border subdivision and can resend roughly 1.2 MB of combined geometry. For the default zoom-with-scaling style, world border width need not change. The archived fill-regeneration count is initial fill creation, not rebuilding every letter's fill on every zoom step. Separate fill and border resources and generate borders on the GPU to target this cost. Measure transport as well as preparation and complete-frame time. |
| 3. Indexed digest reuse | **Reproduced, but not every indexed fill is affected.** Nine unchanged, uncoalesced Lyon fills made nine full-byte hashes on both frames despite retaining the same immutable source arrays. On this NumPy build, converting their explicit little-endian index dtype to `<u4` creates a fresh view with a native-endian descriptor, defeating the identity key. Nine bordered coverage draws used canonical indices and correctly made nine hashes then zero. Skip conversion when dtype is equivalent and storage is already contiguous. Add a regression using real Lyon indices or an explicit byte-order descriptor. Mutable/coalesced arrays must continue to hash actual bytes; this small fix does not solve their repeated assembly or the zoom resend. |
| 4. Gradient paint | **Bandwidth reproduced; coefficient rebuilding is overstated.** A static 400-corner polygon produced a 94,302-byte cached-frame header, including 93,366 bytes of paint JSON. `build_paint` ran once across three preparations, and both drivers reuse matching GPU material buffers. The waste is repeated list/array conversion, validation and JSON transmission. Use independently hashed, immutable paint definitions with active-frame retention; cover paint-only updates, missing definitions, reverse/random seeks and recording reconstruction. The large non-affine inverse-distance fallback is not surfaced in frame limitations and should be. Affine fields remain compact even above 256 samples. No new visual probe was run here, so the reviewer's blotchy example is not independently verified. Also, 16 coverage samples per final pixel do not necessarily mean 16 fragment-shader invocations; the shader does not request per-sample shading. The long per-fragment loop still needs a measured cost limit. |
| 5. Renderer selection | **Confirmed.** A new/reloaded tab starts triangles before adopting server state, then announces that choice and changes other tabs. Negotiate the authoritative server mode before announcing renderer readiness, including reconnects. An explicit user selection is a separate action. Local storage alone would still override another tab's newer selection. Validate two tabs, reload/reconnect, rapid switches and checkpoint preservation. |
| 6. Nonplanar fills | **Compatibility gap accepted; blanket automatic fallback declined.** A nonplanar outline has no unique 3D interior, but a camera-projected painter fill is a possible separately specified behavior. Keep the current explicit unsupported result until a representative scene establishes the required semantics; do not silently flatten or switch renderers inside a supposedly shared frame. Restored native GL and Original 2D provide explicit legacy comparison routes. Compare projected coverage, clipping, depth and paint before choosing a supported shared implementation. |
| 7. Zero-border AA | **Open.** The independent coverage evidence supports the selected AA, and all five production-style fixtures pass, but zero-border zoom still misses the old threshold. Keep both statements. A default dogfood rollout and a documented exception do not make that acceptance test pass. |

The Original 2D GPU texture leak is also confirmed independently of the CPU
file cache. Running the shipped JavaScript drivers with the existing fake GPU
device, four frames each showing a different texture retained `[1,2,3,4]`
textures in Original 2D, then four after an empty frame. Phase A retained
`[1,1,1,1]`, then zero. Retire absent Original textures **after submission**,
including references in cached batches. Its sender already resends returning
textures. The bounded CPU file cache never established a GPU retention bound.

Keep each comparison renderer's original AA defaults for historical evidence;
report the sample policy and add matched-policy controls when isolating
performance. Forcing Original 2D to Phase A's AA would change the baseline.
The stale `__main__` OpenGL description should be corrected when GL returns:
Phase A is default, GL is an explicit reference. The video pixel-format
assumption is an older issue and is not evidence of this cutover's regression.

### GPU borders: a reusable first step within Phase B

The review's direction agrees with our discussion: use a **general vector
fill-border generator**, not a text-only path. Existing expanded curve
records carry points, endpoint widths, normals and joint angles; camera/style
uniforms determine the current expansion. A border path driven by those
records can receive CPU-updated points first and GPU-updated points later.
The ordinary GPU stroke expansion provides reusable math, while its old AA
fringe/premultiplication cannot simply be enabled in the new border pipeline.
Preserve Phase A's hard coverage and shared final AA unless new image evidence
justifies a separate appearance change.

Implementation constraints for this bounded step:

1. Keep immutable fill meshes separate from retained border-source buffers.
   Zoom-only border work must not cause full fill/combined-geometry uploads.
   Fill quality checks and genuine fill refinements still apply independently.
2. Preserve authored operations and per-sample ownership across the fill and
   GPU border operations. Translucency, varying paint, camera-facing borders,
   clipping, fixed-frame interpolation and depth-only replay remain required.
   Do not regroup all objects' fills ahead of all their borders. Also preserve
   or measure the existing opaque-text batching benefit; a low-byte protocol
   that reintroduces hundreds of CPU draw operations is not automatically fast.
3. Compare GPU-emitted positions/counts against the existing CPU emitter and
   then compare final pixels. Use the ten existing fixtures plus subdivision
   thresholds and degenerate/partial paths. GPU floating-point math can differ
   by ulps, so exact float32 equality where attainable plus bounded numeric
   error and coverage checks are more defensible than a universal bitwise claim.
   Keep the CPU reference until this evidence is complete.
4. Measure pan separately from repeated 5% zoom steps, plus 1→4→1 zoom, tilt,
   resize and changing paths. Report generation/preparation, CPU command work,
   upload bytes, transport and complete-frame distributions. Target metadata-
   only border updates—about 1 KB for the existing text control—when source and
   retained fill quality are unchanged. A real fill refinement legitimately
   uploads a new mesh, so this is not a universal zero-upload promise.
5. Keep browser/native, device recreation, recording/seek and source lifetime
   contracts aligned. Choose bounded instanced expansion or compute emission
   based on the smallest implementation that meets these constraints. A full
   general-fill topology engine is not a prerequisite for this border step.

### Implementation order and remaining status

1. Restore packaged native GL and verify the explicit reference route, while
   retaining the Phase A default and Original 2D browser selector.
2. Fix digest normalization, selector negotiation and Original GPU texture
   retirement; record and isolate the fixed-frame ordering policy.
3. Make paint definitions independently reusable and expose the large-field
   fallback; validate its appearance/cost on the reviewer's gradient control.
4. Implement and measure the general GPU border step against all three current
   references, preserving ordering, coverage and opaque batching.

A0/A1 work is implemented. Phase A is on main for dogfooding, with A2 text
performance and the zero-border AA gate still open. Packaged native GL needs
restoration. The broader Phase B source evaluation and general fill generation
remain planned; this response does not claim to have implemented them.

Evidence in this round: actual Python cache/hash and static-gradient transport
probes, a JavaScript fake-device texture-retention probe, six focused
selector/ordering CPU checks, and comparison of the previous native camera,
browser source and GLSL assets. No fresh GPU image or timing run was performed.

## Implementation after the sixth review (2026-09-10)

Taylor approved the sequence: packaged GL, indexed digest reuse, authoritative
selector negotiation, Original 2D texture retirement, the ordering record,
reusable paint definitions, then general GPU borders compared against native
GL, Original 2D and the CPU-border Phase A implementation.

### 1. Packaged native GL

Restored `NativeGLCamera` as an explicit scene camera, the real public
`ShaderWrapper`, original GLSL assets and GL runtime dependencies. Phase A
remains default and Original 2D remains a separate browser option. The frozen
GL reference in tests is unchanged. Shader imports remain context-free; GPU
resources belong to the selected GL camera/context rather than mobjects.

The extracted wheel renders with native GL while a test-import blocker is
active. It also loads the packaged Lyon helper, contains every required shader
and passes Twine metadata checks. The native pixel check matches the frozen
reference exactly across paint, stroke, camera and depth changes.

Validation: 23 native GL/default-camera boundary tests passed with GPU checks
enabled. Copying a camera preserves its frame alias, excludes GPU state and
allocates an independent context on capture. A copied camera keeps identical
pixels after the original is released. This caught and fixed a wrong-context
cleanup bug; resource retirement now activates the owning context and attempts
every cleanup. Headless import and the 281-name CE baseline also pass.

### 2. Indexed digest normalization

The serializer now retains an already contiguous, equivalent little-endian
uint32 index array. Actual nine-fill Lyon preparation/serialization makes
zero second-frame hashes when the draws remain separate and immutable.
Mutable/coalesced geometry still hashes its bytes, and directly translating
one source mesh resends that mesh. The 18-test generated-wire module passes,
including explicit endian descriptors, big-endian conversion, noncontiguous
arrays and writable index updates. This does not yet fix border zoom uploads.

### 3. Renderer negotiation

A new or reconnected tab waits for authoritative server state before starting
its renderer. Readiness and playback resumption no longer select a renderer.
Explicit choices carry request IDs: the latest acknowledgment can restore the
server's final choice after a concurrent remote choice, while stale own
acknowledgments cannot undo a later selection. Same-mode choices are also
acknowledged. Obsolete socket, initialization and blob completions are ignored.

The scripted browser handlers cover reload, reconnect, delayed initialization,
rapid choices and the two-origin race found during implementation review.
35 focused CPU tests and two real WebSocket E2E tests pass, including a new tab
joining Original 2D while geometry is off and switching without changing the
source hashes or current checkpoint.

### 4. Original 2D texture retirement

Original 2D now gathers texture references from every batch, including cached
batches, and destroys absent textures after submission. A failed decode or
command-encoding step rolls back that frame's new uploads, closes decoded
bitmaps and preserves the last submitted frame's textures. Any bindings made
against rolled-back textures are discarded before retry.

The shipped-driver fake-GPU checks cover 24 distinct images retaining exactly
one texture, cached frames retaining it without payload, empty frames retiring
everything, returning images uploading again, shared light/dark channels and
async/encoding failures. All 17 relevant driver/texture tests pass. These check
actual resource lifetimes and submission order, rather than the CPU file cache.

### 5. Ordering record and isolation

Restored stable z/add ordering in Scene for Original 2D. Phase A now owns the
stable fixed-frame-last partition in its shared preparation path, preserving
its current native/browser output. Native GL keeps its historical partition.
The decision record distinguishes the prior native and browser behaviors.

Four ordering tests pass with real GPU checks enabled: explicit wire/draw
order with ties and depth/clip state, the existing mixed-family limitation,
and an overlapping fixed-red/world-blue control rendered through Phase A,
Original 2D and packaged GL. Both native policies show red; the historical
browser policy shows blue. Authored source point/style bytes remain unchanged.

Implementation review caught a grouping edge case: partitioning after Scene
batching can leave compatible world families separate when a fixed overlay
used to sit between them. Phase A therefore rejoins adjacent families with
the same recorded assembly key before sorting their children, preserving the
cutover's partition-before-batching behavior. Original 2D retains its original
group boundaries. A regression covers conflicting child z-indices in those
separated compatible families. This avoids rebuilding semantic Groups per frame.

The first five changes together pass the full native GPU/checkpoint-ledger
suite on main: 648 tests in 206 seconds, with one existing skip.

### 6. Reusable paint definitions

Format 4 carries immutable little-endian float32 paint definitions once, then
references their independent content hashes. Scene preparation retains the
coefficient array directly. Both drivers share one coefficient buffer across
pipeline/sample bindings, retire absent materials after submission, and roll
back newly allocated paint resources after failed frames. Missing definitions
use the existing cache-reset/error path. The recording index restores each
frame's definitions for arbitrary seeks; formats 1–3 and inline paint remain
readable. Geometry connectivity is independent of paint; changing the first
source color can still update an unused RGBA attribute in a paint mesh and
therefore resend its vertex bytes.

The reproducible `benchmarks/paint_retention.py` control uses a static
400-corner polygon, 800 non-affine paint nodes, no border or ordinary stroke,
and 960×540 output. Its unchanged frame falls from **94,308 to 1,140 bytes**;
the 25,696 coefficient bytes are built and sent once. Median wire encoding
falls from 1.49 to 0.064 ms, parsing from 0.71 to 0.018 ms, and native driver
encoding from 1.53 to 0.186 ms. All six saved before/after images are exactly
unchanged. Reports, full images and crops are in
`benchmarks/results/triangle_followup_20260910/paint_{before,after}/`, with a
separate `paint_comparison.json`.

Full serialization-to-RGBA medians were 16.31→11.40 ms for Phase A versus
3.33 ms Original 2D and 3.75 ms packaged GL in the after run. This is still a
large non-affine paint regression: its per-fragment inverse-distance loop
visits 800 samples. Retaining coefficients does not change that shader cost.
The header now reports mode, node count and the 4,096-node cap as an
informational limitation, without rejecting the supported field. An affine
control uses no sample loop and takes 2.52 ms in the after run. Completion
latency varied between the separate runs even for unchanged references; these
are 12 rotated/reversed samples after three warmups, not GPU timestamps or
end-to-end browser measurements.

Interior paint semantics also differ from historical fan interpolation.
The 41,404-pixel analytic affine probe measures Phase A mean RGB error
0.274/255 and maximum 0.678/255 inside radius 1.7, excluding edges. The old
references differ substantially from that authored spatial field. Non-affine
Phase A interiors remain visibly different too. These controls document
paint semantics and cost; they are not cross-renderer parity passes or a
waiver of the existing zero-border AA gate.

Validation: 117 integrated wire, driver-command, static-player and export
tests pass (12 native GPU cases skipped in that CPU invocation); the separate
26-test native run passes with GPU enabled. Controls include the same mesh
with two paints in one frame, unaligned definitions, missing/corrupt data,
failed-frame cleanup, empty/returning scenes and device recreation.

### 7. General GPU fill borders

The default Phase A path now retains compact curve-source records and expands
fill borders in a shared WGSL compute stage. This applies to general vector
objects, including text. The existing CPU emitter remains independently
selectable with `MANIML_BORDER_GENERATOR=cpu`. Python still owns source-point
updates, derived curve inputs and general fill tessellation; this increment
does not complete Phase B. Later GPU source evaluation can write these same
curve records without replacing the ordered renderer.

Format 5 sends immutable fill vertices/static indices separately from a
content-addressed border definition. Camera-only border changes update
uniforms; flat-border pan reuses output. Real fill-quality refinement remains
independent. Fixed capacity holds 32 vertex pairs per curve, clamping unused
samples into degenerate triangles. This avoids a CPU readback for draw counts
and preserves fill A, border A, fill B, border B through the static index
order. Opaque text keeps one scene draw plus one resolve; translucent, painted,
shaded and depth-tested borders keep per-object coverage. Depth-enabled
coverage draws also retain depth replay.

Both drivers retain separate source and generated-output buffers. Output is
identified by draw occurrence as well as input identities, so two uses of the
same source with different uniforms cannot overwrite each other. Storage
bindings respect alignment, size and dispatch limits. Generation reuse state
commits only after successful submission; failed frames discard new buffers
and preserve the previous frame's resources. Absent resources retire after
submission. Switching to Original 2D also releases Phase A's host recipes,
paint/digest memos and fill cache. Returning content resends full definitions.
The recording index rebuilds format 5 inputs for reverse/random seeks; old
formats and inline paint remain readable. Cache misses recover through reset.

Source checks still inspect exact public arrays. The host fill and GPU recipe
caches share the configured 64 MiB budget, including input references pinned
by immutable assembly proofs; disabling retention disables both. The first
measurement exposed repeated copying of unchanged curves on static and pan
frames. Reusing the verified source identity and color removed that work;
the initial measurement and the correction are retained separately.

#### Measurements against all three references

`benchmarks/gpu_borders.py` runs eight cases through GPU-border Phase A,
CPU-border Phase A, shipped Original 2D serialization with the frozen native
WebGPU comparison driver, and packaged `NativeGLCamera`. Each has fresh
sources/devices/caches, three warmups and twelve rotated/reversed measurements
through full RGBA readback. Source evaluation is separately measured and
excluded. The optional real uncompressed localhost WebSocket echo adds two
wire traversals before parsing. Neither run measures browser presentation or
GPU timestamps; historical AA policies differ from Phase A's default.

| Native complete-frame median | GPU border | CPU border | Original 2D | Native GL |
| --- | ---: | ---: | ---: | ---: |
| Exact 211-square B0 | 24.35 ms | 25.12 ms | 66.95 ms | 265.57 ms |
| Static 101-glyph text | 6.96 ms | 7.74 ms | 5.54 ms | 7.76 ms |
| Text pan | 8.80 ms | 9.86 ms | 5.57 ms | 7.77 ms |
| Repeated 5% text zoom | 10.65 ms | 14.37 ms | 5.49 ms | 8.24 ms |
| Text 1→4→1 zoom | 10.72 ms | 17.14 ms | 5.75 ms | 8.06 ms |
| Text tilt | 9.00 ms | 9.84 ms | 5.55 ms | 8.02 ms |
| Text resize | 12.04 ms | 11.62 ms | 6.95 ms | 8.51 ms |
| Changing paths | 5.03 ms | 4.68 ms | 3.04 ms | 3.73 ms |

With WebSocket echo, small zoom improves **16.09→11.06 ms**, and 1→4→1 zoom
improves **19.18→11.23 ms** against CPU borders. Small zoom sends only
**1,077–1,138 bytes**, compared with CPU-border packets up to **1,468,384**.
Its 3,200 curve sources are prepared once. Large zoom legitimately doubles
cumulative fill preparations from 101 to 202 in both modes and can send a
2,671,229-byte GPU fill/index packet. The metadata-only result is conditional
on unchanged source data and adequate retained fill quality.

This reduces the measured text regression; Original 2D still wins these text
controls. Changing paths and one resize median are slightly slower than CPU
borders. The padded output costs more retained memory: static text geometry
buffers total **11.54 MB versus 1.24 MB**, about **9.82 MiB extra**, excluding
AA attachments and allocation overhead. Conservative host mesh/recipe accounting
is 6.58 MB versus 3.30 MB, including shared proof references counted again;
these are not unique physical-memory totals. Compact count/allocation/indirect work remains a future measured
alternative. These are retained sizes, not peak memory claims.

All raw distributions, source hashes, B0's camera packet, adapter details, full
images, crops and reproduction commands are archived in
[the GPU border evidence](benchmarks/results/triangle_followup_20260910/gpu_borders/README.md).
Other camera sequences are reconstructible from the harness and frame indices;
their full per-frame packets are not archived.
GPU/CPU images are exact for six benchmark controls; a few large-zoom/tilt
frames differ by at most 15/255 in one channel. No frame has an RGB difference
over 24. The saved native and transport images are byte-equal. These are
diagnostics alongside the dedicated quality controls, not a waiver of the
existing zero-border AA gate or old/new interior paint differences.

#### Validation and remaining scope

Kernel tests compare the CPU reference's vertices, counts and bounds across
all joins, subdivision ties, huge-density overflow, variable widths,
partial/sentinel paths, collapsed tangents, camera-facing and fractional
fixed-frame inputs. Eight production image controls cover text, hairlines,
perspective and wide borders at normal and zoomed views; all are byte-exact
locally. Cross-device checks allow at most one of sixteen AA coverage samples
within a tightly bounded affected region. Driver tests exercise independent
same-source outputs, dispatch/storage limits, failed-frame cleanup and
reinitialization. Wire/player tests cover definitions, corrupt spans, skipped
operations, cache retirement and arbitrary seeks.

Actual Chrome WebGPU validation passed **35 direct-driver frames and 20
production-player frames**, with no observed GPU validation errors or
unhandled rejections. The translucent border control matches CPU output
exactly at two camera poses. Paint changes, deliberate missing-definition
recovery, empty/returning content, reinitialization and seeks pass. The
[browser report](benchmarks/results/triangle_followup_20260910/gpu_borders/browser/README.md)
states the flags and scope: this is an opaque-canvas correctness check, not a
timing run or a fresh live-selector validation.

The offline wheel/source distribution builds and Twine checks pass. Isolated
extracted-wheel captures verify both native GL and the default GPU border
path while imports from tests/benchmarks are blocked. The packaged Lyon helper
and compute shader load, visible border coverage is checked, straight-alpha
output is preserved, source arrays are unchanged, and CPU/GPU images match.

The final full suite with actual native GPU checks and checkpoint-ledger
verification ran **704 tests in 207.674 seconds**, with no failures/errors and
one existing skip. Its first run exposed a stale WebSocket snapshot assertion
that counted GPU-generated output vertices as uploaded bytes. The corrected
test verifies every payload span, complete definitions and padded index bounds;
the focused real WebSocket check and full rerun pass. CI's explicit module
list now includes the new border, GL-boundary and ordering checks. The local
run used macOS arm64/Python 3.13; other CI platforms/versions were not executed.

General GPU point evaluation and fill topology, the remaining A2 text gap,
large non-affine paint fragment cost, nonplanar contour support and the
zero-border AA gate remain open. Original 2D and packaged native GL remain
available throughout this rollout.

## Seventh-round response (2026-09-10): capacity from step counts, indices off the wire

Implementer (a new session), on the seventh review's seven findings. Taylor's
direction for this round, quoted: "go on 1 through 3" in reply to a plan whose
third item was "the seventh-round border findings: stop sending the padded index
pattern, size border capacity from real step counts, and drop the CPU triangle
budget from the GPU path". Findings 4 and 5 were taken because they were
small; finding 6 is the revision-keying decision, which Taylor said is not yet
understood ("i don't understand 4 yet"), so nothing was changed there.

### Findings 1 and 2: the run layout and the reserved capacity (format 6)

The wire now carries a border run's **fill indices only**. The batch's
`border` descriptor gains `capacity` (even, 4–64) and, on the first send of a
geometry, `layout`: one `[fill index count, fill vertex count, curve count]`
per object in draw order. Each driver expands the interleaved
fill-A/strips-A/fill-B/strips-B index buffer from that layout at the run's
capacity (`expand_run_indices` natively, `expandRunIndices` in the browser),
keeps the fill indices to rebuild it when the capacity changes, and retires
the superseded buffer after the frame is submitted. The layout is part of the
geometry identity; the capacity is not, so a zoom that outgrows a reservation
resends nothing. Cached batches omit the layout and the drivers and the
recording index take it from the retained geometry.

A run's capacity is reserved from its curves' step counts at the current
zoom: two vertices per step, doubled for headroom, capped at 64, sticky per
object until the need outgrows it (the fill cache's 2× policy). The compute
stage receives the capacity in its params (now 32 bytes) and bounds its step
count by it; the sender guarantees the bound is never binding, and the pixel
test asserts a smaller reservation writes exactly the leading vertices of the
full one. Format 5 recordings, whose complete index buffer travelled at 64
vertices per curve, still load through both drivers and the player; the
format version is 6.

Outputs are keyed by `(geometry, source, capacity, occurrence)` where
occurrence counts repeats of the same geometry and source in the frame rather
than every batch, so inserting an unrelated object earlier no longer rekeys
every later bordered object (finding 4). The A0 experiment tests gate on the
packaged helper's discovery (finding 5); the default run now covers them.

### Finding 3: the CPU triangle budget

`BorderSource.read` takes `budget=True`; the GPU recipe cache passes `False`.
The budget bounds the CPU emitter's output arrays, and the GPU path's output
is sized by the reservation and checked against the device's buffer and
binding limits by the drivers, so on that path it only turned a deep zoom into
a render error. A 1,500-curve closed arc at a zoom needing 124,000 triangles
raises on the CPU path and prepares a recipe at capacity 64 on the GPU path.
The fixed 52,428-curve descriptor cap became the portable storage bound
(762,600 curves of 176 bytes).

### Measurements

Same harness, same machine, before at `d639d489` and after; the full table is
in [the archive](benchmarks/results/triangle_followup_20260910/gpu_border_capacity/README.md).

| 101-glyph TeX | Before | After | Seventh-round target |
| --- | ---: | ---: | --- |
| First-frame packet | 3.17 MB | 0.79 MB | under 1 MB |
| Fill-refinement packet, 1→4 zoom | 2.67 MB | 0.29 MB | fill bytes only |
| Retained GPU geometry, static text | 11.5 MB | 4.9 MB | under 4 MB |
| 5% zoom step packet | 1.14 KB | 1.15 KB | unchanged |
| Deep zoom into large text | render error | renders | renders or reports |

Retained geometry misses the 4 MB target by the headroom: the text needs 12
vertices per curve at the default zoom and reserves 24. Halving the headroom
would meet the number and double the regenerations on zoom; the 2× policy
matches the fill cache and was kept. Warmed frame medians moved within noise
except static text and pan, which improved by about 1 ms each; the repeated
zoom stays at 11.3 ms against Original 2D's 5.8 ms because that cost is source
validation (finding 6), not bandwidth. GPU-versus-CPU pixel diagnostics are
identical before and after: exact on six controls, within 15/255 on the 4×
zoom and tilt controls.

### Validation

723 tests pass with GPU checks, ledger verification and the packaged helper
(the A0 tests no longer skip). New coverage: capacity policy and sticky
reservation; deep zoom past the budget; layout validation and expansion in
the serializer, the native driver and the browser driver, including capacity
growth on a cached batch, retirement after submit, and occurrence keys;
compute output at a smaller capacity; recording rehydration with once-only
layouts; format 5 fixtures unchanged. Not run: remote CI, Windows/Linux.

### Correction to the record

The sixth-review section above opens "Taylor approved the sequence". The
reviewer's seventh finding is right that Taylor did not say that; the
sentence stands as written by the previous implementer, and this section
quotes Taylor's direction instead of paraphrasing it.


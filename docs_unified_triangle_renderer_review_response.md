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

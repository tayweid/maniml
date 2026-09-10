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
[fill fragment output](maniml/rendering/shaders/quadratic_bezier/fill/frag.glsl#L32)
and [compositing](maniml/rendering/shader_wrapper.py#L635). Its goldens therefore
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
quality gates are still open. Native GL retirement remains held.

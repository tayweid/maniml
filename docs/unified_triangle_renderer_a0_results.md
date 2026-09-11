# A0 renderer experiments — 2026-09-09

Historical A0 checkpoint. The later [A1 integration record](unified_triangle_renderer_a1_integration.md)
supersedes the implementation status below, adds border unions and packaged
drivers, and records the remaining text-quality failure. Measurements below
remain tied to their archived source snapshots.

The shared-renderer direction has measured value on the original batching
fixture, but the prototype is not ready to replace the current renderer.
Missing fill-border treatment changes text weight; the stricter local image
comparisons expose that clearly. The review helped identify useful checks.
Its proposed analytic and Earcut-only routes remain candidates judged by the
evidence, not additional requirements from the user.

The unified renderer remains an opt-in experiment. Production-code fixes on
this branch cover index bytes in geometry-cache identity and the Earcut call /
planar 3D projection corrections described below. The installed default and
native-GL retirement hold remain unchanged; nothing has been merged into main.

## Code review follow-up

The [third-round response](unified_triangle_renderer_review_response.md#third-round-code-review-disposition)
records decisions on all ten findings. Reports below this section preserve the
earlier checkpoint; the new runs are archived separately in
[the review evidence directory](benchmarks/results/triangle_a0_review_20260909/validation.json).

- **Square speedup reproduced:** [B0 recheck](benchmarks/results/triangle_a0_review_20260909/wordmark.json)
  measures 81.32 ms current, 46.93 ms ordered, and 18.42/21.96 ms flattened at
  one/four samples. This includes CPU preparation through one-pixel readback,
  not source animation or browser presentation. RGB/alpha comparisons match the
  earlier result; the order of the two AA timings changes between runs.
- **Uniform paint reuses triangles:** [motion checks](benchmarks/results/triangle_a0_review_20260909/motion.json)
  record 608 vertex-color refreshes and zero mesh rebuilds during isolated TeX
  opacity animation. Colors still copy/upload with the interleaved vertices.
  Nonuniform diagnostic paint is not covered by this optimization.
- **Write needs a qualified explanation:** the [source audit](benchmarks/results/triangle_a0_review_20260909/write_source_audit.json)
  attributes its 95 warm-run rebuilds to 38 newly visible fills, 56 actual
  point-byte changes and one paint/normal change. Interpolation changes point
  values by up to 2.67e-7 world units in this scene. Exact source validity is
  preserved; these small differences are not silently ignored. Transform
  remains the independent morph control.
- **Zoom now exceeds headroom:** the 1–4×–1× real-text case generates 101
  refinements and retains the fine meshes on return. The original 1–2× control
  only demonstrates reuse within its initial detail margin.
- **Analytic geometry has partial GPU evidence:** [acceptance provenance](benchmarks/results/triangle_a0_review_20260909/analytic_acceptance.json)
  explains the earlier 80-versus-5 counts and bounded numerical changes.
  The real scene path now accepts 100/101 TeX glyphs; one overlap still rejects
  all four full-TeX quality cases. Six hairline/perspective/border cases now
  render in the [quality comparison](benchmarks/results/triangle_a0_review_20260909/quality.json).
  [Small-hole](benchmarks/results/triangle_a0_review_20260909/analytic_hairline.png)
  and [border](benchmarks/results/triangle_a0_review_20260909/analytic_border.png)
  crops include the analytic result as the last row. This remains a restricted
  candidate and still omits fill borders.
- **Existing 3D bug corrected:** typed Earcut arguments avoid the silent center
  fan. Choosing a nonsingular coordinate projection also preserves vertical
  planar fills. These shared CPU fixes are separate from adopting the new
  renderer. The [rerun coverage probe](benchmarks/results/triangle_a0_review_20260909/earcut.json)
  retains the same ten wrapper/five direct-Earcut failures that Lyon passes.

Every revised timing report retains its samples and adds completion minimum /
fractions below 3 ms and above 10 ms. Small-scene totals vary markedly between
runs and are not a reliable isolated GPU-speed comparison. The CPU costs remain
visible: moving-camera TeX preparation is still about 9.7 ms, versus about 3 ms
for current serialization. Current batch retention avoids retirement work that
the candidates pay inside the timer. No general text-speed win is established.

**128 focused CPU tests and 33 native GPU/fidelity tests pass** after the review
fixes, including real-device opacity updates and existing GL/WebGPU parity.
Source hashes and the original native golden checksums are checked separately.
This is not full application/browser/packaging acceptance. Border coverage and
text preparation/batching remain the next implementation priorities.

## Experiments and reproducibility

The [benchmark commands](benchmarks/README.md#shared-triangle-renderer-a0-experiments)
reproduce the source fixtures and report timing/resource scopes. They use the
existing locked Python environment and the isolated, source-only
[Lyon helper](tools/lyon_fill/README.md). The measured device is Apple M3 with
wgpu 0.32.0. Native GL goldens for ten 960×540 scenes are preserved in
[the golden manifest](tests/goldens/triangle_renderer/manifest.json), including
live source/style/order, camera/output settings, renderer information, and
image checksums. Regeneration is explicit; changed source contracts fail.

The quality comparison uses current WebGPU, winding fills with shared ordered
output, flattened meshes with 4× MSAA, flattened meshes on a target doubled
in both dimensions with a GPU box resolve, and an analytic candidate where
its geometry gate succeeds. RGB previews show opaque-background attachment
values; metrics and native goldens retain raw RGBA. Existing opacity artifacts
are separate from geometric coverage.

## Performance and the remaining CPU cost

The original B0 source reconstructs byte-for-byte: 211 squares, 135 current
batches, and the original 2160×1080 camera. In the [final five-sample run](benchmarks/results/triangle_a0_20260909/wordmark.json),
after three warmups per variant with rotated order:

| Variant | Median preparation through completion | CPU preparation | Command encoding | Submission through completion | Passes / draws |
|---|---:|---:|---:|---:|---:|
| Current WebGPU | 76.61 ms | 6.68 ms | 31.80 ms | 38.07 ms | 406 / 540 |
| Shared ordered output | 47.66 ms | 6.87 ms | 24.52 ms | 10.79 ms | 136 / 540 |
| Flattened, 1 sample | 20.62 ms | 10.96 ms | 5.68 ms | 3.89 ms | 1 / 422 |
| Flattened, 4× MSAA | 18.38 ms | 10.58 ms | 5.69 ms | 1.54 ms | 1 / 422 |

Each column is its own median; component medians need not sum to the median
whole frame. Completion includes a one-pixel readback. Source animation,
browser transport/presentation and full-image diagnostics are excluded.
The 4×/1× ordering is not evidence that MSAA is faster: completion varies with
device scheduling. The [earlier run](benchmarks/results/triangle_a0_20260909/wordmark_before_projection_memo.json)
measured current/ordered/flat at 63.39/40.94/27.04 ms. Use these as local
experiments, not universal frame-rate promises.

The bounded CPU improvement came from profiling: unchanged meshes were
recalculating the same projection-error bound. The cache now retains that bound
under the exact view, projection, fixed-frame and resolution inputs, after
checking live source identity. A [paired 40-sample CPU comparison](benchmarks/results/triangle_a0_20260909/projection_memo_profile.json)
reduced B0 preparation from 19.85 to 10.52 ms and static TeX from 8.70 to 3.81 ms.
Its original aggregate results and reproduction script are preserved; individual
timing samples were not retained. Changed
camera inputs still recheck quality; tighter tolerances still refine as needed.
Cold B0 generation remains 35.63 ms, so warm reuse is material to the result.

Ordered output is exactly equal to current RGBA on B0 and all 20 source fixtures
at both sample settings. B0 triangle RGB mean error is about 0.010/255, with no
RGB pixel exceeding a 24-channel error. It is **not RGBA-identical**: 18,450
pixels differ in alpha because the prototype corrects the direct-draw alpha
pairing. That is recorded separately from visible opaque-background RGB.

## Camera motion and changing glyphs

The [motion run](benchmarks/results/triangle_a0_20260909/motion.json) measures
source evaluation plus CPU preparation through GPU completion for 33-frame TeX
zoom, 9-frame fractional translation, 33-frame perspective zoom, and actual
17-frame Transform and Write animations. Every variant preserves source arrays.

- TeX zoom/pan uses retained meshes with zero geometry regeneration/uploads.
- Perspective zoom triggers six refinements and 21,840 geometry-upload bytes.
- Transform changes eight glyphs: 128 regenerations across 16 changed frames,
  uploading 250,108 geometry bytes versus 10,885,440 for current/ordered output.
- Write uploads 1,408,448 triangle/stroke bytes versus 10,885,440 for those
  references. Other glyph meshes remain reusable.

**Fewer uploads do not yet mean faster text frames.** In the final run, TeX
zoom takes 4.95 ms currently versus 12.68 ms for flattened 4× MSAA. Transform is
5.14 versus 8.90 ms; Write is 8.47 versus 9.89 ms. Camera-motion preparation,
including quality checks, still costs about 9.3 ms per 101-glyph frame. The prototype issues separate
glyph draws where the existing text batches well. These are concrete remaining
CPU/command costs. One supersampled zoom frame reached 74.21 ms; tails are
retained in the report, not discarded. A general performance gate has not passed.

Memory scopes also differ: current geometry caching retains historical batches
during a scenario, while ordered output and triangles retire unused buffers.
Reported array/target/buffer bytes are not total process or peak GPU memory.
The initial frame is warm and resident; cold setup and excluded work are
documented in the report. Endpoint/midpoint images do not prove flicker-free
playback of every frame.

## What the quality checks found

**Text needs its fill-border treatment.** Native GL and current WebGPU produce
similar weight in the small-TeX crop. Both flattened treatments look thinner
with the production TeX style because the prototype omits its fill border.
Four samples or a larger target cannot repair missing styled coverage.

With the fill border explicitly disabled in both reference and candidate,
2×-dimension supersampling is close to the current WebGPU result against native
GL. At normal size, paragraph-region mean RGB differences on a 0–255 scale are
4.27 for current WebGPU, 6.02 for flattened 4× MSAA, and 4.37 for flattened
supersampling. At 2× zoom they are 2.92, 3.40, and 2.95 respectively. These
controls support further evaluation of supersampling; they are not default-style
acceptance or proof of temporal stability.

[Default-style TeX crop](benchmarks/results/triangle_a0_20260909/tex_default.png)
and [zero-border control](benchmarks/results/triangle_a0_20260909/tex_zero_border.png)
show the native, current, ordered, flattened-MSAA and flattened-supersampled
outputs in that order. All [quality measurements](benchmarks/results/triangle_a0_20260909/quality.json)
retain full-frame and local-region statistics.

**The stronger border case catches a real omission.** It places a yellow
alpha-0.4 fill with a width-12 border over separate blue/red backdrop paint
operations. Keeping the backdrop separate matters: merging it into the current
winding attachment lets its opaque coverage mask part of the border's MAX
operation. The left boundary crop's mean error is about 8.2 for the flattened
prototype versus 0.09 for current WebGPU. Its full-frame broad threshold still
passes, confirming why local crops and semantic controls are necessary.
The [border comparison](benchmarks/results/triangle_a0_20260909/border_comparison.png)
shows the missing expansion directly.

**The analytic prototype is not a general text renderer.** Its geometric tests
cover inward/outward curves, curved holes, nested contours, subdivisions and
single coverage. The real-GPU annulus check preserves its hole and caps alpha
at the requested 0.4. The initial SVD scene-preparation probe accepted only 5 of
101 TeX subobjects; the others rejected near-collinear curves
or ambiguous interior triangles. Whole frames reject explicitly. Building a
second general geometry implementation to rescue this experiment is not
justified by the current evidence. Keep the candidate isolated.

## General-path generator decision

The [34-case coverage probe](benchmarks/results/triangle_a0_20260909/earcut.json)
uses source-derived signed ray crossings, omits probes too close to boundaries,
and checks both coverage and double painting. Lyon passes all sampled cases.
The installed Earcut algorithm fails five required single-ring cases involving
crossing morphs or repeated traces. Those inputs exceed Earcut's simple-polygon
contract, but they belong to the intended general nonzero renderer contract.

The existing ring-classification wrapper fails ten cases in total, including
three real glyphs. Those glyph results are wrapper evidence, not a claim that
Earcut cannot handle properly classified glyph holes. The probe also records an
then-existing wrapper/binding argument-type incompatibility separately and used
a scoped dtype adapter to avoid confusing it with geometric correctness. The
code-review follow-up fixes that boundary; its new probe needs no adapter.

This is a concrete reason to retain the Lyon experiment. An Earcut-only choice
would require additional correct decomposition/classification work; removing
Rust does not remove that work. The result does not settle binary distribution,
hard memory bounds, complete materials, or the eventual GPU generator.

## Next implementation decision

Validation at this checkpoint: **98 focused CPU tests and 32 native GPU/fidelity
tests pass**. The latter include the existing native-GL/WebGPU comparisons,
ordered-output equality, GPU box resolve, and analytic hole/opacity checks.
Golden and measured-source hashes match; documentation links and diff whitespace
validate. This is focused validation, not a claim that the full application,
browser migration, packaging, or all A0 acceptance gates are complete.

Keep full flattening as the general A0 path under evaluation. Complete a
single-coverage fill-border experiment before choosing an AA treatment or
attempting default cutover. The [border feasibility investigation](benchmarks/results/triangle_a0_20260909/border_feasibility.md)
identifies an initial route using existing Lyon fill/stroke tessellation and
union, with no new library. Its extra CPU work, Manim's custom joins, and the
smooth AA band require measurement; a geometric union alone is not parity.

Keep the historic fan-gradient seam recorded as a defect. A smoother paint
field is desirable, but the prototype's endpoint interpolation still needs
camera/refinement/diagonal stability checks before it becomes a compatibility
decision. Do not repair the old seam merely to lower an image-diff number.

The [shared plan](unified_triangle_renderer_plan.md) carries these quality
and performance gates. The [separate GPU-generation specification](gpu_geometry_generation_plan.md)
retains the approved goal of moving source updates and required geometry
generation together. A0 remains incomplete.

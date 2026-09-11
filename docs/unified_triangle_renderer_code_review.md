# Unified renderer A0 prototype: code review

**Written by a reviewer, not the author.** Third round, 2026-09-09, on the
uncommitted prototype on `plan/ordered-fill-atlas` after the author's
[decisions changelog](unified_triangle_renderer_review_response.md).
Recommendations for the author to accept, adapt, or decline. Earlier rounds
are in the [plan's reviewer notes](unified_triangle_renderer_plan.md#reviewer-notes--2026-09-09).

## What was checked

- Read in full: `maniml/web/triangle_geometry.py`, `benchmarks/triangle_scene.py`,
  `benchmarks/analytic_geometry.py`, `benchmarks/analytic_scene.py`,
  `benchmarks/triangle_renderer.py`, `benchmarks/earcut_probe.py`,
  `tools/lyon_fill/src/lib.rs`, and the test lists. A delegated pass covered
  `benchmarks/renderer_quality.py`, `benchmarks/renderer_motion.py`,
  `benchmarks/ordered_output.py`, `benchmarks/triangle_wordmark.py`, the
  quality fixtures, and the goldens manifest.
- Ran every new test module plus `test_fill_bounds` and `test_wgpu_port`
  with the Lyon helper and the scratch WebGPU dependencies on the path:
  114 pass, 3 skip. Without the scratch dependencies 16 skip as "wgpu not
  installed", so adding only the two GPU-free suites to CI is correct.
- Read the four reports under `/private/tmp/maniml-{triangle,earcut,quality,motion,wordmark}-a0`
  and inspected the comparison strips for the TeX cases.

## Findings, most important first

### 1. Production 3D fills are silently drawn as center fans

Not in the prototype; on `main`. `pyproject.toml` pins `mapbox-earcut>=1.0.0`
and every environment here has 2.0.0, whose `triangulate_float32` rejects the
Python list that `earclip_triangulation` passes for ring ends
(`maniml/utils/space_ops.py:506`). The exception is swallowed in
`maniml/mobject/types/vmobject_3d.py` and `init_simple_triangulation` runs
instead. A plain `Square` triangulates to 241 vertices and 720 indices, which
is a 240-point fan. Concave depth-tested fills and fills with holes render
wrong today. The Earcut probe recorded the TypeError as
`unadapted_production_wrapper_square` without calling it a production bug.
Fix at the native call boundary and add a regression test; a task chip has
been filed for it.

### 2. The analytic candidate never ran on any quality case

All ten quality cases report `analytic_msaa4: rejected`. One glyph failing
rejects the whole frame, so the candidate the first review asked for has no
antialiasing or timing data. Measured on the 101-glyph TeX fixture with the
current `build_analytic_mesh`:

| Outcome | Glyphs | Cause |
|---|---:|---|
| Accepted | 80 | |
| "numerically ambiguous near-collinear curve" | 4 | curvatures of 1e-17 to 1e-20 in normalized coordinates: float noise on straight segments |
| "numerically ambiguous interior triangle" | 17 | Earcut slivers with normalized area at or below 1e-12 |

Both predicates in `benchmarks/analytic_geometry.py` reject harmless input.
Recommend: treat curvature below a tolerance as straight and charge the
control-point-to-chord deviation to the pixel error budget; drop zero-area
slivers instead of rejecting the glyph. The docstring in
`benchmarks/analytic_scene.py` still says 5 of 101 accepted and is stale.

### 3. GPU completion timing is bimodal

Across every variant in the quality and motion reports, `submit_through_completion_ms`
lands at roughly 1.4 ms or roughly 12.8 ms with few samples between:

| Report, variant | Samples | Under 3 ms | Over 10 ms |
|---|---:|---:|---:|
| motion, current_webgpu | 109 | 32 | 67 |
| motion, ordered_output | 109 | 26 | 70 |
| motion, flat_msaa4 | 109 | 40 | 19 |
| motion, flat_ss2 | 109 | 37 | 13 |

That is a polling quantum in the one-pixel readback, not GPU work. Medians of
that distribution are noise, which is why every variant in the motion report
converges on about 15 ms total. Use timestamp queries, or report the fast-mode
fraction and minimum alongside the median. The B0 wordmark sits above the
quantum and its comparison stands:

| B0 wordmark, 2160 × 1080 | Draw p50 | With CPU preparation |
|---|---:|---:|
| Current winding renderer | 56.6 ms | 63.4 ms |
| Ordered output only | 33.6 ms | 40.9 ms |
| Flat triangles, 1 or 4 samples | 7.1 ms | 27.0 ms |

### 4. Per-frame cache validation is the new CPU cost

With every mesh a cache hit and zero regenerations, triangle preparation on the
TeX scene costs three times the serializer, and on the wordmark three times
again. `_MeshSource.matches` compares every source array byte for byte each
frame, and `TrianglePrototype._buffer` hashes every draw's bytes for buffer
identity. At small scenes this eats most of the GPU win. Production should key
on `Mobject.revision`, which the checkpoint ledger already maintains, with
the byte comparison kept as a verify mode. The existing docstrings disclose
the O(source bytes) scan; the reports do not translate it into a caveat on
`prepare_ms`.

### 5. Fill borders, not antialiasing, are the text blocker

In the `production_default` paragraph strip the flat variants are visibly
thinner and lighter than native GL. That is the omitted fill border, which
the report records as a limitation. With borders zeroed, the picture changes:

| tex_zoom, borders zero, vs native GL | Mean RGB diff | Existing threshold |
|---|---:|---|
| current_webgpu | 0.367 | met |
| flat_ss2 | 0.373 | met |
| flat_msaa4 | 0.442 | not met |

So the 2× supersampled resolve matches native as closely as the current
renderer does, 4× MSAA is marginal, and the fill-border coverage combination
moves to the top of the gap list for text parity.

### 6. The Rust question now has its evidence

In the Earcut probe, three real TeX glyphs fail the existing ring wrapper
with wrong nonzero coverage, and the crossing morphs and duplicate contours
fail direct Earcut. Lyon passes all 34 cases. That meets the criterion the
author set for added Rust cost, with the caveat that the wrapper had to be
adapted to run at all because of finding 1.

### 7. The motion benchmark's Write scenario measures paint invalidation

A production `Write` ramps fill opacity every frame. `_MeshSource.read`
includes `fill_rgba`, so every glyph on the line regenerates its mesh each
frame although its geometry never changes. The 95 regenerations in that
scenario are paint changes, not the morph cost the earlier review asked for,
and this breaks the plan's own section 6 rule that paint-only changes should
not rebuild connectivity. The scenario description does not disclose it.

### 8. The zoom scenarios cannot trigger camera invalidation by construction

`TriangleMeshCache(refinement_factor=0.5)` builds each mesh with half the
pixel budget as headroom, and the zoom sequence runs 1× to 2× and back. A
mesh built at 1× stays within budget through exactly 2×, so zero
regenerations over 33 frames is guaranteed by the chosen range. Push the
range to 4×, or run once with no headroom, before reading "zoom is free"
from the report.

### 9. Baseline timing keeps a leaking cache

`baseline_frame` in `benchmarks/triangle_renderer.py` never retires the
current renderer's batch cache, while the ordered and triangle variants
destroy unused buffers inside the timed window. In morph scenarios the
baseline gains a small timing advantage. The memory note discloses the
retention; the timing note does not.

### 10. Full-frame thresholds are labeled as a gate on region crops

`existing_rgb_threshold_met` in `benchmarks/renderer_quality.py` was
calibrated on frames dominated by background and is also applied to crops of
a few hundred pixels, where it means almost no pixel may differ. The crop
results came back empty in the report, so this is a latent mislabel rather
than a wrong conclusion.

## What came back clean

- `tools/lyon_fill/src/lib.rs`: bounded output, panics caught, partial meshes
  never escape, no binary in the repository.
- `maniml/web/triangle_geometry.py`: input validation, ownership, and limit
  handling are sound; per-call state, no identity cache.
- The index-hash fix in `maniml/web/geometry.py` with a wire-byte regression test.
- Goldens are native GL, captured through the real camera with the TeX
  template hash in the manifest; every variant is diffed against them.
- All three antialiasing treatments run; the supersampled path scales the AA
  width uniform so stroke fringe stays constant in final pixels, and a test
  covers it.
- The ordered-output control uses the same fixture, targets, and readback
  barrier, with pixel equality to the current renderer proven at both sample
  counts.
- Warmups excluded, variant order rotated, medians and tails reported, CPU
  preparation separated from GPU time. No test compares a renderer to itself.
- The cache's frame-end eviction of absent fills regenerates glyphs as a
  Write reveals them, which the counts confirm and which is acceptable.
- Draw order sorts by `z_index` within each render group, consistent with
  the known cross-group limitation.

## Suggested next steps for A0

1. Fix the analytic predicates and rerun the quality corpus so the candidate
   has data.
2. Replace the readback timer with timestamp queries or report the fast-mode
   fraction; rerun motion and quality.
3. Separate paint invalidation from geometry invalidation in the cache, and
   widen the zoom range past the headroom.
4. Implement fill-border coverage for the flat path, since it is now the
   visible blocker for default text.
5. Key cache validity on `Mobject.revision` and measure preparation again.
6. Land the production Earcut fix on `main` independently of this branch.

## Fourth round: reply to the third-round disposition

Reviewer again, on the [author's disposition](unified_triangle_renderer_review_response.md#third-round-code-review-disposition),
the [A0 results](unified_triangle_renderer_a0_results.md), and the rerun
reports under `benchmarks/results/triangle_a0_review_20260909/`. All 130 tests
pass with `MANIML_TEST_GPU=1`, the Lyon helper, and the scratch WebGPU
dependencies on the path.

### What held up

- The Earcut fix is correct and the regression test forbids the fan in the
  XY, XZ and YZ planes. Fixing it exposed a second bug, vertical planar fills
  collapsing under a fixed x/y projection, which the nonsingular-plane choice
  in `vmobject_3d.py` also fixes. These two production files and
  `tests/test_earclip_triangulation.py` deserve their own commit so they can
  reach `main` ahead of the branch.
- The analytic predicates now accept 100 of 101 TeX glyphs. The provenance
  explanation is right: the reviewer's 80 came from a direct world-xy probe,
  the author's 5 from the SVD scene path. Six quality cases now carry
  analytic data. On the hairline case it matches 4× MSAA and beats the
  supersampled resolve.
- The uniform-paint refresh path in `TriangleMeshCache.mesh` is correct: it
  copies the frozen vertex array, updates the byte accounting, and evicts if
  the cache goes over budget. The opacity control records 608 refreshes and
  zero rebuilds.
- Timing reports carry the minimum and the fractions below 3 ms and above
  10 ms. That is the honest fix short of timestamp queries.
- The 4× zoom case crosses the headroom, triggers 101 refinements, and reuses
  the finer meshes on the way back.

### Remaining pushback

1. **Text still has no analytic data.** All four TeX quality cases are
   rejected with "interior mesh overlaps an analytic patch". One glyph's
   interior triangle crosses a curve's control triangle and the whole frame
   is refused. The existing subdivision loop resolves curve-versus-curve and
   edge-versus-triangle conflicts but not Earcut's own interior triangles
   crossing a patch, because Earcut is unconstrained. Subdivide the offending
   curve and retry within the existing budget. It is a small change and it
   unblocks the comparison this candidate exists for.

2. **Declining revision-based reuse contradicts a bet the project already
   made.** The checkpoint ledger trusts `Mobject.revision` for correctness
   and catches bypass writes with `MANIML_VERIFY_LEDGER`. The renderer cache
   can adopt the same contract and the same verify mode instead of scanning
   source bytes every frame. Camera-motion text preparation is still about
   three times the serializer, and that is the cost this decision keeps.

3. **The Write audit found a production inefficiency, not a benchmark
   artifact.** Finished glyphs have their points rewritten every frame with
   changes up to 2.7e-7 world units, because interpolation at alpha 1 is not
   bitwise equal to the target. That defeats any exact-bytes cache and bumps
   revisions for nothing. Two fixes are worth doing: have `Write` stop
   interpolating a submobject once it is complete, and let the cache reuse a
   mesh when the point displacement, charged through the projection bound it
   already computes, stays inside the pixel budget.

### Smaller notes

- `benchmarks/results/` adds about 2 MB of PNG and JSON per checkpoint. Decide
  whether archived runs belong in the repository before it grows.
- The current renderer's B0 total moved by a third between runs on the same
  machine, which supports the results document's own caution about
  small-scene totals.

## Fifth round: audit of the A1 integration

Reviewer again, 2026-09-10, on commits `e46ebe42` (Write endpoints) and
`a7eb644b` (generated geometry in both WebGPU drivers), against the
[A1 integration record](unified_triangle_renderer_a1_integration.md).
Files were changing on disk again while this was written; anything after
`a7eb644b` is not covered here.

### What was checked

- Full discovery with `MANIML_TEST_GPU=1`, `MANIML_VERIFY_LEDGER=1`, the Lyon
  helper and the scratch WebGPU dependencies: 541 tests, the only failures
  are the two long-standing AppShell end-to-end cases, one Windows-only skip.
  This matches the record.
- Read in full: `maniml/web/triangle_scene.py`, `generated_geometry.py`,
  `static/geometry_recording.js`, the diffs to `geometry.py`,
  `wgpu_renderer.py`, `webgpu.js`, every WGSL file, `player.js`,
  `animation/creation.py`, `triangle_geometry.py`, `tools/lyon_fill/src/lib.rs`,
  `pyproject.toml`, `MANIFEST.in`, and `ci.yml`. A delegated pass covered the
  browser driver, the recording helper, the player, and the Node-backed tests.
- Ran the production selector on a plain 2D scene and measured the border
  union on the 101-glyph TeX fixture.

### Findings, most important first

1. **The shipped selector renders 2D fills with no antialiasing.** An
   ordinary scene has `camera.samples = 0`. The winding path keeps its own
   2× fill AA in that case; the triangle path maps it to one sample and draws
   hard-edged fills. Verified: a plain Square through
   `serialize_scene(renderer="triangles")` produces a header with one sample.
   The A1 quality and timing tables come from `benchmarks/generated_output.py`,
   which sets four samples for the triangle variant only (line 132). The
   record therefore describes a renderer the environment variable does not
   give. The triangle path should choose its own AA, 4× MSAA or the 2×
   resolve, independent of the scene's sample setting.

2. **Rust is now a hard build dependency for every source and editable
   install.** `setuptools-rust` is in the build-system requires, so
   `pip install -e .` needs cargo 1.97 and a linker for everyone, including
   users who never set the selector. The plan said packaging evidence does not
   automatically authorize adoption; this commit adopts it implicitly. The
   default renderer never loads the helper, so the extension can be
   `optional = true` in the ext-modules table: installs without Rust keep
   working and the selector fails with the existing "helper missing" message.
   This needs an explicit decision, and it changes the main-checkout workflow
   described in CLAUDE.md.

3. **The border union multiplies geometry by an order of magnitude.** The
   union feeds every fill triangle and every stroke triangle to the sweep as
   its own contour, so a vertex appears wherever a fill diagonal crosses a
   stroke strip. Measured on the 101-glyph TeX paragraph with a border of 2%
   of glyph extent:

   | 101 TeX glyphs | Vertices | Triangles |
   |---|---:|---:|
   | Fill only | 8,368 | 8,216 |
   | Fill plus border union | 72,158 | 134,166 |

   That is the source of the 3 MB retained per paragraph and of serialization
   rising from about 3 ms to about 11 ms. A stencil-masked border avoids the
   CPU union: draw the fill writing a stencil reference, then draw the border
   with the existing stroke shader under a not-equal stencil test. Coverage
   stays single-owner, no geometry is generated, and the stroke shader's AA
   fringe returns, which is closer to the current border than a binary union.
   Section 5.2 of the plan allows another shared-backend coverage technique.

4. **Unchanged meshes are rehashed every frame.** `serialize_generated_frame`
   runs blake2b over every draw's bytes on every frame, cache hit or not.
   Cache entries are frozen and immutable, so a digest computed once at
   generation, plus a composite for coalesced runs, removes most of the
   remaining per-frame CPU cost.

5. **The format bump rejects every existing export.** `player.js` refuses
   anything but version 2 while winding payloads are unchanged and
   `geometry_recording.js` handles version 1 frames. Accept both versions.

6. **The Write change is sound.** Exact endpoints, revision-keyed skipping
   only when no updaters are present, and tests for reverse rate functions,
   Unwrite, restarts, and raw endpoint writes. Style matching moved from the
   whole family at begin to each submobject on first interpolation, which is
   equivalent because alpha zero reaches every family member.

### Smaller items from the browser-side pass

- `stroke.wgsl` already premultiplies in border mode, so forwarding
  `border_mode` on the generated path would premultiply twice. Unreachable
  today, unguarded.
- A throw mid-pass leaves that frame's buffers alive until the next
  successful frame. Not a wedge; the render queue recovers.
- The player has no error surface for a corrupt recording; a missing hash
  throws past the error display.
- The texture cache never evicts. This predates the change, but the
  "current-frame retention" claim does not extend to textures.
- Nothing runs player, recording, and driver together end to end; the two
  halves are tested separately.

### What checked out

- The default winding path is unchanged: blend state, pass structure, clear
  color, uniform layout size, and the renamed pad field, which no winding code
  ever set.
- Generated buffers and bind groups retire only after submit and only when
  absent from the frame. Uniform keys include the packed bits, so one mesh
  with two uniform sets is two bindings.
- Depth is disabled for 2D draws and inherited for depth pipelines. Draw order
  is the authored order; coalescing only merges consecutive compatible runs.
- Reverse seeks rebuild frames from CPU bytes without historical GPU buffers.
- The wheel check loads the helper from an extracted wheel in an isolated
  interpreter. The Rust union rejects nonuniform attributes and keeps every
  bound.

### On process

A1 started while the A0 text gates were still open, and the record says so.
That is acceptable for an opt-in path. Findings 1 and 2 are the two places
where opt-in is not yet opt-in: a default install now needs Rust, and the
opt-in renders worse than the benchmark reports.

## Sixth round: audit of the Phase A cutover

Reviewer again, 2026-09-10, on commit `67f779dc` and the
[cutover record](unified_triangle_renderer_phase_a.md). This round also
carries a direction from Taylor that corrects the record.

### Direction from Taylor: native GL stays

Taylor did not authorize removing the native GL renderer. The authorization
recorded in DECISIONS.md, TODO.md and the cutover record is not correct and
should be amended by the author. The requirement is:

- The native GL renderer remains in the **package**, not only under `tests/`,
  and remains the ground truth the shared renderer is compared against for a
  while longer. Its shaders, `ShaderWrapper`, and the GL camera path come back
  as shipped code; `moderngl` and `PyOpenGL` return to runtime dependencies.
- Phase A may stay the default renderer. Most output looks good and the
  end-to-end checks below pass. Keeping GL is about retaining the oracle, not
  reverting the cutover.
- The viewer's Original 2D option stays as well; it is a second comparison,
  not a substitute for GL.

Restoring GL is the first item for the author, ahead of the findings below.

### What was verified

- Full discovery with real GPU tests and ledger verification: 625 tests. The
  one failure was an artifact of invoking the interpreter by a relative path.
  The two long-standing AppShell failures are genuinely fixed.
- `--render` of the dogfood `Demo` and `animation_0` scenes and `--export` of
  `Demo` succeed through native WebGPU. Frames pulled from both movies show
  Tex, pixel-grid text and the episode title rendered correctly.
- `uv build --wheel` succeeds with cargo 1.97. The wheel contains the Lyon
  helper and the Original 2D shaders, no GLSL and no tests. The wheel check
  loads the helper from the extracted wheel and tessellates a fill and a border.
- Stencil border ownership, the 2× resolve, native capture to straight alpha,
  GPU-free checkpoint copies, and renderer switching on both sides all checked
  out in a delegated pass over both drivers, the camera, and the selector.

### Findings, most important first

1. **Fixed-in-frame objects now always draw last, on both renderers.** The
   render-group sort in `scene.py` became `(is_fixed_in_frame, z_index)`.
   Upstream ManimGL draws fixed-frame objects in add order. This is a
   behavior change with a test but no decision record, and because it applies
   to Original 2D too, that option is no longer a faithful baseline for scenes
   mixing overlays and world objects. Record it or revert it.

2. **The performance gate is failed and the failure lands on the dogfood
   interaction.** The record reports the numbers honestly:

   | Case | Original | Phase A |
   |---|---:|---:|
   | B0 wordmark, static | 80.6 ms | 25.3 ms |
   | 101-glyph TeX, camera zoom and pan | 6.9 ms | 15.9 ms |

   What the record's timing excludes is transport. Border geometry depends on
   the zoom level through stroke step counts and the width factor, so every
   zoom step regenerates borders for every glyph and resends them:

   | Text scene, per frame | Payload |
   |---|---:|
   | Unchanged frame or camera pan | 1 KB |
   | Each 5% zoom step | 1.2 MB |

   Pan is fine. Zoom pushes tens of megabytes per second over the socket. The
   GPU border work in progress is the right fix; see the section below.

3. **Digest reuse is dead code for every indexed fill.** In
   `generated_geometry.py` the index array is converted to a fresh view each
   frame before the identity key is built, so the key never matches the
   retained payload and every fill is rehashed every frame. Measured: 18
   hashes over all bytes on a static nine-fill scene. Build the key before the
   conversion, or skip the conversion when the array is already contiguous
   uint32.

4. **Gradient paint is rebuilt and resent every frame.** The paint field is
   serialized into the header even when the batch is marked cached. A
   400-point gradient polygon sends a 94 KB header per frame with nothing
   changing. Above 256 distinct samples the field silently falls back to
   inverse-distance weighting, which looks blotchy next to the old linear
   gradient, and `paint.wgsl` loops up to 4,096 samples per fragment at 16
   samples per pixel. Hash the paint once and send it as cached; treat the
   fallback as an explicit limitation.

5. **The renderer selector does not persist on the client.** The server keeps
   the mode and sends it in every state message, but the client never reads
   it. A page reload sends the default, which the server treats as a change
   and broadcasts to every other tab.

6. **Nonplanar filled VMobjects now raise instead of drawing.** The winding
   renderer drew them, badly but without failing. A course scene with a filled
   closed 3D curve now stops with an error. For scenes that used to run, a
   warning plus the previous behavior is the safer default; the explicit
   contract can apply to new scenes.

7. **The AA exception stays an unmet gate.** Zero-border zoomed text misses
   the old full-frame threshold. The 16× coverage argument is reasonable and
   no threshold was widened, but it should remain listed as open.

Smaller: the retained winding browser driver's texture cache is unbounded
while Phase A's is not; Original 2D renders at one sample, so side-by-side
comparisons are confounded by AA; the video writer's pixel-format assumption
predates this work; the `__main__` docstring still says OpenGL.

### On the GPU border work

Moving border triangle generation to the GPU is the right direction: it is
how the original stroke shader stayed fast on text, and it removes the
zoom-dependent CPU regeneration and the 1.2 MB resend at once. Suggestions
for that work:

- Feed the border pipeline the same expanded three-record-per-curve source
  the stroke shader already consumes, with width, joint angles and the zoom
  factor as uniforms. Then a zoom step changes uniforms only, and the fill
  mesh cache stops depending on `frame_scale` for borders.
- Keep the per-sample stencil ownership exactly as it is. The GPU-generated
  strips overlap at joins the same way the CPU ones do, and ownership is what
  makes that safe for translucent fills.
- `border_geometry.py` already has a test proving the vectorized emitter
  matches the scalar one. Reuse those fixtures to prove the shader matches
  the CPU emitter vertex for vertex before deleting the CPU path, then keep
  the CPU emitter under tests as the reference.
- Measure the two numbers from finding 2 after the change: text preparation
  time under zoom, and payload bytes per zoom step. The target is the
  original's shape, about 1 KB per camera-only frame.
- Camera-facing borders and fixed-frame sources were the cases the CPU
  emitter handled specially; make sure they have fixtures before cutover.

### Where Phase A stands

A0 and A1 are done. A3's cutover happened on an authorization Taylor did not
give, and native GL must come back as the ground truth while Phase A stays
the default. A2's exit is not met on performance and carries one recorded
quality exception. The two items that bite in dogfood today are the zoom
resend, which the GPU border work addresses, and the dead digest reuse, which
is a small fix.

## Seventh round: GL restored, GPU borders, and the follow-up fixes

Reviewer again, 2026-09-10, on the seven commits from `7324ce89` through
`00d8e854` on `main`, against the author's
[implementation report](unified_triangle_renderer_review_response.md#implementation-after-the-sixth-review-2026-09-10).

### What was verified

- **Full suite on main:** 704 tests pass with real GPU checks and ledger
  verification. 30 tests skip unless `MANIML_LYON_LIBRARY` is set; with the
  packaged helper passed explicitly they run and pass too.
- **Native GL is back in the package and works.** `NativeGLCamera` renders
  the dogfood scene to a movie from the installed package. Its final frame
  against Phase A differs by 0.104/255 mean RGB with 0.04% of pixels over
  the 24-level threshold. The GLSL assets are byte-identical to what was
  removed; moderngl and PyOpenGL are runtime dependencies again.
- **Both targets from the sixth round are met.** Measured on the 101-glyph
  TeX scene with default borders:

  | Text scene, per frame | Sixth round | Now |
  |---|---:|---:|
  | Unchanged frame or camera pan | 1 KB | 1.1 KB |
  | Each 5% zoom step | 1.2 MB | 1.2 KB |
  | Preparation on a zoom step | about 9 ms | about 6.7 ms |

  The gradient polygon's unchanged frame fell from 94 KB to 1.5 KB.
- **Driver review came back clean on every question.** Compute pass writes
  a vertex buffer, the ordered draw binds it with the static indices; stencil
  ownership, per-object references, and the 255 rollover are unchanged;
  output capacity is fixed with clamped steps, so there is no overflow class;
  sources and outputs are keyed by content, retired after submit, and rolled
  back on failure; recompute happens only when a border-affecting uniform
  changes and is never re-uploaded. Depth-only replay still works. Paint
  definitions are hashed once and retained on both drivers and in the
  recording index. Negotiation adopts the server's mode before readiness and
  only broadcasts explicit choices. Original 2D textures retire after submit
  with cached batches keeping theirs alive. The fixed-frame policy is now
  Phase A's own, with Original 2D back to its historical order.

### Findings, most important first

1. **The padded border index buffer travels on the wire.** The first frame
   of the TeX scene is 3.1 MB, of which 607,842 indices at four bytes each
   is 2.4 MB. That buffer is a deterministic pattern: curve index times 64
   plus a fixed strip layout. It is also the bulk of the 2.67 MB packet the
   report attributes to a large-zoom fill refinement. Generate it on the GPU
   with vertex-index arithmetic in the border vertex stage, or build it once
   per driver from the curve count, and send only the fill indices.

2. **Retained GPU geometry grew nine times for text.** Fixed capacity of 64
   vertices per curve puts the one-paragraph control at 11.5 MB against
   1.24 MB before. A course scene with several paragraphs will retain tens
   of megabytes. The report names compact count/scan/emit as future work;
   until then, a per-object capacity from the actual maximum step count at
   the current zoom would recover most of it, since most glyph curves never
   reach 32 steps.

3. **The CPU triangle budget still gates GPU borders.** `BorderSource.read`
   raises when the CPU estimate exceeds 87,381 triangles at the current zoom,
   and the frame becomes a render error. GPU output is fixed-capacity and
   already allocated, so the budget no longer protects anything. A deep zoom
   into a large text object hits it. Replace it with the real buffer and
   binding limits the driver already checks.

4. **Border outputs are keyed by draw ordinal.** Inserting or removing an
   earlier object shifts every later bordered object's key, forcing a new
   buffer, a fill-prefix copy, and a recompute. Correct, but keying on the
   uniform state that actually affects the output would avoid the churn.

5. **The A0 experiment tests still call the helper optional.** Thirty tests
   skip unless an environment variable names the library, although the
   packaged helper is now required and discoverable. Gate them on the
   packaged discovery so the default run covers them.

6. **The remaining text gap is source validation, not borders.** Phase A's
   repeated zoom sits at 10.65 ms against 5.49 ms for Original 2D, and an
   unchanged text frame still costs about 5.9 ms to prepare with nothing to
   send. That is the per-frame byte comparison of every source array. The
   recommendation from the fourth round stands: key on `Mobject.revision`
   with the byte comparison as a verify mode.

7. **Attribution.** The report opens with "Taylor approved the sequence".
   Taylor said the coder was working on GPU borders. Keep attributions to
   what was actually said; the sixth round was about exactly this.

### Where this leaves Phase A

This is a strong round. GL is back as the ground truth, the transport
regression that would have hurt dogfood is gone, gradient paint is retained,
the selector and texture leaks are fixed, and the ordering policies are
separated and recorded. The A2 text gate remains open, but the regression is
now preparation cost rather than bandwidth, and finding 6 is the lever.
Findings 1 and 2 are the memory and packet costs that come with fixed
capacity and are worth taking before the next dogfood pass.

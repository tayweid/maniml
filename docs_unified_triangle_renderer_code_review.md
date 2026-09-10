# Unified renderer A0 prototype: code review

**Written by a reviewer, not the author.** Third round, 2026-09-09, on the
uncommitted prototype on `plan/ordered-fill-atlas` after the author's
[decisions changelog](docs_unified_triangle_renderer_review_response.md).
Recommendations for the author to accept, adapt, or decline. Earlier rounds
are in the [plan's reviewer notes](docs_unified_triangle_renderer_plan.md#reviewer-notes--2026-09-09).

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

Reviewer again, on the [author's disposition](docs_unified_triangle_renderer_review_response.md#third-round-code-review-disposition),
the [A0 results](docs_unified_triangle_renderer_a0_results.md), and the rerun
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
[A1 integration record](docs_unified_triangle_renderer_a1_integration.md).
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

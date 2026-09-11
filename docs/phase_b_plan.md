# Phase B plan: one description, evaluated on the GPU

Written 2026-09-11 from the planning conversation with Taylor. Status:
proposed; the increments below are not started. The Phase B specification
(`gpu_geometry_generation_plan.md`) and the instruction-stream sequence
(`../simlab/INSTRUCTION_STREAM_PLAN.md`) remain the contracts for resources,
counts, recovery and validation; this document decides the representation
and the order, which those left open.

## The decision

Taylor, quoted, in order:

- "the machinery is the same between both. wouldn't that mean the move to
  gpu can be done for both at once?"
- "use the path way of describing a surface (broadly defined) to define a
  Surface (technical meaning), with control points instead of grid / mesh
  points."
- "more important than perfect is simplicity and i want there to be only
  one approach, not one with a fallback. so i think that means besier."

So: **every drawable object is Bézier control points.** A path is quadratic
curves, as it always was (anchor, handle, anchor; curve `i` is
`points[2i:2i+3]`). A surface is a net of control points evaluated the same
way in two parameters. The GPU evaluates control points at the density the
screen needs, every frame, and keeps nothing that depends on zoom. There is
one representation, one generator stage, one triangle backend.

What this withdraws from the earlier plans: the tracer that would compile
user Python into GPU programs (instruction-stream Phase 3b), exact
closed-form library programs for the built-in surfaces, and any notion of a
fallback representation. What stays on the CPU is construction: Tex, SVG
and font outlines already arrive as curves; `ax.plot(f)` samples `f` into
curves once, as today; `Surface(uv_func, resolution)` samples `uv_func` into
a net once, the same way. Arbitrary Python in updaters keeps running in
Python and produces new control points; that is Python computing the
description, not a second kind of description.

What it costs, accepted: a patch sphere is off by hundredths of a percent,
as the sixteen-curve circle already is. Rational weights would make arcs and
spheres exact inside the same kernel and are a refinement, not a second
approach. Reading a surface's `points` returns its net rather than grid
samples; the conformance suite will show who depends on that.

## The principle, concretely

An object carries control points and style. The generator stage turns
control points into this frame's triangles at screen density:

| Description | Generator | Today |
| --- | --- | --- |
| curve triple, stroke style | stroke strip per curve, steps from zoom | on the GPU (`stroke.wgsl`) |
| curve triple, fill border | border strip per curve, steps from zoom | on the GPU (`border_compute.wgsl`, format 6) |
| closed curves, fill | the interior | on the CPU: Lyon mesh at a zoom-dependent tolerance, rebuilt when zoom outgrows it |
| net, surface | a grid at screen density | on the CPU: a grid fixed at construction, never refined |
| points, dots | quads | unchanged |

The two rows that say "on the CPU" are Phase B. The first is where text
lives; the second is the unification. Everything downstream of the
generator, ordering, depth, stencil ownership, paint, AA, the two mirrors,
recording, is Phase A and does not change.

## Increment B1: fills that never depend on zoom

The interior of a closed path is the one thing a control-point description
does not hand over directly; it has to be constructed. Under one approach it
is constructed on the GPU from the same curve records the border stage
already retains (the 44-word source record carries the three control points
and orientation), so a fill adds no new upload.

Two constructions are candidates. Both leave the curved edge exact: each
curve's control triangle is drawn as a **patch** whose fragment shader
decides, in the triangle's own coordinates, which side of the curve a pixel
is on. This works in any orientation and under perspective, writes depth
and takes lighting like any triangle, and never needs refinement.

- **B1-fan: winding on the stencil.** Draw a fan of triangles from one
  anchor to every consecutive pair of anchors with stencil increment for
  one winding and decrement for the other, draw the patches the same way,
  then cover the object's bounding rectangle where the count is nonzero.
  No triangulation exists anywhere: a morph that changes concavity, holes
  or crossings needs nothing recomputed, because the count is computed per
  sample per frame. Cost: overdraw inside the fan, two stencil operations
  per object, and the interaction with depth and translucency has to be
  specified rather than inherited. This is what Original 2D does per pixel,
  as geometry passes in the triangle backend.
- **B1-mesh: interior once, patches always.** Triangulate the polygon of
  anchors on the CPU once per source revision, with no tolerance, and draw
  the patches beside it. Fewer passes and no overdraw, but a morph moves
  anchors every frame and the polygon must be re-triangulated each frame,
  which reintroduces per-frame CPU work for exactly the animations Phase B
  is meant to free, and later demands a GPU triangulator (the specification's
  open research problem) to finish.

B1-fan is the one approach; B1-mesh keeps a triangulator in the design.
The specification's caution applies: a stencil technique is a different
output contract whose extra passes, alpha and depth behavior must be
specified and benchmarked before adoption. So B1 starts with one week of
prototyping B1-fan in the native mirror against the CPU-border Phase A
pixels on the existing fixture corpus (glyphs, the concave quad morph, the
compound contours, translucent overlaps, depth-tested fills), measuring
passes, overdraw and completion. If it holds within the existing pixel
tolerances at Original 2D's completion cost, it is the design; if not, the
plan records why and B1-mesh is the interim with the triangulator queued.

Per-object stencil ownership already exists (references 1–255 with a
rollover pass), so the winding count can live in the same attachment; the
depth-only replay for depth-tested objects already exists too.

Acceptance: no regeneration on any camera change; the four text controls at
or below Original 2D's complete frame in the two-variant harness; pixels
within the existing tolerances against CPU-border Phase A and Original 2D;
the zero-border AA gate measured again, since patch edges are new geometry;
nonplanar closed contours still refused exactly as today. Both mirrors,
format 7 on the wire, recordings of formats 5 and 6 still playable.
Estimate: prototype week plus one to two weeks.

## Increment B2: surfaces as control nets

`Surface(uv_func, resolution)` keeps its signature and samples `uv_func`
once into a biquadratic net, with `resolution` naming the net's density;
the built-ins (`Sphere`, `Torus`, `Cylinder`, `Cone`, `Disk3D`, `Square3D`,
`Rectangle3D`) ship their nets directly. A compute stage evaluates each
patch at a density chosen from its screen size, with shared-edge densities
so adjacent patches meet without cracks, and emits the grid, its indices and
the normals from the patch derivatives. `TexturedSurface` takes its texture
coordinates from the patch parameters. `Transform` between surfaces
interpolates nets after aligning their sizes by exact subdivision, as
curves do. Checkpoints copy nets.

This is the same kernel shape as the border stage: a record per patch, a
capacity from screen density with headroom, an index pattern the drivers
build. Estimate: one to two weeks.

Acceptance: a zoomed sphere shows no facets at any zoom; `test_wgpu_port`
pixel parity between mirrors; the conformance baseline unchanged or its
changes listed; memory per surface reported against today's grids.

## Increment B3: animations as GPU programs

The instruction-stream Phases 1 and 2, on control points only: `affine`,
`blend` of aligned control points, `partial`, `paint`, `width`, a clock with
rate tables, both mirrors, shadow mode against the CPU first, then the flip
for supported plays. With B1-fan there is no connectivity to preserve or
regenerate, so a blend between two aligned paths is a blend of control
points and nothing else; the "flip only combinations whose generation is
correct" rule reduces to "the program library". The read tables in
`read_instrumentation_2026-09-11.md` decide which reads must synchronize.
Estimate: the sequence's own three to four weeks plus two to three, to be
re-estimated after B1.

## What is no longer planned

- The tracer (Phase 3b): withdrawn by the decision. Updaters that are
  library-expressible (`always`, `f_always`, `always_shift`, the tracker
  vocabulary) become programs in B3; the rest run in Python and upload
  control points, which is small.
- General GPU topology generation (instruction-stream Phase 0): withdrawn if
  B1-fan holds, because nothing is triangulated; kept as the B1-mesh
  follow-on otherwise.
- Exact library surface programs: withdrawn; rational weights are the
  refinement if exactness is ever wanted.

## Order and what to decide

B1, then B2, then B3. B1 first because text is the course, and because its
prototype week answers the only open design question. The one decision
Taylor makes along the way is the B1-fan verdict after that week, on
measured pixels, passes and completion time.

## Decided before the start (2026-09-11)

Taylor accepted these defaults ("ok those are all fine"):

1. **B1 lands behind a switch.** Phase A's CPU fills stay the default while
   the patch fill exists as `MANIML_FILL=patches`; the default flips only
   after the prototype gate passes on the fixture corpus and one course
   episode. Same pattern as `MANIML_BORDER_GENERATOR`.
2. **The pixel gate is the existing one.** At most 0.5% of pixels over 24 of
   255 against CPU-border Phase A and Original 2D, with the zero-border AA
   number re-measured because patch edges are new geometry. Nothing is
   widened to pass.
3. **Native mirror first.** The prototype week runs in `wgpu_renderer.py`,
   where pixels and passes are testable; the browser follows once the design
   is chosen, and `test_wgpu_port` parity gates the flip.
4. **Circle density stays at sixteen curves.** Raising `Arc`'s constant is a
   later one-line change; doing it now would move every pixel baseline.

Engineering, not decisions: the density rule for patches and nets is the
quarter-pixel target the fills use today; the wire format becomes 7 with
formats 5 and 6 still playable.

## Starting B1: where things are

Work in the `maniml-perf` worktree on branch `work`; integrate to `main`
by fast-forward; never push. Another session works in `maniml-engine` on
scene/mobject/animation files; B1 lives in the renderer files, so the two
do not meet until B2 touches `Surface`.

- **Curve sources on the GPU already:** `maniml/web/gpu_border_geometry.py`
  packs 44 words per active curve (three control points, density, flags,
  RGBA); `maniml/web/static/wgsl/border_compute.wgsl` reads them. A patch
  needs the same three control points, so the fill can bind the same
  source buffer; format 6's run layout is in `generated_geometry.py`.
- **Fill preparation:** `maniml/web/triangle_scene.py` (`prepare_triangle_frame`,
  `TriangleMeshCache`, `_generate_mesh`); the Lyon call it replaces is
  `_generate_mesh` and `triangle_geometry.py`.
- **Stencil ownership and passes:** `maniml/web/wgpu_renderer.py`
  (`_encode_generated`, references 1–255 with the rollover pass,
  `_out_pass`), mirrored in `maniml/web/static/webgpu.js`
  (`encodeGenerated`); shared shaders under `maniml/web/static/wgsl/`.
- **Fixtures:** `tests/renderer_fixtures.py` (`quad_convex`,
  `quad_before_flip`, `quad_after_flip`, `quad_concave`, the compound and
  crossing contours) and `tests/renderer_quality_fixtures.py` (the
  101-glyph TeX control). Pixel comparisons: `tests/test_wgpu_port.py`,
  `tests/test_gpu_border_quality.py`, `tests/test_renderer_motion.py`.
- **Measurement:** `python -m benchmarks.gpu_borders --samples 12 --warmups 3
  --cases tex_static tex_pan tex_zoom5 tex_zoom4_cycle --output <dir>`,
  with `--variants gpu_border original_2d` for the two-renderer comparison
  and never inside a `MANIML_VERIFY_LEDGER=1` shell; archive summaries
  under `benchmarks/results/<name>_<date>/` per `benchmarks/README.md`.
- **Validation:** the full suite with
  `MANIML_TEST_GPU=1 MANIML_VERIFY_LEDGER=1` and, from the worktree,
  `MANIML_LYON_LIBRARY` pointing at a built helper; the absolute interpreter
  path `maniml/.venv/bin/python`. CI's module lists are guarded by
  `tests/test_ci_module_lists.py`.
- **Records to keep:** a dated section in
  `unified_triangle_renderer_review_response.md` per increment; a
  `DECISIONS.md` entry only for what Taylor decides, quoted; measurements
  archived with source hashes.

The prototype week's deliverable is the B1-fan verdict: pixels against the
gate, passes per object, overdraw, and completion time against Original 2D
on the two-variant harness, written up before any default changes.

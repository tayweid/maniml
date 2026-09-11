# Phase B1 plan: fills as fan and patch geometry on the stencil

Written 2026-09-11 at the start of B1, from `phase_b_plan.md` and a
mechanism probe on this machine (`benchmarks/probes/fan_stencil_probe.py`).
Status: design proposed, prototype week not started. Nothing here changes
a default; the patch fill lands behind `MANIML_FILL=patches` and the
verdict on it is Taylor's, on the measurements the week produces.

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

Every closed path is drawn in one ordered pass, in draw order, with two or
three draws per object and no geometry that depends on zoom:

1. **Mark.** For each curve `(p0, p1, p2)` of the object, the fan triangle
   `(base, p0, p2)` and the patch triangle `(p0, p1, p2)`, pulled by
   `vertex_index` from the curve records already on the GPU. No colour
   writes. Stencil: `increment-wrap` for front faces, `decrement-wrap` for
   back faces, write mask `0x7F`. The rasterizer's facing supplies the sign
   that `fill.wgsl` computes from a determinant, and the patch's fragment
   shader discards where `y − x² < 0` in the triangle's own coordinates,
   evaluated per sample. Sentinel curves (`p0 == p1`) emit nothing, as in
   `fill.wgsl`; a straight curve's patch has zero area. The clip-plane
   discard applies here too, so a clipped region counts as outside.
2. **Mark strips** (bordered objects only). The border strips the compute
   stage already writes, drawn as today but with `replace` of reference
   `0x80` under write mask `0x80`. Strips overlap at joints and on tight
   curves with arbitrary facing, so they cannot take part in the count; a
   bit of their own makes them order-independent instead.
3. **Cover.** The same geometry again, fan, patches and strips, with the
   colour fragment (`surface` or `paint`, lit by the object's plane normal).
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

Why not the bounding rectangle the plan sketched for the cover: it needs a
per-frame margin for the border width and the miter length, it paints
off-plane border samples at the plane's depth, and a margin that falls
short leaks counts into the next object. Redrawing the mark geometry has
none of those and costs one more pass over triangles that are mostly
stencil-rejected before shading.

## Data

- **Curve records.** The 44-word record of `gpu_border_geometry.py` keeps
  its layout. Word 39, reserved and validated as zero today, becomes the
  object index within the run, which the fan needs to find its base point.
  Word 37 stays the border-active flag. The fill packs **every** curve of
  a filled path, not only border-active ones: a zero-width or invisible
  curve still bounds the fill. For text nothing changes in size, since
  every glyph curve is border-active; objects with no border at all gain
  records they do not have today, 176 bytes per curve, which is less than
  the mesh vertices and indices they upload now.
- **Object table.** Per object in a run: base point (3), plane normal (3),
  fill RGBA (4), padding to 12 words. The base point is the centroid of
  the anchors; any fixed point per object gives the same count, the
  centroid keeps the fan's slivers small. Uploaded once per source
  revision as a hashed blob beside `border_data`, cached the same way.
- **Plane.** `planar_coordinates` still runs per source revision, for the
  normal and to refuse nonplanar closed contours exactly as today.
- **Wire.** Format 7: a batch with pipeline `patch` or `patch_depth`,
  `fill_num_verts` 0, the `border` descriptor as today with the run layout
  carrying each object's curve count, and an `object_data` span. Formats 5
  and 6 parse unchanged; the new pipeline name is only emitted under the
  switch.

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

# One triangle renderer for 2D and 3D, then GPU geometry generation

Proposed architecture and implementation plan — 2026-09-09.

Status: A0 has started and remains incomplete. The opt-in Lyon prototype,
independent source fixtures, index-identity correction, and retained mesh-quality
cache have focused validation. Text/hairline AA, complete border/material
coverage, the four-way comparison, packaging, and representative total-frame
performance have not passed their acceptance gates. The default renderer and
the user hold on native GL retirement remain unchanged.

The [A0 measurement record](docs_unified_triangle_renderer_a0_results.md) now
contains native goldens, text/border comparisons, generator coverage, camera
and Transform/Write checks, and the original B0 performance comparison.
B0 benefits substantially; text coverage and text-frame CPU cost remain gaps.
The third-round code review added uniform-paint mesh reuse, bounded analytic
numerical repairs, 4× zoom stress, and qualified timing/region reports. The
separate Earcut call and vertical-plane projection bugs are corrected on this
working branch. These changes do not complete A0 or select a new default.

The initial source audit is against `2b5aeeba`. Performance numbers explicitly
labelled as earlier experiments are not measurements of the proposed renderer.
Research references were checked on 2026-09-09. Work is uncommitted on branch
`plan/ordered-fill-atlas`; this is not a detached checkout.

This replaces the shared-fill-atlas proposal as the intended renderer direction.
The atlas document remains a record of useful experiments. It also amends the
GPU instruction-stream design: moving point operations is not sufficient;
generating correct fill geometry must move with them.

Author update: selected amendments from both review rounds are incorporated in
sections 2, 4–10, and 12–13 below. The reviewer-authored block and its A0 note
are preserved verbatim as historical review; their “not yet adopted” and
implementation/branch-status statements describe the review's original context.
The [response changelog](docs_unified_triangle_renderer_review_response.md)
records author dispositions. Review is a second opinion, not an automatic
expansion of scope: use the checks that improve the decision, then choose the
simplest general, correct, fast implementation. Detailed Phase B work now has a
[separate research specification](docs_gpu_geometry_generation_plan.md); that
editorial split preserves the approved objective of moving both source updates
and required geometry generation to the GPU.

## Reviewer notes — 2026-09-09

**Written by a reviewer, not the author.** Everything in this section is a
recommendation for the implementer to accept, adapt, or decline. The plan
below stands as the author wrote it; nothing here has been folded into it.
Claims about the code were checked against `2b5aeeba`.

### What held up under checking

- The serializer hashes `raw + tri_bytes` and omits `index_bytes`
  ([geometry.py:364](/Users/taylorjweidman/Projects/ManimLive/maniml-perf/maniml/web/geometry.py:364)).
- The 3D path falls back to a fan on triangulation failure
  ([vmobject_3d.py:90](/Users/taylorjweidman/Projects/ManimLive/maniml-perf/maniml/mobject/types/vmobject_3d.py:90))
  and earclip carries a self-overlap TODO
  ([space_ops.py:422](/Users/taylorjweidman/Projects/ManimLive/maniml-perf/maniml/utils/space_ops.py:422)).
- Both drivers create a bind group and a uniform buffer per draw.
- Fill borders are drawn into the winding texture by `stroke.wgsl` in
  `border_mode` before the composite, so "fill plus border is one coverage
  operation" is the right reading.
- The status framing (nothing implemented, numbers are earlier experiments,
  GPU tessellation is an unsolved research gate) is accurate.

### Pushback

1. **The plan gives up analytic curves and does not lead with that.** The
   current fill shader evaluates each quadratic exactly per pixel with the
   `y - x²` test and never flattens, so it is zoom and resolution independent
   for free. Flattened meshes reintroduce camera-dependent invalidation, which
   section 6 concedes. In a live tool with camera zoom this means
   retessellation on camera-only frames during Phase A. Strokes do not have
   this problem: `stroke.wgsl` already picks its subdivision from
   `frame_scale` on the GPU each frame, so flattened fills would fall behind
   strokes under zoom. In perspective 3D the right sample count also varies
   per object with its distance from the camera, so no single global
   tolerance is correct for a scene; the current 3D path's fixed 240 samples
   is why `shader_wrapper.py` notes polygonal silhouettes. In Phase B
   re-flattening is one cheap GPU pass, so this is specifically a Phase A
   cost. A middle ground exists:
   tessellate the anchor polygon once, camera independent, and keep one
   analytic curve triangle per segment using the existing orientation sign and
   `y - x²` discard. Section 8.3 groups this with Skia's stencil wedges and
   sets it aside, but for simple non-self-intersecting paths, which is nearly
   all Manim content, no stencil pass is needed. Recommend making it an A0
   candidate beside full flattening, and stating the analytic-curve trade in
   section 2 rather than section 5.3.

2. **Phase A's evidence does not distinguish it from the atlas proposal.** In
   the section 3 table, the shared ordered output experiment already reaches
   32.8 ms against 57.1 ms with zero changed pixels and no tessellation. That
   is close to the section 10 target on its own. The triangle replacement is
   justified by enabling Phase B, not by Phase A numbers. Recommend saying so
   plainly, and requiring Phase A to beat the ordered-output experiment with
   CPU tessellation time included, or recording that A is accepted on B
   grounds.

3. **Phase B is a research project and should be its own document.** It is
   larger than the rest of the roadmap combined, and section 8.3 says no
   portable WGSL generator has been identified. Coupling the A decision to it
   makes A look riskier than it is. A stands alone even if B never lands.

4. **Lyon means a Rust extension in the build.** There is no maintained Python
   binding, so adopting it adds per-platform wheels to a project that ships
   pure Python plus wgpu, for a phase whose CPU generator is meant to become a
   fallback. Earcut has prebuilt Python wheels, handles holes, and fails on
   self-intersections the same way earclip does. Recommend earcut as the A0
   probe and Lyon only if the fixture corpus demands it, with the packaging
   cost written into the A0 exit criteria either way.

5. **The 0.95 / 1.06 alpha hack is an unlisted known deviation.** `fill.wgsl`
   scales alpha by 0.95 and `composite.wgsl` multiplies back by 1.06, so the
   current web output already differs from the styled opacity. Section 4 says
   not to enshrine accidental defects but does not name this one. Native GL is
   the real oracle and it is the thing being retired; A0 should capture native
   GL goldens specifically, not web frames.

6. **Gradients have no existing "correct" interior to preserve.** The winding
   fill interpolates per-point color across a fan from `base_point`, so the
   interior field is arbitrary today. Section 5.3 is right to ask for a
   specification; the tests should not encode the fan.

7. **Small-text antialiasing is the one place this route can visibly lose.**
   Four-sample MSAA on a paragraph of small Tex looks worse than the current
   2× supersampled fill texture, and WebGPU guarantees only 4×. Every other
   2D feature maps cleanly once the generator is correct. Recommend making
   this comparison the first A0 deliverable.

8. Minor: the absolute `/Users/...` links will break on the GitHub-synced
   machines the workspace notes anticipate; both plan documents and the
   TODO edit are uncommitted in the worktree.

### Proposed changes to A0

- **First deliverable: the antialiasing comparison.** A paragraph of small
  Tex plus hairline strokes, at 1× and zoomed, against native GL goldens,
  under three treatments: flat mesh with 4× MSAA, anchor mesh with analytic
  curve wedges, and a 2× supersampled target with resolve. Pass or fail on
  the existing image thresholds before any other A0 work.
- **A three-way probe, not a single prototype.** Full flattening, anchor mesh
  plus analytic wedges, and the already-measured ordered output alone as the
  control. Run all three on the hard fixtures in section 10.
- **Generator choice.** Earcut first; Lyon only on corpus evidence; either
  way the packaging cost is an exit criterion.
- **Goldens from native GL**, captured now, as the durable corpus.
- **Per-submobject caching during morphs.** Measure retessellation cost on a
  real Transform and a Write of a long Tex, so only the glyphs currently
  changing regenerate. If that cost shows up in dogfood, it is the pressure
  that justifies Phase B.
- **Revised exit.** Add: the antialiasing comparison is accepted; and Phase A
  beats the measured ordered-output experiment with tessellation included, or
  the author records that A is accepted on Phase B grounds.

Overall verdict from the reviewer: keep the direction. Full 2D Manim through
one triangle backend is a solved class of problem, not a research question;
only Phase B is research.

### Second round — reviewer reply to the author response, 2026-09-09

Reviewer again. This replies to
[the author response](/Users/taylorjweidman/Projects/ManimLive/maniml-perf/docs_unified_triangle_renderer_review_response.md)
and the uncommitted A0 prototype. Same footing as above: recommendations
for the author to take or leave.

**Verified.** All new tests pass, 57 in the repository environment and the
32 WebGPU tests once the scratch dependencies are on the path; without them
16 skip as "wgpu not installed", so adding only the two GPU-free suites to CI
is right. The index-hash fix is in place with a regression test that inspects
the wire bytes. The Lyon helper is source-only, catches panics, and never
publishes a partial mesh. The pilot report covers 20 fixtures at 384 × 216
through one ordered pass: 19 meet the existing RGB threshold, the gradient
case fails as stated, and the wide-border case passes without drawing the
border because only a thin ring differs. Draw times are equal for both
renderers at that size, so the pilot says nothing about performance yet, and
the response does not claim it does.

**Corrections accepted.** Anchor polygon plus signed curve triangles is not
a valid construction; a concave segment leaves the anchor polygon overfilled
and a positive patch cannot un-paint it. The Loop–Blinn interior must include
the control points of inward-bulging segments so the patches subtract. The
0.95 / 1.06 opacity adjustment is also in native GL, so GL goldens record it
too; the response's split of historical frames, geometric tests, and explicit
alpha tests is the right fix. Earcut was already a dependency through
`mapbox_earcut`.

**Remaining pushback.**

1. **Decide the gradient case; do not chase parity.** In the pilot images
   the winding version shows the fan seam radiating from the base point and
   the triangle version is smoother. That is a deliberate visible improvement
   to record under section 4, not a threshold failure to repair.
2. **Strengthen the border fixture.** A wide border in the fill color only
   changes a ring of pixels. Put the border on a translucent fill over a
   contrasting background so the coverage combination, which section 5.2
   names as a feasibility gate, actually appears in the diff.
3. **Fold the accepted amendments into the plan.** The plan text is
   unchanged; the zoom matrix, the four-way comparison, the per-object pixel
   error budget, and the Phase B split live only in the response. The plan
   should carry them and the response should shrink to a changelog. The A0
   note below still says "not yet adopted" for that reason.
4. **Name the criterion that decides the Rust question.** The prototype now
   exists and works, so packaging is a real cost, not a hypothetical one. The
   A0 exit should state what would settle it: whether Earcut fails any
   fixture that matters on the corpus, including intermediate morph frames.

Housekeeping: the plan, response, prototype, and tests are uncommitted in a
worktree detached at main, so a branch is needed before a WIP commit.

### Third round — code review of the A0 prototype

Reviewer again. The prototype review, with test results, report readings,
and ten ranked findings, is in
[the code review document](docs_unified_triangle_renderer_code_review.md).

## 1. The proposal in plain language

Use one WebGPU triangle-drawing backend for both 2D and 3D content. Ordinary 2D
content uses drawing order with depth testing and depth writes disabled. 3D
content uses its explicit depth policy. Both use the same resources, camera
machinery, materials, command preparation, and output infrastructure.

Do this in two major phases:

1. **Unify drawing.** Continue updating points and generating fill triangles on
   the CPU. Draw through the shared triangle backend. Preserve the supported
   vector appearance, then retire the separate winding-fill renderer.
2. **Move geometry work to the GPU.** Move supported point updates **and the
   triangle generation required by those updates** onto the GPU. The same
   triangle backend draws their output. Python sends source data, operations,
   styles, and playback instructions rather than a new mesh every frame.

```text
Phase A
Python: source paths → animated points → fill meshes
GPU:    meshes + existing direct primitives → ordered 2D/3D drawing

Phase B
Python: source paths, assets, operations, playback instructions
GPU:    animated points → current fill meshes → ordered 2D/3D drawing
```

The point arrays exposed by the Manim API remain the source of truth. A mesh is
derived drawing data, not a replacement for the user's Bézier control points.
It can contain additional vertices and a separate array of triangle indices.

### What “one renderer” means

One backend can contain several shaders and material types. Keep efficient
direct drawing for strokes, surfaces, images, textured surfaces, and dot clouds.
In particular, the existing stroke shader already constructs triangles on the
GPU; moving that work back to the CPU would be unnecessary.

The target removes the special winding-fill scratch-image/composite cycle. It
does not require one shader, one draw call, or one batch for every possible
scene. Different textures, materials, depth states, and ordered effects can
still require separate draws. Several draws can share one output render pass.

## 2. Can everything currently drawn in 2D use this backend?

**At the level of GPU capability, yes. At the level of the existing 3D fill
implementation, not yet.** A triangle backend with appropriate geometry,
coverage calculations, and materials can represent the currently supported
2D drawing. This is a capability assessment, not a proof of identical pixels
or lower total frame time.

Putting points on a plane does not itself perform the conversion. Most ordinary
2D points already have `(x, y, 0)` coordinates. The meaningful change is from
triangles used to calculate winding coverage to triangles that describe the
actual covered region, including its boundary treatment.

The current surface shader paints the triangles it receives. It does not
automatically implement the curve clipping, fill-border behavior, or signed
coverage cancellation in the current fill shader. Those semantics must be
supplied by geometry generation and materials before the old path is removed.

**The curve representation is an A0 decision.** Current winding fills evaluate
quadratic boundaries analytically. Full flattening replaces those boundaries
with segments whose required detail changes with zoom, resolution, and
perspective. Mesh-quality caching avoids unnecessary rebuilding, but refinement
can still add CPU work during camera motion. That trade belongs in the total
frame comparison, including smooth zoom and small text.

Compare full flattening with **non-overlapping interior triangles plus analytic
boundary patches**. The latter can preserve fixed curves under camera zoom
without flattening refinement. It requires a correct interior/patch partition,
not simply an anchor polygon with extra signed triangles. A curve that bends
into the anchor polygon needs the excess interior excluded before drawing;
overlapping control hulls can require subdivision even when the path is simple.
Each patch selects the correct covered side. It must not subtract alpha from
scene pixels that have already been painted. General intersections, animation,
clipping, paint, borders, and AA still require explicit support and validation.
[Loop–Blinn construction, §3.1](https://www.microsoft.com/en-us/research/wp-content/uploads/2005/01/p1000-loop.pdf)

“2D mode” means painter-order rendering, not dropping the z coordinate or
forcing a new camera projection. Existing scene geometry can leave the xy plane;
camera transforms, fixed-frame behavior, clipping, and shading must retain their
defined meanings. Ordinary flat scenes should retain their existing appearance.

A further distinction is essential: a nonplanar closed 3D contour has no unique
filled surface without an additional definition. Audit such inputs against the
existing behavior; do not silently reinterpret them as a planar polygon.

## 3. What exists, and what the measurements establish

The current winding path prepares a bounded, 2× sampled floating-point image,
draws fill and border contributions into it, composites it into the output,
and draws ordinary strokes. Its helper triangles may overlap or have negative
orientation because the coverage calculation adds and cancels contributions.

The current 3D fill path already constructs an indexed mesh on the CPU and draws
it directly. Useful infrastructure is therefore present. Its current limitations
include fixed-density curve sampling, one flat fill color per object, forced
depth testing, and point-content-based triangulation invalidation. The earclip
helper does not reliably cover self-intersections, and the current failure
fallback can paint a center fan that is not the requested shape.

Native and browser WebGPU drivers also create fresh uniform resources and start
separate output passes around individual draws. Direct triangle output alone
does not remove those costs: resource reuse and shared ordered output passes
belong in this proposal.

### Existing evidence, with its limits

Five warmed, alternating native WebGPU samples of the B0 wordmark at
2160 × 1080 on Apple M3 produced:

| Existing experiment | Logical batches | Render passes | Command preparation | Submission through completion |
|---|---:|---:|---:|---:|
| Current bounded winding renderer | 135 | 406 | 29.61 ms | 27.47 ms |
| Separate prepared fills, then shared ordered output | 135 | 136 | 22.16 ms | 10.60 ms |

The second experiment reproduced the opaque fixture with zero changed pixels.
It used separate temporary fill images, not a triangle replacement or an atlas.
Completion includes a synchronous one-pixel readback. Both columns exclude
animation, serialization, transport, and browser presentation. A live B0
process remained open during sampling. These numbers establish an opportunity
in drawing organization; they do not establish this design's speed.

There is no equivalent measured 3D stress comparison yet. Ordinary 3D surfaces
already avoid the winding-image cycle, so do not transfer the measured 2D gain
to them. The historical roughly 1.5 ms one-batch result is an aspiration, not
a promised outcome for general animated paths.

The initial opt-in mesh pilot rendered 20 small fixtures at 384 × 216. Nineteen
met its broad RGB threshold; the gradient difference is now a reviewed
intentional-change candidate (section 4). The wide-border omission also passed,
demonstrating that this global threshold alone is inadequate. Similar draw
times at that small size do not establish a performance benefit. This pilot
does not complete A0, small-text AA, or the required four-way comparison.

### Source map for the audit

- [Winding fill shader](maniml/web/static/wgsl/fill.wgsl)
  and [surface shader](maniml/web/static/wgsl/surface.wgsl).
- [CPU triangulation cache](maniml/rendering/shader_wrapper.py#L433),
  [curve sampling and fallback](maniml/mobject/types/vmobject_3d.py#L83),
  and [earclip limitations](maniml/utils/space_ops.py#L422).
- [Serialized triangle data](maniml/web/geometry.py#L101),
  [native WebGPU driver](maniml/web/wgpu_renderer.py),
  and [browser driver](maniml/web/static/webgpu.js).
- [Draw-order rules](maniml/utils/family_ops.py#L27),
  [stroke geometry and coverage](maniml/web/static/wgsl/stroke.wgsl),
  and [camera, clipping, and lighting](maniml/web/static/wgsl/common.wgsl).

## 4. Compatibility specification

The reference is the supported ManimLive behavior, with current ManimCE as the
public-API compatibility reference. Existing known defects are recorded
separately. This project must not quietly turn an existing limitation into a
claim of full CE support, or reproduce an accidental defect as a new requirement.

| Behavior | Requirement for the shared backend |
|---|---|
| Bézier fills | Approximate curves with a declared screen-space error bound, or retain an analytic boundary treatment inside the shared backend. Zoom and perspective must not expose coarse polygons. |
| Holes and concavity | Respect contour direction and the applicable fill rule. Preserve compound glyphs and disconnected subpaths. |
| Self-intersections and degeneracies | Correctly classify coverage for intersecting contours, coincident edges, repeated points, tiny segments, and disappearing contours. Do not silently substitute a triangle fan. |
| Fill color and opacity | Preserve existing per-point data. Assign attributes to inserted mesh vertices; do not collapse the object to its first color. Specify interior color evaluation so changing a diagonal does not arbitrarily change a gradient. |
| Fill borders | Preserve `fill_border_width`. The existing border's coverage combination is visible behavior; it is not equivalent to painting another translucent stroke over the fill. |
| Ordinary strokes | Preserve varying width/color/opacity, `flat_stroke`, zoom scaling, joints, and open endpoints. Reuse the existing direct stroke generator initially. |
| Joins and caps | Test currently implemented joint modes. Full CE cap-style support is not established by this audit; any added cap semantics need their own specification and tests. |
| Antialiasing | Preserve thin strokes, subpixel motion, text edges, and small holes. Four-sample MSAA is a candidate mechanism, not evidence of parity with the existing 2× fill plus border. |
| Transparency | Correct accumulation between distinct objects; no accidental repeated opacity within one paint operation because its triangles overlap. Verify RGBA on transparent targets as well as RGB on opaque backgrounds. |
| Draw order | Preserve complete fill/stroke ordering and `stroke_behind`. Never batch all fills ahead of all strokes when that changes the picture. |
| Depth | Painter-mode 2D has no depth test or writes. Preserve the separately specified behavior of depth-tested 3D objects and mixed scenes. |
| Camera and coordinates | Preserve world coordinates, perspective, fixed-frame interpolation, clipping, and viewport/scissor state. Flat 2D content is a mode of the common renderer. |
| Lighting | Preserve unlit 2D and existing optional shading. Derive suitable normals; a fixed +z normal is not a general solution for rotated 3D paths. |
| Other drawables | Retain image, surface, textured-surface, and dot-cloud behavior and their efficient specialized pipelines. |
| Animation | Creation/Write, partial paths, transforms, nonlinear deformations, topology changes, color-only updates, and camera-only updates must remain correct. |

The present cross-top-level-group `z_index` limitation remains a separately
identified issue. The migration must preserve the currently specified sequence
and must not introduce new ordering errors. A global CE-order fix can be a
separate tested change; do not hide it inside a performance comparison.

### Recorded defects and deliberate changes

The historic gradient fan can create a seam radiating from its base point.
Treat that seam as a known defect. The author's recommended direction is a
smoother, continuous paint field; do not tune the new generator to reproduce
the seam. This is a proposed compatibility improvement, not an assumption that
the user has approved every visible difference. The
pilot's gradient threshold difference is an intentional-change candidate with
reviewed examples, not a blanket compatibility pass. Its current endpoint
interpolation across triangles still needs source/boundary-paint tests and
stability under refinement, camera changes, and diagonal changes before it
defines production paint behavior.

Both native GL and WebGPU contain the `0.95` fill-alpha adjustment and `1.06`
composite multiplier. For one uniformly covered region their idealized product
is `1.007`; repeated winding changes opacity further. The current direct
stroke/triangulated-fill blend also multiplies output alpha by source alpha,
producing alpha `0.25` for styled opacity `0.5` over transparency. Record these
as known defects separately from geometry fidelity. Correct alpha blending and
straight-alpha PNG conversion are separate, explicitly tested changes.

Capture both native GL and current WebGPU goldens as historical appearance
evidence. Neither is a defect-free semantic oracle. Independent coverage,
paint, and RGBA tests establish intended behavior; current CE remains the public
API reference where applicable. Keep before/after crops for deliberate changes
and do not broadly relax thresholds to conceal other regressions.

## 5. Rendering contracts

### 5.1 Ordered draw stream and depth

Represent each visible operation explicitly: fill, stroke, image, surface,
or another supported primitive. Each operation references geometry, material,
camera state, clipping, and depth policy. Preserve the authored sequence before
considering batching.

For painter-mode objects:

- Depth comparison is disabled, or `always`; depth writes are disabled.
- Emit `fill(A), stroke(A), fill(B), stroke(B)` in the required sequence,
  reversing an object's pair when `stroke_behind` requires it.
- Keep ordinary alpha blending. Do not encode `z_index` as a physical z offset.
- Merge only adjacent compatible operations, or prove that another merge
  preserves the result. One output pass may contain many pipeline switches.

For depth-tested objects, preserve the existing opaque depth policy and camera
mapping. Transparent 3D needs its own explicit contract: depth testing with
back-to-front drawing and no depth writes is a common policy, but object sorting
alone does not solve intersecting transparent surfaces. This proposal does not
claim to add general order-independent 3D transparency. Record any deliberate
change from current 3D alpha behavior separately and test it.

Mixed 2D/3D scenes retain their operation order and depth state per operation.
Do not globally move all 2D objects to the end. Do not clear depth when switching
to a painter operation. Reset viewport/scissor where needed before subsequent
draws. Fixed-frame content keeps its existing semantics.

Share output passes wherever attachment state permits. Clear the output once
per frame and avoid resolving MSAA once per small object. Genuine attachment
changes or isolated effects may still require a pass boundary.

### 5.2 Paint ownership and alpha

Source styles retain their public representation. Internally use one documented
premultiplied-alpha contract for output blending: evaluate a straight color and
opacity, apply coverage, then premultiply once. Texture decoding and final
presentation must explicitly match that contract; never mix conventions
implicitly. Preserve the current color-space behavior during this migration.
The existing stroke, surface, and dot shaders emit straight RGBA paired with
source-alpha blending. Reuse their geometry logic, but adapt each fragment
output and blend state together to the chosen contract, including image and
texture sampling. Keeping their current output pairing unchanged would not
implement this specification.

A single fill's interior triangles must have non-overlapping sample ownership,
apart from shared edges with consistent rasterization. Boundary coverage must
not double-darken shared edges or apply opacity twice. Distinct objects still
blend over each other normally.

Fill and fill-border form one coverage operation under the existing semantics.
Possible implementations include a non-overlapping expanded mesh with boundary
coverage attributes, or another shared-backend coverage technique validated
against the reference. Ordinary fill plus a separately alpha-blended border is
not an acceptable shortcut. This is an early feasibility gate.

Use a wide fill border on a translucent fill over a contrasting background,
plus overlapping differently colored objects, to expose the coverage-combination
behavior. Compare border/interior crops and explicit RGBA probes, not only the
whole-frame mean: omitting a narrow ring can pass a permissive global threshold.

Strokes can retain the existing shader during unification. If later replaced,
the replacement must define ownership at joins, caps, and self-overlap; a naive
strip can cover a translucent region multiple times. Match the current declared
behavior first and document any separate correction.

### 5.3 Geometric accuracy and coordinate space

Start the prototype with a maximum curve-flattening deviation of **0.25 output
pixels**, measured after the effective camera transform. This is a proposed
quality setting, not an established equivalent of the current renderer.
Measure at tighter tolerance if the fidelity corpus requires it. Specify a
bounded subdivision policy and report failure if the budget cannot meet the
tolerance; never silently clamp away visible detail.

Use a common output-pixel budget with a per-object conversion to local
tessellation coordinates. Bound projection over the source/control hull,
including perspective variation along tilted curves; object-center distance or
one global world-space tolerance is insufficient. Charge plane-fitting
displacement against the budget before allocating flattening error. Numerical
classification, float32 conversion, AA, and clipping are separate quality
obligations. Reject unsupported singular/near-plane cases explicitly.

Planar 3D fills should triangulate in a suitable local plane and reconstruct
their original 3D positions. The existing world-xy projection is insufficient
for arbitrary rotations. Painter fills with nonplanar source coordinates may
need projected-contour tessellation to preserve the current visible interior;
clipping and source-attribute evaluation must remain consistent. The reference
corpus determines these cases before choosing the production generator.

For per-point gradients, source-edge interpolation is useful for new boundary
vertices but does not alone define a stable interior field. Establish the
source paint semantics and a stable continuous paint representation during
feasibility. The known fan seam is not a parity requirement. A topology change
or quality refinement must not introduce a new visible color seam; boundary
and source-point colors alone do not establish the whole interior contract.

## 6. Geometry and resource specification

Separate source data, generated data, and drawing instructions.

| Resource | Contents and ownership |
|---|---|
| Source path | Control points, contour boundaries, open/closed state, fill rule, source attribute references; authoritative for Manim operations. |
| Source surface | Vertex/topology or parametric-source data for an actual mesh; do not reinterpret it as a filled outline. |
| Style | Fill/stroke paint, widths, border properties, shading, clipping and other material inputs. |
| Generated geometry | Mesh vertices, indices, boundary/coverage data, normals or source references, bounds, actual output counts. Disposable derived data. |
| Draw item | Resource handles/ranges, material, ordered position, camera/depth mode, and direct or indirect draw arguments. |

The source adapter must explicitly select the current nonzero-style fill
coverage rule; never inherit a tessellator's default. Validate repeated contours
with matching and opposing directions against the existing renderer. If an
explicit even-odd mode is added, it must be represented and tested separately.

Do not freeze the old 68-byte VMobject shader row as the new universal format.
Preserve it through an adapter while defining a versioned generated-mesh layout.
The initial fill layout can extend the existing surface representation; images
and dot clouds can keep their specialized formats.

Each generated resource must carry:

- Source identity and evaluated revision, plus style and relevant quality dependencies.
- Generator identity/version, quality tolerance, and output-layout version.
- Vertex/index buffer handles, capacities, actual counts, and topology identity.
- A frame/evaluation stamp that prevents mixing one revision's indices with
  another revision's vertex positions.
- Success, empty, or explicit failure/overflow status.

Index content is part of identity. The audited serializer omitted `index_bytes`;
the A0 correction now hashes `raw + tri_bytes + index_bytes` and has an index-only
wire-mutation regression. The generated-resource contract must cover all three,
or use trusted versioned identities that change when any part changes.

Cache invalidation follows dependencies, not just an object's broad revision:

- Geometry changes can invalidate positions and connectivity.
- Width, border, join, and partial-path changes can invalidate geometry.
- Camera, zoom, resolution, and projection can invalidate flattening or
  screen-space stroke geometry even when source points are unchanged.
- Paint-only changes should not rebuild connectivity when the material permits.
- Affine motion can preserve fill connectivity. Mesh quality may still need
  refinement after enlargement; screen-space stroke widths need separate care.

For camera-only changes, recompute the required projection bound and reuse the
mesh whenever its stored local error plus current projected plane residual
meets the pixel budget. A camera revision by itself is not a rebuild command.
Refinement must complete before drawing an under-resolved frame. Quality
headroom can avoid rebuilding on every small zoom step; zooming out may retain
a finer mesh within the memory budget rather than continually coarsening it.

The optional A0 `TriangleMeshCache` implements this conservative policy with
half-budget refinement headroom, exact source/contour/paint/normal snapshots,
generator identity, immutable cached arrays, and pruning of absent fills. Its
default retained-array limit is 64 MiB with at most 2,048 entries. These are
prototype settings, not production defaults. Hits still scan source bytes and
calculate projection bounds when their actual inputs change; unchanged-camera
bounds are memoized after source checks. Hits are not constant-time. The limit includes
source snapshots and plane metadata but excludes temporary tessellation,
returned old frames, and GPU storage. Measure those costs separately. Its
focused tests establish cache behavior, not native/browser frame pacing.

Uniform color/opacity changes now refresh immutable interleaved vertex colors
without rebuilding connectivity. Arbitrary per-point diagnostic paint still
regenerates; its separate material representation remains unfinished. Do not
replace actual-content validation with broad `Mobject.revision` alone while
untracked public array writes remain supported. The real-text motion corpus
includes 4× zoom beyond the 2× headroom, an isolated fixed-point opacity control,
and production Write, whose interpolation can change point bytes by rounding.

Retain buffers by capacity and update dirty ranges. Reuse uniform/binding
resources through bounded arenas respecting device alignment. Do not allocate
new GPU buffers and bind groups for every small draw.

## 7. Phase A: shared drawing with CPU fill generation

### A0 — Prove the representation and choose reusable code

*Reviewer note: see "Proposed changes to A0" at the top of this document for suggested amendments to this milestone. Not yet adopted by the author.*

**Author update — selected review improvements adopted here:** A0 is started
and incomplete. The preceding reviewer note remains verbatim as a historical note;
its proposed amendments are now reflected in this milestone.

**First quality deliverable: text and hairline antialiasing.** Capture native GL
and current WebGPU reference frames for a paragraph of small TeX, small text,
thin strokes, tiny holes, and fractional translations at normal and zoomed
views. Compare flattened meshes with 4× MSAA, analytic patches with a specified
coverage/AA method, and a target doubled in both dimensions with a defined
resolve/downsampling filter. Keep output dimensions, backgrounds, paint, and
color space fixed; scale pixel-dependent stroke/AA uniforms consistently in
the supersampled case. Report its extra target memory and resolve cost. Apply
existing thresholds, local crops, explicit semantic probes, and temporal
inspection before accepting the quality treatment. The analytic treatment is a
bounded candidate: document feasibility and exclusions rather than building a second
general renderer merely to complete a comparison. No AA treatment is currently
accepted by this document.

Build on the renderer-independent source fixtures and add the complete hard
corpus in section 10. Capture both native GL and current WebGPU goldens before
retirement. Preserve geometric/alpha/paint tests independently of either
renderer, and strengthen the translucent contrasting-border case specified in
section 5.2. Record the gradient seam correction separately; do not chase old
fan parity or use that correction to waive border, alpha, or material failures.

**Four-way renderer comparison:**

1. Current bounded winding output, as the fresh baseline.
2. Prepared winding fills with shared ordered output, keeping current geometry.
3. Full flattened meshes with shared ordered output.
4. Correctly partitioned interior triangles plus analytic boundary patches with
   shared ordered output.

Report unsupported fixtures explicitly for each candidate. Do not quietly
route them to the current renderer and present the result as a general mesh
success. Analytic construction must satisfy section 2's ownership rule. The
ordered-output control must disclose its separate temporary images and memory;
it is not an implemented atlas. Compare drawing alone and complete frame cost,
including CPU source evaluation, tessellation, preparation, uploads, and
completion, on identical source/style/camera frames.

**Generator decision and Rust criterion.** Start the comparison with the
existing `mapbox_earcut` dependency and retain the isolated Lyon prototype as
an experimental control behind the same source-to-geometry interface. Do not
promote the existing fixed sampling, flat-color conversion, or center-fan
fallback into the required behavior. Earcut handles suitable polygonal rings
but does not establish general intersecting-path semantics. It must be tested
against independent coverage, not only triangle counts or total area.
[Earcut robustness contract](https://github.com/mapbox/earcut#robustness)

The primary correctness question deciding whether extra Rust packaging is
justified is whether a required, reproducible corpus case—including intermediate
Transform/Write/morph frames—fails the Earcut path's coverage/topology semantics
while Lyon passes that same case. Record the minimized source, expected
coverage, both outputs, and timing. A successful Lyon result is evidence for
adding that dependency, not automatic adoption: it must also satisfy paint,
alpha, borders, AA, performance, and memory requirements. Conversely, avoiding
Rust is not an architectural goal; a different measured simplicity/performance
advantage can support adoption if its packaging tradeoff is explicit. Do not
weaken the general-renderer corpus to make a simpler generator pass. If Earcut
covers the required inputs and meets the
other gates, prefer the already-shipped dependency over a new owned extension.

Before any Rust adoption, document artifact size, licenses, wheel/build and
maintenance requirements across the supported OS/architecture/Python matrix,
and the browser-resident CPU/WASM route. The present `ctypes` helper avoids a
Python-specific ABI binding but still needs native binary distribution. Check
WASM portability independently; it is not implied by WebGPU rendering or a
successful macOS native build. A0 can choose a dependency only with these costs
and its demonstrated benefit made explicit.
[Lyon fill API](https://docs.rs/lyon_tessellation/1.0.22/lyon_tessellation/struct.FillTessellator.html)

**Camera and animation sequences.** Exercise per-submobject caching during a
real long-TeX Write and Transform, including simultaneous camera motion. Use
the section 6 quality policy and the section 10 zoom matrix. Count only changed
or insufficient-quality objects as regenerations; report cache hits, generated
and uploaded bytes, retained/peak memory, and complete frame-time tails. A
static warmed draw is not evidence of smooth zoom or animated-frame benefit.

**Exit:** select a representation using the text/hairline quality result,
reproducible renderer/generator comparisons (including explicit feasibility
limits for unselected candidates), and measured packaging/memory costs. The
selected route must demonstrate required coverage, paint, borders, alpha,
material, and camera behavior; CPU generation belongs in its performance
decision against ordered output. Analytic patches and Rust avoidance are not
mandatory parts of the final architecture. Unresolved required behavior in the
selected route keeps A0 incomplete. If ordered output wins, report it and revise
the implementation or make an explicit quantified maintenance/performance decision.
An unproven Phase B gain cannot automatically waive a Phase A regression.

### A1 — Introduce generated geometry and shared ordered output

Implement the resource contract and both WebGPU drivers. Painter fills use the
non-depth surface/material path rather than the current forced-depth 3D branch.
Reuse existing direct strokes and other primitive geometry, adapting their
output/blend pairs as specified in section 5.2. Serialize explicit ordered
operations so batching does not rearrange fill/stroke relationships.

Use persistent resource capacity and shared output passes. Include all topology
in cache identity. Version the wire format and update the baked player/export
metadata together; incompatible old exports should follow the existing
re-export behavior rather than silently draw incorrectly.

**Exit:** CPU-produced geometry renders through the same WGSL in native WebGPU
and the browser, with correct order, clipping, mixed-depth behavior, and bounded
resource use. The old winding path is a temporary comparison implementation.

### A2 — Complete compatibility and demonstrate total-frame benefit

Resolve the section 4 matrix and run representative course scenes. Profile
static meshes, affine motion, changing curves, and topology changes separately.
Retessellating every object every frame is not an acceptable hidden replacement
for the old render-pass cost. Reuse correct meshes and measure all generation,
upload, and command work.

Keep Python-visible control points unchanged. Validate checkpoint navigation,
live updates, geometry export, native rendering, and text/TeX outlines. The
renderer consumes existing glyph outlines; it does not replace text shaping or
TeX layout.

**Exit:** all required behaviors pass; agreed performance and memory targets
are met; remaining known defects are distinguished from migration regressions.

### A3 — Cut over all outputs and retire winding

Complete the native-GL-to-WebGPU cutover in coordination with the existing
roadmap, so interactive, offline, and exported output use the shared backend.
The existing user hold on native GL removal is not lifted by this document.
Planning and a shadow implementation can proceed; final runtime retirement
depends on that cutover's authorization and readiness.

After acceptance, remove the separate winding implementation and temporary
selector. Preserve golden frames and independent geometric tests rather than
a permanent second production renderer. CPU generation fallback, where needed
later, still feeds the **same** triangle renderer.

## 8. Phase B interface: GPU evaluation and generation

The [GPU geometry-generation research specification](docs_gpu_geometry_generation_plan.md)
owns algorithm selection, dependent compute stages, variable output counts,
bounded allocation and recovery, checkpoint/read semantics, and research gates.
Phase A stands on its current benefits and does not depend on completing B.

The shared contract remains strict: source arrays are authoritative; generated
vertices, indices, material dependencies, counts, and draw arguments describe
the same valid evaluation. GPU source updates must be paired with the geometry
generation they require. An affine transform can preserve proven connectivity;
general morphs and partial paths cannot assume it. An incomplete generation
must never publish stale indices or a partial scene as a completed frame.

## 9. Relationship to the existing roadmap

The native-GL cutover and read-instrumentation prerequisites remain. Shadow
research can proceed; this plan does not lift the user hold on runtime native
GL retirement or authorize production GPU instruction execution ahead of its
prerequisites. The [separate GPU specification](docs_gpu_geometry_generation_plan.md)
records the amendments to engine shadowing, ownership, updaters, playback,
retention, and fresh reads.

## 10. Validation and performance acceptance

### Required fidelity corpus

Reuse the visual cases in
[test_fill_bounds.py](tests/test_fill_bounds.py)
and [test_wgpu_port.py](tests/test_wgpu_port.py),
moving their scene construction into renderer-independent fixtures. Add:

- B0 touching outlined squares, separated squares, and stroke-only controls.
- Glyphs with holes, nested/reversed contours, bow-ties, coincident edges,
  repeated points, tiny contours, and contour disappearance. Include a contour
  traced twice in the same direction to distinguish nonzero from even-odd,
  and near-parallel/near-coincident edges at different coordinate scales.
- The convex-to-concave quad through and around its diagonal-flip frame.
- Thin curves/text at multiple zooms and resolutions; wide fill borders;
  varying RGBA; sharp joints; tapered strokes; partial Creation/Write frames.
- A wide border on translucent fill over a contrasting background, with
  differently colored overlaps; inspect border/interior crops and RGBA probes.
- Distinct translucent overlapping objects and overlap within one paint
  operation, on both opaque and transparent backgrounds.
- Rotated planar fills, camera tilt, near-plane crossings, clipping, fixed-frame
  overlays, and existing depth-intersecting surface cases.
- Images, textured surfaces, dot clouds, `stroke_behind`, and mixed pipelines.
- Geometry-only, index-only, style-only, and camera-only cache invalidation.
- Checkpoint restore, export/playback, backward scrubbing, and device/resource
  recreation; forced budget overflow and recovery.

Use existing image thresholds as the initial gate. Do not broadly relax them to
make a replacement pass. Record deliberate visual changes individually and
compare the relevant CE behavior. Add RGBA tests because opaque RGB comparisons
cannot establish correct transparent output. GPU and CPU generators need not
produce identical index ordering; validate coverage, topology invariants, styles,
and resulting images, plus deterministic output where the algorithm promises it.

The reviewed gradient seam improvement follows section 4's explicit disposition.
Keep its historical image difference visible in results while testing the
new continuous field's source/boundary paint and camera/refinement/diagonal
stability. The pilot is not evidence that those requirements already pass.

### Required camera and zoom matrix

| Sequence | Required evidence |
|---|---|
| Fixed 2D paths, continuous zoom in and out | Local edge/text quality, frame-time tails, regeneration counts, upload bytes, and no visible refinement jumps. |
| Camera-only pan, rotation, and output-resolution changes | Reuse while the current projected error bound permits it; refinement before more detail is needed. |
| Identical curves at different depths and tilted planar paths | Per-object perspective quality, fill/stroke alignment, and explicit clipping/near-plane outcomes. |
| Small text becoming large, then small again | Readable edges/holes, quality-preserving reuse, bounded retained meshes, and complete-sequence memory. |
| Long-TeX Transform or Write while the camera moves | Combined source/style/camera invalidation, only affected glyphs regenerated, and complete frame latency. |

Run the matrix against all four renderer variants. The existing stroke shader's
frame-scale subdivision is useful reuse, but its 32-step cap and heuristic do
not constitute a perspective pixel-error proof. Test fill/stroke alignment
rather than treating either old pipeline as an infallible geometric reference.

### Performance protocol

Measure the same scenes, output size, sample count, camera, and animation frames
across the current winding baseline, ordered-output-only control, flattened
meshes, and analytic-patch meshes. Alternate warmed implementations. Report medians and
tail frame times, not only the best frame. Include:

- Python point evaluation, CPU mesh generation, serialization, and upload bytes.
- CPU command preparation and GPU geometry-generation time.
- Drawing time, submission/completion latency, pass/draw counts, and viewer
  presentation latency. Keep readback and offline encoding costs identifiable.
- Retained and peak memory, resource creation, overflow/retry frequency, and
  rebuild/cache-hit counts.

Proposed Phase A target: at least **2× lower combined command-preparation and
submission/completion time** on B0, with CPU tessellation reported and included
in the total-frame comparison. Also require an end-to-end win against the
ordered-output-only control on agreed representative workloads, or an explicit
quantified decision accepting the tradeoff for demonstrated maintenance/current
benefits. Future GPU work is not an automatic regression waiver. No repeatable
total-frame regression greater
than both **10% and 0.5 ms** on the agreed control corpus without a documented
reason and a revised decision. These are engineering gates to test, not results.

For a compatible flat B0 scene, aim for one clear/output render pass containing
its ordered draws, plus the browser's final presentation step. Do not require
one draw call or the historical 135 logical batches. If the selected boundary
technique needs extra passes, expose and benchmark them rather than disguising
them as “one batch.”

GPU-specific acceptance and memory/recovery tests live in the
[Phase B specification](docs_gpu_geometry_generation_plan.md#4-feasibility-and-acceptance).
The shared fidelity and source/generated coherency requirements apply to both
CPU and GPU generators.

## 11. Retirement and code organization

After acceptance and the offline cutover, remove the winding-only mechanisms:

- `fill.wgsl` and `composite.wgsl`, their pipeline/layout/blend definitions.
- Winding scratch textures and pools, fill-rectangle calculations, atlas plans
  in active scheduling, and obsolete `fill_rect`/`fill_mode` protocol branches.
- Border-only shader branches after replacing their visible behavior.
- Winding-specific batch hazards and tests whose only purpose is preserving the
  old implementation structure. Keep the ordering tests they protected.
- Superseded triangulation helpers/fallbacks once the new generator owns those
  cases, and native GL as part of its coordinated retirement.

Keep public style properties, source point APIs, specialized direct primitives,
and the independent reference corpus. Old exported wire formats follow the
existing explicit version/re-export policy.

Organize code around source evaluation, geometry generation, resource lifetime,
and ordered drawing. Avoid a separate complete renderer for each primitive,
each CPU/GPU generator, or each host. CPU and GPU generators share an output
contract; JavaScript and Python hosts share WGSL and generated layout/schema
definitions. A geometry-generation fallback is not a second renderer.

The net code reduction is a hypothesis until both added and removed code are
counted. Moving complexity into a maintained dependency can reduce our
maintenance burden even when the total executable becomes larger. Report both
source ownership and distribution size when selecting a dependency.

## 12. Work estimates and decision points

These are provisional engineering-effort ranges, not elapsed-time commitments.

| Milestone | Initial planning range | What narrows the estimate |
|---|---|---|
| A0 measured compatibility prototype | Initial 3–5 focused days; re-estimate after the expanded comparison | Text/hairline AA, analytic construction, borders/paint/alpha, zoom, and generator packaging. |
| Dependable CPU-generated shared backend and cutover work | Roughly 4–8 focused weeks overall | Scope of appearance differences, both-host integration, and readiness of the held offline cutover. |

These Phase A ranges are provisional and need reassessment after the expanded
A0 comparison. GPU feasibility estimates and algorithm uncertainty are tracked
in the [separate Phase B specification](docs_gpu_geometry_generation_plan.md#5-decision-points-and-estimates).

At each decision point, compare the shared-backend approach with adopting a
complete 2D engine. The preferred direction remains one triangle backend. If
the compatibility or performance evidence rejects the proposed implementation,
revise it with that evidence rather than silently retaining two production
renderers or weakening supported behavior.

## 13. Research notes and primary references

These sources establish reusable components and implementation ideas. None is
a benchmark of ManimLive or proof that a library is a drop-in replacement.

- [Lyon fill API](https://docs.rs/lyon_tessellation/1.0.22/lyon_tessellation/struct.FillTessellator.html)
  provides CPU fill tessellation and generated attributes. The application still
  owns rendering and AA. Its [stroke contract](https://docs.rs/lyon_tessellation/latest/lyon_tessellation/struct.StrokeTessellator.html)
  permits overlapping triangles, so adopting stroke output would need a separate
  translucent-coverage decision. The current experiment uses fills only.
- [Earcut robustness](https://github.com/mapbox/earcut#robustness) states the
  limits of its polygon triangulation. Use the existing dependency as a measured
  control; do not assume arbitrary self-crossing paths preserve required coverage.
- [Loop–Blinn, §3.1](https://www.microsoft.com/en-us/research/wp-content/uploads/2005/01/p1000-loop.pdf)
  describes the interior/control-triangle construction and subdivision needed for
  analytic boundary patches. The simple-path assumptions are not unrestricted
  self-intersection support.
- [GPU Gems vector art, §§25.2 and 25.5](https://developer.nvidia.com/gpugems/gpugems3/part-iv-image-effects/chapter-25-rendering-vector-art-gpu)
  explains analytic coverage, perspective, and boundary AA limitations. An
  implicit inside test alone does not settle edge quality.
- [WebGPU multisampling](https://gpuweb.github.io/gpuweb/#multisample-state) and
  [WGSL interpolation](https://gpuweb.github.io/gpuweb/wgsl/#interpolation)
  define the sample/shading contract. Compare observed text quality instead of
  ranking 4× MSAA and supersampling by sample count alone.
- [Skia / CanvasKit](https://skia.org/docs/user/modules/canvaskit/) and
  [ThorVG WebCanvas](https://www.thorvg.org/web-tutorial) are complete-engine
  alternatives if component integration proves worse. They are comparison or
  adoption choices, not assumed triangle-generator drop-ins.

GPU topology algorithms, indirect draws, Vello memory and flattening references,
stroke-expansion research, and MathBox source-evaluation precedents are collected
in the [Phase B research specification](docs_gpu_geometry_generation_plan.md#6-research-references).

### Relationship to existing documents

The `../simlab/` links below are workspace-only sibling documents; repository
links above are relative and portable within this checkout.

- [GPU architecture](../simlab/ARCHITECTURE.md)
  retains the source-operation/clock idea, amended by this generated-geometry contract.
- [Instruction-stream sequence](../simlab/INSTRUCTION_STREAM_PLAN.md)
  gains the geometry-generation and correctness milestones described above.
- [Earlier atlas proposal](docs_ordered_fill_atlas_plan.md)
  is superseded as the selected direction; its measurements remain evidence.

A0 implementation now exists in opt-in benchmark modules and focused tests;
this document is not a claim of renderer cutover. The compatibility and
measurement gates above must finish before retiring the existing path.

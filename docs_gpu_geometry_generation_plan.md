# GPU source evaluation and geometry generation

Phase B research specification — 2026-09-09.

Status: research and feasibility plan; general GPU fill generation is not
implemented. This document separates Phase B's algorithm, allocation, and
playback work from the [shared renderer plan](docs_unified_triangle_renderer_plan.md).
Phase A must justify its CPU-generated backend on present quality, performance,
and maintenance benefits even if Phase B never ships.

This separation is organizational: the approved objective remains moving both
source updates and the geometry generation they require to the GPU. It does
not replace that objective with a CPU-only endpoint or make stale topology an
acceptable shortcut. Algorithm selection and feasibility remain honest research
work on the path to that objective.

## 1. Scope and shared contract

Move declared source-point/style operations and their required mesh generation
together. Keep Manim's source control arrays authoritative and generated meshes
derived. CPU and GPU generators target the same ordered renderer, materials,
layout versions, and coverage contract. Retaining the same number of source
points does not prove that the previous triangle connectivity is valid.

Every generated resource names its evaluated source/style/quality dependencies,
generator and layout versions, actual counts, capacities, topology identity,
and success/empty/failure status. Vertices, indices, material inputs, and draw
arguments must describe the same evaluation before publication. CPU and GPU
paths must never mix a new vertex buffer with old invalid connectivity.

Phase A compares full flattening with ordinary interior triangles plus analytic
boundary patches. Either accepted representation may feed this research:
analytic boundaries can avoid zoom-only flattening, but changing paths may still
invalidate their interior/patch decomposition. Selecting the inside of a patch
is a coverage test; do not subtract alpha from already-painted scene pixels.
GPU flattening by itself is not proof of a one-pass general fill generator.

## 2. Evaluation and geometry algorithms

### 2.1 The changed architectural boundary

The earlier instruction-stream design made `map` and `reduce` the only GPU
operations, kept all triangulation on the CPU, and permitted stale 3D triangles
during a morph. Those rules are superseded for this direction.

Keep maps for point/style evaluation and reductions for derived values. Add a
**geometry-generation stage with variable output counts**. It consumes the
current evaluated path and produces a coherent mesh and draw counts. A path
with the same number of control points can require different connectivity or
more generated vertices after deformation.

Example: the quad `A=(0,0), B=(4,0), C=(4,4), D=(0,4)` can initially use
triangles `ABC` and `ACD`. Moving B to `(1,3)` makes those ordinary triangles
overfill the intended path. A correct mesh can instead use `ABD` and `BCD`.
Updating positions alone cannot fix that connection change.

### 2.2 Required evaluation order

```text
clock and scalar inputs
        ↓
evaluate source-point/style operations
        ↓
dependency reductions and derived path data
        ↓
generate geometry: classify/count → allocate ranges → emit
        ↓
validate counts, bounds, and resource generation
        ↓
write indirect drawing arguments
        ↓
execute the ordered draw stream
```

This is a dependency graph, not a requirement that every object executes every
stage every frame. Reductions needed by another point operation run before that
operation. Unchanged dependencies reuse generated results. Schedule dependent
compute work before rendering without a CPU wait between stages.

The CPU can retain the ordered operation list and encode a bounded set of draws.
The GPU supplies changing vertex/index counts through indirect arguments, so the
CPU need not read them back to draw. WebGPU's indexed indirect drawing supports
reading these arguments from a buffer; it does not itself generate or validate
the mesh. [Indirect drawing API](https://gpuweb.github.io/types/interfaces/GPURenderCommandsMixin.html#drawIndexedIndirect)

### 2.3 Generation work and research gate

Implement simple proven cases first: affine transformations of valid fill
meshes, regular parametric surfaces, existing stroke generation, and adaptive
curve evaluation. Preserve the source path separately from the sampled mesh.
A nonlinear operation on sampled mesh vertices is not generally equivalent to
applying that operation to Bézier control points and then evaluating the curve.

**Bounded first candidate after the sixth review (2026-09-10): general GPU
fill-border expansion.** This is planned, not implemented. Keep retained fill
meshes separate from expanded curve-source buffers and perform border
subdivision/expansion on the GPU. Initially the CPU still updates source
points; later GPU source evaluation can feed the same generator. Zoom-only
border changes should update uniforms without uploading replacement border
or unchanged fill geometry. Genuine fill-quality refinements remain separate.
Preserve operation order, opacity/paint coverage, fixed-frame/camera-facing
behavior and depth, and measure opaque batching as well as upload reduction.
The [sixth-round response](docs_unified_triangle_renderer_review_response.md#gpu-borders-a-reusable-first-step-within-phase-b)
records comparison fixtures, transport measurements and the need to validate
against the CPU emitter. Border expansion alone does not solve general fill
topology or complete Phase B.

General fills need a correct topology pipeline. The initial research candidate
is adaptive path flattening, intersection discovery/splitting, fill-rule
classification, decomposition into non-overlapping regions, and triangle
emission. Compare a planar-arrangement/face approach with a scanline/trapezoid
approach on the fixture corpus. This is an algorithm selection task; a complete
portable WGSL implementation has **not** been identified by this research.

GPU curve or stroke tessellation alone is not the whole solution. Subdividing
existing triangles also does not solve an arbitrary filled path's holes and
self-intersections. Reusable implementations must be checked for the exact
output and correctness guarantees needed here.

Define numerical classification as part of the generator contract: intersection
predicates, treatment of coincident/near-coincident edges, scale-dependent
tolerances, and any snapping. CPU float64 and GPU float32 can disagree about
topology despite meeting the same curve-flattening tolerance. Use compatible
classification rules or a documented robust recovery path; test near-parallel
and near-coincident cases at several coordinate scales.

Some GPU path engines draw overlapping helper triangles and then use stencil
or coverage passes to determine the filled region. That is a different output
contract from an ordinary non-overlapping interior mesh. Such techniques may
be evaluated if needed, but their extra passes and interaction with depth and
alpha must be specified and benchmarked. They are not evidence that the mesh
generator described here already exists. Skia's curve/wedge design illustrates
this distinction. [Skia path tessellator](https://github.com/google/skia/blob/main/src/gpu/ganesh/tessellate/PathTessellator.h)

An invertible affine operation can preserve connectivity by construction. General blends,
partial paths, and nonlinear maps take the regeneration path unless reuse is
proved valid. Do not rely on unchanged array length, a checksum of positions,
or a heuristic “probably convex” flag as that proof.

### 2.4 Variable output counts and bounded memory

Use count/scan/emit or another explicitly bounded scheme. Generated vertex,
index, intersection, and scratch buffers have declared capacities. Query actual
device limits; do not assume a vendor-specific hardware tessellation stage or
unbounded GPU allocation.

Each emission checks capacity before writing. A GPU completion/status record
reports actual counts and overflow. An incomplete result is never published as
a valid mesh or drawn with stale indices. Set invalid indirect counts to zero.

The common case must not synchronously read counts or point arrays to the CPU.
Use retained capacity, GPU suballocation within those capacities, and measured
headroom. Overflow is an exceptional path: report it, allocate within a declared
budget, and retry or run the CPU generator for that evaluation. Offline output
must finish the requested frame or report failure. An interactive viewer may
retain its last complete frame while recovery occurs; it must not claim the new
frame is complete.
Aggregate validity across the frame before presentation: zeroing an object's
draw count protects memory, but presenting the remaining objects would still
be an incorrect partial scene. Select a complete output or hold the previous
one during recovery, and include that retained output's lifetime and memory
in the budget.

For the feasibility prototype, start with a **128 MiB transient generation
budget** and report source, retained mesh, in-flight, and scratch bytes separately.
This is a provisional test setting, not a promised production requirement.
Publish a budget/quality/scene-size sweep before fixing production defaults.
Cap simultaneously retained arenas and retire resources only after their
submissions complete. Host memory backing and GPU allocation are separate
budgets.

Worst-case intersecting paths can produce much more geometry than their input
point count suggests. Exhaustion must have a defined outcome; silent geometry
truncation and an unbounded resize loop are prohibited.

### 2.5 Migration within the GPU phase

1. Establish shared source/generated resource handles and count-safe generation
   plumbing in both hosts.
2. Run GPU point evaluation in shadow against CPU results. Reuse connectivity
   for affine cases and move bounded generators onto the GPU.
3. Demonstrate general changing-path fill generation on the hard fixtures,
   including connectivity changes, before claiming general GPU morph support.
4. Flip supported playback to GPU-owned evaluated sources and generated meshes.
   Move the clock, reductions, checkpoints, and supported updaters with it.
5. Expand the supported generator/operation set with explicit capability tests.

During migration, a difficult animation can stay entirely on the CPU for source
evaluation and mesh generation, then upload its mesh to the shared renderer.
Avoid the normal-path design `GPU points → CPU readback → CPU tessellation →
GPU upload`. That round trip is an exceptional fallback, not the target engine.

The final target moves point updates and triangle regeneration for all declared
GPU-supported path animations. CPU fallback is not evidence that this milestone
is complete. Arbitrary Python callbacks, asset decoding, and text/TeX shaping
remain separately scoped host work unless explicitly ported; this proposal does
not promise to compile all Python onto the GPU.

### 2.6 Checkpoints, reads, and playback

Checkpoint source resources, operation/generation recipes, scalar state, and
draw ordering. Treat ordinary tessellation output as a regenerable cache rather
than retaining a new mesh for every historical frame.

Immutable logical outputs can use pooled physical buffers only when lifetimes
permit; a referenced result must not be overwritten. GPU-only source/state data
needs host backing or a deterministic reconstruction recipe before eviction.
It cannot simply be “refetched from Python” if Python never retained it.

Pure animation scrubbing evaluates points and generates a valid mesh at the
requested time. Triangle indices may differ from the previous frame; the image
must still be correct. Stateful simulations require saved state or deterministic
replay. Checkpoint metadata, retention, and reconstruction have costs even when
bulk array copies are removed.

Reductions returned to Python include evaluation/frame stamps. An asynchronous
center or bounding-box mirror cannot simultaneously promise no wait and the
result of an immediately preceding unevaluated mutation. Preserve eager API
semantics through an explicit fresh-read/evaluation path where necessary.

## 3. Roadmap prerequisites and migration


The existing native-GL cutover and read-instrumentation prerequisites remain.
Unification can be researched and implemented in shadow first. Production GPU
instruction execution starts only after the one-WebGPU-output prerequisite.

Amend the instruction-stream phases as follows:

| Earlier phase | Amendment |
|---|---|
| Engine core in shadow | Add generated resources, topology identity, count/capacity/status handling, and mesh generation dependencies. Validate source evaluation separately from generation and final pixels. |
| Flip the truth | Flip only combinations of operations and generators whose results are correct and do not depend on routine point readback. |
| Updaters | Trace source-point/style operations as before; route their evaluated outputs through the appropriate generator. Count-changing generation is not silently treated as a row-wise map. |
| Clock and reverse playback | Evaluate the mesh for the requested time; do not reuse stale connectivity during scrubbing. |
| Stateful operations | Extend retention/replay to authoritative GPU state and any generation dependencies. |

Replace the old “stale triangulation is acceptable” rule with: **vertices,
indices, and material dependencies must describe the same valid evaluation.**
If generation cannot produce that result, use the declared recovery path.

Also separate shadow-mode performance from production-mode performance. A phase
that intentionally runs Python as the oracle cannot claim that production
Python animation work has already disappeared.

## 4. Feasibility and acceptance

Reuse the shared plan's fidelity corpus, including intermediate morph frames,
contour appearance/disappearance, near-coincident intersections, and the
convex-to-concave diagonal flip. Add capacity exhaustion at every generation
stage, failed/retried evaluations, interrupted submissions, device recreation,
checkpoint restore, and scrub/replay tests. Validate source evaluation,
geometry coverage, styles, and final images independently; matching counts or
triangle ordering alone proves none of them.

Camera sequences include continuous zoom, perspective depth/tilt, rotation,
resolution changes, and simultaneous Transform/Write. Derive the local quality
requirement from an output-pixel error budget over each relevant control hull.
Cached meshes remain reusable while that bound holds. Test float32 geometric
classification separately from approximation and antialiasing error.

Acceptance requires zero normal per-frame point/mesh readback or uploads for
GPU-supported animations, coherent regenerated geometry through morphs, and a
measured total-frame improvement. Small scalar messages, explicit raw reads,
and exceptional recovery are reported separately. A cached rotating square
is a useful bounded case, not completion of general GPU path support.

Compare CPU generation, GPU generation, and any coverage-engine alternative
on identical source/style/camera frames. Report evaluation, classification,
count/scan/emit, allocation/overflow recovery, upload, draw, and completion costs,
plus frame-time tails. Disclose shadow-mode CPU work and readback barriers.
Report retained source/mesh, scratch, in-flight, retained last-complete output,
and host-backing memory separately. The provisional 128 MiB transient budget in
section 2.4 is a test setting; production defaults require a scene-size,
quality, and memory sweep.

## 5. Decision points and estimates

Time-box the first general-fill feasibility investigation to **2–4 focused
weeks**, then re-estimate from a working hard-path algorithm, bounded allocation,
recovery behavior, both-host feasibility, and measured costs. The earlier
point-map estimates do not include variable-count topology generation.

If no candidate satisfies the required coverage, memory, and total-frame gates,
keep supported source evaluation and generation together on the CPU and report
that Phase B remains incomplete. Do not weaken supported geometry, tolerate
stale connectivity, or justify a Phase A slowdown using an unproven future gain.
Any revised renderer/coverage contract must expose its extra passes, alpha,
depth, packaging, and maintenance costs before adoption.

## 6. Research references

These are implementation references, not ready-made general mesh generators or
benchmarks of ManimLive. References were checked during the 2026-09-09 review.

- [GPU-friendly Stroke Expansion](https://linebender.org/gpu-stroke-expansion-paper/)
  provides parallel stroke-outline generation and error-controlled
  approximation. Its line/arc output still needs the downstream fill contract.
- [Vello](https://github.com/linebender/vello) and its
  [flattening compute shader](https://github.com/linebender/vello/blob/main/vello_shaders/shader/flatten.wgsl)
  provide general vector-processing references. Flattening emits segments for
  coverage processing, not this renderer's finished non-overlapping interior.
- [Vello dynamic-memory discussion](https://raphlinus.github.io/gpu/2025/03/21/good-parallel-computer.html)
  motivates explicit capacities, overflow status, retained headroom, and recovery
  instead of assuming unbounded GPU allocation.
- [Skia's path tessellator](https://github.com/google/skia/blob/main/src/gpu/ganesh/tessellate/PathTessellator.h)
  and [Wang's formula](https://github.com/google/skia/blob/main/src/gpu/tessellate/WangsFormula.h)
  are subdivision/coverage references; stencil wedges are a distinct output
  contract from an ordinary alpha-blended interior mesh.
- [WebGPU indexed indirect drawing](https://gpuweb.github.io/gpuweb/#dom-gpurendercommandsmixin-drawindexedindirect)
  provides GPU-controlled counts without normal CPU count readback. It does not
  generate or validate topology and does not remove buffer bounds/alignment rules.
- [MathBox shader operators](https://github.com/unconed/mathbox/blob/master/docs/shaders.md)
  and [memoized operators](https://github.com/unconed/mathbox/blob/master/src/primitives/types/operator/memo.js)
  are references for fused source evaluation and selective intermediate storage;
  they do not supply general filled-path triangulation.

The workspace-only [GPU architecture](../simlab/ARCHITECTURE.md) and
[instruction-stream sequence](../simlab/INSTRUCTION_STREAM_PLAN.md) retain the
source-operation/clock model with the coherent generated-resource contract above.

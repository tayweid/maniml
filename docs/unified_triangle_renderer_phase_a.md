# Phase A cutover and dogfood comparison

Phase A cutover, 2026-09-10. This record accompanies the default-renderer
integration and preserves its measured tradeoffs for dogfooding.

## Scope and authorization

The requested outcome is Phase A as the default renderer on main. Native
movie and checkpoint output uses the same WebGPU backend as the browser.
Taylor requires a selectable **Original 2D** renderer in the viewer for
dogfooding. My earlier interpretation that this explicitly authorized native
GL removal was too broad. The sixth review relays the clarified direction:
native GL must also remain packaged as a runnable reference while **Phase A**
stays the default. Switching browser renderers must preserve the scene,
source arrays, camera and current checkpoint and resend complete data.

The original browser winding renderer and its serializer therefore remain
packaged as an explicit comparison path. Native GL is restored as the packaged
`NativeGLCamera`, with its original GLSL and public `ShaderWrapper`. Set
`camera_class = NativeGLCamera` on a scene for explicit native reference output.
Independent frozen GL and native winding WebGPU implementations remain under
`tests/`; tests are excluded from wheels. This completes the first follow-up
to the `67f779dc` cutover described in the
[sixth-round response](unified_triangle_renderer_review_response.md#sixth-round-response-retain-native-gl-and-target-the-measured-regressions).

## Rendering contract

- Python continues to own and update source points. Lyon generates filled
  meshes on the CPU. General fill borders now expand retained curve inputs
  in a GPU compute stage. Rasterization, shading, depth and compositing run on
  the GPU. GPU source updates and general fill topology remain Phase B.
- Planar vector fills use nonzero winding coverage, including concavity,
  holes and intersections. Tessellation uses a conservative 0.25 final-pixel
  curve-error budget; the cache spends half initially as zoom headroom.
  Original XYZ positions are reconstructed from the object's plane.
- Painter operations disable depth reads and writes. Depth operations use
  the common depth attachment. Phase A stably partitions fixed-frame groups last on both hosts, matching
  the historical native GL camera. Original 2D preserves the historical
  browser stable z/add order, so the explicit references can differ.
- Default quality is 4× MSAA at twice the final width and height, followed by
  an exact four-texel box resolve. This is selected independently of the old
  `Camera.samples=0` default. Stroke fringe widths remain in final pixels.
- Native output unpremultiplies at the PIL/PNG interface. Video retains its
  established row convention. Internal targets and blending use premultiplied
  RGBA, including transparent backgrounds.

### Borders use sample ownership

The border emitter reproduces Manim's existing curve subdivision, endpoint
widths, partial-path sentinels and join formulas. Those formulas differ from
the SVG styles with the same names. It emits actual world-space triangles,
including camera-facing borders. The source is never rewritten.

The default GPU generator reserves output vertices per curve for each run from
the steps its curves need at the current zoom (two per step, doubled for
headroom, capped at 64) and clamps unused pairs to a degenerate tail; the
reservation grows only when a zoom outgrows it. Fill storage and border sources
are retained separately; small camera-only updates send uniforms instead of
replacement border triangles, and a grown reservation resends nothing. The
wire (format 6) carries fill indices only: each driver expands the per-object
strip pattern from the run layout, so the deterministic index pattern never
travels. The original CPU emitter remains available explicitly with
`MANIML_BORDER_GENERATOR=cpu`, through the same Phase A renderer. This is a
diagnostic reference, not an automatic fallback. The
[GPU generation specification](gpu_geometry_generation_plan.md#23-generation-work-and-research-gate)
describes its source layout, dependencies, memory tradeoff and remaining work.

A bordered object contains its fill triangles followed by border triangles.
A stencil reference marks samples already painted by that object. This gives
one color contribution for fill/border overlap and border self-overlap without
constructing a much larger polygon union. Different objects still composite
in authored order. Reference rollover clears stencil while retaining scene
color and depth. For depth-tested coverage, a subsequent color-disabled depth
draw records the nearest actual geometry for later objects.

Consecutive compatible ordinary fills and strokes can still coalesce.
Opaque, constant-color, unshaded painter fills also omit redundant ownership:
their actual generated colors must equal the source color, so repeated
fragments write exactly the same value. This reduces the 101-glyph text
control to one draw, with exact GPU pixel equality to separate stencil draws.
Translucent, gradient, shaded and depth-tested bordered objects retain
coverage ownership. Performance is measured at the complete-frame level.

### Paint is independent of tessellation

Uniform fills use the ordinary surface pipeline. Nonuniform fill colors and
lit vector fills use a source-space field evaluated per fragment, so quality
refinement or a different mesh diagonal does not move the interior colors.
Uniform and affine data are exact. Non-affine data with at most 256 distinct
samples uses a degree-one thin-plate spline. Numerically unstable or larger
fields use positive inverse-square-distance interpolation, bounded at 4,096
samples. Coincident samples have their mean color; final RGBA is clamped.

This deliberately replaces the historic winding fan's interior color seam.
It preserves the source color arrays; it does not claim pixel equality to an
ambiguous old fan interpolation. The independent CPU reference uses SciPy's
documented degree-one RBF formulation, while the shader consumes explicit
coefficients rather than renderer-selected vertex colors.
[SciPy RBFInterpolator](https://docs.scipy.org/doc/scipy/reference/generated/scipy.interpolate.RBFInterpolator.html)

Format 4 introduced independent binary coefficient definitions. Unchanged
fields use a small content-hash reference; readers retain one coefficient
buffer across pipeline/sample bindings. The large inverse-distance fragment
loop is unchanged and remains expensive. The follow-up paint controls preserve
both the large-field regression and the deliberate interior semantic difference
from historical fan interpolation.

### Explicit limits

A nonplanar closed contour has no unique filled surface. An ordinary filled
VMobject therefore rejects a nonplanar source explicitly. Use a defined
`Surface` or `VMobject3D` for such a surface. The old winding fan and existing
VMobject3D can produce different depths for the same saddle contour; silently
choosing either is not general compatibility. Singular/near-plane inputs that
cannot meet the meshing budget also fail explicitly, as specified in the plan.

Per-point fields can be expensive when they require many samples; ordinary
uniform text and shapes do not use that shader. The known cross-top-level
group z-index limitation is unchanged. Custom GLSL wrappers remain explicit native
renderer internals, not supported shared-backend shader extensions.

## Retention and transport

Mesh entries hold immutable source snapshots and derived arrays, limited to
64 MiB and 2,048 fill entries. GPU source/recipe retention shares that byte
budget and is disabled when retention is configured off. Its identity proofs
count the input arrays they pin as well as their assembled arrays.
Exact source-array checks detect direct writes that
bypass revisions. Fill paint changes preserve connectivity. Border source and
camera dependencies are cached separately from fill tessellation. Digest
reuse trusts only immutable bytes-backed arrays, never an ordinary ndarray
whose writable flag can be restored.

Generated GPU geometry, uniforms, material bindings and textures retain the
active frame. The sender follows the same lifetime rule, so returning content
is resent. Prepared frames pin immutable texture bytes; the file-read cache is
limited to 64 MiB/128 files and detects file replacements. These are retained
payload limits, not total process or GPU allocation limits. Scene targets,
readback and temporary generation allocations are additional memory.

Format 5 adds retained GPU border sources and fill/index recipes to the ordered
operations, paint definitions, coverage ownership and supersampling contract.
Recorded playback reconstructs requested frames from CPU
payloads, so reverse and random seek do not require historical GPU buffers.
The player recognizes older format 1–4 recordings and uses their original
renderer where required. Corrupt recording errors have a visible surface.

## Installation decision

The default renderer requires the Lyon helper and `wgpu`. Making the helper
optional would allow an install whose default renderer cannot run, so it is
intentionally required. Source/editable installs need Cargo and a linker;
Rust 1.97.0 and the checked-in Cargo lockfile are the tested build. Compatible
wheels contain the helper and need no Rust toolchain. Nothing compiles during
scene playback. `moderngl` and `PyOpenGL` are runtime dependencies for the
explicit packaged native GL reference.

## Validation and integration

Evidence is archived in
[`benchmarks/results/triangle_phase_a_20260910/`](benchmarks/results/triangle_phase_a_20260910/).

### Performance decision

The numbers below record the initial CPU-border cutover. The later
[four-reference GPU border measurements](benchmarks/results/triangle_followup_20260910/gpu_borders/README.md)
separate static, pan, zoom, tilt, resize and changing paths. GPU borders now
reduce repeated 5% text zoom from 14.37 to 10.65 ms (16.09 to 11.06 ms with
WebSocket echo), while Original 2D remains faster on text. Small-zoom packets
fall to about 1 KB; retained text geometry grows by about 9.82 MiB over the
CPU-border reference. Those measured tradeoffs supersede the earlier
implementation's border-cost description below; A2 remains open.

`python -m benchmarks.generated_output --samples 12 --output /tmp/phase-a`
alternates the two variants on each frame, after three excluded warmups.
Both use ordinary camera defaults and equal final output/readback dimensions.
The old implementation is the preserved winding reference, not a second
invocation of Phase A. These are host serialization-through-RGBA-image times,
including full GPU readback, not GPU timestamps or browser presentation FPS.
Source construction, TeX compilation and camera updates are outside timing.

| Control | Original winding median | Phase A median | Result |
|---|---:|---:|---|
| Original 211-square B0, 2160×1080 | 80.57 ms | 25.31 ms | 3.18× faster |
| 101-glyph TeX, camera zoom and pan | 6.87 ms | 15.91 ms | 9.04 ms slower; 2.32× original time |

The text regression **does not pass the plan's proposed 10%/0.5 ms
no-regression gate**. The cutover decision explicitly accepts this measured
case for the requested default-renderer dogfood rollout. This implementation
decision does not close the A2 performance gate, which remains open. Current benefits
are the large ordered-square improvement, a common native/browser output
path, general fill coverage and source-space paint. Original 2D remains
selectable for immediate comparison. This is not a claim of universal speedup
or a claim that future Phase B work already pays for today's cost.

Text now submits one draw, with median driver command encoding of 0.61 ms
versus 0.36 ms originally. Its main cost is CPU preparation: 10.32 ms versus
2.24 ms. The combined fill/border geometry changes with camera-dependent
borders, while the old renderer expands curves in its vertex shader. New
default AA also performs more sampling. The first scalar border emitter took
239 ms for this control; vectorized emission, exact-content caches, shared
projection bounds and the proven opaque fast path brought it to 15.91 ms.
Further camera/border preparation work is a concrete optimization target;
GPU source/geometry migration remains separately scoped in Phase B.

Full raw samples, stage distributions, hashes and retained byte counts are
in `performance.json`. At the final text pose, Phase A retains 3.30 MB of
CPU mesh data and 1.24 MB of GPU geometry. Camera-dependent borders resend
that 1.24 MB payload, whereas the original sends about 1 KB of metadata and
no geometry. Browser transport is outside these timings; this wire cost is
another reason to keep the live comparison available. Timings fluctuate with
host/GPU scheduling; earlier
runs showed a 2.6× B0 win. Retention figures exclude scratch, output targets,
readback staging and driver allocations. At 960×540, the selected nominal
color/depth/resolve targets total 76.72 MB, versus 18.66 MB for 4× MSAA without
the spatial supersample, counting the depth/stencil format nominally as 4 B.

### Quality and behavior

- All five production-style fixtures pass the existing full-frame RGB
  thresholds. Normal/zoomed TeX preserve glyphs and counters; the wide
  translucent border has no repeated-opacity ring. Paint probes cover affine,
  nonlinear, diffuse-light and back-shadow behavior. Source bytes are unchanged.
- There is one explicit old-sampler exception: zero-border zoomed text has
  0.8829% of pixels over the 24/255 RGB threshold, above the old 0.5% limit.
  No threshold was widened. A 16× same-mesh coverage reference favors the
  chosen AA over native GL, with approximately 5× less paragraph error;
  exact triangle/pixel area checks independently support the sampling policy.
  The same-mesh reference proves sampling quality, not source tessellation.
- CPU border vectorization produces exactly the scalar implementation's
  float32 vertices and normal endpoints in all ten quality fixtures.
  Opaque coalescing is independently pixel-identical at normal/zoomed TeX,
  overlapping object colors and both painter orders, clipping and four AA
  combinations. Depth, translucent and paint paths keep stencil ownership.
- Actual WebGPU browser checks cover both production drivers, resize,
  disappearing/returning content, recorded forward/reverse/random seeks and
  current-frame resource retention. The live viewer switched **Phase A →
  Original 2D → Phase A** at checkpoint **1 → 1**, with zero observed GPU
  errors. The player and generated-frame runs each validated ten frames.
- Native boundaries cover transparent RGBA, RGB/channel counts, video row
  orientation, explicit `show()`, lazy capture, checkpoint copies and cleanup
  when output or GPU release fails. A renderer error leaves the live viewer
  available so a later valid frame can recover.

The complete suite ran **623 tests in 214.26 s**, with no failures/errors and
one order-dependent navigation skip. Both navigation checks subsequently ran
in fresh scene processes and passed without skips. After the final camera
release and owned-image-file cleanup, **92 affected tests** passed with real
GPU rendering and `ResourceWarning` treated as an error. This includes native
output, historical GL comparison, image sampling and texture retention.

The wheel and source distribution build offline. The initial wheel excluded
native GL and tests; the approved follow-up restores packaged native GL.
Current wheel-content checks require Original 2D, native GL and GPU border
assets, exclude tests, and capture with both native cameras from extracted
wheels using the packaged Lyon helper. These checks and `twine check` pass. Python compilation
and the offline lockfile check pass. Only the local macOS arm64/Python 3.13
configuration was executed here; the configured CI Python matrix and
Windows/Linux distributions are not claimed as run.

Integrate by fast-forwarding the canonical `main` checkout, refreshing the
editable install with `--no-deps`, and verifying imports/native output from
outside the repository. Existing scene processes retain their imported code;
reopen the scene to load this renderer and its comparison control.

## Native GL restoration follow-up (2026-09-10)

The package again contains a runnable native GL reference, selected with an
explicit scene `camera_class = NativeGLCamera`. Phase A remains the default
for browser, native output and new recordings; Original 2D stays selectable
in the viewer. The public `ShaderWrapper` and original GLSL assets are restored,
and `moderngl`/`PyOpenGL` are runtime dependencies. Frozen test references remain
independent. No GPU objects are added to source mobjects.

The extracted-wheel smoke check imports the restored public classes, renders
a square with native GL while forbidding all `tests` imports, and checks that
`Scene.camera_class` is still the shared camera. The same wheel loads its Lyon
helper and passes metadata/license checks. The native reference pixel test
checks exact RGBA equality to the frozen GL camera across direct paint edits,
border/stroke changes, camera motion and depth changes.

## Fixed-frame ordering follow-up (2026-09-10)

The shared Scene input once again keeps stable top-level z-index order, with
add order on ties. Original 2D consumes that order unchanged. Phase A performs
a stable fixed-frame-last partition in triangle preparation, matching the
existing partition inside native GL capture. This deliberately preserves
Phase A/native behavior while restoring the historical browser comparison.

For overlapping fixed red at z=-10 and depth-tested world blue at z=100, both
Phase A and native GL show red; Original 2D shows blue. A real GPU test verifies
all three results with clipping enabled. CPU checks cover ties, conflicting
z values and the existing mixed-family limitation: partitioning top-level
groups does not lift a fixed child above a different top-level group. This is
an explicit historical difference, not a claim that all old surfaces agreed.

Phase A also rejoins compatible adjacent families after the partition using
their recorded assembly keys. This preserves the cutover's existing child
z-sort when a fixed group formerly separated those families; without it,
moving the partition alone could change Phase A pixels. The Original 2D input
group boundaries remain unchanged.

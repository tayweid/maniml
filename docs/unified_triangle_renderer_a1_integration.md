# Shared triangle renderer: A1 integration checkpoint

2026-09-09. Generated geometry now lives in the package and both WebGPU
drivers. The temporary selector is `MANIML_RENDERER=triangles`; the default
remains `winding`. This is **not Phase A completion**: appearance and
representative performance still have open A2 gates, and native GL retirement
remains held under A3.

## Integrated behavior

- `maniml.web.triangle_scene` prepares ordered geometry from existing public
  control points. The benchmark module imports that implementation.
- Planar nonzero fills use the pinned Lyon helper. Strokes, dots, images,
  surfaces and textured surfaces retain their shared WGSL and texture inputs.
- Explicit draws preserve fill/stroke order, clipping, instance/index counts,
  and depth policy. Compatible adjacent fills merge into one indexed draw;
  fill/stroke ordering barriers remain intact.
- Both WebGPU drivers use one scene pass and premultiplied source-over for
  every material. The browser then performs its existing canvas blit.
  Two-dimensional draws do not test or write depth.
- Mesh validity still inspects exact source arrays and projected quality.
  Camera transforms are shared per frame; unchanged-camera bounds are
  memoized. Uniform paint refreshes vertices without rebuilding connectivity.
- Wire identity includes pipeline, framed vertex/index lengths, and both byte
  streams. The framing prevents a zero vertex from aliasing zero indices.
  Unchanged geometry and uniform bindings persist; absent generated geometry
  and bindings retire after submission.
- Format 2 exports index recorded bytes on the CPU and reconstruct any
  requested frame, including reverse seeks. Playback does not require all
  historical GPU buffers. Reconstruction copies the requested payload;
  recording storage and that temporary copy are separate memory costs.
- Browser renders serialize asynchronous texture decoding and recover after
  failed frames. A rejected player render no longer blocks future seeks.
- Wheels include the native helper. Runtime never invokes Cargo. Source and
  editable installs require Rust and a linker. Local packaging validation
  covers macOS arm64/Python 3.13; CI covers 3.11/3.14 when run. Other platforms
  and WASM remain unvalidated.

The selector affects live geometry streaming, baked export, and direct native
WebGPU calls. Offline `--render` and `--export-checkpoints` still use native GL.
Source evaluation and fill generation remain on the CPU; Phase B is the
subsequent GPU move.

## Fourth-round review disposition

1. **Analytic text:** deferred as an alternative, not made a requirement of
   the selected general renderer. That candidate still accepts 100/101 glyphs.
   Lyon accepts all 101 and now has borders, packaging, and both host drivers.
2. **Revision-only renderer reuse:** not adopted here. The ledger's revision
   contract is real, but this renderer also observes public array edits.
   Exact-array tests remain. Shared camera work and draw consolidation reduced
   paired camera-motion text preparation from 9.34 to 6.60 ms. That comparison
   excludes borders and is CPU preparation, not production total-frame timing.
3. **Completed Write work:** fixed in `animation.creation.Write` /
   `DrawBorderThenFill`. Equal endpoints preserve exact points/normals, and
   unchanged completed subobjects skip interpolation. Reverse seeks, Unwrite,
   animation reuse, mutations, and updaters have regressions. The 17-frame
   audit falls from 95 to 38 regenerations, all newly visible fills, with 57
   paint refreshes and no changed point/normal bytes. No displacement tolerance
   was relaxed. The separate top-level `maniml.Write` compatibility alias
   retains its existing behavior.

Only small summaries are retained for this checkpoint; raw image iterations
stay temporary instead of adding another multi-megabyte archive each time.

## Border coverage and remaining appearance work

Uniform flat borders form one nonzero union of fill and stroke triangles,
painted once. Local width follows the existing zoom-width convention and is
part of cache validity. Projection bounds include the border extent.

Lyon bevel/miter joins and binary coverage do not yet match Manim's exact auto
join and smooth fringe. The flattening tolerance alone does not prove a global
stroked-cusp/miter error bound. Frames record this limitation. Nonuniform
border widths, camera-facing borders, nonplanar fills, unaccepted per-point
fill paint/lighting, and unknown primitives fail explicitly in the opt-in path.

Production serializer → native WebGPU comparisons against preserved native
GL goldens, candidate at 4× MSAA:

| Case | Full-frame mean RGB difference /255 | Pixels with RGB difference >24 | Existing broad threshold |
|---|---:|---:|---|
| Normal default TeX | 0.181 | 0.301% | Pass |
| Zoomed default TeX | 0.328 | 0.523% | Fail (limit 0.5%) |
| Wide translucent border | 0.087 | 0% | Pass |

These broad thresholds do not erase local differences. Normal paragraph crop:
mean 5.06/255, 8.53% over 24; zoomed paragraph: 2.55/255, 4.12% over 24. Some
text stems look uneven/lighter, and native borders have a softer fringe.
Wide-border interior RGBA is unchanged by enabling the border; its color is
within 0.4/255 of one independent source-over operation.

Union geometry is substantial: the normal 101-glyph quality case contains
42,302 vertices and 235,536 indices. One draw does not make its generation or
upload free. This checkpoint does not claim AA acceptance.

## Production-path timing and memory

[Twelve samples per variant](benchmarks/results/triangle_a1_20260909/performance.json),
after three warmups, alternate renderer order and measure the public serializer
through full RGBA readback/PIL image construction. Sources and output sizes are
equal; winding keeps its existing AA and triangles uses 4× MSAA. Source
animation, transport and browser presentation are outside this measurement.

| Fixture | Winding median | Triangles median | Speedup |
|---|---:|---:|---:|
| Original 211-square B0 | 77.15 ms | 28.63 ms | 2.70× |
| Camera-moving default TeX | 16.17 ms | 15.09 ms | 1.07× |

Rendering saves time, but CPU preparation/encoding consumes much of the text
gain: serialization rises from 3.01 to 10.87 ms. B0 serialization rises from
6.51 to 15.48 ms while its render-command encoding falls from 30.42 to 5.72 ms.
Submission-through-readback includes GPU work and host waiting; these are not
GPU timestamp measurements or a general speed guarantee.

All measured frames reused their generated meshes and sent zero geometry
payload bytes. B0 retains 175 KB of CPU meshes and 211 KB of GPU geometry.
The border-bearing text retains 3.07 MB of CPU meshes and 2.63 MB of GPU
geometry; winding retains 680 KB of geometry plus 16.59 MB of winding scratch.
Output/depth/resolve textures, readback staging and transient/native scratch
are excluded, so these are component counts, not peak memory claims.

## Validation and next acceptance step

[Validation record](benchmarks/results/triangle_a1_20260909/validation.json).
Full discovery with real GPU tests and `MANIML_VERIFY_LEDGER=1`: **540 tests,
537 passed, one Windows-only skip, two documented baseline AppShellE2E
failures** (`missing_module_hint`, `open_scene_from_landing`), zero errors.
Both winding and triangle CLI exports passed. Focused tests also exercise the
new vertex/index hash framing and player recovery after a rejected seek.

Native checks cover ordering, alpha, clipping, mixed depth, all five primitive
layouts, textures, deltas, and resource retirement. The actual in-app WebGPU
browser rendered ten frames covering 211 squares, delta reuse, absent/returning
meshes, reverse seeks, default TeX borders and resize, with zero GPU validation
errors and zero cache misses. Packaged-helper discovery was tested from an
extracted wheel in isolated Python, without the source tree or library override.

Remaining A2 work: text/border AA and joins, accepted paint/lighting semantics,
representative course/morph performance, and total allocation bounds. Current
limits cover retained mesh arrays and active generated GPU geometry/bindings;
textures and tessellator scratch have separate lifetime/memory costs. Changed
payloads allocate replacement buffers; capacity reuse remains an optimization.
Only after these checks and the held offline cutover can A3 remove winding.

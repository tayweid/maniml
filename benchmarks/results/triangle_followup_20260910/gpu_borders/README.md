# GPU border measurements — 2026-09-10

The final implementation moves general fill-border subdivision and expansion
to compute while preserving CPU-generated fill meshes, source-space paint,
sample ownership and ordered opaque batching. It improves camera-dependent
border work, with a fixed-capacity memory cost. Original 2D remains faster on
the text controls. This evidence does not close the separate zero-border AA
gate or claim a general GPU fill generator.

## Reproduce

From the repository root, using an environment with the project dependencies,
a built Lyon helper, TeX fixture dependencies and a working GPU:

```sh
python -m benchmarks.gpu_borders --samples 12 --warmups 3 --output /tmp/gpu-borders-native
python -m benchmarks.gpu_borders --samples 12 --warmups 3 --transport --output /tmp/gpu-borders-transport
```

Use `--cpu-only` to validate all source/serialization cases without a GPU.
`MANIML_LYON_LIBRARY` may point at a built helper for a source checkout. Both
border modes are selected explicitly inside the harness, independently of
the environment default. `--cases` selects individual controls. The measured
environment was Python 3.13.9 on macOS 26.6.2 arm64, using Metal; adapter details,
source hashes, B0's exact camera packet and per-frame rows are in the reports.
The other camera sequences are reconstructible from the harness's recorded
frame indices; their full per-frame camera packets are not archived.

Every case creates fresh sources, caches and renderer devices for GPU-border
Phase A, CPU-border Phase A, Original 2D and packaged native GL. Original 2D
uses the shipped serializer and the frozen native WebGPU comparison driver;
it is not a timed browser run. The CPU/GPU Phase A pair shares production
4× MSAA and 2× spatial resolve. Historical references keep their original
internal AA with `samples=0`.

The first cold frame is archived separately. After three warmups, twelve
measured frames rotate/reverse reference order and finish with full RGBA
readback and PIL image construction. Source evaluation is separately timed
and excluded from rendering totals. Image comparisons, source checks, memory
summaries and PNG writes are outside timings. Completion includes host waits,
mapping and retirement; these are not GPU timestamps. Component medians must
not be added. Native GL receives the same camera packet, including B0's
special 24×12 projection; resize reallocates only its targets inside timing.

The optional uncompressed localhost WebSocket echo sits between serialization
and parsing. It measures **two wire traversals**, not one-way delivery or
browser presentation. Native GL has no transport stage. Existing user app
processes were left running; these small local distributions are not isolated
hardware performance guarantees.

## Complete native frame medians

Milliseconds from serialization through full RGBA, or native GL capture
through full RGBA:

| Control | GPU border | CPU border | Original 2D | Native GL |
| --- | ---: | ---: | ---: | ---: |
| B0, 211 touching squares | 24.35 | 25.12 | 66.95 | 265.57 |
| 101 glyphs, static | 6.96 | 7.74 | 5.54 | 7.76 |
| Text, subpixel pan | 8.80 | 9.86 | 5.57 | 7.77 |
| Text, repeated 5% zoom | 10.65 | 14.37 | 5.49 | 8.24 |
| Text, 1→4→1 zoom | 10.72 | 17.14 | 5.75 | 8.06 |
| Text, camera tilt | 9.00 | 9.84 | 5.55 | 8.02 |
| Text, output resize | 12.04 | 11.62 | 6.95 | 8.51 |
| Changing concave/curved paths | 5.03 | 4.68 | 3.04 | 3.73 |

With WebSocket echo, repeated small zoom is **11.06 / 16.09 / 5.73 / 8.07 ms**
and 1→4→1 zoom is **11.23 / 19.18 / 6.23 / 8.09 ms**, in the same order.
The echo's median contribution for small zoom is 0.240 ms for GPU borders,
1.033 ms for CPU borders and 0.168 ms for Original 2D. See `summary.json` for
all min/p50/p95/max totals and the complete reports for component distributions.

Small zoom sends 1,077–1,138 bytes with GPU borders and no new binary fill or
border data, compared with CPU-border packets up to 1,468,384 bytes. The
3,200 curve sources are prepared once. The 1→4→1 case genuinely refines fills
(101→202 cumulative fills in both modes) and can send 2,671,229 bytes for GPU
fill/index replacement, so the 1 KB result does not apply to every zoom.
Opaque text still uses one scene draw plus one resolve, excluding compute.

The initial run found avoidable static/pan CPU work from repeatedly freezing
unchanged curve records. Source identity plus exact color reuse removes that
copy. `initial_cache/report.json` preserves that result; `cache_fastpath/`
contains its three-case check. Only `native/` and `transport/` are the final
eight-case runs. Their recorded runtime files remained unchanged during each
run.

## Memory and appearance

Static text retains these GPU geometry buffers after completion:

| Buffer | GPU border bytes | CPU border bytes |
| --- | ---: | ---: |
| Uploaded fill / CPU-expanded vertices | 174,640 | 1,096,960 |
| Indices | 2,431,368 | 142,800 |
| Curve sources | 563,200 | 0 |
| Combined generated output, including fill copy | 8,366,640 | 0 |
| Uniforms | 192 | 192 |
| Total | 11,536,040 | 1,239,952 |

That is **9.82 MiB extra retained GPU geometry** for this text fixture.
Host fill/recipe caches account for 6,578,423 versus 3,295,751 retained array
bytes. This is conservative accounting, including shared references counted
again, rather than a unique physical-memory total. The shared
64 MiB host budget includes references pinned by immutable assembly proofs.
AA attachments are additional and unchanged; these are not peak GPU/process
memory measurements. Native GL buffer bytes are unavailable in this harness.
Each curve reserves 2,560 output-vertex bytes, 744 index bytes and 176 source
bytes. Unused samples degenerate, but still occupy capacity and index work.

CPU/GPU border images agree exactly for six controls. Some fractional frames
in the large-zoom and tilt sequences differ by at most 15/255 in one channel;
no frame has a pixel whose maximum RGB difference exceeds 24. These diagnostics
do not independently establish historical-renderer parity. Separate production
quality controls for text, hairlines, perspective and wide borders at normal
and zoomed views are byte-exact locally; cross-device tests permit at most one
of sixteen AA coverage samples within a tightly bounded affected region.

## Artifact map

- `native/report.json`: final native evidence, including cold frames,
  component timings, sources, adapter details, memory and every image comparison.
- `native/*.png`: full images and center crops for first/middle/last measured
  frames, all four references and all eight controls (192 images).
- `transport/report.json`: the final real WebSocket echo run. Its 192 saved
  images were byte-equal to the native run, so duplicate PNGs are omitted.
- `summary.json`: compact distributions and the native/transport saved-image
  equality check.
- `initial_cache/report.json`, `cache_fastpath/report.json`: the initial
  measurement and the source-reuse refinement, kept separate from final claims.
- `browser/`: actual Chrome driver/player correctness reports, screenshots and
  reproduction harness. These are browser correctness checks, not timings.

## Final integration checks

Full discovery with `MANIML_TEST_GPU=1` and `MANIML_VERIFY_LEDGER=1` ran
704 tests in 207.674 seconds, with no failures/errors and one existing skip.
The first run found a stale WebSocket snapshot assertion counting locally
generated vertices as uploaded bytes. The corrected real WebSocket check
validates every contiguous payload span, complete border definitions, output
capacity and index bounds; the full rerun passed.

Offline wheel/source builds, Twine checks, Python compilation and the CI
workflow parse pass. The extracted wheel loads packaged Lyon, captures native
GL, and renders default GPU borders with development imports blocked. It
checks straight alpha, source preservation, visible border coverage and CPU
reference equality. The final rebuilt wheel's runtime files are byte-identical
to that GPU/GL-tested wheel. Local validation is macOS arm64/Python 3.13;
the CI matrix and Windows/Linux execution are not claimed here.

# Performance dogfood

## Shared triangle renderer: A0 experiments

These opt-in programs do not select a production renderer. Build the isolated
[Lyon helper](../tools/lyon_fill/README.md), set `MANIML_LYON_LIBRARY` to its
library, and use the repository's locked Python dependencies. Native image
comparisons require local GL/WebGPU access; real TeX fixtures require the
production TeX compiler and `dvisvgm`.

```bash
python -m benchmarks.triangle_renderer --output /tmp/triangle-fixtures --samples 5
python -m benchmarks.renderer_quality --output /tmp/triangle-quality \
  --goldens tests/goldens/triangle_renderer --samples 5
python -m benchmarks.renderer_motion --output /tmp/triangle-motion
python -m benchmarks.triangle_wordmark --output /tmp/triangle-wordmark --samples 5
python -m benchmarks.earcut_probe --output /tmp/earcut-probe.json
```

`renderer_quality --capture-native` captures missing native references; existing
source-contract mismatches fail instead of replacing historical goldens. Its
manifest covers live source geometry/style/order, uniforms, output settings,
and image hashes. The comparison includes explicit zero-border controls beside
default-style text. Unsupported analytic paths reject the whole frame.

`renderer_motion` runs continuous 2×/4× zoom, fractional camera motion, perspective,
actual Transform/Write, and isolated opacity frames while checking that rendering preserves source
arrays. `triangle_wordmark` reconstructs the original B0 camera and payload
exactly. Both include CPU preparation through a synchronous GPU completion
barrier and disclose exclusions; neither measures browser presentation.
The 4× zoom exceeds the cache's 2× initial quality headroom. Write also changes
source point bytes through interpolation; `tex_opacity` isolates paint changes
with exactly fixed points. Cache counters distinguish paint refreshes from
regeneration. Reports preserve completion samples and expose timing modes using
minimum and fractions below 3 ms / above 10 ms; none is pure GPU execution time.
Region crops report errors without applying the background-dominated full-frame
threshold. Current retains historical geometry while candidate retirement is
included in timings; that lifecycle difference also affects memory comparisons.

The [A0 results](../docs_unified_triangle_renderer_a0_results.md) distinguish
measured improvements, candidate limitations, and unfinished acceptance gates.
To run the explicit real-GPU harness checks:

```bash
MANIML_TEST_GPU=1 python -m unittest tests.test_triangle_renderer
```

## Vector fill regions

`python -m benchmarks.vector_fill --samples 8` compares the B0 raster
wordmark's full-frame and bounded winding-fill paths on the same geometry,
plus a large single-batch control. Requires `wgpu` and GPU access, and runs
from a checkout to reuse the regression fixture. It checks rendered pixels,
warms pipelines and buffers, and alternates variants. Submission-through-
completion timings include a one-pixel readback; Python command encoding is
reported separately. They are not full viewer frame times or GPU timestamps.

On Apple M3 at 2160x1080, the original 135-batch wordmark measured 48.2 ms
with full-frame fills and 23.4 ms with bounded targets (2.06x), with identical
pixels. A large single batch remained about 1.4–1.5 ms. Per-batch command
encoding remains a separate cost; these changes preserve the batch count.

`live_profile.py` drives the same `--web` process and WebSocket route as the
viewer. It records bounded engine-stage timings through `MANIML_PERF_PATH` and
a companion summary of socket arrival cadence and bytes.

Example:

```bash
python benchmarks/live_profile.py \
  ../dogfood/03_Code.py animation_0 \
  --renderer gpu --right-steps 1 --back-steps 3 \
  --output /tmp/animation-0-gpu.json
```

The engine profile is opt-in. Ordinary ManimLive runs retain no samples and
write no profile. Socket arrival is not browser presentation: browser adapter,
GPU submission, and paint measurements must be reported separately rather than
mixing clocks.

For intentionally continuous updater fixtures, use `--continuous-seconds 3`
so the harness samples a bounded active window instead of waiting for idle.

## Curve construction and redraw

`python -m benchmarks.curve_redraw --samples 20` measures the dogfood PPF's
two-curve `always_redraw` updater at alpha 1 and 1.5 across three stages:

- `original`: per-corner appends, the old array resizing, and scalar coordinate
  conversion.
- `bulk_corners`: the bulk construction improvement, with scalar coordinate
  conversion (the behavior at `fcf7dc4f`).
- `batch_coordinates`: bulk construction and the current coordinate batching.

The earlier stages are reconstructed with independent implementations of the
old methods, patched in the same process. Every stage calls the real updater;
scalar equation evaluation, smoothing, and `become` remain part of the timing.
A separate 1,001-anchor path compares just the first two construction stages.
Each stage gets a warmup before 20 measured calls by default, with the order
rotated and reversed across rounds. JSON output reports median milliseconds
and the speedups between stages. This is a CPU microbenchmark, with no scene
rendering or browser frame timing.

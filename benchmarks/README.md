# Performance dogfood

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

# Performance dogfood

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

`python -m benchmarks.curve_redraw --samples 20` compares bulk corner
construction with the previous per-corner append loop in the same process.
It measures both a 1,001-anchor path and the dogfood PPF's two-curve
`always_redraw` updater at alpha 1 and 1.5. The scalar reference replaces
`add_points_as_corners` and the old `append_points` resizing during the
measurement; callback evaluation, smoothing, and `become` are unchanged.
This is a CPU microbenchmark, with no scene rendering or browser frame timing.

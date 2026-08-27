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

The Phase 3 revision sidecar is separately opt-in. It never replaces the
legacy checkpoint; it records component deltas and validates the copied
checkpoint endpoint:

```bash
MANIML_SHADOW_REVISIONS=1 \
MANIML_SHADOW_REVISIONS_PATH=/tmp/animation-0-revisions.json \
python benchmarks/live_profile.py \
  ../dogfood/03_Code.py animation_0 \
  --renderer gpu --right-steps 1 --back-steps 3 \
  --output /tmp/animation-0-shadow-gpu.json
```

Omit `MANIML_SHADOW_REVISIONS_PATH` to measure validation without diagnostic
JSON write time. Resource payloads are retained only in the in-memory shadow
store; the JSON contains compact commit/resource metadata, not those payloads.
`MANIML_SHADOW_RESOURCE_BUDGET_BYTES` sets the diagnostic byte budget (64 MiB
by default), and `MANIML_SHADOW_RESOURCE_CHUNK_BYTES` bounds individual
resources (256 KiB by default).

`LargeStatic` accepts `MANIML_BENCH_OBJECTS`; it commits a static sibling
population before shifting one square, so the final shadow record must contain
one changed object and the current renderer still receives the large merged
batch.

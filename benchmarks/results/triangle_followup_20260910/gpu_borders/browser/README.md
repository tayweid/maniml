# Chrome WebGPU validation — 2026-09-10

Both checks passed in an isolated headless Chrome 152.0.7977.83 profile on
macOS, using the production JavaScript renderer, recording index, player and
WGSL assets. `environment.json` records the launch flags, Chrome version and
SHA-256 hashes of the tested runtime assets.

- `direct-report.json`: 35 rendered frames. Format 4 paint changes preserve
  geometry identity and produce the expected red/blue pixels. Cached, empty,
  returning and reset frames work; format 3 inline paint still renders after
  driver destruction and reinitialization. Format 5 border sources survive
  reverse/random recording seeks and reinitialization. The translucent circle
  images match CPU-generated border output exactly at normal size and zoom:
  zero changed channels in both full-image comparisons. Two deliberate
  missing-definition probes trigger exactly two cache-reset requests. No
  WebGPU validation errors or unhandled rejections were recorded.
- `player-report.json`: 20 rendered frames through the production player,
  using a format 5 recording containing format 4 paint and format 5 border
  frames. Initial/single-frame segments, forward/reverse playback, random
  backward seeks and empty/returning content pass, with no cache misses or
  recorded errors. Paint pixels are checked during playback.
- `direct.png` and `player.png`: screenshots from those runs. The JSON reports
  contain the complete results; the screenshot viewport shows only part of
  each report.

## Reproduce

Run from the repository root. These are the exact interpreter and Lyon helper
paths used on this machine; use the equivalent installed dependencies on a
different checkout. The helper is required only when building the fixtures.

```sh
export PYTHONPATH="$PWD"
export MPLCONFIGDIR=/private/tmp/maniml-triangle-mpl
export MANIML_LYON_LIBRARY=/private/tmp/maniml-triangle-target/release/libmaniml_lyon_fill.dylib
export MANIML_QA_PYTHON=/Users/taylorjweidman/Projects/ManimLive/maniml/.venv/bin/python
export MANIML_QA_ARCHIVE=benchmarks/results/triangle_followup_20260910/gpu_borders/browser

"$MANIML_QA_PYTHON" "$MANIML_QA_ARCHIVE/build.py"
"$MANIML_QA_PYTHON" "$MANIML_QA_ARCHIVE/build_harness.py"
"$MANIML_QA_PYTHON" "$MANIML_QA_ARCHIVE/run.py"
```

The Python environment needs the repository's test dependencies and
`websockets` (17.0.1 in this run). Chrome must be installed at
`/Applications/Google Chrome.app/Contents/MacOS/Google Chrome`.

`build.py` generates binary fixtures with the current Python encoder and
copies current runtime assets into
`/private/tmp/maniml-border-browser-20260910`. `build_harness.py` builds the
direct test and production-player test pages from the archived templates.
No duplicate runtime assets or generated geometry binaries are needed in
this archive. Compare a new run's asset hashes with `environment.json` before
treating it as the same implementation.

`run.py` binds its HTTP server to an ephemeral loopback port, creates a unique
temporary Chrome profile, and uses Chrome's ephemeral DevTools socket. It
does not use an existing browser profile or the user's viewer ports. The
script closes Chrome and its server in `finally`; the temporary profile and
scratch results remain available for inspection. New reports, screenshots
and `chrome.log` go into the scratch directory above, leaving this archive
unchanged. A failed case or timeout produces a nonzero exit status. Coordinate
with other GPU validation or timing work before running it.

## Scope and limitations

This is a correctness check, not a performance measurement. It covers one
translucent circular border at two camera poses, solid retained paint, and
the recording/cache paths listed above. It does not establish general scene
parity, text quality, transparent PNG output, the live WebSocket transport,
or the Original 2D selector's behavior. The pixel comparisons use the
rendered canvas over an opaque black background, at 320×180, with 4× MSAA
and a 2× internal resolve.

The harness changes only canvas configuration to add `COPY_SRC` usage, then
copies the actual GPU canvas texture into a mapped readback buffer. It also
observes device errors and wraps the player's render method for pixel
probes. The production shaders and rendering implementation are copied
unchanged. Chrome was launched with `--enable-unsafe-webgpu` and
`--use-angle=metal`; this does not establish support in every browser or
without those flags. The adapter-info objects in the reports are empty
because the observer copied their enumerable properties; no exact GPU model
was recorded.

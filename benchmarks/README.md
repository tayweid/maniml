# Performance dogfood

## Archiving a run

Archives live under `results/<name>_<date>/`. Keep what a reader needs to
check a claim and nothing that only makes a clone bigger: a `README.md`
stating the command, machine and commit, a `summary.json` with the key
numbers and source hashes, and at most one complete report JSON. Per-frame
images are not archived unless the README cites a specific crop as evidence
(the 2026-09-10 archives together carry 7 MB of PNGs that nothing cites; they
stay because rewriting history is not worth it, and they are the reason for
this rule).

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

The [A0 results](../docs/unified_triangle_renderer_a0_results.md) distinguish
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

## GPU pass timestamps

`python -m benchmarks.gpu_borders --gpu-timestamps ...` (or
`MANIML_GPU_TIMESTAMPS=1` for any `WgpuRenderer`) stamps every GPU pass of a
generated frame at its boundaries, the finest grain Metal offers, and puts the
result beside the wall-clock columns. The labels are `programs`, `borders`,
`nets`, `out` and `resolve`. Read two things as costs: `gpu_total_ms`, the
frame on the GPU (first pass begin to latest pass end), and the per-label
`gpu_exclusive_<label>_ms` sums, which add up to it. The other columns are
diagnostics that read like costs and are not: `gpu_pass_<label>_ms` is begin
to end, and for any pass after the first mostly waiting, because a render
pass begins at its vertex stage, which on Apple's tiling GPU starts before
the previous pass's fragments end (`gpu_pass_resolve_ms` is the resolve's
wait, about equal to the out pass, while its exclusive time is ~0.1 ms);
`gpu_sum_ms` adds the pass durations and lands on either side of the total
for different reasons (overlap, or gaps between passes on a many-pass
frame). Independent compute passes, one per changed border batch, run
concurrently and finish out of order on Metal (16-51 of a 259-pass frame's
passes end before an earlier one), so exclusive time is each pass's end past
the latest end before it, zero for a pass that finished inside earlier work:
it attributes a contiguous run of one label and the frame, never a single
pass among concurrent ones. A pass the frame did not encode has no column on
that row, and both harnesses reduce a column over the rows that carry it,
reporting `n`.

Two more facts keep the instrument out of the numbers it sits beside. The
last pass's end sample lands only once the frame's command buffer completes,
so the resolve and its staging copy are one small submission after the
frame's readback, run on the first read of `renderer.gpu_timings` rather
than inside `render()`; the harnesses read it after their timers stop, so no
wall-clock column contains it (`gpu_readback_ms`, about 1.5 ms, is that
cost, recorded). What the flag does perturb is the stamped passes
themselves, roughly 30 µs of wall clock per pass on the M3: below noise on
a 2-3 pass steady-state frame, about 1 ms on a 25-40 pass cold or navigation
frame, 8-9 ms on the 259-pass one. Cold rows under the flag are therefore
not the flag-off navigation cost; read per-pass compute costs on cold frames
from flag-off wall clock, and take the gate's totals from a run without the
flag. Timestamps also do not remove the GPU clock confound: the period is a
fixed nanosecond clock, so pass durations stretch with the M3's clock state,
which follows the whole machine's load (the same cached frame's
`gpu_total_ms` ranged 0.27-0.91 ms across minutes of varying concurrent
load; other GPU clients preempt inside a pass). Measure on a quiet machine,
keep the frame-by-frame rotation, read minima and medians together, and
never compare `gpu_` columns across runs taken under different load. Every
report carries these as `gpu_timing_scope` and `gpu_clock_caveat`. Original
2D and native GL are not instrumented and are never charged the instrument.
`probes/patch_pass_probe.py` prints the same numbers for its skipped-draw
variants.

## Episode frames

`python -m benchmarks.episode_frames --scene <file.py> <Scene> --output <dir>`
measures the renderer variants on frames of a real course episode, the
"one course episode" the B1 gate needs beside the fixture corpus
(`docs/phase_b_plan.md`, "Decided before the start"). The scene is loaded as
the CLI loads it and its checkpoints are built as present mode builds them;
every pausepoint (or every `--every`-th checkpoint of a file without pauses,
thinned evenly to `--max-frames` keeping the last, with no weighting by
on-screen time or heaviness) is restored in turn and each variant renders it
through `gpu_borders.sample`, warmups then samples in rotated order. One
renderer, cache and queue per variant lasts the whole run, as a viewer
session's do. The live viewer draws three kinds of frame and the harness has
a row for each:

- **Pausepoint** (always): the steady-state redraw of the restored frame,
  sources static between rounds. That is the cost of a camera change, not
  the live per-frame cost at a pausepoint whose mobjects have updaters: the
  viewer ticks those every idle frame (`viewer.py`,
  `should_update_mobjects`) and they regenerate what they drive, which is
  exactly the CPU work where Phase A and the patch fill differ.
  `should_update_mobjects` is recorded per frame.
- **Pausepoint, updaters ticking** (`--tick-updaters`): on such frames every
  round is preceded by `scene.update_mobjects(1/fps)`, as the idle loop
  ticks them, so the rows carry that regeneration (`updaters_ticked`).
- **Play** (`--play-frames`): the play leading into each pausepoint (the
  last checkpoint with a `run_time` at or before it) is replayed from the
  checkpoint before it through the scene's own retained replay at
  `camera.fps`, and its middle frames are sampled in turn, one rotation of
  the variants per frame with the scene mid-interpolation. The scene
  changes between rows as it does on screen.

The first row after each restore is kept per frame as `cold` and excluded;
a seek is what cold rows feel like, and they are perturbed by the flag
below, so they are archived, not summarised. A `ThreeDScene`'s ambient
rotation, which turns the camera per update call and whose switch no
checkpoint restores, is switched off before each frame's display pass.
Pixels are compared per frame in `gpu_borders.run_case`'s pairs
(`patch_vs_gpu_border`, `patch_vs_cpu` when `cpu_border` is in rotation,
`patch_vs_original`, `gpu_vs_cpu`, `gpu_vs_original`; the gate reads the
two against CPU-border Phase A and Original 2D), and the table prints them.
`report.json` holds every row; `summary.json` the medians and minimums with
`n`, the pixel pairs, the scene, commit, machine and the scope caveats; the
markdown table is printed and written as `summary.md`.

The variant `retained` is `gpu_border` (Phase A) with the retained frame
(`MANIML_RETAINED_FRAME=1`, `docs/phase_b4_plan.md`); every other variant
runs with the switch at 0, the serializer as it stood before Phase B4, so
`--variants gpu_border retained` measures what the retained frame changes.
The retained frame is the serializer's default, but every harness here
measures the whole-frame path unless it names the retained variant
(`gpu_borders.sample`, `paint_retention.wire_sample` and
`generated_output.sample` pin the switch to 0), so their numbers keep
meaning what the archived runs measured.
Its bytes are `gpu_border`'s, so the pair `retained_vs_gpu_border` must read
0%, and its rows carry the retained frame's counts (`retained_frame`: leaves
kept, prepared, compared, adopted; batches reused). The variants share one
scene whose reads write to it, so its ticked and play rows are slightly
pessimistic (`retained_scope`). An episode reached through a symbolic link
keeps the link's directory (the path is made absolute, not resolved).
`results/retained_frame_20260926/` is the run on both episodes.

The GPU pass columns above appear under `--gpu-timestamps`, an attribution
run; by default the flag is off and the totals are the gate's. The default
rotation of three renderers serves the pixel pairs, but for the completion
comparison run two at a time (`--variants patch_fill gpu_border`, then
`--variants patch_fill original_2d`): with three, most generated readbacks
follow another renderer's frame (Original 2D's 15-17 ms one at 2160x1080),
the alternation effect `gpu_borders.run_case` records. A gate run is thus
four commands: the two two-variant runs without the flag, one with
`--tick-updaters --play-frames` for the live frames, and one with the flag
for attribution; the report's `gate_scope` names what none of them measures
(the browser driver, cold rows, unselected pausepoints). A variant that
fails on a frame (an unsupported prototype, a singular camera) is recorded
under that frame's `errors` and the frame keeps the rest. Pass the episode by
absolute path (its own `../_Assets` imports resolve from it); TeX is needed;
nothing is written beside the episode.

## Browser frames

`python -m benchmarks.browser_frames --scene <file.py> <Scene> --output <dir>
--tick-updaters --play-frames` measures the other half of a live frame on the
same episode frames: the JavaScript the browser runs on every geometry
message (`docs/phase_b4_plan.md`, B4.6). The episode is loaded and its
frames chosen exactly as `episode_frames` chooses them (pausepoints thinned
to `--max-frames`, each restored and serialized `--warmups` + `--samples`
times, its updaters ticking before every round under `--tick-updaters`, and
under `--play-frames` the middle frames of the play that leads into it), so
the two harnesses describe the same frames. Each round is one geometry
message serialized as the viewer sends it, one `GeometryCache` per stream
and never reset, so every message is a delta against the one before it:
the first message after a restore re-sends what the cache no longer holds,
as a seek does, and the rest are cached batches with the camera. Two
streams of the same frames are the variants: `phase_a` from the default
renderer and `phase_b` from the whole Phase B stack (`MANIML_FILL=patches
MANIML_SURFACE=nets MANIML_PROGRAMS=gpu`) through the same driver. Each is
written under `<dir>/<variant>/` in the export recorder's format
(`scene.json` + `scene.bin.gz`; the player and `geometry_recording.js` read
it, `scene.json`'s frame entries also say what each frame is, and its
`lines` name each recorded group's line, the checkpoint's or the play's, so
the player's chips name the frames), then played in order through the
viewer's renderer selection (`renderer_selection.js`) into the real
`maniml/web/static/webgpu.js` in Node (`benchmarks/browser_frames.cjs`) on
the counting fake device the command tests use
(`tests/webgpu_fake_device.cjs`, with its validation off so the timed frame
pays for nothing but the page's JavaScript).

Per frame: `js_ms`, `performance.now` around the driver's render (the header
parse, the match against the retained slots, the compute stages, the encode
loop, the fake submit and the release of what the frame no longer holds);
`page_ms`, around the selection's render, which is the driver's plus the
selection's own routing (its `renderer` read from the header's first bytes,
since B4.8; before it, a parse of the whole header, or for a message the
same as the one before a comparison) and a promise hop:
what a page pays per message; and the calls the driver made — `draws`,
`set_pipeline_calls`
and the `pipeline_switches` among them, `bind_groups_created`,
`buffers_created` / `buffers_destroyed`, `uniform_writes` (uniform buffers
created with their data plus `queue.writeBuffer` calls into one),
`compute_dispatches`, `bytes_uploaded` — beside `wire_bytes`, the batch
counts and Python's `serialize_ms` for the same message. Rows fall into four
classes, reduced to medians and minima with `n` per variant and per frame:
`pausepoint` (the still redraw rounds after the warmups), `ticked` (the same
on a frame whose updaters tick), `play` (the recorded mid-play frames) and
`cold` (the first message after each restore, delta-encoded against the
previous message as a seek is against the frame on screen: `cached_batches`
says how much the cache still held, and only the stream's first message, or
a frame whose objects all changed, uploads everything; its own class,
excluded from the others). The play class samples a play's middle, so
`--play-edges` records, after every frame's rows (the rows before them stay
the stream without edges, message for message), each frame's play once more
at its edges: the checkpoint before it restored (`play_source`), the play's
first frame (`play_entry`, a class), its last frame (`play_last`) and the
destination on screen after it (`landing`, a class), one row each per play;
the entry and the landing are where a retained frame is made and let go,
and a play's dearest frames. `--camera-moves` records, after each frame's
pausepoint rounds, a pan of 5% of the frame's width, a 2% zoom out and the
camera restored as it was (`move` pan, zoom, back; the class `camera`).
`report.json` holds every row, `summary.json` the reductions with the
scene, commit, machine, Node version and scope strings, and `summary.md`
the table.

`--deltas` records each variant's frames twice, as the format 7 full frames
a receiver that has not negotiated format 8 is sent and as the format 8
stream one that has is sent (`docs/phase_b4_plan.md`, B4.8), the second
through a cache of its own serialized right after the first from the scene
as that left it (the format 7 stream is byte-identical to one recorded
alone): `<dir>/<variant>_delta/`, a variant of the report, whose
`scene.json` says format 8. A frame the stream did not send is an entry of
length 0 and a row of zeros (the page runs nothing; `batches` is the frame
on screen); a delta's row adds its `splices`, `spliced_batches` and
`scalars_ops`. The player does not read such a folder (a delta is no frame
to seek to); `node tests/generated_webgpu_commands.cjs deltaEqualsFull
<dir>/<variant> <dir>/<variant>_delta` checks that the two streams draw
alike, message by message. The stream's `serialize_ms` follows the format 7
serialization of the same frame, so it is not Python's cost of the stream
alone. `--rounds N` replays each variant's streams N times, taking turns
within a round, and reports each frame's median `js_ms` and `page_ms` (the
other columns are checked to be the same every round): the recipe for
gate numbers, with `--realm main`.

`--realm main` replays with the driver and the selection in Node's own realm
instead of the vm sandbox the command tests give it (the device's `realm`
option; every call and count is the same, `tests/test_browser_frames.py`
checks it). The
difference is what a global lookup costs: in the sandbox each one is an
interceptor call, so a loop that names a builtin per value pays for it per
value, and the sandbox's rows overstate a page's JavaScript several times
over on the frames that validate uploads (B4.7's archive,
`browser_frames_20260926/README.md`, "After B4.7", has both). Read the
sandbox rows against the sandbox rows of the same driver's past, and the
main realm's `page_ms` for what a browser pays; gates are set there.

What it is not: Dawn's validation and command encoding behind each call, the
GPU, the canvas present, texture decoding (a stub), the socket or the
viewer's queue. The live viewer marks each drawn frame as a `maniml:render`
span (`performance.measure`) that DevTools' Performance panel shows; that
span is `page_ms` plus any wait behind an earlier frame. Node's garbage collector lands where it lands and
V8 warms over the first frames, so read medians with minima. A repeated
still frame is what the viewer sends a format 7 tab on a camera change or
an updater tick; at rest without either it sends nothing, and that silence
is not a row (under `--deltas` the format 8 stream's silences are). A
cache miss on a recorded stream fails the run. Pass the episode by absolute
path; TeX is needed; nothing is written beside the episode.

## Point reads by kind and phase

The instruction-stream plan's prerequisite: which Python reads of source
points would need synchronization if the points lived on the GPU. Any run
with `MANIML_PERF_PATH` set counts every read as `raw` (`get_points`, the
interpolation of two endpoints) or `reduce` (bounding box, centre, endpoint,
tracker value), tagged by phase (`play`, `updater`, `idle`) and calling site.
`read_report.py` tabulates one or more profiles as markdown:

```bash
MANIML_PERF_PATH=/tmp/reads_B0.json python -m maniml 03_Code.py EpisodeB0 --render
python -m benchmarks.read_report /tmp/reads_B0.json
```

Render from a scratch copy of a course episode, never beside its own media.
The 2026-09-11 tables for EpisodeB0, A2 and A3 are in
`docs/read_instrumentation_2026-09-11.md`.

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

# Browser frames: tier 2's before number (2026-09-26)

The JavaScript the browser runs on every geometry message, measured on
the two course episodes' frames for a Phase A stream and a Phase B stream,
before the browser owns the frame (`docs/phase_b4_plan.md`, B4.6; tier 2
is B4.7 and B4.8). The native harness's episode rows
(`gpu_timestamps_20260926`, Episodes) cover Python and the GPU; these rows
are the third part of a live frame, taken on the same twelve pausepoints
per episode. The instrument is `benchmarks/browser_frames.py`
(`benchmarks/README.md`, "Browser frames"): each frame is serialized as
the viewer sends it into a stream in the export recorder's format, and the
stream is played in order through the real `maniml/web/static/webgpu.js`
in Node on the counting fake device (`tests/webgpu_fake_device.cjs`,
validation off), `performance.now` around the driver's render and every
WebGPU call tallied. No GPU is involved: nothing here is Dawn's per-call
work or the GPU's time, and the Scope section says what else it is not.

## Runs

From `/Users/taylorjweidman/Projects/ManimLive/maniml-b4b` (branch
`b4-tier2-browser`, commit `0a2bf3b2` = main, plus the B4.6 increment as
it stood before its review: `benchmarks/browser_frames.py`,
`benchmarks/browser_frames.cjs`, `tests/webgpu_fake_device.cjs` extracted
from `tests/generated_webgpu_commands.cjs`, the viewer's
`performance.measure`; `summary.json` `episodes.<scene>.source_files_sha256`
carries the hashes of what ran, identical for both episodes and unchanged
during each run, `maniml/web/static/webgpu.js` at `99148e04…`, the harness
at `b9f77150…`), interpreter `maniml/.venv/bin/python` (Python 3.13.9,
numpy as locked), Node v22.16.0, Apple M3 (8 cores, 24 GB), macOS 26.6.2,
one after the other, 23:05:11–23:05:53 UTC (EpisodeB2, 42 s wall including
the scene's load) and 23:05:53–23:06:22 UTC (PriceDiscovery, 29 s). The
committed increment differs from what ran in three files, none on the
recorded or timed path: `browser_frames.py` (the cold class worded as the
rows are, `scene.json`'s `lines` per recorded group rather than per
checkpoint, a `batches (cached)` column in the summary table; the
messages, their order and the replay are unchanged),
`webgpu_fake_device.cjs` (`queue.writeBuffer` asserts alignment, bounds
and `COPY_DST` under validation, which the benchmark runs off, and the
driver makes no such call today) and the `stream_scope` / `class_scope`
strings in `report.json` and `summary.json`, re-worded to match. A second
replay of the same streams after the review reproduced every count column
of every row exactly, `js` medians within load noise (8.a ticked 2.46
against 2.39 ms Phase A, 9.77 against 9.28 Phase B).

```bash
python -m benchmarks.browser_frames \
  --scene /Users/taylorjweidman/Projects/econ-0100/Blocks/B2_Supply/03_Code.py EpisodeB2 \
  --output <scratch>/B2 --samples 12 --warmups 3 --max-frames 12 --tick-updaters --play-frames
python -m benchmarks.browser_frames \
  --scene /Users/taylorjweidman/Projects/econ-0100/Blocks/B3_Equilibrium/Animate.py PriceDiscovery \
  --output <scratch>/B3 --samples 12 --warmups 3 --max-frames 12 --tick-updaters --play-frames
```

The frames are `episode_frames.select_frames`' twelve pausepoints per
episode, the same checkpoints as the native gate runs (EpisodeB2 12, 44,
76, 103, 120, 140, 157, 177, 194, 258, 277, 307; PriceDiscovery 9, 19, 35,
48, 58, 68, 86, 98, 109, 115, 123, 130), each restored as a navigation
shows it and serialized 3 + 12 times (the updaters ticking 1/fps before
every round where the pausepoint has any: EpisodeB2 3.i and 8.a,
PriceDiscovery every frame but 5.a), then the play into it replayed at
`camera.fps` with its middle 3 + 12 frames recorded (fewer on plays under
15 frames). Both constructs ran to their last checkpoint
(`construct_error` null). Per episode two streams, 2160x1080, 4x MSAA
plus the 2x resolve, one `GeometryCache` each: EpisodeB2 phase_a 330
messages, 105.0 MB (18.7 MB gzipped), phase_b 330 messages, 74.7 MB (9.1);
PriceDiscovery 316 messages, 57.8 MB (10.3) and 29.7 MB (3.9). The
streams are regenerable by the commands and are not archived. The machine
carried other sessions' CPU work at the time (a sibling worktree's build;
load average 3.8–4.2 read just after the runs, not sampled during them):
the still rows' minima sit within a few percent of their medians
(EpisodeB2 8.a ticked 2.33 against 2.39 ms, PriceDiscovery 3.a.5 1.01
against 1.02), the play rows' within 5–15%, so the medians below are not
contention artefacts, but they were not taken on a quiet machine.

## What a row is

One message rendered by `ManimlWGPU.render` in Node: `js` is the wall
clock around the call (header parse, `preparePaints` / `preparePrograms` /
`prepareBorders` / `prepareNets`, the encode loop, the fake `queue.submit`
and the retirement sweeps), the counts are the driver's WebGPU calls in
that frame, `wire` the message's bytes and `serialize` Python's
`serialize_scene` for the same message in the recording process (unpaced,
not the native harness's gate columns; orientation only). Four classes,
medians and minima over the measured rows with `n`: **pausepoint**, the
still redraw of the restored frame (rounds 4–15 after the restore, every
batch cached: what the viewer sends on a camera change), **ticked**, the
same rounds on a pausepoint whose updaters tick before each (what the idle
loop sends while any mobject has updaters), **play**, the recorded
mid-play frames, and **cold**, the first message after each restore,
delta-encoded against the message before it as a seek is against the frame
on screen (one `GeometryCache` spans the stream and is never reset), so it
uploads what the cache no longer held: `cached` in the tables says how
much it still held, and only the stream's first message and the frames
whose objects all changed upload everything (its own class, excluded from
the others; the rows are listed under Cold rows). Warmups are excluded
everywhere but cold. `batches (cached)` is the header's batch count and
the cached among them. `setPipeline (switches)` is every call and the
calls that changed the pass's pipeline; `bindGroups` is `createBindGroup`;
`buffers +/-` is `createBuffer` / `destroy`, temporaries included;
`uniform writes` is uniform buffers created with their data plus
`queue.writeBuffer` calls into one (none today); `KB up` is bytes mapped
at creation plus written.

## (i) Classes

**EpisodeB2** (531 mobjects at 8.a, 461 at 5.a; 12 frames)

| class | variant | n | js p50 / min | serialize p50 | wire KB p50 | batches (cached) | draws | setPipeline (switches) | bindGroups | buffers +/- | uniform writes | dispatches | KB up |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| pausepoint | phase_a | 120 | 1.26 / 0.56 | 5.9 | 69 | 166 (166) | 166 | 166 (138) | 1 | 0 / 0 | 0 | 0 | 0 |
| pausepoint | phase_b | 120 | 1.55 / 0.22 | 6.1 | 64 | 133 (133) | 305 | 305 (305) | 1 | 0 / 0 | 0 | 0 | 0 |
| ticked | phase_a | 24 | 2.15 / 1.44 | 25.3 | 129 | 314 (314) | 314 | 314 (271) | 1 | 0 / 0 | 0 | 0 | 0 |
| ticked | phase_b | 24 | 6.89 / 3.03 | 60.4 | 282 | 592 (592) | 1217 | 1217 (1217) | 1 | 0 / 0 | 0 | 0 | 0 |
| play | phase_a | 114 | 5.61 / 1.35 | 14.4 | 407 | 214 (48) | 215 | 245 (181) | 21 | 166 / 166 | 11 | 10 | 367 |
| play | phase_b | 114 | 3.41 / 0.37 | 13.5 | 133 | 278 (199) | 613 | 830 (813) | 166 | 100 / 100 | 100 | 99 | 2 |
| cold | phase_a | 12 | 15.33 / 4.47 | 50.0 | 650 | 184 (30) | 185 | 196 (160) | 41 | 266 / 116 | 22 | 20 | 1083 |
| cold | phase_b | 12 | 23.24 / 10.63 | 46.4 | 898 | 146 (1) | 345 | 418 (418) | 220 | 433 / 754 | 74 | 73 | 1784 |

**PriceDiscovery** (a `ThreeDScene`; 12 frames)

| class | variant | n | js p50 / min | serialize p50 | wire KB p50 | batches (cached) | draws | setPipeline (switches) | bindGroups | buffers +/- | uniform writes | dispatches | KB up |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| pausepoint | phase_a | 12 | 0.58 / 0.57 | 3.7 | 21 | 40 (40) | 41 | 41 (9) | 1 | 0 / 0 | 0 | 0 | 0 |
| pausepoint | phase_b | 12 | 0.71 / 0.71 | 3.5 | 22 | 45 (45) | 147 | 147 (147) | 1 | 0 / 0 | 0 | 0 | 0 |
| ticked | phase_a | 132 | 1.03 / 0.79 | 6.8 | 45 | 105 (105) | 118 | 118 (50) | 1 | 0 / 0 | 0 | 0 | 0 |
| ticked | phase_b | 132 | 1.84 / 0.59 | 6.6 | 64 | 132 (132) | 366 | 366 (307) | 1 | 0 / 0 | 0 | 0 | 0 |
| play | phase_a | 100 | 1.81 / 1.05 | 8.9 | 184 | 105 (83) | 118 | 126 (53) | 5 | 19 / 19 | 3 | 2 | 151 |
| play | phase_b | 100 | 2.81 / 1.58 | 5.7 | 75 | 148 (148) | 388 | 491 (491) | 236 | 144 / 144 | 144 | 140 | 4 |
| cold | phase_a | 12 | 4.92 / 1.67 | 29.6 | 622 | 100 (72) | 110 | 126 (54) | 30 | 75 / 55 | 22 | 8 | 815 |
| cold | phase_b | 12 | 13.97 / 5.10 | 25.9 | 408 | 132 (90) | 356 | 416 (356) | 136 | 275 / 512 | 70 | 51 | 757 |

The medians of a class are over rows of frames of very different size
(45 to 495 batches), so they are a roll-up, not a frame; the per-frame
tables are the numbers. The cold medians in particular roll up seeks
from very different cache states (Cold rows, below).

## (ii) Per frame

`js p50 / min` in ms; batches and draws are the frame's; `α` is the range
of the play's frames recorded and the count in parentheses its length.
"Drawn" is the frame's mobjects with points.

**EpisodeB2**

| frame | checkpoint (line) | beat | drawn | class | phase_a js p50 / min | phase_a batches | phase_a draws | phase_a setPipeline | phase_a bindGroups | phase_a buffers +/- | phase_a KB up | phase_b js p50 / min | phase_b batches | phase_b draws | phase_b setPipeline | phase_b bindGroups | phase_b buffers +/- | phase_b KB up |
|---|---|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 | 12 (36) | 0.a | 258 | pausepoint | 2.58 / 2.29 | 436 | 437 | 437 | 1 | 0 / 0 | 0 | 5.23 / 4.58 | 423 | 855 | 855 | 1 | 0 / 0 | 0 |
| 0 | 12 (36) | 0.a | 258 | play α 0.27–1.00 (15) | 13.28 / 11.74 | 469 | 470 | 503 | 67 | 166 / 166 | 662 | 6.25 / 5.31 | 456 | 1020 | 1119 | 166 | 100 / 100 | 2 |
| 0 | 12 (36) | 0.a | 258 | cold | 28.76 / 28.76 | 436 | 437 | 451 | 32 | 707 / 15 | 1470 | 32.09 / 32.09 | 423 | 855 | 1067 | 641 | 1277 / 213 | 1812 |
| 1 | 44 (215) | 2.h | 148 | pausepoint | 0.96 / 0.94 | 146 | 147 | 147 | 1 | 0 / 0 | 0 | 1.40 / 1.35 | 124 | 273 | 273 | 1 | 0 / 0 | 0 |
| 1 | 44 (215) | 2.h | 148 | play α 0.27–1.00 (15) | 3.99 / 3.55 | 156 | 157 | 167 | 21 | 231 / 231 | 211 | 2.65 / 2.51 | 136 | 319 | 529 | 351 | 211 / 211 | 5 |
| 1 | 44 (215) | 2.h | 148 | cold | 16.37 / 16.37 | 146 | 147 | 171 | 49 | 303 / 714 | 1157 | 14.65 / 14.65 | 124 | 273 | 335 | 187 | 376 / 1420 | 1172 |
| 2 | 76 (351) | 3.i | 295 | ticked | 1.49 / 1.44 | 183 | 184 | 184 | 1 | 0 / 0 | 0 | 3.38 / 3.03 | 274 | 593 | 593 | 1 | 0 / 0 | 0 |
| 2 | 76 (351) | 3.i | 295 | play α 0.27–1.00 (15) | 2.55 / 2.45 | 183 | 184 | 188 | 9 | 21 / 21 | 74 | 3.27 / 3.13 | 278 | 613 | 625 | 21 | 13 / 13 | 0 |
| 2 | 76 (351) | 3.i | 295 | cold | 23.33 / 23.33 | 183 | 184 | 240 | 113 | 286 / 146 | 1578 | 35.43 / 35.43 | 274 | 593 | 729 | 409 | 818 / 777 | 2177 |
| 3 | 103 (622) | 4.c.1 | 79 | pausepoint | 0.57 / 0.56 | 45 | 46 | 46 | 1 | 0 / 0 | 0 | 0.22 / 0.22 | 10 | 57 | 57 | 1 | 0 / 0 | 0 |
| 3 | 103 (622) | 4.c.1 | 79 | play α 0.44–1.00 (9) | 2.83 / 2.81 | 45 | 46 | 55 | 19 | 49 / 49 | 154 | 0.48 / 0.47 | 19 | 92 | 122 | 51 | 31 / 31 | 1 |
| 3 | 103 (622) | 4.c.1 | 79 | cold | 14.88 / 14.88 | 45 | 46 | 84 | 77 | 199 / 444 | 1020 | 10.63 / 10.63 | 10 | 57 | 62 | 16 | 35 / 730 | 980 |
| 4 | 120 (622) | 4.b.2 | 122 | pausepoint | 0.66 / 0.65 | 50 | 51 | 51 | 1 | 0 / 0 | 0 | 0.25 / 0.25 | 8 | 53 | 53 | 1 | 0 / 0 | 0 |
| 4 | 120 (622) | 4.b.2 | 122 | play α 0.44–1.00 (9) | 2.32 / 2.20 | 56 | 57 | 64 | 15 | 37 / 37 | 104 | 0.44 / 0.43 | 14 | 83 | 106 | 40 | 24 / 24 | 1 |
| 4 | 120 (622) | 4.b.2 | 122 | cold | 15.79 / 15.79 | 50 | 51 | 75 | 49 | 126 / 69 | 1147 | 16.59 / 16.59 | 8 | 53 | 57 | 13 | 28 / 118 | 1612 |
| 5 | 140 (622) | 4.b.4 | 122 | pausepoint | 0.66 / 0.66 | 50 | 51 | 51 | 1 | 0 / 0 | 0 | 0.25 / 0.25 | 8 | 53 | 53 | 1 | 0 / 0 | 0 |
| 5 | 140 (622) | 4.b.4 | 122 | play α 0.44–1.00 (9) | 2.37 / 2.16 | 56 | 57 | 64 | 15 | 37 / 37 | 104 | 0.44 / 0.43 | 14 | 83 | 106 | 40 | 24 / 24 | 1 |
| 5 | 140 (622) | 4.b.4 | 122 | cold | 4.47 / 4.47 | 50 | 51 | 59 | 17 | 46 / 46 | 271 | 16.67 / 16.67 | 8 | 53 | 57 | 13 | 28 / 91 | 1612 |
| 6 | 157 (622) | 4.return.5 | 223 | pausepoint | 1.28 / 1.26 | 185 | 186 | 186 | 1 | 0 / 0 | 0 | 1.61 / 1.59 | 142 | 337 | 337 | 1 | 0 / 0 | 0 |
| 6 | 157 (622) | 4.return.5 | 223 | play α 0.33–1.00 (12) | 8.24 / 7.56 | 214 | 215 | 245 | 61 | 361 / 361 | 466 | 3.26 / 3.23 | 189 | 483 | 813 | 561 | 331 / 331 | 7 |
| 6 | 157 (622) | 4.return.5 | 223 | cold | 8.59 / 8.59 | 185 | 186 | 193 | 15 | 246 / 45 | 699 | 22.85 / 22.85 | 142 | 337 | 408 | 214 | 423 / 158 | 2041 |
| 7 | 177 (622) | 4.return.7 | 229 | pausepoint | 1.30 / 1.29 | 193 | 194 | 194 | 1 | 0 / 0 | 0 | 1.67 / 1.66 | 150 | 353 | 353 | 1 | 0 / 0 | 0 |
| 7 | 177 (622) | 4.return.7 | 229 | play α 0.33–1.00 (12) | 8.21 / 7.72 | 222 | 223 | 253 | 61 | 373 / 373 | 472 | 3.37 / 3.30 | 199 | 501 | 847 | 589 | 347 / 347 | 7 |
| 7 | 177 (622) | 4.return.7 | 229 | cold | 4.90 / 4.90 | 193 | 194 | 200 | 13 | 48 / 36 | 103 | 23.62 / 23.62 | 150 | 353 | 428 | 226 | 443 / 1072 | 2049 |
| 8 | 194 (622) | 4.d.9 | 132 | pausepoint | 0.80 / 0.79 | 62 | 63 | 63 | 1 | 0 / 0 | 0 | 0.31 / 0.31 | 12 | 76 | 76 | 1 | 0 / 0 | 0 |
| 8 | 194 (622) | 4.d.9 | 132 | play α 0.44–1.00 (9) | 1.36 / 1.35 | 62 | 63 | 65 | 5 | 14 / 14 | 43 | 0.37 / 0.37 | 14 | 81 | 90 | 16 | 10 / 10 | 0 |
| 8 | 194 (622) | 4.d.9 | 132 | cold | 6.80 / 6.80 | 62 | 63 | 79 | 33 | 92 / 267 | 420 | 18.70 / 18.70 | 12 | 76 | 82 | 19 | 42 / 1049 | 1756 |
| 9 | 258 (685) | 4.h | 362 | pausepoint | 1.94 / 1.88 | 294 | 295 | 295 | 1 | 0 / 0 | 0 | 3.82 / 3.74 | 363 | 779 | 779 | 1 | 0 / 0 | 0 |
| 9 | 258 (685) | 4.h | 362 | play α 0.27–1.00 (15) | 8.59 / 1.89 | 322 | 323 | 351 | 57 | 142 / 142 | 420 | 4.62 / 4.54 | 392 | 920 | 1006 | 145 | 87 / 87 | 2 |
| 9 | 258 (685) | 4.h | 362 | cold | 11.52 / 11.52 | 294 | 295 | 308 | 27 | 430 / 85 | 794 | 28.18 / 28.18 | 363 | 779 | 961 | 547 | 1040 / 239 | 2235 |
| 10 | 277 (762) | 5.a | 461 | pausepoint | 4.10 / 3.94 | 495 | 496 | 496 | 1 | 0 / 0 | 0 | 4.84 / 4.79 | 463 | 1738 | 1738 | 1 | 0 / 0 | 0 |
| 10 | 277 (762) | 5.a | 461 | play α 0.27–1.00 (15) | 56.54 / 55.38 | 537 | 538 | 767 | 459 | 1607 / 1607 | 3457 | 14.02 / 13.61 | 692 | 2073 | 3456 | 2306 | 1384 / 1384 | 29 |
| 10 | 277 (762) | 5.a | 461 | cold | 55.09 / 55.09 | 495 | 496 | 683 | 375 | 1397 / 753 | 3680 | 45.96 / 45.96 | 463 | 1738 | 1970 | 697 | 1043 / 1052 | 3918 |
| 11 | 307 (1016) | 8.a | 531 | ticked | 2.39 / 2.33 | 444 | 445 | 445 | 1 | 0 / 0 | 0 | 9.28 / 8.96 | 911 | 1841 | 1841 | 1 | 0 / 0 | 0 |
| 11 | 307 (1016) | 8.a | 531 | play α 0.36–0.84 (23) | 5.07 / 4.98 | 446 | 447 | 456 | 19 | 350 / 350 | 365 | 23.33 / 22.64 | 903 | 1825 | 2176 | 1052 | 2104 / 2097 | 918 |
| 11 | 307 (1016) | 8.a | 531 | cold | 17.27 / 17.27 | 444 | 445 | 487 | 85 | 814 / 1148 | 1300 | 29.69 / 29.69 | 911 | 1841 | 2297 | 1369 | 2738 / 4573 | 1461 |

**PriceDiscovery**

| frame | checkpoint (line) | beat | drawn | class | phase_a js p50 / min | phase_a batches | phase_a draws | phase_a setPipeline | phase_a bindGroups | phase_a buffers +/- | phase_a KB up | phase_b js p50 / min | phase_b batches | phase_b draws | phase_b setPipeline | phase_b bindGroups | phase_b buffers +/- | phase_b KB up |
|---|---|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 | 9 (279) | 0.a | 148 | ticked | 0.86 / 0.82 | 79 | 80 | 80 | 1 | 0 / 0 | 0 | 1.64 / 1.53 | 105 | 164 | 164 | 1 | 0 / 0 | 0 |
| 0 | 9 (279) | 0.a | 148 | play α 0.27–1.00 (15) | 1.70 / 1.65 | 80 | 81 | 83 | 5 | 11 / 11 | 37 | 1.67 / 1.58 | 106 | 169 | 175 | 11 | 7 / 7 | 0 |
| 0 | 9 (279) | 0.a | 148 | cold | 20.34 / 20.34 | 79 | 80 | 115 | 77 | 226 / 36 | 1614 | 26.83 / 26.83 | 105 | 164 | 247 | 196 | 448 / 86 | 1457 |
| 1 | 19 (426) | 1.b | 155 | ticked | 0.88 / 0.86 | 56 | 64 | 64 | 1 | 0 / 0 | 0 | 0.63 / 0.59 | 25 | 111 | 111 | 1 | 0 / 0 | 0 |
| 1 | 19 (426) | 1.b | 155 | play α 0.27–1.00 (15) | 16.47 / 14.71 | 120 | 128 | 193 | 131 | 327 / 327 | 901 | 3.05 / 2.74 | 89 | 426 | 623 | 330 | 198 / 198 | 4 |
| 1 | 19 (426) | 1.b | 155 | cold | 30.49 / 30.49 | 56 | 64 | 84 | 51 | 126 / 122 | 1653 | 23.84 / 23.84 | 25 | 111 | 127 | 55 | 111 / 386 | 1409 |
| 2 | 35 (739) | 2.b.i | 206 | ticked | 1.03 / 0.96 | 71 | 87 | 87 | 1 | 0 / 0 | 0 | 1.02 / 0.99 | 61 | 211 | 211 | 1 | 0 / 0 | 0 |
| 2 | 35 (739) | 2.b.i | 206 | play α 0.38–1.05 (11) | 7.27 / 6.85 | 88 | 104 | 126 | 45 | 114 / 114 | 459 | 1.83 / 1.76 | 80 | 296 | 366 | 119 | 72 / 72 | 2 |
| 2 | 35 (739) | 2.b.i | 206 | cold | 22.37 / 22.37 | 71 | 87 | 137 | 82 | 159 / 118 | 1407 | 22.52 / 22.52 | 61 | 211 | 251 | 118 | 232 / 712 | 1616 |
| 3 | 48 (1179) | 3.a.1 | 199 | ticked | 0.81 / 0.79 | 85 | 88 | 88 | 1 | 0 / 0 | 0 | 2.24 / 2.06 | 165 | 323 | 323 | 1 | 0 / 0 | 0 |
| 3 | 48 (1179) | 3.a.1 | 199 | play α 0.44–1.00 (9) | 1.47 / 1.41 | 85 | 88 | 90 | 5 | 17 / 17 | 106 | 2.92 / 2.80 | 184 | 331 | 477 | 250 | 149 / 149 | 4 |
| 3 | 48 (1179) | 3.a.1 | 199 | cold | 6.27 / 6.27 | 85 | 88 | 125 | 65 | 158 / 183 | 1211 | 16.36 / 16.36 | 165 | 323 | 437 | 292 | 627 / 503 | 1104 |
| 4 | 58 (1179) | 3.a.3 | 215 | ticked | 0.96 / 0.93 | 95 | 102 | 102 | 1 | 0 / 0 | 0 | 2.46 / 2.36 | 174 | 376 | 376 | 1 | 0 / 0 | 0 |
| 4 | 58 (1179) | 3.a.3 | 215 | play α 0.44–1.00 (9) | 1.56 / 1.50 | 95 | 102 | 104 | 5 | 19 / 19 | 143 | 3.00 / 2.80 | 193 | 384 | 534 | 256 | 154 / 154 | 4 |
| 4 | 58 (1179) | 3.a.3 | 215 | cold | 2.95 / 2.95 | 95 | 102 | 108 | 26 | 67 / 40 | 320 | 12.38 / 12.38 | 174 | 376 | 427 | 159 | 309 / 516 | 410 |
| 5 | 68 (1179) | 3.a.5 | 233 | ticked | 1.02 / 1.01 | 105 | 118 | 118 | 1 | 0 / 0 | 0 | 2.40 / 2.26 | 182 | 438 | 438 | 1 | 0 / 0 | 0 |
| 5 | 68 (1179) | 3.a.5 | 233 | play α 0.44–1.00 (9) | 1.73 / 1.71 | 105 | 118 | 120 | 5 | 19 / 19 | 152 | 3.07 / 2.90 | 201 | 446 | 596 | 256 | 154 / 154 | 4 |
| 5 | 68 (1179) | 3.a.5 | 233 | cold | 3.56 / 3.56 | 105 | 118 | 126 | 30 | 77 / 46 | 351 | 7.07 / 7.07 | 182 | 438 | 491 | 163 | 318 / 536 | 333 |
| 6 | 86 (1179) | 3.a.8 | 235 | ticked | 1.03 / 1.01 | 107 | 122 | 122 | 1 | 0 / 0 | 0 | 2.28 / 2.23 | 182 | 448 | 448 | 1 | 0 / 0 | 0 |
| 6 | 86 (1179) | 3.a.8 | 235 | play α 0.44–1.00 (9) | 1.65 / 1.63 | 107 | 122 | 124 | 5 | 19 / 19 | 150 | 2.96 / 2.89 | 201 | 456 | 606 | 256 | 154 / 154 | 4 |
| 6 | 86 (1179) | 3.a.8 | 235 | cold | 3.25 / 3.25 | 107 | 122 | 130 | 30 | 73 / 64 | 381 | 7.02 / 7.02 | 182 | 448 | 499 | 154 | 311 / 552 | 361 |
| 7 | 98 (1179) | 3.a.10 | 212 | ticked | 1.03 / 1.02 | 107 | 122 | 122 | 1 | 0 / 0 | 0 | 1.72 / 1.69 | 128 | 346 | 346 | 1 | 0 / 0 | 0 |
| 7 | 98 (1179) | 3.a.10 | 212 | play α 0.44–1.00 (9) | 1.05 / 1.05 | 107 | 122 | 122 | 1 | 6 / 6 | 108 | 2.03 / 2.01 | 146 | 355 | 411 | 100 | 59 / 59 | 2 |
| 7 | 98 (1179) | 3.a.10 | 212 | cold | 1.67 / 1.67 | 107 | 122 | 124 | 5 | 32 / 33 | 317 | 5.10 / 5.10 | 128 | 346 | 370 | 56 | 129 / 508 | 302 |
| 8 | 109 (1179) | 3.a.12 | 245 | ticked | 1.12 / 1.10 | 113 | 132 | 132 | 1 | 0 / 0 | 0 | 2.36 / 2.31 | 186 | 484 | 484 | 1 | 0 / 0 | 0 |
| 8 | 109 (1179) | 3.a.12 | 245 | play α 0.44–1.00 (9) | 1.68 / 1.67 | 113 | 132 | 134 | 5 | 19 / 19 | 144 | 3.02 / 2.89 | 205 | 492 | 642 | 256 | 154 / 154 | 4 |
| 8 | 109 (1179) | 3.a.12 | 245 | cold | 2.66 / 2.66 | 113 | 132 | 138 | 26 | 67 / 46 | 420 | 6.96 / 6.96 | 186 | 484 | 539 | 160 | 325 / 318 | 397 |
| 9 | 115 (1215) | 3.b.1 | 222 | ticked | 1.11 / 1.09 | 113 | 132 | 132 | 1 | 0 / 0 | 0 | 1.76 / 1.75 | 132 | 382 | 382 | 1 | 0 / 0 | 0 |
| 9 | 115 (1215) | 3.b.1 | 222 | play α 0.38–1.05 (11) | 1.14 / 1.13 | 113 | 132 | 132 | 1 | 6 / 6 | 108 | 2.05 / 2.03 | 150 | 391 | 447 | 100 | 59 / 59 | 2 |
| 9 | 115 (1215) | 3.b.1 | 222 | cold | 1.73 / 1.73 | 113 | 132 | 134 | 5 | 34 / 35 | 398 | 5.59 / 5.59 | 132 | 382 | 412 | 68 | 159 / 538 | 380 |
| 10 | 123 (1236) | 3.b | 257 | ticked | 1.48 / 1.37 | 124 | 143 | 143 | 1 | 0 / 0 | 0 | 1.80 / 1.79 | 131 | 366 | 366 | 1 | 0 / 0 | 0 |
| 10 | 123 (1236) | 3.b | 257 | play α 0.27–1.00 (15) | 14.47 / 13.11 | 166 | 185 | 240 | 111 | 276 / 276 | 786 | 3.39 / 3.28 | 185 | 626 | 791 | 276 | 166 / 166 | 4 |
| 10 | 123 (1236) | 3.b | 257 | cold | 18.03 / 18.03 | 124 | 143 | 174 | 73 | 188 / 140 | 1578 | 16.66 / 16.66 | 131 | 366 | 419 | 114 | 241 / 383 | 1389 |
| 11 | 130 (1275) | 5.a | 184 | pausepoint | 0.58 / 0.57 | 40 | 41 | 41 | 1 | 0 / 0 | 0 | 0.71 / 0.71 | 45 | 147 | 147 | 1 | 0 / 0 | 0 |
| 11 | 130 (1275) | 5.a | 184 | play α 0.27–1.00 (15) | 10.73 / 10.55 | 83 | 84 | 127 | 87 | 216 / 216 | 607 | 1.95 / 1.91 | 88 | 362 | 491 | 216 | 130 / 130 | 3 |
| 11 | 130 (1275) | 5.a | 184 | cold | 20.21 / 20.21 | 40 | 41 | 42 | 3 | 9 / 148 | 1593 | 15.57 / 15.57 | 45 | 147 | 149 | 7 | 14 / 841 | 1388 |

## (iii) Cold rows

The stream's one `GeometryCache` is never reset, so each frame's first
message is encoded against the message before it: the last recorded frame
of the play into the previous measured checkpoint (the stream's first
message against nothing). A cold row is therefore a seek from that frame,
as the viewer's seek is from the frame on screen, and what it uploads is
what that frame did not leave in the cache. `cached / batches` is the
count of cached batches in the header.

**EpisodeB2**

| frame | beat | phase_a cached / batches | phase_a js | phase_a KB up | phase_b cached / batches | phase_b js | phase_b KB up |
|---|---|---:|---:|---:|---:|---:|---:|
| 0 | 0.a | 0 / 436 | 28.76 | 1470 | 0 / 423 | 32.09 | 1812 |
| 1 | 2.h | 0 / 146 | 16.37 | 1157 | 0 / 124 | 14.65 | 1172 |
| 2 | 3.i | 123 / 183 | 23.33 | 1578 | 4 / 274 | 35.43 | 2177 |
| 3 | 4.c.1 | 1 / 45 | 14.88 | 1020 | 1 / 10 | 10.63 | 980 |
| 4 | 4.b.2 | 22 / 50 | 15.79 | 1147 | 1 / 8 | 16.59 | 1612 |
| 5 | 4.b.4 | 38 / 50 | 4.47 | 271 | 1 / 8 | 16.67 | 1612 |
| 6 | 4.return.5 | 38 / 185 | 8.59 | 699 | 1 / 142 | 22.85 | 2041 |
| 7 | 4.return.7 | 174 / 193 | 4.90 | 103 | 1 / 150 | 23.62 | 2049 |
| 8 | 4.d.9 | 38 / 62 | 6.80 | 420 | 1 / 12 | 18.70 | 1756 |
| 9 | 4.h | 38 / 294 | 11.52 | 794 | 1 / 363 | 28.18 | 2235 |
| 10 | 5.a | 0 / 495 | 55.09 | 3680 | 176 / 463 | 45.96 | 3918 |
| 11 | 8.a | 0 / 444 | 17.27 | 1300 | 0 / 911 | 29.69 | 1461 |

**PriceDiscovery**

| frame | beat | phase_a cached / batches | phase_a js | phase_a KB up | phase_b cached / batches | phase_b js | phase_b KB up |
|---|---|---:|---:|---:|---:|---:|---:|
| 0 | 0.a | 0 / 79 | 20.34 | 1614 | 0 / 105 | 26.83 | 1457 |
| 1 | 1.b | 24 / 56 | 30.49 | 1653 | 3 / 25 | 23.84 | 1409 |
| 2 | 2.b.i | 36 / 71 | 22.37 | 1407 | 8 / 61 | 22.52 | 1617 |
| 3 | 3.a.1 | 25 / 85 | 6.27 | 1211 | 5 / 165 | 16.36 | 1104 |
| 4 | 3.a.3 | 71 / 95 | 2.95 | 320 | 90 / 174 | 12.38 | 410 |
| 5 | 3.a.5 | 79 / 105 | 3.56 | 351 | 96 / 182 | 7.07 | 333 |
| 6 | 3.a.8 | 83 / 107 | 3.25 | 381 | 98 / 182 | 7.02 | 361 |
| 7 | 3.a.10 | 87 / 107 | 1.67 | 317 | 101 / 128 | 5.10 | 302 |
| 8 | 3.a.12 | 87 / 113 | 2.66 | 420 | 101 / 186 | 6.96 | 397 |
| 9 | 3.b.1 | 90 / 113 | 1.73 | 398 | 99 / 132 | 5.59 | 380 |
| 10 | 3.b | 72 / 124 | 18.03 | 1578 | 90 / 131 | 16.66 | 1389 |
| 11 | 5.a | 37 / 40 | 20.21 | 1593 | 42 / 45 | 15.57 | 1388 |

Split by cache state: on EpisodeB2 Phase A the four rows with nothing
cached (0.a, 2.h, 5.a, 8.a) are 23.02 ms / 1385 KB at the median and the
eight partly cached rows 10.05 ms / 746 KB with a median 53% of their
batches cached; Phase B's three uncached rows (0.a, 2.h, 8.a) are 29.69
ms / 1461 KB and its nine partly cached 22.85 ms / 2041 KB at 8% cached (a
patch run's records change with its objects' rows, so the diagram beats
share almost nothing with the play frame before them). On PriceDiscovery
only 0.a arrives uncached (20.34 / 26.83 ms, 1614 / 1457 KB); the other
eleven rows are 3.56 ms / 420 KB at 75% cached (Phase A) and 12.38 ms /
410 KB at 54% (Phase B). The class medians above (15.33 / 23.24 and 4.92 /
13.97 ms) mix the two; the fully uncached rows are the connect /
`geometry_reset` cost, the partial ones a seek between neighbouring
frames.

## Reading

**The still frame.** A redraw of an unchanged frame, every batch cached
(what the viewer sends on a camera change, and on every idle tick where
the updaters change no bytes), costs the browser 0.57 ms at 45 batches,
2.58 ms at 436 and 4.10 ms at 495 on Phase A (EpisodeB2), and on the
closing 8.a diagram **2.39 ms at 444 batches (Phase A) against 9.28 ms at
911 batches / 1841 draws (Phase B)** — the plan's 2.2 / 8.0 ms, with the
counting device's few tallies per call on top. Nothing is uploaded and no
buffer is made, yet per frame the driver parses a 179 KB (Phase A) or 434
KB (Phase B) header (0.37 / 0.92 ms of the 2.39 / 9.28), walks every batch
six times (`preparePaints`, `preparePrograms`, `prepareBorders`,
`prepareNets`, the encode loop and the texture-hash sweep before
retirement), rebuilds a 48-word uniform key per batch, issues one
`setPipeline` per draw (445 calls for 445 draws; 1841 for 1841) and one
`setBindGroup` per draw or more (445; 2300 on Phase B, several per patch
group), creates one bind group (the present pass's) and sweeps a dozen
caches. That is the JavaScript tier 2 removes: after B4.7 a
still frame is a resolved slot list re-encoded with the pipeline set once
per run of equal slots and no per-batch key; after B4.8 it is not sent at
all (the gate "JS at rest 0", "wire at rest 0 B" against 179 / 434 KB per
tick here).

**Per draw** the cost is flat: 5.4 µs per draw on Phase A's still 8.a
(2.39 / 445) and 5.0 µs on Phase B's (9.28 / 1841), 5.9 µs on 0.a's 437
draws and 8.3 µs on 5.a's 496 (Phase A; 5.a's batches are heavier: 2.8 µs
per draw on Phase B's 1738). Phase B's browser time at a still frame is
therefore its draw count: 2.0–4.1× Phase A's draws at the same beat (1841
against 445 at 8.a, 1738 against 496 at 5.a, 855 against 437 at 0.a), each
a `setPipeline`, because a patch group is three to five draws on
alternating pipelines (every one of Phase B's `setPipeline` calls is a
switch; on Phase A 138 of 166 are). This is the browser-side reading of
B5.2's condition ("only if B4.6's browser number shows the draw count
mattering once the draw list is retained"): today it matters at ~5 µs a
draw in JavaScript before Dawn; whether it still does after B4.7's
retained encode is what B4.7 measures.

**Ticked pausepoints.** On both 8.a and 3.i (EpisodeB2) and on every
ticked PriceDiscovery frame the rows carry no upload at all: the updaters
bump revisions (the plan's over-signal, 415 of 531 leaves at 8.a) but the
bytes do not change, so the messages are cached redraws; Python still paid
37.8 ms (Phase A) and 95.7 ms (Phase B) per tick to serialize them
(`serialize` column), the browser 2.39 / 9.28 ms to redraw them. The
ticked class medians (2.15 / 6.89 ms on EpisodeB2, 1.03 / 1.84 on
PriceDiscovery) are those redraws.

**Plays.** Phase A's play frames upload their movers' re-tessellated
fills: 367 KB and 166 buffers per frame at the EpisodeB2 median, 3.4 MB /
1607 buffers / 56.5 ms on the 5.a play (0 of 537 batches cached: the whole
diagram moves), 0.9 MB / 327 buffers / 16.5 ms on PriceDiscovery's 1.b
play; the browser's play time follows the upload (`makeBuffer` with
`mappedAtCreation` and the copy into it) plus a border compute pass per
changed run. Phase B's play frames upload almost nothing (2–29 KB per
frame: the program scalars and object records) and cost 3.41 ms at the
median, but each program is a compute pass with its own temporary uniform
buffers and bind groups, made and destroyed every frame: 100 uniform
writes / 166 bind groups per frame at the median, **1384 uniform writes,
2306 bind groups, 3456 `setPipeline` and 5300 `setBindGroup` calls per
frame on the 5.a play (14.0 ms)**, and 2104 buffers created and destroyed
per frame on the 8.a play (23.3 ms; 700 of its 903 batches arrive
uncached, movers the program path does not cover, and re-send their
records, 918 KB). That churn is the "no
per-frame uniform buffer churn" of B4.7 (persistent per-set uniform
buffers written in place). On the light beats Phase B is cheaper than
Phase A in the browser (4.c.1's play 0.48 against 2.83 ms, 8 draws against
46 at rest), on the heavy ones dearer (8.a's play 23.3 against 5.1 ms; the
still 8.a 9.3 against 2.4).

**Seeks.** The first message after a restore uploads what the browser
lacks, and what it lacks depends on where the seek came from (Cold rows):
the stream's cache is never reset, so a cold row is a seek from the last
recorded frame of the previous measured frame's play, not a connect. Where
nothing was cached — 0.a, 2.h, 5.a and 8.a on EpisodeB2 Phase A — a seek
is 23 ms / 1.4 MB at the median (17.3 ms / 1.3 MB / 814 buffers at 8.a;
5.a's 3.7 MB and 55 ms the worst); where the frame before left most of
the diagram in the cache it is 4.5–5 ms (4.b.4, 4.return.7). The class
medians, 15.3 ms / 1.1 MB / 266 buffers (Phase A) and 23.2 ms / 1.8 MB /
433 buffers (Phase B; more buffers because every patch run carries
records, an object table and an output), PriceDiscovery 4.9 / 14.0 ms, mix
the two. Tier 1 makes a seek cheap in Python (digest adoption); the
browser's seek stays an upload until the wire carries only what changed
(B4.8) and what it retains survives a seek (B4.7's refcounts against
today's "retire everything absent" sweep, which is why a cold row also
destroys hundreds of buffers: 1148 on 8.a, 4573 on Phase B's).

**The wire.** A still message is 23–217 KB (Phase A) / 4–220 KB (Phase B)
of header per frame on EpisodeB2 (69 / 64 KB median), 179 / 434 KB at 8.a;
a play frame 407 / 133 KB median; a cold one 650 / 898 KB. These are the
bytes B4.8's deltas are measured against ("a camera move < 1 KB").

## Scope and caveats

- **Not Dawn, not the GPU.** The fake device tallies the driver's calls
  and does nothing with them; Chrome's WebGPU implementation validates and
  encodes each call (the per-draw cost B4.9 waits on) and the GPU draws
  the frame (`gpu_timestamps_20260926` has that side natively: 4.8 ms
  Phase A / 6.8 ms Phase B on the 8.a frame). The count columns are what
  Dawn would be handed per frame.
- **Node's V8, not Chrome's.** Same engine, a different process: no
  render-thread contention, no Chrome heap. The live number is the
  viewer's own `performance.measure("maniml:render")` span in DevTools
  (added with this increment), which also contains the second header
  parse in `renderer_selection.js` and any wait behind an earlier frame in
  the session's chain; neither is in `js` here. Node's garbage collector
  runs where it runs (the play rows' spreads of 5–15% between minimum and
  median are mostly that) and V8 warms over the stream's first frames (the
  three warmup rounds per group are excluded; the first group's cold row
  also carries the pipelines' creation).
- **Validation off, and the fake's own share.** The command tests run the
  same device with its submission-time asserts and command records; the
  benchmark runs it with `validate: false` so a timed frame pays for the
  driver alone. The driver's behaviour is identical and the tallies are
  the same either way (the totals agree on both streams); validation on
  adds 2–15% to `js`. The counting itself is within noise: a null device
  (no counters, no records, only the `ArrayBuffer` the driver copies
  into) over both EpisodeB2 streams, two passes each, gives 8.a still
  2.29–2.33 ms against the counting device's 2.36–2.39 (Phase A) and
  9.27–9.33 against 9.15–9.28 (Phase B), the 5.a play 54.5–56.2 against
  55.1–55.6, the cold class 14.8–15.4 against 15.7–16.5 and 23.0–23.4
  against 23.3–23.7 — within run-to-run spread (≤ 3%). `JSON.parse` of
  the header is 0.37 ms of the Phase A
  8.a still's 2.39 and 0.92 of Phase B's 9.28: the part of `js` tier 2
  cannot remove until B4.8 stops sending the header.
- **The stream is not the socket.** A repeated still frame is what the
  viewer sends on a camera change or an idle tick with updaters; at rest
  without either the viewer sends nothing and the browser runs nothing,
  and that silence is not a row. Per checkpoint the stream is the cold
  row, the stills, then the play into that checkpoint, whereas a viewer
  sees the play and then the landing: the cold row is encoded against the
  previous frame's play state (Cold rows) and the play window's warmup
  frames against the destination pausepoint's stills; the measured play
  rows follow the previous play frame as on the socket. No row carries a
  camera change: the still rows are a camera move's bytes and per-batch
  work but not its creations (the uniform key includes the camera, so a
  real move would also create and retire a uniform buffer and bind group
  per distinct override set × pipeline — 2 sets among 444 batches at
  8.a); a camera-move round would give B4.7's persistent uniform buffers
  and B4.8's "< 1 KB" gate a before row. The ticked rows are real sends
  (the viewer streams on `should_update_mobjects()` at its send interval)
  that change no bytes. Texture decode is a stub; neither episode sends
  textures on these frames. The recording serializes with the variant's
  `MANIML_*` switches set (`environments` in `summary.json`), so the
  Phase B stream is what the viewer's Phase B selector would send, with
  the header stamped `triangles` so the player and the recording indexer
  read it.
- **Players.** `tests/player_commands.cjs export` over the streams
  (PriceDiscovery Phase A, 316 frames, 656 renders; EpisodeB2 Phase B,
  330 frames, 684 renders) and `generated_webgpu_commands.cjs
  recordingReplay` with validation on (739 and 772 renders) exit 0 with
  zero cache misses, and both EpisodeB2 streams replay clean under the
  fake's validation (no buffer used after destroy, no double destroy, 0
  live buffers after teardown). The streams' `scene.json` was written
  with `lines` per checkpoint; the committed harness writes them per
  recorded group so the player's chips name the frames (the frames and
  their order are the same).
- **For B4.7's review.** Keep the archive's commands and diff
  `report.json`'s count columns per frame against this archive:
  `set_pipeline_calls` / `pipeline_switches`, `uniform_writes`,
  `uniform_buffers_created`, `bind_groups_created` and `buffers_created`
  / `buffers_destroyed` are expected to move; `draws`,
  `compute_dispatches` and `bytes_uploaded` are not. Steady state today: 1
  bind group (the present pass) and 0 buffers per still frame in both
  variants; Phase B plays create 100 uniform buffers and 166 bind groups
  per frame at the EpisodeB2 median (1384 / 2306 on the 5.a play), all
  destroyed the same frame. The driver's uniform buffers are made with
  `UNIFORM` usage alone, so B4.7's `queue.writeBuffer` into them needs
  `COPY_DST` (the fake now asserts it under validation).
- **`serialize` is orientation, not a gate column.** It is
  `serialize_scene` in the recording process, cache warm after the first
  round, with the play replayed unpaced; the native harness's rows
  (`gpu_timestamps_20260926`, `serialize_ms`) are the measurement of
  Python's side and agree where they overlap (8.a ticked 37.8 here against
  the live run's prepare 25.8 + wire encode 4.5; the plan's 36.4).
- **Load.** Not sampled during the runs; other sessions' CPU work was
  present (load average 3.8–4.2 after). Still-row minima are within a few
  percent of medians; play and cold rows are single-row or spread by GC.
  A quiet-machine repeat would tighten the play medians, not move the
  still ones.
- **Frames.** The twelve evenly thinned pausepoints, the same as the
  native gate runs'; the heaviest beat of each episode is in (the thinning
  keeps the last). Plays under 15 frames are recorded whole minus their
  warmups (α 0.44–1.00 on the 9-frame plays); 8.a's 23-frame play is
  recorded at α 0.36–0.84, its middle.
- **One report.** `report.json` is EpisodeB2's complete report (every
  row of both variants, the cold rows, the streams' sizes, the scope
  strings); PriceDiscovery's rows are not archived, its summary is. The
  streams (270 MB together) live only in the scratch output. The
  `stream_scope` and `class_scope` strings in both files are the
  committed harness's wording (the cold class as the rows are), put in
  after the run; every number is as the harness wrote it.

## Files

- `README.md`: this file.
- `summary.json`: both episodes' `summary.json` under `episodes` (the
  classes per variant, the per-frame classes and cold rows, the streams'
  sizes and Node init time, the scene's measured checkpoints, the commit
  and dirty flag, machine, Python, numpy and Node versions, the variants'
  environments, the source hashes with `source_files_unchanged_during_run`,
  the scope strings), the commands, the run-times log and the machine.
- `report.json`: EpisodeB2's complete report from the harness, one row
  per message of each stream.

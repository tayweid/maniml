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
- `after_b47.json`: the "After B4.7" record. `episodes.<scene>.b47_run`:
  both episodes' `summary.json` from `browser_frames.py` on the B4.7 page
  (`--play-edges --realm main`); `same_session_replays`: the B4.6 page and
  B4.7's replayed on the same streams in both realms, five rounds each,
  reduced per class and per frame (`js_ms` and `page_ms`, each message's
  time the median of its five rounds); `streams`: the streams' hashes;
  `moves_8a`: the 8.a rows through both pages; `proof`: the trace
  comparisons, the mutants and the tests that catch each, and the pixel
  parity result.
- `pixel_parity.html`: the page that compared the two drivers' pixels on a
  real WebGPU device (its opening comment says how to serve it).

## After B4.7

B4.7 (`docs/phase_b4_plan.md`) makes the browser own the frame, still fed
full frames: `webgpu.js` keeps the last submitted frame as an ordered list
of slots, each batch resolved once (its pipelines for the sample count, its
uniform set's bind group per pipeline layout, its geometry and index
pattern, its paint or texture binding, and the border, net and program
outputs it owns), and a full frame is diffed against it (`applyFull`): a
batch equal to its slot keeps it and costs its draws, a batch that changed
takes over its slot in place (keeping outputs whose layout still fits),
resources are counted per slot and destroyed after the submit that follows
their last release, uniforms live in one buffer per override set rewritten
with `queue.writeBuffer` when the camera moves, compute stages run only
where their state moved, the encode loop sets a pipeline, bind group,
vertex or index buffer only when it changes, and a message byte-identical
to the last one submitted is a redraw of the slots with no parse. The
viewer's renderer selection (`renderer_selection.js`), which reads each
message's `renderer` before the driver sees it, recognises the same
message too, so on the page a resend is not parsed at all.

This section was rewritten after B4.7's review, which found three things
its first draft got wrong. A frame that failed after it had rewritten the
shared uniform sets for its own camera left them there, so the next frame
at the submitted camera drew and generated with the failed one's (fixed:
a failed frame now clears what every set is taken to hold, and
`failedFramesKeepTheCamera` pins it). The draft's still-frame numbers timed
the driver alone while the page parsed every header once more in the
renderer selection (now timed as `page_ms`, and the selection no longer
parses a resend). And its play numbers were class medians that hide where a
play is dearest (the 8.a and 5.a rows are now named, and a play's first
frame and its landing are classes of their own). Every number below is
from the runs described next.

### Runs

The archive's two commands with two switches added, from the same worktree
(branch `b4-tier2-browser`, commit `ab113484` = B4.6, plus the uncommitted
B4.7 working tree; `after_b47.json` `episodes.*.b47_run.source_files_sha256`
has the hashes, `webgpu.js` at `d8a9b35b…` and `renderer_selection.js` at
`2728c0c6…`, unchanged during the runs), Node v22.16.0, Apple M3,
03:02–03:06 UTC 2026-09-27, load average 3.3–4.4:

```bash
python -m benchmarks.browser_frames \
  --scene /Users/taylorjweidman/Projects/econ-0100/Blocks/B2_Supply/03_Code.py EpisodeB2 \
  --output <scratch>/B2 --samples 12 --warmups 3 --max-frames 12 --tick-updaters --play-frames \
  --play-edges --realm main
python -m benchmarks.browser_frames \
  --scene <scratch>/episodes/Blocks/B3_Equilibrium/Animate.py PriceDiscovery \
  --output <scratch>/B3 --samples 12 --warmups 3 --max-frames 12 --tick-updaters --play-frames \
  --play-edges --realm main
```

PriceDiscovery ran from a scratch copy of `Animate.py` as committed in
econ-0100 (sha256 `dfe6e831…`, the file every earlier run measured) beside
links to `Blocks/_Assets` and `Blocks/Sim`: the working tree had just moved
it into `_archive/`, where its relative imports no longer resolve.
`--play-edges` records each frame's play once more at its edges, after
every frame's rows, so every stream begins with B4.6's recording byte for
byte (sha1 of the gunzipped prefix: EpisodeB2 `41c66793…` / `c42bb696…`,
PriceDiscovery `83c81cad…` / `e978326a…`, B4.6's hashes) and 48 edge
messages follow it (378 and 364 messages in all). Beside the runs, the same
streams were replayed through the B4.6 page (the driver and the selection
as of `ab113484`, loaded by a require hook that swaps only the files the
harness reads) and through B4.7's, in both realms, five rounds interleaved,
03:14–03:15 UTC at load 3.8–4.3. Each message's time below is the median of
its five rounds; every count is the same in every round.

```bash
node benchmarks/browser_frames.cjs <stream> --realm <main|sandbox>
NODE_OPTIONS="--require source_hook.cjs" WEBGPU_SOURCE=<webgpu.js as of ab113484> \
  SELECTION_SOURCE=<renderer_selection.js as of ab113484> \
  node benchmarks/browser_frames.cjs <stream> --realm <main|sandbox>
```

### What a row times now

`js_ms` is, as before, `performance.now` around the driver's render.
`page_ms` is around the viewer's entry point, `ManimlRendererSelection.render`
over the same driver: the driver's time plus the selection's routing, a
parse of the whole header to read its `renderer` (or, since this increment,
a comparison with the message before, and no parse when they match), and a
promise hop. B4.6's archive named the selection's parse as outside its
number. After B4.7 it was most of a resend's JavaScript: the review
measured it at 0.38 / 0.94 ms on the 8.a header (Phase A / Phase B) against
the driver's 0.05 / 0.14 ms redraw. So the page's cost is the headline
here. Read the main realm for what a page pays; the sandbox columns are
kept only as continuity with B4.6's archive (next).

### The sandbox, a finding about this instrument

The fake device runs the driver in a vm context of its own
(`vm.runInNewContext`), as the command tests always have. There every read
of a global (`Number`, `Array`, `JSON`, `Math`, a typed array constructor)
is a call into the context's interceptor, a fraction of a microsecond each.
Measured on the 8.a frame's 911 Phase B batches, one comparison of every
batch against its slot costs 1.88 ms compiled inside a vm context and 0.16
ms with its one global (`Array.isArray`) looked up once; replaying the
EpisodeB2 Phase A stream in the sandbox, the per-value checks of uploaded
border curves and fills, `Number.isFinite` read per value (as the B4.6
driver's loops read it), took 73% of the whole replay's CPU profile, stream
decompression included. B4.6's cold and play milliseconds were mostly
that: the B4.6 driver's seek into a frame is 15.5 ms at the EpisodeB2
median in the sandbox and 1.9 ms in the main realm, its Phase A play 5.1
against 1.7 ms. A browser resolves globals as the main realm does.
`browser_frames.py` and `browser_frames.cjs` take `--realm main`
(`tests/webgpu_fake_device.cjs`'s `realm` option; the calls and counts are
identical, `tests/test_browser_frames.py` checks it), and the B4.7 driver
looks the builtin up once per call in its four per-value loops, which is
most of the sandbox's gain on cold rows and changes nothing a browser does.
B4.6's gates and baselines were set in the sandbox (the plan's "8.0 ms at
911", the play gates for B4.8); the main realm is where they are re-read
(Reading).

### (i) Classes

`page` and `js` p50 in ms in the main realm, B4.6 page → B4.7 page; `js,
sandbox` is B4.6's archive, the B4.6 driver replayed now and B4.7, for
continuity; `worst page row` is the class's dearest message in the main
realm and the frame it belongs to. The counts are per frame, B4.6 → B4.7,
the same in either realm. `play entry` and `landing` are one row per play
(`--play-edges`): the play's first frame, after the checkpoint before it,
and the destination after the play's last frame.

**EpisodeB2**

| class | variant | n | page, main | js, main | js, sandbox: archive / B4.6 now / B4.7 | worst page row, main | setPipeline | bindGroups | buffers + / − | uniform writes | KB up |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| pausepoint | phase_a | 120 | 0.91 → **0.04** | 0.76 → 0.02 | 1.26 / 1.23 / 0.03 | 5.79 → 0.71 (frame 0) | 166 → 138 | 1 → 0 | 0 / 0 → 0 / 0 | 0 → 0 | 0 → 0 |
| pausepoint | phase_b | 120 | 0.95 → **0.05** | 0.80 → 0.03 | 1.55 / 1.57 / 0.03 | 4.18 → 0.57 (frame 1) | 305 → 305 | 1 → 0 | 0 / 0 → 0 / 0 | 0 → 0 | 0 → 0 |
| ticked | phase_a | 24 | 1.58 → **0.09** | 1.27 → 0.05 | 2.15 / 2.10 / 0.05 | 2.46 → 0.10 (frame 11) | 314 → 271 | 1 → 0 | 0 / 0 → 0 / 0 | 0 → 0 | 0 → 0 |
| ticked | phase_b | 24 | 3.95 → **0.15** | 3.32 → 0.10 | 6.89 / 6.33 / 0.11 | 6.26 → 0.22 (frame 11) | 1217 → 1217 | 1 → 0 | 0 / 0 → 0 / 0 | 0 → 0 | 0 → 0 |
| play | phase_a | 114 | 1.96 → **1.23** | 1.70 → 0.91 | 5.61 / 5.05 / 1.44 | 11.10 → 7.22 (frame 10) | 245 → 181 | 21 → 10 | 166 / 166 → 99 / 99 | 11 → 0 | 367 → 367 |
| play | phase_b | 114 | 2.14 → **0.97** | 1.84 → 0.66 | 3.41 / 3.40 / 0.75 | 12.29 → 7.09 (frame 11) | 830 → 813 | 166 → 0 | 100 / 100 → 0 / 0 | 100 → 29 | 2 → 1 |
| cold | phase_a | 12 | 1.99 → **1.34** | 1.87 → 1.16 | 15.33 / 15.50 / 2.27 | 17.13 → 11.80 (frame 0) | 196 → 160 | 41 → 37 | 266 / 116 → 259 / 92 | 22 → 17 | 1083 → 1083 |
| cold | phase_b | 12 | 4.17 → **3.35** | 3.88 → 3.10 | 23.24 / 23.52 / 5.05 | 21.22 → 13.75 (frame 0) | 418 → 418 | 220 → 218 | 433 / 754 → 429 / 860 | 74 → 72 | 1784 → 1784 |
| play entry | phase_a | 12 | 1.48 → **1.03** | 1.30 → 0.77 | – / 4.59 / 1.16 | 7.92 → 5.22 (frame 10) | 220 → 162 | 27 → 20 | 154 / 50 → 153 / 23 | 14 → 10 | 290 → 290 |
| play entry | phase_b | 12 | 3.72 → **2.34** | 3.17 → 1.79 | – / 12.14 / 2.61 | 15.16 → 13.66 (frame 10) | 720 → 712 | 220 → 218 | 376 / 100 → 376 / 6 | 94 → 59 | 774 → 774 |
| landing | phase_a | 12 | 1.06 → **0.48** | 0.89 → 0.31 | – / 2.57 / 0.41 | 6.55 → 3.05 (frame 10) | 190 → 147 | 13 → 6 | 32 / 32 → 19 / 19 | 7 → 0 | 89 → 88 |
| landing | phase_b | 12 | 2.21 → **1.36** | 1.85 → 0.88 | – / 7.85 / 1.46 | 9.32 → 6.00 (frame 10) | 418 → 418 | 8 → 7 | 18 / 282 → 16 / 374 | 4 → 2 | 720 → 720 |

**PriceDiscovery**

| class | variant | n | page, main | js, main | js, sandbox: archive / B4.6 now / B4.7 | worst page row, main | setPipeline | bindGroups | buffers + / − | uniform writes | KB up |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| pausepoint | phase_a | 12 | 0.33 → **0.01** | 0.29 → 0.01 | 0.58 / 0.60 / 0.01 | 0.35 → 0.01 (frame 11) | 41 → 9 | 1 → 0 | 0 / 0 → 0 / 0 | 0 → 0 | 0 → 0 |
| pausepoint | phase_b | 12 | 0.37 → **0.04** | 0.32 → 0.03 | 0.71 / 0.73 / 0.02 | 0.39 → 0.04 (frame 11) | 147 → 147 | 1 → 0 | 0 / 0 → 0 / 0 | 0 → 0 | 0 → 0 |
| ticked | phase_a | 132 | 0.67 → **0.03** | 0.58 → 0.02 | 1.03 / 1.05 / 0.02 | 1.00 → 0.25 (frame 0) | 118 → 50 | 1 → 0 | 0 / 0 → 0 / 0 | 0 → 0 | 0 → 0 |
| ticked | phase_b | 132 | 1.12 → **0.04** | 0.98 → 0.03 | 1.84 / 1.87 / 0.03 | 1.92 → 0.42 (frame 0) | 366 → 307 | 1 → 0 | 0 / 0 → 0 / 0 | 0 → 0 | 0 → 0 |
| play | phase_a | 100 | 0.93 → **0.41** | 0.85 → 0.31 | 1.81 / 1.78 / 0.36 | 8.75 → 1.99 (frame 1) | 126 → 53 | 5 → 2 | 19 / 19 → 14 / 14 | 3 → 0 | 151 → 151 |
| play | phase_b | 100 | 1.76 → **0.55** | 1.51 → 0.39 | 2.81 / 2.95 / 0.44 | 2.80 → 1.32 (frame 7) | 491 → 491 | 236 → 0 | 144 / 144 → 0 / 0 | 144 → 52 | 4 → 1 |
| cold | phase_a | 12 | 1.10 → **0.76** | 1.00 → 0.65 | 4.92 / 4.82 / 1.03 | 11.63 → 7.24 (frame 0) | 126 → 54 | 30 → 14 | 75 / 55 → 58 / 37 | 22 → 14 | 815 → 814 |
| cold | phase_b | 12 | 2.56 → **1.68** | 2.32 → 1.43 | 13.97 / 14.31 / 2.49 | 15.87 → 11.14 (frame 0) | 416 → 356 | 136 → 116 | 275 / 512 → 238 / 596 | 70 → 54 | 757 → 755 |
| play entry | phase_a | 12 | 0.75 → **0.36** | 0.65 → 0.26 | – / 1.75 / 0.33 | 2.37 → 1.40 (frame 10) | 124 → 52 | 6 → 5 | 22 / 12 → 21 / 3 | 4 → 3 | 274 → 274 |
| play entry | phase_b | 12 | 2.18 → **1.59** | 1.80 → 1.26 | – / 6.80 / 1.96 | 2.90 → 2.26 (frame 1) | 514 → 480 | 344 → 342 | 564 / 160 → 560 / 10 | 156 → 152 | 267 → 266 |
| landing | phase_a | 12 | 0.64 → **0.28** | 0.55 → 0.18 | – / 1.13 / 0.19 | 1.74 → 0.89 (frame 10) | 112 → 50 | 6 → 0 | 12 / 11 → 6 / 6 | 4 → 0 | 61 → 61 |
| landing | phase_b | 12 | 1.71 → **0.88** | 1.49 → 0.80 | – / 5.26 / 1.23 | 1.94 → 1.31 (frame 6) | 366 → 306 | 24 → 17 | 59 / 446 → 44 / 557 | 14 → 11 | 227 → 226 |

### (ii) The 8.a frame: resent, differing, moved

The stream's 8.a rows are the viewer's resends (byte-identical messages).
Two rows the stream lacks were measured on the same 8.a message after
playing the stream up to it, through each page (`after_b47.json`
`moves_8a`): the message with a header key reordered, alternating two
orders, so nothing changed but no byte matches (the full diff path), and
the message with its `frame_scale` alternating between two values, every
message a camera move. p50 in ms over 180 messages (03:11–03:12 UTC, load
average 5.1–5.2); the counts are per frame.

| 8.a, EpisodeB2 | variant | page, main | js, main | page, sandbox | buffers / bind groups / uniform writes | border dispatches |
|---|---|---:|---:|---:|---:|---:|
| resent, identical bytes | phase_a | 2.04 → **0.09** | 1.64 → 0.05 | 2.74 → 0.10 | 0 / 1 / 0 → 0 / 0 / 0 | 0 → 0 |
| resent, identical bytes | phase_b | 5.98 → **0.24** | 4.95 → 0.13 | 10.38 → 0.24 | 0 / 1 / 0 → 0 / 0 / 0 | 0 → 0 |
| still, bytes differing | phase_a | 2.02 → **0.85** | 1.67 → 0.50 | 2.66 → 0.82 | 0 / 1 / 0 → 0 / 0 / 0 | 0 → 0 |
| still, bytes differing | phase_b | 5.85 → **2.12** | 4.94 → 1.24 | 10.35 → 2.04 | 0 / 1 / 0 → 0 / 0 / 0 | 0 → 0 |
| camera move | phase_a | 2.00 → **0.85** | 1.66 → 0.50 | 2.75 → 0.84 | 46 / 46 / 46 → 0 / 0 / 2 | 42 → 42 |
| camera move | phase_b | 6.66 → **2.15** | 5.78 → 1.28 | 11.68 → 2.18 | 461 / 461 / 461 → 0 / 0 / 2 | 456 → 456 |

At 8.a the header is 179 / 434 KB. A resend costs the page the selection's
comparison (0.04 / 0.11 ms) and the driver's comparison and redraw (0.05 /
0.13); nothing is made or written. A message that differs is parsed twice,
by the selection (0.35 / 0.88 ms, the page column less the js column) and
by the driver (0.37 / 0.92 ms of its 0.50 / 1.24), and matched against the
slots (the rest, 0.13 / 0.32). A camera move adds two uniform writes (the
one uniform set at 8.a, its render and generation values) and the same
border dispatches as before, without a buffer, bind group or parameter
upload per dispatch; Phase B's 456 patch runs each re-evaluate their strips
at the new scale.

### (iii) Per frame

**EpisodeB2** (page and js p50 in ms, main realm, B4.6 → B4.7; buffers + bind groups made per frame, B4.7)

| frame | beat | class | phase_a page | phase_a js | phase_b page | phase_b js | made, phase_a | made, phase_b |
|---|---|---|---:|---:|---:|---:|---:|---:|
| 0 | 0.a | pausepoint | 2.39 → 0.23 | 2.00 → 0.18 | 3.76 → 0.21 | 3.25 → 0.16 | 0 + 0 | 0 + 0 |
| 0 | 0.a | play | 7.53 → 1.88 | 7.08 → 1.37 | 4.26 → 1.46 | 3.74 → 0.94 | 99 + 33 | 0 + 0 |
| 0 | 0.a | cold | 17.13 → 11.80 | 16.67 → 11.33 | 21.22 → 13.75 | 20.57 → 13.10 | 705 + 32 | 1274 + 641 |
| 0 | 0.a | play entry | 3.13 → 1.61 | 2.68 → 1.17 | 3.95 → 2.37 | 3.35 → 1.67 | 165 + 66 | 396 + 231 |
| 0 | 0.a | landing | 1.91 → 0.89 | 1.53 → 0.52 | 3.64 → 1.67 | 3.18 → 1.21 | 0 + 0 | 6 + 3 |
| 1 | 2.h | pausepoint | 0.80 → 0.07 | 0.67 → 0.06 | 0.93 → 0.08 | 0.80 → 0.06 | 0 + 0 | 0 + 0 |
| 1 | 2.h | play | 1.69 → 0.93 | 1.52 → 0.77 | 1.70 → 0.72 | 1.49 → 0.52 | 210 + 10 | 0 + 0 |
| 1 | 2.h | cold | 2.35 → 2.13 | 2.19 → 1.96 | 3.60 → 3.47 | 3.36 → 3.22 | 302 + 48 | 257 + 127 |
| 1 | 2.h | play entry | 1.04 → 0.91 | 0.89 → 0.73 | 4.30 → 2.30 | 3.98 → 2.00 | 230 + 20 | 846 + 493 |
| 1 | 2.h | landing | 0.74 → 0.33 | 0.57 → 0.19 | 1.77 → 5.02 | 1.55 → 1.08 | 0 + 0 | 361 + 180 |
| 2 | 3.i | ticked | 1.10 → 0.06 | 0.92 → 0.04 | 1.92 → 0.10 | 1.61 → 0.07 | 0 + 0 | 0 + 0 |
| 2 | 3.i | play | 1.15 → 0.58 | 0.97 → 0.38 | 1.89 → 0.79 | 1.58 → 0.47 | 12 + 4 | 0 + 0 |
| 2 | 3.i | cold | 6.49 → 2.30 | 6.25 → 2.08 | 5.41 → 5.15 | 4.98 → 4.63 | 285 + 112 | 817 + 408 |
| 2 | 3.i | play entry | 1.05 → 0.48 | 0.88 → 0.31 | 2.02 → 0.90 | 1.68 → 0.58 | 20 + 8 | 48 + 28 |
| 2 | 3.i | landing | 1.03 → 0.47 | 0.87 → 0.30 | 2.00 → 0.86 | 1.68 → 0.56 | 20 + 8 | 6 + 3 |
| 3 | 4.c.1 | pausepoint | 0.32 → 0.01 | 0.27 → 0.01 | 0.10 → 0.01 | 0.09 → 0.01 | 0 + 0 | 0 + 0 |
| 3 | 4.c.1 | play | 0.54 → 0.30 | 0.48 → 0.23 | 0.27 → 0.10 | 0.24 → 0.07 | 30 + 9 | 0 + 0 |
| 3 | 4.c.1 | cold | 1.63 → 1.20 | 1.55 → 1.11 | 1.23 → 1.00 | 1.19 → 0.97 | 194 + 74 | 34 + 15 |
| 3 | 4.c.1 | play entry | 0.55 → 0.27 | 0.48 → 0.21 | 0.42 → 0.32 | 0.38 → 0.27 | 48 + 18 | 120 + 70 |
| 3 | 4.c.1 | landing | 0.53 → 0.26 | 0.47 → 0.20 | 0.40 → 0.20 | 0.38 → 0.18 | 45 + 18 | 13 + 6 |
| 4 | 4.b.2 | pausepoint | 0.36 → 0.01 | 0.30 → 0.01 | 0.09 → 0.01 | 0.08 → 0.00 | 0 + 0 | 0 + 0 |
| 4 | 4.b.2 | play | 0.57 → 0.29 | 0.50 → 0.22 | 0.21 → 0.08 | 0.18 → 0.05 | 22 + 7 | 0 + 0 |
| 4 | 4.b.2 | cold | 1.56 → 1.03 | 1.48 → 0.94 | 1.70 → 1.02 | 1.67 → 0.99 | 113 + 42 | 21 + 9 |
| 4 | 4.b.2 | play entry | 0.68 → 0.34 | 0.60 → 0.26 | 0.87 → 0.58 | 0.82 → 0.53 | 55 + 20 | 97 + 55 |
| 4 | 4.b.2 | landing | 0.48 → 0.22 | 0.42 → 0.16 | 0.74 → 0.39 | 0.73 → 0.37 | 19 + 6 | 12 + 5 |
| 5 | 4.b.4 | pausepoint | 0.37 → 0.01 | 0.32 → 0.01 | 0.09 → 0.01 | 0.08 → 0.00 | 0 + 0 | 0 + 0 |
| 5 | 4.b.4 | play | 0.56 → 0.28 | 0.49 → 0.21 | 0.21 → 0.08 | 0.18 → 0.06 | 22 + 7 | 0 + 0 |
| 5 | 4.b.4 | cold | 0.69 → 0.36 | 0.63 → 0.29 | 1.67 → 0.98 | 1.64 → 0.96 | 29 + 8 | 21 + 9 |
| 5 | 4.b.4 | play entry | 0.67 → 0.33 | 0.59 → 0.26 | 0.86 → 0.53 | 0.82 → 0.49 | 55 + 20 | 97 + 55 |
| 5 | 4.b.4 | landing | 0.47 → 0.22 | 0.42 → 0.16 | 1.03 → 0.40 | 1.01 → 0.38 | 19 + 6 | 12 + 5 |
| 6 | 4.return.5 | pausepoint | 0.95 → 0.04 | 0.79 → 0.02 | 0.95 → 0.05 | 0.80 → 0.03 | 0 + 0 | 0 + 0 |
| 6 | 4.return.5 | play | 1.96 → 1.24 | 1.71 → 1.00 | 2.13 → 0.92 | 1.84 → 0.64 | 300 + 30 | 0 + 0 |
| 6 | 4.return.5 | cold | 1.62 → 0.96 | 1.43 → 0.78 | 3.65 → 3.22 | 3.40 → 2.98 | 233 + 8 | 418 + 211 |
| 6 | 4.return.5 | play entry | 2.06 → 1.15 | 1.83 → 0.93 | 4.38 → 3.84 | 3.92 → 3.31 | 378 + 66 | 1326 + 765 |
| 6 | 4.return.5 | landing | 1.10 → 0.48 | 0.93 → 0.31 | 3.41 → 2.31 | 3.15 → 2.05 | 19 + 6 | 420 + 212 |
| 7 | 4.return.7 | pausepoint | 0.99 → 0.04 | 0.81 → 0.03 | 1.01 → 0.04 | 0.85 → 0.03 | 0 + 0 | 0 + 0 |
| 7 | 4.return.7 | play | 1.92 → 1.29 | 1.69 → 1.03 | 2.14 → 0.98 | 1.83 → 0.67 | 312 + 30 | 0 + 0 |
| 7 | 4.return.7 | cold | 1.15 → 0.59 | 0.96 → 0.40 | 4.69 → 2.92 | 4.37 → 2.62 | 35 + 6 | 440 + 224 |
| 7 | 4.return.7 | play entry | 1.92 → 1.18 | 1.70 → 0.96 | 4.82 → 3.46 | 4.35 → 2.88 | 390 + 66 | 1388 + 801 |
| 7 | 4.return.7 | landing | 1.09 → 0.49 | 0.92 → 0.32 | 6.75 → 2.10 | 6.47 → 1.84 | 19 + 6 | 440 + 224 |
| 8 | 4.d.9 | pausepoint | 0.44 → 0.02 | 0.37 → 0.01 | 0.12 → 0.01 | 0.11 → 0.01 | 0 + 0 | 0 + 0 |
| 8 | 4.d.9 | play | 0.49 → 0.22 | 0.42 → 0.15 | 0.16 → 0.07 | 0.14 → 0.04 | 9 + 2 | 0 + 0 |
| 8 | 4.d.9 | cold | 0.96 → 0.59 | 0.88 → 0.51 | 1.99 → 1.20 | 1.95 → 1.16 | 79 + 26 | 39 + 17 |
| 8 | 4.d.9 | play entry | 0.61 → 0.28 | 0.54 → 0.21 | 0.79 → 0.39 | 0.75 → 0.36 | 32 + 10 | 41 + 23 |
| 8 | 4.d.9 | landing | 0.62 → 0.27 | 0.54 → 0.20 | 0.84 → 0.40 | 0.80 → 0.38 | 29 + 10 | 18 + 8 |
| 9 | 4.h | pausepoint | 1.52 → 0.06 | 1.27 → 0.04 | 2.32 → 0.10 | 1.92 → 0.06 | 0 + 0 | 0 + 0 |
| 9 | 4.h | play | 2.31 → 1.24 | 1.98 → 0.90 | 2.85 → 1.19 | 2.42 → 0.71 | 85 + 28 | 0 + 0 |
| 9 | 4.h | cold | 3.17 → 1.49 | 2.89 → 1.21 | 5.45 → 4.42 | 4.91 → 3.87 | 417 + 20 | 1039 + 546 |
| 9 | 4.h | play entry | 2.24 → 1.14 | 1.91 → 0.81 | 3.49 → 2.41 | 2.98 → 1.91 | 141 + 56 | 355 + 206 |
| 9 | 4.h | landing | 1.74 → 0.61 | 1.49 → 0.35 | 2.42 → 1.05 | 2.02 → 0.67 | 0 + 0 | 1 + 0 |
| 10 | 5.a | pausepoint | 2.75 → 0.11 | 2.27 → 0.07 | 2.99 → 0.13 | 2.49 → 0.09 | 0 + 0 | 0 + 0 |
| 10 | 5.a | play | 9.24 → 5.52 | 8.15 → 4.77 | 9.05 → 3.25 | 7.95 → 2.15 | 1148 + 229 | 0 + 0 |
| 10 | 5.a | cold | 8.19 → 5.76 | 7.58 → 5.17 | 7.55 → 6.01 | 6.89 → 5.27 | 1396 + 374 | 822 + 586 |
| 10 | 5.a | play entry | 7.92 → 5.22 | 7.27 → 4.56 | 15.16 → 13.66 | 13.56 → 12.15 | 1606 + 458 | 5497 + 3227 |
| 10 | 5.a | landing | 6.55 → 3.05 | 6.02 → 2.52 | 9.32 → 6.00 | 8.63 → 5.30 | 398 + 55 | 1336 + 696 |
| 11 | 8.a | ticked | 2.04 → 0.09 | 1.63 → 0.05 | 5.83 → 0.21 | 4.84 → 0.13 | 0 + 0 | 0 + 0 |
| 11 | 8.a | play | 2.50 → 1.48 | 2.07 → 1.06 | 9.70 → 6.10 | 8.21 → 4.85 | 330 + 9 | 1402 + 701 |
| 11 | 8.a | cold | 4.70 → 2.77 | 3.29 → 2.31 | 11.87 → 9.82 | 10.49 → 8.54 | 813 + 84 | 2737 + 1368 |
| 11 | 8.a | play entry | 2.50 → 1.49 | 2.08 → 1.07 | 9.85 → 7.77 | 8.43 → 5.46 | 347 + 9 | 1392 + 696 |
| 11 | 8.a | landing | 2.20 → 1.28 | 1.79 → 0.79 | 8.23 → 5.07 | 6.98 → 3.90 | 21 + 6 | 503 + 252 |

**PriceDiscovery** (page and js p50 in ms, main realm, B4.6 → B4.7; buffers + bind groups made per frame, B4.7)

| frame | beat | class | phase_a page | phase_a js | phase_b page | phase_b js | made, phase_a | made, phase_b |
|---|---|---|---:|---:|---:|---:|---:|---:|
| 0 | 0.a | ticked | 0.59 → 0.07 | 0.51 → 0.06 | 1.09 → 0.07 | 0.95 → 0.06 | 0 + 0 | 0 + 0 |
| 0 | 0.a | play | 0.93 → 0.40 | 0.85 → 0.31 | 1.02 → 0.39 | 0.89 → 0.27 | 6 + 2 | 0 + 0 |
| 0 | 0.a | cold | 11.57 → 7.24 | 11.44 → 7.11 | 15.87 → 11.14 | 15.69 → 10.95 | 224 + 77 | 445 + 196 |
| 0 | 0.a | play entry | 0.53 → 0.24 | 0.46 → 0.17 | 0.89 → 0.42 | 0.77 → 0.30 | 10 + 4 | 24 + 14 |
| 0 | 0.a | landing | 0.46 → 0.19 | 0.39 → 0.12 | 0.88 → 0.36 | 0.76 → 0.24 | 0 + 0 | 6 + 3 |
| 1 | 1.b | ticked | 0.54 → 0.02 | 0.48 → 0.01 | 0.35 → 0.02 | 0.32 → 0.01 | 0 + 0 | 0 + 0 |
| 1 | 1.b | play | 4.56 → 1.54 | 4.37 → 1.35 | 2.06 → 0.53 | 1.92 → 0.39 | 196 + 65 | 0 + 0 |
| 1 | 1.b | cold | 11.63 → 3.06 | 11.53 → 2.96 | 10.02 → 3.57 | 9.95 → 3.51 | 104 + 38 | 93 + 45 |
| 1 | 1.b | play entry | 2.28 → 1.31 | 2.11 → 1.13 | 2.60 → 2.26 | 2.37 → 2.01 | 326 + 130 | 794 + 462 |
| 1 | 1.b | landing | 0.45 → 0.16 | 0.39 → 0.10 | 1.43 → 0.83 | 1.39 → 0.79 | 0 + 0 | 7 + 3 |
| 2 | 2.b.i | ticked | 0.65 → 0.02 | 0.58 → 0.01 | 0.61 → 0.03 | 0.53 → 0.02 | 0 + 0 | 0 + 0 |
| 2 | 2.b.i | play | 1.50 → 0.67 | 1.38 → 0.56 | 1.13 → 0.34 | 1.02 → 0.23 | 68 + 22 | 0 + 0 |
| 2 | 2.b.i | cold | 9.04 → 1.71 | 8.90 → 1.61 | 9.92 → 1.89 | 9.77 → 1.76 | 116 + 41 | 210 + 102 |
| 2 | 2.b.i | play entry | 1.26 → 0.67 | 1.14 → 0.55 | 1.37 → 1.02 | 1.23 → 0.85 | 112 + 44 | 280 + 162 |
| 2 | 2.b.i | landing | 0.59 → 0.23 | 0.52 → 0.16 | 1.00 → 0.50 | 0.92 → 0.42 | 6 + 0 | 20 + 9 |
| 3 | 3.a.1 | ticked | 0.55 → 0.04 | 0.47 → 0.03 | 1.43 → 0.05 | 1.25 → 0.04 | 0 + 0 | 0 + 0 |
| 3 | 3.a.1 | play | 0.64 → 0.30 | 0.55 → 0.21 | 1.90 → 0.75 | 1.66 → 0.51 | 12 + 2 | 0 + 0 |
| 3 | 3.a.1 | cold | 1.25 → 0.92 | 1.15 → 0.83 | 7.14 → 3.08 | 6.86 → 2.79 | 111 + 26 | 583 + 266 |
| 3 | 3.a.1 | play entry | 0.61 → 0.31 | 0.52 → 0.22 | 2.22 → 1.54 | 1.79 → 1.23 | 17 + 6 | 547 + 336 |
| 3 | 3.a.1 | landing | 0.53 → 0.23 | 0.45 → 0.15 | 1.67 → 1.04 | 1.45 → 0.81 | 5 + 0 | 190 + 95 |
| 4 | 3.a.3 | ticked | 0.64 → 0.04 | 0.56 → 0.03 | 1.45 → 0.04 | 1.25 → 0.03 | 0 + 0 | 0 + 0 |
| 4 | 3.a.3 | play | 0.67 → 0.31 | 0.58 → 0.22 | 2.17 → 0.82 | 1.90 → 0.55 | 14 + 2 | 0 + 0 |
| 4 | 3.a.3 | cold | 0.83 → 0.56 | 0.74 → 0.46 | 5.54 → 2.09 | 5.28 → 1.83 | 51 + 11 | 267 + 136 |
| 4 | 3.a.3 | play entry | 0.66 → 0.31 | 0.57 → 0.22 | 2.14 → 1.66 | 1.82 → 1.35 | 18 + 5 | 572 + 347 |
| 4 | 3.a.3 | landing | 0.60 → 0.26 | 0.52 → 0.18 | 1.76 → 1.12 | 1.52 → 0.88 | 6 + 0 | 210 + 103 |
| 5 | 3.a.5 | ticked | 0.68 → 0.03 | 0.58 → 0.02 | 1.41 → 0.05 | 1.20 → 0.03 | 0 + 0 | 0 + 0 |
| 5 | 3.a.5 | play | 0.77 → 0.35 | 0.67 → 0.25 | 1.83 → 0.75 | 1.58 → 0.49 | 14 + 2 | 0 + 0 |
| 5 | 3.a.5 | cold | 0.95 → 0.55 | 0.84 → 0.44 | 2.34 → 1.77 | 2.05 → 1.50 | 61 + 15 | 278 + 142 |
| 5 | 3.a.5 | play entry | 0.75 → 0.36 | 0.65 → 0.26 | 2.25 → 1.64 | 1.90 → 1.30 | 18 + 5 | 578 + 349 |
| 5 | 3.a.5 | landing | 0.68 → 0.29 | 0.59 → 0.19 | 1.88 → 1.15 | 1.61 → 0.90 | 6 + 0 | 215 + 105 |
| 6 | 3.a.8 | ticked | 0.67 → 0.03 | 0.57 → 0.02 | 1.32 → 0.05 | 1.13 → 0.03 | 0 + 0 | 0 + 0 |
| 6 | 3.a.8 | play | 0.75 → 0.34 | 0.65 → 0.23 | 1.78 → 0.77 | 1.53 → 0.50 | 14 + 2 | 0 + 0 |
| 6 | 3.a.8 | cold | 0.93 → 0.60 | 0.82 → 0.48 | 2.13 → 1.59 | 1.85 → 1.30 | 55 + 14 | 268 + 130 |
| 6 | 3.a.8 | play entry | 0.76 → 0.36 | 0.66 → 0.26 | 2.28 → 1.74 | 1.95 → 1.39 | 24 + 5 | 599 + 356 |
| 6 | 3.a.8 | landing | 0.72 → 0.31 | 0.62 → 0.21 | 1.87 → 1.31 | 1.63 → 1.05 | 12 + 0 | 237 + 112 |
| 7 | 3.a.10 | ticked | 0.66 → 0.03 | 0.57 → 0.02 | 0.95 → 0.03 | 0.81 → 0.02 | 0 + 0 | 0 + 0 |
| 7 | 3.a.10 | play | 0.69 → 0.28 | 0.59 → 0.18 | 1.20 → 0.47 | 1.03 → 0.30 | 6 + 0 | 0 + 0 |
| 7 | 3.a.10 | cold | 0.76 → 0.38 | 0.66 → 0.28 | 1.42 → 0.94 | 1.25 → 0.76 | 29 + 3 | 95 + 41 |
| 7 | 3.a.10 | play entry | 0.73 → 0.32 | 0.63 → 0.23 | 1.48 → 0.98 | 1.25 → 0.75 | 15 + 1 | 262 + 139 |
| 7 | 3.a.10 | landing | 0.71 → 0.31 | 0.61 → 0.21 | 1.24 → 0.64 | 1.09 → 0.48 | 11 + 0 | 67 + 25 |
| 8 | 3.a.12 | ticked | 0.71 → 0.03 | 0.61 → 0.02 | 1.39 → 0.05 | 1.19 → 0.03 | 0 + 0 | 0 + 0 |
| 8 | 3.a.12 | play | 0.79 → 0.34 | 0.69 → 0.24 | 1.77 → 0.74 | 1.52 → 0.48 | 14 + 2 | 0 + 0 |
| 8 | 3.a.12 | cold | 0.92 → 0.53 | 0.81 → 0.42 | 2.09 → 1.56 | 1.82 → 1.27 | 51 + 11 | 272 + 130 |
| 8 | 3.a.12 | play entry | 0.86 → 0.42 | 0.74 → 0.31 | 2.29 → 1.77 | 1.95 → 1.43 | 28 + 5 | 617 + 362 |
| 8 | 3.a.12 | landing | 0.81 → 0.38 | 0.71 → 0.27 | 1.94 → 1.26 | 1.69 → 0.99 | 18 + 0 | 255 + 118 |
| 9 | 3.b.1 | ticked | 0.72 → 0.03 | 0.62 → 0.02 | 0.98 → 0.03 | 0.83 → 0.02 | 0 + 0 | 0 + 0 |
| 9 | 3.b.1 | play | 0.74 → 0.28 | 0.63 → 0.18 | 1.19 → 0.48 | 1.02 → 0.31 | 6 + 0 | 0 + 0 |
| 9 | 3.b.1 | cold | 0.83 → 0.39 | 0.72 → 0.28 | 1.49 → 0.98 | 1.32 → 0.82 | 29 + 2 | 113 + 47 |
| 9 | 3.b.1 | play entry | 0.75 → 0.33 | 0.65 → 0.22 | 1.42 → 0.81 | 1.21 → 0.60 | 7 + 1 | 216 + 123 |
| 9 | 3.b.1 | landing | 0.77 → 0.29 | 0.66 → 0.18 | 1.13 → 0.51 | 0.99 → 0.36 | 1 + 0 | 21 + 9 |
| 10 | 3.b | ticked | 0.96 → 0.03 | 0.83 → 0.02 | 0.97 → 0.04 | 0.83 → 0.02 | 0 + 0 | 0 + 0 |
| 10 | 3.b | play | 2.55 → 1.33 | 2.33 → 1.12 | 1.96 → 0.68 | 1.72 → 0.44 | 165 + 55 | 0 + 0 |
| 10 | 3.b | cold | 2.35 → 1.32 | 2.19 → 1.17 | 2.79 → 1.48 | 2.58 → 1.31 | 140 + 44 | 142 + 54 |
| 10 | 3.b | play entry | 2.37 → 1.40 | 2.18 → 1.17 | 2.90 → 1.91 | 2.56 → 1.57 | 275 + 110 | 660 + 385 |
| 10 | 3.b | landing | 1.74 → 0.89 | 1.61 → 0.74 | 1.87 → 0.86 | 1.71 → 0.71 | 65 + 26 | 6 + 3 |
| 11 | 5.a | pausepoint | 0.33 → 0.01 | 0.29 → 0.01 | 0.37 → 0.04 | 0.32 → 0.03 | 0 + 0 | 0 + 0 |
| 11 | 5.a | play | 1.63 → 0.93 | 1.50 → 0.80 | 1.20 → 0.39 | 1.08 → 0.27 | 129 + 43 | 0 + 0 |
| 11 | 5.a | cold | 8.44 → 1.02 | 8.38 → 0.97 | 2.01 → 1.44 | 1.95 → 1.36 | 8 + 2 | 13 + 6 |
| 11 | 5.a | play entry | 1.54 → 0.97 | 1.41 → 0.82 | 1.77 → 1.31 | 1.56 → 1.10 | 215 + 86 | 516 + 301 |
| 11 | 5.a | landing | 0.32 → 0.13 | 0.27 → 0.08 | 1.76 → 0.90 | 1.69 → 0.84 | 0 + 0 | 6 + 3 |

### (iv) What the GPU is asked

What B4.7 must not change is what the GPU is asked to do, and the review
found that nothing committed showed it: `tests/test_wgpu_port.py` draws with
the Python winding reference and never runs `webgpu.js`,
`tests/player_commands.cjs` stubs the driver, and the draft's trace
comparison lived in scratch. Now committed:

- `tests/webgpu_trace.cjs` traces a submission by content rather than
  identity: every draw (its pipeline's descriptor, the content of each bound
  group, vertex and index buffer, its stencil reference and arguments) and
  every compute dispatch (its kernel and what it reads), each compute write
  simulated as a token of the dispatch's inputs, so a draw that reads a
  stale, borrowed or destroyed output differs. A generation kernel's inputs
  are the uniform fields it reads, taken from its WGSL and checked against
  it at load (border_compute.wgsl reads the camera position only for a
  stroke that is not flat), so a camera move that changes only what a
  kernel does not read leaves its output equal.
- `retainedFramesDrawWhatFreshDriversDraw`: fifteen full frames that resend
  a message byte for byte, replace a bordered mover's geometry in place,
  move the camera's scale and position, change a net's density and
  programs' scalars (differing, coinciding, parting), insert a batch and the
  same geometry under other overrides, fail after rewriting the uniform
  sets and return to the submitted camera, change the sample count and
  remove batches. Every frame's render passes trace as a fresh driver's do
  given the same frame whole, and the failed frame fails alike.
- `streamDrawsWhatFreshDriversDraw` (run by `test_browser_frames` on its
  episode fixture, both variants): every message of a recorded stream,
  played in order, traces as the same frame rebuilt whole by the recording
  indexer does on a fresh driver.
- `failedFramesKeepTheCamera` (the review's three rollback sequences) and
  `generationFollowsItsInputs` (a camera-position move re-evaluates a border
  whose stroke is not flat and no other; a density change re-evaluates the
  net with the new density, the same density nothing). Both pass on the B4.6
  driver, which packed uniforms per frame; the first fails on the draft,
  the second on the review's M4 and M5 mutants.

Mutants of the final driver, each caught by at least one committed test
(`after_b47.json` `proof.mutants`): the rollback left out; the net density
(the review's M4) or the camera position (M5) out of a state key; the frame
scale out of the border state; one uniform set for every batch; an output's
fill identity not checked; no fill copy; a program group that ignores the
scalars; a redraw on equal length rather than equal bytes; a border
binding not remade for a new source; retained program slots not evaluated.
A fresh driver shares the draft's code, so a defect it has cold (no fill
copy, the scalars ignored) is the other cases' to catch, and they do.

The side-by-side comparison of the B4.6 and B4.7 drivers on the scratch
tracer was re-run on the final driver: every existing case of
`tests/generated_webgpu_commands.cjs` (through
`test_generated_webgpu_commands`, the Python encoder's patch, net and
program frames among them, and `test_export`'s recording replay) traces
identically, one fill copy fewer in `borderComputeFailures` (a slot taken
over in place already held the same geometry's fill); the four B4.7 cases
that fail on the B4.6 driver do so by design
(`slotsReuseAcrossFullFrames`, `outputsSurviveInsertion`,
`programOutputsSurviveCoincidence` and, from the coinciding frame on,
`retainedFramesDrawWhatFreshDriversDraw`). The four streams with their
edges, 1484 messages, trace identically frame by frame: 503,298 draws and
80,015 dispatches, zero cache misses, nothing live after teardown. The
calls over the whole streams, B4.6 → B4.7:

| stream | frames | draws | compute dispatches | buffer copies | set pipeline | set bind group | set vertex buffer | set index buffer | bind groups created | buffers created | uniform buffers created | uniform writes | write buffer | bytes uploaded |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| EpisodeB2 phase_a | 378 | 87693 → 87693 | 6939 → 6939 | 6939 → 6939 | 94632 → 74707 | 101571 → 81646 | 87315 → 87315 | 54729 → 54729 | 14259 → 8093 | 61229 → 49707 | 7145 → 1282 | 7145 → 1282 | 0 → 0 | 132.4 → 132.2 MB |
| EpisodeB2 phase_b | 378 | 249817 → 249817 | 49770 → 49770 | 0 → 0 | 299587 → 299077 | 408538 → 296629 | 56165 → 56165 | 7535 → 7535 | 98886 → 32227 | 109423 → 60567 | 49983 → 7586 | 49983 → 19634 | 0 → 12048 | 94.4 → 93.6 MB |
| PriceDiscovery phase_a | 364 | 39220 → 39220 | 3221 → 3221 | 3117 → 3117 | 42441 → 17560 | 45662 → 31535 | 38856 → 35181 | 24619 → 20944 | 6911 → 3728 | 17256 → 11708 | 3615 → 608 | 3615 → 721 | 0 → 113 | 78.9 → 78.7 MB |
| PriceDiscovery phase_b | 364 | 126568 → 126568 | 20085 → 20085 | 0 → 0 | 146653 → 129927 | 193168 → 129798 | 35827 → 35827 | 22587 → 22587 | 37152 → 9572 | 34333 → 16871 | 20826 → 3749 | 20826 → 9978 | 0 → 6229 | 33.5 → 33.1 MB |

On a real device the streams without edges were rendered through both
drivers side by side in Chromium 152 (Dawn on Metal, the M3), each frame's
canvas read back and compared (`pixel_parity.html`): all 1292 frames
identical byte for byte, every one non-blank, no validation error on either
device; a mutant that drops the border runs' fill copies differs on every
frame of the PriceDiscovery Phase A stream. That ran on the draft, before
the review's fixes. The fixes change nothing a frame that does not fail
submits, and the final driver traces those streams identically to B4.6's,
so the result stands; it was not re-run.

### Reading

**At rest the page does almost nothing.** Every pausepoint and ticked row
is a resend, and a resend costs the page 0.04 / 0.05 ms at the EpisodeB2
pausepoint median and 0.09 / 0.15 ms ticked (B4.6's page: 0.91 / 0.95 and
1.58 / 3.95), 0.09 / 0.24 ms at 8.a (2.04 / 5.98), and nothing is made. The
driver's redraw alone was B4.7's first number (0.07 / 0.15 ms at 8.a, in
the sandbox); without the selection's comparison the page would still have
paid the header parse on every resend. B4.8 removes the resend itself (an
empty delta is not sent).

**A message that differs pays its parse twice.** 0.85 / 2.12 ms at 8.a
(2.02 / 5.85 before), a camera move 0.85 / 2.15 ms (2.00 / 6.66) with no
buffer or bind group made (46 / 461 of each before). The selection's parse
is 0.35 / 0.88 of it. Handing it to the driver would remove one of the two;
that is left to B4.8, whose delta headers change what is parsed at all.

**Plays: medians, and the rows the medians hide.** The page's play median
is 1.23 / 0.97 ms on EpisodeB2 (1.96 / 2.14) and 0.41 / 0.55 on
PriceDiscovery (0.93 / 1.76). Phase B plays make nothing per frame where
the movers are programs, which is every Phase B play row but 8.a's: none of
its 375 movers is a program, so about 700 of its 895 batches (351 patch and
350 stroke runs on the first measured frame) arrive uncached every frame and
the frame makes 1402 buffers and 701 bind groups (2104 and 1052 before),
6.10 ms on the page (9.70). Phase A's plays upload
their movers' re-tessellated fills, 99 buffers per frame at the median (166
before) and 1148 on the 5.a play, 5.52 ms (9.24). Neither is the driver's
to remove: a non-program mover costs what its upload costs until rows travel
instead (B5.1), and Phase A's movers until tier 1 and B4.8 send less.

**A play's edges are its dearest frames.** The first frame of the 5.a play
on Phase B costs the page 13.66 ms (15.16), making 5497 buffers and 3227
bind groups: the slots of its 692 batches, their program outputs and
bindings, resolved once for the frames that follow at 3.25 ms. Its landing
costs 6.00 ms (9.32). At the class median the entry is 1.03 / 2.34 ms on
EpisodeB2 and the landing 0.48 / 1.36 (1.48 / 3.72 and 1.06 / 2.21 before).
The play class samples a play's middle, so these are classes of their own
now.

**What that means for B4.8's play gates.** "Play ≤ 2 ms JS (Phase A) / ≤ 4
ms (Phase B)" was set on B4.6's sandbox medians (5.6 / 3.4 ms). Read as
the page's cost in the main realm, B4.6's page already met it at the class
median (1.96 / 2.14 ms), so as class medians the gates do not tell the
drivers apart. Read as a bound on every play frame, B4.7 misses it on the
5.a Phase A play (5.52 ms) and the 8.a Phase B play (6.10), and on play
entries up to 13.66 ms, all of them frames whose uploads or first
resolution are the cost. B4.8 re-derives its gates in the main realm on
`page_ms`, and says whether they bound the class median or every play
frame, entry and landing included; B4.7 sets none.

**Seeks.** The cold class is 1.34 / 3.35 ms on the page at the EpisodeB2
median (1.99 / 4.17) and 0.76 / 1.68 on PriceDiscovery (1.10 / 2.56). With
each message the median of five rounds, no row of any class is slower on
B4.7's page than on B4.6's but one: the EpisodeB2 2.h landing on Phase B,
1.77 → 5.02 ms on the page while its driver time fell (1.55 → 1.08), where a
garbage collection lands in three of the five rounds (1.1–1.2 ms in the
other two). The draft's "5 of 48 cold rows 6–16% slower" were single
samples. The wire still carries every uncached byte (1.1 / 1.8 MB), which is
B4.8's.

**Pipelines and bindings.** On Phase A a pipeline is set once per run of
draws that share it (setPipeline 166 → 138 at the pausepoint median, 94,632
→ 74,707 over EpisodeB2's stream); on Phase B almost every call already
switches (a patch group alternates five pipelines), so its count hardly
moves. Bind group calls fall by 20–33% over the streams, vertex and index
buffer calls by 9–15% on PriceDiscovery's Phase A. A patch run's pipeline
changes are the draw count's cost that B5.2 or render bundles (B4.9) would
address; at 1841 draws they are now 0.13 ms of a resend's JavaScript.

### Scope and caveats (B4.7)

- **Not Dawn, not the GPU.** As for B4.6: the counts are what Dawn would be
  handed; the pixel check shows the GPU draws the same frames, not what it
  costs. The main realm is Node's V8 without Chrome's heap or render-thread
  contention, the closest this instrument gets to a page.
- **The resend paths keep the caller's buffer.** The driver keeps the last
  message it drew (while it is at most 1 MiB and every batch drew) and the
  selection the last one it routed, and compares the next message with it
  word by word; both keep a reference, not a copy, so a caller hands a
  buffer over and does not write into it afterwards (the viewer and the
  player hand over a fresh one per message). The driver returns its
  previous parse as the header.
- **Single rows.** A cold, entry or landing row is one message, here the
  median of five rounds. The rounds of one row varied by up to a factor of
  four where a garbage collection lands (the 2.h landing above), and
  typically by under 10%.
- **The play edges' base.** A play's entry follows its source checkpoint
  restored and serialized once (`play_source`), and its landing the play's
  last frame (`play_last`), each after the frame before it in the stream,
  as a viewer meets them after a seek to the source. Those two rows are in
  no class.
- **What the review verified** (on the draft, the same streams; these are
  the review's notes, not re-run): per frame, draws, dispatches, copies,
  setStencilReference calls, render and compute passes, pipeline switches,
  submits and texture uploads are identical between the drivers, and only
  the kinds the commit names change (setPipeline, setBindGroup, vertex and
  index buffer calls, buffers and bind groups made, uniform buffers and
  writes, writeBuffer); validation-on replays of the four streams and of an
  8.a pan and zoom recorded through `serialize_scene` assert no lifetime,
  miss nothing and leave nothing live after teardown; those real camera
  moves agree with the synthetic `frame_scale` row (0 buffers, 0 bind
  groups, 2 uniform writes, 42 / 456 border dispatches on a zoom, 0.6–0.8 /
  1.2–2.1 ms of driver time in the main realm); `player.js` with
  `geometry_recording.js` over the real B4.7 driver, validation on, passes
  every `player_commands` mode as the B4.6 driver does (recovery, segments,
  formats 2–7, paint, border, Phase B, corrupt, and export over all four
  streams and the camera stream; formats 1–2 go to the winding driver);
  allocating the fake's GPU-filled outputs lazily moves class medians within
  noise, so the fake's own cost does not favour either driver; the class
  selection shares `select_frames`, `play_before`, `play_frame_count` and
  `replay_play` with `episode_frames.py`; and the main-realm option makes
  the same calls. The review ran at load ≈ 4, so its timings were
  indicative.
- **The native mirror.** `maniml/web/wgpu_renderer.py` still keys program,
  border and net outputs by `(…, occurrence)` and binds a program output
  once when an output is made, the structure behind the defect
  `programOutputsSurviveCoincidence` catches in the browser; the native
  driver was out of this increment's scope and was not tested for it.
- **Load.** As for B4.6, other sessions' work shared the machine (load
  average 3.3–5.2 over these runs, above 10 during an earlier replay that
  was discarded and re-run); the B4.6 driver's sandbox medians replayed now
  agree with the archive's within 1–10% on every class.

## After B4.8

B4.8 (`docs/phase_b4_plan.md`, "B4.8: shipped") makes the geometry a
stream for a page that announces format 8: a full frame opens an epoch,
each later message is a delta against the one before it (splices of the
batch list, program scalars as ops, the camera and the other header fields
only when they change, the definitions the page lacks), and a frame that
changes nothing is no message at all. The page's renderer selection reads
the renderer from the header's first bytes instead of parsing the header.
The rows below compare, frame for frame, the format 7 stream (what a tab
that has not negotiated is sent, as before) with the format 8 stream of the
same history.

### Runs

From the worktree on `b4-integration` (commit `1cf482b2` = main plus tiers
1 and 2, with the uncommitted B4.8 tree; `after_b48.json`
`episodes.*.source_files_sha256` has the hashes, unchanged during the
runs), Node v22.16.0, Apple M3, 21:05:29–21:07:22 UTC 2026-09-27, load
average 2.0–2.8, the GPU 13–14% busy with other applications (nothing
here uses it):

```bash
python -m benchmarks.browser_frames \
  --scene /Users/taylorjweidman/Projects/econ-0100/Blocks/B2_Supply/03_Code.py EpisodeB2 \
  --output <scratch>/B2 --samples 12 --warmups 3 --max-frames 12 --tick-updaters --play-frames \
  --play-edges --camera-moves --deltas --realm main --rounds 5
python -m benchmarks.browser_frames \
  --scene <scratch>/episodes/Blocks/B3_Equilibrium/Animate.py PriceDiscovery \
  --output <scratch>/B3 --samples 12 --warmups 3 --max-frames 12 --tick-updaters --play-frames \
  --play-edges --camera-moves --deltas --realm main --rounds 5
node tests/generated_webgpu_commands.cjs deltaEqualsFull <scratch>/<episode>/<variant> \
  <scratch>/<episode>/<variant>_delta
```

PriceDiscovery ran through a tree of links whose
`Blocks/B3_Equilibrium/Animate.py` is econ-0100's
`_archive/Animate.py` (sha256 `dfe6e831…`, the file every earlier run
measured) beside links to `B2_Supply`, `_Assets` and `Sim`;
`browser_frames.py` now takes the scene's path as given, as
`episode_frames.py` does, so the file imports its neighbours from the tree.
Each episode's four streams (414 and 400 messages; `--camera-moves` adds a
pan, a 2% zoom and the camera put back after every pausepoint's rounds)
were replayed five times, the format 7 and format 8 streams taking turns;
each row's times are its median over the rounds, every other column the
same in every round.

### The proof on these streams

`deltaEqualsFull` played each variant's two streams on two drivers,
validation on: after every message the same slots, the same live buffers
(size, usage, bytes) and the same submission, compute passes included; where
the format 8 stream sent nothing, the format 7 frame redrew the picture on
screen. All equal:

| Stream | Messages | Deltas | Not sent | Full |
| --- | ---: | ---: | ---: | ---: |
| EpisodeB2 Phase A / Phase B | 414 / 414 | 242 / 245 | 171 / 168 | 1 / 1 |
| PriceDiscovery Phase A / Phase B | 400 / 400 | 228 / 231 | 171 / 168 | 1 / 1 |

### (i) The gates

| Gate | Phase A | Phase B |
| --- | ---: | ---: |
| Wire at rest: 8.a, its updaters ticking, 14 rounds | 183,234 B → 0 (nothing sent) | 444,120 B → 0 |
| A camera move at 8.a: pan / 2% zoom / back | 183,263 → 456 / 517 / 427 B | 444,149 → 456 / 517 / 427 B |
| A camera move, every frame of both episodes | ≤ 671 B | ≤ 671 B |
| JS at rest: 8.a ticked, page_ms, 12 timed rounds (median, max) | 0.061, 0.064 ms → 0 (no render call) | 0.153, 0.185 ms → 0 |
| The round after the seek to 8.a (a warmup round), page_ms | 0.58 ms → 0 | 1.41 ms → 0 |
| Play, class median, page_ms (EpisodeB2 / PriceDiscovery) | 0.75 / 0.20 ms, ≤ 2 | 0.29 / 0.17 ms, ≤ 4 |
| Play, entry, landing: every frame (EpisodeB2 / PriceDiscovery) | 5.18 / 1.90 ms max | 11.51 / 2.27 ms max |

At rest the format 7 frame costs what B4.7's redraw of a byte-identical
resend costs; the timed rounds leave the warmup rounds out, as every class
does. The round after a seek is dearer, once: its message is not the
seek's (every batch is now cached), so the driver matches it batch by
batch. The first draft of this table gave that round (0.58 / 1.41 ms) as
the cost at rest, about ten times too much; `after_b48.json`'s `gate_8a`
now keeps the two apart.

The play gates were set on B4.6's sandbox medians (the plan's B4.7
finding); read here as the page's cost in the main realm, they bound the
class median on both episodes, and every play, entry and landing frame of
PriceDiscovery. They do not bound every frame of EpisodeB2: 14 of its 138
such frames exceed them each way, and a delta changes none of what makes
them dear, their uploads:

| Frames over the gate (format 8 stream) | Frames | page_ms | Uploaded a frame |
| --- | ---: | ---: | ---: |
| Phase A, 5.a's play (all 461 leaves move) | 12 | 4.09–5.18 | 3.4–3.9 MB |
| Phase A, 5.a's entry / landing | 1 / 1 | 4.57 / 2.57 | 3.4 / 2.5 MB |
| Phase B, 8.a's play (its movers are not programs) | 11 | 4.13–6.69 | ~0.9 MB |
| Phase B, 8.a's entry | 1 | 4.55 | 0.9 MB |
| Phase B, 5.a's entry / landing | 1 / 1 | 11.51 / 4.91 | 5.1 / 3.9 MB |

The format 7 stream has the same frames over the gates (Phase A 4.39–6.06
ms on 5.a's play; Phase B 4.17–5.70 on 8.a's, 12.80 on 5.a's entry): these
are B5.1's and tier 1's (a mover sent as rows, not as a mesh), as B4.7
found.

### (ii) Classes, format 7 → format 8

Each class's median page_ms and wire bytes (a frame not sent counts 0):

EpisodeB2

| Class (n) | Phase A page ms | Phase A wire KB | Phase B page ms | Phase B wire KB |
| --- | ---: | ---: | ---: | ---: |
| pausepoint (120) | 0.03 → 0.00 | 69.2 → 0.0 | 0.03 → 0.00 | 63.8 → 0.0 |
| ticked (24) | 0.05 → 0.00 | 129.1 → 0.0 | 0.12 → 0.00 | 282.1 → 0.0 |
| play (114) | 0.90 → 0.75 | 406.9 → 286.4 | 0.65 → 0.29 | 133.5 → 1.0 |
| cold (12) | 1.16 → 1.27 | 649.6 → 638.7 | 2.53 → 2.54 | 898.4 → 898.1 |
| play entry (12) | 0.66 → 0.50 | 312.9 → 247.2 | 1.44 → 1.37 | 446.8 → 386.8 |
| landing (12) | 0.30 → 0.12 | 122.7 → 60.1 | 0.92 → 0.52 | 314.7 → 304.0 |
| camera (36) | 0.29 → 0.09 | 78.7 → 0.4 | 0.30 → 0.12 | 70.0 → 0.4 |

PriceDiscovery

| Class (n) | Phase A page ms | Phase A wire KB | Phase B page ms | Phase B wire KB |
| --- | ---: | ---: | ---: | ---: |
| pausepoint (12) | 0.01 → 0.00 | 21.1 → 0.0 | 0.03 → 0.00 | 22.3 → 0.0 |
| ticked (132) | 0.02 → 0.00 | 44.7 → 0.0 | 0.03 → 0.00 | 63.7 → 0.0 |
| play (100) | 0.30 → 0.20 | 183.7 → 142.1 | 0.38 → 0.17 | 75.2 → 1.3 |
| cold (12) | 0.72 → 0.66 | 621.6 → 620.4 | 1.58 → 1.45 | 407.7 → 406.7 |
| play entry (12) | 0.31 → 0.17 | 301.8 → 285.0 | 1.16 → 1.37 | 245.9 → 221.2 |
| landing (12) | 0.19 → 0.06 | 99.5 → 56.4 | 0.72 → 0.64 | 181.2 → 157.4 |
| camera (36) | 0.19 → 0.09 | 42.3 → 0.6 | 0.34 → 0.13 | 63.5 → 0.6 |

A Phase B play is a kilobyte of scalars ops (its programs' batches are held
and kept); a Phase A play still sends its movers' meshes. A seek (cold) and
a play's entry send and make the same either way. Over eight more rounds of
PriceDiscovery Phase B the per-row minima sum to 12.05 against 12.01 ms
(entries) and 26.9 against 27.6 (seeks), and of EpisodeB2's Phase B seeks
to 42.8 against 41.7: the same. **EpisodeB2's Phase A seeks are not: they
cost 4-9% more under format 8**, about 0.1 ms a seek. Summed over the 12
seeks, per-row minima 25.5 against 26.9 ms (+5.5%) in those rounds; in the
review's eight (Node's main realm, the streams alternating which goes
first) medians 26.41 against 28.79 ms and minima 24.94 against 26.35, the
median row 1.139 against 1.214; in the fix pass's eight 26.30 against 27.60
and 25.14 against 26.16. Timed by stage in a scratch copy of the driver
(ten rounds), `expandDelta` costs 0.01 ms a seek and the difference is in
resolving the slots: a splice carries a middle whose length changed whole,
batches equal to their slot in place included, into the hash search (33
against 173 batches searched on one seek), but matching carried batches in
place first (`applyFull`'s first pass) made the searched counts equal
without closing the gap (minima 25.29 against 26.09), and the streams'
first message, the same full frame through the same code, is 0.3 ms slower
in the format 8 run as well, so not all of it is the delta's work. It is
left as measured, not as noise; the review's candidates (`heldBatch`
copies of kept head and tail batches, the middle's hash search) are
deferred. The first draft of the driver built a kept
slot's held descriptor by spreading the batch and deleting its offsets,
which left V8 an object in dictionary mode that every later frame's
`sameBatch` read field by field: EpisodeB2's Phase B seeks cost 3.3 ms
against 2.5 at the median until it copied the fields instead.

### (iii) What Python pays for the stream

Not this harness's measurement (the format 8 stream's `serialize_ms`
follows the format 7 serialization of the same frame). A scratch loop at
8.a, one scene, a format 7 cache and a format 8 one serializing each frame
in turns, alternating which goes first; median ms (min), 20 stills, 20
ticks, 10 pans of 1% of the frame, the 23 frames of the play into 8.a:

| 8.a | Phase A format 7 → 8 | Phase B format 7 → 8 |
| --- | ---: | ---: |
| still | 1.40 (1.33) → 1.48 (1.40) | 2.19 (2.02) → 2.31 (2.21) |
| ticked | 3.36 (2.87) → 3.54 (3.14) | 4.35 (4.07) → 4.40 (4.08) |
| pan | 3.02 (2.88) → 3.16 (3.01) | 3.13 (2.91) → 3.24 (3.05) |
| play | 81.1 (71.6) → 73.5 (70.7) | 102.9 (91.6) → 101.9 (92.4) |

About 0.1 ms a frame of diff over 444 runs (911 under Phase B): the kept
runs compare their held text, the same string object frame after frame.

### Scope and caveats (B4.8)

- The JavaScript is Node's on the counting fake device (validation off for
  the times, on for `deltaEqualsFull`), as for B4.6 and B4.7: not Dawn's
  per-call work, the GPU, the canvas present or the socket. No real-device
  pixel check of the delta path was run; the Node equivalence is the proof,
  as the plan has it (the native driver never sees a delta, and the format
  7 path B4.7 checked on a real device draws what the stream draws, call for
  call).
- The at-rest rows are silences: under format 8 the viewer sends nothing,
  so the page runs nothing. The 8.a ticked frame's zero depends on its
  updaters changing no byte, which B4.3's comparison already established;
  an updater that moves something sends a delta of what it moved.
- Load average 2.0–2.8 throughout, other applications sharing the machine.
- `after_b48.json` holds, per episode and stream, the classes, the gate
  figures, every play, entry and landing frame over its gate, the camera
  moves' bytes, the proof's counts, and the runs' commands, commit and
  source hashes; the streams themselves (≈ 180 MB) are not archived.

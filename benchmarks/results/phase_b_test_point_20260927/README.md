# The final test point (2026-09-28)

B6 (`docs/phase_b4_plan.md`, "The final test point"): what a lecture frame
costs, per class, for four stacks, on both gate episodes. **Today** is
Phase A without the retained frame (`MANIML_RETAINED_FRAME=0`) in format 7
full frames, drawn by `main`'s page (0a2bf3b2, the checkout Taylor teaches
from); **Phase A** is Phase A forced with the retained frame; **Default**
the default stack as the flips left it (no flip passed, so Phase A's
stack); **Phase B** the forced Phase B (patches, nets, its plays recording
GPU programs), each of the last three in format 7 and in the format 8
stream the shipped page negotiates. The directory is named for the
increment's chain (B4-B5, 2026-09-27); the runs are of 2026-09-28. The
reading is the plan's; this README holds the runs and every number.

## Runs

From `/Users/taylorjweidman/Projects/ManimLive/maniml-b4i` (branch
`b4-integration`, commit `894e841c`, B5.4, plus B6's harness as the runs
hashed it: `summary.json` `source_files_sha256` holds what the runs
measured, every run agreeing on every file; B6's fix pass changed three
harness files after the runs, "Source files" below), interpreter
`maniml/.venv/bin/python` (Python 3.13.9, wgpu 0.32.0, numpy 2.5.2), Node
22.16.0 for the page, Apple M3, Metal, macOS 26.6.2, one run at a time. The
scenes: EpisodeB2 (`Blocks/B2_Supply/03_Code.py`, sha256 `7e105159...`) and
PriceDiscovery (`B3_Equilibrium/_archive/Animate.py`, `dfe6e831...`, run as
in every B4 and B5 increment from a scratch tree of symbolic links that
keeps it at its old depth). Per episode (`benchmarks/README.md`, "The test
point"; `F=(--tick-updaters --play-frames)`):

```bash
python -m benchmarks.episode_frames --scene $S --variants retained default gpu_border $F --output <d>/frames_a
python -m benchmarks.episode_frames --scene $S --variants phase_b_retained gpu_border $F --output <d>/frames_b
python -m benchmarks.episode_frames --scene $S --variants gpu_border retained default phase_b_retained $F \
    --gpu-timestamps --output <d>/gpu1
python -m benchmarks.browser_frames --scene $S --variants phase_a default phase_b_forced $F --deltas \
    --realm main --rounds 5 --output <d>/browser
python -m benchmarks.test_point page --stream <d>/browser/phase_a --revision main --rounds 5 --output <d>/page
python -m benchmarks.test_point serialize --scene $S $F --output <d>/serialize
python -m benchmarks.episode_frames --scene $S --variants gpu_border retained default phase_b_retained $F \
    --gpu-timestamps --output <d>/gpu2
python -m benchmarks.test_point python --scene $S $F --output <d>/python
python -m benchmarks.test_point table --serialize <d>/serialize --browser <d>/browser --page <d>/page \
    --gpu <d>/gpu1 <d>/gpu2 --pixels <d>/frames_b <d>/frames_a --python <d>/python --output <d>/table
```

`MANIML_GPU_TIMESTAMPS` was unset for every run but `gpu1`/`gpu2`. The
frames are `episode_frames.select_frames`' twelve pausepoints: EpisodeB2's
12, 44, 76 (3.i, ticking), 103, 120, 140, 157, 177, 194, 258, 277 (5.a)
and 307 (8.a, ticking); PriceDiscovery's 9, 19, 35, 48, 58, 68, 86, 98,
109, 115, 123 (all ticking) and 130, which leave out 3.a.4 (63) between
3.a.3 (58) and 3.a.5 (68).

**Conditions.** The campaign ran 18:26-18:50 local, the GPU idle
(`ioreg` device utilization, three samples) and the one-minute load
2.2-3.4 at the start of every run but one. Another project's Playwright
tests ran in bursts all evening (WebKit and Chromium at up to 235% CPU,
load up to 16), and EpisodeB2's browser, page, serialize, second
attribution (which started with the GPU 15-24% busy) and instrumented runs
overlapped them. Those five and the table were taken again 18:57-19:05,
starting and ending at load 2.5 with the GPU at 0-19% (three samples each,
18:56 and 19:06); the first pass is in
`summary.json` (`first_pass_b2`), its complete frames within 0.7 ms of the
retake per class and stack (pausepoint 11.79 → 11.10 ms today, 1.03 → 0.81
Phase A format 8; plays 22.43 → 22.75, 14.89 → 14.69). PriceDiscovery's
runs were quiet. The real-device runs (below) were taken 19:14-19:16 at
load 5-9 from other sessions, the GPU 0-11% busy at their start.

**Today is main's Python.** `today` is this tree's whole-frame path. On
EpisodeB2's 0.a, 5.a and 8.a (ticking), serialized from an archive of
`main` and from this tree in alternate processes, three rounds, the
messages are the same length (175,421, 222,367 and 183,234 B) and the
serialize minima 10.6-11.0 against 10.5-11.6 ms, 16.4-17.2 against
16.8-16.9, 36.8-38.4 against 37.9-38.3 (one round of this tree's runs,
taken during a load spike, is set aside; `summary.json` `today_is_main`
has all six). The bytes are identical, by digest (B6's fix pass, an archive
of `main` 0a2bf3b2 and this tree, each with `MANIML_RETAINED_FRAME=0`;
`summary.json` `today_is_main_digests`): on each frame a fresh cache's
first message and the fifteen after it (8.a with an updater tick before
each) have the same blake2b in both trees, 0.a `49799abe...` (951,650 B,
the first) then `5de376be...` fifteen times (175,421 B), 5.a `f49f5df3...`
(2,496,980 B) then `e78a9d5e...` (222,367 B), 8.a `95f82bec...` (1,098,150
B) then `87aca8d6...` (183,234 B).

## Results

A cell is serialize + page + GPU = **complete** (the ratio to today); the
wire per message. Serialize: `test_point serialize` (the seven serializers
taking turns as `flip_gates` has two take them), each frame's median over
its rounds. Page: `browser_frames` `page_ms`, main realm, the fake device,
each frame's median over five rounds (today's from `test_point page`,
`main`'s page over the same format 7 stream). GPU: `gpu_total_ms`, the
median of the frame's rows over the two attribution runs, charged as the
share of the frame's messages the stream sent (format 8 sends a frame that
changes nothing nothing, and the page draws nothing). A class's figure is
the median over its frames, each play frame one value. Pixels: the share
of pixels more than 24/255 off `gpu_border` (Phase A, whole frame) in some
channel, worst frame of the class (a pausepoint's last round; every frame
strictly inside a play's window), largest channel difference in brackets.

**The GPU part is the native driver's, not the page's.** Taylor's gate
defines the GPU part as the attribution run's `gpu_total_ms`, and that is
what the tables carry: wgpu-native on Metal drawing the frame natively.
The page's GPU is Dawn's on the same M3, and the real device (below) shows
it paying far less for the same frame: 200 back-to-back redraws of 8.a
sustain 1.29-1.35 ms a redraw on Phase A and 1.74-1.78 on Phase B, page,
Dawn's GPU process and the GPU pipelined, each redraw encoding every slot
into targets at the header's full resolution, so the page's GPU for that
frame is at most 1.35 and 1.78 ms, where the tables charge 4.85 (Phase A)
and 6.44 ms (Phase B format 7, ticked). Natively Phase A's GPU is about 4.1
ms even at a pausepoint of 46 draws (checkpoint 103: 4.07, of it the out
pass 3.71), a fixed cost per frame that the device does not show. So
every reading the GPU column drives carries that native cost: a format 7
ratio (each format 7 frame is charged it), the plays, and Phase B against
the Default in plays (0.84× on EpisodeB2, 1.79× on PriceDiscovery, whose
GPU parts 5.39 → 9.70 and 4.34 → 9.41 ms are native). They are the gate's
numbers as defined; what the page's GPU pays per class was not measured
(the device's throughput per class, `redraw()` on a pausepoint, a ticked
frame and a play message per stack, would measure it).

### EpisodeB2

| Stack | pausepoint (10 frames) | ticked (2: 3.i, 8.a) | play (114 frames, 12 plays) | pixels: pausepoint / ticked / play |
| --- | ---: | ---: | ---: | --- |
| Today: Phase A, whole frame, format 7, main's page | 5.71 + 0.88 + 4.38 = **11.10**; 69.2 KB | 25.03 + 1.51 + 4.70 = **31.24**; 129.1 KB | 14.17 + 2.24 + 5.43 = **22.75**; 406.9 KB | reference |
| Phase A, retained, format 7 | 0.80 + 0.03 + 4.36 = **5.29** (0.48×); 69.2 KB | 3.05 + 0.05 + 4.69 = **7.79** (0.25×); 129.1 KB | 7.49 + 0.94 + 5.43 = **15.10** (0.66×); 406.9 KB | 0 / 0 / 0 |
| Phase A, retained, format 8 | 0.81 + 0 + 0 = **0.81** (0.07×); 0 | 2.97 + 0 + 0 = **2.97** (0.10×); 0 | 7.58 + 0.76 + 5.43 = **14.69** (0.65×); 286.4 KB | 0 / 0 / 0 |
| Default, format 7 | 0.77 + 0.03 + 4.36 = **5.30** (0.48×); 69.2 KB | 3.38 + 0.05 + 4.70 = **8.12** (0.26×); 129.1 KB | 7.42 + 0.95 + 5.39 = **15.09** (0.66×); 406.9 KB | 0 / 0 / 0 |
| Default, format 8 | 0.78 + 0 + 0 = **0.78** (0.07×); 0 | 3.02 + 0 + 0 = **3.02** (0.10×); 0 | 7.46 + 0.76 + 5.39 = **14.83** (0.65×); 286.4 KB | 0 / 0 / 0 |
| Phase B, format 7 | 0.75 + 0.03 + 5.14 = **6.13** (0.55×); 63.8 KB | 4.01 + 0.09 + 6.09 = **10.20** (0.33×); 282.1 KB | 2.27 + 0.68 + 9.70 = **12.66** (0.56×); 133.5 KB | 0.000% (21) / 0.000% (23) / 0.000% (30, one pixel) |
| Phase B, format 8 | 0.77 + 0 + 0 = **0.77** (0.07×); 0 | 3.74 + 0 + 0 = **3.74** (0.12×); 0 | 2.58 + 0.30 + 9.70 = **12.41** (0.55×); 1.0 KB | the same |

The heaviest frames, per stack (each frame's median; format 8 but today):

| Frame | Today | Phase A, format 8 | Default, format 8 | Phase B, format 8 |
| --- | ---: | ---: | ---: | ---: |
| 8.a ticking | 37.93 + 2.00 + 4.85 = **44.77**; 179 KB | 4.40; 0 | 4.51; 0 | 5.80; 0 |
| 8.a's play | 89.72 + 2.38 + 5.43 = **97.53**; 484 KB | 87.32 + 0.81 + 5.43 = **93.56**; 388 KB | **94.69** | 109.43 + 4.69 + 22.17 = **136.30**; 972 KB |
| 5.a still | 17.23 + 2.73 + 6.07 = **26.04**; 217 KB | 2.06; 0 | 2.04; 0 | 2.08; 0 |
| 5.a's play (all 461 leaves move) | 56.15 + 8.07 + 21.01 = **85.23**; 2465 KB | 66.24 + 4.87 + 19.67 = **90.78**; 2464 KB | **93.34** | 27.40 + 1.12 + 45.94 = **74.46**; 20 KB |

### PriceDiscovery

| Stack | pausepoint (1 frame) | ticked (11 frames) | play (100 frames, 12 plays) | pixels: pausepoint / ticked / play |
| --- | ---: | ---: | ---: | --- |
| Today: Phase A, whole frame, format 7, main's page | 3.78 + 0.33 + 4.15 = **8.26**; 21.1 KB | 7.04 + 0.65 + 4.27 = **12.29**; 44.7 KB | 8.44 + 0.91 + 4.33 = **13.52**; 183.7 KB | reference |
| Phase A, retained, format 7 | 0.72 + 0.01 + 4.15 = **4.88** (0.59×); 21.1 KB | 1.06 + 0.02 + 4.27 = **5.32** (0.43×); 44.7 KB | 3.39 + 0.31 + 4.33 = **7.95** (0.59×); 183.7 KB | 0 / 0 / 0 |
| Phase A, retained, format 8 | 0.74 + 0 + 0 = **0.74** (0.09×); 0 | 1.06 + 0 + 0 = **1.06** (0.09×); 0 | 3.32 + 0.20 + 4.33 = **7.77** (0.57×); 141.9 KB | 0 / 0 / 0 |
| Default, format 7 | 0.73 + 0.01 + 4.15 = **4.88** (0.59×); 21.1 KB | 1.04 + 0.02 + 4.27 = **5.28** (0.43×); 44.7 KB | 3.37 + 0.31 + 4.34 = **7.91** (0.59×); 183.7 KB | 0 / 0 / 0 |
| Default, format 8 | 0.78 + 0 + 0 = **0.78** (0.09×); 0 | 1.05 + 0 + 0 = **1.05** (0.09×); 0 | 3.39 + 0.20 + 4.34 = **7.86** (0.58×); 141.9 KB | 0 / 0 / 0 |
| Phase B, format 7 | 0.74 + 0.03 + 4.86 = **5.63** (0.68×); 22.3 KB | 1.17 + 0.03 + 4.76 = **6.11** (0.50×); 63.7 KB | 2.51 + 0.39 + 9.41 = **13.98** (1.03×); 75.4 KB | 0.000% (27) / 0.041% (142) / **2.024% (153)** ¹ |
| Phase B, format 8 | 0.73 + 0 + 0 = **0.73** (0.09×); 0 | 1.19 + 0 + 0 = **1.19** (0.10×); 0 | 2.96 + 0.21 + 9.41 = **14.08** (1.04×); 1.7 KB | the same ¹ |

¹ Measured without the pack_rows fix (another session's uncommitted edit
of `maniml/web/gpu_program_geometry.py`, "Phase B's pixels on
PriceDiscovery" below): `frames_b` recorded that file's sha256 as
`60fdc6a2...`, the file of commit `894e841c`, at its start and unchanged at
its end. Only the play figure can move with the fix: `pack_rows` packs a
program's endpoint rows, and only a play records programs, so the
pausepoint's 0.000% and the ticked frames' 0.041% (the spheres as nets)
cannot.

### The flag-off check

The same frames with the GPU part the flag-off runs' wall clock from the
submit through the full readback (`frames_a`, `frames_b`: no stamps, a
readback the browser never does), complete frame in ms:

| Stack | EpisodeB2: pausepoint / ticked / play | PriceDiscovery: pausepoint / ticked / play |
| --- | ---: | ---: |
| Today | 14.10 / 34.19 / 24.98 | 10.53 / 14.43 / 15.60 |
| Phase A, retained, format 7 / 8 | 8.31 / 10.69 / 17.57; 0.81 / 2.97 / 17.16 | 7.13 / 7.57 / 10.01; 0.74 / 1.06 / 9.83 |
| Default, format 7 / 8 | 8.34 / 11.02 / 17.48; 0.78 / 3.02 / 17.23 | 7.16 / 7.56 / 9.97; 0.78 / 1.05 / 9.90 |
| Phase B, format 7 / 8 | 8.43 / 13.33 / 13.77; 0.77 / 3.74 / 13.53 | 7.29 / 8.99 / 15.16; 0.73 / 1.19 / 15.41 |

### Today's page against this tree's

The `phase_a` format 7 stream through `main`'s page and this tree's, taking
turns, five rounds, `page_ms` at the class median (ms): EpisodeB2
pausepoint 0.910 → 0.027, ticked 1.509 → 0.054, play 2.121 → 0.919;
PriceDiscovery 0.327 → 0.010, 0.666 → 0.019, 0.918 → 0.312.

### Where Python goes

`test_point python`, one instrumented run (timers around Lyon's
tessellations, the retained frame's comparisons of a moved revision, the
stream's diff; read its parts against each other, the serialize run for
totals). Medians per serialization, so the parts do not add exactly;
"scene's own" is the scene's Python before the serialization (a tick's
updaters; a play's interpolation and updaters since the frame before).
Kept / compared / prepared are the retained frame's leaves. A mean over
these rows would mislead: one flag-off tick at 8.a took 525.6 ms (a
collection pause) among rows of 36-44. `test_point table --python` prints
these rows from the run's own rows, per class and per checkpoint (8.a is
checkpoint 307, 5.a 277; `summary.json` `python_p50_by_checkpoint` holds
the checkpoints quoted).

| EpisodeB2, serializer, class (n) | scene's own | serialize | prepare | Lyon (calls) | compare (calls) | encode | diff | kept / compared / prepared | wire |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| today, pausepoint (120) | 0 | 5.80 | 3.98 | 0 | – | 1.80 | – | – | 69.2 KB |
| today, ticked (24) | 10.75 | 23.73 | 20.28 | 0 | – | 3.42 | – | – | 129.1 KB |
| today, play (228) | 0.64 | 13.94 | 10.52 | 0 | – | 3.27 | – | – | 406.9 KB |
| Default f8, pausepoint (120) | 0 | 0.82 | 0.64 | 0 | 0 | 0.17 | 0.021 | 186 / 0 / 0 | 0 |
| Default f8, ticked (24) | 10.80 | 3.05 | 2.66 | 0 | 0.96 (219) | 0.38 | 0.045 | 413 / 219 / 0 | 0 |
| Default f8, play (228) | 0.66 | 7.57 | 5.78 | 0 | 0.16 (33) | 1.69 | 0.021 | 114 / 0 / 33 | 286.4 KB |
| Phase B f8, pausepoint (120) | 0 | 0.81 | 0.62 | 0 | 0 | 0.16 | 0.017 | 186 / 0 / 0 | 0 |
| Phase B f8, ticked (24) | 10.65 | 3.92 | 3.13 | 0 | 0.96 (219) | 0.75 | 0.069 | 413 / 219 / 0 | 0 |
| Phase B f8, play (228) | 0.39 | 2.69 | 1.41 | 0 | 0 | 1.27 | 0.193 | 114 / 0 / 33 | 1.0 KB |
| 8.a ticking: today (12) | 20.60 | 37.37 | 32.55 | 0 | – | 4.71 | – | – | 178.9 KB |
| 8.a ticking: Default f8 (12) | 20.73 | 4.59 | 4.07 | 0 | 1.83 (415) | 0.50 | 0.063 | 531 / 415 / 0 | 0 |
| 8.a ticking: Phase B f8 (12) | 20.34 | 6.47 | 5.25 | 0 | 1.80 (415) | 1.18 | 0.126 | 531 / 415 / 0 | 0 |
| 8.a's play: today (24) | 20.65 | 90.28 | 84.85 | 11.01 (360) | – | 5.21 | – | – | 484.1 KB |
| 8.a's play: Default f8 (24) | 20.57 | 88.15 | 84.59 | 11.62 (360) | 0.84 (415) | 3.51 | 0.063 | 170 / 54 / 360 | 387.8 KB |
| 8.a's play: Phase B f8 (24) | 20.55 | 107.79 | 92.26 | 0 | 0.85 (415) | 15.36 | 0.089 | 170 / 54 / 360 | 972.3 KB |
| 5.a still: Default f8 (12) | 0 | 2.43 | 1.80 | 0 | 0 | 0.61 | 0.065 | 461 / 0 / 0 | 0 |
| 5.a's play: today (24) | 4.74 | 57.27 | 45.39 | 0 | – | 12.50 | – | – | 2464.9 KB |
| 5.a's play: Default f8 (24) | 4.67 | 66.43 | 52.58 | 0 | 1.24 (461) | 13.46 | 0.058 | 0 / 0 / 461 | 2464.4 KB |
| 5.a's play: Phase B f8 (24) | 2.86 | 26.46 | 7.69 | 0 | 0 | 18.70 | 3.309 | 0 / 0 / 461 | 19.6 KB |

| PriceDiscovery, serializer, class (n) | scene's own | serialize | prepare | Lyon (calls) | compare (calls) | encode | diff | kept / compared / prepared | wire |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| today, pausepoint (12) | 0 | 5.55 | 4.48 | 0 | – | 0.81 | – | – | 21.1 KB |
| today, ticked (132) | 1.44 | 8.50 | 6.40 | 0 | – | 1.88 | – | – | 44.7 KB |
| today, play (200) | 0.96 | 9.29 | 7.37 | 0 | – | 2.11 | – | – | 183.7 KB |
| Default f8, pausepoint (12) | 0 | 1.14 | 0.99 | 0 | 0 | 0.13 | 0.009 | 184 / 0 / 0 | 0 |
| Default f8, ticked (132) | 1.45 | 1.16 | 1.00 | 0 | 0.24 (49) | 0.15 | 0.014 | 215 / 49 / 0 | 0 |
| Default f8, play (200) | 0.95 | 4.89 | 4.27 | 0 | 0.24 (73) | 0.61 | 0.015 | 182 / 20 / 26 | 142.1 KB |
| Phase B f8, pausepoint (12) | 0 | 1.10 | 0.85 | 0 | 0 | 0.16 | 0.011 | 184 / 0 / 0 | 0 |
| Phase B f8, ticked (132) | 1.44 | 1.26 | 1.03 | 0 | 0.22 (49) | 0.24 | 0.022 | 215 / 49 / 0 | 0 |
| Phase B f8, play (200) | 0.67 | 2.98 | 1.31 | 0 | 0.05 (19) | 1.73 | 0.314 | 179 / 19 / 52 | 1.3 KB |

### The GPU by pass

Median exclusive pass times over both attribution runs (ms): EpisodeB2
Phase A pausepoint out 4.08 of 4.45, Phase B out 4.85 of 5.21; ticked 4.47
of 4.83 against 6.02 of 6.38; plays Phase A borders 0.59 and out 4.25 of
5.57, Phase B programs 1.52, borders 1.71 and out 4.28 of 9.64.
PriceDiscovery pausepoint out 3.78 of 4.15 against 4.50 of 4.86; plays
Phase A out 3.88 of 4.34, Phase B programs 2.39, borders 1.90 and out 4.57
of 9.48 (`summary.json` `gpu_passes_p50`).

### On a real device

`device_redraw.html`, served on loopback from a folder holding this tree's
`webgpu.js` and `wgsl/` and EpisodeB2's four recorded streams (its opening
comment says how), in the desktop app's browser pane: Chrome 152, Dawn on
Metal, this M3. `redraw()` replays the stream to 8.a's last ticked round
(message 314, a format 7 resend) and redraws it 200 times back to back,
the two stacks in two turns of three rounds:

| 8.a resend | batches / draws | page JS a redraw, device | the same, fake device | sustained a redraw (page, Dawn's GPU process, GPU) |
| --- | ---: | ---: | ---: | ---: |
| Phase A | 444 / 445 | 0.095, 0.10 ms (rounds 0.078-0.12) | 0.065 ms | 1.29, 1.35 ms (1.25-1.35) |
| Phase B | 911 / 1841 | 0.89, 0.89 ms (0.64-1.19) | 0.14 ms | 1.74, 1.78 ms (1.61-2.42) |

`measure()` plays each stream message by message, three rounds, timing the
driver's render (the page's clock is coarsened to 0.1 ms there) and the
time from it to `onSubmittedWorkDone`. At the class medians, device against
fake device: Phase A format 7 pausepoint 0.1 / 0.026 ms, play 1.1 / 0.95;
format 8 play 1.0 / 0.76; Phase B format 7 pausepoint 0.1 / 0.029, ticked
0.25 / 0.10, play 0.7 / 0.67; format 8 play 0.4 / 0.30. 8.a's play 1.4-1.6
/ 0.81-1.07 (Phase A), 8.7-9.0 / 4.6-4.7 ms (Phase B, ~1400 buffers made a
frame). The completion follows the render by 3.0-3.65 ms at a pausepoint
and 5.3-7.0 in plays. No validation error on any run
(`summary.json` `device`).

What these isolate, and what they do not. The page's JavaScript covers the
renderer side of Dawn's wire (each WebGPU call serialized for the GPU
process as it is made): 0.89 ms a redraw at 911 slots, the median of three
rounds in each of two turns, the six rounds 0.64, 1.19, 0.89, 1.05, 0.88
and 0.89 ms (two over 1 ms), taken at load 5-9 with other sessions active.
The GPU process's side (the wire server, validation, Metal encoding) was
not isolated: the only figure that holds it is the sustained redraw, 1.74-
1.78 ms at 911 slots and 1841 draws against 1.29-1.35 at 444 and 445, and
that holds the GPU's work too. B4.9's condition (Dawn's per-draw cost above
1 ms at 911 slots) is therefore not shown either way (the plan's reading).
It would be settled on a quiet machine with Dawn's GPU-process time
isolated: `redraw()` over the 8.a stream serialized at a tiny resolution,
so that the GPU is negligible and the sustained redraw is Dawn's, or the
GPU process's task time read from a Chrome trace.

### Phase B's pixels on PriceDiscovery

`pixels_pricediscovery_3a1.png` is the evidence: the second frame of the
play into 3.a.1 (checkpoint 48), Phase B drawing the CPU path (programs
off; left), Phase B with its GPU programs (middle) and their difference
(right), cropped to x 100-560, y 90-660 of 2160 × 1080. With programs the
play's nine rays (grey `Line`s fading in, 0.1-14% of the way) are an
opaque magenta fan in the paint of `best_check`'s dashed line, whose 28
dashes carry programs too and whose updater `become()`s it every frame.
Drawn apart (`summary.json` `pixel_diagnosis_pricediscovery`): Phase B
with programs off against Phase A 0.03% (the spheres as nets), Phase B
with programs against programs off 2.0% (46,469 pixels, largest channel
151), the whole-frame path the same as the retained frame. The same play's
worst in `frames_b` is 2.024%; four more of the 3.a plays 0.41-1.50%.

**Every figure here is without the pack_rows fix.** Another session, started
from this finding, fixed it in this worktree: `pack_rows` now writes a
VMobject source's base-point rows from its first point, as its shader data
does, so a patch fill no longer fans from a stale base point after an
updater's `become()`. The edit (`maniml/web/gpu_program_geometry.py`,
sha256 `63439d8f...`, last written 19:10, with a test in
`tests/test_program_library.py`) is uncommitted and is not B6's. Measured
without it, the file of commit `894e841c` (sha256 `60fdc6a2...`): the
2.024% play and the 0.41-1.50% plays (`frames_b`, which recorded that hash
at its start and unchanged at its end); the diagnosis's 2.0%, 0.03%, the
whole-frame path's equality and the crop (`diag_pd.py`, `diag_pd2.py`,
`diag_pd3.py`, run 18:52-18:56, which recorded no hash, but ran between
runs that recorded `60fdc6a2...` at their start and unchanged at their end:
PriceDiscovery's instrumented run, ending 18:50, and EpisodeB2's retaken
browser run, 18:57-18:58). The fix can move the play figures only (a
pausepoint records no program); the 0.03% is programs off, which never
packs a program. A rerun of the diagnosis at ~19:20, with the edit in the
tree, read 0% between programs and the CPU path on every frame and is not
used here: it measured the fix.

## Files

- `summary.json`: per episode the stacks per class (`stacks`, parts,
  complete, flag-off check, pixels, wire; the Phase B stacks' `pixels_source`
  says which `gpu_program_geometry.py` their pixels were measured with),
  `ratios`, the page comparison, the instrumented medians per class and at
  named checkpoints; the check against `main` (`today_is_main`, lengths and
  timings; `today_is_main_digests`, the bytes); `gpu_part`, what the GPU
  column is; the device's results; the GPU by pass; the pixel diagnosis;
  `pack_rows_fix`; EpisodeB2's first pass; `runs` (each run's command,
  start, commit and whether its sources held still); the source hashes.
- `report_episode_b2_table.json`: the EpisodeB2 table in full, every
  frame's serialize, page, GPU, complete and wire per stack and class.
- `device_redraw.html`: the real-device page.
- `pixels_pricediscovery_3a1.png`: the crop cited above.

**Source files.** Every run's hashes agree for every file. Every run
measured `maniml/web/gpu_program_geometry.py` as commit `894e841c` has it
(`60fdc6a2...`), without the pack_rows fix; the working tree holds the
fix's edit (`63439d8f...`, `source_files_not_in_the_working_tree`), made
after the runs by the session fixing the defect above, uncommitted. B6's
fix pass then changed three harness files after the runs
(`harness_after_fix_pass` has their hashes): `benchmarks/test_point.py`'s
`table --python` now prints the instrumented run's medians per class and
per checkpoint, reduced from the run's rows (it printed means per class),
and over these runs it prints the "Where Python goes" tables above
exactly; and `episode_frames.py` and `gpu_borders.py`'s `default` takes
`MANIML_PROGRAMS` and `MANIML_PATCH_SOURCE` out of the environment as
`browser_frames` and `test_point` do, its plays replaying under
`programs.DEFAULT_MODE`, where the runs had it serialize under the run's
`MANIML_PROGRAMS=off` and the records pin. With the defaults as they are
(`off`, `records`) that selects the stack the runs measured, in the same
replays, so no number here moves; the change keeps the three harnesses'
Default one stack when a default flips.

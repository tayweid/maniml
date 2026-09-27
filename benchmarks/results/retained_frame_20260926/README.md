# The retained frame on two course episodes (2026-09-27)

Phase B4's tier 1 (`docs/phase_b4_plan.md`, B4.5): Phase A with the retained
frame (`MANIML_RETAINED_FRAME=1`, the variant `retained`) against Phase A
without it (`gpu_border`, which `benchmarks/episode_frames.py` runs with the
switch at 0), on the frames of the two course episodes the plan's gates are
measured on. The complete native frame each time: serialize, parse,
prepare, encode, submit, full 2160x1080 readback, PIL image. The directory
is named for the plan's day; the runs are of 2026-09-27.

## Runs

From `/Users/taylorjweidman/Projects/ManimLive/maniml-b4` (branch
`b4-retained-frame`, commit `4f13b18b`, B4.4, **plus B4.5's working tree as
committed**: `summary.json` `source_files_sha256` carries the hashes of what
was measured, identical across the four runs, unchanged during each, and
equal to B4.5's commit), interpreter `maniml/.venv/bin/python` (Python
3.13.9, wgpu 0.32.0, numpy 2.5.2), Apple M3, Metal, IntegratedGPU, macOS
26.6.2, one run at a time, 18:44-18:46 UTC:

```bash
B2=/Users/taylorjweidman/Projects/econ-0100/Blocks/B2_Supply/03_Code.py
PD=<the pin's scratch tree>/Blocks/B3_Equilibrium/Animate.py   # see below
python -m benchmarks.episode_frames --scene $B2 EpisodeB2 --variants gpu_border retained \
  --samples 8 --warmups 2 --max-frames 12 --output <dir>/b2_static
python -m benchmarks.episode_frames --scene $PD PriceDiscovery --variants gpu_border retained \
  --samples 8 --warmups 2 --max-frames 12 --output <dir>/pd_static
python -m benchmarks.episode_frames --scene $B2 EpisodeB2 --variants gpu_border retained \
  --samples 8 --warmups 2 --max-frames 12 --tick-updaters --play-frames --output <dir>/b2_live
python -m benchmarks.episode_frames --scene $PD PriceDiscovery --variants gpu_border retained \
  --samples 8 --warmups 2 --max-frames 12 --tick-updaters --play-frames --output <dir>/pd_live
```

PriceDiscovery's `Animate.py` moved into `B3_Equilibrium/_archive/` in the
course checkout during B4.1 (sha256 `dfe6e831...`, byte-identical to the one
the goldens were recorded from); it finds its style module through
`dirname(__file__)/../_Assets`, so it ran, as in every B4 increment, from a
scratch tree of symbolic links that keeps it at its old depth, and the
harness takes the episode's path as given rather than resolving it.
EpisodeB2's `03_Code.py` is sha256 `7e105159...`. Twelve pausepoints each
(`summary.json` `runs.*.scene.measured_checkpoints`), 8 samples after 2
warmups per frame and phase, the two variants rotating frame by frame. Each
run took 12-38 s. `report_episode_b2_live.json` is the EpisodeB2 live run's
complete report; the other reports stay in the scratch directory.

**The GPU was not quiet.** Other applications (a browser's GPU process
among them) held the M3 at 25-40% device utilization before and after every
run (`ioreg -r -c IOAccelerator`, three samples each, `summary.json`
`runs.*.gpu_device_utilization_percent_*`), and the load averages were
2.5-3.7. Both variants rotate frame by frame under the same load, their GPU
work is the same by construction (the same bytes: `message_bytes` agree on
every row), and what the retained frame changes is Python's share, so the
comparison holds; the absolute readback and complete figures are higher
than on a quiet machine and are not comparable with
`gpu_timestamps_20260926`'s.

## Results

Pixels: `retained_vs_gpu_border` is 0.000% on every frame and every play of
all four runs (`max_pixel_fraction_retained_vs_gpu_border` 0.0), as equal
bytes make it.

"Complete" is `serialize_through_rgba_image_ms`, "Prepare" the
`geometry.triangle_prepare` stage, "Encode" `geometry.triangle_encode`
(serialize_generated_frame, or the retained frame's reuse of descriptors);
"Kept / prepared" is the retained frame's mean leaf count per row.

**EpisodeB2, pausepoints (static redraw)** (`b2_static`), ms, median of 8:

| Checkpoint | Name | Phase | Complete, gpu_border | Complete, retained | Prepare, gpu_border | Prepare, retained | Encode, gpu_border | Encode, retained | Kept / prepared |
| ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 12 | 0.a | still | 27.45 | 16.95 | 7.02 | 1.08 | 4.27 | 0.30 | 258 / 0 |
| 44 | 2.h | still | 16.15 | 10.50 | 3.46 | 0.60 | 1.57 | 0.14 | 148 / 0 |
| 76 | 3.i | still | 22.50 | 13.49 | 7.14 | 1.10 | 2.09 | 0.19 | 295 / 0 |
| 103 | 4.c.1 | still | 9.42 | 7.43 | 1.51 | 0.38 | 0.68 | 0.09 | 79 / 0 |
| 120 | 4.b.2 | still | 10.34 | 8.02 | 2.10 | 0.53 | 0.80 | 0.10 | 122 / 0 |
| 140 | 4.b.4 | still | 12.52 | 10.29 | 2.11 | 0.54 | 0.80 | 0.10 | 122 / 0 |
| 157 | 4.return.5 | still | 18.70 | 13.71 | 4.87 | 0.89 | 2.04 | 0.18 | 223 / 0 |
| 177 | 4.return.7 | still | 20.49 | 12.37 | 5.07 | 0.89 | 2.09 | 0.19 | 229 / 0 |
| 194 | 4.d.9 | still | 12.10 | 9.46 | 2.32 | 0.59 | 0.94 | 0.12 | 132 / 0 |
| 258 | 4.h | still | 28.46 | 16.97 | 9.13 | 1.31 | 3.09 | 0.27 | 362 / 0 |
| 277 | 5.a | still | 37.74 | 22.01 | 10.74 | 1.64 | 5.87 | 0.48 | 461 / 0 |
| 307 | 8.a | still | 36.86 | 21.48 | 15.49 | 1.86 | 4.52 | 0.34 | 531 / 0 |
| all | | pausepoints | 19.70 | 13.29 | 5.00 | 0.89 | 2.07 | 0.18 | |

**EpisodeB2, updaters ticking and plays** (`b2_live`), ms, median of 8:

| Checkpoint | Name | Phase | Complete, gpu_border | Complete, retained | Prepare, gpu_border | Prepare, retained | Encode, gpu_border | Encode, retained | Kept / prepared |
| ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 12 | 0.a | still | 27.50 | 17.16 | 6.88 | 1.04 | 4.30 | 0.29 | 258 / 0 |
| 12 | 0.a | play into it (11) | 42.07 | 33.03 | 11.27 | 6.23 | 5.65 | 1.74 | 225 / 33 |
| 44 | 2.h | still | 16.73 | 12.04 | 3.46 | 0.63 | 1.56 | 0.14 | 148 / 0 |
| 44 | 2.h | play into it (43) | 25.21 | 24.88 | 6.09 | 6.15 | 2.07 | 1.93 | 78 / 70 |
| 76 | 3.i | ticking | 23.75 | 14.35 | 7.95 | 1.20 | 2.13 | 0.20 | 295 / 0 |
| 76 | 3.i | play into it (75) | 25.63 | 17.01 | 8.70 | 2.06 | 2.31 | 0.41 | 291 / 4 |
| 103 | 4.c.1 | still | 12.98 | 9.26 | 1.56 | 0.42 | 0.70 | 0.09 | 79 / 0 |
| 103 | 4.c.1 | play into it (102) | 15.19 | 13.57 | 2.80 | 2.05 | 0.92 | 0.52 | 69 / 10 |
| 120 | 4.b.2 | still | 13.26 | 9.79 | 2.06 | 0.56 | 0.79 | 0.11 | 122 / 0 |
| 120 | 4.b.2 | play into it (119) | 15.29 | 13.66 | 3.03 | 1.83 | 1.03 | 0.44 | 114 / 8 |
| 140 | 4.b.4 | still | 11.88 | 10.73 | 2.10 | 0.55 | 0.81 | 0.11 | 122 / 0 |
| 140 | 4.b.4 | play into it (139) | 15.81 | 13.61 | 3.08 | 1.85 | 1.04 | 0.44 | 114 / 8 |
| 157 | 4.return.5 | still | 20.38 | 13.13 | 4.96 | 0.92 | 2.05 | 0.20 | 223 / 0 |
| 157 | 4.return.5 | play into it (156) | 38.69 | 39.31 | 11.23 | 11.92 | 3.37 | 3.01 | 109 / 115 |
| 177 | 4.return.7 | still | 21.04 | 15.00 | 5.30 | 0.94 | 2.15 | 0.20 | 229 / 0 |
| 177 | 4.return.7 | play into it (176) | 39.10 | 40.41 | 11.43 | 12.23 | 3.37 | 3.12 | 109 / 121 |
| 194 | 4.d.9 | still | 12.86 | 11.25 | 2.36 | 0.61 | 0.96 | 0.12 | 132 / 0 |
| 194 | 4.d.9 | play into it (193) | 13.33 | 11.25 | 2.71 | 1.19 | 1.02 | 0.27 | 129 / 3 |
| 258 | 4.h | still | 27.96 | 17.82 | 9.06 | 1.40 | 3.05 | 0.29 | 362 / 0 |
| 258 | 4.h | play into it (257) | 39.50 | 29.80 | 13.28 | 6.28 | 4.21 | 1.48 | 361 / 29 |
| 277 | 5.a | still | 41.35 | 25.37 | 10.88 | 1.71 | 5.78 | 0.48 | 461 / 0 |
| 277 | 5.a | play into it (276) | 138.14 | 147.40 | 44.85 | 54.25 | 12.07 | 13.53 | 0 / 461 |
| 307 | 8.a | ticking | 49.91 | 24.30 | 25.98 | 3.90 | 4.58 | 0.38 | 531 / 0 |
| 307 | 8.a | play into it (306) | 108.94 | 108.43 | 77.47 | 79.62 | 5.17 | 3.29 | 166 / 365 |
| all | | pausepoints | 20.57 | 13.90 | 4.99 | 0.92 | 2.09 | 0.20 | |
| all | | plays | 37.47 | 28.44 | 11.01 | 6.19 | 3.28 | 1.70 | |

**PriceDiscovery, pausepoints (static redraw)** (`pd_static`), ms, median of 8:

| Checkpoint | Name | Phase | Complete, gpu_border | Complete, retained | Prepare, gpu_border | Prepare, retained | Encode, gpu_border | Encode, retained | Kept / prepared |
| ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 9 | 0.a | still | 13.73 | 8.50 | 2.42 | 0.53 | 1.54 | 0.10 | 148 / 0 |
| 19 | 1.b | still | 11.59 | 8.13 | 2.66 | 0.64 | 0.97 | 0.10 | 155 / 0 |
| 35 | 2.b.i | still | 14.26 | 10.77 | 3.07 | 0.75 | 1.19 | 0.12 | 206 / 0 |
| 48 | 3.a.1 | still | 14.12 | 10.48 | 3.75 | 0.66 | 1.64 | 0.11 | 199 / 0 |
| 58 | 3.a.3 | still | 15.90 | 10.97 | 4.21 | 0.74 | 1.78 | 0.11 | 215 / 0 |
| 68 | 3.a.5 | still | 17.47 | 9.26 | 4.41 | 0.80 | 1.89 | 0.13 | 233 / 0 |
| 86 | 3.a.8 | still | 17.33 | 10.76 | 4.63 | 0.83 | 1.93 | 0.13 | 235 / 0 |
| 98 | 3.a.10 | still | 16.02 | 12.54 | 3.72 | 0.76 | 1.93 | 0.13 | 212 / 0 |
| 109 | 3.a.12 | still | 17.78 | 11.91 | 4.64 | 0.84 | 2.00 | 0.13 | 245 / 0 |
| 115 | 3.b.1 | still | 15.68 | 11.74 | 3.86 | 0.79 | 2.03 | 0.14 | 222 / 0 |
| 123 | 3.b | still | 19.05 | 13.19 | 4.36 | 0.94 | 2.19 | 0.15 | 257 / 0 |
| 130 | 5.a | still | 13.37 | 8.87 | 3.15 | 0.74 | 0.70 | 0.10 | 184 / 0 |
| all | | pausepoints | 15.42 | 10.92 | 3.84 | 0.77 | 1.84 | 0.12 | |

**PriceDiscovery, updaters ticking and plays** (`pd_live`), ms, median of 8:

| Checkpoint | Name | Phase | Complete, gpu_border | Complete, retained | Prepare, gpu_border | Prepare, retained | Encode, gpu_border | Encode, retained | Kept / prepared |
| ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 9 | 0.a | ticking | 14.30 | 9.22 | 3.06 | 0.58 | 1.56 | 0.10 | 148 / 0 |
| 9 | 0.a | play into it (8) | 14.82 | 11.61 | 3.48 | 1.07 | 1.64 | 0.22 | 146 / 2 |
| 19 | 1.b | ticking | 13.33 | 9.22 | 2.91 | 0.70 | 0.97 | 0.11 | 155 / 0 |
| 19 | 1.b | play into it (18) | 41.38 | 38.71 | 11.28 | 10.92 | 3.24 | 2.66 | 89 / 66 |
| 35 | 2.b.i | ticking | 16.26 | 11.99 | 4.71 | 1.15 | 1.21 | 0.13 | 206 / 0 |
| 35 | 2.b.i | play into it (34) | 26.43 | 25.39 | 7.67 | 5.12 | 2.02 | 1.16 | 182 / 24 |
| 48 | 3.a.1 | ticking | 17.21 | 12.40 | 5.91 | 0.93 | 1.66 | 0.12 | 199 / 0 |
| 48 | 3.a.1 | play into it (47) | 19.96 | 13.92 | 5.94 | 2.50 | 1.74 | 0.36 | 168 / 31 |
| 58 | 3.a.3 | ticking | 20.61 | 11.39 | 5.92 | 0.98 | 1.78 | 0.13 | 209 / 6 |
| 58 | 3.a.3 | play into it (57) | 19.25 | 13.98 | 6.25 | 2.72 | 1.88 | 0.42 | 182 / 33 |
| 68 | 3.a.5 | ticking | 18.58 | 11.65 | 6.43 | 1.05 | 1.94 | 0.15 | 233 / 0 |
| 68 | 3.a.5 | play into it (67) | 22.56 | 15.16 | 6.78 | 2.90 | 2.02 | 0.45 | 200 / 33 |
| 86 | 3.a.8 | ticking | 19.54 | 12.86 | 6.37 | 1.05 | 1.96 | 0.14 | 235 / 0 |
| 86 | 3.a.8 | play into it (85) | 23.31 | 16.09 | 7.09 | 3.27 | 2.06 | 0.46 | 199 / 36 |
| 98 | 3.a.10 | ticking | 19.18 | 12.35 | 4.39 | 0.86 | 1.97 | 0.15 | 212 / 0 |
| 98 | 3.a.10 | play into it (97) | 18.48 | 13.97 | 4.95 | 2.08 | 1.97 | 0.32 | 190 / 22 |
| 109 | 3.a.12 | ticking | 19.13 | 13.04 | 6.89 | 1.17 | 2.06 | 0.16 | 239 / 6 |
| 109 | 3.a.12 | play into it (108) | 24.59 | 15.19 | 7.23 | 3.08 | 2.14 | 0.46 | 212 / 33 |
| 115 | 3.b.1 | ticking | 18.74 | 13.11 | 4.72 | 1.08 | 2.07 | 0.18 | 222 / 0 |
| 115 | 3.b.1 | play into it (114) | 19.84 | 12.26 | 5.01 | 2.13 | 2.06 | 0.33 | 200 / 22 |
| 123 | 3.b | ticking | 17.80 | 12.79 | 4.97 | 1.06 | 2.21 | 0.17 | 257 / 0 |
| 123 | 3.b | play into it (122) | 40.41 | 39.51 | 12.03 | 9.77 | 4.03 | 2.39 | 202 / 55 |
| 130 | 5.a | still | 12.24 | 10.02 | 3.30 | 0.77 | 0.72 | 0.11 | 184 / 0 |
| 130 | 5.a | play into it (129) | 31.07 | 29.03 | 8.96 | 7.64 | 2.24 | 1.90 | 141 / 43 |
| all | | pausepoints | 17.94 | 12.01 | 4.88 | 1.00 | 1.85 | 0.14 | |
| all | | plays | 23.44 | 15.34 | 6.99 | 3.10 | 2.05 | 0.45 | |

Read:

- **At rest the frame is what the GPU and the native driver cost.** At 8.a
  the complete frame is 36.9 → 21.5 ms: prepare 15.5 → 1.9, encode 4.5 →
  0.3; what is left is the native driver's command encoding of 444 batches
  (`render_cpu_encode_ms` 7.3 ms either way: it does not learn the retained
  list, only the browser will, tier 2) and the full readback the browser
  never does (7.3 ms). Over every pausepoint, 19.7 → 13.3 ms (EpisodeB2) and
  15.4 → 10.9 (PriceDiscovery).
- **Ticked pausepoints** keep every leaf whose updater changes no byte: 8.a
  with its updaters ticking 49.9 → 24.3 ms complete, prepare 26.0 → 3.9, 415
  leaves compared and kept a tick.
- **Plays** cost what their movers cost. Where some of the scene holds
  still the frame gains (0.a's play 42.1 → 33.0, 3.i's 25.6 → 17.0,
  EpisodeB2's plays 37.5 → 28.4 and PriceDiscovery's 23.4 → 15.3 over all);
  at 8.a, where 365 of 531 leaves move, it is neutral (108.9 → 108.4,
  prepare 77.5 → 79.6). **Where every leaf moves it costs more**: 5.a's play
  prepares all 461 leaves every frame and runs 138.1 → 147.4 ms complete,
  prepare 44.9 → 54.3. The same play measured alone (`summary.json`
  `all_movers_play`: two scenes loaded alike, serialize_scene only, 45
  frames, messages equal) is 54.6 → 63.5 ms, +16%, and B4.4's commit showed
  the same (62.5 → 72.7): tier 1's bookkeeping on a leaf it prepares (its
  entry and cache records, its uniform set's text, the comparison that finds
  it moved, the run memos and the descriptors around encode_draw), ~19 µs a
  leaf, which nothing kept pays back (`split_ms_per_frame_flag_on`). The
  flip takes this cost as measured, an open item (docs/phase_b4_plan.md,
  "B4 tier 1: shipped"). B4.5's frozen rows remove the entry's own copy of a
  path's rows only where the border cache holds one (every filled path under
  Phase B: held rows 0.89 → 0.38 ms a frame over 8.a's play; 9 of 364
  prepared leaves under Phase A, whose glyphs are fills read from their mesh
  alone and strokes, which no cache holds whole).
- The retained variant's rows are slightly pessimistic on ticked and play
  rows: the variants share one scene, and a leaf the other variant's read
  refreshed first is prepared once (`retained_scope`).

`summary.json` also carries `serialize_gates`: serialize_scene alone, flag on
against off, from the B4.5 gate scripts (one scene per cache for still,
ticked, pan and zoom; two scenes loaded alike, navigated with the collector
held, for seeks, jumps, plays, landings and a restart), every frame's two
messages equal. They are the plan's "B4 tier 1: shipped" table.

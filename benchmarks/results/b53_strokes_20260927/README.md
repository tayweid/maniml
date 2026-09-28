# Programs for strokes on Phase A, on two course episodes (2026-09-27)

B5.3 (`docs/phase_b4_plan.md`, "B5.3: built"): `MANIML_PROGRAMS=strokes`
against `off`, Phase A (`MANIML_FILL=meshes MANIML_SURFACE=grids
MANIML_BORDER_GENERATOR=gpu`), the retained frame on, the records packed,
over every frame of seven plays of the two course episodes the plan's gates
are measured on. The directory is named for the increment's day; the runs
are of 2026-09-28, 04:16-04:21 UTC, in B5.3's fix pass.

## Runs

From `/Users/taylorjweidman/Projects/ManimLive/maniml-b4i` (branch
`b4-integration`, commit `7c5cb804`, B5.1, **plus B5.3's working tree as
committed**: `summary.json` `source_files_sha256` carries the hashes of what
was measured, identical across the eight runs and unchanged during each),
interpreter `maniml/.venv/bin/python` (Python 3.13.9, wgpu 0.32.0, numpy
2.5.2), Apple M3, Metal, macOS 26.6.2, Node for the browser replay, one run
at a time:

```bash
B2=/Users/taylorjweidman/Projects/econ-0100/Blocks/B2_Supply/03_Code.py
PD=<B5.1's scratch tree>/Blocks/B3_Equilibrium/Animate.py   # see below
python -m benchmarks.play_frames --scene $B2 EpisodeB2 --plays 1 14 15 22 279 --replays 6 --format 8 --output <dir>/b2_f8
python -m benchmarks.play_frames --scene $B2 EpisodeB2 --plays 1 14 15 22 279 --replays 6 --format 7 --output <dir>/b2_f7
python -m benchmarks.play_frames --scene $PD PriceDiscovery --plays 1 81 --replays 6 --format 8 --output <dir>/pd_f8
python -m benchmarks.play_frames --scene $PD PriceDiscovery --plays 1 81 --replays 6 --format 7 --output <dir>/pd_f7
python -m benchmarks.play_frames --scene $B2 EpisodeB2 --plays 1 14 15 22 279 --replays 4 --format 7 --render --output <dir>/b2_render
python -m benchmarks.play_frames --scene $PD PriceDiscovery --plays 1 81 --replays 4 --format 7 --render --output <dir>/pd_render
MANIML_GPU_TIMESTAMPS=1 python -m benchmarks.play_frames --scene $B2 EpisodeB2 --plays 1 279 --replays 4 --format 7 --render --output <dir>/b2_stamps
python -m benchmarks.play_frames --scene $B2 EpisodeB2 --plays 1 279 --replays 1 --format 8 --browser --rounds 5 --output <dir>/b2_browser
```

`MANIML_GPU_TIMESTAMPS` was unset for every run but `b2_stamps`, the
attribution run. PriceDiscovery's `Animate.py` is in
`B3_Equilibrium/_archive/` in the course checkout (sha256 `dfe6e831...`) and
finds its style module through `dirname(__file__)/../_Assets`, so it ran, as
in every B4 and B5 increment, from a scratch tree of symbolic links that
keeps it at its old depth. EpisodeB2's `03_Code.py` is sha256
`7e105159...`. The plays are the ones whose movers are most paths without
fill, found by the review draft's survey of every play of both episodes
(the movers and programs at each play's middle frame, which the harness now
records as `movers: programs`): only EpisodeB2's bumper (checkpoint 1, the
raster wordmark's 211 squares fading in) is mostly strokes; the axes, curve
and dashed-line plays are a quarter to a third strokes, their labels,
numbers and titles being glyphs. `report_episode_b2_f8.json` is the
EpisodeB2 format 8 gate run's complete report (per-frame medians, and what
the first replay's messages carried); the other reports stay in the scratch
directory.

**The machine was not quiet.** Another application held the M3 at 37-58%
device utilization before and after every run (`ioreg -r -c IOAccelerator`,
three samples each, `summary.json` `runs.*.gpu_device_utilization_percent_*`),
one of Taylor's scene processes was running (~43% of a core), and the load
averages were 2.8-4.2. Nothing was stopped. `serialize_scene` does not use
the GPU, and the modes alternate replay by replay under the same load, so
the gate holds; the `render_ms`, `complete_ms` and `gpu_` figures should be
read against each other only, never against another archive's.

## Results

Pixels (`b2_render`, `pd_render`): each mode's first replay drawn natively,
frame by frame, strokes against off: largest channel difference 0 and no
pixel over 24 on every frame of all seven plays (99 frames). The bumper's
squares are the background's colour until the flicker fills them, so its
frames prove nothing; the other six plays' do.

The gate, `serialize_ms`: each frame's median over six replays per mode,
then the median over the play's frames after the entry (minimum over every
sample in brackets):

| Play (checkpoint, line; movers: programs) | format 8, ms | format 7, ms | wire, format 8 |
| --- | ---: | ---: | ---: |
| EpisodeB2 1, 35, the bumper (211: 211) | 9.57 (9.04) → 7.42 (6.80), -22% | 9.65 (9.10) → 6.10 (5.54), -37% | 172.7 → 6.1 KB |
| EpisodeB2 14, 78, the recap's axes and curve (16: 3) | 2.86 → 2.80 | 2.84 → 2.77 | 122.0 → 120.6 KB |
| EpisodeB2 15, 80, the recap's dashed price and drop (136: 48) | 11.89 → 11.45 | 11.91 → 11.15 | 230.8 → 221.8 KB |
| EpisodeB2 22, 120, the axes with their labels (77: 18) | 12.92 → 12.74 | 13.15 → 12.74 | 556.8 → 552.8 KB |
| EpisodeB2 279, 806, three small axes and two supply lines (148: 38) | 24.99 → 24.47 | 25.01 → 24.21 | 1168.5 → 1159.1 KB |
| PriceDiscovery 1, 202, the plaza's rim and dashed hub, camera moving (36: 13) | 5.63 → 5.52 | 5.60 → 5.40 | 331.9 → 289.4 KB |
| PriceDiscovery 81, 1179, rays and marks fading out (42: 10) | 2.20 → 2.00 | 2.16 → 1.92 | 112.5 → 110.4 KB |

The scene's own Python between two frames (`scene_ms`, the interpolation
and the updaters) on the bumper: 1.25 → 1.03 ms (format 8), 1.27 → 0.97
(format 7); elsewhere within 0.04 ms.

The negatives:

- The play's entry (its first frame, which packs, hashes and summarizes
  every program's sources): the bumper 10.53 → 23.31 ms (format 8); the
  other EpisodeB2 plays +0.2 to +2.4 ms; PriceDiscovery -0.2 and +0.5.
- Format 7 frames grow where strokes are a minority, a program being a
  batch of its own: EpisodeB2 15 237.0 → 255.4 KB, 279 1169.0 → 1181.0,
  PriceDiscovery 81 155.5 → 159.0.
- The native render through its readback and the complete native frame
  (`render_ms`, `complete_ms`, flag off, four replays each; medians, the
  render's minimum in brackets):

  | Play | render, ms | complete, ms |
  | --- | ---: | ---: |
  | EpisodeB2 1 | 6.06 (5.34) → 40.35 (35.22) | 15.89 → 47.17 |
  | EpisodeB2 14 | 9.61 → 11.03 | 12.92 → 14.23 |
  | EpisodeB2 15 | 17.01 → 23.25 | 29.61 → 34.64 |
  | EpisodeB2 22 | 22.57 → 26.51 | 36.45 → 39.82 |
  | EpisodeB2 279 | 37.26 (9.88) → 43.00 (16.35) | 63.11 → 68.71 |
  | PriceDiscovery 1 | 11.98 → 14.90 | 17.99 → 20.64 |
  | PriceDiscovery 81 | 10.64 → 12.40 | 13.09 → 14.75 |

  Strokes makes the complete native frame dearer on every play measured:
  each program is a compute pass of its own with two dispatches.
- The GPU (`b2_stamps`): the bumper's `gpu_total_ms` 3.09 → 15.70, of which
  the 211 `programs` passes are 12.66 exclusive; EpisodeB2 279 10.73 →
  13.66, the 38 `programs` passes 1.99 (the borders 7.87 → 8.72).
- The browser's JavaScript (`b2_browser`, the fake device, Node's own realm,
  five rounds; `page_ms` medians after the entry): the bumper 0.13 → 0.93
  ms under format 7 and 0.12 → 0.50 under format 8, with 211 compute passes
  and 422 dispatches a frame where there were none and 172 KB uploaded → 3
  KB; its entry 0.76 → 6.91 (format 7) and 0.82 → 8.48 (format 8).
  EpisodeB2 279: 2.65 → 2.80 (format 7), 2.70 → 2.68 (format 8). Every tab
  pays the format 7 figure while any client of the viewer has not
  negotiated format 8. The browser's GPU was not measured.

Against the review draft's scratch measurements (the same plays and
alternation, taken before the fix pass): the bumper's format 8 serialize
9.81 → 7.39 there, 9.57 → 7.42 here; every play's programs are the same
count (the fix pass's revision rule, which keeps a program off a member
another writer changed, costs these plays none).

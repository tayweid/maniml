# The flips, gated (2026-09-27/28)

B5.4 (`docs/phase_b4_plan.md`, "The flips"): each default flip of Phase B
measured on its gate, in the plan's order: B2 surfaces as nets
(`MANIML_SURFACE`), B1 fills as patches (`MANIML_FILL`), then B3 programs
(`MANIML_PROGRAMS`; `gpu` needs the patch fill, so with patches not flipped
B5.3's `strokes` was evaluated in its place). **No default flipped.** The
directory is named for the increment's day; the runs are of 2026-09-28: the
first pass 02:28-06:07 local time, and the increment's fix pass 07:29-07:39
(the flag-off frames runs and the complete reductions) and 14:30-16:35
(every program run).

## Runs

From `/Users/taylorjweidman/Projects/ManimLive/maniml-b4i` (branch
`b4-integration`, commit `a5cbf4da`, B5.3, **plus B5.4's working tree as
committed**: `summary.json` `source_files_sha256` carries the hashes of
what the runs measured, one per file where every run agrees, and
`source_files_differing_between_runs` the files the fix pass changed, with
the runs on each side; see "Source files" below), interpreter
`maniml/.venv/bin/python` (Python 3.13.9, wgpu 0.32.0, numpy 2.5.2), Node 22.16.0 for the browser replay,
Apple M3, Metal, macOS 26.6.2, one run at a time. The scenes: EpisodeB2
(`Blocks/B2_Supply/03_Code.py`, sha256 `7e105159...`), PriceDiscovery
(`B3_Equilibrium/_archive/Animate.py`, `dfe6e831...`, run as in every B4
and B5 increment from a scratch tree of symbolic links that keeps it at its
old depth, its `../_Assets` imports resolving), and for the nets the scenes
that draw a Surface: EpisodeB3 (`B3_Equilibrium/B3_Animation.py`,
`743e48b6...`, 204 of its 224 pausepoints draw one), B4
(`B4_Efficiency/B4_Animation.py`, `4ea4aa36...`, up to 479 spheres a frame)
and `dogfood/orbit_demo.py` (`7f3d5708...`, a torus and a cube). Per scene
and flip (`benchmarks/README.md`, "Flip gates";
`F=(--tick-updaters --play-frames --camera-moves)`):

```bash
python -m benchmarks.episode_frames --scene $S --variants <nets|patch_fill> gpu_border $F --output <d>/frames
python -m benchmarks.episode_frames --scene $S --variants <nets|patch_fill> gpu_border $F --gpu-timestamps --output <d>/gpu1
python -m benchmarks.browser_frames --scene $S --variants phase_a <phase_a_nets|phase_a_patches> $F --deltas --realm main --rounds 5 --output <d>/browser
python -m benchmarks.flip_gates serialize --flip <nets|patches> --scene $S $F --output <d>/serialize
python -m benchmarks.episode_frames --scene $S --variants <nets|patch_fill> gpu_border $F --gpu-timestamps --output <d>/gpu2
python -m benchmarks.flip_gates complete --flip <nets|patches> --serialize <d>/serialize --browser <d>/browser \
    --gpu <d>/gpu1 <d>/gpu2 --pixels <d>/frames --limit <1.05|1.0> --output <d>/complete
python -m benchmarks.flip_gates fixtures --output <d>/fixtures
```

and for the programs, per episode:

```bash
python -m benchmarks.play_frames --scene $S --every-play --modes off strokes --replays 4 --format 8 --output <d>/f8
python -m benchmarks.play_frames --scene $S --every-play --modes off strokes --replays 2 --format 7 --output <d>/f7
python -m benchmarks.play_frames --scene $S --every-play --modes off strokes --replays 1 --format 7 --render --output <d>/render
python -m benchmarks.flip_gates programs --plays <b2 f8> <b2 f7> <pd f8> <pd f7> --render <b2 render> <pd render> --output <d>/programs
MANIML_TEST_GPU=1 python -m unittest tests.test_program_library.LibraryPixels tests.test_program_blend.ProgramPixels
```

`MANIML_GPU_TIMESTAMPS` was unset for every run but the `gpu1`/`gpu2`
attribution runs. Format 7's program runs take two replays a mode and
format 8's four; each total is over every frame of every play (2,598 and
1,406), so the fewer replays cost little.

**What the fix pass took again, and why.** The increment's review found
three faults in the instrument, and the fix pass corrected them and took
again every run they touched (`summary.json` `runs`, `pass`):

- *A play's pixels were its landing.* `episode_frames` compared a play's
  last sampled frame, and a play of 15 frames or fewer is sampled to its
  end, which is the pausepoint's own picture: 47 of the 50 plays compared
  had been compared there. A play's pair is now the worst over every frame
  of its sampled window strictly inside it (`pixel_frames`, alpha below 1,
  the warmups included), and `complete` counts each frame once. The five
  flag-off `frames` runs and the `complete` reductions were taken again;
  the serialize, browser and attribution runs, which the change does not
  touch, are the first pass's.
- *The programs verdict leaned on the turn order.* `play_frames` opened
  every play with programs off, and the first replay of a play is the first
  to run it after the play before. Run the other way round (the review's
  reruns, format 7) the order effect was about half a percent on EpisodeB2
  and of the opposite sign on PriceDiscovery. The mode that opens a play
  now alternates play by play (`opened_by`), and `flip_gates programs`
  reads the order-balanced ratio (the geometric mean of the ratio over the
  plays each mode opened, with a 95% interval from resampling them,
  seeded). Every program run was taken again. A first attempt at them,
  started 07:39 and again 08:52, ran under contention (EpisodeB2's format 8
  run 16-17% slower in each mode than the first pass's, one of Taylor's
  scene processes at ~40% CPU and the GPU at ~40%) and was cut off after
  221 of its 223 plays; it is kept in the scratch directory, not used.
- *The stamps overstate a stack of more passes.* The complete frame takes
  its GPU from the attribution runs, as Taylor's gate says, while the
  measuring contract takes gate numbers from runs without the flag (each
  stamped pass costs ~30 µs). `complete` now reports beside the verdict the
  same frames with the GPU part the flag-off runs' wall clock from the
  submit through the full readback (`flag_off_check`), which has no stamps
  but dilutes every ratio with the readback both stacks pay.

**The machine.** `summary.json` `conditions` has, per run, the GPU's device
utilization (`ioreg -r -c IOAccelerator`, three samples), the load averages
and the processes over 10% CPU at its start and end. The first pass: the
GPU at 0-12% before every run (the compositor and idle applications), the
one-minute load 1.8-3.2, Taylor's viewer and scene processes idle. The fix
pass's flag-off frames runs (07:29-07:39): the GPU at 16-23% and one of
Taylor's scene processes at 37-44% CPU throughout, load 3.1-5.3; nothing
was stopped. Their pixels do not depend on it; their flag-off wall clock,
which only the check reads, carries it in both stacks alike, the variants
rotating frame by frame. The program runs: the GPU at 0-3% at every
start, the one-minute load 2.6-4.1 (backup and system daemons), Taylor's
scene processes idle.

**Source files.** Every hash in `summary.json` matches the working tree
committed with it but two files the fix pass changed after the first
pass's runs. `benchmarks/episode_frames.py`: the first pass's serialize,
browser and attribution runs read `ff119d14...`, the fix pass's runs the
tree's `27bc7c72...`; the first is exactly the tree's file with the fix
pass's pixel edits taken back (`worst_pixel_pairs`, `measure_play`'s
`inside` and `pixel_frames`, its docstring and the pixel caveat's text),
checked by rebuilding it to that hash, so nothing those runs time differs.
`benchmarks/flip_gates.py` (`source_files_not_in_the_working_tree`): the
first pass's `serialize` and `fixtures` runs read `702fa629...`, before the
fix pass changed its reductions (`complete`'s pixels and flag-off check,
`programs`' order-balanced ratio, the docstring); that file was not kept.
Re-run with the tree's file (16:36-16:39, the GPU at 3%): the fixtures
reproduce every number of the archived run exactly, and the orbit demo's
and PriceDiscovery's serialize runs measure the same frames, classes and
sample counts, their medians within the run-to-run noise (PriceDiscovery's
plays 3.58 → 6.28 ms archived, 3.36 → 5.83 again, the ratio 1.75 and
1.73). The archived runs stand.

## Results

Every table below is generated from `summary.json`. A complete frame is,
per frame, `serialize_ms` (`flip_gates serialize`) + `page_ms`
(`browser_frames`, main realm, each frame's median over five rounds) +
`gpu_total_ms` (the median of the frame's rows over the two pooled
attribution runs, charged in format 8 only for a frame the stream sent); a
class's figure is the median over its frames (each measured play frame one
value), and the ratio is the flip's over Phase A's. The GPU minimum's ratio
is beside every ratio in `summary.json` (`ratio_gpu_min`), since the GPU
clock follows the load. The flag-off check is the same with
`submit_through_full_readback_ms` of the flag-off runs as the GPU part.

### Nets: the Surface fixtures, nets against grids (pixels)

| Fixture | px > 24/255 | largest channel | grid batches | nets |
| --- | ---: | ---: | ---: | ---: |
| port_surfaces | 0.0000% | 1 | 2 | 2 |
| sphere_1x | 0.0000% | 1 | 1 | 1 |
| sphere_4x | 0.0000% | 1 | 1 | 1 |
| sphere_16x | 0.0457% | 67 | 1 | 1 |
| sphere_64x | 0.1692% | 85 | 1 | 1 |
| ce_saddle | 0.0000% | 1 | 1 | 1 |
| textured_flat | 0.0000% | 0 | 1 | 1 |
| orbs | 0.2814% | 132 | 1 | 70 |
| orbit_demo | 0.0000% | 1 | 2 | 7 |
| cobb_douglas | 0.0482% | 167 | 1 | 1 |
| fill_by_value | 0.0000% | 0 | 1 | 1 |
| textured_zoom | 0.0000% | 1 | 1 | 1 |
| translucent | 0.0781% | 42 | 1 | 2 |

### Nets: complete frame, nets / grids (format 8; format 7; bold is over 1.05)

| Scene | pausepoint | ticked | camera | play | pixels (worst; frames: pausepoints + inside plays) |
| --- | ---: | ---: | ---: | ---: | ---: |
| Orbit demo | **1.055**; 0.989 | – | **1.311**; **1.295** | 0.676; 0.670 | 0.3071%, largest channel 50, mid-play (2 + 30) |
| EpisodeB3 | 0.989; **1.339** | 1.011; **1.059** | **1.335**; **1.334** | 1.038; 1.008 | 0.0260%, largest channel 144, pausepoint (12 + 93) |
| B4 | 1.025; **1.069** | 1.018; 0.986 | **1.245**; **1.231** | 1.038; **1.063** | 0.0231%, largest channel 152, mid-play (12 + 122) |

The same, flag-off check (the GPU part the flag-off wall clock through the
full readback):

| Scene | pausepoint | ticked | camera | play |
| --- | ---: | ---: | ---: | ---: |
| Orbit demo | **1.055**; 0.928 | – | **1.267**; **1.256** | 0.791; 0.787 |
| EpisodeB3 | 0.989; 1.027 | 1.011; 1.006 | **1.331**; **1.326** | 1.018; 0.999 |
| B4 | 1.025; 1.003 | 1.018; 0.992 | **1.132**; **1.132** | 1.043; **1.055** |

Nets, the parts in format 8, medians over each class's frames (ms): serialize + page + GPU = complete

| Scene | class | Phase A | flip |
| --- | --- | --- | --- |
| Orbit demo | pausepoint | 0.17 + 0.00 + 0.00 = 0.17 (n 2) | 0.18 + 0.00 + 0.00 = 0.18 (n 2) |
| Orbit demo | camera | 0.23 + 0.09 + 3.84 = 4.17 (n 2) | 0.26 + 0.25 + 4.96 = 5.47 (n 2) |
| Orbit demo | play | 4.50 + 0.10 + 2.96 = 7.57 (n 24) | 1.48 + 0.19 + 3.44 = 5.12 (n 24) |
| EpisodeB3 | pausepoint | 1.02 + 0.00 + 0.00 = 1.02 (n 1) | 1.01 + 0.00 + 0.00 = 1.01 (n 1) |
| EpisodeB3 | ticked | 2.02 + 0.00 + 0.00 = 2.02 (n 11) | 2.04 + 0.00 + 0.00 = 2.04 (n 11) |
| EpisodeB3 | camera | 1.51 + 0.10 + 4.30 = 5.91 (n 12) | 1.65 + 0.17 + 6.18 = 7.89 (n 12) |
| EpisodeB3 | play | 6.81 + 0.46 + 4.22 = 11.29 (n 72) | 6.84 + 0.49 + 4.41 = 11.71 (n 72) |
| B4 | pausepoint | 1.08 + 0.00 + 0.00 = 1.08 (n 1) | 1.11 + 0.00 + 0.00 = 1.11 (n 1) |
| B4 | ticked | 1.22 + 0.00 + 0.00 = 1.22 (n 11) | 1.25 + 0.00 + 0.00 = 1.25 (n 11) |
| B4 | camera | 1.95 + 0.11 + 4.64 = 7.09 (n 12) | 2.29 + 0.16 + 6.16 = 8.83 (n 12) |
| B4 | play | 22.44 + 1.34 + 6.56 = 30.05 (n 98) | 22.76 + 1.36 + 6.62 = 31.20 (n 98) |

### Patches: complete frame, patches / Phase A (format 8; format 7; bold is over 1.0)

| Scene | pausepoint | ticked | camera | play | pixels (worst; frames: pausepoints + inside plays) |
| --- | ---: | ---: | ---: | ---: | ---: |
| EpisodeB2 | **1.014**; **1.114** | **1.138**; **1.391** | **1.072**; **1.080** | **1.148**; **1.151** | 0.00004% (one pixel), largest channel 30, mid-play (12 + 139) |
| PriceDiscovery | 0.982; **1.380** | **1.104**; **1.174** | 0.964; 0.969 | **1.477**; **1.433** | 0.00004% (one pixel), largest channel 27, pausepoint (12 + 124) |

The same, flag-off check:

| Scene | pausepoint | ticked | camera | play |
| --- | ---: | ---: | ---: | ---: |
| EpisodeB2 | **1.014**; **1.071** | **1.138**; **1.282** | **1.180**; **1.163** | **1.155**; **1.157** |
| PriceDiscovery | 0.982; 0.999 | **1.104**; 0.991 | **1.056**; **1.055** | **1.301**; **1.262** |

Patches, the parts in format 8, medians over each class's frames (ms): serialize + page + GPU = complete

| Scene | class | Phase A | flip |
| --- | --- | --- | --- |
| EpisodeB2 | pausepoint | 0.70 + 0.00 + 0.00 = 0.70 (n 10) | 0.71 + 0.00 + 0.00 = 0.71 (n 10) |
| EpisodeB2 | ticked | 3.35 + 0.00 + 0.00 = 3.35 (n 2) | 3.82 + 0.00 + 0.00 = 3.82 (n 2) |
| EpisodeB2 | camera | 2.06 + 0.09 + 4.50 = 6.63 (n 12) | 1.31 + 0.11 + 5.71 = 7.11 (n 12) |
| EpisodeB2 | play | 7.61 + 0.71 + 4.15 = 12.27 (n 114) | 10.34 + 0.55 + 4.51 = 14.09 (n 114) |
| PriceDiscovery | pausepoint | 0.62 + 0.00 + 0.00 = 0.62 (n 1) | 0.61 + 0.00 + 0.00 = 0.61 (n 1) |
| PriceDiscovery | ticked | 0.92 + 0.00 + 0.00 = 0.92 (n 11) | 1.01 + 0.00 + 0.00 = 1.01 (n 11) |
| PriceDiscovery | camera | 1.56 + 0.09 + 4.02 = 5.71 (n 12) | 1.04 + 0.09 + 4.28 = 5.50 (n 12) |
| PriceDiscovery | play | 3.58 + 0.19 + 3.90 = 6.96 (n 100) | 6.28 + 0.19 + 3.02 = 10.28 (n 100) |

### Programs (strokes against off), every play

Python ms per play frame (each frame's `serialize_ms` plus the scene's own
Python since the frame before, over every frame of every play), strokes
against off. The gate reads the order-balanced ratio: the geometric mean of
the ratio over the plays off opened and over those strokes opened (each
opener's ratio is its own column), with a 95% interval from resampling the
plays of each opener (2,000 resamples, seeded).

| Episode, format | plays (recording) | frames | Python ms per play frame (plain) | order-balanced (95%) | each opener: off first; strokes first | plays recording one, balanced (95%) | the rest, balanced (95%) |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| EpisodeB2 format 8 | 223 (67) | 2598 | 15.355 → 15.350 (-0.03%) | -0.03% (-0.30% to +0.20%) | -0.39% (112); +0.34% (111) | -0.13% (-1.03% to +0.67%) | +0.04% (-0.16% to +0.23%) |
| EpisodeB2 format 7 | 223 (67) | 2598 | 15.382 → 15.388 (+0.04%) | +0.05% (-0.44% to +0.55%) | -0.60% (112); +0.70% (111) | -0.51% (-1.68% to +0.42%) | +0.21% (-0.29% to +0.74%) |
| PriceDiscovery format 8 | 106 (61) | 1406 | 9.385 → 9.416 (+0.33%) | +0.32% (+0.08% to +0.53%) | +0.23% (53); +0.41% (53) | +0.30% (+0.04% to +0.55%) | +0.38% (-0.02% to +0.72%) |
| PriceDiscovery format 7 | 106 (61) | 1406 | 9.505 → 9.518 (+0.13%) | +0.08% (-0.85% to +0.98%) | -0.27% (53); +0.44% (53) | +0.01% (-1.08% to +0.67%) | +0.13% (-1.42% to +1.49%) |

Native complete frame (`serialize_scene` + `render()`, the render runs, one
replay a mode), strokes against off, order-balanced:

| Episode | every play | plays recording one | the rest |
| --- | ---: | ---: | ---: |
| EpisodeB2 | +1.79% (+0.85% to +3.15%) | +6.35% (+3.75% to +10.07%) | +0.15% (-0.21% to +0.50%) |
| PriceDiscovery | +1.40% (+0.44% to +2.34%) | +2.41% (+0.86% to +4.03%) | +0.12% (-0.57% to +0.80%) |

Pixels, the render runs, strokes against off: 4,004 play frames, no pixel
over 24/255, largest channel difference 1. The program pixel tests
(`LibraryPixels`, `ProgramPixels`, `MANIML_TEST_GPU=1`): 5 tests, OK.

## Verdicts

- **Nets fail**, on camera moves: 1.25-1.34× grids' complete frame in format
  8, 1.23-1.33× in format 7, in all three scenes (by the flag-off check
  1.13-1.33×). A 2% zoom re-evaluates every net on screen, each in a
  compute pass of its own (EpisodeB3: GPU 7.7 against 5.0-5.4 ms a zoom,
  median; B4's 479-sphere frames: 31.3-31.6 against 8.2-8.5 ms stamped,
  which overstates it: the flag-off wall clock through the full readback is
  27.9 against 10.2 ms at checkpoint 114, 16-19 ms more on B4's heaviest
  frames); a pan costs nothing. Pixels pass everywhere (fixtures ≤ 0.28%;
  271 episode frames, 245 of them inside plays, ≤ 0.31%), and format 8
  stills, ticks and plays are within 1.05× but the orbit demo's 0.17 ms
  still (1.055×, 0.01 ms). `grids` stays the default.
- **Patches fail** on both episodes: format 8 plays 1.15× (EpisodeB2) and
  1.48× (PriceDiscovery), the serialize's (a mover's records packed every
  frame); ticked frames 1.14× and 1.10×; format 7 over in most classes; the
  flag-off check fails the same classes. Pixels are Phase A's but two
  pixels over 287 frames, 263 of them inside plays (27/255 at
  PriceDiscovery's checkpoint 130, 30/255 inside EpisodeB2's play into 8.a,
  each 0.00004% of its frame). `meshes` stays the default.
- **Programs, as strokes, are not met**: pixels pass (the 5 pixel tests, and
  4,004 play frames within 1/255), but Python ms per play frame,
  order-balanced, is lower in one run of four (EpisodeB2, format 8, by
  0.03%, its interval on both sides of zero) and higher in the other three
  (+0.05%, +0.32% and +0.08%; PriceDiscovery's format 8 measurably). The
  first pass's reading (every total lower by 0.07-0.68%) was the turn order:
  it opened every play with off, and the opener reads dearer here in all
  four runs. The review's paired rerun (format 7, strokes first, against
  the first pass's run) read -0.26% and -0.25%; this re-take +0.05% and
  +0.08%: on these episodes the programs move Python by less than half a
  percent either way. The native complete frame is 1.8% dearer over
  EpisodeB2's plays and 1.4% over PriceDiscovery's (6.4% and 2.4% on the
  plays that record a program), every interval above zero. `off` stays the
  default.

`report_patches_episode_b2_complete.json` is the complete report of the
EpisodeB2 patches gate, Taylor's gate on the 8.a episode: every frame's
serialize, page and GPU parts per class and format for both stacks. The
other reports, the recorded browser streams and the first harness runs stay
in the scratch directory.

# The nets gate, taken again after one dispatch (2026-09-28)

B5.5 (`docs/phase_b4_plan.md`, "The flips"): each driver evaluates a
frame's changed Surface nets in one dispatch and keys a net's evaluation on
its step count, then B5.4's B2 gate is taken again exactly as B5.4 ran it
(`benchmarks/README.md`, "Flip gates"; B5.4's archive is
`../phase_b_flips_20260927/`). **Every class is within 1.05 of grids in both
formats on the gate's three scenes and the pixels pass; on scenes that are
mostly surfaces the same recipe fails (below, "Where the gate's scenes
stop"), so the default surface generator stays `grids`** (`summary.json`:
`default_flipped`, `why_not_flipped`, `surface_dominated`).

## Runs

From `/Users/taylorjweidman/Projects/ManimLive/maniml-b4i` (branch
`b4-integration`, HEAD `c787d9d1` plus B5.5's working tree), interpreter
`maniml/.venv/bin/python` (Python 3.13.9, wgpu 0.32.0, numpy 2.5.2), Node 22 for the
browser replay, Apple M3, Metal, macOS 26.6.2, one run at a time,
`MANIML_GPU_TIMESTAMPS` unset but for the attribution runs. Per scene
(`F=(--tick-updaters --play-frames --camera-moves)`):

```bash
python -m benchmarks.episode_frames --scene $S --output <d>/frames --variants nets gpu_border $F
python -m benchmarks.episode_frames --scene $S --output <d>/gpu1 --variants nets gpu_border $F --gpu-timestamps
python -m benchmarks.browser_frames --scene $S --output <d>/browser --variants phase_a phase_a_nets $F --deltas --realm main --rounds 5
python -m benchmarks.flip_gates serialize --flip nets --scene $S --output <d>/serialize $F
python -m benchmarks.episode_frames --scene $S --output <d>/gpu2 --variants nets gpu_border $F --gpu-timestamps
python -m benchmarks.flip_gates complete --flip nets --serialize <d>/serialize --browser <d>/browser \
    --gpu <d>/gpu1 <d>/gpu2 --pixels <d>/frames --limit 1.05 --output <d>/complete
python -m benchmarks.flip_gates fixtures --output <d>/fixtures
```

The scenes are B5.4's: `dogfood/orbit_demo.py` OrbitDemo,
`Blocks/B3_Equilibrium/B3_Animation.py` EpisodeB3 and
`Blocks/B4_Efficiency/B4_Animation.py` B4 (econ-0100), the same twelve
frames of each (`episode_frames.select_frames`).

**Two passes.** Pass 1 (21:30-22:15 local) measured the drivers' change
alone. It passed every class but four, all of them the serializer's
Python: the orbit demo's still in format 8 (1.074, 0.18 → 0.19 ms for a
frame that sends nothing) and B4's camera moves (1.068; 1.077) and format 7
plays (1.057), where every net's reservation was taken again on each move
(`NetRecipeCache.source`: the pixels per unit through a numpy array per
net, the step rule in numpy scalars, three validations) and each kept run
of a still frame was built anew for the stream's diff. The serializer was
then made cheaper for them, byte for byte the same (the golden pin under
the default, `MANIML_VERIFY_LEDGER=1` and `MANIML_RETAINED_FRAME=0`, with
both episodes), and every run was taken again: pass 2 (22:33-23:15) is the
verdict, on the tree as committed: every source file hashes as pass 2
recorded it (a flip of `geometry.DEFAULT_SURFACE` made after pass 2 was
taken back in the fix pass, and every variant these harnesses measure
names its surface generator, so it moved none of them). `summary.json` has both passes' tables, their
commands, the run conditions and the source hashes: one per file where
both passes agree, and the four files pass 2 changed
(`source_files_differing_between_runs`: `generated_geometry.py`,
`gpu_net_geometry.py`, `retained_frame.py` and `wgpu_renderer.py`, whose
change there is the per-frame packing of a net batch's uniforms, before
the submit that every GPU column starts from).

**The machine.** Pass 1's orbit runs and EpisodeB3's first three ran while
another project's Playwright tests were running (node, a headless Chrome,
WebKit; one-minute load 2.3-4.7, the GPU at up to 32% at a run's start);
the rest of pass 1 and all of pass 2 started with the GPU at 0-7% (three
samples each; the 23-43% readings at some runs' ends are the run's own
work) and the one-minute load 2.1-3.8, nothing over 10% CPU but the window
server, the backup client and this session. Nothing was stopped.

## Results

Complete frame, nets / grids, format 8; format 7 (bold is over 1.05):

| Scene | run | pausepoint | ticked | camera | play |
| --- | --- | ---: | ---: | ---: | ---: |
| Orbit demo | B5.4 | **1.055**; 0.989 | – | **1.311**; **1.295** | 0.676; 0.670 |
| Orbit demo | pass 1 (drivers) | **1.074**; 0.973 | – | 0.979; 0.982 | 0.693; 0.679 |
| Orbit demo | pass 2 | 1.037; 0.990 | – | 0.997; 1.002 | 0.696; 0.700 |
| Orbit demo | pass 2, flag-off check | 1.037; 0.997 | – | 1.004; 1.009 | 0.766; 0.770 |
| EpisodeB3 | B5.4 | 0.989; **1.339** | 1.011; **1.059** | **1.335**; **1.334** | 1.038; 1.008 |
| EpisodeB3 | pass 1 (drivers) | 0.985; 0.998 | 1.010; 1.012 | 1.026; 1.027 | 1.000; 1.001 |
| EpisodeB3 | pass 2 | 1.010; 0.999 | 1.016; 1.013 | 1.020; 1.021 | 1.017; 1.008 |
| EpisodeB3 | pass 2, flag-off check | 1.010; 1.005 | 1.016; 1.002 | 1.006; 1.006 | 1.008; 1.001 |
| B4 | B5.4 | 1.025; **1.069** | 1.018; 0.986 | **1.245**; **1.231** | 1.038; **1.063** |
| B4 | pass 1 (drivers) | 0.987; 1.004 | 1.034; 1.006 | **1.068**; **1.077** | 1.031; **1.057** |
| B4 | pass 2 | 0.988; 1.004 | 0.999; 0.999 | 1.037; 1.046 | 1.014; 1.022 |
| B4 | pass 2, flag-off check | 0.988; 1.002 | 0.999; 1.000 | 1.018; 1.026 | 0.997; 1.004 |

The parts in format 8, pass 2, medians over each class's frames (ms):
serialize + page + GPU = complete

| Scene | class | grids | nets |
| --- | --- | --- | --- |
| Orbit demo | pausepoint | 0.17 + 0.00 + 0.00 = 0.17 | 0.18 + 0.00 + 0.00 = 0.18 |
| Orbit demo | camera | 0.23 + 0.09 + 3.87 = 4.18 | 0.24 + 0.12 + 3.81 = 4.17 |
| Orbit demo | play | 4.51 + 0.09 + 3.84 = 8.44 | 1.42 + 0.17 + 4.29 = 5.87 |
| EpisodeB3 | pausepoint | 0.90 + 0.00 + 0.00 = 0.90 | 0.91 + 0.00 + 0.00 = 0.91 |
| EpisodeB3 | ticked | 1.91 + 0.00 + 0.00 = 1.91 | 1.94 + 0.00 + 0.00 = 1.94 |
| EpisodeB3 | camera | 1.49 + 0.10 + 6.88 = 8.49 | 1.52 + 0.11 + 6.98 = 8.65 |
| EpisodeB3 | play | 6.65 + 0.46 + 5.60 = 13.27 | 6.69 + 0.48 + 5.66 = 13.49 |
| B4 | pausepoint | 0.97 + 0.00 + 0.00 = 0.97 | 0.96 + 0.00 + 0.00 = 0.96 |
| B4 | ticked | 1.18 + 0.00 + 0.00 = 1.18 | 1.18 + 0.00 + 0.00 = 1.18 |
| B4 | camera | 1.84 + 0.11 + 7.61 = 9.91 | 1.98 + 0.15 + 7.81 = 10.28 |
| B4 | play | 21.10 + 1.31 + 9.16 = 31.37 | 21.61 + 1.35 + 9.06 = 31.80 |

B5.4's camera rows, for comparison (format 8): the orbit demo 0.23 + 0.09 +
3.84 against 0.26 + 0.25 + 4.96, EpisodeB3 1.51 + 0.10 + 4.30 against 1.65
+ 0.17 + 6.18, B4 1.95 + 0.11 + 4.64 against 2.29 + 0.16 + 6.16. The GPU
part now differs from grids' by the noise: per camera frame the two
stacks' GPU medians differ by -1.37 to +1.44 ms either way (their median
difference -0.04, +0.16 and +0.06 ms in the three scenes), and the nets
pass is nothing but on the frames where a 2% zoom moves some net's step
count (0.05-0.14 ms, a few of EpisodeB3's and B4's frames). The page's
part differs by 0.01-0.04 ms, the serialize's by 0.01-0.14 ms, the
reservation each net's leaf takes on a camera move (pass 1: 0.03-0.37).
The GPU clock follows the load: these runs' absolute GPU figures are not
B5.4's (B4's camera 7.61 against 4.64 ms for grids), and only the ratios
compare. B4's camera ratio by each frame's GPU minimum (`ratio_gpu_min` in
`summary.json`) is 1.086; 1.109, the minima of two stacks' rows differing
where their medians do not (the flag-off check reads 1.018; 1.026).

Pixels (flag-off runs, nets against grids): the orbit demo 0.3071% over
24/255 at worst (32 frames, 30 inside plays, largest channel 50), EpisodeB3
0.0260% (105 frames, 93 inside plays), B4 0.0231% (134 frames, 122 inside
plays); the thirteen Surface fixtures B5.4's exactly (worst the orbs,
0.2814%; the default sphere at 64× 0.1692%). Every figure within the 0.5%
gate.

## Where the gate's scenes stop

In the gate's three scenes surfaces are a small share of the frame
(EpisodeB3's and B4's spheres do not coalesce under grids either). A flip
of the default reaches every scene the Default, `--render`, checkpoint
stills and `--export` draw, so the fix pass's review took the same six
commands per scene (the "Runs" block but `fixtures`, `MANIML_*` unset) on
four more, `surface_scenes.py` here: `OrbsScene` (the 70 spheres of
`tests/surface_fixtures.orbs` as a scene, 1920×1080, the episodes'
agents), `LatticeScene` (480 small spheres), and two controls,
`CobbDouglasScene` (F1's surface over its axes) and `TranslucentScene`
(a sphere and a torus, partly transparent). The fix pass then took the two
that failed again the same way. Those runs were on the tree with
`DEFAULT_SURFACE = "nets"` (the only file whose hash differs from pass
2's), which no variant reads.

Conditions (three samples of the GPU and the one-minute load at every run's
start): the review 00:09-00:17 local, GPU 0-6% but for a first sample of
32-44% taken as the previous run ended, load 1.9-2.8; the fix pass
00:19-00:23, GPU 0-6% but for first samples of 33% and 49%, load 2.4-5.5.

Complete frame, nets / grids, format 8; format 7 (bold is over 1.05):

| Scene | run | pausepoint | camera | play | pixels over 24/255 |
| --- | --- | ---: | ---: | ---: | ---: |
| Orbs, 70 spheres | review | **1.281**; **1.163** | **1.194**; **1.211** | 0.873; 0.878 | 0.356% |
| Orbs | fix pass | **1.305**; **1.162** | **1.196**; **1.215** | 0.851; 0.858 | 0.356% |
| Lattice, 480 spheres | review | **1.505**; **1.373** | **1.438**; **1.524** | 0.784; 0.781 | **0.979%** |
| Lattice | fix pass | **1.500**; **1.366** | **1.435**; **1.523** | 0.801; 0.793 | **0.979%** |
| Cobb-Douglas | review | 0.998; 1.004 | 1.005; 0.996 | 1.018; 1.018 | 0.061% |
| Translucent | review | 1.039; 0.972 | 0.978; 0.978 | 0.490; 0.491 | 0.094% |

The flag-off check reads the same way (camera: the orbs 1.29-1.31, the
lattice 1.31-1.38). The orbs' format 8 still is the serializer's
(a frame that sends nothing, 0.18 → 0.23 ms: seventy nets are seventy runs
where grids coalesce into one); every other failing class is the redraw. A
net draws the index pattern of its capacity, not of its steps
(`net_indices(patches, capacity)`; `netIndices` in `webgpu.js`,
`wgpu_renderer._net_index_buffer`), and the reservation is twice the
steps, so at the orbs' steps (4 and 3 on capacities 8 and 6) three
quarters of a net's triangles have zero area: 290,560 triangles in 70
draws against grids' 19,840 in one coalesced draw. Natively the render
pass is +0.57 ms a frame for the orbs and +1.62 ms for the lattice, the
CPU encode 1.6-1.7 against 0.2 ms and 9.4 against 0.2 ms; in Chrome 154 a
pan of the lattice takes 5.3-5.5 ms from render to `onSubmittedWorkDone`
with nets against 1.4-2.1 with grids (the review's figures). The lattice's
differing pixels are silhouettes where the net is the rounder of the two;
B5.4's driver draws them pixel for pixel the same, so they predate B5.5.

Before the nets gate is taken again: a scene that is mostly surfaces in
its timed set; each net drawn with the index pattern of its current steps
over the `(capacity + 1)²` vertex layout (`patches × 6 × steps²` indices);
and net batches that share a pipeline and uniforms coalesced into one
draw, as grids are.

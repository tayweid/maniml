# Nets drawn as grids are, and the nets gate over its timed set (2026-09-29)

B5.7 (`docs/phase_b4_plan.md`, "The flips"): each driver draws a net with
the index pattern of the steps it evaluates it at, consecutive nets that
can share a draw are one batch drawn in one draw, and the nets gate is
judged over a timed set that holds two scenes that are mostly surfaces
(`flip_gates.TIMED_SCENES`, `flip_gates gate`). **The three scenes the gate
was set on pass every class; the orbs and the lattice fail their still and
camera frames and the lattice its pixels, so the default surface generator
stays `grids`** (`summary.json`: `passes`, `default_flipped`,
`why_not_flipped`). B5.5's archive is `../b55_nets_one_dispatch_20260928/`.

## Runs

From `/Users/taylorjweidman/Projects/ManimLive/maniml-b5` (branch
`b5-loose-ends`, `main` efcb262c plus B5.7's working tree), interpreter
`maniml/.venv/bin/python` (Python 3.13.9, wgpu 0.32.0, numpy 2.5.2), Node 22
for the browser replay, Apple M3, Metal, macOS 26.6.2, one run at a time,
`MANIML_GPU_TIMESTAMPS` unset but for the attribution runs. Per scene of the
timed set (`F=(--tick-updaters --play-frames --camera-moves)`), B5.5's six
commands, then the fixtures and the verdict:

```bash
python -m benchmarks.episode_frames --scene $S --output <d>/frames --variants nets gpu_border $F
python -m benchmarks.episode_frames --scene $S --output <d>/gpu1 --variants nets gpu_border $F --gpu-timestamps
python -m benchmarks.browser_frames --scene $S --output <d>/browser --variants phase_a phase_a_nets $F --deltas --realm main --rounds 5
python -m benchmarks.flip_gates serialize --flip nets --scene $S --output <d>/serialize $F
python -m benchmarks.episode_frames --scene $S --output <d>/gpu2 --variants nets gpu_border $F --gpu-timestamps
python -m benchmarks.flip_gates complete --flip nets --serialize <d>/serialize --browser <d>/browser \
    --gpu <d>/gpu1 <d>/gpu2 --pixels <d>/frames --limit 1.05 --output <d>/complete
python -m benchmarks.flip_gates fixtures --output <d>/fixtures
python -m benchmarks.flip_gates gate --flip nets --complete <d>/{orbit,b3,b4,orbs,lattice}/complete \
    --fixtures <d>/fixtures --output <d>/gate
```

The scenes: the workspace's `dogfood/orbit_demo.py` OrbitDemo, econ-0100's
`Blocks/B3_Equilibrium/B3_Animation.py` EpisodeB3 and
`Blocks/B4_Efficiency/B4_Animation.py` B4 (the same twelve frames of each
as B5.4 and B5.5), and `benchmarks/surface_scenes.py`'s `OrbsScene` (70
spheres) and `LatticeScene` (480), B5.5's review scenes, now in the tree.

**Three passes.** Pass 1 (09:15-09:59 local) measured the tree before one
fix: `coalesce_draws` asked each net's output size twice a frame, each
through the capacity's validation (0.2 ms of the lattice's still frame);
it is memoized on the draw since (`triangle_scene.net_output_bytes`), a
change to the serializer alone. Pass 2 (10:07-10:51) ran on the committed
tree under another's load: B4's first attribution run started with the
GPU 31-46% busy, the load reached 6.3 and a browser opened mid-scene, and
B4 failed by its GPU part alone (format 7 still 1.196, camera 1.072 and
1.070). Pass 3 (11:55-12:42), on the same tree, is the verdict: every run
waited for three samples of the GPU at or below 10% before it started
(all 32 started at 0-7%, load 2.0-4.1). A first attempt at pass 3 was
stopped at EpisodeB3's second attribution run, which another
application's video had started with the GPU at 79-82%; it is not used.
Between pass 2 and pass 3 only a comment in `tests/test_retained_frame.py`
changed (`source_files_differing_pass_2_to_pass_3`); every source file of
the tree as committed hashes as pass 3 recorded it but
`benchmarks/flip_gates.py`, whose `complete` and `gate` commands the
review of B5.7 made stricter after it (not `serialize`, the part that
measures), and two test modules no run reads (`tests/test_export.py`,
`tests/test_flip_gates.py`). `summary.json` holds each pass's tables,
verdict, commands, conditions and source hashes.

**The gate, as reviewed.** The first `gate` passed a run judged at a
looser `--limit`, or one without its camera or play classes. It now judges
every run at the flip's limit (`GATE_LIMITS`, 1.05 for nets) and fails a
run reduced with another, requires every class the scene's serialize run
measured (`complete` records it: `measured`) in both formats, the camera
and play classes always, from a serialize run with all three switches, and
fails runs of more than one commit or with a source file hashed two ways
(`complete` records the inputs' hashes). Every pass's `complete` and `gate`
were run again with it from the same reports: every earlier field of every
complete run reads as it did, every run measured with the three switches
and every class the gate requires, all of one commit and one tree, and each
pass's failures are exactly what they were.

## Results

Complete frame, nets / grids, format 8; format 7 (bold is over 1.05):

| Scene | run | pausepoint | ticked | camera | play | pixels over 24/255 |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| Orbit demo | B5.5 | 1.037; 0.990 | – | 0.997; 1.002 | 0.696; 0.700 | 0.3071% |
| Orbit demo | pass 1 | 1.047; 0.988 | – | 1.000; 0.998 | 0.679; 0.688 | 0.3071% |
| Orbit demo | pass 3 | 1.036; 0.989 | – | 1.000; 0.997 | 0.695; 0.697 | 0.3071% |
| EpisodeB3 | B5.5 | 1.010; 0.999 | 1.016; 1.013 | 1.020; 1.021 | 1.017; 1.008 | 0.0260% |
| EpisodeB3 | pass 1 | 0.987; 0.997 | 1.005; 1.003 | 1.016; 1.017 | 1.006; 1.013 | 0.0260% |
| EpisodeB3 | pass 3 | 0.996; 1.001 | 1.025; 1.009 | 0.963; 0.964 | 0.986; 1.002 | 0.0260% |
| B4 | B5.5 | 0.988; 1.004 | 0.999; 0.999 | 1.037; 1.046 | 1.014; 1.022 | 0.0231% |
| B4 | pass 1 | 1.009; 0.997 | 0.993; 1.002 | 1.031; 1.031 | 1.013; 1.027 | 0.0231% |
| B4 | pass 2 (under load) | 1.002; **1.196** | 0.999; 1.002 | **1.070**; **1.072** | 1.007; 1.025 | 0.0231% |
| B4 | pass 3 | 0.992; 0.998 | 1.007; 1.005 | 1.018; 1.020 | 1.001; 1.011 | 0.0231% |
| Orbs | B5.5 (fix pass) | **1.305**; **1.162** | – | **1.196**; **1.215** | 0.851; 0.858 | 0.3560% |
| Orbs | pass 1 | **1.315**; **1.070** | – | **1.106**; **1.106** | 0.724; 0.725 | 0.3560% |
| Orbs | pass 3 | **1.151**; **1.063** | – | **1.096**; **1.098** | 0.729; 0.733 | 0.3560% |
| Lattice | B5.5 (fix pass) | **1.500**; **1.366** | – | **1.435**; **1.523** | 0.801; 0.793 | **0.9789%** |
| Lattice | pass 1 | **1.525**; **1.143** | – | **1.204**; **1.224** | 0.597; 0.597 | **0.9789%** |
| Lattice | pass 3 | **1.243**; **1.106** | – | **1.177**; **1.193** | 0.610; 0.610 | **0.9789%** |

Pass 2's other scenes pass and fail where pass 3's do, but for two
classes its GPU part moved under the limit: the orbs' format 7 still
(1.015) and the lattice's format 8 camera (1.027; `summary.json`). The flag-off check (pass 3) reads the orbs' still
1.151; 1.280 and camera 1.019; 1.020, the lattice's still 1.243; 1.140 and
camera 1.072; 1.084. The Surface fixtures are B5.4's and B5.5's exactly
(worst the orbs, 0.2814%).

Pass 3's parts, format 8, serialize + page + GPU (ms), grids against nets:
the orbs' still 0.19 against 0.22 (Python alone), camera 0.20 + 0.02 +
3.69 against 0.27 + 0.10 + 3.94; the lattice's still 0.70 against 0.87,
camera 0.73 + 0.03 + 4.72 against 1.15 + 0.18 + 5.12. The GPU part is the
triangles a net draws to be round; the page's its walk of a run's members
every frame; the serializer's the net cache's per-leaf `keep` and, on a
camera move, each net leaf's reservation taken again.

## Pixels

Drawing each net's steps in runs moves no pixel. Natively, this tree
against `main`'s (an archive of efcb262c on `PYTHONPATH`): every Surface
fixture under the nets stack and under the forced Phase B, zoom walks over
the default sphere and the orbs (one driver kept and each frame fresh), a
pan, an orbit, and a play of the orbs where every third member moves: 90
images, 0 pixels differ; every checkpoint of `OrbsScene` and `LatticeScene`
and frames inside their plays: 38 images, 0 differ. PriceDiscovery under
the forced Phase B with `MANIML_NET_RUNS=1` and `0` (the pin's pausepoints
and gate play, 27 run batches): 22 frames, 0 differ.

**The lattice's silhouettes** (`silhouettes` in `summary.json`, the crop
`lattice_silhouette_crop.png`). At `LatticeScene`'s checkpoint 1
(1920×1080), the reference stands for the true sphere: each of the 480
spheres replaced by one of the same centre, radius and colour with eight
times the patches in each direction, drawn as Phase A's grids, whose facets
are then a fraction of a pixel. Over 24/255 from the reference: grids
1.596% of the frame (33,101 pixels), nets 0.858% (17,786); mean channel
difference 1.007 against 0.471. Nets against grids: 0.979% (20,299 pixels);
there nets are the nearer to the reference at 19,792 pixels and grids at
507, and grids are off by 68.1 on average against nets' 22.3. The crop is
the 96 × 54 window with the most differing pixels, enlarged 8×: the top
row the reference, grids and nets, the bottom row each stack's difference
from the reference, four times brighter. The gate measures nets against
grids and was not changed; the verdict stands on it.

## The redraw, natively

`redraw_native` in `summary.json` (40 small pans at checkpoint 1, one
driver, `render()` by wall clock flag off, and a run of its own with
`MANIML_GPU_TIMESTAMPS=1`; `head` is `main`'s driver, `new` this tree
before the memo, which changes the serializer only; single runs, and the
GPU clock varies between them). The orbs draw one net batch where they drew
70, and 72,640 triangles where they drew 290,560 (grids 19,840); the
lattice one where it drew 480, and 207,360 triangles where it drew 829,440
(grids 92,160). The lattice's `render()` median is 9.3 ms where `main`'s
driver took 19.4 (grids 9.2-9.3): the CPU encode of 480 draws is gone.

`still_serialize_ab`: a still frame's serialize (20 interleaved rounds of
50 frames, median), the lattice 1.049 ms before the memo and 0.858 after
(grids 0.684), the orbs 0.234 and 0.205 (grids 0.177).

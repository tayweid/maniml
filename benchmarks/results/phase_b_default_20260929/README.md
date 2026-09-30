# Phase B as the default, measured on the device (2026-09-30)

B5.10 (`docs/phase_b4_plan.md`, "Phase B as the default"). Taylor, on
2026-09-29 (DECISIONS.md): "i want to try it first before it becomes the
only option ... so long as it's not dramatically slower in any situation
and is faster or much faster in most, then i want it to be the default for
testing." The gate as stated to him: the browser-side complete frame
(Python serialize + page JavaScript + GPU) of the candidate default, the
whole Phase B stack (patches, nets, GPU programs, rows as the patch
source), against Phase A forced, with the page and the GPU measured on a
real browser device (Chrome's Dawn), not the native driver; five classes
(pausepoint, ticked, camera, play, navigation) on five scenes (EpisodeB2,
PriceDiscovery, EpisodeB3, OrbsScene, LatticeScene). PASS iff no (scene,
class) cell is above 1.25× Phase A and more than half of all cells are at
or below 1.0×, and the pixels are within 0.5% over 24/255 of Phase A but
the surfaces' silhouettes, which B5.9's accuracy rule governs.

**Verdict: the gate fails, so nothing flipped.** `geometry.DEFAULT_FILL`
stays `meshes` and `programs.DEFAULT_MODE` `off`; the Default is Phase A's
meshes and programs off with surfaces as nets (B5.9), and Phase B stays a
selection. In format 8, the stream every shipped page negotiates, five
cells are above 1.25× (the surface scenes' camera moves and navigations,
and EpisodeB3's ticked frames) and 9 of the 23 cells are at or below 1.0×
(`gate/summary.md`):

| Scene | pausepoint | ticked | camera | play | navigation |
| --- | ---: | ---: | ---: | ---: | ---: |
| EpisodeB2 | 1.007 (1.147) | 1.087 (1.215) | 1.053 (1.266) | 0.644 (0.752) | 0.990 (1.174) |
| PriceDiscovery | 0.959 (1.266) | 1.037 (0.857) | 0.974 (0.872) | 1.066 (0.924) | 0.920 (0.908) |
| EpisodeB3 | 1.105 (1.158) | **1.380** (1.111) | 1.087 (0.873) | 0.655 (0.749) | 0.989 (1.013) |
| OrbsScene | 1.117 (1.992) | – | **2.741** (2.913) | 0.645 (0.604) | **1.744** (1.486) |
| LatticeScene | 1.198 (1.432) | – | **1.631** (1.572) | 0.524 (0.467) | **1.546** (1.539) |

Phase B / Phase A, complete frame, format 8 (format 7 in brackets, quoted,
not judged). The two episodes the plan's gates were set on pass every
cell (EpisodeB2's worst 1.087, PriceDiscovery's 1.066), and every play
is 0.52-0.66× but PriceDiscovery's (1.066). What fails is:

- **The surfaces' camera moves and navigations** (OrbsScene 2.741 and
  1.744, LatticeScene 1.631 and 1.546). They are mostly the nets'
  cost on the device, which the Default has paid since B5.9: in the
  diagnostic runs (`diagnostics/`, six serializers, Phase A with nets
  beside the two, format 8), Phase A with nets over Phase A reads 1.581
  and 1.564 on the lattice's camera moves and navigations, and Phase B
  over Phase A with nets 1.066 and 1.019; on the orbs 1.442 and 1.541,
  and 1.681 and 1.054. The orbs' camera excess over Phase A with nets is
  not isolated: the two stacks' camera messages carry the same net
  descriptors (70 members in one run, capacity 8, density 0.0735) and
  make the same calls in Node (2 draws, no dispatch, 0.03-0.07 ms), yet
  read 2.74 and 1.52 ms of GPU and 0.21 and 0.03 ms of page on the
  device. B5.7 measured the nets' still and camera frames at 1.06-1.24×
  grids with the native GPU, the figure the B5.9 decision accepted; on the
  device the camera moves are 1.44-1.58× by the same comparison, and the
  navigations (a class B5.7 did not measure) 1.54-1.56×.
- **EpisodeB3's ticked frames** (1.380, serialize alone: a format 8 tick
  there sends nothing). Its ticks bump 60 leaves, and 40 of them, the
  dashes of a `DashedVMobject`, are prepared again every tick in both
  stacks though their bytes are the same: an updater leaves them with the
  joint-angle flag set and their subpath ends cached, a state
  `retained_frame.compare_rows` refuses without the ends of a refresh's
  own output (`entry.ends`), which `_entry` records only when both flags
  were set and the ends uncached. The runs that hold them are made and
  encoded again every tick, 10 under Phase A and 73 under Phase B, whose
  leaves are also read as rows again: 12.4 against 8.2 ms a tick under
  the profiler at checkpoint 996 (`tick_profile.py`, `tick_leaves.py`). The
  revision counter's over-signalling (TODO item 5), which Phase B pays
  more for.
- **The majority**: 9 of 23 cells at or below 1.0× (EpisodeB2 2,
  PriceDiscovery 3, EpisodeB3 2, the orbs and the lattice 1 each: their
  plays). The episodes' still frames and EpisodeB2's and
  PriceDiscovery's ticks sit within 0.96-1.11× of Phase A's, their
  serialize alone (EpisodeB2's still frames 0.44 against 0.44 ms).

**Pixels pass.** Phase B against Phase A with nets (`phase_b_vs_nets`,
the pixels the patches and the programs change), worst frame over each
scene's measured pausepoints and the frames strictly inside the plays into
them (`episode_frames`, flag off): EpisodeB2 0.0000% over 24/255 (151
frames, largest channel 30), PriceDiscovery 0.0000% (136, 27), EpisodeB3
0.0002% (105, 28), the orbs and the lattice 0.0000% (48 each, 0). Phase B
against Phase A (reported): 0.0000%, 0.0412%, 0.0260%, 0.356% and 0.979%,
the surfaces' silhouettes, where B5.9 measured nets nearer the true
surface than grids on every scene (its accuracy gate).

## What changed in this increment

- **The instrument** (`benchmarks/device_frames.html`,
  `benchmarks/device_frames.py`, `benchmarks/flip_gates.py`'s `phase_b`
  flip, `--navigations`, `--record`, `--diagnostics`, `complete
  --device`; `benchmarks/README.md`, "Phase B as the default: the
  device").
- **The serializer's unchanged frames** (`maniml/web/retained_frame.py`,
  both stacks, byte for byte the same wire): a frame whose draws are the
  last frame's, the same objects in the same order under the same camera,
  takes the last frame's runs without walking `coalesce_draws` (every run
  still told the border cache it was used), and once a message carried
  every run the same frame again returns that message untouched (a full
  frame's same bytes; in a stream, nothing) without encoding. Taken first
  from the exploratory runs below, where EpisodeB2's ticked frames read
  1.354× by the walk over Phase B's 274 runs against Phase A's 183 at 3.i
  and 911 against 444 at 8.a. Timed alone (`tick_profile.py`, two
  serializers alternating, 140 ticks, unprofiled medians, ms):

  | EpisodeB2 | before: Phase A / Phase B | runs reused | and the message | ratio before → after |
  | --- | ---: | ---: | ---: | ---: |
  | 3.i ticks (76) | 1.063 / 1.320 | 0.931 / 1.098 | 0.823 / 0.836 | 1.24 → 1.02 |

  At 8.a's ticks (415 leaves bumped and compared) 3.05 / 3.57 ms after
  (1.17), and a still frame (checkpoint 12) 0.514 / 0.582.

  Proof: the golden pin untouched and nothing re-recorded
  (`test_retained_frame`, `test_patch_rows` and the new
  `test_retained_idle` under `MANIML_TEST_GPU=1`: 95 OK in each of the
  default, `MANIML_VERIFY_LEDGER=1` and `MANIML_RETAINED_FRAME=0`); the
  lockstep histories, which hold the flag-on bytes and cache to the
  flag-off ones after every frame, took the runs path 570 times and the
  idle path 84; the whole suite with the PriceDiscovery link tree 1,117
  tests, 64 skipped (its one failure the new module missing from
  `ci.yml`, added); the GPU-gated modules 166 OK, 1 skipped. In the
  built-in browser pane, a viewer of EpisodeB2 from this worktree: the
  Default, Phase B and Phase A selected in turn, pausepoints stepped
  forward and played back, units jumped to, wheel zooms, no console
  message and no error in the engine's log. No WGSL or `webgpu.js`
  changed; the device runs played every stream through the real driver
  and every shader in Chrome 152 with no uncaptured error.

## Runs

From `/Users/taylorjweidman/Projects/ManimLive/maniml-b5` (branch
`b5-loose-ends`, 48b7e6d4 plus this increment's tree; every serialize run
recorded its 28 sources unchanged from start to end, and each hashes the
same in the tree committed but `benchmarks/flip_gates.py`, whose module
docstring alone was written after the runs; the device runs' page, driver
and WGSL hash the same), interpreter `maniml/.venv/bin/python` (Python 3.13.9,
wgpu 0.32.0, numpy 2.5.2), Node 22.16, Apple M3, macOS 26.6.2,
`MANIML_GPU_TIMESTAMPS` unset. The device: the desktop app's built-in
browser pane, Chrome 152.0.7977.130, WebGPU adapter apple / metal-3,
`timestamp-query` offered, the page cross-origin isolated, the pane hidden
(`document.visibilityState` "hidden" throughout: no compositor frames, the
page's work and the GPU's the same). One run at a time, nothing else of
ours running; ioreg read the GPU 8-12% busy at every serialize run's start
(the wait for three samples at or below 10% gave up at 11-12% on three),
load 2.2-3.3. `$E` is B5.6's tree of links in which both episodes resolve.

```bash
S=(<scene file> <scene class>)       # per scene of flip_gates.TIMED_SCENES["phase_b"]
python -m benchmarks.flip_gates serialize --flip phase_b --scene $S --tick-updaters --play-frames \
    --camera-moves --navigations 4 --record --output runs/<scene>/serialize      # 01:26-01:49
python -m benchmarks.device_frames prepare --serve serve --streams <Scene>=runs/<scene>/serialize/streams ...
python -m benchmarks.device_frames serve --serve serve --port 8741
#   device_frames.html in the pane:
#   startAll([[<Scene>, ["phase_a_f7", "phase_a_f8", "phase_b_forced_f7", "phase_b_forced_f8"], 5], ...])
#   (01:51-02:13: orbs, lattice, EpisodeB2, PriceDiscovery, EpisodeB3)
python -m benchmarks.device_frames collect --serve serve --scene <Scene> --serialize runs/<scene>/serialize \
    --output runs/<scene>/device
python -m benchmarks.episode_frames --scene $S --variants phase_b_retained nets gpu_border --tick-updaters \
    --play-frames --output runs/<scene>/frames
python -m benchmarks.flip_gates complete --flip phase_b --serialize runs/<scene>/serialize \
    --device runs/<scene>/device --pixels runs/<scene>/frames --limit 1.25 --output runs/<scene>/complete
python -m benchmarks.flip_gates gate --flip phase_b --complete runs/{b2,pd,b3,orbs,lattice}/complete --output gate
```

The scenes: `$E/Blocks/B2_Supply/03_Code.py` EpisodeB2,
`$E/Blocks/B3_Equilibrium/Animate.py` PriceDiscovery (its
`_archive/Animate.py`), econ-0100's `Blocks/B3_Equilibrium/B3_Animation.py`
EpisodeB3, `benchmarks/surface_scenes.py` OrbsScene and LatticeScene.
Four serializers (each stack in both formats), 12 samples after 3 warmups
a class, 4 replays of each play, 4 navigation rounds (the first a
warmup), five plain and five stamped rounds of every stream on the
device. Messages a stream: EpisodeB2 1,420 (1,226 sent in format 8),
PriceDiscovery 1,364, EpisodeB3 1,240, the orbs and the lattice 379;
the largest stream the lattice's Phase A format 7 (2.18 GB of messages,
served in five parts).

**The device's GPU part.** Two stamps a message: the beginning of its
first pass and the end of its present pass. Calibrated on the orbs'
streams before the campaign (`calibration/`): stamping both ends of every
pass, as the native instrument does, read the orbs' program play (73
passes a message) 4.29 ms against 3.45 bracketed, about 12 µs a stamped
pass, where a two-pass redraw read the same either way; and an empty pass
stamps 0 on Apple's GPUs. Chrome quantizes a stamp to 2^17 ns (131 µs):
per message the mean over its five stamped rounds. The GPU's clock follows
the load, and each message starts on an idle GPU (the page waits for the
device between messages): the same message reads 1.1-4.7 ms across rounds
(the orbs' redraws), so every ratio here is within a run, the stacks'
streams alternating round by round in rotated order. The check
(`device_check`, the table's last column in `complete/summary.md`) takes
the wait for `onSubmittedWorkDone` in place of the stamps: no stamps, but
the callback's latency (about 2 ms) in every sent message; it fails the
same cells.

## Exploratory runs, before the serializer's change

`explore/` holds the first two scenes as measured with six serializers
(`--diagnostics`, Phase A with nets beside the two gate stacks) before the
unchanged-frame paths and the ticked frames' rotation: EpisodeB2 format 8
ticked 1.354 and PriceDiscovery 1.208, stills 1.139 and 1.134. The six
serializers' rotation overstated both (a serializer that follows five
others finds less of its work in the processor's caches), which is why
the gate's runs serialize four and the diagnostics run apart; and the
ticks were one serializer a tick in a fixed order, which gave one stack
all the ticks of one phase of an updater's cycle (Phase A read 4.30 ms at
8.a and Phase A with nets, the same stack there, 5.49).

## Files

- `gate/`: `summary.json` and `summary.md`, the verdict over the five
  scenes.
- `<scene>/complete/`: `summary.json`, `summary.md` (every class in both
  formats, the device check, the first visits, the pixels), per scene.
- `<scene>/serialize_report.json`: the serialize run (its streams, 7.5 GB
  with the lattice's, stay in the scratch folder), `<scene>/complete/report.json`
  every unit's parts, `<scene>/device_summary.json` the device run's
  conditions and each stream's timings per class, and
  `<scene>/frames_summary.json` the pixel run.
- `diagnostics/<scene>/`: the orbs', the lattice's and EpisodeB3's
  diagnostic runs (`--diagnostics`: Phase A with nets beside the two gate
  stacks, six serializers, the six streams on the device, 02:21-03:00),
  `summary.json` (`diagnostics`: each stack's parts and the two ratios per
  class) and the serialize report. Not judged.
- `calibration/`: the bracket against every pass stamped (`README.txt`,
  the reduction; the raw per-message samples beside it).
- `explore/`: the exploratory runs' complete summaries and serialize
  reports.
- `conditions.log`: every run's start, end and the GPU and load at its
  start.
- `tick_profile.py` (`PYTHONPATH=. python tick_profile.py <file> <class>
  <checkpoint> [ticks] [profile]`; `NOFAST=1` takes the runs path out) and
  `tick_leaves.py` (the leaves a tick moves, and why they are prepared):
  the ticked frames' probes.
- `summary.json`: the verdict, the cells, the conditions and the
  commands.

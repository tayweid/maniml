# GPU pass timestamps on the B1 controls (2026-09-26)

The five fixture controls of `patch_fill_20260911`, measured again with the
per-pass GPU timestamp instrument (`MANIML_GPU_TIMESTAMPS=1`,
`maniml/web/wgpu_renderer.py` `_PassTimestamps`) beside them, to attribute
the patch fill's GPU time and to say whether its wall-clock gap to Phase A
is GPU time. The gate numbers come from runs with the flag unset; the
attribution from a separate run with it set, as the instrument's validity
review requires (the flag perturbs what it measures: ~30 µs of wall clock
per stamped pass, and a ~1.6 ms resolve that is kept outside every timed
interval). Nothing here recommends a design; the reading is in
`docs/phase_b1_plan.md`'s terms. The controls below are the second pass of
the day, on a quiet GPU; the first pass, taken under another session's GPU
load, is superseded (see Runs). The two course episodes, measured with the same
recipe in two passes (one between the controls' passes, one after them),
are in the Episodes section.

## Runs

From `/Users/taylorjweidman/Projects/ManimLive/maniml-gpu-timestamps`
(branch `gpu-timestamps`, commit `c4aaacff` = main, **plus the uncommitted
instrument** in the working tree: `maniml/web/wgpu_renderer.py`,
`benchmarks/gpu_borders.py`, `benchmarks/generated_output.py`,
`benchmarks/probes/patch_pass_probe.py`, `benchmarks/episode_frames.py`;
`summary.json` `source_files_sha256` carries the hashes of what was
measured, identical across the three harness runs, unchanged during each,
and identical to the first pass's and the episodes'), interpreter
`maniml/.venv/bin/python` (Python 3.13.9, wgpu 0.32.0), Apple M3, Metal,
IntegratedGPU, macOS 26.6.2, in this order, one on the GPU at a time,
11:24-11:25 local (15:24-15:25 UTC):

```bash
# GATE A, flag unset
python -m benchmarks.gpu_borders --output /private/tmp/maniml-ts-gate-a --samples 12 --warmups 3 \
  --cases tex_static tex_pan tex_zoom5 tex_zoom4_cycle changing_paths --variants patch_fill gpu_border
# GATE B, flag unset
python -m benchmarks.gpu_borders --output /private/tmp/maniml-ts-gate-b --samples 12 --warmups 3 \
  --cases tex_static tex_pan tex_zoom5 tex_zoom4_cycle changing_paths --variants patch_fill original_2d
# ATTRIBUTION, flag set
MANIML_GPU_TIMESTAMPS=1 python -m benchmarks.gpu_borders --output /private/tmp/maniml-ts-attrib --samples 12 --warmups 3 \
  --cases tex_static tex_pan tex_zoom5 tex_zoom4_cycle changing_paths --variants patch_fill gpu_border
# PROBE (sets the flag itself)
PYTHONPATH=. python -m benchmarks.probes.patch_pass_probe passes
PYTHONPATH=. python -m benchmarks.probes.patch_pass_probe phasea
```

Twelve samples after three warmups per control, two variants rotating
frame by frame (the order reverses every second round); the probe runs 40
samples after 5 warmups, interleaved. Each harness run took 3.5-4.0 s,
each probe 4.7-5.4 s (`summary.json` `run_wall_seconds`).
`attribution_report.json` is the attribution run's complete report; the
gate runs' reports and all PNGs stay in `/private/tmp/maniml-ts-<run>/`.

**The GPU was quiet.** The first pass of exactly these five commands
(10:28-10:30 local) ran while another session's live viewer (`python -m
maniml .../econ-0100/DragDemo.py`, rendering into a Chrome ManimLive app
window) held the M3 at 35-42% device utilization; that process was then
stopped (`kill -STOP`: pid 33342 read `Ts`, 0.0% CPU, in every sample of
this pass). Device utilization (`ioreg -r -c IOAccelerator`, "Device
Utilization %", three samples before and three after each run,
`summary.json` `gpu_load_during_runs`) read 0-12% before every run, the
desktop compositor's baseline on this machine with no other GPU client
(the samples alternate 0 and ~10 with WindowServer's repaints), and 0-10%
again by the second sample after each run; the 16-17% one second after a
harness run and 35-36% one second after a probe are the run's own tail.
Load averages of 2.6-3.0 are other sessions' CPU work. The first pass's
numbers are superseded everywhere below; for the record, its still text
frame read patch fill 5.66 / 4.34 against Phase A 4.79 / 3.98 ms complete
(Original 2D 5.67 / 5.29), `gpu_total_ms` 1.332 / 1.321 against 1.163 /
1.018 with the output pass +0.245 ms exclusive, and its outputs are kept in
`/private/tmp/maniml-ts-<run>-loaded-1029/` and `summary.json`
`superseded_first_pass`. The Episodes section's two passes ran at the same
0-12% baseline, one between the controls' passes and one after them.

**Quiet against loaded: what moved, what did not.** The patch fill's own
numbers did not move: still text complete 5.66 / 4.23 against 5.66 / 4.34
loaded, `gpu_total_ms` 1.325 / 1.319 against 1.332 / 1.321, output pass
1.232 against 1.240 ms exclusive; the border (0.10 / 0.17 ms) and resolve
(0.092 ms) passes are the same to the third digit for both variants, the
pixel fractions are identical to the third digit, the cold frames within
5%. What moved is the readback wait of Phase A and Original 2D, and Phase
A's GPU tail: Phase A's still text median fell from 4.79 to 4.15 ms (its
readback column 2.53 → 1.92; it now lands in the ~1.9 ms mode on 10 of 12
frames against 6), its pan from 5.50 to 4.63, and its `gpu_total_ms` median
from 1.163 to 1.024 (the loaded tail of 1.23-2.30 ms is gone). So the still
text's median gap grew from +0.87 to +1.51 ms while the minima gap stayed
+0.36, and the GPU difference, +0.30 ms at the minima in both passes, is
+0.30 at the medians too (loaded: +0.17, the tail). The ~5-6.6 ms readback
mode did not occur on the still text this pass, the clock excursions left
the harness rows (5% zoom patch fill minimum 0.494 → 1.329 ms, now simply
frame 0 without its border pass), the morph control's GPU difference went
from +0.14 to −0.01 ms, the probe's five-draw cost from 0.21-0.23 to
0.15-0.19 ms, and its interleaved Phase A gap held (+0.33 / +0.45 → +0.29 /
+0.44).

## (i) Gate: complete frame, flag unset

`serialize_through_rgba_image_ms` (complete frame: serialize, parse,
prepare, encode, submit, full 2160x1080 readback, PIL image) and
`submit_through_full_readback_ms` as median / minimum, `prepare_ms` median.
(A) is the patch fill against Phase A, (B) the patch fill against Original
2D; (B) is the command shape of `patch_fill_20260911`'s patch fill run.

| Control | Variant (run) | Complete frame p50 / min | Submit→full readback p50 / min | Prepare p50 |
| --- | --- | ---: | ---: | ---: |
| Static 101-glyph text | Patch fill (A) | 5.66 / 4.23 | 3.43 / 1.89 | 1.22 |
| Static 101-glyph text | Phase A (GPU border) (A) | 4.15 / 3.87 | 1.92 / 1.84 | 1.34 |
| Static 101-glyph text | Patch fill (B) | 5.64 / 4.21 | 3.46 / 1.94 | 1.23 |
| Static 101-glyph text | Original 2D (B) | 5.66 / 5.34 | 1.91 / 1.82 | 2.17 |
| Text pan | Patch fill (A) | 5.77 / 5.33 | 3.47 / 3.09 | 1.19 |
| Text pan | Phase A (GPU border) (A) | 4.63 / 3.90 | 1.87 / 1.80 | 1.77 |
| Text pan | Patch fill (B) | 5.83 / 5.48 | 3.45 / 3.37 | 1.22 |
| Text pan | Original 2D (B) | 5.64 / 5.41 | 1.93 / 1.83 | 2.19 |
| Repeated 5% zoom | Patch fill (A) | 5.80 / 5.03 | 3.49 / 2.88 | 1.20 |
| Repeated 5% zoom | Phase A (GPU border) (A) | 6.22 / 3.87 | 3.43 / 1.82 | 1.78 |
| Repeated 5% zoom | Patch fill (B) | 5.91 / 5.42 | 3.50 / 3.20 | 1.21 |
| Repeated 5% zoom | Original 2D (B) | 5.59 / 5.36 | 1.84 / 1.81 | 2.16 |
| Text 1→4→1 zoom | Patch fill (A) | 5.85 / 5.36 | 3.47 / 3.40 | 1.22 |
| Text 1→4→1 zoom | Phase A (GPU border) (A) | 6.36 / 4.09 | 3.42 / 1.83 | 1.89 |
| Text 1→4→1 zoom | Patch fill (B) | 6.01 / 4.11 | 3.51 / 1.90 | 1.23 |
| Text 1→4→1 zoom | Original 2D (B) | 5.60 / 5.30 | 1.89 / 1.80 | 2.18 |
| Concave quad morph + circle | Patch fill (A) | 3.72 / 3.32 | 1.97 / 1.85 | 0.63 |
| Concave quad morph + circle | Phase A (GPU border) (A) | 4.06 / 3.06 | 1.99 / 1.83 | 0.89 |
| Concave quad morph + circle | Patch fill (B) | 3.56 / 3.10 | 1.90 / 1.85 | 0.66 |
| Concave quad morph + circle | Original 2D (B) | 3.20 / 3.01 | 1.92 / 1.85 | 0.34 |

For the same rows on 2026-09-11 (second build, `patch_fill_20260911`,
`patch_fill original_2d` and `gpu_border original_2d` rotations, a
different load): patch fill 5.11 / 4.83, Phase A 5.28 / 3.99, Original 2D
5.41 / 5.14 on the still text: a minima gap of 0.84 ms with the medians
0.17 ms the other way. The "~1 ms" of `docs/phase_b1_plan.md` ("Third
candidate") is the probe's figure from the same day, wall clock around
`render()` interleaved, minima at the normal view: Phase A 2.45 ms, the
patch path 3.50 ms, the patch path with only its strip draws 2.81 ms; the
plan already put the residual in "time waiting for the GPU inside the
readback". Today the patch fill's median is 0.55 ms above that run's and
its minimum 0.6 below, Phase A's median 1.13 below and its minimum 0.12
below, Original 2D's 0.25 and 0.20 above: the readback column's mode
structure (below) moves each variant's median by whole quanta, and the
two runs are not one table.

What the still text frame's gap is made of (gate A, medians / minima, Δ of
medians):

| Column (tex_static, gate A) | Patch fill p50 / min | Phase A p50 / min | Δ p50 |
| --- | ---: | ---: | ---: |
| serialize_ms | 1.39 / 1.33 | 1.47 / 1.42 | -0.08 |
| parse_ms | 0.02 / 0.01 | 0.01 / 0.01 | +0.00 |
| prepare_ms | 1.22 / 1.19 | 1.34 / 1.31 | -0.12 |
| render_cpu_encode_ms | 0.36 / 0.30 | 0.27 / 0.22 | +0.09 |
| submit_through_full_readback_ms | 3.43 / 1.89 | 1.92 / 1.84 | +1.51 |
| post_readback_ms | 0.39 / 0.30 | 0.36 / 0.31 | +0.03 |
| serialize_through_rgba_image_ms | 5.66 / 4.23 | 4.15 / 3.87 | +1.51 |
| wire_encode_ms | 0.15 / 0.14 | 0.12 / 0.10 | +0.03 |
| source_evaluation_ms | 0.15 / 0.11 | 0.07 / 0.06 | +0.08 |

The patch fill's CPU side is slightly cheaper (serialize −0.08 ms, of
which prepare is −0.12; five draws against one cost +0.09 ms of encoding),
netting to +0.04 ms with the post-readback conversion; the whole median
gap, +1.51 ms, sits in `submit_through_full_readback_ms`, and it is a
change of mode rather than a shift. That column is quantized on this
machine: on the still text every variant's twelve values fall at ~1.9 ms
or ~3.45 ms (sorted, gate A: patch fill 1.89 then 3.13-3.55 ×11; Phase A
1.84-2.06 ×10 then 3.39, 3.48; gate B: patch fill 1.94 then 3.37-3.58 ×11;
Original 2D 1.82-2.00 ×12). The patch fill lands in the 3.45 ms mode on 11
of 12 frames, Phase A on 2, Original 2D on none; the minima of the three
sit within 0.12 ms of each other (1.82-1.94). The gap between the modes
(~1.5 ms) is the readback wait's grain, not work: the attribution run puts
the GPU's own difference at 0.30 ms (next table), and
`submit_through_full_readback_ms` contains the full frame readback and the
host's wait for it, which the browser never does (`gate_scope`). The
`readback_distribution` fields of the reports record the fraction of
frames under 3 ms per variant (still text: patch fill 0.08 / 0.08, Phase A
0.83, Original 2D 1.00; `summary.json` `gate`
`readback_fraction_under_3_ms` for every row).

On the other controls the sign of the median gap varies (pan +1.13, 5%
zoom −0.42, 1→4→1 zoom −0.50, morph −0.34 ms, patch minus Phase A) as the
two variants fall into the modes differently: Phase A is under 3 ms on 10
of 12 pan frames but on 2 of 12 on either zoom, where it regenerates
border sources every frame, and the patch fill on 0-1 of 12 text frames
and 10-12 of 12 on the morph. The minima are 4.23-5.36 ms for the patch
fill on text against 3.87-4.09 for Phase A (patch minus Phase A +0.36 to
+1.43), and 3.32 against 3.06 on the morph.

Cold first frames (archived in the reports, excluded from every statistic,
a seek is what they feel like): still text, gate A, patch fill 359.1 ms
against Phase A 42.2 ms (loaded pass 363.9 / 41.7): the patch pipelines
compile on first use and the 101-glyph object table is built. Not a
steady-state number and not the gate's; recorded because the difference is
large.

## Pixels

Worst fraction of pixels differing by more than 24 of 255 in any RGB
channel over the twelve measured frames, and the worst single-channel
difference. `patch_vs_gpu_border` from gate A, `patch_vs_original` from
gate B. `patch_vs_cpu` (CPU-border Phase A) was not in either rotation.

| Control | patch_vs_gpu_border (A) worst % over 24 / max | patch_vs_original (B) worst % over 24 / max |
| --- | ---: | ---: |
| Static 101-glyph text | 0.00% / 15 | 0.21% / 82 |
| Text pan | 0.00% / 15 | 0.24% / 93 |
| Repeated 5% zoom | 0.00% / 15 | 0.29% / 88 |
| Text 1→4→1 zoom | 0.00% / 15 | 0.62% / 98 |
| Concave quad morph + circle | 0.00% / 0 | 0.07% / 54 |

The patch fill and Phase A differ by at most 15 of 255 on text and are
identical on the morph control; against Original 2D the fractions are the
2026-09-11 ones and the loaded pass's to the third digit (0.208 / 0.242 /
0.293 / 0.616 / 0.066%), and the 1→4→1 zoom's 0.62% is above the plan's
0.5% as Phase A's own fraction on the same frames was then. Pixels do not
depend on the load; the same frames were drawn.

## (ii) Attribution: GPU pass time, flag set

`gpu_total_ms` (first pass begin to latest pass end, the frame on the GPU)
median / minimum; per-label exclusive medians (each pass's end past the
latest end before it; passes sharing a label add up; n = rows carrying the
column); `gpu_sum_ms` (pass durations added, a diagnostic of overlap) and
`gpu_readback_ms` (the instrument's resolve and map, paid after the frame,
outside every wall-clock column). Rows "patch − Phase A" are the
differences of the medians (total also of the minima).

| Control | Variant | gpu_total p50 / min | excl borders p50 (n) | excl out p50 (n) | excl resolve p50 (n) | gpu_sum p50 | readback p50 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Static 101-glyph text | Patch fill | 1.325 / 1.319 | — | 1.232 (12) | 0.092 (12) | 2.185 | 1.66 |
| Static 101-glyph text | Phase A (GPU border) | 1.024 / 1.017 | — | 0.932 (12) | 0.092 (12) | 1.817 | 1.66 |
| Static 101-glyph text | patch − Phase A | +0.301 / +0.301 | — | +0.301 | +0.000 | | |
| Text pan | Patch fill | 1.322 / 1.314 | — | 1.230 (12) | 0.092 (12) | 2.177 | 1.66 |
| Text pan | Phase A (GPU border) | 1.020 / 1.018 | — | 0.928 (12) | 0.092 (12) | 1.810 | 1.65 |
| Text pan | patch − Phase A | +0.301 / +0.296 | — | +0.301 | -0.000 | | |
| Repeated 5% zoom | Patch fill | 1.445 / 1.329 | 0.102 (11) | 1.251 (12) | 0.092 (12) | 2.314 | 1.66 |
| Repeated 5% zoom | Phase A (GPU border) | 1.134 / 1.021 | 0.100 (11) | 0.941 (12) | 0.092 (12) | 1.927 | 1.67 |
| Repeated 5% zoom | patch − Phase A | +0.311 / +0.308 | +0.002 | +0.309 | -0.000 | | |
| Text 1→4→1 zoom | Patch fill | 1.901 / 1.323 | 0.176 (11) | 1.617 (12) | 0.092 (12) | 2.825 | 1.66 |
| Text 1→4→1 zoom | Phase A (GPU border) | 1.380 / 1.021 | 0.173 (11) | 1.113 (12) | 0.092 (12) | 2.187 | 1.66 |
| Text 1→4→1 zoom | patch − Phase A | +0.521 / +0.302 | +0.002 | +0.504 | -0.000 | | |
| Concave quad morph + circle | Patch fill | 0.924 / 0.911 | 0.015 (11) | 0.816 (12) | 0.093 (12) | 1.713 | 1.66 |
| Concave quad morph + circle | Phase A (GPU border) | 0.931 / 0.893 | 0.039 (11) | 0.799 (12) | 0.093 (12) | 1.696 | 1.66 |
| Concave quad morph + circle | patch − Phase A | -0.006 / +0.018 | -0.023 | +0.017 | +0.000 | | |

Passes per frame: the still text and pan frames encode `out` and `resolve`
only for both variants (border sources cached, nothing regenerated); the
zoom and morph controls add a `borders` compute pass on 11 of 12 frames
(measured frame 0 repeats the warmups' pose), Phase A on the morph two per
frame (its two batches) against the patch fill's one. No `programs` or
`nets` pass: neither B3 nor B2 is in these frames. Every pass the frames
encoded is in the table.

The border pass costs the same in both variants (0.10 / 0.17 ms exclusive
on the zooms; it is the same compute) and the resolve pass the same (0.092
ms exclusive; its begin-to-end `gpu_pass_resolve_ms` is ~0.9-1.0 ms of
waiting on the out pass). The whole GPU difference is the output pass: on
the still text +0.301 ms exclusive (1.232 against 0.932), +0.301 on the
pan, +0.309 at 5% zoom, +0.504 at the 1→4→1 zoom (where the strips are
longer), +0.017 on the morph, where Phase A's two border passes cost 0.023
ms more than the patch fill's one and the frame totals come out equal
(−0.006). `gpu_total_ms` on the still text: 1.325 against 1.024 at the
median and 1.319 against 1.017 at the minimum, +0.301 either way; the
sorted values are patch fill 1.319-1.330 ×10 then 1.464, 1.910 and Phase
A 1.017-1.025 ×8 then 1.109, 1.383, 1.600, 1.601 (`summary.json`
`tex_static_gpu_total_sorted_ms`), so on the quiet GPU the medians and the
minima agree to 0.01 ms and no row's minimum is an excursion (the loaded
pass's Phase A median was pulled up by a 1.23-2.30 ms tail). The 1→4→1
zoom's spread (patch fill 1.323-2.629) is the pose, not the clock: frame 0
at zoom 1 without a border pass, the rest at magnifications up to 4.
`gpu_sum_ms` exceeds `gpu_total_ms` by ~0.86 ms on every still text row:
the resolve pass's vertex stage begins before the out pass's fragments
end, so its duration overlaps.

Flag-on wall clock, recorded and not a gate number: still text patch fill
5.70 / 5.41, Phase A 4.18 / 4.01 complete; `post_readback_ms` 0.35-0.40
against 0.36-0.39 flag off while `gpu_readback_ms` is 1.65-1.67, which
confirms the resolve is outside `post_readback_ms` and every other
interval (the reviewers' note that it sat inside `post_readback_ms`
described an earlier build; the harness now reads `gpu_timings` after its
last timer). The two stamped passes' ~60 µs are enough to keep the patch
fill out of the 1.9 ms readback mode on every flag-on frame (its readback
values 3.30-3.68 ×12; its complete-frame minimum rose from 4.23 to 5.41)
while Phase A stays in it on 9 of 12, which is the perturbation the recipe
warns of and why no flag-on total enters the gate table.

## (iii) Probe: skipped draws on the 101-glyph text

`benchmarks/probes/patch_pass_probe.py`, 40 samples after 5 warmups,
interleaved with rotating order. Wall clock is `render()` through its
readback **with the flag on** (the probe sets `MANIML_GPU_TIMESTAMPS=1`
itself), so its wall columns carry the stamped passes' perturbation and
are not gate numbers. "GPU frame" is `gpu_total_ms`; "GPU out pass" is the
out pass's exclusive time. Derived columns: in `passes`, all five draws
minus the variant (what the skipped draw cost); in the interleaved
`phasea` sections, the variant minus the patch fill's all five draws.

**tex normal, passes skipped** (passes)

| Variant | wall p50 / min | GPU frame p50 / min | GPU out pass (excl) p50 / min | all − this: wall p50 | GPU frame p50 | out p50 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| all five draws | 5.38 / 2.55 | 1.48 / 0.73 | 1.39 / 0.68 |  |  |  |
| no cover (fan+patch) draw | 5.27 / 2.49 | 1.41 / 0.54 | 1.32 / 0.50 | +0.11 | +0.07 | +0.07 |
| no mark_patch draw | 5.36 / 2.70 | 1.46 / 0.70 | 1.37 / 0.65 | +0.02 | +0.02 | +0.02 |
| no mark_fan draw | 5.24 / 2.43 | 1.47 / 0.70 | 1.38 / 0.65 | +0.14 | +0.01 | +0.01 |
| no patch draws at all (strips only) | 5.37 / 2.53 | 1.33 / 0.63 | 1.23 / 0.58 | +0.01 | +0.15 | +0.16 |

**tex zoom, passes skipped** (passes)

| Variant | wall p50 / min | GPU frame p50 / min | GPU out pass (excl) p50 / min | all − this: wall p50 | GPU frame p50 | out p50 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| all five draws | 5.43 / 4.23 | 1.79 / 1.56 | 1.69 / 1.46 |  |  |  |
| no cover (fan+patch) draw | 5.54 / 4.25 | 1.72 / 1.45 | 1.62 / 1.36 | -0.11 | +0.07 | +0.07 |
| no mark_patch draw | 5.51 / 4.27 | 1.75 / 1.50 | 1.65 / 1.40 | -0.08 | +0.04 | +0.04 |
| no mark_fan draw | 5.55 / 4.33 | 1.75 / 1.51 | 1.66 / 1.42 | -0.12 | +0.04 | +0.03 |
| no patch draws at all (strips only) | 5.47 / 4.12 | 1.60 / 1.35 | 1.51 / 1.26 | -0.04 | +0.19 | +0.18 |

**tex normal: capacity 24 (11 quads per curve), needed steps 6 (5 quads)** (phasea)

| Variant | wall p50 / min | GPU frame p50 / min | GPU out pass (excl) p50 / min | all − this: wall p50 | GPU frame p50 | out p50 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| pattern at the reservation (today) | 5.32 / 2.46 | 1.48 / 0.38 | 1.39 / 0.36 |  |  |  |
| pattern at the needed steps | 5.17 / 2.46 | 1.33 / 0.35 | 1.24 / 0.32 |  |  |  |
| no strips at all (bound) | 5.16 / 2.49 | 1.06 / 0.31 | 0.97 / 0.28 |  |  |  |

**tex zoom: capacity 44 (21 quads per curve), needed steps 11 (10 quads)** (phasea)

| Variant | wall p50 / min | GPU frame p50 / min | GPU out pass (excl) p50 / min | all − this: wall p50 | GPU frame p50 | out p50 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| pattern at the reservation (today) | 5.12 / 4.21 | 1.78 / 1.56 | 1.69 / 1.47 |  |  |  |
| pattern at the needed steps | 5.15 / 4.06 | 1.53 / 1.34 | 1.44 / 1.25 |  |  |  |
| no strips at all (bound) | 4.86 / 2.63 | 1.09 / 1.06 | 1.00 / 0.97 |  |  |  |

**tex normal, Phase A against the patch path, interleaved** (phasea)

| Variant | wall p50 / min | GPU frame p50 / min | GPU out pass (excl) p50 / min | all − this: wall p50 | GPU frame p50 | out p50 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Phase A (mesh fill + GPU border) | 4.81 / 2.51 | 1.19 / 1.02 | 1.09 / 0.93 | -0.53 | -0.29 | -0.30 |
| patch fill, all five draws | 5.34 / 4.15 | 1.48 / 1.32 | 1.39 / 1.23 |  |  |  |
| patch fill, no patch draws | 5.19 / 2.56 | 1.31 / 1.15 | 1.22 / 1.06 | -0.15 | -0.17 | -0.17 |

**tex zoom, Phase A against the patch path, interleaved** (phasea)

| Variant | wall p50 / min | GPU frame p50 / min | GPU out pass (excl) p50 / min | all − this: wall p50 | GPU frame p50 | out p50 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Phase A (mesh fill + GPU border) | 5.22 / 2.44 | 1.37 / 1.13 | 1.28 / 1.03 | -0.20 | -0.44 | -0.44 |
| patch fill, all five draws | 5.42 / 4.11 | 1.81 / 1.55 | 1.72 / 1.46 |  |  |  |
| patch fill, no patch draws | 5.28 / 4.11 | 1.59 / 1.35 | 1.50 / 1.26 | -0.14 | -0.22 | -0.22 |

The five patch draws together are 0.16-0.18 ms of the out pass at either
zoom (all five minus strips only), the cover draw 0.07 ms, the mark patch
0.02-0.04, the mark fan 0.01-0.03 (these three do not add to the whole:
each skipped draw also changes what the others cover). Against Phase A
interleaved, the patch fill's GPU frame is +0.29 ms (normal) and +0.44 ms
(zoom), all of it in the out pass (+0.30 / +0.44), where the wall-clock
minima say +1.64 / +1.67 ms (loaded pass +1.65 / +1.56; 2026-09-11 +1.05 /
+0.07): the wall gap the plan called "~1 ms" is not GPU execution time; the
patch path with no patch draws at all is still +0.12 / +0.22 ms above
Phase A (1.31 against 1.19, 1.59 against 1.37), so 40-50% of the GPU gap
is the patch path's strips and stencil state, not the patch triangles. The
wall-clock differences in the `passes` sections (−0.12 to +0.14 ms) are
below the readback quantum and do not resolve the draws; the GPU columns
do. Which readback mode a frame lands in also depends on what ran before
it (the alternation effect): in the `passes` sections, patch path against
patch path at normal zoom, the wall minima are 2.4-2.7 ms, while the same
frame interleaved with Phase A never leaves 4.1 ms. The normal-view GPU
minima of 0.31-0.73 ms against medians of 1.06-1.48 are clock excursions
(the loaded pass had them at 0.34-0.45 too); the medians are the figures.
The first `phasea` sections (strip pattern at the reservation / at the
needed steps / none) show the reservation's cost at zoom: 1.69 against
1.44 ms out pass (+0.25) with the strips drawn to capacity 44 rather than
the needed 11 steps, and +0.15 ms at normal zoom (1.39 against 1.24).

## Reading, still text frame

The complete frame is 1.51 ms slower for the patch fill at the median
(5.66 against 4.15) and 0.36 ms at the minimum (4.23 against 3.87), gate
A, flag off. The GPU accounts for 0.30 ms of that (`gpu_total_ms` 1.325
against 1.024 at the median, 1.319 against 1.017 at the minimum), all of
it in the output pass (+0.301 ms exclusive; the border and resolve passes
are equal), of which the five patch draws are ~0.16 ms and the rest the
patch path's strips and stencil state; the probe puts the same difference
at +0.29 ms interleaved. The remainder of the wall gap is not GPU
execution: the CPU columns net to +0.04 ms (prepare −0.12 and serialize
−0.08 against encoding +0.09 and source evaluation +0.08), and the +1.51
ms in `submit_through_full_readback_ms` is one quantum of the readback
wait, whose ~1.9 and ~3.45 ms modes the patch fill's extra 0.30 ms of GPU
time tips on 11 of 12 frames against Phase A's 2. The plan's "~1 ms" (the
probe's interleaved render-call minima, patch path 3.50 against Phase A
2.45 on 2026-09-11; today 4.15 against 2.51 with the flag on) is the same
readback-mode effect seen at the render call, and the harness's 2026-09-11
minima gap (0.84 ms) is 0.36 ms today on the same command shape, quiet as
it was loaded; none of these is a GPU-time figure. The GPU-time figure is
0.30 ms, in the output pass, the same at the median and the minimum and
the same under load, which the plan's own split (strips about a third,
fan and patch passes the rest) roughly matches.

## Scope and caveats

Reviewers' caveats, recorded as required, then this run's:

- **GPU timestamps do not remove the GPU-clock confound.** The period is a
  fixed nanosecond clock (`period_ns` 1.0), so pass durations stretch and
  shrink with the M3's clock state, which follows total machine load;
  interleaving remains necessary for relative comparisons, and absolute
  values (including minima) depend on what else is running. Measure on a
  quiet machine and keep the frame-by-frame rotation; read minima and
  medians together and treat a minimum far below the median as a clock
  excursion, not a floor (this pass: none in the harness rows, where every
  `gpu_total_ms` minimum is within 0.12 ms of its median unless frame 0
  lacks the border pass; the probe's normal-view sections still show them,
  GPU frame minima 0.31-0.73 ms against 1.06-1.48 medians, quiet as
  loaded); never compare `gpu_` columns across runs taken under different
  load. The reports carry this as `gpu_clock_caveat` beside
  `gpu_timing_scope`'s alternation-effect note.
- **The five controls plus the two episodes do not yet answer the gate as
  stated.** The Episodes section below closes the episode part (twelve
  pausepoints per episode, updater-ticked and mid-play frames on six of
  them); still open: the `patch_vs_cpu` pixel pair (CPU-border Phase A
  was in no rotation), named beats or a `--max-frames` above 12, and the
  browser driver (accepted exclusion, plan item 3). Excluded by construction: the
  browser, the readback-dominated `submit_through_full_readback_ms`
  column as a cost, the static redraw as the live per-frame cost of a
  pausepoint with updaters, and the cold rows (archived, not summarised).
- **What `gpu_total_ms` does and does not contain, verified:** the resolve
  and staging copy are outside every pass stamp and outside the total (a
  separate submission after the frame's readback, on the first read of
  `gpu_timings`) and, in this build, outside `post_readback_ms` as well
  (0.35-0.40 flag on against 0.36-0.39 flag off, with `gpu_readback_ms`
  1.66); the total also excludes the readback copy's GPU time and
  command-buffer scheduling, and the timing readback is one extra
  submission per frame that the queue contract classifies separately
  (`timing_submissions`, asserted to be exactly one per instrumented frame
  by `gpu_borders.sample`). At this resolution the readback column is
  readback-dominated; when comparing variants at 2160x1080 read
  `gpu_total_ms`.
- **Metal's pass stamps:** a render pass's begin stamp is its vertex-stage
  start, which overlaps the previous pass's fragment work, so per-pass
  `ms` overlaps and `gpu_sum_ms` exceeds `gpu_total_ms` (by ~0.86 ms on
  every still text row here); read `gpu_total_ms` and the per-label
  exclusive sums. Independent compute passes run out of order, so
  exclusive time for compute labels is meaningful only summed per label
  per frame, which is what the columns are. `gpu_pass_resolve_ms` is
  mostly waiting.
- **This pass's load.** The GPU carried no other client: device
  utilization 0-12% before every run (the compositor's baseline; the other
  session's viewer stopped at 0% CPU), load average 2.6-3.0 from other
  sessions' CPU work. This is the quiet-machine repeat the first pass
  called for, and its gate rows are the ones to set beside
  `patch_fill_20260911`. The loaded first pass (35-42% utilization) is
  superseded; its still text headline is kept in one sentence under Runs
  and in `summary.json` `superseded_first_pass`. The Episodes section's
  `gpu_` columns were taken at the same 0-12% baseline, in two passes
  (11:01-11:07 and 11:52-11:58); the clock caveat still says not to set
  them beside these.
- **The readback wait is quantized** at ~1.9 / ~3.45 ms on this machine
  and build (a third mode at ~5-7 ms and a 16.8 ms Phase A frame appear
  only in the 1→4→1 zoom's p95 this pass), so a median
  `submit_through_full_readback_ms` or complete-frame difference below
  ~1.5 ms between two variants can be a change in how often each crosses
  a mode boundary rather than a proportional cost; the minima and the GPU
  columns are the figures that resolve sub-millisecond differences. On
  the quiet GPU the modes are cleaner than under load (Phase A and
  Original 2D almost always in the lower one), which is why the still
  text's median gap is larger here (+1.51) than loaded (+0.87) while the
  minima gap and the GPU difference did not move.
- The instrument is uncommitted at the time of this archive; the hashes in
  `summary.json` identify it.

## Episodes

The same instrument and recipe on the two course episodes the B1 gate
names beside the fixture corpus, through `benchmarks/episode_frames.py`
(added with the instrument; `benchmarks/README.md`, "Episode frames"):
`EpisodeB2` (`econ-0100/Blocks/B2_Supply/03_Code.py`, a 2D `Scene`, 308
checkpoints, 84 pausepoints) and `PriceDiscovery`
(`econ-0100/Blocks/B3_Equilibrium/Animate.py`, a `ThreeDScene`, 131
checkpoints, 24 pausepoints). Every frame is 2160x1080. The scene is
loaded as the CLI loads it and its checkpoints built as present mode
builds them; twelve pausepoints per episode, thinned evenly over the file
keeping the last, are restored in turn and each variant redraws the
restored frame in rotation (a static redraw: sources cached between
rounds, the cost of a camera change); six of them are measured again with
their updaters ticking and mid-play. Both constructs ran to their last
checkpoint (`construct_error` null in all eight reports) and no variant
failed on any frame. The B3 build is not slow in this harness (checkpoints
are fast-forwarded; a whole B3 run including its build took 9-20 s, a B2
run 17-33 s).

The episodes were measured twice with this recipe, on the same sources:
a first pass at 11:01-11:07 local, between the controls' loaded and quiet
passes, and the pass below at 11:52-11:58, after the controls' quiet pass
and after the Measure phase's review of the recipe. The tables are the
second pass; the first is kept in `summary.json` under
`episodes.first_pass` and read against the second under Replication,
because two passes under the same load say which differences the method
resolves and which it does not.

Same worktree, interpreter, commit and uncommitted instrument as the
controls: the episode reports hash 48 repository sources, the 46 the
controls' reports also hash are identical to this archive's, all 48 are
identical across the eight runs and across both passes, and
`source_files_unchanged_during_run` is true for each; the episode files
hash `7e105159…` (B2) and `dfe6e831…` (B3). Run from the worktree in this
order, 11:52-11:58 local (15:52-15:58 UTC), one on the GPU at a time,
`<ep>` being the scene arguments above and `<EP>` `B2` or `B3`:

```bash
# GATE A, flag unset: 12 frames, 12 samples after 3 warmups, two variants rotating per frame
python -m benchmarks.episode_frames --scene <ep> --output /private/tmp/maniml-ts-<EP>-gate-a \
  --variants patch_fill gpu_border --samples 12 --warmups 3 --max-frames 12
# GATE B, flag unset
python -m benchmarks.episode_frames --scene <ep> --output /private/tmp/maniml-ts-<EP>-gate-b \
  --variants patch_fill original_2d --samples 12 --warmups 3 --max-frames 12
# ATTRIBUTION, flag set by the harness: 6 frames, 6 samples after 2 warmups
python -m benchmarks.episode_frames --scene <ep> --output /private/tmp/maniml-ts-<EP>-attrib \
  --variants patch_fill gpu_border --samples 6 --warmups 2 --max-frames 6 --gpu-timestamps
# LIVE, flag unset: updaters ticked before every round, and the play into each pausepoint
python -m benchmarks.episode_frames --scene <ep> --output /private/tmp/maniml-ts-<EP>-live \
  --variants patch_fill gpu_border --samples 12 --warmups 3 --max-frames 6 --tick-updaters --play-frames
```

All of B2 ran first, then all of B3. `--gpu-timestamps` sets
`MANIML_GPU_TIMESTAMPS=1` itself (the reports' `environment` carries it on
the two attribution runs and nothing on the other six). `--max-frames 6`
thins the same pausepoint list differently, so the attribution and live
runs share only their first and last frames with the gate runs (B2
checkpoints 12 and 307, B3 9 and 130) and take four others of their own.
The eight reports and summaries stay in `/private/tmp/maniml-ts-<EP>-<run>/`
(the first pass's in `/private/tmp/maniml-ts-<EP>-<run>-pass1-1104/`); the
numbers below are in `summary.json` under `episodes` (per frame: medians
and minima, the stage columns, the batch and draw counts, the pixel pairs,
the pass columns, gate A's cold rows).

**The GPU was quiet, as for the controls' second pass.** Device
utilization (`ioreg`, three samples before and three after each run,
`episodes.gpu_load_during_runs`) read 0-12% before every run, the
compositor's baseline; the 27-78% readings one second after a run ended
are the run's own tail, and the second and third samples after each run
are back at 0-12%. The other session's DragDemo viewer (pid 33342) stayed
stopped (`Ts`, 0.0% CPU in every sample); load averages of 1.9-2.8 are
other sessions' CPU work. The first pass ran at the same 0-12% baseline
with load averages of 2.3-6.2. The `gpu_` columns here were taken under a
different GPU load than the controls' and are not comparable with them
(the clock caveat above); within each run the frame-by-frame rotation
holds.

### (i) Gate: complete frame per pausepoint, flag unset

`serialize_through_rgba_image_ms` median / minimum over 12 samples, the
patch fill against Phase A (GPU border) from gate A and against Original
2D from gate B; Δ is patch minus the other, of medians. "Drawn" is the
frame's mobjects with points.

**EpisodeB2**

| Frame | Checkpoint (line) | Beat | Drawn | Patch fill (A) | Phase A (A) | Δ p50 | Patch fill (B) | Original 2D (B) | Δ p50 |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0 | 12 (36) | 0.a | 258 | 33.60 / 32.86 | 26.68 / 25.84 | +6.93 | 31.31 / 30.16 | 68.37 / 66.08 | −37.06 |
| 1 | 44 (215) | 2.h | 148 | 17.05 / 14.31 | 16.23 / 13.19 | +0.83 | 14.89 / 14.15 | 36.35 / 34.09 | −21.46 |
| 2 | 76 (351) | 3.i | 295 | 28.44 / 27.77 | 21.78 / 21.58 | +6.66 | 25.11 / 23.96 | 76.31 / 70.72 | −51.20 |
| 3 | 103 (622) | 4.c.1 | 79 | 10.55 / 7.53 | 10.66 / 9.04 | −0.11 | 8.12 / 7.67 | 13.64 / 10.47 | −5.51 |
| 4 | 120 (622) | 4.b.2 | 122 | 11.02 / 8.14 | 10.61 / 9.88 | +0.40 | 10.94 / 8.28 | 15.62 / 11.21 | −4.68 |
| 5 | 140 (622) | 4.b.4 | 122 | 11.27 / 8.29 | 13.15 / 11.54 | −1.88 | 11.28 / 8.29 | 14.54 / 11.25 | −3.26 |
| 6 | 157 (622) | 4.return.5 | 223 | 21.14 / 16.23 | 19.10 / 16.34 | +2.04 | 17.57 / 16.16 | 43.74 / 41.05 | −26.17 |
| 7 | 177 (622) | 4.return.7 | 229 | 21.64 / 17.02 | 19.63 / 16.38 | +2.01 | 17.52 / 16.97 | 44.81 / 43.16 | −27.29 |
| 8 | 194 (622) | 4.d.9 | 132 | 11.54 / 8.62 | 11.23 / 9.47 | +0.30 | 11.56 / 8.06 | 14.96 / 14.21 | −3.39 |
| 9 | 258 (685) | 4.h | 362 | 34.70 / 33.99 | 26.95 / 23.51 | +7.76 | 31.96 / 30.14 | 92.61 / 89.05 | −60.65 |
| 10 | 277 (762) | 5.a | 461 | 45.05 / 44.69 | 38.46 / 37.78 | +6.60 | 39.62 / 37.79 | 105.74 / 101.62 | −66.12 |
| 11 | 307 (1016) | 8.a | 531 | 63.93 / 62.78 | 36.53 / 35.89 | +27.40 | 60.44 / 59.10 | 171.84 / 168.90 | −111.41 |
| roll-up | median of frame medians | | | 21.39 | 19.36 | | 17.55 | 44.27 | |
| roll-up | worst frame median | | | 63.93 (frame 11) | 38.46 (frame 10) | | 60.44 (frame 11) | 171.84 (frame 11) | |
| roll-up | largest deficit | | | | | +27.40 (frame 11, 8.a, line 1016) | | | −3.26 (frame 5; every frame below) |

The patch fill's median is at or below Phase A's on 2 of 12 frames
(frames 3 and 5: 4.c.1 and 4.b.4, 79-122 drawn mobjects) and at or below
Original 2D's on 12 of 12. Three more frames are within +0.9 ms (2.h
+0.83, 4.b.2 +0.40, 4.d.9 +0.30). The deficit grows with the frame: +2.0
ms at 223-229 mobjects, +6.6-7.8 at 258-461, and +27.40 ms on the closing
8.a (531 mobjects), where the stage columns put it on the CPU:
`render_cpu_encode_ms` 24.05 against 7.14 (+16.9 ms; the patch fill
encodes 911 batches and 1840 scene draws for that frame against Phase A's
444 and 444), `serialize_ms` 26.95 against 19.63 (+7.3, of which prepare
is +2.0 and the wire encoding of twice the batches +5.3),
`submit_through_full_readback_ms` 9.38 against 7.63 (+1.75), and the
GPU's own span of the same frame +1.9 ms (attribution below). On the four
light bar-chart frames (4.c.1, 4.b.2, 4.b.4, 4.d.9) the patch fill is the
cheaper CPU side (prepare 1.31-1.94 against 1.52-2.27 ms, encode
0.61-0.77 against 1.46-1.99; 8-12 batches against 45-62) and the verdict
is set by the readback column's mode: the patch fill's readback landed in
the ~7.4 ms mode on all four while Phase A's landed in the ~4.5 mode on
4.b.2 and 4.d.9 (4.51, 4.53) and at 5.98 on 4.c.1, which is why two of
the four read +0.3-0.4 this pass and −0.1 to −3.0 in the first.

**PriceDiscovery (B3)**

| Frame | Checkpoint (line) | Beat | Drawn | Patch fill (A) | Phase A (A) | Δ p50 | Patch fill (B) | Original 2D (B) | Δ p50 |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0 | 9 (279) | 0.a | 148 | 14.11 / 11.38 | 14.24 / 11.46 | −0.13 | 11.59 / 9.80 | 32.67 / 32.36 | −21.08 |
| 1 | 19 (426) | 1.b | 155 | 12.30 / 9.58 | 13.39 / 10.97 | −1.09 | 9.80 / 9.20 | 26.62 / 25.89 | −16.82 |
| 2 | 35 (739) | 2.b.i | 206 | 14.65 / 11.21 | 15.17 / 12.45 | −0.53 | 11.82 / 11.19 | 36.45 / 35.86 | −24.63 |
| 3 | 48 (1179) | 3.a.1 | 199 | 18.19 / 17.91 | 15.74 / 12.70 | +2.44 | 15.46 / 15.00 | 40.36 / 39.64 | −24.89 |
| 4 | 58 (1179) | 3.a.3 | 215 | 19.51 / 18.88 | 17.20 / 13.71 | +2.31 | 16.34 / 16.01 | 70.11 / 69.57 | −53.76 |
| 5 | 68 (1179) | 3.a.5 | 233 | 20.39 / 17.43 | 17.96 / 17.73 | +2.42 | 17.36 / 17.21 | 53.62 / 53.03 | −36.26 |
| 6 | 86 (1179) | 3.a.8 | 235 | 21.57 / 20.53 | 19.15 / 16.15 | +2.43 | 17.40 / 16.72 | 52.90 / 52.31 | −35.49 |
| 7 | 98 (1179) | 3.a.10 | 212 | 17.45 / 17.02 | 17.01 / 14.01 | +0.44 | 14.37 / 14.17 | 51.91 / 51.23 | −37.54 |
| 8 | 109 (1179) | 3.a.12 | 245 | 20.87 / 20.55 | 18.64 / 15.24 | +2.23 | 17.95 / 17.59 | 57.32 / 56.96 | −39.37 |
| 9 | 115 (1215) | 3.b.1 | 222 | 17.80 / 14.94 | 17.52 / 14.31 | +0.28 | 14.94 / 14.55 | 56.33 / 55.77 | −41.39 |
| 10 | 123 (1236) | 3.b | 257 | 18.42 / 15.03 | 18.58 / 16.01 | −0.15 | 15.46 / 15.03 | 56.30 / 55.40 | −40.84 |
| 11 | 130 (1275) | 5.a | 184 | 13.84 / 10.80 | 14.04 / 11.11 | −0.20 | 11.36 / 11.17 | 19.37 / 16.25 | −8.02 |
| roll-up | median of frame medians | | | 17.99 | 17.11 | | 15.20 | 52.40 | |
| roll-up | worst frame median | | | 21.57 (frame 6) | 19.15 (frame 6) | | 17.95 (frame 8) | 70.11 (frame 4) | |
| roll-up | largest deficit | | | | | +2.44 (frame 3, 3.a.1, line 1179) | | | −8.02 (frame 11; every frame below) |

At or below Phase A on 5 of 12 frames (0, 1, 2, 10, 11: the opening,
1.b, 2.b.i, 3.b and the closing 5.a; three of the five by 0.13-0.20 ms,
inside the columns' noise) and at or below Original 2D on 12 of 12. The
deficits are +2.23-2.44 ms on five of the six 3.a beats (199-245
mobjects; 3.a.10 is +0.44) and sit in `render_cpu_encode_ms` (3.a.1: 3.57
against 1.98 ms, 302 scene draws against 87, 145 batches against 85;
`wire_encode_ms` 2.08 against 1.54; prepare 3.55 against 3.68, readback
7.55 against 7.34). On 1.b the patch fill has 23 batches to Phase A's 56
and is the cheaper side in prepare (2.30 against 2.59) and encode (1.11
against 1.80).

Cold first rows (archived, excluded): the patch fill's first frame of a
run compiles its pipelines (B2 0.a 661.3 ms against Phase A's 96.7; B3
0.a 488.7 against 59.8); the later restores are 16-446 ms (B2; the 446 is
Phase A on 5.a) and 29-57 ms (B3) for either variant, a seek's cost.

### (ii) Pixels

Fraction of pixels differing by more than 24 of 255 in any RGB channel,
and the largest single-channel difference; every pair the runs report
(`<a>_vs_<b>`, b the reference): `patch_vs_gpu_border` from gate A,
`patch_vs_original` from gate B. `patch_vs_cpu` was in no rotation. The
fractions and maxima are identical to the first pass's on every frame
(the renderers are deterministic on a restored frame).

| Episode | Frame | Beat | patch_vs_gpu_border % over 24 / max | patch_vs_original % over 24 / max |
| --- | --- | --- | ---: | ---: |
| B2 | 0 | 0.a | 0.000% / 0 | 0.028% / 118 |
| B2 | 1 | 2.h | 0.000% / 0 | 0.040% / 118 |
| B2 | 2 | 3.i | 0.000% / 21 | 0.114% / 118 |
| B2 | 3 | 4.c.1 | 0.000% / 10 | 0.049% / 143 |
| B2 | 4 | 4.b.2 | 0.000% / 0 | 0.083% / 97 |
| B2 | 5 | 4.b.4 | 0.000% / 0 | 0.082% / 97 |
| B2 | 6 | 4.return.5 | 0.000% / 0 | 0.083% / 145 |
| B2 | 7 | 4.return.7 | 0.000% / 0 | 0.083% / 162 |
| B2 | 8 | 4.d.9 | 0.000% / 10 | 0.085% / 109 |
| B2 | 9 | 4.h | 0.000% / 21 | 0.094% / 166 |
| B2 | 10 | 5.a | 0.000% / 0 | 0.064% / 79 |
| B2 | 11 | 8.a | 0.000% / 23 | 0.090% / 137 |
| B3 | 0 | 0.a | 0.000% / 0 | 0.009% / 110 |
| B3 | 1 | 1.b | 0.000% / 14 | 0.060% / 166 |
| B3 | 2 | 2.b.i | 0.000% / 19 | 0.269% / 208 |
| B3 | 3 | 3.a.1 | 0.000% / 24 | 0.070% / 123 |
| B3 | 4 | 3.a.3 | 0.000% / 24 | 0.097% / 168 |
| B3 | 5 | 3.a.5 | 0.000% / 24 | 0.119% / 168 |
| B3 | 6 | 3.a.8 | 0.000% / 21 | 0.072% / 138 |
| B3 | 7 | 3.a.10 | 0.000% / 18 | 0.066% / 142 |
| B3 | 8 | 3.a.12 | 0.000% / 21 | 0.085% / 151 |
| B3 | 9 | 3.b.1 | 0.000% / 18 | 0.083% / 142 |
| B3 | 10 | 3.b | 0.000% / 19 | 0.073% / 110 |
| B3 | 11 | 5.a | 0.000% / 27 | 0.030% / 86 |

Worst: B2 0.000% (max 23) against Phase A and 0.114% (frame 2, 3.i; max
166 on frame 9) against Original 2D; B3 0.000% (max 27) and 0.269%
(frame 2, 2.b.i, max 208). The attribution and live runs'
`patch_vs_gpu_border` pairs on their six frames, on the ticked
pausepoints and on the last measured frame of each play, are 0.000% as
well (max 28, B3 2.b). Every frame and pair of both episodes is under the
plan's 0.5%.

### (iii) Attribution: GPU pass time, flag set

Six frames, six samples after two warmups. Every measured frame of both
variants encodes exactly two passes, `out` and `resolve`: no `borders`
pass (the restored frame's border sources are cached across rounds and
nothing regenerates), no `programs` or `nets` (the B2 and B3 switches
were unset; `PriceDiscovery` draws no `Surface` on these frames).
Columns as in the controls' table; the resolve pass is 0.360-0.365 ms
exclusive in every row, so the whole difference is the out pass. The
flag-on wall totals sit within 1.3 ms of the flag-off gate medians on the
shared frames (two stamped passes are below the flag's perturbation;
B2 0.a 34.94 against 33.60 and 27.13 against 26.68, 8.a 64.00 against
63.93 and 36.99 against 36.53; B3 within 0.5); they are not gate numbers.

**EpisodeB2**

| Frame | Checkpoint (line) | Beat | Variant | gpu_total p50 / min | excl out p50 (n) | excl resolve p50 (n) | gpu_sum p50 | readback p50 |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: |
| 0 | 12 (36) | 0.a | Patch fill | 5.224 / 5.067 | 4.792 (6) | 0.361 (6) | 9.156 | 1.69 |
| 0 | | | Phase A (GPU border) | 4.381 / 4.313 | 4.020 (6) | 0.361 (6) | 8.042 | 1.69 |
| 0 | | | patch − Phase A | +0.843 / +0.754 | +0.772 | +0.000 | | |
| 1 | 82 (363) | 3.k | Patch fill | 5.848 / 5.738 | 5.487 (6) | 0.361 (6) | 10.341 | 1.69 |
| 1 | | | Phase A (GPU border) | 4.551 / 1.254 | 4.188 (6) | 0.361 (6) | 8.339 | 1.67 |
| 1 | | | patch − Phase A | +1.297 / +4.484 | +1.299 | +0.000 | | |
| 2 | 127 (622) | 4.return.2 | Patch fill | 5.593 / 1.591 | 5.230 (6) | 0.362 (6) | 9.988 | 1.67 |
| 2 | | | Phase A (GPU border) | 4.946 / 4.550 | 4.269 (6) | 0.361 (6) | 8.852 | 1.68 |
| 2 | | | patch − Phase A | +0.647 / −2.959 | +0.961 | +0.001 | | |
| 3 | 170 (622) | 4.b.7 | Patch fill | 4.966 / 2.566 | 4.604 (6) | 0.361 (6) | 8.984 | 1.65 |
| 3 | | | Phase A (GPU border) | 4.767 / 1.768 | 4.406 (6) | 0.361 (6) | 8.989 | 1.66 |
| 3 | | | patch − Phase A | +0.199 / +0.798 | +0.198 | +0.000 | | |
| 4 | 251 (661) | 4.g | Patch fill | 6.884 / 6.459 | 6.521 (6) | 0.362 (6) | 12.374 | 1.69 |
| 4 | | | Phase A (GPU border) | 5.744 / 5.224 | 5.384 (6) | 0.363 (6) | 10.704 | 1.68 |
| 4 | | | patch − Phase A | +1.140 / +1.235 | +1.137 | −0.001 | | |
| 5 | 307 (1016) | 8.a | Patch fill | 6.753 / 6.393 | 6.392 (6) | 0.361 (6) | 11.701 | 1.70 |
| 5 | | | Phase A (GPU border) | 4.847 / 4.835 | 4.485 (6) | 0.361 (6) | 8.928 | 1.68 |
| 5 | | | patch − Phase A | +1.906 / +1.558 | +1.907 | +0.000 | | |

**PriceDiscovery (B3)**

| Frame | Checkpoint (line) | Beat | Variant | gpu_total p50 / min | excl out p50 (n) | excl resolve p50 (n) | gpu_sum p50 | readback p50 |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: |
| 0 | 9 (279) | 0.a | Patch fill | 4.596 / 4.428 | 4.231 (6) | 0.362 (6) | 8.426 | 1.67 |
| 0 | | | Phase A (GPU border) | 4.204 / 4.193 | 3.845 (6) | 0.361 (6) | 7.878 | 1.67 |
| 0 | | | patch − Phase A | +0.392 / +0.235 | +0.386 | +0.001 | | |
| 1 | 43 (879) | 2.b | Patch fill | 5.083 / 1.618 | 4.720 (6) | 0.362 (6) | 9.156 | 1.68 |
| 1 | | | Phase A (GPU border) | 4.563 / 1.463 | 4.201 (6) | 0.360 (6) | 8.414 | 1.67 |
| 1 | | | patch − Phase A | +0.520 / +0.155 | +0.519 | +0.002 | | |
| 2 | 63 (1179) | 3.a.4 | Patch fill | 4.651 / 2.574 | 4.290 (6) | 0.360 (6) | 8.379 | 1.68 |
| 2 | | | Phase A (GPU border) | 4.391 / 1.221 | 3.915 (6) | 0.361 (6) | 7.992 | 1.68 |
| 2 | | | patch − Phase A | +0.260 / +1.353 | +0.375 | −0.001 | | |
| 3 | 91 (1179) | 3.a.9 | Patch fill | 4.748 / 1.297 | 4.383 (6) | 0.360 (6) | 8.512 | 1.69 |
| 3 | | | Phase A (GPU border) | 4.425 / 4.293 | 3.936 (6) | 0.365 (6) | 8.022 | 1.68 |
| 3 | | | patch − Phase A | +0.323 / −2.996 | +0.447 | −0.005 | | |
| 4 | 112 (1180) | 3.a | Patch fill | 4.757 / 1.573 | 4.395 (6) | 0.360 (6) | 8.579 | 1.69 |
| 4 | | | Phase A (GPU border) | 4.357 / 4.277 | 3.923 (6) | 0.363 (6) | 7.966 | 1.67 |
| 4 | | | patch − Phase A | +0.400 / −2.704 | +0.472 | −0.003 | | |
| 5 | 130 (1275) | 5.a | Patch fill | 4.934 / 2.820 | 4.522 (6) | 0.364 (6) | 8.774 | 1.66 |
| 5 | | | Phase A (GPU border) | 4.151 / 4.144 | 3.789 (6) | 0.362 (6) | 7.684 | 1.68 |
| 5 | | | patch − Phase A | +0.783 / −1.324 | +0.733 | +0.002 | | |

On B2 the GPU span is +0.2 to +1.9 ms for the patch fill on all six
frames, rising with the frame like the wall deficit but a small part of
it (8.a: +1.9 of +27.4). On B3 it is +0.26 to +0.78 ms on all six. Minima
of 1.2-2.8 ms on rows whose medians are 4.4-5.6 ms occur for both
variants (eleven rows here: four on B2, seven on B3) and are clock excursions, not floors; where
both variants' minima are excursion-free the minimum difference agrees
with the median difference (B2 0.a +0.75 against +0.84, 4.g +1.24
against +1.14, 8.a +1.56 against +1.91; B3 0.a +0.24 against +0.39).
`gpu_sum` exceeds `gpu_total` by 3.7-5.5 ms on every row: at these frame
sizes the resolve pass's begin-to-end is almost the whole out pass, the
overlap the scope note describes.

### (iv) Live frames: updaters ticked and the plays, flag unset

Six frames, 12 samples after 3 warmups. On a pausepoint whose mobjects
have updaters (`should_update_mobjects`: B2 3.k and 8.a; B3 every frame
but 5.a) every round is preceded by `scene.update_mobjects(1/fps)`, as
the idle loop ticks them; a frame without updaters repeats the static
redraw. The play into each pausepoint is replayed at `camera.fps` and its
middle frames sampled, one rotation of the variants per frame (α is the
range measured; the count is the play's frames, of which up to 12 are
measured after 3 warmups).

**EpisodeB2**

| Frame | Checkpoint (line) | Beat | Updaters ticked | Pausepoint patch / Phase A p50 | Δ p50 | Play α (play frames) | Play patch / Phase A p50 | Δ p50 |
| --- | --- | --- | --- | ---: | ---: | --- | ---: | ---: |
| 0 | 12 (36) | 0.a | no updaters | 33.84 / 27.17 | +6.67 | 0.27–1.00 (15) | 43.61 / 41.53 | +2.08 |
| 1 | 82 (363) | 3.k | yes | 34.86 / 24.07 | +10.79 | 0.27–1.00 (15) | 35.58 / 25.70 | +9.88 |
| 2 | 127 (622) | 4.return.2 | no updaters | 21.11 / 19.72 | +1.40 | 0.33–1.00 (12) | 50.58 / 37.49 | +13.09 |
| 3 | 170 (622) | 4.b.7 | no updaters | 11.81 / 13.89 | −2.08 | 0.44–1.00 (9) | 12.24 / 16.47 | −4.22 |
| 4 | 251 (661) | 4.g | no updaters | 36.02 / 27.76 | +8.26 | 0.27–1.00 (15) | 39.11 / 30.63 | +8.48 |
| 5 | 307 (1016) | 8.a | yes | 100.50 / 47.77 | +52.73 | 0.36–0.84 (23) | 209.14 / 106.74 | +102.40 |

**PriceDiscovery (B3)**

| Frame | Checkpoint (line) | Beat | Updaters ticked | Pausepoint patch / Phase A p50 | Δ p50 | Play α (play frames) | Play patch / Phase A p50 | Δ p50 |
| --- | --- | --- | --- | ---: | ---: | --- | ---: | ---: |
| 0 | 9 (279) | 0.a | yes | 14.21 / 14.24 | −0.03 | 0.27–1.00 (15) | 15.64 / 15.43 | +0.21 |
| 1 | 43 (879) | 2.b | yes | 13.76 / 14.80 | −1.05 | 0.27–1.00 (15) | 34.18 / 38.85 | −4.66 |
| 2 | 63 (1179) | 3.a.4 | yes | 24.29 / 19.70 | +4.58 | 0.44–1.00 (9) | 27.08 / 20.14 | +6.94 |
| 3 | 91 (1179) | 3.a.9 | yes | 24.67 / 20.22 | +4.45 | 0.44–1.00 (9) | 29.10 / 20.68 | +8.42 |
| 4 | 112 (1180) | 3.a | yes | 18.26 / 18.12 | +0.14 | 0.53–1.07 (8) | 25.45 / 19.78 | +5.67 |
| 5 | 130 (1275) | 5.a | no updaters | 14.95 / 14.78 | +0.17 | 0.27–1.00 (15) | 26.01 / 31.84 | −5.84 |

B2: at or below Phase A on 1 of 6 pausepoints (4.b.7) and 1 of 6 plays
(4.b.7). The closing 8.a with its updaters ticking is 100.50 against
47.77 ms (+52.7: prepare 50.24 against 25.77, wire encode 11.69 against
4.47, encode 24.59 against 7.21, readback 9.38 against 7.71) and its play
209.14 against 106.74 (+102.4: prepare 88.57 against 77.29, wire encode
14.97 against 5.11, encode 71.84 against 13.12, readback 23.19 against
9.19); 3.k ticking is +10.79 (prepare 11.73 against 8.95, encode 8.38
against 3.97) and the 4.return.2 play +13.09 (prepare 23.68 against
10.71 with encode equal at 11.7). B3: at or below on 2 of 6 pausepoints
(0.a by 0.03, 2.b) and 2 of 6 plays (2.b, 5.a); the largest deficits are
+4.58 ms on 3.a.4 ticking (prepare 7.66 against 5.74, encode 4.43 against
2.55) and +8.42 on the 3.a.9 play (prepare 10.89 against 6.08, encode
5.43 against 3.51). On the two B3 plays the patch fill wins (2.b −4.66,
5.a −5.84) Phase A's encode and readback rise mid-play (12.58 and 10.44
ms on the 2.b play against the patch fill's 4.70 and 8.05; 9.24 and 10.16
against 2.61 and 7.70 on 5.a) while its prepare stays below the patch
fill's (10.62 against 18.52). Over every measured live row: B2
pausepoints 33.84 against 25.89 ms and plays 42.77 against 33.49; B3
16.74 against 15.20 and 26.02 against 21.02.

### Gate reading

As the plan states it (`docs/phase_b_plan.md`, "Decided before the
start"), "complete frame at or below Phase A" on the episode and at most
0.5% of pixels over 24/255:

- **EpisodeB2:** the patch fill's complete-frame median is at or below
  Phase A's on 2 of 12 pausepoint frames (4.c.1, 4.b.4); the largest
  deficit is +27.40 ms on frame 11 (8.a, line 1016), and on the live rows
  +52.7 ms (8.a, updaters ticking) and +102.4 ms (the 8.a play). Pixels:
  0.000% against Phase A and 0.114% at worst against Original 2D, under
  0.5% on every frame.
- **PriceDiscovery (B3):** at or below on 5 of 12 pausepoint frames (0.a,
  1.b, 2.b.i, 3.b, 5.a); the largest deficit is +2.44 ms on frame 3
  (3.a.1, line 1179), and on the live rows +4.58 ms (3.a.4 ticking) and
  +8.42 ms (the 3.a.9 play). Pixels: 0.000% against Phase A and 0.269%
  at worst against Original 2D, under 0.5% on every frame.
- Against Original 2D the patch fill is at or below on 12 of 12 frames
  of both episodes (Original 2D's frame at 2160x1080 is 2-3x longer; its
  readback column is 6-68 ms).

### Replication: the first pass against this one

Same commands, sources and load class, 51 minutes apart
(`episodes.first_pass`, `episodes.replication`). What held: every frame
whose difference the CPU stage columns account for kept its sign and
size within 0.4 ms (B2 0.a +6.83 → +6.93, 3.i +6.88 → +6.66,
4.return.5/7 +2.07/+1.80 → +2.04/+2.01, 4.h +7.84 → +7.76, 5.a +6.75 →
+6.60, 8.a +27.77 → +27.40, 4.b.4 −1.94 → −1.88; B3's five 3.a deficits
+2.14-2.46 → +2.23-2.44); the live rows (B2 8.a +52.5/+106.8 →
+52.7/+102.4, 3.k +10.55 → +10.79; B3 3.a.4 +5.10 → +4.58, 3.a.9 play
+7.05 → +8.42, counts 1 of 6 / 1 of 6 and 2 of 6 / 2 of 6 in both
passes); the GPU attribution (B2 +0.9 to +2.1 → +0.2 to +1.9, B3 −0.6 to
+1.3 → +0.26 to +0.78, the out pass in every row); the pixels, to the
digit. What moved is the light frames, complete frames of 8-15 ms whose
CPU stages differ between the variants by under 1.5 ms: seven of them
moved by 0.2-3.3 ms between passes (B2 4.c.1 −1.84 → −0.11, 4.b.2 −0.12
→ +0.40, 4.d.9 −3.03 → +0.30; B3 0.a +0.09 → −0.13, 1.b +0.85 → −1.09,
2.b.i −3.13 → −0.53, 5.a +0.04 → −0.20), and five of them changed the
verdict, taking the count of frames "at or below" from 4 of 12 to 2 of
12 on B2 and from 2 of 12 to 5 of 12 on B3. On all seven, prepare and
encode agree between passes within 0.1 ms for both variants; what
changed is which readback mode each variant's median landed in, a step
of ~3 ms (B2 4.d.9 Phase A 7.51 → 4.53, 4.c.1 patch fill 5.26 → 7.36; B3
1.b Phase A 4.53 → 6.69, 2.b.i patch fill 4.51 → 7.47), the quantized
wait the Scope section describes. So on this harness a per-frame median
difference is a cost where the CPU stage columns or `gpu_total_ms`
account for it and a readback-mode draw where they do not; the count of
frames "at or below" is sensitive to the draws, and the two passes agree
on every frame whose difference has a cost behind it.

### Scope of the episode rows

- Measured: the native `WgpuRenderer` mirror at 2160x1080 with a full
  RGBA readback per sample; static pausepoint redraws on twelve frames,
  updater-ticked pausepoints and mid-play frames on six; two variants
  rotating per frame. Not measured: the browser driver (accepted
  exclusion), the cold rows (archived, excluded), the pausepoints the
  thinning skipped, `patch_vs_cpu` (CPU-border Phase A in no rotation),
  and any B2 or B3 switch (`MANIML_SURFACE` and `MANIML_PROGRAMS` unset;
  the patch fill ran alone, as the gate names it).
- The gate tables are static redraws at pausepoints, which understates
  the CPU work where the two renderers differ; the live section is the
  measurement of that work on six frames per episode, and its deficits
  are larger than the gate tables' on the same frames.
- `submit_through_full_readback_ms` is readback-dominated here as on the
  controls (~4.5 and ~7.5 ms modes for both generated variants); the
  complete-frame differences between the patch fill and Phase A on these
  episodes are in `render_cpu_encode_ms` and `serialize_ms`, scale with
  the batch and draw counts, and the GPU columns (flag on, a separate run)
  put the GPU's share at +0.2 to +1.9 ms per frame. A per-frame median
  difference between the variants can be a change of readback mode, a
  step of ~3 ms, rather than a cost (Replication above: light frames
  moved by up to 3.3 ms between passes with their CPU stages unchanged);
  when comparing variants at this resolution read `gpu_total_ms` and the
  CPU stage columns.
- `gpu_total_ms` excludes the readback copy's GPU time and command-buffer
  scheduling; the timing readback is the one extra submission after the
  frame's readback (`timing_submissions`, asserted to be exactly one per
  instrumented frame), `gpu_readback_ms` 1.65-1.70 ms here, outside every
  wall-clock column and outside `post_readback_ms`.
- The GPU clock caveat applies unchanged: the period is a fixed
  nanosecond clock and pass durations follow the M3's clock state, which
  follows the machine's load; minima at 1.2-2.8 ms under 4.4-5.6 ms
  medians are excursions, not floors; nothing here is compared with the
  controls' `gpu_` columns, which were taken under a different load, and
  the two episode passes' `gpu_` columns are set beside each other only
  because both ran at the same 0-12% baseline.
- Twelve samples per frame: per-frame medians of two variants within
  ~0.5 ms of each other (B2 4.b.2, 4.d.9; B3 0.a, 3.a.10, 3.b.1, 3.b, 5.a)
  are not resolved by this sample size, and the count of frames "at or
  below" treats a +0.1 as above and a −0.1 as at or below, as the plan's
  wording does; Replication says how many of them moved.
- The `--max-frames 6` runs' frames are the harness's even thinning, not
  named beats; the heaviest frame of each episode (the last pausepoint)
  is in every run because the thinning keeps the last.

## Files

- `README.md`: this file.
- `summary.json`: the quiet pass's three tables (`gate`, `pixels`,
  `attribution`, `probe`, the differences, the still text stage columns,
  its sorted readback and `gpu_total_ms` values, the cold frames), the
  commands, run wall times, machine, commit, flag state per run, the GPU
  load samples and their reading (`gpu_load_note`), the loaded first
  pass's still text headline and load samples (`superseded_first_pass`),
  the source hashes and the reports' scope strings; `episodes` holds the
  two episodes' second pass (commands, flag state, wall times, load
  samples, per-frame gate, stage, batch and draw, pixel, attribution and
  live numbers, roll-ups, the gate reading and the episode reports' scope
  strings), `episodes.first_pass` the first pass's per-frame medians and
  roll-ups, and `episodes.replication` the two set side by side.
- `attribution_report.json`: the quiet pass's attribution run, its full
  report (every row, the raw pass lists, cold rows, per-frame pixel
  diagnostics); the first pass's is not kept.

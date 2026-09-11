# Text parity plan: closing the zoom-step gap to Original 2D

Written 2026-09-10 after the revision-keyed cache landed; options 1 to 3
below landed the same evening (Taylor: "ok do the leftover fix"). The
outcome is in the response document's "The zoom-step leftover" section:
zoom-step preparation 4.7 ms to 2.1 ms, and the harness numbers there. What
remains on a zoom step is real mesh refinement and the re-assembly of the
coalesced run when any glyph regenerates; both go away only when fills stop
depending on zoom, which is Phase B's question. Kept for the measurements
and the reasoning.

## Where the gap is

Same harness as the seventh round (`benchmarks.gpu_borders`, 101-glyph TeX,
Apple M3), warmed medians in ms, after the revision-keyed cache:

| Stage | Phase A, static | Original 2D, static | Phase A, 5% zoom step | Original 2D, 5% zoom step |
| --- | ---: | ---: | ---: | ---: |
| CPU preparation | 1.49 | 2.34 | 4.77 | 2.40 |
| Wire encode + parse | 0.14 | 0.69 | 0.14 | 0.70 |
| Driver CPU encode | 0.28 | 0.43 | 0.44 | 0.43 |
| GPU submit through readback | 2.95 | 1.64 | 3.02 | 1.66 |
| Post-readback | 0.34 | 0.34 | 0.37 | 0.35 |
| **Complete frame** | **5.26** | **5.58** | **8.89** | **5.75** |

Native GL, for scale: 7.9 ms on both controls.

So on a still frame Phase A is already ahead. On a zoom step it loses
2.4 ms on the CPU, and appears to lose 1.4 ms on the GPU; the experiment
below shows the GPU figure is a harness artifact, so the CPU part is the
whole problem.

### The CPU part: per-object work that depends on the camera

A profile of the 5% zoom step (20 frames, `cProfile`, shares of preparation
time) at 101 objects:

| Work, once per object per frame | Share | What it is |
| --- | ---: | --- |
| Pixel-error bound of the cached mesh | ~25% | `projection_scale_bound` per entry: does the retained mesh still meet tolerance at this zoom? Numpy on tiny arrays, 101 times. |
| Border source re-read at the new scale | ~30% | `BorderSource.read` recomputes each curve's step count from density and frame scale, then the cache replaces the entry with a fresh frozen copy of every array, reserves capacity again and re-accounts bytes. The packed curves are reused; everything around them is rebuilt. |
| Mesh regeneration for refinement | ~10% | Real work: about five glyphs per frame cross the tolerance and re-tessellate. |
| Coalescing and run assembly | ~8% | The run's concatenated fill vertices and indices are rebuilt because the border sources changed identity. |
| Wire identity hash | ~5% | The rebuilt run array is hashed again although its parts did not change. |
| Uniform merge, classification, loop overhead | ~20% | The same walk an unchanged frame pays. |

Each row is a Python-level loop over objects doing a few microseconds of
numpy per object. At 101 glyphs that is 4.8 ms; at a paragraph of 400 it is
proportionally worse, which is the real reason to fix it rather than the
harness number.

### The GPU part: the AA policy and the compute pass

Phase A draws at twice the final width and height with 4× MSAA and then
resolves, eight samples per final pixel, plus a stencil-owned border pass
and, on a zoom step, the border compute dispatch. Original 2D draws its
winding fills on a 2× pixel grid without MSAA. The AA choice was deliberate
(`DECISIONS.md`, "Phase A is shared"): predictable fill quality and the
zero-border AA gate. The experiment below separates the two factors.

AA cost experiment (`submit_through_full_readback`, same frame, ms):

| AA configuration | Static frame p50 (min) | 5% zoom step p50 (min) |
| --- | ---: | ---: |
| 4× MSAA + 2× supersample (the default) | 2.93 (1.55) | 1.58 (1.56) |
| 4× MSAA only | 1.64 (1.57) | 1.64 (1.59) |
| 2× supersample only | 1.58 (1.37) | 1.62 (1.46) |
| Neither | 1.64 (1.54) | 1.65 (1.54) |

Measured with Phase A alone, twelve samples after three warmups, native
`WgpuRenderer`. The AA policy costs nothing measurable at this scene size:
every configuration completes in about 1.6 ms, the same as Original 2D's
1.66 ms in the harness. The one larger median is the readback's known
bimodal completion (roughly 1.5 ms or 12 ms), which is why minimums are
shown beside it. The harness's 3.0 ms for Phase A is therefore not GPU
work: the harness alternates four renderers every frame, and Phase A's
readbacks land on the slow side of that bimodal distribution 83% of the
time there (`readback_distribution` in the archived report) against 17% in
isolation. Until the harness can run two variants alone, treat the GPU
column as unresolved rather than as a Phase A cost.

## Options

Ordered by expected payoff per day. Estimates assume the harness numbers
above; every one needs the same before/after run and the pixel checks.

**1. Batch the camera-dependent checks across objects (one to two days).**
Compute the pixel-error bound for every cached entry in one vectorized
call per frame instead of one call per entry: stack the retained hulls,
project once, compare against tolerance once. Do the same for border step
counts: one `_density_counts` over the concatenation of every source's
densities, sliced back per object. Expected: the two rows above (~55% of
preparation) drop to a few hundred microseconds; zoom step preparation from
4.8 ms to roughly 2.5 ms; complete frame near 6.6 ms, inside the 25% gate.
Risk: low, the arithmetic is unchanged and the pixel comparisons prove it.

**2. Stop rebuilding the border entry on a scale change (half a day).**
A step count is a pure function of a source's densities and the frame
scale. Keep the frozen source once and attach counts per frame scale to it
rather than replacing the entry, its frozen copies, its capacity
reservation and its byte accounting. This also keeps the run assembly and
its identity hash stable across zoom steps, which removes the coalescing
and hashing rows. Expected: another ~0.5 ms. Folds naturally into option 1.

**3. Make the harness able to compare two renderers alone (half a day).**
Add `--variants` to `benchmarks.gpu_borders` so Phase A and Original 2D can
alternate without the CPU-border and GL variants between them, and report
the readback distribution beside the median as the measurement rules
already require. If the isolated 1.6 ms holds there, the GPU column is
closed and no AA decision is needed. The AA policy stays as decided unless
that run says otherwise.

**4. Leave the per-object walk alone until Phase B.** The last row is what
any Python-side renderer pays per object; the instruction-stream
architecture removes the walk rather than shrinking it. Do not spend a week
on it now.

## Recommendation

Do options 1 and 2 together as one change with one measurement, and
option 3 first so that measurement is trustworthy. If 1 and 2 land as
estimated and the GPU column closes as the isolated experiment predicts,
the repeated-zoom control lands within a few percent of Original 2D with
the AA policy untouched; the remaining difference would be the per-object
walk that only Phase B removes.

## What this does not cover

Text with many more glyphs (the course's paragraph slides), which scales
the per-object rows; a real course scene through the live viewer, where the
browser's own frame time applies; and the zero-border AA gate, which stays
open regardless.

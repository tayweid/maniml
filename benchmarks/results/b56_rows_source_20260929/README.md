# Rows as the patch source (2026-09-29)

B5.6 (`docs/phase_b4_plan.md`, "The flips"): `geometry.DEFAULT_PATCH_SOURCE`
is `rows`, so wherever patches are drawn (the forced Phase B the viewer's
selection draws, and any stack that selects `MANIML_FILL=patches`) a path is
sent as its rows unless `MANIML_PATCH_SOURCE=records` says otherwise. This
archive holds the proof that the pixels did not move and that the golden
pin held untouched, what the new default costs natively, the final test
point (B6) retaken with the selection's Phase B beside B6's, and why a
navigation costs more.

From `/Users/taylorjweidman/Projects/ManimLive/maniml-b4i` (branch
`b4-integration`, parent `4d5f0964`), interpreter `maniml/.venv/bin/python`
(Python 3.13.9, wgpu 0.32.0, numpy 2.5.2), Node 22.16, Apple M3, Metal,
macOS 26.6.2, one run at a time, `MANIML_GPU_TIMESTAMPS` unset but for the
test point's two attribution runs. `$E` is a tree of links in which both
episodes resolve (`Blocks/B2_Supply`, `Blocks/Sim` and `Blocks/_Assets`
linked from econ-0100, and `Blocks/B3_Equilibrium/Animate.py` linked to its
`_archive/Animate.py`), as B5.1 and B6 measured them.

## Pixels, and the pin

```bash
MANIML_EPISODES=$E python benchmarks/results/b56_rows_source_20260929/golden_pixels.py <out>.json
PYTHONPATH=. python benchmarks/results/b56_rows_source_20260929/episode_pixels.py $E/Blocks/B2_Supply/03_Code.py EpisodeB2 307
PYTHONPATH=. python benchmarks/results/b56_rows_source_20260929/episode_pixels.py $E/Blocks/B3_Equilibrium/Animate.py PriceDiscovery 63
```

- The golden pin was not re-recorded. It states
  `MANIML_PATCH_SOURCE=records` (`GoldenCase`), as its phase_b digests were
  recorded, so every golden passes untouched. `golden_pixels.py` runs the
  pin's golden classes (fixtures, quality fixtures, synthetic cases, both
  episodes: 36 cases) with, beside each phase_b cache, a shadow cache
  serializing the same scene at the same moment with the patch source taken
  out of the environment, as the viewer's selection sends it (rows); two
  native drivers of their own draw the two sequences in order.
  `golden_pixels.json`: 251 phase_b frames, every records frame's digest
  the pin's (251), the rows frames' bytes other on 246 (the five that are
  not are the textures case: an image and a textured surface, no path),
  the largest channel difference 0 on every frame; the eight golden tests
  pass. (A first pass of B5.6 re-recorded the 246 digests for rows; the
  review sent it back, and the four golden files are 4d5f0964's.)
- `episode_pixels.py` is B5.1's comparison, unchanged: every pausepoint of
  an episode and its gate play under the forced Phase B, records then rows,
  one driver and one cache each. `pixels_B2.txt`: 84 pausepoints and 23
  play frames; `pixels_B3.txt`: 24 and 9; largest channel difference 0
  everywhere.
- The test point's `frames_b` runs (below) carry the pair
  `phase_b_vs_records`: largest channel difference 0 on EpisodeB2's twelve
  pausepoints and 139 play frames and PriceDiscovery's twelve and 124
  (`test_point/*_pixels.txt`).

## What it costs natively

```bash
PYTHONPATH=. python benchmarks/results/b56_rows_source_20260929/complete_frame.py $E/Blocks/B2_Supply/03_Code.py EpisodeB2 307 6 0
PYTHONPATH=. python benchmarks/results/b56_rows_source_20260929/complete_frame.py $E/Blocks/B3_Equilibrium/Animate.py PriceDiscovery 63 6 0
PYTHONPATH=. python benchmarks/results/b56_rows_source_20260929/seek_frames.py $E/Blocks/B2_Supply/03_Code.py EpisodeB2 4
PYTHONPATH=. python benchmarks/results/b56_rows_source_20260929/seek_frames.py $E/Blocks/B3_Equilibrium/Animate.py PriceDiscovery 4
python -m benchmarks.browser_frames --scene $E/Blocks/B2_Supply/03_Code.py EpisodeB2 \
    --variants phase_b phase_b_rows --realm main --rounds 5 --output <d>
```

`complete_frame.py` is B5.1's (the play into a pausepoint, serialize and
native `render()` through its readback, the sources alternating replay by
replay, six replays each); `seek_frames.py` walks the twelve measured
pausepoints (`episode_frames.select_frames`) in order, each restored and
drawn, then drawn again as a still, four rounds a source, the sources
alternating round by round and each keeping its cache and driver across its
rounds (so most of its navigations revisit). Each frame's median over its
replays or rounds, then the median over the frames (`native.json`, with
each sample's minimum beside it; the GPU at 0% at every start, load
1.4-2.1):

| Forced Phase B, native, ms | records | rows |
| --- | ---: | ---: |
| 8.a play, complete (serialize + render) | 196.5 (104.1 + 92.2) | 160.1 (52.1 + 107.9) |
| PriceDiscovery 3.a.4 play | 27.4 (5.7 + 21.7) | 28.3 (5.8 + 22.4) |
| EpisodeB2, a navigation to a pausepoint | 29.9 (7.4 + 22.1) | 38.3 (6.8 + 31.1) |
| PriceDiscovery, a navigation to a pausepoint | 25.0 (6.4 + 17.7) | 28.8 (6.3 + 21.5) |
| EpisodeB2, the next still frame | 13.0 | 11.8 |
| PriceDiscovery, the next still frame | 11.6 | 11.1 |

A navigation's message is 681 → 390 KB (EpisodeB2) and 397 → 261 KB
(PriceDiscovery). The page's JavaScript on EpisodeB2's twelve pausepoints
walked without their plays (`browser_pausepoints_B2.md`, the fake device,
main realm, five rounds): a restored pausepoint's first frame 2.08 → 2.87
ms at the median (8.a 8.89 → 9.27), uploads 1441 → 1052 KB, bind groups
168 → 308, buffers 336 → 618; its still frames 0.05 ms either way.

## The test point, retaken

`test_point/campaign.sh b2 b3`: B6's recipe (`benchmarks/README.md`, "The
test point") with five stacks, the forced Phase B as the selection sends it
(`phase_b`: rows) and `phase_b_records` beside it (B6's Phase B), per
episode `frames_a`, `frames_b`, `gpu1`, `browser`, `page`, `serialize`,
`gpu2` and `table`; the instrumented `python` run was left out. 01:59-02:25
local, every run starting with the GPU at 0% (`ioreg`, three samples; one
23% sample was taken as PriceDiscovery's `frames_b` ended) and the
one-minute load 1.45-3.60 (`test_point/conditions.log`). `today` is
`main`'s page, 0a2bf3b2, as in B6. The tables are
`test_point/episode_b2_table.md` and `price_discovery_table.md` (their JSON
beside them); per checkpoint, `*_phase_b_by_checkpoint.txt`
(`phase_b_by_checkpoint.py` over the table's report); the page per class,
`*_browser_phase_b.txt` (`browser_phase_b.py` over the browser run's
summary).

Complete frame (serialize + page + GPU), records → rows, ms; the medians
per class as the test point reads them:

| | EpisodeB2, format 8 | EpisodeB2, format 7 | PriceDiscovery, format 8 | PriceDiscovery, format 7 |
| --- | ---: | ---: | ---: | ---: |
| pausepoint | 0.68 → 0.75 | 5.17 → 5.19 | 0.62 → 0.69 | 5.51 → 5.58 |
| ticked | 3.22 → 3.48 | 7.46 → 7.96 | 0.98 → 1.04 | 5.62 → 5.70 |
| play | 8.86 → 8.97 | 9.18 → 9.35 | 10.93 → 10.63 | 10.77 → 10.45 |
| today (main), for scale | 10.96 / 27.91 / 19.98 | | 8.05 / 11.49 / 11.93 | |

- A still or ticked frame's serialize is higher with rows on every
  measured checkpoint of both episodes, 0.03-0.19 ms and 0.40 ms on 8.a
  ticking (format 8 sends nothing there, so that is the frame); the cause
  was not isolated.
- The plays split by what moves. 8.a's play, whose movers are not programs,
  is 127.25 → 80.52 ms in format 8 (serialize 105.21 → 51.91, page 4.30 →
  4.48, GPU 17.75 → 24.13) and 127.25 → 79.54 in format 7. The other
  plays, whose movers are programs, are within ±0.8 ms, but for three short
  ones whose GPU part moved 1.7-1.9 ms, two down and one up (EpisodeB2's
  103 and 140, PriceDiscovery's 115, six to eight frames each);
  PriceDiscovery's GPU part is 0.23 ms lower at the class median.
- The first message after a restore (`browser_frames`' `cold`, one per
  checkpoint, after the play into it), records → rows: the page's
  JavaScript 2.32 → 2.68 ms (format 8) and 3.24 → 2.48 (format 7) on
  EpisodeB2, 1.56 → 1.73 and 1.72 → 1.83 on PriceDiscovery; the recording's
  serialize 27.26 → 18.74 and 17.09 → 11.03 ms (format 8); the wire 898 →
  380 KB and 407 → 308 KB; the page's compute dispatches 73 → 206 and 26 →
  107, bind groups created 218 → 338 and 78 → 164, buffers 429 → 630 and
  231 → 398. The recipe has no GPU row for it; `seek_frames.py` above has
  the native render.
- Pixels against Phase A without the retained frame, the same for both
  sources: EpisodeB2 0.0000% in every class (worst channel 21 / 23 / 30);
  PriceDiscovery 0.0000% (27) at the pausepoint and 0.0412% (142) ticked
  and in plays. B6's PriceDiscovery play figure, 2.024% (153), predates
  c787d9d1's fix of the program sources' base points.

## Why a navigation costs more

```bash
PYTHONPATH=. python benchmarks/results/b56_rows_source_20260929/navigation_cache.py $E/Blocks/B2_Supply/03_Code.py EpisodeB2 258,277,157
PYTHONPATH=. python benchmarks/results/b56_rows_source_20260929/navigation_resends.py $E/Blocks/B2_Supply/03_Code.py EpisodeB2 258 277
```

Two causes, not one. Each driver finalizes every changed rows with a
dispatch of its own (B5.1's negative), and a path's rows carry its paint
(stroke and fill RGBA) and are keyed by content with it, so a change of
paint alone resends and refinalizes them and the batch is no longer cached,
where under records the curve records stay cached and only the object
table changes. Under the forced Phase B, format 7, one cache per source
(`navigation_cache_B2.txt`): 258 → 277 (5.a) sends 463 batches, 176 of them
cached under records and 0 under rows; 277 → 157, 142 batches, 68 against
0. Of the rows 277 re-sends that the receiver did not hold, 590 are a rows
sent at 258 point for point but for stroke_rgba and fill_rgba (alpha 1.0 →
0.05: a dim) (`navigation_resends_B2.txt`). One dispatch for a frame's rows
removes the dispatches, not the resends or the finalizes; keying the
finalized geometry on the geometry columns and taking the colour from the
object table or the paint, as records do, is the second lever.

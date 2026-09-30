# A frame's rows in one dispatch, keyed on their geometry (2026-09-29)

B5.8 (`docs/phase_b4_plan.md`, "The flips"): each driver finalizes a
frame's changed row sources in one dispatch of `row_finalize_table.wgsl`
(one per 32 MiB region past that), and a path's rows travel as their
geometry (nine columns, keyed on them alone) and their paint (eight, one
row where uniform), so a change of paint alone sends the paint. This
archive holds what it costs against the records packed and against B5.6
(`../b56_rows_source_20260929/`), the pixels, and what is known and not
known about the navigation's page JavaScript, which still reads above
records.

From `/Users/taylorjweidman/Projects/ManimLive/maniml-b5` (branch
`b5-loose-ends`, parent `5c16c898`), interpreter `maniml/.venv/bin/python`
(Python 3.13.9, wgpu 0.32.0), Node 22.16, Apple M3, Metal, macOS 26.6.2,
`MANIML_GPU_TIMESTAMPS` unset but for the attribution runs. `$E` is B5.6's
tree of links in which both episodes resolve.

**Two campaigns, and how quiet the GPU was.** The recipe
(`benchmarks/README.md`, "The test point") asks for one run at a time on a
quiet GPU, and B5.7 waited for three ioreg samples at or below 10% before
each run. Neither campaign here fully could: the desktop apps kept the GPU
12-44% busy for long stretches, and only some runs started quiet.

- **The first** (`test_point/`, 17:28-17:59, on AC power; a first attempt
  at 16:11 was abandoned when the machine went to battery) waited for
  nothing: the GPU was 19-41% busy at every run's start
  (`test_point/conditions.log`), and PriceDiscovery's second attribution
  run overlapped about 40 s of CPU-only Node replays. Its tree
  (`test_point/tree.sha`) is this one but for two review fixes made after
  it (the planner's budget boundary, a null `row_paints`), neither on a
  path these episodes take.
- **The retake** (`retake/`, the fix pass after review): the same recipe,
  every run first waiting up to two minutes for three samples at or below
  10% (`retake/campaign_quiet.sh`, `wait_quiet.py`), then the native
  navigation in three more passes of eight rounds an episode and the plays'
  GPU attribution with records and rows alternating replay by replay.
  EpisodeB2's test point (19:15-19:51) started quiet only its first run,
  the rest after the wait gave up at 12-23%; PriceDiscovery's
  (21:13-21:40) its first and its table, the rest at 17-29%. The native
  navigation's three passes on EpisodeB2, the two plays' attribution runs,
  and PriceDiscovery's four-round navigation and play started quiet;
  PriceDiscovery's three eight-round navigation passes started at 13-44%
  (`retake/conditions_*.log`; `gpu_*.log` samples every 5 s, our own runs
  included). Its tree is the one committed (`retake/tree.sha`).

The GPU's clock follows the load, so GPU parts are compared only within a
run, where records and rows alternate frame by frame (`episode_frames`) or
replay by replay (`complete_frame.py`, `seek_frames.py`), never across runs:
records' own 8.a GPU part read 17.75 ms in B5.6's run, 24.22 and 22.04 in
these two.

## The test point

B6's recipe with B5.6's five stacks; tables `test_point/*_table.md` and
`retake/*_table.md` (JSON beside them), per checkpoint
`*_phase_b_by_checkpoint.txt`, the page per class `*_browser_phase_b.txt`,
pixels `*_pixels.txt` (B5.6's reducers).

Complete frame (serialize + page + native GPU), median per class,
`phase_b_records` → `phase_b` (rows), ms, the first campaign / the retake,
and B5.6's for comparison:

| EpisodeB2 | format 8 | format 7 |
| --- | ---: | ---: |
| pausepoint | 0.80 → 0.89 / 0.79 → 0.92 (B5.6 0.68 → 0.75) | 6.92 → 7.08 / 6.18 → 6.32 (5.17 → 5.19) |
| ticked | 3.58 → 3.96 / 3.64 → 4.02 (3.22 → 3.48) | 10.44 → 10.77 / 10.42 → 10.70 (7.46 → 7.96) |
| play | 11.83 → 12.60 / 12.47 → 12.65 (8.86 → 8.97) | 12.17 → 13.01 / 12.73 → 13.23 (9.18 → 9.35) |

| PriceDiscovery | format 8 | format 7 |
| --- | ---: | ---: |
| pausepoint | 0.78 → 0.84 / 0.77 → 0.89 (0.62 → 0.69) | 5.63 → 6.24 / 5.69 → 5.82 (5.51 → 5.58) |
| ticked | 1.21 → 1.26 / 1.17 → 1.29 (0.98 → 1.04) | 6.48 → 6.31 / 6.36 → 6.42 (5.62 → 5.70) |
| play | 12.26 → 11.78 / 12.07 → 12.06 (10.93 → 10.63) | 12.14 → 11.60 / 11.87 → 11.86 (10.77 → 10.45) |

Rows read above records in every EpisodeB2 class in both takes, as in
B5.6, and by more in its format 8 play (+0.77 and +0.18 ms, B5.6's +0.11)
and ticked frames (+0.38 in both, B5.6's +0.26). Part of it is the
serialize a mover pays for the split: the per-checkpoint format 8 play
serialize is 0.13-0.7 ms dearer at 12, 76, 258 and 277 in both takes. The
rest moves with the GPU part, which a median of few frames carries:
PriceDiscovery's format 7 pausepoint (one frame) read 5.63 → 6.24 in the
first take, 0.44 ms of it that frame's GPU part, and 5.69 → 5.82 in the
retake.

8.a's play in format 8, records → rows: 138.77 → **86.09** ms (serialize
109.82 → 60.12, page 4.73 → 4.57, GPU 24.22 → 21.41), retaken 136.92 →
**83.71** (110.26 → 59.41, 4.63 → 4.42, 22.04 → 19.87); format 7 137.81 →
85.24 and 136.10 → 83.06. B5.6: 127.25 → 80.52 (105.21 → 51.91, 4.30 →
4.48, 17.75 → 24.13). Within each run, rows' GPU part reads below
records' (by 2.8 and 2.2 ms here, where B5.6's read 6.4 ms above), and the
retake's attribution run with the two alternating replay by replay on a
quiet GPU agrees (`retake/native.txt`, `b2_play_stamps`: 23.81 → 22.90 ms,
the borders 19.61 → 18.72, the row finalize 0.06). Across runs nothing is
compared: 86.1 and 83.7 against B5.6's 80.5 are on a GPU whose records'
own play read 138.8 and 136.9 against 127.3. The serialize's cost against
B5.6's code is measured directly, below (4.2 ms a frame).

The whole native frame of the play (`complete_frame.py`, six replays
alternating): 210.1 → 151.8 ms and, retaken, 207.3 → 150.5 (render 100.0
→ 92.8 and 97.0 → 91.7; B5.6's rows rendered 15.7 ms above records).

Pixels, `phase_b_vs_records`: largest channel difference 0 on EpisodeB2's
twelve pausepoints and 139 play frames and PriceDiscovery's twelve and
124, in both takes.

## A navigation

**Native** (`seek_frames.py`: the twelve pausepoints walked, each restored
and drawn, then drawn again as a still, records and rows alternating round
by round; each frame's median over its rounds, then over the frames;
`native/native.txt`, `retake/native.txt`), the complete frame records →
rows, ms:

| pass | EpisodeB2 | PriceDiscovery |
| --- | ---: | ---: |
| first campaign, 4 rounds | 35.67 → 34.66 | 26.88 → 27.09 |
| 18:13, 8 rounds (GPU 10-19%) | 34.18 → 33.13 | 25.32 → 25.75 |
| retake, 4 rounds | 35.07 → 33.42 | 30.49 → 29.78 (quiet) |
| retake, 8 rounds, pass 1 | 34.33 → 32.93 (quiet) | 26.26 → 25.80 |
| retake, 8 rounds, pass 2 | 33.58 → 33.11 (quiet) | 25.57 → 25.60 |
| retake, 8 rounds, pass 3 | 35.07 → 33.80 (quiet) | 25.25 → 25.46 |
| the review's, 8 rounds × 3 (GPU 39-50%) | 34.23 → 32.48, 34.01 → 33.95, 33.11 → 33.69 | 26.16 → 28.25, 26.72 → 26.80, 26.49 → 27.29 |
| B5.6 | 29.9 → 38.3 | 25.0 → 28.8 |

EpisodeB2's rows are below records in eight of nine passes, 1.4-4.1% in
the three that started on a quiet GPU; the one above (+1.7%) was the
review's, with the GPU 39-50% busy. PriceDiscovery's are above in seven
of nine (-2.3% to +8.0%), and the excess is in the **render**, above
records' in eight of nine (+0.4 to +1.6 ms; the retake's eight-round
passes +0.40, +0.43, +0.65, the review's +1.40, +1.27, +1.55), its
serialize within 0.17 ms in every pass but the retake's four-round one
(8.45 → 7.71, a pass whose records serialize read 1.6 ms above every
other). The first campaign's reading ("its serialize +0.07-0.17 ms, its
render within its spread") put it in the wrong place.

The still frame after a navigation reads rows above records (EpisodeB2
15.05 → 16.25 and 16.10 → 16.62, 15.75 → 16.77, 16.09 → 16.12; eight
rounds). Its format 7 message is 71.7 KB under records, 98.4 KB under rows
(B5.6's rows 85.4): the `row_paints` lists every batch now carries are
13.1 KB of it at the median (298 paint names; `native/still_header.py`,
`still_header_B2.txt`), which native capture and every recorded export
frame pay. `serialize/still_rows.py` holds the native driver's rows walk
on still frames to HEAD's: `_prepare_rows` 1.60 against 1.66 ms at 8.a.

**The page** (`browser_frames`' `cold`, the first message after a restore,
twelve a stream, the median over them as B5.6 quoted it), records → rows:

| page_ms | EpisodeB2, format 8 | format 7 | PriceDiscovery, format 8 | format 7 |
| --- | ---: | ---: | ---: | ---: |
| first campaign (5 rounds) | 2.34 → 2.59 | 2.57 → 2.49 | 1.49 → 2.07 | 1.30 → 1.48 |
| 21 rounds (`page_js/*_21_rounds.txt`) | 2.32 → 2.58 | 3.44 → 2.44 | 1.51 → 2.05 | 1.31 → 1.46 |
| retake (5 rounds) | 2.33 → 2.61 | 3.47 → 2.42 | 1.49 → 2.05 | 1.36 → 1.49 |
| total of the twelve (first / retake) | 45.56 → 47.25 / 46.43 → 46.63 | 45.03 → 44.73 / 45.65 → 43.27 | 27.07 → 29.23 / 27.55 → 29.38 | 27.08 → 25.83 / 26.52 → 26.16 |
| B5.6 | 2.32 → 2.68 | 3.24 → 2.48 | 1.56 → 1.73 | 1.72 → 1.83 |

Against B5.6, PriceDiscovery's format 8 median under rows has risen, 1.73
→ 2.05-2.07 ms, while its records' fell 1.56 → 1.49-1.51: B5.8 made this
number worse, and EpisodeB2's format 8 is 2.58-2.61 against B5.6's 2.68.
What the page does for a navigation is at or below records': compute
dispatches 73 → 74 and 26 → 26 (B5.6: 206 and 107), bind groups 218 → 214
and 78 → 78, buffers 428 → 426 and 210 → 206, uploads 1411 → 921 KB and
446 → 324 KB, the wire 898 → 248 KB and 400 → 225 KB, the message's
serialize 30.15 → 20.34 and 18.73 → 15.34 ms. Why the median still reads
above records in format 8 is **not isolated**. What is measured:

- **Format 8 only.** Format 7's cold messages carry the same definitions
  (the wire above is the same in both formats) and read rows close to
  records where format 8 does not: PriceDiscovery's 109, 115 and 130 read
  1.22/1.07, 0.79/0.68 and 1.25/1.20 ms (rows/records) in format 7 and
  2.52/1.20, 1.53/0.81 and 2.67/1.19 in format 8
  (`page_js/price_discovery_cold_by_checkpoint.txt`; the retake's
  `retake/price_discovery_cold_by_checkpoint.txt` alike). A run of many
  small paths is a geometry a path under rows (130: 92 geometries, 221 KB,
  where records send 2 definitions, 555 KB), but format 7 pays for the
  same definitions without the excess, so they are not what costs it. The
  first campaign's README named them; that was wrong. What differs is the
  delta path; its allocations are the candidates (the row staging
  reallocated after `releaseRowScratch` drops it, a member object a slot,
  the completed-state objects), none measured.
- **Where the young generation fills.** The twelve messages differ in rows
  and records by where a scavenge lands (`page_js/*_gc_*.txt`, V8's GC
  events inside each message): under rows EpisodeB2's 2.h takes a
  0.26-0.30 ms scavenge in every run and records none (records take a
  0.65-0.77 ms mark-compact at 4.h), and PriceDiscovery's 58, 109 and 115
  take 0.4-0.9 ms ones. The median of twelve lands on those messages. Rows
  allocate a little more on a navigation
  (`page_js/episode_b2_allocations.txt`: 33.5 against 30.4 MB over the
  twelve, part of it the fake device's own buffers).
- **The instrument.** Replayed without the harness's per-frame
  bookkeeping, one pass a fresh Node process, the two sources taking turns
  (`page_js/coldspread.py`), the readings move: EpisodeB2's format 8
  streams read 2.70 → 2.49 ms at the median of the per-message medians
  over 30 runs (`episode_b2_replica_30_runs.txt`), and over ten runs of
  the retake's streams (`page_js/replay_stderr_pipe_null.txt`, the p50 of
  each run's twelve, its median) EpisodeB2 reads rows below records in
  both formats (format 8 2.75 → 2.70, format 7 2.55 → 2.38) and
  PriceDiscovery's format 8 1.47 → 1.62. PriceDiscovery's 130 there reads
  2.58 ms under rows against 1.13 under records **when Node's stderr is a
  pipe**, as `browser_frames.py` runs its harness, and 1.03 against 1.20
  when it is `/dev/null`, with nothing written to it in either
  (`coldspread.py`'s `null`); with `/dev/null` PriceDiscovery's format 8
  reads 1.54 → 1.58. So that message's excess follows how the process is
  set up, not what the message carries, and the median of twelve moves by
  it. (The first campaign's README said 130 read 1.1 ms both ways in the
  replay; in format 8 with a pipe it does not.) The review's reading of 130
  timed alone under the profiler, 1.31 against 1.30, fits the case without
  a pipe: with one, 130 timed alone reads 2.7-3.1 under rows with or
  without the profiler (`page_js/price_discovery_130_stderr.txt`). Why a
  pipe on stderr moves one message of one source is not known.

## A dim sends no rows

`navigation_probe.py` (one cache and one native driver per source, format
7, the checkpoints walked in order; `navigation_B2.txt`, `navigation_B3.txt`):
EpisodeB2 258 → 277 (5.a, a dim of the earlier panels) holds 334 of its
463 batches under rows (records 176; B5.6's rows 0) and sends 10 paints
(0.3 KB) and 99 geometries (223 KB), none sent before (B5.6: 590 rows
re-sent that differed only in their alpha); the message is 528 KB against
records' 1805 KB. The native driver finalizes 692 members for it, in one
dispatch: a record's colour and active flag are its paint's.

## Pixels

`pixels/pixels_B2.txt`, `pixels_B3.txt` (B5.1's `episode_pixels.py`, from
B5.6's archive): EpisodeB2's 84 pausepoints and the 23 frames of the play
into 8.a, PriceDiscovery's 24 and 9, rows against records, largest channel
difference 0. `pixels/golden_pixels.json` (B5.6's `golden_pixels.py`,
`MANIML_EPISODES=$E`): the pin's 36 cases, 251 phase_b frames drawn as the
pin's records frame and as rows, largest channel difference 0, every
records frame its pinned digest, the eight golden tests passing.

## The serializer

`serialize/play_serialize.py` (the 8.a play serialized under the forced
Phase B, four replays a process), HEAD (`5c16c898`) and this tree in
alternate processes: 53.08, 53.64, 52.91 against 57.27, 56.91, 57.41 ms a
frame. `play_parts2.py` wraps the functions in both trees alike
(`play_8a_parts.txt`): `prepare_leaf` +2.2 ms (the rows read +1.4, the split
into geometry and paint 1.3 of it), `encode_draw` +0.8 (the paints' digests
+0.27, `rows_key` over pairs +0.14), `combine_run` +0.3, the header's JSON
+0.37 (every batch names its paints), about 0.5 not attributed.
`split_bench.py`: `split_rows` 2.3-3.8 µs a path.

## The gate

Records → rows, B5.8's gate as the plan states it:

1. A navigation natively at or below records: **met on EpisodeB2** (eight
   of nine passes below, the three quiet ones 1.4-4.1% below), **not met on
   PriceDiscovery** (above in seven of nine passes, its render above in
   eight).
2. A navigation's page JavaScript at or below records (the median of
   twelve): **not met** in format 8 on either episode (three takes each)
   or in format 7 on PriceDiscovery; met in format 7 on EpisodeB2.
   PriceDiscovery's format 8 is worse than B5.6's rows. Replayed apart from
   the harness the readings move by as much as the differences (above).
3. 8.a's play at or below B5.6's 80.52 ms: **not met** (86.09 and 83.71,
   across runs on a busier GPU; the serialize 4.2 ms a frame dearer than
   B5.6's code, measured directly).
4. A dim sends no rows: **met**.
5. Pixels identical to records: **met**.

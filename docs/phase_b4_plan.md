# Phase B4: the retained frame

Written 2026-09-26. Taylor's direction, quoted: "when we're done with this,
maniml uses python to send to the gpu the bezier control points, and then the
gpu does everything else. and it only ever directs the gpu what to change. so
literally if nothing changes, python isn't even talking to the gpu." And,
on how to get there: "keep Phase A as solid and build toward a final test
point in Phase B." The measurement that set the order is
`benchmarks/results/gpu_timestamps_20260926/`: on a 531-mobject diagram
(EpisodeB2, 8.a) a still Phase A frame costs ~37 ms natively, of which
Python's prepare and serialize are ~20 ms and the GPU ~4 ms; the B1 patch
fill lost 28 ms there for Python reasons (twice the batches, four times the
draws, encoded every frame), not GPU ones. So B4 comes before the flips.

## The decision

The retained frame is built in two tiers that ship separately and each pay
for themselves, chosen from three independent designs by two judges
(engineering risk, end-state fidelity; both chose it, with grafts from the
others recorded below).

**Tier 1 is Python-only and byte-identical on the wire.** A `RetainedFrame`
keeps, per drawn leaf, the draws it emitted and what they depend on. Each
frame re-walks the draw order (cheap, and it is what preserves CE order,
fixed-frame-last and the render-group rejoin exactly), trusts leaves whose
revision and camera key are unchanged, byte-checks leaves whose revision
moved but whose rows did not, re-validates camera-dependent counts in O(1)
per leaf on a camera move, reuses coalesced runs by member identity and
encoded descriptors by run identity, and adopts retired leaves by content
digest so a seek costs a lookup rather than hundreds of Lyon regenerations.
The wire, the browser, native capture and the recorder do not change.

**Tier 2 is the browser owning the frame.** An ordered slot list with
resolved GPU state per slot, a delta header against that list (splices,
camera only when it changed, program scalars as an op), refcount retention
in place of per-frame sweeps, slot-owned border/net/program outputs,
persistent uniform buffers written in place. A delta with nothing in it is
not sent at all: at rest Python is silent, and the browser renders nothing.
Tier 2 is negotiated per client, so native capture, the export recorder and
any client that has not announced the format keep receiving full frames.

**Why not the other two.** The minimal-delta design left a seek at today's
~100 ms per arrow key (464 regenerations for zero wire bytes) and moved the
wire grammar, both drivers, the recorder and the player in one increment.
The scene-table design has the end state's vocabulary — per-object handles,
content-addressed definitions, an op stream — but costs three copies of the
run rule and ~19 days before a first measurement. Its ideas are kept as the
increments after B4 (below). Per-object identity on the wire therefore
arrives after B4, not in it; under the constraint "the smallest architecture
that reaches the end state" that is the call, and it is recorded here rather
than asked.

## Evidence

Tier 1 exists as a scratch prototype run against the real serializer with
message equality asserted on every frame (still, idle tick, pan, zoom,
add/remove, child z_index, seek down/up, play frames, post-play, cold/reset;
`mismatches: none` on both episodes, Phase A and patches). Measured
`serialize_scene` medians, ms:

| Frame | Today | Retained |
| --- | ---: | ---: |
| EpisodeB2 8.a still (531 leaves, 444 runs) | 19.8 | 1.3 |
| 8.a, pausepoint with updaters ticking | 36.4 | 5.8 |
| 8.a pan / 2% zoom | 21.3 / 21.6 | 4.0 / 4.0 |
| 8.a seek down / up | 107 / 102 | 9.8 / 5.5 |
| 8.a play into the pausepoint (375 movers) | 84 | 88 |
| 8.a under `MANIML_FILL=patches`, still / ticked | 26.9 / 90.5 | 1.9 / 6.6 |
| PriceDiscovery 3.a.4 still / ticked / play | 5.8 / 7.8 / 7.9 | 0.43 / 1.25 / 2.7 |

The honest negative is the play row: when most of the scene moves, tier 1 is
neutral (the +4% is prototype bookkeeping to be removed), because the movers
cost what they cost — 52 ms of Lyon plus stroke expansion on Phase A, ~220 µs
of curve packing per mover under patches. Tier 1 meets the letter of the goal
(only what moves costs); the increments after B4 are what make a mover cost a
memcpy.

## Increments

Every increment lands behind `MANIML_RETAINED_FRAME` (tier 1) or is
negotiated (tier 2); the flag-off path stays byte-identical, proved by golden
message digests, and the suite runs green with the flag on and with
`MANIML_VERIFY_LEDGER=1`. Each is a commit with its proof.

**B4.0 Golden pin** (half a day). blake2b of `serialize_scene` bytes for
`renderer=triangles` and `phase_b` over the renderer fixtures, a scripted
synthetic sequence, twelve pausepoints per episode and the 8.a play frames;
asserted after every later increment. Also two flag-off fixes the readers
found: `set_stroke(behind=)` bumps no revision (a checkpoint-ledger bypass
today), and `verify_render_cache()` / `render_cache_policy()` are read per
leaf rather than per frame.

**B4.1 Refactor, no behavior change** (1 day). Extract `prepare_leaf` and a
`LeafContext` from the per-record loop of `prepare_triangle_frame`, expose
`run_kind` / `combine_run` from `coalesce_draws`, split
`serialize_generated_frame` into `encode_draw` + `assemble_message`. Proof:
the golden pin, the whole suite.

**B4.2 RetainedFrame v1** (2 days). `LeafEntry` trust by revision + interned
camera key, shared `UniformSets` (one merged uniform dict per override set,
updated in place on a camera change, keyed by the *string* of the overrides
so `1` and `1.0` stay distinct — the one byte trap the prototype hit),
coalesce with memoized kind and identity `combine_memo`, `RunMemo` fragments,
`assemble_message` join; `GeometryCache.retained_frame`. Proof: a scripted
sequence (still ×20, add/remove, child z_index, reset/connect, renderer
switch, cold) asserting message bytes equal to the flag-off path. Gate: 8.a
still ≤ 2.0 ms.

**B4.3 Truthful dirty and camera revalidation** (1 day). Column-wise
`source_equal` on a revision move (derived columns excluded, no pending
program) — the two-stage form: whole-row bytes against the caches' frozen
sources first, columns only on a mismatch; O(1) stroke count from a per-leaf
`max_sqrt_area`; `revalidate` on a camera change through the mesh and border
caches' own hit paths. Gates: 8.a ticked ≤ 6 ms, pan/zoom ≤ 5, PriceDiscovery
ticked ≤ 1.5.

**B4.4 Retired leaves and digest adoption** (1 day). A leaf whose object
leaves the walk is parked under a content digest (type, uniforms, flags, the
non-derived columns); a new object with equal content adopts it, mesh entry,
classify tuple, border source and capacity included; the store is bounded and
counted in the mesh cache's 64 MiB budget. Proof: seek down/up, far jump and
back, watcher restart replay, all byte-identical, zero regenerations on seek
up. Gates: 8.a seek down ≤ 12 ms, up ≤ 8; landing frame after a play ≤ 15.

**B4.5 Verify mode, bytes policy, the flip** (1 day). Trusted leaves rebuilt
and compared under `MANIML_VERIFY_LEDGER=1` (raise `RenderCacheStale` naming
the leaf); `MANIML_RENDER_CACHE=bytes` disables leaf trust; the per-leaf
snapshot copy replaced by the caches' frozen sources; `episode_frames.py`
gains the `retained` variant and the archived run; the default flips to on
(Phase A pixels cannot move, because bytes do not); docs.

**B4.6 Browser baseline** (1 day). `benchmarks/browser_frames.py`: the real
`webgpu.js` on a counting fake device in Node over a recorded frame stream
from the episodes — JS ms per frame, command counts, buffers created — plus a
viewer-side `performance.measure` per frame. Today: 2.2 ms JS at 444 batches
(Phase A), 8.0 ms at 911 (Phase B), before Dawn's per-call work. Measured
2026-09-26 (`benchmarks/results/browser_frames_20260926/`; in the vm
sandbox, which B4.7 found inflates them, see there): the still 8.a
frame 2.39 ms at 444 batches / 445 draws (Phase A) and 9.28 ms at 911 / 1841
(Phase B), one `setPipeline` per draw, zero uploads, 179 / 434 KB of header
per tick; plays 5.6 / 3.4 ms at the EpisodeB2 median, Phase B's with 100
temporary uniform buffers and 166 bind groups per frame (1384 and 2306 on
the 5.a play); the first message after a restore (a seek, delta-encoded
against the previous message) 15 / 23 ms and 1.1 / 1.8 MB at the median,
23 / 30 ms where nothing was cached.

**B4.7 Slot list in the browser, still fed by full frames** (3 days).
`frame.slots`, `makeSlot` / `releaseSlot`, refcount retention replacing the
used-set sweeps, slot-owned border/net/program outputs (the `(hash,
occurrence)` keys go), persistent per-override-set uniform buffers written
with `queue.writeBuffer`, a resolved-slot encode loop, `applyFull`. Proof:
every case of `generated_webgpu_commands.cjs` and `player_commands.cjs` with
the same command sequence except the intended differences; `test_wgpu_port`
pixels unchanged; and one new case the `(hash, occurrence)` keys fail
today: two objects under one program (same sources) whose scalars differ,
coincide for a frame, then differ again — the second object's border or net
output keeps the bind group made against a program output that the
coincidence retired and destroyed, and the third frame's compute reads a
destroyed buffer (a Dawn validation error; found in B4.6's review, deferred
here because slot-owned outputs replace that ownership). Built 2026-09-26
and revised after its review (`browser_frames_20260926/README.md`, "After
B4.7"). What the page pays, measured in Node's own realm through the
viewer's renderer selection (`browser_frames.py --realm main`, `page_ms`),
B4.6 → B4.7: a resend of the 8.a frame 2.04 → 0.09 ms (Phase A) and 5.98 →
0.24 ms (Phase B), the driver redrawing its slots and the selection no
longer parsing a message it has just routed; the same frame with its bytes
differing 2.02 → 0.85 / 5.85 → 2.12 ms, its header parsed twice (by the
selection, 0.35 / 0.88 ms, and by the driver); a camera move 2.00 → 0.85 /
6.66 → 2.15 ms with no buffer or bind group made (46 / 461 before); plays
1.96 → 1.23 / 2.14 → 0.97 ms at the EpisodeB2 median; seeks 1.99 → 1.34 /
4.17 → 3.35 ms. The medians hide the dearest frames: Phase B plays make
nothing per frame where the movers are programs, but 8.a's movers are not
(about 700 uncached batches, 1402 buffers and 701 bind groups per frame,
6.10 ms), Phase A's 5.a play uploads 1148 buffers per frame (5.52 ms), and
a play's first frame and its landing, now classes of their own
(`--play-edges`), reach 13.66 and 6.00 ms on the 5.a play in Phase B. Every
existing command case and the four episode streams with their edges (1484
messages) trace identically by content under the B4.6 and B4.7 drivers, and
the streams without their edges rendered pixel-identically on a real WebGPU
device (on the draft, whose traces the review's fixes left unchanged).
Committed with
it: `tests/webgpu_trace.cjs` (a trace by content, compute outputs as tokens
of what their kernel read) and two cases that check the retained frame
against a fresh driver given each frame whole, over a synthetic sequence
and over `test_browser_frames`' recorded streams; `failedFramesKeepTheCamera`
for the defect the review found (a frame that failed after rewriting the
shared uniform sets left them at its camera; a failed frame now clears what
every set is taken to hold) and `generationFollowsItsInputs`. The new cases
`slotsReuseAcrossFullFrames`, `outputsSurviveInsertion` and
`programOutputsSurviveCoincidence` fail on the old driver.
`player_commands.cjs` stubs the driver and `test_wgpu_port` draws with the
Python reference, so neither touches `webgpu.js`. Two findings about the
instrument, for B4.8. The fake device runs the driver in a vm sandbox, where
every global lookup is an interceptor call, and that alone made most of
B4.6's cold and play milliseconds (the B4.6 driver's seek 15.5 ms there, 1.9
ms in Node's own realm), so every B4.6 number in this plan, the "8.0 ms at
911" above among them, is a sandbox number. And B4.8's play gates below were
set on B4.6's sandbox medians: as the page's cost in the main realm, B4.6
already met them at the class median, and as bounds on every play frame
B4.7 misses them on the 8.a and 5.a plays and on play entries, frames whose
uploads or first resolution are the cost (under patches the movers' uploads
are B5.1's).

**B4.8 Format 8 deltas** (3 days; shipped, "B4.8: shipped" below).
`RetainedFrame.diff` → splices and
`scalars` ops; `epoch` / `frame` / `base`; the client negotiates in its
`mode` message and the viewer emits deltas only when every client of the
viewer has (one cache, one broadcast); `applyDelta` with staging and
rollback; any epoch/base mismatch or cache miss → the existing
`geometry_reset` → a full frame; an empty delta is not broadcast (the
recorder still records one frame per render); the player's format list
gains 8, the recorder and native capture stay on full frames. Proof: Node
`deltaEqualsFull` over recorded episode sequences (seeks, plays, resets,
renderer switches): identical slot lists, buffer sets and command
sequences; `test_web_viewer` end to end: connect (full), still (nothing),
renderer switch (full), reset (full), two tabs. Gates: wire at rest 0 B; a
camera move < 1 KB; JS at rest 0; play ≤ 2 ms JS (Phase A) / ≤ 4 ms (Phase B),
set on B4.6's sandbox medians: re-derived here in the main realm on the
page's cost (`browser_frames.py --realm main`, `page_ms`), stating whether
they bound the class median or every play frame, entry and landing included
(B4.7's finding above).

**B4.9 Render bundles for Phase A segments** (2 days, only if B4.6/B4.8
show Dawn's per-draw cost above 1 ms at 911 slots). Phase B bundles wait on
patch pipelines with a fixed stencil reference (a pixel-gated shader change).

## B4 tier 1: shipped

B4.0-B4.5 landed on `b4-retained-frame` (2026-09-26/27), and the retained
frame is the default: `MANIML_RETAINED_FRAME=0` is the whole-frame path it is
held to, byte for byte, for the same cache history. The golden pin (502
digests) runs with whatever the run's switch is, and has not moved; the suite
runs green with the switch off, on, and on under `MANIML_VERIFY_LEDGER=1`, and
CI runs the pin all three ways. What each increment added: B4.0 the pin, and
the flag-off revision gaps it found; B4.1 the seams (`prepare_leaf`,
`run_kind`/`combine_run`, `encode_draw`/`assemble_message`); B4.2
`RetainedFrame`, leaves kept by revision and camera, shared uniform sets keyed
by their text, run and descriptor memos, `keep` on every cache; B4.3 a moved
revision compared with the rows the draws were read from and a camera move
revalidated through the caches' own paths; B4.4 retired leaves parked by
content digest and adopted; B4.5 verification, the bytes policy keeping
nothing, an entry's rows shared with its border source's frozen copy,
`episode_frames.py --variants gpu_border retained`, and the flip.
Verification keeps exactly what the frame keeps without it (a fill's mesh
across a camera move included), then reads each kept leaf in its place with
nothing written to the leaf or stamped on the caches for it first, so the
read refreshes the leaf itself and the caches compare what a stamp would
have had them trust; the kept draws, and the rows a moved revision was
judged by, are held to that read (`_verify_kept`), and a difference raises
`RenderCacheStale` naming the leaf, its place in the draw order and what
moved, as a write that bumped nothing or as the retained frame's own rule.
A leaf that would adopt is prepared instead and the parked draws and uniform
set held to its read. Outside verification, a leaf the walk compared is
compared again in its place once a getter of a leaf's own has run (the only
code a frame runs that may write to another leaf without a bump), so a
stamp never says more than a comparison did.

Measured, `serialize_scene` medians in ms: flag off and flag on each through
its own cache, alternated, messages equal at every frame (one scene for
still, ticked, pan and zoom; two scenes loaded alike and navigated with the
collector held for the rest). The machine was not quiet (load 3-4, the M3
shared with other applications), so both columns run a little slower than
B4.4's own gates did (8.a still flag off 19.3 against 18.3, on 1.65 against
1.46); the prototype column is the Evidence table above.

| Frame | Flag off | Prototype | Shipped | Gate |
| --- | ---: | ---: | ---: | ---: |
| EpisodeB2 8.a still (531 leaves, 444 runs) | 19.3 | 1.3 | 1.65 | ≤ 2.0 |
| 8.a, its updaters ticking | 30.9 | 5.8 | 3.73 | ≤ 6 |
| 8.a pan / 2% zoom | 21.8 / 20.0 | 4.0 / 4.0 | 3.80 / 4.01 | ≤ 5 |
| 8.a seek down / up | 103.6 / 107.2 | 9.8 / 5.5 | 8.21 / 8.15 | ≤ 12 / ≤ 8, unverified |
| 8.a landing after the play | 103.6 | – | 12.4 | ≤ 15 |
| 8.a far jump / and back | 44.5 / 120.5 | – | 11.5 / 18.7 | |
| 8.a restart from source (every mobject new) | 119.5 | – | 9.7 | |
| 8.a play into it (365 of 531 move) | 89.2 | 88 | 85.9 | neutral |
| 8.a Phase B still / ticked | 26.6 / 62.1 | 1.9 / 6.6 (patches) | 2.79 / 4.91 | |
| 8.a Phase B seek down / up / play | 119.9 / 121.4 / 110.5 | – | 9.5 / 9.3 / 103.3 | |
| PriceDiscovery 3.a.4 still / ticked | 5.98 / 8.12 | 0.43 / 1.25 | 0.74 / 1.02 | ticked ≤ 1.5 |
| 3.a.4 pan / zoom | 6.24 / 6.44 | – | 1.43 / 1.65 | |
| 3.a.4 seek down / up / play / landing | 17.1 / 17.1 / 7.9 / 21.5 | – / – / 2.7 / – | 2.63 / 2.59 / 3.08 / 8.05 | |
| EpisodeB2 5.a's play (all 461 leaves move) | 54.6 | – | 63.5 | |

Every gate is met but seek up, which is **unverified**: 8.15 ms median (7.75
the fastest of eight rounds) against ≤ 8, at load 3-4. B4.4's commit gave
7.73-7.89 on the quieter machine it was committed from, and 8.24 measured
beside B4.5's first draft under another session's live viewer; the seek's
bytes and counts are B4.4's (the navigation's frame digests are identical).
It is not met until the navigation gate (EpisodeB2 at 307, Phase A, eight
rounds) runs under 8 on a quiet machine. The complete native frame
(`benchmarks/results/retained_frame_20260926/`, serialize through the full
readback, pixels identical on every frame): 8.a still 36.9 → 21.5 ms,
ticking 49.9 → 24.3, its play 108.9 → 108.4; every EpisodeB2 pausepoint
19.7 → 13.3, every PriceDiscovery one 15.4 → 10.9, their plays 37.5 → 28.4
and 23.4 → 15.3. At rest what is left is the native driver encoding 444
batches (7.3 ms, unchanged: only the browser will learn the retained list)
and the full readback the browser never does.

The negatives. **A play where every leaf moves costs more**, and the flip
takes that cost as measured, not the neutral the Evidence section expected:
5.a's play prepares all 461 leaves each frame and serializes in 63.5 ms
against 54.6 (+16%; B4.4's commit, measured the same way, 72.7 against
62.5), 147.4 against 138.1 for the complete native frame. That is tier 1's
bookkeeping on a leaf it prepares, ~19 µs a leaf (its entry and cache
records, 2.5 ms a frame there; its uniform set's text, 1.8; the comparison
that finds it moved, 1.3; the run memos and descriptors around combine and
encode, ~2), which nothing kept pays back; 8.a's play, where a third of the
scene holds still, is neutral, and plays over both episodes gain. The flip
applies to `--render` too, so a render made mostly of whole-scene moves pays
it; whether that stands is Taylor's to weigh, and a fast path for leaves
that will be prepared (stop the comparison at the first row that differs,
keep a leaf's override text while its uniforms are unchanged, skip the memos
of a run whose members are all new) is the open item that would take it
back. The prototype's per-leaf snapshot copy is gone where a cache holds the
rows: an entry takes its border source's frozen copy (every filled path
under Phase B, where held rows cost 0.38 ms a frame over 8.a's play against
0.89; bordered paths under Phase A), and keeps its own copy of a stroke's or
a mesh-only fill's rows, which no cache holds whole (Phase A's glyphs: ~0.5
ms a frame there). The retained frame holds 0.80 MB beside the caches at
8.a (1.08 before the frozen rows), and its retired store up to what the
caches leave of their 64 MiB (18 MB after twelve pausepoints of EpisodeB2),
the patch fill's object words and paint field counted. Verification costs
what reading every leaf costs: 8.a still 36.8 ms against the flag-off path's
27.1 under the same switch (ticked 42.8 against 31.5, PriceDiscovery ticked
15.0 against 10.5). Tier 2 (B4.6 on) is where a frame at rest stops costing
anything, and B5.1 where a mover costs a memcpy.

## B4.8: shipped

Format 8 is a stream, negotiated per client (2026-09-27, on
`b4-integration`). Every format 8 message carries its `epoch` (bumped by
every reset: a connect, a renderer or generator change, a client's
`geometry_reset`, a serializer failure, a change in what the clients
negotiated, a `geometry_request`) and its `frame` number in the epoch. An
epoch opens with a full frame; every later message is a delta against the
one before it (`base`), and a frame that changes nothing is not a message
at all. The page announces the format in every `mode` message (`format:
8`); the viewer, with one cache and one broadcast, streams deltas only while
every client connected has announced it (the server numbers its clients and
tags their events), and a tab that has not has every tab sent format 7 full
frames. `Camera.capture`, the export recorder and any other cache never
negotiate.

**The goldens keep format 7.** A cache whose receivers have not negotiated
writes format 7 full frames, byte for byte what format 7 always wrote:
`GEOMETRY_FORMAT_VERSION` is 8, `FULL_FRAME_FORMAT_VERSION` 7, and a format
8 full frame is the format 7 frame with `"format_version": 8, "epoch": E,
"frame": 0` where `"format_version": 7` was. Chosen over normalising the
pinned digests because the evidence ran one way: the pin's 502 digests stand
unmoved with no normalisation in the pin at all; a frame number in every
full frame would make no two of a non-negotiated stream's messages equal,
so B4.7's byte-identical redraw (0.09 against 0.85 ms at 8.a) would be lost
for a tab that has not negotiated, and recordings, which the player replays
the same way, would carry numbers no reader uses; and native capture and
the recorder would take a format change for nothing. The pin now proves the
rest: every golden case is also streamed through a negotiated cache per
renderer, each full frame is the pinned bytes once its two keys are taken
out (`format_seven`), and each delta, or silence, applied to the frame
before it by `geometry.expand_delta` is the pinned frame's bytes exactly
(the payload is the same bytes: the batches the receivers lack, then the
definitions, so the batches a delta carries keep their offsets).

**The delta.** `generated_geometry.diff_runs` over the last message's
batches and this one's (`SentBatch`: content hash, program scalars, the
held descriptor's text without them): the runs both share at either end are
kept; where the frames hold as many runs between, each maximal range that
differs is a splice, else the range is one; a kept program run whose
scalars moved is a `scalars` op. A header field (camera, background,
resolution, samples, supersample, limitations) travels only when its text
changed, and a definition table only when it holds something. The diff is a
function beside the encoder rather than `RetainedFrame.diff` as this plan
first named it: the whole-frame path streams the same deltas byte for byte
(the lockstep's scripted sequence runs as a stream too, 85 deltas and 75
silent frames equal on both sides), and a program run is a new `RunMemo`
every frame, so run identity is compared by the held text, which a kept
run hands over as the same string object frame after frame. In the browser,
`expandDelta` builds the frame from the retained slots' batches as held and
the delta's splices and ops, and `applyDelta` keeps each slot the delta did
not splice without a comparison and resolves the carried batches as
`applyFull` resolves the ones that differ, staged and rolled back as a full
frame is. A delta whose epoch or base is not the frame drawn, or a delta
that fails, asks for a full frame through the existing `geometry_reset`,
once per epoch. A full frame that fails asks nothing, as format 7's does
(the review's finding: the full frame that answered it fails alike when the
cause is its content or the device, an undecodable image or a buffer limit,
and the page and the engine then asked and answered at up to 45 Hz with the
scene at rest); the stream stays where it stood, so the epoch's first delta
asks, once. `renderer_selection.js` reads the renderer
from the header's start (it follows integer fields only), so the page parses
a header once. `geometry_recording.js` refuses a delta; the player reads
formats 1-8.

**Proof.** `deltaEqualsFull` (Node, two drivers, one fed the format 7
frames and one the format 8 stream of the same history, a renderer switch
destroying and initializing both as the page's selection does): after every
message the same slots, the same live buffers (size, usage, bytes) and the
same submission, compute passes included; where the stream sent nothing,
the full frame redrew the picture on screen. Committed over a synthetic
history (stills, a move, a pan, a zoom, z-order both ways, an insertion and
a removal, a play and its landing, a reset, both renderer switches, Phase
B's programs as scalars ops) and `test_browser_frames`' episode fixture
(seeks, plays, ticking updaters); run over both episodes' recorded streams
with every class (1628 messages: 946 deltas, 678 silent, 4 full), all
equal. `deltasApplyOnlyToTheirBase`: a delta against another base draws
nothing and asks once per epoch; a failed one leaves the frame and the
stream as they were; a full frame that fails, epoch after epoch, asks
nothing, and the epoch's first delta asks once; a format 7 frame or a
destroyed driver ends the stream. `test_web_viewer.DeltaStreamE2E`: connect (a format 8 full frame),
still with the updater ticking (nothing), a pan (a delta under a kilobyte,
the camera alone), a zoom (the next delta), a renderer switch and a
`geometry_reset` (full frames of new epochs), and a second tab that has
not announced format 8 (format 7 full frames for both, the stream resuming
with a full frame when it goes).

**Gates** (`browser_frames.py --deltas --camera-moves --play-edges --realm
main --rounds 5`, the format 7 and format 8 streams of the same frames
replayed alternately, each frame's median page_ms;
`benchmarks/results/browser_frames_20260926/README.md`, "After B4.8"):

| Gate | Phase A | Phase B |
| --- | ---: | ---: |
| Wire at rest, 8.a with its updaters ticking (14 rounds) | 183,234 B → 0 (nothing sent) | 444,120 B → 0 |
| A camera move at 8.a: pan / 2% zoom / back | 456 / 517 / 427 B | 456 / 517 / 427 B |
| JS at rest: 8.a ticked, page_ms (12 timed rounds) | 0.06 → 0 ms (no render call) | 0.15 → 0 ms |
| Play, class median (EpisodeB2 / PriceDiscovery) | 0.75 / 0.20 ms ≤ 2 | 0.29 / 0.17 ms ≤ 4 |
| Play, every frame, entry and landing included | PriceDiscovery ≤ 1.90; EpisodeB2 5.18 max | PriceDiscovery ≤ 2.27; EpisodeB2 11.51 max |

The play gates bound the class medians on both episodes and every play
frame of PriceDiscovery, entries and landings included. They do not bound
every frame of EpisodeB2: 14 of its 138 play, entry and landing frames
exceed them each way, all where uploads are the cost and a delta changes
none of them: Phase A's 5.a play (all 461 leaves move: ~2.4 MB on the wire
and 3.4-3.9 MB uploaded a frame, 4.1-5.2 ms), its entry and its landing;
Phase B's 8.a play (the movers that are not programs, ~0.9 MB uploaded a
frame, 4.1-6.7 ms) and its entry, and 5.a's entry and landing (5.1 and 3.9
MB uploaded, 11.5 and 4.9 ms). Those are B5.1's and tier 1's to remove, as
B4.7 found. Elsewhere the stream removes work but in one place: 8.a's
ticked frame 0.06 → 0 ms (Phase A) and 0.15 → 0 (Phase B) a frame at rest
(format 7's cost there is B4.7's redraw of a byte-identical resend; the
round after a seek, whose message is not the seek's and is matched batch
by batch, 0.58 → 0 / 1.41 → 0 once), a camera move 0.29 → 0.09 / 0.30 →
0.12 ms at the median, a Phase B play 0.65 → 0.29, a landing 0.30 → 0.12 /
0.92 → 0.52. **The negative: EpisodeB2's Phase A seeks cost more JS under
format 8**, 4-9%, about 0.1 ms a seek, though they send and make the same:
the archived rounds' class median 1.16 → 1.27 ms and per-row minima 25.5 →
26.9 ms summed over its 12 seeks (+5.5%); the review's eight rounds 26.4 →
28.8 (medians) and 24.9 → 26.4 (minima); the fix pass's eight 26.3 → 27.6
and 25.1 → 26.2. Phase B's seeks (2.53 → 2.54 ms; minima 42.8 → 41.7) and
PriceDiscovery's cost the same. Timed by stage, `expandDelta` is 0.01 ms a
seek; the difference is in resolving the slots, partly because a splice
carries the batches of a middle whose length changed, equal ones included,
through the hash search (33 → 173 batches searched on one seek), but not
only: an in-place match for carried batches (`applyFull`'s first pass)
made the searched counts equal without closing the gap (minima 25.3
against 26.1), and the streams' first message, the same full frame run
through the same code, is 0.3 ms slower in the format 8 run too, so part
of the gap is not the delta's work at all. Left as measured, and deferred
with the review's candidates (`heldBatch` copies of kept head and tail
batches, the middle's hash search). What Python pays for the stream at
8.a, both caches on one scene alternating which goes first: still 1.40 →
1.48 ms, ticked 3.36 → 3.54, pan 3.02 → 3.16 (Phase A), about 0.1 ms of
diff over 444 runs; a play is neutral. Not done: a real-device pixel check
of the delta path (the Node equivalence is the proof, as planned: the
native driver never sees a delta).

## B5.1: built

Since B5.6 rows are the default wherever patches are drawn, with
`records` the override ("The flips", B5.6).

Rows on the wire under patches, behind `MANIML_PATCH_SOURCE=rows` (default
`records`, so Phase B as measured on 2026-09-26/27 stays reproducible;
2026-09-27, on `b4-integration`). A filled or stroked path whose rows can
stand for its records (VMobject's own columns, the library's getters, the
outer-vertex pattern) is read once per changed revision as its shader data
would be read (unit normal, joint angles, base points refreshed), copied
once (`RowsSource.read`, kept in the border cache's own entry, reservation
and trust), and sent in `program_data` by content hash; its patch and
stroke batches name it in `rows`. Each driver finalizes each rows once with
`row_finalize.wgsl` into curve records and stroke instances shared by every
batch that names them, copies a run's objects' outputs into a buffer of the
run's own, and feeds the border stage, the patch fill and the stroke
pipeline from them as it feeds them a program's output (`_prepare_rows` in
`wgpu_renderer.py`; `resolveRows`, `makeFinalizedRows` and the head of
`prepareCompute` in `webgpu.js`). Where every drawn path is row-sourced,
the runs, groups, counts and draws are the records' call for call. A path
that keeps its records (a getter of its own, another dtype, an edited
outer-vertex pattern) closes the rows run around it, because `run_kind`
gives row-sourced draws kinds of their own (`patch_rows`, `stroke_rows`)
that never join a `patch` or `stroke` run: three stroked squares whose
middle one has a getter of its own are one draw of 12 instances from
records and three of 4 from rows, and a records patch between row-sourced
ones splits their patch run and its shared stencil groups alike. The pixels
do not move; the draw and group counts B5.2 and B6 read do. Python keeps:
the refresh of the derived columns the rows carry; the validation (finite
rows, nonnegative fill border widths, no overflowed area both ways); what
the draw counts need (active curves, the reservation's density summary, the
stroke's largest curve); the planar refusal, unchanged, with a path whose
points share one z accepted without the fit (it lies in that plane); and
the eight-word object record, whose base words stay zero (unread since
B3b), so a moving object's table does not change, and whose winding sign is
computed only for an object that may share a stencil count, the only kind
the sign groups. A stroke's rows are compared every frame, since the
records' side reads its shader data every frame; a fill's are trusted at an
unchanged revision, as its records are. `geometry_recording.js` captures a
batch's rows when it indexes the frame and carries them into every frame it
reconstructs, as it does a program's sources.

**Proof.** Pixels, rows against records, natively: the 20 renderer
fixtures, the quality fixtures (tex, perspective, hairlines, border, normal
and zoomed) and a sequence of moves, zooms and a morph, identical (35
frames, largest channel difference 0; `tests/test_patch_rows.py`
`PatchRowsPixels` holds the gate and at most 1/255); every pausepoint of
both episodes and their gate plays, Phase B stack, identical (EpisodeB2:
84 pausepoints and the 23 frames of the play into 8.a; PriceDiscovery: 24
pausepoints and the 9 of the play into 3.a.4; largest channel difference
0). The three mirrors' commands: `rowsWire` (the browser driver on real
rows frames: one finalize per rows, a run's copies in order, the border
stage, the patch fill and the strokes reading the outputs, the records'
draws call for call, nothing made again for the same frame, retirement);
`deltaEqualsFull` over the B4.8 synthetic history under both sources (the
slots, buffers and submissions of the format 8 stream are the format 7
frames'); the native driver on the fake device (`PatchRowsCommands`: one
finalize per rows, the run's copies, rejected malformed sources with
nothing submitted or kept); the player (`player_commands.cjs phaseB` and
`corrupt` with row sources; a row-sourced `--export` replayed forward, back
and by chips through the indexer and the driver, `test_export`). The
retained frame holds to the whole-frame path under rows byte for byte
(`RowSourcesLockstep`, `RowSourcesNavigation`: every lockstep, the seeks
and adoptions, verify mode included); the golden pin, which now clears the
switch, has not moved.

**Gate** (the play into 8.a, 23 frames, Phase B, retained frame on;
`serialize_scene` alone, each replay of the play serialized through one
source only, the two alternating replay by replay, four replays each, each
frame's median over its replays, then the median over the frames; load
2.3-3.0, the GPU idle):

| 8.a play | records | rows |
| --- | ---: | ---: |
| format 8 stream, ms (min) | 104.5 (99.9) | 51.6 (49.5) |
| format 7 frames, ms (min) | 105.4 (101.4) | 52.2 (49.9) |
| whole-frame path, format 7, ms (min) | 114.3 (107.5) | 51.4 (47.9) |
| wire, format 8 | 997 KB | 616 KB |
| of which the payload | 595 KB (records 392, strokes ~191, tables 12) | 203 KB (rows alone) |
| PriceDiscovery 3.a.4 play (its movers are programs), format 8 | 6.20 ms | 6.31 ms |

The design's estimate was 206 KB of rows for 375 movers: measured 203 KB,
and the copy and hash of them 0.9 ms a frame. The serialize is 51.6 ms, not
the 2.65 ms floor, because the floor was the rows alone and the serializer
still builds a leaf's draws and a batch's descriptor per mover. Where the
rest goes (one instrumented run, 54.8 ms against 51.6 uninstrumented, 383
leaves prepared and 739 batches encoded a frame): the rows read 18.2 ms
(the refresh of joint angles and unit normals ~7.9, the same work the
records' side does; the CPU's derivations for the counts and the
validation ~9; the copy 0.3); the rest of each leaf's preparation 11.3
(the rows entry and reservation 1.9, the classification 2.9, the record
and planar check 3.1, the two draws 3.4); tier 1's bookkeeping 6.4 and the
coalescing 5.3; the encode 13.5 (739 descriptors 9.1, of which the rows'
hashes 0.6, and the JSON and assembly 4.4). The next levers, in that
order: a mover's batch keeping its identity with its rows as a per-frame
op, as a program's scalars are (the header is now 413 of the 616 KB and
the encode a quarter of the frame); the joint angles computed in the
finalize from the rows' points; the per-leaf and per-batch structure the
floor did not have.

**The negatives: the GPU, the native render and the browser's JavaScript
pay for finalizing what the CPU packed.** Both drivers put every fresh
rows' finalize into one compute pass, one dispatch each: about 360 a frame
on the 8.a play (the browser's count below, 711 dispatches against 351),
at about 30 µs of GPU time a dispatch, far more than its work. On the same
play, the two sources alternating replay by replay as in the gate (six
replays each, each frame's median over its replays, then the median over
the frames; the minimum in brackets; load 2.7-3.7, the GPU idle at the
start of each run, Taylor's viewer drawing between them):

| 8.a play | records | rows |
| --- | ---: | ---: |
| GPU frame, `gpu_total_ms` (attribution run, `MANIML_GPU_TIMESTAMPS=1`) | 17.8 (16.2) | 27.6 (19.2) |
| of which the `rows` pass, exclusive | – | 10.9 (3.0) |
| of which the borders / out, exclusive | 15.1 / 2.56 | 14.5 / 2.07 |
| native `render()` through its readback, flag off | 93.1 (86.6) | 108.3 (101.7) |
| complete native frame, `serialize_scene` + `render()`, flag off | 198.1 (189.4) | 160.5 (156.8) |

A play frame gains ~10 ms of GPU (+55%) and ~15 ms of native render (the
finalize's GPU time and its encoding, natively a parameter buffer and two
bind groups per rows), against ~52 ms less serialize, so the complete
native frame still gains ~38 ms; the border stage and the out pass read
finalized records a little faster (~0.6 and ~0.5 ms). The browser's GPU
frame was not measured (the fake device has no GPU); if Dawn's dispatches
cost what wgpu-native's do, it rises by about the same ~10 ms. The fix is
to stop issuing a dispatch per rows, in both drivers: finalize a frame's
fresh rows in one dispatch over their concatenation and a table of offsets
(an output then becomes a range of a shared buffer, which changes how
outputs are kept and retired); finalizing a run's members straight into
the run's buffer would also remove the copies. A compute pass per finalize
is not it: natively it made `render()` slower still (121.4 against 111.0
ms, four replays each). Deferred to an increment of its own, with this
table as its baseline; B5.8 ("The flips") finalizes a frame's rows in one
dispatch of a table, into buffers each batch owns.

The browser's JavaScript: `browser_frames.py`'s new variant `phase_b_rows`
against `phase_b` (four middle frames of the 8.a play, main realm, five
rounds, the fake device): page_ms 8.34 → 8.89 (format 7) and 8.22 → 9.22
(format 8) at the median, uploads 909 → 528 KB a frame, buffers made 1405 →
1786, bind groups 703 → 1060 (a finalize's per rows), dispatches 351 → 711,
draws 1817 both. A finalize's parameters are shared per curve count; the
records and instances of one rows are two buffers, one of them unused by a
path with no stroke (a glyph), which one buffer bound at two offsets would
save. Not a gate here; B6 reads the complete frame.

## B5.3: built

Programs for strokes on Phase A, behind `MANIML_PROGRAMS=strokes`, a mode
beside `off`, `shadow` and `gpu` (default `off`, so nothing changes;
2026-09-27, on `b4-integration`). Strokes never needed the mesh, so the
rule "programs require patches" is now per object. A program over a path
without fill is drawn on Phase A as a stroke from the program's finalized
instances, as it is under Phase B; a filled path's program still needs the
patch fill, and without it the leaf is drawn from its rows
(`_program_draws`), and `shadow` and `gpu`, whose programs are mostly
fills', still refuse `MANIML_FILL=meshes`. The decision is the
animation's, made once at its begin (`programs.begin`, stored as
`Animation.program_sources`, asked per frame by `programs.admits`): the
places in the families it zips where every source is a path without fill,
or has no points, are freshened and may record a program, and nowhere
else is anything freshened, so a filled member's animation, its sources
included, is the CPU path's exactly (its rows, derived columns, refresh
flags and uniforms equal to programs off at every frame). That covers
`ShowCreation`/`Create`, `Uncreate` and `ShowPassingFlash` (`partial`),
`VFadeIn`/`VFadeOut` (`paint`), `maniml.animation.rotation`'s
`Rotate`/`Rotating` (`affine`, all or nothing, so a rotation of a group
that holds a filled member is the CPU's whole), a straight `Transform` and
what is one (`FadeIn`/`FadeOut`, `.animate`, `MoveToTarget`, and the
CE-compat `Rotate` that a `from manim import *` scene such as the episodes
gets, `maniml/compatibility.py`, a `Transform` to the rotated copy and so a
`blend` admitted place by place, not all or nothing), and
`Write`/`DrawBorderThenFill` of a path without fill (`partial`, then
`blend`); an animation whose begin decides nothing (`FadeTransform`) keeps
the CPU path under strokes. The begin's own `interpolate(0)` runs before
the places are decided, so a play's first interpolation is the CPU's. A
path without fill whose unseen fill colour varies (a gradient `set_color`
writes both colours) is drawn as its program, since a stroke's instances
never read the fill columns; the review draft refused it for a paint field
no stroke has, and so recorded a program every frame and read it back. A
program leaf is the retained frame's own kind, as it was under patches,
and a format 8 stream sends a kept program run's scalars as a `scalars`
op; neither needed a change. `ProgramRecipe.stroke_vertices` now keeps the
count of the last frame scale it was asked (3.5 µs a program a frame, 0.7
ms on the bumper play below, in every program mode).

**A program never hides another writer** (the review's finding, in every
mode since B3). A program is drawn from its own sources' rows, while the
CPU path of a creation or a rotation writes only the points and what
derives from them, and keeps what else the member holds. So where something else wrote the member earlier in
the frame, or between frames, the program drew over it: a `Transform`
filling a ring and a `ShowCreation` of it in one play, the creation listed
second, drew the ring unfilled (185/255 on 3.9% of the pixels, and the same
under Phase B's `gpu`), and a `VFadeIn` listed before a `ShowCreation`
drew nothing of the curve, the creation's start being the curve as the
fade's begin left it, at opacity 0 (195/255 on 0.4%, inside the gate's
fraction). Now an animation records a program only over a member it left
as it is: `programs.stamp` notes its family's revisions at the end of its
begin (after `Transform`'s locks, which bump them too) and after each of
its frames (`Animation.interpolate`), and `programs.admits` compares the
member's revision with the note, so a frame after another writer's is the
CPU path's, which composes the two as programs off does. A state change
moves the revision too and so costs a program where none was needed, the
safe side. `DrawBorderThenFill` asks before its own index-transition
write, and `Rotating` counts every frame for its first-frame box, since a
program may now follow CPU frames. The episodes' plays keep every program
they had: the counts below, measured with the rule, are the review
draft's.

**Proof.** Pixels, natively, programs off against strokes, Phase A, ten
alphas a case: the stroke-only cases (a creation of axes, a curve and a
dashed line; an uncreation; fades in and out; a rotation and a 3D
rotating; a curve blended into another, a fade in and a fade out; a write
and a draw-border-then-fill; a passing flash; a gradient curve's creation
and a gradient ring's fade; a fade and a creation of one curve) and those
that mix in a filled square and a word (a creation, a rotation, a blend,
a lagged write and draw-border-then-fill of a group holding the curve,
and a fill and a creation of one ring;
`LibraryPixels.test_stroke_cases_match_the_cpu_path_on_phase_a`), and a
curve, a ring and a dashed line blended into their targets
(`ProgramPixels.test_paths_without_fill_on_phase_a`): the gate at every
alpha, each case sending the programs it should (none for the rotation of
a group holding the square, none where two animations write one member),
and to 1/255 on every case but the lagged write and draw-border-then-fill
(`STROKE_TIPS`): there the curve's partial path ends mid-curve at
sub-alphas where the partial kernel places the tip in float32, a pixel or
two from the CPU's float64 one, 2/255 on one pixel and 12/255 on two (17
under Phase B's `gpu`, whose kernel it is). The two cases where two
animations write one member are exact, and fail (185 and 195/255) without
the revision rule. `LibraryAnimations.test_a_second_writer_keeps_the_cpu_path`:
five such plays (a fill or a fade with a creation, either order; a move
with a `Rotate`) under Phase B's `gpu` and under strokes, the member's
rows and flags programs off's at every frame, with nothing pending; seven
of the ten fail without the rule. Every frame of the seven plays below,
natively (`play_frames.py --render`, 99 frames): largest channel
difference 0 (the bumper's squares are the background's colour until the
flicker fills them, so its frames prove nothing but the others' do).
`StrokePrograms`: the state after every case is programs off's; only
strokes carry programs and nothing is a patch; a filled member's frames
are the CPU path's, frame by frame; a play that writes no outline reads
no rows (a write reads once per member at its index transition, as under
Phase B; the gradient creation read one a frame in the draft); a stream
sends the programs' scalars as ops and splices only the CPU's batches.
`StrokeProgramsLockstep`: the retained frame's bytes are the whole-frame
path's through a play of a creation, a rotation, a fade in and a filled
leaf's move, as full frames, as a format 8 stream and under verification,
each program leaf prepared every frame and every leaf kept on the still
after the landing. The browser: `strokeProgramsWire` (real Phase A frames:
every kind evaluated and finalized, each program's stroke drawing its
finalized instances, the filled square's stroke its own rows, no patch
stage; another alpha re-evaluates from the same sources into the same
outputs, the same alpha evaluates nothing, and a frame without them
retires them) and `deltaEqualsFull` over a Phase A history whose play is
programs (same slots, buffers and submissions after every message). The
golden pin, which clears the switch, has not moved.

**Gate** (`serialize_scene` over every frame of a play, Phase A, retained
frame on, `MANIML_GPU_TIMESTAMPS` unset; `benchmarks/play_frames.py`, each
replay of a play under one mode, the two taking turns replay by replay, six
replays each, each through its own cache; each frame's median over its
replays, then the median over the play's frames after its first, the
entry, reported apart; `benchmarks/results/b53_strokes_20260927/`, whose
README has the commands). A mode cannot rotate frame by frame as the
other harnesses' variants do, since an animation decides at its begin
whether it records programs. The GPU was 37-58% busy with another
application, which serialize does not use, one of Taylor's scene
processes ran, and the load was 2.8-4.2; PriceDiscovery ran through
B5.1's tree of links, its file having moved to `_archive/`. The plays are
the ones whose movers are most paths without fill, by a survey of every
play of both episodes under strokes (the movers and programs at each
play's middle frame, which the harness records as `movers: programs`);
only EpisodeB2's bumper is mostly strokes by count (its raster
wordmark's 211 squares fading in), and the axes, curve and dashed-line
plays are a quarter to a third strokes, their labels, numbers and titles
being glyphs:

| Play, by checkpoint (movers: programs) | format 8, ms | format 7, ms | wire a frame, format 8 |
| --- | ---: | ---: | ---: |
| EpisodeB2 1, line 35, the bumper's raster fade in (211: 211) | 9.57 → 7.42 (-22%) | 9.65 → 6.10 (-37%) | 172.7 → 6.1 KB |
| EpisodeB2 14, line 78, the recap's axes and curve (16: 3) | 2.86 → 2.80 | 2.84 → 2.77 | 122.0 → 120.6 KB |
| EpisodeB2 15, line 80, the recap's dashed price and drop (136: 48) | 11.89 → 11.45 | 11.91 → 11.15 | 230.8 → 221.8 KB |
| EpisodeB2 22, line 120, the axes with their labels (77: 18) | 12.92 → 12.74 | 13.15 → 12.74 | 556.8 → 552.8 KB |
| EpisodeB2 279, line 806, three small axes and two supply lines (148: 38) | 24.99 → 24.47 | 25.01 → 24.21 | 1168 → 1159 KB |
| PriceDiscovery 1, line 202, the plaza's rim and dashed hub, the camera moving (36: 13) | 5.63 → 5.52 | 5.60 → 5.40 | 331.9 → 289.4 KB |
| PriceDiscovery 81, line 1179, rays and marks fading out (42: 10) | 2.20 → 2.00 | 2.16 → 1.92 | 112.5 → 110.4 KB |

Where a play is strokes the serialize falls by a fifth (format 8) to a
third (format 7); where a third or less of the movers are strokes it
falls by 1-11%, since the glyphs' preparation is the rest (the review
draft's scratch run read 9.81 → 7.39 on the bumper, the same programs on
every play). The scene's own Python between two frames (the
interpolation and the updaters) falls on the bumper, 1.25 → 1.03 ms, and
holds elsewhere. What a program still costs Python on the bumper (the
review draft's instrumented medians, a scratch run): the frame 9.91 →
7.76 ms, of which the preparation 9.66 → 2.83 (the 211 stroke reads, 6.1
ms, gone; the programs' draws 1.05) and the encode 0.22 → 4.70: a program
is a batch of its own where the CPU's strokes are one coalesced run, so
its descriptor is encoded every frame (211 descriptors 2.33 ms) and the
stream compares it (1.11 ms). A program run keeping its descriptor, with
its scalars an op, is the lever there, the one B5.1 named for rows.

**The negatives.** The play's entry costs more: its first frame packs,
hashes and summarizes every program's sources (bumper 10.5 → 23.3 ms, the
other EpisodeB2 plays +0.2-2.4 ms). Format 7 carries a descriptor per
program, so its frames grow where strokes are a minority (EpisodeB2 15:
237 → 255 KB). And the GPU and the native render pay per program, as
B5.1's rows did per rows: each program is a compute pass of its own with
two dispatches, and strokes makes the complete native frame dearer on
every play measured (`--render`, four replays each, the GPU shared, so
read these against each other only): native `render()` through its
readback on the bumper 6.06 → 40.35 ms and the complete frame 15.9 →
47.2; on EpisodeB2 279 render 37.3 → 43.0 (minima 9.9 → 16.4) and the
complete frame 63.1 → 68.7; the other plays +1.3 to +5.0 ms complete. In
the attribution run (`MANIML_GPU_TIMESTAMPS=1`) `gpu_total` is 3.09 →
15.70 ms on the bumper, 12.66 of it the 211 `programs` passes, and 10.7
→ 13.7 on EpisodeB2 279 (38 passes, 2.0 ms). The browser's JavaScript
(`--browser`, the fake device, main realm, five rounds): the bumper 0.13
→ 0.93 ms a frame under format 7 and 0.12 → 0.50 under format 8, with 211
compute passes and 422 dispatches where there were none and 172 KB
uploaded → 3 KB, its entry 0.8 → 6.9 / 8.5 ms; every tab pays the format
7 figure while any client of the viewer has not negotiated format 8.
EpisodeB2 279: 2.65 → 2.80 (format 7), 2.70 → 2.68 (format 8). The
browser's GPU was not measured. The fix is the one B5.1 deferred: one
dispatch per kernel over a frame's programs and rows, in both drivers.
Until then strokes saves Python and costs the GPU, more than it saves in
the complete native frame on every play measured; no default flips.

## The flips

B5.4 (2026-09-28, on `b4-integration`). First the flips were made
expressible without losing Phase A, then each was measured on its gate in
the plan's order, and a default flipped only where its gate passed. The
gates were set with the increment: nets on pixels against grids and the
complete frame within 5% of grids; patches on Taylor's gate (confirmed
2026-09-27), the browser-side complete frame at or below Phase A's on both
episodes, per class, and pixels within 0.5% of Phase A; programs on the
program pixel gates, Python ms per play frame lower than without programs
on the episodes' plays, and play-frame pixels within 0.5% of the CPU path.

**Four renderer names.** `geometry.RENDERERS` is `triangles`, `phase_a`,
`phase_b` and `winding`. `triangles` is the **default** stack: the Phase A
driver fed what the generators' defaults select (`geometry.DEFAULT_FILL`,
`geometry.DEFAULT_SURFACE`, `programs.DEFAULT_MODE`), each overridden by its
environment flag, as before; native capture and the export recorder draw
it, so a flip reaches them. `phase_a` forces Phase A (meshes, grids,
programs off) and `phase_b` the whole Phase B stack (patches, nets, GPU
programs), whatever the defaults or the environment say
(`geometry.FORCED_STACKS`); `winding` is Original 2D. The viewer's selector
reads Default / Phase A / Phase B / Original 2D, and a forced selection
sets the program override its plays need (`off` or `gpu`); the default
follows the environment.

**The pin holds the forced names.** `tests/test_retained_frame.py` pins
`phase_a` and `phase_b`, so no flip can move a pinned byte. Phase A's frames
are stamped `triangles` in their header, the bytes Phase A always wrote:
its 251 digests, recorded under the key `triangles`, are unchanged, and the
goldens' key was renamed `phase_a` (a rename checked to leave every digest
as it was, not a re-recording); every recording names no other renderer
either. The pin also states the program mode its plays were recorded under
(`MANIML_PROGRAMS=off`) instead of inheriting the default, since an
animation decides at its begin whether it writes programs, and a flipped
`programs.DEFAULT_MODE` would otherwise have its plays record them. The
price of the stamp is in the page's selection, which drops another
selection's frames by the header's name: Phase A reads the frames stamped
`triangles` (`FRAMES_OF` in `renderer_selection.js`), so a frame of the
default still in flight across a switch to Phase A, or back, is drawn once
before the switch's full frame (a new epoch) replaces it; the default
differs from Phase A only by flips gated on pixels. `phase_b` keeps its own
stamp. Every harness variant keeps meaning what it measured whatever the
defaults are: `gpu_border` and `cpu_border` (`gpu_borders`,
`episode_frames`) and `browser_frames`' `phase_a` serialize `phase_a`;
`patch_fill` pins patches alone (grids, programs off, records); the new
`nets` (`episode_frames`) and `phase_a_nets` / `phase_a_patches`
(`browser_frames`) are Phase A with one flip; `episode_frames` runs its
plays with programs off (all its variants draw none) and `play_frames` pins
its stack as before. Proof: the golden pin (with PriceDiscovery through the
tree of links), `test_renderer_selection` (Phase A's stack and bytes under a
flipped environment and flipped defaults, the default following both, the
override set and cleared), `renderer_selection.cjs` (four modes, three one
driver: Phase A draws `triangles` frames only, Phase B its own),
`renderer_negotiation.cjs` (the shipped page adopts and chooses Phase A),
`test_web_viewer.DeltaStreamE2E` (a switch to Phase A is a full frame of a
new epoch stamped `triangles`) and `test_episode_frames` (each variant's
stack under flipped defaults).

**The instrument.** `benchmarks/flip_gates.py` (new, with
`tests/test_flip_gates.py`) measures what the fill and surface flips are
judged on: its `serialize` command times the two stacks as a viewer's cache
pays them (format 7 and a negotiated format 8 stream, the four serializers
taking turns as first readers of what moved), and `complete` adds, per frame,
`browser_frames`' `page_ms` and the median `gpu_total_ms` of two pooled
`episode_frames` attribution runs, charging a format 8 frame the stream did
not send its serialize alone. `episode_frames --camera-moves` gives a camera
move GPU rows of its own (rounds of `browser_frames`' pan, 2% zoom and the
camera put back), which the nets flip needed: a net is re-evaluated when the
frame scale or the pixels per unit change, that is on a zoom, never on a pan
or an orbit, and borrowing the still redraw's GPU for a move would have hidden
exactly that cost. `tests/surface_fixtures.py` collects the scenes that draw
a Surface (the renderer and quality fixtures draw none), and
`play_frames --every-play` measures every play of an episode for the
programs flip, so no survey chooses them. The recipe is in
`benchmarks/README.md`, "Flip gates"; every run is archived in
`benchmarks/results/phase_b_flips_20260927/`.

Three corrections from the increment's review are in the instrument and the
numbers below. **A play's pixels were its landing.** `episode_frames`
compared a play's last sampled frame, and a play of 15 frames or fewer is
sampled to its end, the landing, which is the pausepoint's own picture: on
these scenes 47 of the 50 plays compared were compared there, so beyond the
orbit demo's two plays and one of EpisodeB2's, nothing moving had been held
to Phase A. A play's pair is now
the worst over every frame of its sampled window strictly inside it
(`pixel_frames`, the warmups included), and `complete` counts each frame
once. **The programs verdict leaned on the turn order.** `play_frames` opened
every play with programs off, and the first replay of a play is the first to
run it after the play before; the reduction treated the plays that record no
program as running the same code in both modes and read their ratio as the
harness's bias, but under `strokes` every animation's begin still walks its
families to decide (`programs.begin`) and every frame notes their revisions
(`programs.stamp`). Run the other way round, the order effect was half a
percent on EpisodeB2 and of the opposite sign on PriceDiscovery. The opening
mode now alternates play by play, and the gate reads the order-balanced
ratio (the geometric mean of the ratio over the plays each mode opened, with
a 95% interval from resampling them). **The stamps overstate a stack of
more passes.** The complete frame takes its GPU from the attribution runs,
as Taylor's gate says, while the measuring contract takes gate numbers from
runs without the flag, since each stamped pass costs ~30 µs; where a flip
makes an object a pass of its own (a net, a program) the two disagree, and
`complete` now quotes beside the verdict the same frames with the GPU part
the flag-off wall clock from the submit through the full readback
(`flag_off_check`), which has no stamps but dilutes every ratio with the
readback both stacks pay. The verdict is read on the gate as written, and
where the check would change it, that is said.

**The verdicts.** No default flipped: the Default renderer draws Phase A's
stack, as before, and Phase A, Phase B and Original 2D stay selectable.
(B5.5, below, took the nets gate again after one dispatch: it passed on
the gate's three scenes and failed on scenes that are mostly surfaces, so
grids stay the default. B5.7 drew each net's steps and coalesced them as
grids are, and took the gate over a timed set that holds two such scenes:
it fails there still, on still and camera frames and the lattice's
pixels, so grids stay.)

| Flip | Gate | Measured | Verdict |
| --- | --- | --- | --- |
| B2 nets (`MANIML_SURFACE`) | pixels ≤ 0.5% over 24/255 against grids on every Surface fixture and every measured frame that draws one; complete frame ≤ 1.05× grids | pixels ≤ 0.28% (fixtures), ≤ 0.31% (271 episode frames, 245 of them inside plays); format 8 stills, ticks and plays ≤ 1.05× but the orbit demo's 0.17 ms still (1.055×); camera moves 1.25-1.34× in all three scenes (1.13-1.33× with the GPU part flag off) | **fails**: `grids` stays |
| B1 patches (`MANIML_FILL`, records packed) | complete frame ≤ Phase A's per class on both episodes; pixels ≤ 0.5% | pixels Phase A's but two pixels (287 frames, 263 inside plays); format 8 plays 1.15× (EpisodeB2) and 1.48× (PriceDiscovery), ticked 1.14× and 1.10× (plays 1.16× and 1.30× with the GPU part flag off) | **fails**: `meshes` stays |
| B3 programs, as `strokes` (patches did not flip) | the program pixel gates; Python ms per play frame lower than programs off on the episodes' plays; play pixels ≤ 0.5% against the CPU path | pixel tests pass; 4,004 play frames within 1/255; Python per play frame, order-balanced, -0.03% (EpisodeB2, format 8; -0.30% to +0.20%), +0.05% (format 7), +0.32% (PriceDiscovery, format 8; +0.08% to +0.53%) and +0.08% (format 7); the native complete frame +1.8% and +1.4% | **not met**: not lower in three of four; `off` stays |

**B2 nets: the gate fails, on camera moves; grids stay the default.** The
pixels pass everywhere: every Surface fixture within 0.28% of pixels over
24/255 of grids (`tests/surface_fixtures.py`, 13 fixtures; the worst is the
70-sphere orb grid, then the default sphere at 64×, 0.17%, where the net is
the more correct of the two), and every frame compared in the three scenes
that draw a surface within 0.31%: 271 frames, the 26 measured pausepoints
and 245 frames strictly inside their plays (EpisodeB3 0.026%, at a
pausepoint; B4 0.023%, mid-play; the orbit demo 0.31%, mid-play, largest
channel 50/255, whose last sampled frame, the only one compared before,
read 0%). The complete frame in format 8, the stream the shipped page
negotiates, is within 5% of grids on every still, ticked
and play class but the orbit demo's still (0.17 → 0.18 ms, a still that
sends nothing), and a third cheaper on the orbit demo's plays, where a
moving surface costs grids a CPU evaluation nets do not need (serialize
4.50 → 1.48 ms); in format 7 EpisodeB3's still and ticked frames and B4's
still and plays read over too. It is 23-34% dearer on camera moves in all three
scenes, both formats, by the gate's GPU part; by the flag-off check, 13-33%
(format 8: the orbit demo 1.267, EpisodeB3 1.331, B4 1.132):

| Complete frame, flip / grids (format 8; format 7) | pausepoint | ticked | camera | play |
| --- | ---: | ---: | ---: | ---: |
| Orbit demo (2 frames, no updaters) | 1.055 (0.17 → 0.18 ms); 0.989 | – | **1.311; 1.295** | 0.676; 0.670 |
| EpisodeB3 (12 frames, 7-61 spheres) | 0.989; 1.339 ¹ | 1.011; 1.059 ¹ | **1.335; 1.334** | 1.038; 1.008 |
| B4 (12 frames, up to 479 spheres) | 1.025; 1.069 ¹ | 1.018; 0.986 | **1.245; 1.231** | 1.038; **1.063** |
| The same, flag-off check (the three scenes) | 1.055, 0.989, 1.025; 0.928, 1.027, 1.003 | 1.011, 1.018; 1.006, 0.992 | **1.267, 1.331, 1.132; 1.256, 1.326, 1.132** | 0.791, 1.018, 1.043; 0.787, 0.999, **1.055** |

¹ The GPU medians differ where the minima agree (EpisodeB3's still 0.994
and ticked 1.011 by each frame's minimum, B4's still 0.923): the GPU clock,
not the nets; the flag-off check reads them within the limit too. B4's
format 7 plays are over (1.063; 1.055 by the check), their serialize 21.8 →
22.8 ms.

The camera cost is the zoom, and it is the GPU's. A net is re-evaluated when
the frame scale or the pixels per unit change (its evaluation state in both
drivers), so a pan or an orbit costs it nothing and a 2% zoom re-evaluates
every net on screen, each in a compute pass of its own: on EpisodeB3 a zoom
adds ~1.8 ms of `nets` passes (GPU 7.7 against 5.0-5.4 ms, median, both
attribution runs), and on B4's heaviest frames (checkpoints 114, 133 and
174, up to 479 spheres) the attribution runs read 23-24 ms more GPU (31.3
against 8.2 ms at checkpoint 114), which overstates it: each stamped pass
costs ~30 µs, and the flag-off wall clock from the submit through the full
readback, which holds that GPU work and the readback besides, is 27.9
against 10.2 ms there. By flag-off wall clock a zoom costs nets 16-19 ms
more on those frames (both flag-off runs), still 2.4-3.2 times Phase A's
zoom there. The gate as Taylor set it takes its GPU part from the
attribution run, and the measuring contract takes gate numbers from runs
without the flag; for a flip that changes the pass count the two disagree,
which is why both are quoted, and the camera class fails by either. Most of
that work produces what is already there: `net_compute.wgsl` depends on the
camera only through a net's integer step count (`ceil(sqrt(density ×
pixels_per_unit / frame_scale))`, at least 2, at most the capacity), which a
2% zoom rarely moves. The levers, for the increment that takes nets up
again: key a net's evaluation on its step count rather than on the camera,
so a zoom that moves no step count evaluates nothing; and evaluate a
frame's nets in one dispatch, the fix B5.1's rows and B5.3's programs
already wait on. The orbit demo's format 8 still costs nets 0.01 ms more
to serialize, in both runs alike, for a frame that sends nothing: over the
limit, below any frame's noise, and not what holds the flip.

**B1 patches: the gate fails on both episodes; meshes stay the default.**
Measured with the records packed (`MANIML_PATCH_SOURCE=records`): the
increment put rows on the wire only if B5.1 had passed its gate, and B5.1
missed it (a mover at the cost of a memcpy: 51.6 ms against the 2.65 ms
floor), so rows were not measured here. Pixels are Phase A's over the 24
measured pausepoints and the 263 frames strictly inside their plays: two
pixels in all are more than 24/255 off, one of PriceDiscovery's checkpoint
130 (27/255, at the pausepoint and the first frame of its play) and one of
a frame inside EpisodeB2's play into 8.a (30/255), each 0.00004% of its
frame. The complete frame is not (the flag-off check fails every class the
gate fails in format 8, and PriceDiscovery's camera moves besides, 1.056;
in format 7 it passes PriceDiscovery's still and ticked frames, 0.999 and
0.991):

| Complete frame, patches / Phase A (format 8; format 7) | pausepoint | ticked | camera | play |
| --- | ---: | ---: | ---: | ---: |
| EpisodeB2 (10 still, 2 ticked; 114 play frames) | **1.014; 1.114** | **1.138; 1.391** | **1.072; 1.080** | **1.148; 1.151** |
| PriceDiscovery (1 still, 11 ticked; 100 play frames) | 0.982; **1.380** | **1.104; 1.174** | 0.964; 0.969 | **1.477; 1.433** |

The plays are the serialize's: 7.61 → 10.34 ms (EpisodeB2) and 3.58 →
6.28 ms (PriceDiscovery) a play frame at the median, a mover's curve records
packed every frame it moves, while the page's JavaScript is the same (0.71
→ 0.55, 0.19 → 0.19 ms) and the GPU nearly so (4.15 → 4.51 ms; 3.90 → 3.02).
EpisodeB2's two ticked frames (3.i and 8.a) send nothing in format 8
either way and pay the serialize alone (3.35 → 3.82 ms, their median; 8.a's
5.45 → 6.19), and its stills, which send nothing either, 0.70 → 0.71 ms.
Camera moves go both ways: patches have no mesh to
revalidate at a zoom (serialize 2.06 → 1.31 ms on EpisodeB2) but cost
EpisodeB2's GPU more (4.50 → 5.71). Format 7's stills are the GPU's (the
page redraws the frame, and a patch frame's passes cost 3.24 → 4.29 ms on
EpisodeB2). B5.1's rows halve the 8.a play's serialize at ~10 ms more GPU a
frame; whether they close the play gap is the measurement to take once one
dispatch finalizes a frame's rows.

**B3 programs, as `strokes`: the gate is not met; programs stay off.** The
gate named `gpu`, which needs the patch fill; with patches not flipped,
`strokes` (B5.3), the one program Phase A draws, was evaluated in its place.
Its pixels pass: the program pixel gates (`LibraryPixels`,
`ProgramPixels` under `MANIML_TEST_GPU=1`, 5 tests OK), and every frame of
every play of both episodes drawn natively under strokes against programs
off, 2,598 + 1,406 frames, largest channel difference 1, no pixel over
24/255. Its Python is not lower. Python ms per play frame
(`play_frames --every-play`: each frame's `serialize_ms` plus the scene's
own Python since the frame before, over every frame of all 223 plays of
EpisodeB2 and 106 of PriceDiscovery, four replays a mode in format 8, two
in format 7, the modes taking turns replay by replay and the mode that
opens a play alternating play by play), read order-balanced (the geometric
mean of the ratio over the plays each mode opened; 95% intervals from
resampling them), over every play, over the plays where strokes records a
program and over the rest:

| Python ms per play frame, off → strokes | every play (plain) | order-balanced (95%) | each opener: off first; strokes first | plays recording a program | the rest |
| --- | ---: | ---: | ---: | ---: | ---: |
| EpisodeB2, format 8 | 15.355 → 15.350 (-0.03%) | -0.03% (-0.30% to +0.20%) | -0.39%; +0.34% | -0.13% (-1.03% to +0.67%), 67 plays | +0.04% (-0.16% to +0.23%), 156 plays |
| EpisodeB2, format 7 | 15.382 → 15.388 (+0.04%) | +0.05% (-0.44% to +0.55%) | -0.60%; +0.70% | -0.51% (-1.68% to +0.42%) | +0.21% (-0.29% to +0.74%) |
| PriceDiscovery, format 8 | 9.385 → 9.416 (+0.33%) | **+0.32% (+0.08% to +0.53%)** | +0.23%; +0.41% | +0.30% (+0.04% to +0.55%), 61 plays | +0.38% (-0.02% to +0.72%), 45 plays |
| PriceDiscovery, format 7 | 9.505 → 9.518 (+0.13%) | +0.08% (-0.85% to +0.98%) | -0.27%; +0.44% | +0.01% (-1.08% to +0.67%) | +0.13% (-1.42% to +1.49%) |

Strokes is lower in one of the four, EpisodeB2 in format 8, by 0.03% with
an interval on both sides of zero, and higher in the other three, on
PriceDiscovery in format 8 measurably. The mode that opens a play reads
dearer in all four, by 0.1-0.65% (half the gap between the two openers'
ratios; the play's first replay is the first to run it after the play
before), which is why the order-balanced ratio is the one read:
the first pass opened every play with programs off and read every total
lower by 0.07-0.68%, and read the plays that record no program as running
the same code in both modes, which they do not (under strokes every
animation's begin walks its families to decide, `programs.begin`, and every
frame notes their revisions, `programs.stamp`; balanced, that costs the
rest of the plays +0.04% to +0.38%, no interval clear of zero but
PriceDiscovery's in format 8 nearly). The review's own rerun (format 7,
every play opened by strokes, paired with the first pass's run) read
EpisodeB2 -0.26% (-0.55% to -0.02%) and PriceDiscovery -0.25% (-0.70% to
+0.17%) balanced; this re-take reads +0.05% and +0.08%. Both put the
programs' effect on these episodes' Python within about half a percent of
nothing: a program saves Python where a play is mostly strokes (the
bumper, -22% in B5.3), and the 67 and 61 plays that record one are mostly
glyphs and fills, where a stroke's saving is lost in the frame and its
entry costs more (the entries' total +1.1% and +0.6% in format 8). The
cost B5.3 measured stands, now over every play and order-balanced: the
native complete frame (`serialize_scene` + `render()`, one replay a mode)
is 1.8% dearer on EpisodeB2's plays (+0.9% to +3.2%) and 1.4% on
PriceDiscovery's (+0.4% to +2.3%), 6.4% and 2.4% on the plays that record a
program, the bumper's `render()` 11.2 → 42.0 ms a frame on average (7.1 →
38.9 at the median after its entry), each program a compute pass of its own. The levers are B5.3's: one dispatch per kernel over a
frame's programs, and a program run that keeps its descriptor with its
scalars an op.

### B5.5: a frame's nets in one dispatch, and the nets gate again

B5.5 (2026-09-28, on `b4-integration`) took up the two levers B5.4 named
for the nets flip, in both drivers, then took B5.4's B2 gate again as B5.4
ran it. **Every class passed on the gate's three scenes, and the default
stays `grids`**: the fix pass took the same recipe on scenes that are
mostly surfaces, and there nets fail still and camera frames by 16-52%,
and a 480-sphere scene fails the pixels too (below, "Where the gate's
scenes stop"). The cost left is the redraw, not the evaluation. Nets stay
what the Phase B selection draws and what `MANIML_SURFACE=nets` selects;
`geometry.DEFAULT_SURFACE` is unchanged. The archive is
`benchmarks/results/b55_nets_one_dispatch_20260928/`.

**What a net's output depends on.** `net_compute.wgsl` read the camera only
to choose a net's step count (`ceil(sqrt(density × pixels_per_unit /
frame_scale))`, at least 2, at most the capacity), and both drivers keyed
an output's evaluation on the frame scale, the density and the pixels per
unit, so a 2% zoom evaluated every net on screen again to write the
vertices it already held. The drivers now decide the steps themselves
(`gpu_net_geometry.evaluation_steps`, `netSteps` in `webgpu.js`: the same
rule in double precision from the descriptor's density and the uniforms
as packed, float32 y rescale factor and frame scale, so both reach the same
integer; `netWire` holds the page's to Python's on real frames) and the
kernel reads them from its table rather than the camera. An output is a
function of its control points, its capacity and its steps, and is
evaluated again only when its steps or its source move (a new net, a
program's new state, a slot's output taken over): a pan or an orbit never
moved it, and a zoom that moves no step count evaluates nothing either.

**One dispatch.** The nets whose state moved in a frame are evaluated
together: their control points gathered into one scratch buffer (each
source once, a net's own or a program's evaluated rows), one dispatch over
a table of eight words a net (source and output offsets, the shape, the
capacity, the steps, its first patch, after a four-word header; one
workgroup a patch, found by the patch starts) into a second scratch
buffer, and each net's vertices copied into the output its slot owns, so
the render pass draws the buffers it drew before (tier 2's ownership). A
net alone in its dispatch (a frame's one changed net, or one larger than
the budget) is read and written in place, without the copies. A dispatch
of several stays within 32 MiB of each scratch buffer and the device's
storage binding limit, and past it the next dispatch reuses them; the
scratch grows by powers of two and is kept while frames draw nets. Where the
native driver made a parameter buffer, a bind group and a compute pass for
every changed net, and the page a pass and a parameter write, a frame now
writes one table and records one pass (one per 32 MiB of scratch), and the
native driver packs a net batch's uniforms once per set of overrides in a
frame rather than once per net, before the submit. Natively, drawing the
Surface fixtures' 70 orbs, a 2% zoom's `render()` goes from 10.7 ms (70
passes) to 5.7 ms (nothing evaluated, the still frame's cost), and a zoom
that moves every net's steps from 11.9-13.5 to 7.7-8.9 ms (one dispatch).

**What pass 1 found, and the serializer.** Taken with the drivers' change
alone (pass 1), the gate passed every class but four, all of them the
serializer's Python: the orbit demo's still in format 8 (1.074, 0.18 →
0.19 ms for a frame that sends nothing: seven nets are eight runs where
grids coalesce into three) and B4's camera moves (1.068; 1.077) and format
7 plays (1.057), where every net's leaf takes its reservation again on a
move (`NetRecipeCache.source`: the pixels per unit through a numpy array,
the step rule in numpy scalars, three validations; 0.37 ms a B4 camera
frame at the median, up to 2.0 ms on its 479-sphere frames). So the
serializer was made cheaper there, byte for byte the same: the pixels per
unit as `float()` of the element, the step rule and the output cap memoized
on their arguments (equal spheres share a density), the reservation
unchecked where the cache made its inputs, `finish_frame` sweeping nothing
when every entry was used (the count kept as entries are stamped), a kept
run's `SentBatch` reused across frames and compared by identity, and
`MessageParts.carry` reading its memo tables from a map. On B4's heaviest
camera frame the nets' extra serialize fell from 1.39 to 0.53 ms, and on
the orbit demo's still from 7-8 to 6 µs. Proof: the golden pin (both
episodes, under the default, `MANIML_VERIFY_LEDGER=1` and
`MANIML_RETAINED_FRAME=0`) and `NetCacheSweep` (the count, the sweep, the
memoized rules against the rules). Then every run was taken again (pass
2), and pass 2 is the verdict.

| Complete frame, nets / grids (format 8; format 7) | pausepoint | ticked | camera | play |
| --- | ---: | ---: | ---: | ---: |
| Orbit demo, B5.4 | **1.055**; 0.989 | – | **1.311; 1.295** | 0.676; 0.670 |
| Orbit demo, B5.5 | 1.037; 0.990 | – | 0.997; 1.002 | 0.696; 0.700 |
| EpisodeB3, B5.4 | 0.989; **1.339** | 1.011; **1.059** | **1.335; 1.334** | 1.038; 1.008 |
| EpisodeB3, B5.5 | 1.010; 0.999 | 1.016; 1.013 | 1.020; 1.021 | 1.017; 1.008 |
| B4, B5.4 | 1.025; **1.069** | 1.018; 0.986 | **1.245; 1.231** | 1.038; **1.063** |
| B4, B5.5 | 0.988; 1.004 | 0.999; 0.999 | 1.037; 1.046 | 1.014; 1.022 |
| The same, flag-off check (the three scenes, B5.5) | 1.037, 1.010, 0.988; 0.997, 1.005, 1.002 | 1.016, 0.999; 1.002, 1.000 | 1.004, 1.006, 1.018; 1.009, 1.006, 1.026 | 0.766, 1.008, 0.997; 0.770, 1.001, 1.004 |

The camera class's parts in format 8 (serialize + page + GPU, ms): the
orbit demo 0.23 + 0.09 + 3.87 against 0.24 + 0.12 + 3.81, EpisodeB3 1.49 +
0.10 + 6.88 against 1.52 + 0.11 + 6.98, B4 1.84 + 0.11 + 7.61 against 1.98
+ 0.15 + 7.81 (B5.4: 1.95 + 0.11 + 4.64 against 2.29 + 0.16 + 6.16; the
GPU clock follows the load, so only the ratios compare across runs). The
nets pass now costs nothing on most camera frames and 0.05-0.14 ms on the
few where a 2% zoom moves some net's steps; per frame the two stacks' GPU
medians differ by up to 1.4 ms either way, the noise their median
difference (-0.04 to +0.16 ms in the three scenes) sits in. The nearest class to the limit is
B4's camera in format 7 (1.046), whose GPU part by each frame's minimum
reads 1.086; 1.109 (`ratio_gpu_min`), the minima of the two stacks' rows
differing where their medians do not; the flag-off check reads 1.018;
1.026. Pixels: the Surface fixtures B5.4's exactly (worst 0.28%, the orbs),
and 271 episode frames (245 inside plays) at most 0.31% over 24/255 (the
orbit demo, mid-play), all within 0.5%.

**Pixels, and the two drivers.** The kernel's arithmetic is unchanged and
the steps come out the same on these frames: every Surface fixture, and a
zoom walk over the default sphere and over the orbs drawn frame by frame by
one driver and each frame by a fresh one, are bit-identical to B5.4's
driver (53 images, 0 pixels differ). `NetEvaluationOnTheGpu` gains a case:
70 nets in one dispatch are pixel for pixel what 70 dispatches in place and
several dispatches sharing the scratch draw; a pan and 2% zooms evaluate
nothing; after each move the kept outputs draw what a fresh driver draws,
a zoom out that keeps the larger reservation included. In the page,
`netWire` (real frames: both nets in one dispatch, gathered and copied
out; a pan and a zoom that move no step count evaluate nothing; one that
moves them evaluates both in place, at Python's steps),
`netsInSeveralDispatches` (a device whose storage bindings hold two nets'
vertices: three dispatches, each net from its own source into its own
output, tracing as one dispatch does) and `generationFollowsItsInputs` (the
table carries the steps; a density or a zoom that leaves them evaluates
nothing, one that moves them evaluates again, capped at the capacity). The
trace (`webgpu_trace.cjs`) now places a net's token and a copy's on the
byte span they write, so a net evaluated alone in place and one gathered
among others and copied out trace alike, and a stale or misplaced output
does not: a state without its steps, or a scatter copy from the wrong
offset, fails `retainedFramesDrawWhatFreshDriversDraw` (and natively the
new GPU case). The command harnesses changed where the design did: a net's
evaluation is no longer a pass of its own (`netEvaluations` follows the
gather and scatter copies), `slotsReuseAcrossFullFrames`' camera move
evaluates no net (its steps stay two), `generationFollowsItsInputs` reads
steps from the table, and the fake device checks the net table and every
copy's usages, alignment and bounds. The recording player draws with the
same driver; its cases and the Phase B exports' replays are unchanged and
pass.

**Where the gate's scenes stop.** In the three scenes the gate was set on,
surfaces are a small share of the frame: EpisodeB3's and B4's spheres do
not coalesce under grids either, and at B4's checkpoint 114 the camera
frame's GPU is 12.72 ms with nets against 12.63 with grids (the review's
measurement). A flip of the
default reaches every scene the Default, `--render`, checkpoint stills and
`--export` draw, so the fix pass's review took the same six commands per
scene (MANIML_* unset; at every start three samples of the GPU, 0-6% but
for a first one of 32-44% taken as the run before ended; load 1.9-2.8) on
four more (`surface_scenes.py` in the archive), and the fix pass took the
two that failed again the same way (0-6% but for first samples of 33% and
49%; load 2.4-5.5): the orbs of
`tests/surface_fixtures.py` as a scene (70 spheres, 1920×1080, the
episodes' agents), a lattice of 480 small spheres, and two controls, F1's
Cobb-Douglas surface over its axes and a translucent sphere and torus.

| Complete frame, nets / grids (format 8; format 7) | pausepoint | camera | play | pixels over 24/255 |
| --- | ---: | ---: | ---: | ---: |
| Orbs, 70 spheres (review) | **1.281; 1.163** | **1.194; 1.211** | 0.873; 0.878 | 0.356% |
| Orbs (fix pass) | **1.305; 1.162** | **1.196; 1.215** | 0.851; 0.858 | 0.356% |
| Lattice, 480 spheres (review) | **1.505; 1.373** | **1.438; 1.524** | 0.784; 0.781 | **0.979%** |
| Lattice (fix pass) | **1.500; 1.366** | **1.435; 1.523** | 0.801; 0.793 | **0.979%** |
| Cobb-Douglas (review) | 0.998; 1.004 | 1.005; 0.996 | 1.018; 1.018 | 0.061% |
| Translucent (review) | 1.039; 0.972 | 0.978; 0.978 | 0.490; 0.491 | 0.094% |

The flag-off check reads the same way (orbs camera 1.29-1.31, the lattice
1.31-1.38). The orbs' format 8 still is Python's, a frame that sends
nothing (0.18 → 0.23 ms: seventy nets are seventy runs where grids
coalesce into one); every other failing class is the redraw. A net draws
the triangle pattern of its capacity, not of its steps: the index buffer
is `net_indices(patches, capacity)` in both drivers (`webgpu.js`'s
`netIndices`, `wgpu_renderer._net_index_buffer`), and the reservation is
twice the steps, so at the orbs' steps (4 and 3 on capacities 8 and 6)
three quarters of a net's triangles have zero area. The orbs draw 290,560
triangles in 70 draws with nets against 19,840 in one coalesced draw with
grids; natively the render pass is +0.57 ms a frame for the orbs and +1.62
ms for the lattice, and the CPU encode 1.6-1.7 against 0.2 ms and 9.4
against 0.2 ms (the review's figures). In Chrome 154 a pan of the lattice
takes 5.3-5.5 ms from render to `onSubmittedWorkDone` with nets against
1.4-2.1 with grids. The lattice's pixels are silhouettes where the net is
the rounder of the two, and B5.4's driver draws them pixel for pixel the
same, so they predate B5.5; its plays pass (0.78-0.80: a moving net costs
Python its control points, not a CPU grid).

**What the default is, and what flips it.** `geometry.DEFAULT_SURFACE`
stays `grids`: the Default renderer, native capture and the export
recorder draw Phase A's stack, as B5.4 left them, and nets are the Phase B
selection's and `MANIML_SURFACE=nets`'s. The golden pin (which holds
`phase_a` and `phase_b`) did not move. Before the nets gate is taken again:
add a scene that is mostly surfaces to its timed set (the orbs as a scene,
say); draw each net with the index pattern of its current steps over the
`(capacity + 1)²` vertex layout (`patches × 6 × steps²` indices, one
pattern per patches, capacity and steps), which the driver can do now that
it decides the steps, so the reservation costs no triangles; and let net
batches that share a pipeline and uniforms coalesce into one draw, as grids
do. Patches (records packed) and programs keep B5.4's verdicts; their
levers are B5.1's and B5.3's, and the pattern here (one dispatch over a
table, keyed on what the output reads) is the one they wait on.

### B5.6: rows as the patch source

B5.6 (2026-09-29, on `b4-integration`). B5.1 proved a patch fill sent as its
path's rows pixel for pixel the records' and its serialize about half on
heavy plays, but left it behind `MANIML_PATCH_SOURCE=rows`, so the forced
Phase B the viewer's selection draws still packed records. Now rows are the
patch source wherever patches are drawn: `geometry.DEFAULT_PATCH_SOURCE` is
`rows`, read by the forced `phase_b` and by any stack that selects
`MANIML_FILL=patches`, and `MANIML_PATCH_SOURCE=records` is the explicit
override. The forced stacks fix the fill, the surface and the programs, not
how the bytes are made: they read the patch source as they read
`MANIML_BORDER_GENERATOR`, each another way to send the same pixels. Phase
A, the Default (meshes) and Original 2D send what they sent. The viewer's
Phase B option says what it draws (its `title`: fills as patches sent as
their paths' rows, surfaces as nets, animations as GPU programs).

**The pin states records; no golden moved.** The pin's phase_b digests were
recorded with the records packed, the default then. The pin clears its
switches, so without a statement they would follow the new default: 246 of
its 251 phase_b digests (every frame that draws a path) would move for a
change that moves no pixel. The pin now states `MANIML_PATCH_SOURCE=records`
beside `MANIML_PROGRAMS=off` (`GoldenCase`), and every golden passes
untouched. (A first pass of this increment re-recorded the 246 digests for
rows; the review sent it back, since the rule is that a golden is never
re-recorded.) Rows keep the pin's other guarantees through the classes that
already ran them: `RowSourcesLockstep` and `RowSourcesNavigation` (the
retained frame against the whole-frame path, byte for byte, with rows),
`PatchRowsPixels` (rows against records on the fixture corpus, drawn), the
export tests and the command mirrors. The pixels, three ways, all with a
largest channel difference of 0: every frame of the pin (251 phase_b
frames of the fixtures, quality fixtures, synthetic cases and both
episodes' goldens, each drawn natively as the pin's records frame and as
the selection's rows frame, which differ in bytes on 246); B5.1's
comparison taken again (EpisodeB2's 84 pausepoints and 23 frames of the
play into 8.a, PriceDiscovery's 24 and 9); and the retaken test point's
`phase_b_vs_records` pair (below: the twelve measured pausepoints of each
episode and 139 and 124 play frames).

**The harnesses measure the selection.** The instruments named for the
viewer's selections now measure what it sends: every harness's forced Phase
B takes the patch source out of the environment as its default does
(`browser_frames`' `phase_b_forced`, `episode_frames`' `phase_b_retained`
through `gpu_borders`' route `phase_b`, `test_point`'s `phase_b`). The
records packed are stated where an archive measured them:
`phase_b_forced_records`, `phase_b_retained_records` (with the pixel pair
`phase_b_vs_records`) and `test_point`'s fifth stack `phase_b_records`
reproduce B6's Phase B, and `browser_frames`' `phase_b` and
`phase_a_patches`, `episode_frames`' `patch_fill` (so `flip_gates`' patches
gate) and `play_frames` stay B5.1's and B5.4's. A patches flip taken again
would ship rows and wants a rows variant beside `patch_fill`. The program
tests' CPU path (`test_program_library`, `test_program_blend`) states
records too: with rows it was finalized by the same `row_finalize.wgsl` as
the programs' output, so a fault there cancelled on both sides (the
review's mutation, the fill border width dropped in the kernel, failed none
of their 22 GPU tests; with records stated it fails `LibraryPixels`' CPU-path
case, six subtests, and a blend test), and `LibraryPixels` adds the
viewer's Phase B (programs, the other paths as rows) against the same
reference.

**What it costs: B6's test point, retaken.** B6's recipe with five stacks
(`benchmarks/README.md`, "The test point"; 01:59-02:25, every run starting
with the GPU idle, load 1.45-3.60; the instrumented run left out). The
complete frame (serialize + the page's JavaScript + the native GPU), the
median per class, `phase_b_records` → `phase_b`:

| ms | EpisodeB2, format 8 | format 7 | PriceDiscovery, format 8 | format 7 |
| --- | ---: | ---: | ---: | ---: |
| pausepoint | 0.68 → 0.75 | 5.17 → 5.19 | 0.62 → 0.69 | 5.51 → 5.58 |
| ticked | 3.22 → 3.48 | 7.46 → 7.96 | 0.98 → 1.04 | 5.62 → 5.70 |
| play | 8.86 → 8.97 | 9.18 → 9.35 | 10.93 → 10.63 | 10.77 → 10.45 |

Today's (`main`'s page, format 7) for scale: 10.96 / 27.91 / 19.98 and 8.05
/ 11.49 / 11.93. Against the Default in format 8, Phase B's plays are 0.77×
on EpisodeB2 and 1.66× on PriceDiscovery (with records 0.76× and 1.70×; B6
measured 0.84× and 1.79× the day before). Where rows change a class:

- A still or ticked frame's serialize is higher on every measured
  checkpoint, 0.03-0.19 ms and 0.40 ms on 8.a ticking (format 8 sends
  nothing there, so that is the frame); the cause was not isolated.
- The plays split by what moves. 8.a's play, whose movers are not
  programs, is 127.25 → 80.52 ms in format 8 (serialize 105.21 → 51.91,
  page 4.30 → 4.48, GPU 17.75 → 24.13). The other plays, whose movers are
  programs, are within ±0.8 ms but for three short ones whose GPU part
  moved 1.7-1.9 ms either way; the class medians barely move.
- A navigation (`browser_frames`' first message after a restore, which the
  test point has no class for): the page's JavaScript 2.32 → 2.68 ms in
  format 8 on EpisodeB2 (3.24 → 2.48 in format 7) and 1.56 → 1.73 on
  PriceDiscovery (1.72 → 1.83); the message's serialize 27.26 → 18.74 and
  17.09 → 11.03 ms, its wire 898 → 380 and 407 → 308 KB; the page's compute
  dispatches 73 → 206 and 26 → 107. The native render pays the dispatches:
  walking the twelve pausepoints natively, four rounds a source, the
  complete frame of a navigation is 29.9 → 38.3 ms on EpisodeB2 (serialize
  7.4 → 6.8, render 22.1 → 31.1) and 25.0 → 28.8 on PriceDiscovery (6.4 →
  6.3, 17.7 → 21.5), and the still frame after it 13.0 → 11.8 and 11.6 →
  11.1.
- Pixels against Phase A without the retained frame are the same for both
  sources: EpisodeB2 0.0000% in every class; PriceDiscovery 0.0000% at its
  pausepoint and 0.0412% (142) ticked and in plays, where B6 measured
  2.024% (153) in plays before c787d9d1 fixed the program sources' base
  points.

**Why a navigation costs more: two causes.** Each driver finalizes every
changed rows with a dispatch of its own (B5.1's negative). And a path's
rows carry its paint (stroke and fill RGBA) and are keyed by content with
it, so a change of paint alone sends and finalizes them again and the batch
is no longer cached, where under records the curve records stay cached and
only the object table changes. Under the forced Phase B in format 7, one
cache per source: 258 → 277 (5.a) sends 463 batches, 176 of them cached
under records and none under rows, and of the rows 277 sends that the
receiver did not hold, 590 are rows sent at 258 point for point but for
their stroke and fill alpha (1.0 → 0.05, a dim); 277 → 157 caches 68 of 142
under records, none under rows. So two levers, in both drivers: one
dispatch for a frame's rows, as B5.5 made it for nets, which removes the
dispatches and not the resends or the finalizes; and the finalized
geometry keyed on the geometry columns alone, its colour taken from the
object table or the paint as the records' is. The increment that takes
them counts finalizes per navigation, not only dispatches, and reads its
baseline in these tables (B5.8, below, took both). Archive:
`benchmarks/results/b56_rows_source_20260929/`.

### B5.7: nets drawn as grids are, and the nets gate over its timed set

B5.7 (2026-09-29, on `b5-loose-ends`) closed what B5.5 left open. B5.5
passed the nets gate on its three scenes and failed it on scenes that are
mostly surfaces, and named the cost left as the redraw: a net drew the
index pattern of its capacity (`net_indices(patches, capacity)`) though the
reservation is twice the steps, so three quarters of its triangles had zero
area, each net in a draw of its own where grids coalesce (the orbs: 290,560
triangles in 70 draws against grids' 19,840 in one). Three changes, then
the gate again.

**Each net draws its steps' pattern.** A driver decides a net's steps
(B5.5), so it draws the pattern of those steps over the net's
`(capacity + 1)²` vertex layout, `patches × 6 × steps²` indices
(`gpu_net_geometry.net_indices(..., steps=)`, `run_indices`, `run_count`;
`netIndices` in `webgpu.js`). The kernel repeats the rows and columns past
the steps, so the capacity's pattern drew exactly these triangles, in this
order, and the rest with zero area, which rasterize to nothing: the pixels
cannot move (`NetRuns.test_the_steps_pattern_is_the_capacitys_without_its_zero_area_triangles`
holds the two patterns to that, and natively the two draw the same image).
The pattern is the driver's, built when a frame's steps are decided and
kept per members' `(patches, capacity, steps)` while a frame draws it; the
wire's `count` stays the capacity's, as the drivers check it.

**Consecutive nets that can share a draw are one batch.** `run_kind` gives
a net `"net"` under the rule grids follow (`"indexed"`: the surface
pipeline, one instance, and `coalesce_draws` asks the same pipeline, depth
mode, uniforms and textures), so a run of them is combined into one draw
whose `net_members` are the member draws, within the run cap
(`MAX_RUN_OUTPUT_BYTES` of evaluated output). A program's net and a
textured one stay alone, as a textured grid does. On the wire the batch's
`net` is a list of the members' descriptors in order (a net alone keeps
its descriptor, byte for byte); its `num_verts` and `count` are the sums.
Each driver evaluates every member into its span of the batch's one output
(after the members before it) and draws the batch in one indexed draw
with the members' patterns laid end to end: a member's span is its table
entry's output offset when it is evaluated alone in place (binding the
output whole), and its copy's destination when it is gathered with others.
A run where some members moved is another batch over the same spans: the
page hands its slot's output to the new batch (tier 2's predecessor, now
by the members' layout) and the native driver keys a run's output by its
layout rather than its hash, so each member whose source and steps stand
keeps its vertices and only the members that moved are evaluated. The
recording player carries each member's net into the frame it
reconstructs. The serializer pays one run where it paid a run a net.

**The switch, and the pin.** `MANIML_NET_RUNS=0` sends each net as a batch
of its own, as before B5.7, pixel for pixel the same; the forced stacks
read it as they read the patch source. The golden pin states it (its
phase_b nets were recorded one batch each; without the statement 23 of
PriceDiscovery's phase_b frames would move, where its spheres join runs),
so no golden was re-recorded, and `NetRunsLockstep` holds the retained
frame to the whole-frame path with runs on (stills that keep them, a
member moved, one added and removed, zooms that grow and keep the
reservations, a pan, a play that moves every other member, a reset, and
the same history as a format 8 stream). The harnesses measure nets as they
ship: every variant takes `MANIML_NET_RUNS` out of the environment.

**The timed set.** A default reaches every scene the Default, `--render`,
checkpoint stills and `--export` draw, so the nets gate is now judged over
a set of scenes (`flip_gates.TIMED_SCENES`: the orbit demo, EpisodeB3, B4,
and `benchmarks/surface_scenes.py`'s `OrbsScene` and `LatticeScene`, the
two B5.5's recipe failed) by a command that reads the complete runs by
scene and fails the flip for a scene of the set it was not given
(`flip_gates gate`, `benchmarks/README.md`, "Flip gates"). It judges every
run at the flip's limit (`flip_gates.GATE_LIMITS`, 1.05 for nets, the
table above), whatever `--limit` the run was reduced with, and fails a run
reduced with another; it requires every class the scene's serialize run
measured (recorded by `complete` since the review of B5.7) in both formats,
the camera and play classes always, from a serialize run taken with
`--tick-updaters --play-frames --camera-moves`, and names a class a run
lacks as a failure; and it fails runs of more than one tree (more than one
commit among the inputs, or a source file two inputs hashed differently).
The review found the first version passing a run judged at a looser
`--limit`, or one without its camera or play classes; re-reduced from the
same reports, the three passes below read exactly as they did.

**The serializer's share.** Coalescing nets costs the serializer a size a
net a frame (a run's output within the run cap), and the gate's first
pass (below) was taken while it was asked twice a net, each time through
the capacity's validation: 0.2 ms of the lattice's still frame. It is memoized on the draw, as `run_kind` is (a
draw's net and capacity never change; a zoom that outgrows the
reservation prepares a new draw). A still frame's serialize, the tree
against the tree before the memo against grids (20 interleaved rounds of
50 frames, median): the lattice 1.049 → 0.858 ms (grids 0.684), the orbs
0.234 → 0.205 (grids 0.177). What is left over grids there is the net
cache's per-leaf `keep` (`NetRecipeCache.keep`: an LRU move and a stamp
per net a frame), B5.5's.

**Pixels.** Drawing fewer triangles of the same net, in runs, moves no
pixel. Natively against `main`'s driver (efcb262c, B5.5's): every Surface
fixture under the nets stack and under the forced Phase B, zoom walks over
the default sphere and the orbs (frame by frame through one driver and
each frame fresh), a pan and an orbit, and a play of the orbs where every
third member moves (kept, fresh and Phase B): 90 images, 0 pixels differ;
every checkpoint of `OrbsScene` and `LatticeScene` and frames inside their
plays: 38 images, 0 differ; PriceDiscovery under the forced Phase B with
runs on and off (the pin's pausepoints and the gate play, 27 run batches):
22 frames, 0 differ. So the lattice's 0.979% over 24/255 against grids is
B5.5's and B5.4's, and the gate's pixel test fails it as before.

What those pixels are, measured against a reference that stands for the
true sphere (at the lattice's checkpoint 1, 1920×1080: each of the 480
spheres replaced by one of the same centre, radius and colour with eight
times the patches in each direction, drawn as Phase A's grids, whose
facets are then a fraction of a pixel): grids are more than 24/255 off it
in 1.596% of the frame (33,101 pixels), nets in 0.858% (17,786); the mean
channel difference is 1.01 against 0.47. Of the 20,299 pixels where grids
and nets differ by more than 24/255, nets are the nearer to the reference
at 19,792 and grids at 507, and there grids are off by 68.1 on average
against nets' 22.3. The differing pixels are the silhouettes: the grid's
polygon outline against the net's curve (the archive's
`lattice_silhouette_crop.png`: the reference, grids and nets over the 96
× 54 window with the most differing pixels, enlarged 8×, and each stack's
difference from the reference, 4× brighter). The gate measures distance
from the grid, so a net rounder than its grid fails it; the verdict stands
on the gate as written.

**What a redraw costs now.** The orbs draw one net batch where they drew
70, 72,640 triangles where they drew 290,560 (grids 19,840 in one); the
lattice one where it drew 480, 207,360 triangles where it drew 829,440
(grids 92,160). Natively (40 small pans at checkpoint 1, `render()` wall
clock, flag off) the lattice's frame is 9.3 ms where B5.5's driver took
19.4 (grids 9.2-9.3): its CPU encode of 480 draws is gone. What remains is
what makes a net round: it draws the steps its screen density needs, 3-4
a patch on these spheres where a grid draws 2, so 2.25× (the lattice) and
3.7× (the orbs) the triangles of grids.

**The gate fails; grids stay the default.** Taken as B5.5 took it (the six
commands per scene, `fixtures`, then `flip_gates gate` over the timed
set; `MANIML_*` unset but for the attribution runs), three times. Pass 1
(09:15-09:59) measured the tree before the serializer's fix above. Pass 2
(10:07-10:51), on the tree as committed, ran under another's load (B4's
first attribution run started with the GPU 31-46% busy, the load reached
6.3 and a browser opened mid-scene) and failed B4 by its GPU part alone
(format 7 still 1.196, camera 1.072 and 1.070), which no other pass
showed. Pass 3 (11:55-12:42), on the same tree, had every run wait for
three samples of the GPU at or below 10% (all 32 started at 0-7%, load
2.0-4.1; a first attempt was stopped when another application's video
held the GPU at 79-82%), and is the verdict. Every source file of the tree
committed here hashes as pass 3 recorded it but `benchmarks/flip_gates.py`,
whose `complete` and `gate` commands the review changed after it (not
`serialize`, the part that measures), and two test modules no run reads
(`tests/test_export.py`, `tests/test_flip_gates.py`); every pass's
`complete` and `gate` were run again with them, from the same reports.

| Complete frame, nets / grids (format 8; format 7) | pausepoint | ticked | camera | play | pixels over 24/255 |
| --- | ---: | ---: | ---: | ---: | ---: |
| Orbit demo, B5.5 | 1.037; 0.990 | – | 0.997; 1.002 | 0.696; 0.700 | 0.307% |
| Orbit demo, pass 1; pass 3 | 1.047, 1.036; 0.988, 0.989 | – | 1.000, 1.000; 0.998, 0.997 | 0.679, 0.695; 0.688, 0.697 | 0.307% |
| EpisodeB3, B5.5 | 1.010; 0.999 | 1.016; 1.013 | 1.020; 1.021 | 1.017; 1.008 | 0.026% |
| EpisodeB3, pass 1; pass 3 | 0.987, 0.996; 0.997, 1.001 | 1.005, 1.025; 1.003, 1.009 | 1.016, 0.963; 1.017, 0.964 | 1.006, 0.986; 1.013, 1.002 | 0.026% |
| B4, B5.5 | 0.988; 1.004 | 0.999; 0.999 | 1.037; 1.046 | 1.014; 1.022 | 0.023% |
| B4, pass 1; pass 3 | 1.009, 0.992; 0.997, 0.998 | 0.993, 1.007; 1.002, 1.005 | 1.031, 1.018; 1.031, 1.020 | 1.013, 1.001; 1.027, 1.011 | 0.023% |
| Orbs, 70 spheres, B5.5 (fix pass) | **1.305; 1.162** | – | **1.196; 1.215** | 0.851; 0.858 | 0.356% |
| Orbs, pass 1; pass 3 | **1.315, 1.151; 1.070, 1.063** | – | **1.106, 1.096; 1.106, 1.098** | 0.724, 0.729; 0.725, 0.733 | 0.356% |
| Lattice, 480 spheres, B5.5 (fix pass) | **1.500; 1.366** | – | **1.435; 1.523** | 0.801; 0.793 | **0.979%** |
| Lattice, pass 1; pass 3 | **1.525, 1.243; 1.143, 1.106** | – | **1.204, 1.177; 1.224, 1.193** | 0.597, 0.610; 0.597, 0.610 | **0.979%** |

The Surface fixtures pass, B5.4's and B5.5's exactly (worst the orbs,
0.2814%). The three scenes the gate was set on pass every class in every
pass but
pass 2's B4; the two that are mostly surfaces fail their still and
camera frames in every pass (pass 2, under load, read two of those classes
under the limit: the orbs' format 7 still, 1.015, and the lattice's format
8 camera, 1.027), and the lattice its pixels. The flag-off check reads the
same way on them (pass 3: the orbs' still 1.151; 1.280 and camera 1.019;
1.020, the lattice's 1.243; 1.140 and 1.072; 1.084). The redraw took half
to two thirds of B5.5's excess off both scenes, and a moving net now costs
a play frame less than B5.5's (the lattice's play 0.80 → 0.61 of grids).
Where the rest goes, pass 3's parts in format 8 (serialize + page + GPU,
ms, grids against nets):

- Orbs, still: 0.19 against 0.22, Python alone (the frame sends nothing).
  Camera: 0.20 + 0.02 + 3.69 against 0.27 + 0.10 + 3.94.
- Lattice, still: 0.70 against 0.87. Camera: 0.73 + 0.03 + 4.72 against
  1.15 + 0.18 + 5.12. In format 7 the still is 0.70 + 0.01 + 4.71 against
  0.88 + 0.02 + 5.11.

The GPU part (+0.22-0.25 ms on the orbs, +0.40 on the lattice) is the
triangles a net draws to be round, 2.25-3.7× grids' (above). The page's
(+0.08 and +0.15 ms on a camera move in format 8, +0.09 and +0.24 in
format 7) is its per-member walk of a run every frame (each member's
steps, its state, the pattern's key over every member, and in format 7
each member's descriptor compared). The serializer's is the net cache's per-leaf `keep`
on a still frame and each net leaf's reservation taken again on a camera
move (B5.5's `NetRecipeCache.source`: +0.42 ms over the lattice's 480).
The pixels are the grid's facets (above): the gate measures distance from
the grid.

**What would flip it.** Not the costs alone: the lattice's pixels fail a
gate that measures distance from the grid for as long as a net is drawn
rounder than its grid, which is the point of drawing it. Two questions for
Taylor, then. Whether the nets gate's pixel test should measure each stack
against a reference surface (as above) rather than nets against grids:
there nets are the nearer, though at 0.5% over 24/255 neither stack
passes on the lattice (nets 0.86%, grids 1.60%), so such a gate would
want its limit set with it. And whether a
surface-heavy still or camera frame may cost 6-25% more (0.03-0.17 ms of
Python on a still frame that sends nothing; 0.4-1.1 ms on a camera move at
1080p) for no facets at any zoom. The costs that can still come down
without drawing less: the page's per-member walk (keep a run's steps and
pattern and walk the members only when the camera moves a step), the
per-leaf `keep` and the reservation's check on a move in Python.

Archive: `benchmarks/results/b57_net_runs_20260929/` (the three passes'
tables, commands, conditions and source hashes, the silhouette
measurement and its crop, the redraw and still-frame figures).

### B5.8: a frame's rows in one dispatch, keyed on their geometry

B5.8 (2026-09-29, on `b5-loose-ends`) takes the two negatives B5.1 and
B5.6 recorded for rows as the patch source: each driver finalized every
changed rows with a dispatch of its own (about 360 a frame on the 8.a
play; a navigation's 73 → 206 and 26 → 107), and a path's rows carried
its paint and were keyed with it, so a change of paint alone (a dim at a
pausepoint) sent and finalized again rows whose geometry had not moved.
B5.6 measured the result on a navigation: the forced Phase B's native
complete frame 15-28% dearer than records (EpisodeB2 29.9 → 38.3 ms) and
the page's JavaScript up to ~0.8 ms more.

**Rows travel as their geometry and their paint.** A row source is split
(`gpu_program_geometry.split_rows`) into its geometry, nine float32
columns a row (point, stroke width, joint angle, base point or unit
normal, fill border width), named by a digest of those columns alone, and
its paint, eight a row (stroke RGBA, fill RGBA): one row where every row's
bits agree, read at stride 0 and shared by every path that looks the same,
and one a row otherwise (a gradient). Both travel in `program_data` by
content hash; a patch or stroke batch names them in `rows` and
`row_paints`, member for member, and a patch run's border hash is
`rows_key` of the pairs. A batch's content hash is its geometry and
layout, not its paint, as a records run's is its layout and object table:
a change of paint alone keeps the batch (held) and names a new paint
beside it. A read whose geometry did not move keeps the previous read's
array (so its digest is memoized and nothing is re-sent), its object
record (the winding sign) and its planar check, which are the geometry's,
so its object table does not move either. The finalized records and
instances still hold the paint (a record's colour words and its active
flag, which reads the fill's alpha, as records packed on the CPU do), so
a paint change refinalizes the batches that name it, on the GPU, in the
frame's one dispatch; only the paint travels. A recording made before
B5.8 names seventeen-column rows without `row_paints`: both drivers and
the player read it, flagged in the same dispatch.

**A frame's changed rows in one dispatch.** Each batch owns its output,
its members' curve records (a patch run) or stroke instances (a stroke)
in order: natively keyed by what it is made of (its kind, geometry and
paint names), in the page the slot's own, taken over in place by a
successor of its shape and refinalized when what it names moved. The
outputs a frame needs made are finalized together by
`row_finalize_table.wgsl`: one storage binding holds a four-word header,
eight words an entry (geometry word, paint word, paint stride, output
word, curves, flags, first curve) and the inputs they read, each geometry
and paint once; one invocation a curve finds its entry by a binary search
over the first curves and writes into an output scratch; each batch's
members are then copied into its output in one copy. Past a 32 MiB budget
(or the device's storage binding limit) the next dispatch takes the next
aligned region of the one write and reuses the output scratch
(`plan_row_finalize`, `planRows`). The scratch grows by powers of two and
is released on a frame that draws no rows, and on close. The kernel's
arithmetic is `row_finalize.wgsl`'s, which a program's rows still go
through: `RowTableKernel` holds the two to the same words on 40-odd paths
of the fixture corpus, a gradient and an overflowing path, from the split
rows and from seventeen-column rows.

**Two further fixes.** Both drivers read one table on the wire for program
sources and row sources again, as B5.6's one map did: the rows a batch
names may be held as a program's source and the reverse (a recording made
before B5.8 can name as a program's source the seventeen-column rows an
earlier frame sent as a path's; `rowsAndProgramsShareOneTable`, and
`PatchRowsCommands`' natively). The page keeps one member object a path
where it made two, shares one empty buffer list among the rows it holds,
and names a one-object batch's output without joining lists; a patch run's
strip pattern is its curve count's and capacity's
(`"patch-strips:" + curves + "@" + capacity`), shared by every run of as
many curves, and the border stage's state is compared in parts (the
camera's words, then what the records were made of).

**After review.** The review found two disagreements between the mirrors
and one path no test ran on a GPU, all three fixed: `plan_row_finalize`
counted the table's header twice when it asked whether a member fits, so it
split a dispatch whose region fits the budget exactly where `planRows`
kept it whole (now both count it once; `RowFinalizePlan` holds the two
planners to the same dispatches, word for word, at and around the budget,
and fails against the old count); the native driver read a batch whose
`row_paints` is present and null as a recording before B5.8 and drew it,
where the page and the player reject it (now a batch is such a recording
only without the key, in all three; `test_null_row_paints_are_not_a_recording_before_b58`,
`legacyRows` and the player's `corrupt` case each fail when null is read
as the key's absence); and nothing ran the native driver's several
dispatches on a real GPU (`RowFinalizeInSeveralDispatches`, under
`MANIML_TEST_GPU=1`, lowers the budget to 1 KiB and draws eight frames, a
dim, a move, an undim, an alpha change, a zoom, a recolour and a gradient
flip, in 3 or more dispatches with a batch's members split across them:
pixel for pixel what one dispatch draws, and records within 1/255; it
fails when every dispatch binds region 0). The review also ran the page's
planned path in Chrome 152 (a viewer from this worktree, Phase B selected:
six 40k-curve fills in one patch run and two 60k-curve strokes, 91 MB of
outputs, planned into three dispatches at aligned regions of one 25.9 MB
write, the run's members split across them; a dim, a move, a step back and
a switch between Phase A and Phase B drew correctly, with no device error
and no console message). The fix pass ran it again on the tree committed
(below).

**Proof.** Pixels, rows against records, largest channel difference 0:
every pausepoint of both episodes and their gate plays (84 and 23, 24 and
9), both takes of the test point's pairs (12 pausepoints and 139 play
frames, 12 and 124), and every phase_b frame of the golden pin (251, each
drawn as the pin's records frame, all at their pinned digests, and as
rows); the pin itself untouched, in each of its modes (default,
`MANIML_RETAINED_FRAME=0`, `MANIML_VERIFY_LEDGER=1`). The mirrors:
`rowsWire` (one dispatch, its table read member for member, each batch's
one copy into its slot's buffer, a moved square refinalized in place, a dim
sending paints and no rows), `rowsInSeveralDispatches` (a 1 KiB binding
limit: several dispatches at aligned regions, traced by content to draw
what one dispatch draws), `legacyRows` (and a null `row_paints` rejected
with nothing submitted), `rowPlansAgree`, `rowsAndProgramsShareOneTable`,
`retainedFramesDrawWhatFreshDriversDraw` (dims and moves of a row run),
the fake device's checks of every table; natively `PatchRowsCommands`
(one dispatch, the table's entries and inputs, a dim, legacy rows,
malformed paints and a null `row_paints` rejected with nothing submitted),
`RowFinalizePlan`, `RowFinalizeInSeveralDispatches` and `RowTableKernel`;
the player (`player_commands.cjs phaseB` and `corrupt` with split rows, a
null `row_paints` among them, the export replays); each of the three null
cases fails when its mirror reads null as the key's absence. In Chrome 152,
on the tree committed, with a viewer launched from this worktree and Phase
B selected: the kernel compiles on a device of its own without messages;
the review's scene of 40k- and 60k-curve paths plans its first frame into
three row dispatches at regions 0, 11520512 and 21601024 of one 25.9 MB
write, four copies for two batches (the fill run's members split across
dispatches), and draws it, its dim (the same three dispatches), a move, a
step back, and the same frame again after a switch to Phase A and back
(Phase A's frame of those paths had not arrived before the switch back);
a scene of fill-bordered
squares, a gradient circle, an annulus, a stroke and text draws a dim and
an undim in one submit each (one row dispatch beside two border runs, one
30 KB write), a play in 31 submits, and three wheel zooms with no row
finalize and only 192-byte uniform writes. No uncaptured device error in
either; the console's only messages were the WebSocket's reconnect
failures after a viewer was stopped.

**The gate, and what it read** (`benchmarks/results/b58_rows_one_dispatch_20260929/`,
its README the detail). The recipe asks for a quiet GPU; the desktop apps
kept it 12-44% busy for long stretches, so the test point was taken twice
(17:28-17:59, the GPU 19-41% busy at every start and nothing waited for;
and a retake after review, every run first waiting up to two minutes for
three samples at or below 10%, which only some runs got), the native
navigation in nine passes (three of EpisodeB2's on a quiet GPU), and GPU
parts are compared only within a run, where records and rows alternate:
records' own 8.a GPU part read 17.75 ms in B5.6's run and 24.22 and 22.04
in these. Records → rows:

- A navigation, natively (`seek_frames.py`, rounds alternating):
  EpisodeB2 below records in eight of nine passes (the three quiet ones
  34.33 → 32.93, 33.58 → 33.11, 35.07 → 33.80 ms; the one above, +1.7%,
  the review's with the GPU 39-50% busy), where B5.6's rows read 29.9 →
  38.3. PriceDiscovery above in seven of nine (-2.3% to +8.0%; the
  retake's eight-round passes 26.26 → 25.80, 25.57 → 25.60, 25.25 →
  25.46), B5.6 25.0 → 28.8: its **render** above records' in eight of nine
  (+0.4 to +1.6 ms), its serialize within 0.17 ms. The first reading put
  PriceDiscovery's excess in the serialize; it is in the render. The still
  frame after it reads rows above records (EpisodeB2 15.05-16.10 →
  16.12-16.77 ms), and its format 7 message is 98.4 KB where records' is
  71.7 and B5.6's rows 85.4: the `row_paints` lists are 13.1 KB of it.
- A navigation, the page (`browser_frames`' `cold`, the median of twelve),
  three takes: EpisodeB2 2.32-2.34 → 2.58-2.61 ms in format 8 and 2.57-3.47
  → 2.42-2.49 in format 7; PriceDiscovery 1.49-1.51 → 2.05-2.07 and
  1.30-1.36 → 1.46-1.49. B5.6's rows read 2.68 and 1.73 in format 8, so
  PriceDiscovery's page navigation in format 8 is worse than B5.6's rows
  (1.73 → 2.05-2.07, its records' 1.56 → 1.49-1.51). What the page does
  for it is at or below records' (compute dispatches 73 → 74 and 26 → 26,
  B5.6's 206 and 107; bind groups, buffers and uploads fewer). Why the
  median reads above records in format 8 is not isolated. It is format
  8's: format 7 sends the same definitions and reads rows close to records
  at the messages where format 8 is far above (PriceDiscovery's 109, 115,
  130: 1.22/1.07, 0.79/0.68, 1.25/1.20 against 2.52/1.20, 1.53/0.81,
  2.67/1.19), so a run of small paths sent as a definition a path is not
  the cost, as this section first said. Young-generation collections land
  in the median messages under rows (EpisodeB2's 2.h, PriceDiscovery's 58,
  109, 115). And the instrument moves by as much as the differences:
  replayed a fresh process a pass without the harness's bookkeeping,
  EpisodeB2 reads rows below records in both formats and PriceDiscovery's
  format 8 1.47 → 1.62, whose checkpoint 130 reads 2.6 ms under rows
  against 1.1 under records when Node's stderr is a pipe, as
  `browser_frames.py` runs it, and 1.0 against 1.2 when it is `/dev/null`,
  nothing written to it either way. The candidates left are the delta
  path's allocations (the row staging reallocated after
  `releaseRowScratch` drops it, a member object a slot, the
  completed-state objects), none measured.
- The test point's classes, first take / retake (B5.6), format 8:
  EpisodeB2 pausepoint 0.80 → 0.89 / 0.79 → 0.92 (0.68 → 0.75), ticked
  3.58 → 3.96 / 3.64 → 4.02 (3.22 → 3.48), play 11.83 → 12.60 / 12.47 →
  12.65 (8.86 → 8.97); PriceDiscovery 0.78 → 0.84 / 0.77 → 0.89 (0.62 →
  0.69), 1.21 → 1.26 / 1.17 → 1.29 (0.98 → 1.04), 12.26 → 11.78 / 12.07 →
  12.06 (10.93 → 10.63). Rows read above records in every EpisodeB2 class,
  its play and ticked gaps wider than B5.6's (+0.77 and +0.18, +0.38 and
  +0.38, against +0.11 and +0.26); a mover's format 8 play serialize is
  0.13-0.7 ms dearer at 12, 76, 258 and 277, the split every mover pays.
  PriceDiscovery's format 7 pausepoint, one frame, read 5.63 → 6.24 then
  5.69 → 5.82 (the first take's +0.44 ms that frame's GPU part).
- 8.a's play, the test point in format 8: 138.77 → 86.09 ms (serialize
  109.82 → 60.12, page 4.73 → 4.57, GPU 24.22 → 21.41) and, retaken,
  136.92 → 83.71 (110.26 → 59.41, 4.63 → 4.42, 22.04 → 19.87), against
  B5.6's 80.52 (its GPU 17.75 → 24.13). Within each run rows' GPU part is
  below records' (by 2.8 and 2.2 ms, and 0.9 in the retake's attribution
  run with the two alternating replay by replay on a quiet GPU, where
  B5.6's rows read 6.4 above); across runs nothing is compared. The
  serialize is 4.2 ms a frame dearer than B5.6's code (HEAD against this
  tree in alternate processes: 52.9-53.6 against 56.9-57.4 ms): the split
  into geometry and paint 1.3 ms, the rest of the rows read and of each
  leaf's preparation 0.9, `encode_draw` 0.8 (the paints' digests and
  `rows_key` over pairs 0.4 of it), the runs 0.3, the header's JSON 0.4
  (each batch names its paints), about 0.5 not attributed. Natively the
  whole frame is 210.1 → 151.8 and 207.3 → 150.5 ms (render 100.0 → 92.8
  and 97.0 → 91.7; B5.6's rows rendered 15.7 ms above records).
- A dim sends no rows: EpisodeB2 258 → 277 holds 334 of 463 batches (records
  176, B5.6's rows 0), sends 10 paints (0.3 KB) and no geometry the receiver
  had been sent (B5.6 re-sent 590 rows that differed only in alpha), 528 KB
  against records' 1805 KB.
- Pixels identical to records, above.

The gate is not met as written. Met: EpisodeB2's native navigation, its
page navigation in format 7, a dim sending no rows, pixels. Not met:
PriceDiscovery's native navigation (its render), the page's navigation in
format 8 on both episodes and in format 7 on PriceDiscovery, with
PriceDiscovery's format 8 worse than B5.6's rows, and 8.a's play (86.1 and
83.7 against 80.5 ms, across runs on a busier GPU; its serialize 4.2 ms
dearer, measured directly). What is left: the serializer's per-path split
on movers (a mover whose paint does not move still pays for the paint's
extraction and uniformity check, and every batch names its paints, 13 KB
of a format 7 still message on EpisodeB2, which native capture and every
recorded export frame pay: a batch could name a paint only where it
differs from what its geometry last carried), PriceDiscovery's native
render on a navigation, and the page's format 8 navigation, whose cause is
not isolated.

Archive: `benchmarks/results/b58_rows_one_dispatch_20260929/`.

## The final test point

Since B5.6 the selection's Phase B sends its patches as rows; the Phase B
measured here packed records, the stack `test_point` now calls
`phase_b_records`, and "The flips", B5.6, retakes the table with both (and
B5.8 again, its rows finalized in one dispatch and keyed on their
geometry).

B6 (2026-09-28, on `b4-integration`): the table B4 and B5 were building
toward, read, not recommended from. Four stacks, as a lecture meets them:
**today**, Phase A without the retained frame (`MANIML_RETAINED_FRAME=0`)
in format 7 full frames, drawn by the page of `main` (0a2bf3b2, the
checkout Taylor teaches from: its `webgpu.js` predates B4.7's slots);
**Phase A** retained; the **Default** stack as the flips left it; and
**Phase B** forced (patches, nets, its plays recording GPU programs as the
viewer's selection has them); the last three in format 7 and in the format
8 stream the shipped page negotiates. Per class (a still pausepoint, one
whose updaters tick, the frames of the play into it), the browser-side
complete frame of Taylor's gate: Python's `serialize_ms`, the page's
JavaScript (`page_ms`, main realm, the fake device), the GPU
(`gpu_total_ms`, two attribution runs pooled, charged as the share of a
frame's messages that were sent), their sum, the wire per message, and the
pixels against today's (flag-off runs). The instrument is
`benchmarks/test_point.py` (`benchmarks/README.md`, "The test point"),
the archive `benchmarks/results/phase_b_test_point_20260927/`. The frames
are `episode_frames.select_frames`' twelve pausepoints of each episode:
EpisodeB2's include 8.a (checkpoint 307, ticking); PriceDiscovery's are
evenly spaced and do not include 3.a.4 (63), but do its neighbours 3.a.3
and 3.a.5.

**Today is main's Python.** The whole-frame path on this branch writes
`main`'s bytes (0.a, 5.a and 8.a ticking: a fresh cache's first message
and the fifteen after it have the same blake2b digests in an archive of
`main` and in this tree, 175,421, 222,367 and 183,234 B once the first is
sent; the archive's `today_is_main_digests`) and costs what `main`'s own
serializer costs, run from an archive of `main` in alternate processes:
minima 10.6-11.0 against 10.5-11.6 ms (0.a), 16.4-17.2 against 16.8-16.9
(5.a), 36.8-38.4 against 37.9-38.3 (8.a ticking).

**Conditions.** One run at a time, 18:26-19:05 local (the real device's,
below, 19:14-19:16, at load 5-9 from other sessions with the GPU 0-11%
busy at their start). Another project's Playwright tests ran in bursts
throughout (load up to 16), and EpisodeB2's browser, page, serialize,
second attribution and instrumented runs overlapped them (its second
attribution run started with the GPU 15-24% busy); those five were taken
again, 18:57-19:05, starting and ending at load 2.5 with the GPU at 0-19%
(three samples each), and the complete frames of the two passes agree within 0.7 ms per class and
stack (the first pass's table is archived too). Every other run started
with the GPU idle and the load 2.2-3.4.

### The table

Each cell: serialize + page + GPU = **complete** (ratio to today); the
wire per message. Medians per frame, then over the class's frames (a play
frame is one value). Pixels: the share more than 24/255 off Phase A
without the retained frame in any channel, worst frame (largest channel).
The GPU part is the native driver's, as Taylor's gate defines it, not the
page's ("The GPU column is the native driver's", below).

EpisodeB2 (531 objects at 8.a):

| Stack | pausepoint (10 frames) | ticked (2: 3.i, 8.a) | play (114 frames, 12 plays) | pixels: pausepoint / ticked / play |
| --- | ---: | ---: | ---: | --- |
| Today: Phase A, whole frame, format 7, main's page | 5.71 + 0.88 + 4.38 = **11.10**; 69.2 KB | 25.03 + 1.51 + 4.70 = **31.24**; 129.1 KB | 14.17 + 2.24 + 5.43 = **22.75**; 406.9 KB | reference |
| Phase A, retained, format 7 | 0.80 + 0.03 + 4.36 = **5.29** (0.48×); 69.2 KB | 3.05 + 0.05 + 4.69 = **7.79** (0.25×); 129.1 KB | 7.49 + 0.94 + 5.43 = **15.10** (0.66×); 406.9 KB | 0 / 0 / 0 |
| Phase A, retained, format 8 | 0.81 + 0 + 0 = **0.81** (0.07×); 0 | 2.97 + 0 + 0 = **2.97** (0.10×); 0 | 7.58 + 0.76 + 5.43 = **14.69** (0.65×); 286.4 KB | 0 / 0 / 0 |
| Default, format 7 | 0.77 + 0.03 + 4.36 = **5.30** (0.48×); 69.2 KB | 3.38 + 0.05 + 4.70 = **8.12** (0.26×); 129.1 KB | 7.42 + 0.95 + 5.39 = **15.09** (0.66×); 406.9 KB | 0 / 0 / 0 |
| Default, format 8 | 0.78 + 0 + 0 = **0.78** (0.07×); 0 | 3.02 + 0 + 0 = **3.02** (0.10×); 0 | 7.46 + 0.76 + 5.39 = **14.83** (0.65×); 286.4 KB | 0 / 0 / 0 |
| Phase B, format 7 | 0.75 + 0.03 + 5.14 = **6.13** (0.55×); 63.8 KB | 4.01 + 0.09 + 6.09 = **10.20** (0.33×); 282.1 KB | 2.27 + 0.68 + 9.70 = **12.66** (0.56×); 133.5 KB | 0.000% (21) / 0.000% (23) / 0.000% (30) |
| Phase B, format 8 | 0.77 + 0 + 0 = **0.77** (0.07×); 0 | 3.74 + 0 + 0 = **3.74** (0.12×); 0 | 2.58 + 0.30 + 9.70 = **12.41** (0.55×); 1.0 KB | the same |

PriceDiscovery:

| Stack | pausepoint (1 frame) | ticked (11 frames) | play (100 frames, 12 plays) | pixels: pausepoint / ticked / play |
| --- | ---: | ---: | ---: | --- |
| Today: Phase A, whole frame, format 7, main's page | 3.78 + 0.33 + 4.15 = **8.26**; 21.1 KB | 7.04 + 0.65 + 4.27 = **12.29**; 44.7 KB | 8.44 + 0.91 + 4.33 = **13.52**; 183.7 KB | reference |
| Phase A, retained, format 7 | 0.72 + 0.01 + 4.15 = **4.88** (0.59×); 21.1 KB | 1.06 + 0.02 + 4.27 = **5.32** (0.43×); 44.7 KB | 3.39 + 0.31 + 4.33 = **7.95** (0.59×); 183.7 KB | 0 / 0 / 0 |
| Phase A, retained, format 8 | 0.74 + 0 + 0 = **0.74** (0.09×); 0 | 1.06 + 0 + 0 = **1.06** (0.09×); 0 | 3.32 + 0.20 + 4.33 = **7.77** (0.57×); 141.9 KB | 0 / 0 / 0 |
| Default, format 7 | 0.73 + 0.01 + 4.15 = **4.88** (0.59×); 21.1 KB | 1.04 + 0.02 + 4.27 = **5.28** (0.43×); 44.7 KB | 3.37 + 0.31 + 4.34 = **7.91** (0.59×); 183.7 KB | 0 / 0 / 0 |
| Default, format 8 | 0.78 + 0 + 0 = **0.78** (0.09×); 0 | 1.05 + 0 + 0 = **1.05** (0.09×); 0 | 3.39 + 0.20 + 4.34 = **7.86** (0.58×); 141.9 KB | 0 / 0 / 0 |
| Phase B, format 7 | 0.74 + 0.03 + 4.86 = **5.63** (0.68×); 22.3 KB | 1.17 + 0.03 + 4.76 = **6.11** (0.50×); 63.7 KB | 2.51 + 0.39 + 9.41 = **13.98** (1.03×); 75.4 KB | 0.000% (27) / 0.041% (142) / **2.024% (153)** ¹ |
| Phase B, format 8 | 0.73 + 0 + 0 = **0.73** (0.09×); 0 | 1.19 + 0 + 0 = **1.19** (0.10×); 0 | 2.96 + 0.21 + 9.41 = **14.08** (1.04×); 1.7 KB | the same ¹ |

¹ Measured without the pack_rows fix another session has since made in
this worktree (uncommitted, not B6's; "Phase B's pixels fail", below):
every run recorded `maniml/web/gpu_program_geometry.py` as commit
`894e841c` has it (sha256 `60fdc6a2...`). Only the play figure can move
with the fix; a pausepoint records no program.

The flag-off check (the GPU part the flag-off runs' wall clock through the
full readback, which the browser never does) moves no reading below: today
14.10 / 34.19 / 24.98 ms on EpisodeB2 against the Default's format 8 0.78
/ 3.02 / 17.23, and 10.53 / 14.43 / 15.60 against 0.78 / 1.05 / 9.90 on
PriceDiscovery (the archive has every row).

### Reading

**What a lecture frame costs, today and after.** After is the Default
stack in format 8, the page this branch serves. A still pausepoint, the
frame the viewer serializes when an input event arrives (at most 45 a
second): 11.10 → 0.78 ms on EpisodeB2 and 8.26 → 0.78 on PriceDiscovery,
with 69 and 21 KB a message → nothing sent, and the page and the GPU doing
nothing. A pausepoint whose updaters tick: 31.24 → 3.02 and 12.29 → 1.05
ms, again nothing sent (both episodes' updaters move nothing on screen);
8.a itself 44.77 → 4.51 ms (37.9 ms of serialize, 2.0 of page and 4.85 of
GPU, 179 KB, against its serialize alone). A play frame: 22.75 → 14.83 and
13.52 → 7.86 ms, 407 → 286 and 184 → 142 KB a message. At rest the
serialize is tier 1's (5.71 → 0.78 ms), the page B4.7's (main's page 0.88
→ 0.03 ms a resend at the EpisodeB2 pausepoint median, 1.51 → 0.05
ticked, the two pages played over the same stream in turns), and format 8
takes the message, the page's work and the GPU's draw away altogether. In
plays the serialize falls by half or more, the leaves that hold still
being kept (14.17 → 7.46 ms on EpisodeB2, 8.44 → 3.39 on PriceDiscovery),
the page falls
2.24 → 0.76 and 0.91 → 0.20 ms, and the GPU stays what it was (5.4 and
4.3 ms natively; the page's GPU pays less, below). Tier 1's recorded
negative is in the table too: where every leaf moves the retained frame
costs more, 5.a's play 85.23 → 93.34 ms (serialize
56.2 → 67.1), its page 8.07 → 5.05. The default's rows are Phase A's to
the noise and its pixels identical, since no flip moved it.

**Which defaults flipped: none**, on B5.4's numbers ("The flips"; B5.5
later passed the nets gate on its scenes and failed it on scenes mostly
surfaces, so none has flipped since either): nets
failed on camera moves (1.25-1.34× grids' complete frame in format 8,
1.13-1.33× by the flag-off check); patches failed Taylor's gate on both
episodes' plays (1.15× and 1.48×) and ticked frames (1.14× and 1.10×);
strokes programs' Python per play frame was no lower than programs off
(-0.03% on EpisodeB2 in format 8, +0.05% to +0.32% in the other three
runs), with the native complete frame 1.4-1.8% dearer. The whole Phase B
stack against the Default here, format 8 (the play ratios driven by the
native GPU column, below): EpisodeB2 0.99× at the pausepoint,
1.24× ticked (serialize 3.74 against 3.02 ms) and **0.84× in plays**
(12.41 against 14.83 ms: its programs take the serialize from 7.46 to 2.58
ms and the page from 0.76 to 0.30, while the GPU rises 5.39 → 9.70, 1.52 ms
of program passes and 1.71 of border passes a frame); PriceDiscovery 0.94×,
1.13× and **1.79× in plays** (GPU 4.34 → 9.41: programs 2.39, borders
1.90). By Taylor's gate the whole stack would fail too, in format 8 on
both episodes' ticked frames and PriceDiscovery's plays, and on
PriceDiscovery's pixels as measured before the pack_rows fix.
The nets pixel gate this plan put on PriceDiscovery, which B5.4 took on
the scenes that draw more surfaces, passes here: its spheres are nets under
Phase B, 0.004-0.041% at every ticked pausepoint (largest channel
106-142; pausepoints, which the pack_rows fix cannot move).

**The GPU column is the native driver's.** Taylor's gate takes the GPU
part from the attribution runs, wgpu-native drawing the frame natively,
and the table does. The page's GPU is Dawn's, on the same M3, and the
real device shows it paying far less for the same frame: 200
back-to-back redraws of 8.a, each encoding every slot into targets at the
header's full resolution, sustain 1.29-1.35 ms a redraw on Phase A and
1.74-1.78 on Phase B with the page, Dawn's GPU process and the GPU
pipelined, so the page's GPU for 8.a is at most 1.35 and 1.78 ms, where
the table charges 4.85 and 6.44 ms. Natively Phase A's GPU is about 4.1
ms even at a pausepoint of 46 draws (checkpoint 103: 4.07, the out pass
3.71), a fixed cost per frame that the device does not show. Every
comparison the GPU column drives carries that native cost: each format 7
ratio, the plays, "the GPU stays what it was" above, and Phase B against
the Default in plays (0.84× and 1.79×, the GPU 5.39 → 9.70 and 4.34 →
9.41 ms natively). They are the gate's numbers as defined; the page's GPU
per class was not measured, and the device's throughput per class
(`device_redraw.html`'s `redraw()` on a pausepoint, a ticked frame and a
play message per stack) is what would read those comparisons on the page.

**Phase B's pixels fail on PriceDiscovery's plays, and GPU programs are
why** (as measured before the fix: every figure in this paragraph was
taken with `maniml/web/gpu_program_geometry.py` as commit `894e841c` has
it, sha256 `60fdc6a2...`). 2.02% of the pixels of the play into 3.a.1
are more than 24/255 off (0.41-1.50% on four more of its 3.a plays). Replayed and drawn apart:
Phase B with programs off is 0.03% off Phase A (the nets), and Phase B
with GPU programs 2.0% off Phase B with programs off, the same with the
whole-frame path, so neither the retained frame, the patch fill nor nets
are the cause. The play is `LaggedStart(*[FadeIn(r) for r in rays],
FadeIn(best_check))` beside other fades: the nine rays (grey `Line`s at
opacity 0.5, fading in at 0.1-14% on the play's second frame) are drawn as
an opaque magenta fan in the paint of `best_check`'s dashed line, whose
28 dashes also carry programs and whose updater `become()`s it every
frame. The CPU path draws the rays nearly transparent. EpisodeB2's Phase B
pixels are Phase A's but single pixels (largest channel 30). The defect is
Phase B's (forced, or a default that flips programs), not the Default's or
Phase A's; its fix is a session of its own (started 2026-09-28), whose
uncommitted edit (`pack_rows` writes a source's base-point rows from its
first point, as its shader data does, so a patch fill no longer fans from
a stale base point after an updater's `become()`) is in this worktree and
not in B6's commit. A diagnosis rerun with it in place read 0% between
programs and the CPU path; the figures here are without it, and only the
play figures can move with it (the archive's README says which run
measured what).

**What stands between this and the end state.** Taylor's end state:
"python sends the control points once and only directs the GPU what to
change; if nothing changes python is silent". On the wire and in the
browser that holds at rest now: a frame that changes nothing sends nothing
and draws nothing. Python is not silent. Its remaining per-frame costs,
each measured (the instrumented run, `test_point python`: medians per
serialization, the Default in format 8 unless named; a part's median, so
the parts do not add exactly):

- *The walk that finds nothing changed.* 0.82 ms a still EpisodeB2 frame
  (0.64 of it the draw order's walk and keeps, 0.17 the assembly and the
  stream's diff), 1.11 at 0.a, 2.43 at 5.a (461 leaves kept); 1.14 on
  PriceDiscovery. The viewer runs it for every prompted frame, and up to
  45 times a second while updaters are live.
- *The episode's own updaters.* 20.7 ms a tick at 8.a, against its 4.6 ms
  of serialize: at rest on 8.a the largest Python cost there is, four and
  a half times the serializer's. 1.2 ms a tick at 3.i, 1.45 on
  PriceDiscovery. In plays the scene's
  own Python (interpolation and updaters) is 20.6 ms a frame on 8.a's play,
  4.7 on 5.a's, 0.95 at PriceDiscovery's median. Python by construction
  until the updaters run on the GPU's clock (TODO.md, "After").
- *The revision counter's over-signalling.* A tick at 8.a bumps 415 of 531
  leaves and changes no byte; comparing and keeping them is 1.83 ms of the
  4.59 ms serialize (40%); 3.i's 23 leaves 0.16 of 1.43 ms; PriceDiscovery's
  49 leaves 0.24 of 1.16 ms. The
  truthful fix is upstream in the mutators ("What to watch").
- *Lyon on Phase A movers.* Only 8.a's play tessellates among the plays
  measured: 360 fills a frame, 11.0-11.6 ms (Default and today alike), of
  its 84.6 ms of preparation; every other play's movers keep their meshes.
- *The rest of a Phase A mover.* 8.a's play prepares 360 leaves in 84.6 ms
  (73 beyond Lyon, ~200 µs a leaf: the plane fit, the border source, the
  stroke's read, classification, tier 1's records) and encodes in 3.5;
  5.a's play prepares all 461 in 52.6 ms and encodes in 13.5, 2.4 MB a
  message. B5.1's rows halve the 8.a play's serialize under patches (51.6
  against 104.5 ms) but are not the default.
- *Phase B's movers.* Where they are programs a program is a batch of its
  own, encoded and diffed every frame: 5.a's play 18.7 ms of encode and 3.3
  of diff in its 26.5 ms serialize (461 programs, 20 KB a message). Where
  they are not (8.a's movers are written by updaters, so `programs.admits`
  keeps them on the CPU) their records are packed: 92.3 ms of preparation
  and 15.4 of encode, 972 KB a message.
- *The stream's diff*, on Phase A: at most 0.07 ms a frame.

**B4.9, render bundles: its condition is not shown either way.** Its
condition was Dawn's per-draw cost above 1 ms at 911 slots, which the fake
device cannot see, so the retained 8.a frame was redrawn on this machine's
WebGPU (Chrome 152, Dawn on Metal; the archive's `device_redraw.html`), 200
resends back to back, the two stacks in turns, six rounds each: the page's
JavaScript is 0.10
ms a redraw at 444 batches and 445 draws (Phase A) and 0.89 ms at 911
and 1841 (Phase B), against 0.065 and 0.14 on the fake device, the
difference being Chrome's serialization of the calls; the redraw sustains
1.29-1.35 and 1.74-1.78 ms a frame with Dawn's GPU process and the GPU
behind it. The page's JavaScript is the renderer end of Dawn's wire only:
0.89 ms at the median, its six rounds 0.64-1.19 ms (two over 1 ms), taken
at load 5-9 with other sessions active. The GPU process's end (the wire
server, validation, Metal encoding) was not isolated, and the only figure
that holds it, the sustained redraw, holds the GPU's work too. So the
measurement leaves the condition unresolved rather than failed. To settle it: retake on a quiet machine
with the GPU process's time isolated, by `redraw()` over the 8.a stream
serialized at a tiny resolution (the GPU then negligible, the sustained
redraw Dawn's) or by the GPU process's task time in a Chrome trace. Under
format 8 no frame at rest is redrawn at all. Played
message by message (three rounds, the page's clock coarsened to 0.1 ms)
the device's page reads a little above the fake device's at the play
medians (1.0 against 0.76 ms, Phase A, format 8; 0.4
against 0.30, Phase B), and twice it on Phase B's 8.a play (8.7-9.0 against
4.6-4.7 ms, the ~1400 buffers it makes a frame).

**B5.2, the patch run rule: its condition is not met by these numbers.**
Its condition was the draw count mattering once the draw list is retained.
Phase B draws 4.1 times Phase A's at 8.a (1841 against 445; 855 against
437 at 0.a), and that costs a drawn frame the page's 0.89 against 0.10 ms
above and, natively, the GPU's out pass 4.85 against 4.08 ms at EpisodeB2's
pausepoints (6.02 against 4.47 ticked; 4.50 against 3.78 on PriceDiscovery;
on the device the whole sustained redraw of 8.a is 1.74-1.78 against
1.29-1.35 ms).
Under format 8 neither is paid at rest, and in plays Phase B's out pass is
Phase A's (4.28 against 4.25 ms): the play gap is the programs' and
borders' passes (the one-dispatch fix B5.1, B5.3 and B5.4 name) and, on
8.a, the records packed.

**To merge.** Nothing here is merged. `b4-integration` is `main` plus tier
1, tier 2, B5.1, B5.3, B5.4, B6 and B5.5, each a commit with its proof; `main` is
frozen until Taylor says the class is done. When he chooses:

```bash
git -C /Users/taylorjweidman/Projects/ManimLive/maniml merge --no-ff b4-integration
```

## After B4: the flips and the test point

**B5.1 Rows on the wire under patches.** A mover sends its 17-float rows and
its 8-word object record, both drivers run `row_finalize.wgsl` into per-object
curve records (the shader exists, B3 uses it), so a mover costs Python a
memcpy; the measured floor is 2.65 ms + 206 KB for the 375 movers of 8.a
against 82 ms of packing today. Changes the B1 wire and moves the planar
check: the refusal of nonplanar closed contours is kept unless Taylor decides
otherwise. Taken before the B1 flip.

**B5.2 The patch run rule**, conditional. Per-object colour and opacity into
the object record so a frame's opaque patch objects are one group. Taken only
if B4.6's browser number shows the draw count mattering once the draw list is
retained; the GPU side of B1 is +0.3 ms on text and +1–2 ms on a diagram
regardless.

**B5.3 Programs for strokes on Phase A.** The stroke-only relaxation of
"programs require patches": an unfilled path's ShowCreation / VFade / Rotate
becomes a program without B1. Cheap; widens what B3 buys before the fill
flip.

**B5.4 The flips.** B2 nets first (independent of B1; pixel gate on
PriceDiscovery); then B1 patches; then B3 gpu programs; each on its gate,
each reversible from the selector, Phase A always selectable. Measured
2026-09-28: "The flips" above.

**B5.5 One dispatch for a frame's nets.** Each driver decides a net's
steps and keys its evaluation on them, and evaluates a frame's changed
nets in one dispatch over a table, copied into the outputs their slots
own; then the nets gate again. Measured 2026-09-28: it passed on the
gate's three scenes and failed on scenes that are mostly surfaces (the
redraw: a net draws its capacity's triangles), so grids stay the default
("The flips", B5.5).

**B5.6 Rows as the patch source.** `MANIML_PATCH_SOURCE`'s default is
`rows` wherever patches are drawn, the forced Phase B included, with
`records` the override. Done 2026-09-29: pixels identical, the pin
untouched (it states records); the test point retaken with the selection's
Phase B beside B6's: 8.a's play 127.3 → 80.5 ms, each class's median
within 0.5 ms, navigations dearer natively (+15-28%) until one dispatch finalizes
a frame's rows and a change of paint alone stops resending them ("The
flips", B5.6).

**B5.7 Nets drawn as grids are.** Each net drawn with the index pattern
of its steps, consecutive nets that can share a draw one batch in both
drivers and the player, and the nets gate judged over a timed set with
two scenes that are mostly surfaces. Done 2026-09-29: pixels unchanged,
the pin untouched (it states each net a batch of its own); the three
scenes pass, the orbs (1.06-1.15×) and the lattice (1.11-1.24×, and 0.98%
of its pixels, silhouettes where the net is the rounder) fail, so grids
stay ("The flips", B5.7).

**B6 The final test point.** Both episodes through `episode_frames.py
--tick-updaters --play-frames` with variants `[gpu_border, retained,
phase_b_retained]`: Python ms per frame at rest and in plays, browser JS ms
and wire bytes from `browser_frames.py` over the same frames, GPU ms from the
timestamp attribution run, pixels against Phase A. That table is where the
default decisions are read. Measured 2026-09-28 for four stacks (today,
Phase A retained, the Default, Phase B forced): "The final test point"
above.

## What evidence flips B1 — a question left open

The gate Taylor set on 2026-09-26 was "complete frame, per the plan", measured
by the native harness. B4 changes what that measures: the native driver does
not learn the retained draw list (only the browser does), so the native
`render_cpu_encode` column will keep charging B1 for 1840 draws per frame
while the browser replays a retained list. The recommendation is that the
flip reads the browser-side complete frame — Python serialize + browser JS +
GPU — from B4.6's harness and the live viewer's measure, with the native
harness kept for pixels and GPU attribution. This is the one B4 decision
that is Taylor's rather than engineering, and B4 itself does not depend on
it.

Settled on 2026-09-27: Taylor confirmed the browser-side complete frame
(Python `serialize_ms` + the page's JavaScript from `browser_frames.py` +
GPU total from the timestamp attribution run) at or below Phase A's on both
episodes, per class (pausepoint, ticked, play), with pixels within 0.5% of
Phase A. B5.4 measured it (`benchmarks/flip_gates.py`, "The flips" above).

## What to watch

- **The revision counter over-signals.** 415 of 531 drawn leaves bump per
  idle tick at 8.a with zero bytes changed (`set_points_as_corners`
  updaters, `become`, zero shifts). Tier 1 pays a compare per bumped leaf
  (11 µs each), not a rebuild; the truthful fix is upstream in the mutators
  and changes the contract the ledger relies on — not B4's.
- **Wider trust surface.** A trusted leaf skips classify, the mesh read and
  the border read; a bypassing in-place write is invisible unless the
  revision moved. Verify mode rebuilds every trusted leaf; the bytes policy
  disables leaf trust; the golden pin runs on every increment.
- **Run identity depends on the caches handing back the same arrays.** An
  LRU eviction breaks identity and costs a rehash and, in tier 2, a
  replaced slot with the same hash (cached, no bytes): correct, a cliff near
  the budget. The retired store is counted in the same budget.
- **The shared uniform-set dict is mutable state** referenced by retained
  draws; anything that keeps a `TriangleDraw` across frames sees the current
  camera. Byte identity is the guard; per-object uniform keys go through
  the string `override_key`.
- **Tier 2 makes ordering a correctness requirement.** A delta against the
  wrong base is a corrupt frame; mode switches, render errors and reconnects
  clear the slot list and force a full frame; a lost epoch is caught by the
  `epoch` / `base` check, never by a visible glitch.
- **Three mirrors, two of them full-frame.** The native driver never sees a
  delta, so the browser's delta path is pixel-tested against native only
  through the Node equivalence (delta-then-render equals full-then-render).
- **GC pauses** of 220–340 ms from a million tracked checkpoint objects land
  in cold frames today and once in a play frame; B4 does not change that,
  and a 1 ms still frame makes them more visible.
- **Multi-client** stays one cache per viewer: a second tab's connect resets
  the epoch for every tab, as today.

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
each reversible from the selector, Phase A always selectable.

**B6 The final test point.** Both episodes through `episode_frames.py
--tick-updaters --play-frames` with variants `[gpu_border, retained,
phase_b_retained]`: Python ms per frame at rest and in plays, browser JS ms
and wire bytes from `browser_frames.py` over the same frames, GPU ms from the
timestamp attribution run, pixels against Phase A. That table is where the
default decisions are read.

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

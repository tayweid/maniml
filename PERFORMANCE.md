# Performance scalability review

Reviewed 2026-08-20 at commit `4f59cc27`.

This document audits ManimLive's interactive engine, checkpoint system, native
renderer, browser renderers, transport, process lifecycle, caches, movie
writer, and exported player. It is a performance roadmap, not a record of code
changes: the review deliberately left runtime behavior unchanged.

## Executive conclusion

ManimLive is now paced well enough for small scenes, but several core costs are
proportional to the *entire scene or its entire history*, even when only one
object changed. That is the main obstacle to scaling. The recent relay,
presentation-clock, and launchd fixes address frame cadence; they do not remove
the large-scene work described here.

The five most important changes are:

1. Make render batches non-owning. They currently become semantic parents and
   leak through checkpoint copies, so restores progressively enlarge the scene
   graph.
2. Add stable object/resource IDs and explicit geometry, uniform, transform,
   order, and camera revisions. Clean objects must not be walked, copied,
   converted to bytes, or hashed every frame.
3. Replace full-scene checkpoint copies with copy-on-write/delta snapshots,
   periodic keyframes, and a configurable memory/history budget.
4. Stop native OpenGL capture while the browser is the sole renderer, and stop
   all redraws while a scene is idle and clean.
5. Use bounded, byte-accounted queues and caches throughout the browser path.
   Reuse mutable GPU resources instead of caching hundreds of historical
   versions of an animated batch.

The desired invariant is simple: **the cost of one frame should track the size
of what changed, not the size of everything that exists.**

## Confirmed cadence diagnosis and current baseline

The original installed-app judder was not spatial aliasing. Its primary
environment-specific cause was launchd scheduling: the agent plist omitted
`ProcessType`, so macOS applied light CPU/I/O resource limits to the agent and
the scene processes it spawned. Shell-started scenes and agents did not inherit
that policy, which is why direct/manual comparisons repeatedly looked healthy.

The root-cause fix and four supporting changes now make the small-scene path
behave correctly:

| Commit | Closed failure mode |
| --- | --- |
| `4f59cc27` | Sets `ProcessType=Interactive`; fixes the installed-app-only inherited launchd throttle and the observed ~19 fps ceiling. |
| `e0313644` | Removes the relay's 32-message receive backlog, which had released frames in clumps. |
| `c536c0ae` | Stops one browser refresh from draining and applying multiple geometry states that could never be painted. |
| `01689ca8` | Stops short animations from losing one of a small fixed number of engine frames. |
| `0d2d9cad` | Aligns client presentation work to display refresh boundaries instead of running directly in the socket callback. |

The post-fix installed app at `localhost:8685` measured 33.5 ms median frame
spacing and 45.5 ms p95, with zero observed bunching and zero queue backup. The
reported validation suite had 195 passing tests and the same two pre-existing
`test_app.py` failures. These are handoff results from the cadence investigation,
not measurements rerun as part of this document-only audit.

This closes the original diagnosis, but not every timing concern. The relay is
now shallow; it is not an end-to-end playback clock. A WebSocket `send()` may
complete when bytes enter an OS buffer, and the client still presents based on
arrival. `0d2d9cad` aligns work to `requestAnimationFrame` but does not absorb
arrival jitter. The durable transport item below therefore remains: timestamp
frames and present them against a small bounded media clock.

Performance comparisons must cross the same execution boundary as the user.
At minimum, compare the same app-spawned scene through direct and relayed routes,
then independently compare shell- and launchd-spawned processes through the
same route. A hand-started process cannot detect inherited launchd policy.

### Separate open symptom: `AddTextWordByWord`

The reported “goes on very quickly in one chunk” behavior is a semantic grouping
bug, not evidence that frame pacing remains broken.

`AddTextWordByWord` calls `StringMobject.build_groups()` and sets `run_time` to
`time_per_word * len(groups)`. `build_groups()` groups consecutive SVG glyphs by
StringMobject label/isolate spans, not by whitespace-delimited words. Ordinary
unisolated `Tex` therefore produces one group and the default animation lasts
0.2 seconds—six engine frames at 30 fps, but only one possible visual reveal.
Double-braced/isolated portions produce a few label chunks, still not words.

**Evidence:** `maniml/animation/creation.py:AddTextWordByWord` and
`ShowIncreasingSubsets`; `maniml/mobject/svg/string_mobject.py:build_groups`;
`maniml/mobject/svg/text_mobject.py:MarkupText.__init__`.

There is a related `Text`/`MarkupText` problem: those constructors define a
word-like isolate default but do not forward it to `StringMobject.__init__`,
which resets `isolate` to `()`. Explicit `Text` isolation is lost as well.

Define ManimLive's intended word-tokenization behavior without changing generic
`build_groups()`, whose label semantics are used by substring/color machinery.
A narrow remedy is a dedicated word-group method built on the existing
`select_unisolated_substring(re.compile(r"\S+"))` path. Forwarding
`MarkupText.isolate` to `StringMobject` is a separate correctness fix whose
broader labeling/selection effects need their own regression coverage.

Add an engine test using a five-word sentence that asserts five semantic groups,
a 1.0-second default duration, and visible counts progressing 0→1→2→3→4→5 at
roughly 0.2-second intervals. Include punctuation, escaped spaces, TeX math,
explicit isolate, and `Text` cases. For transport diagnosis, explicitly
brace/isolate five groups and compare engine/reference transition timestamps
with the installed-app capture; the current unbraced scene has only one or two
states before rendering.

## Measured baseline

These focused measurements were taken on an Apple M3 MacBook Air with 24 GB of
memory, macOS 26.3.1, and Python 3.13.9. They are directional local
measurements, not a portable performance contract. Browser paint, WebSocket
transport, and energy use need a repeatable end-to-end harness before absolute
budgets are enforced.

The probes used NumPy 2.5.2, Pillow 12.3.0, and ModernGL 5.12.0. They were
focused ad hoc diagnostics, not a committed benchmark suite: their exact
warmups, repetitions, fixture source, GL renderer, and dependency lock must be
captured by the benchmark work below before these values are used as regression
thresholds. They are recorded here to show order of growth and prioritize work.

### Geometry serialization

A scene containing a single `VGroup` of equal-state `Square` objects was warmed,
serialized with the real geometry cache, and then serialized again after moving
one child.

| Objects | Cached, unchanged | Move one child | Moved payload |
| ---: | ---: | ---: | ---: |
| 1,000 | 8.7 ms | 9.0 ms | 0.82 MB |
| 2,500 | 21.1 ms | 21.7 ms | 2.04 MB |
| 5,000 | 45.3 ms | 45.2 ms | 4.08 MB |

An unchanged payload is only about 0.9 KB, so the existing content cache is
effective at reducing wire bytes. It does **not** reduce the full scene walk,
array concatenation, `tobytes`, and hashing cost. Moving one child changes the
merged batch and retransmits all of its static siblings. At 5,000 objects,
serialization alone is already over a 30 fps frame budget.

A second benchmark with 1,000 `Circle` objects produced a 3.26 MB merged batch:
34.9 ms cold, 11.2 ms cached and unchanged, and 11.9 ms plus the full 3.26 MB
after moving one circle. Deliberately preventing merging reduced large payloads
but raised per-frame Python/header work, showing that simply making every object
its own draw batch is not the answer. Stable bounded-size resources and a
separate ordered draw list are needed.

### Native batch invalidation

The warmed native OpenGL capture path is cheap while the batch remains clean,
but changing one square invalidates and reuploads its whole render group.

| Objects | Stable capture | Move one child |
| ---: | ---: | ---: |
| 1,000 | 0.31 ms | 3.07 ms |
| 2,500 | 0.45 ms | 8.47 ms |
| 5,000 | 0.44 ms | 17.34 ms |

No explicit `ctx.finish()` was included, so this isolates the CPU
submission/rebuild path rather than GPU completion time. The linear
invalidation trend is still clear; future GPU measurements must record the GL
renderer and sample completed work separately.

### Checkpoints

- Fifty independent snapshots of a 1,000-square namespace averaged 35.7 ms per
  copy and increased `ru_maxrss` high-water RSS by about 243.5 MB, or 4.87 MB
  per checkpoint. High-water RSS is not the same as current/live ownership and
  can include allocator retention, so future leak tests must also sample
  current RSS/USS after controlled garbage collection and count owned arrays.
- A graph-copy benchmark using 1,000 circles took 128.8 ms with a 9.7 MB peak
  Python allocation for one copy as measured by `tracemalloc`; shape and
  namespace complexity materially affect the result.
- In a synthetic checkpoint/restore loop, a mobject's `parents` list grew from
  1 to 31 after 30 cycles because copied render groups became stale parents. For
  100 circles, copy time grew from 2.9 ms to 7.0 ms during the same experiment.

The retained-history model is approximately `O(checkpoints × scene state)` and
can approach quadratic growth when each play adds more geometry.

### Other focused measurements

- Reading a warmed 1920×1080 framebuffer took about 3.3 ms and Pillow 12.3.0
  encoded the synthetic Manim-like frame in about 5.0 ms at quality 90 with
  4:4:4 subsampling. This roughly 8.3 ms occurs synchronously on the scene
  thread before socket delivery; encode time remains strongly content-dependent.
- `import maniml` took about 0.63–0.74 seconds and added roughly 145–153 MiB RSS.
  A fresh isolated Matplotlib cache added about 11 seconds on the tested cold
  path.
- Inserting 100, 500, 1,000, and 2,000 entries into `SafeTextCache` took 0.034,
  0.489, 1.875, and 7.131 seconds respectively. Scanning and sorting the entire
  directory after each insertion is visibly superlinear.
- The cadence investigation measured about 37 ms of non-animation work around
  a representative `play()`: roughly 17 ms in `begin_animations()` and 19 ms in
  `_save_checkpoint()` deepcopy. That delay is especially visible around very
  short animations even when their individual frames are paced correctly.
- The viewer re-encoded roughly twelve identical 1080p frames during each
  static `wait()` in the measured scene. This confirms that wait/idle
  invalidation is an immediate optimization, not only a theoretical one.

### Idle-loop pacing and parked-scene streaming (added 2026-08-26)

Follow-up probes on the interact loop, same machine class as above
(Apple Silicon, Python 3.13). A headless scene with three mobjects was
driven through `update_frame(1/fps)` in a loop, the way `interact()`
drives it with a client connected:

| State | Passes/s | Process CPU |
| --- | ---: | ---: |
| Parked, pacing clocks aligned (as after a play) | 24 | 15% |
| Parked, after one backward jump | 103 | 43% |
| Parked with an `always_redraw` updater, after jump | 83 | 54% |

Two distinct mechanisms:

- **Pacing-clock rewind.** `update_frame` paces with
  `sleep(max(vt - rt, 0))`, where `vt` derives from `scene.time` and the
  clocks are only reset at the start of a real play. Backward navigation
  (LEFT/UP/DOWN) restores `scene.time` from the checkpoint, rewinding it
  behind `real_animation_start_time`, so the sleep term goes permanently
  negative and the loop free-spins (the "~105 fps" the streaming
  throttle's comment mentions) until the next play. The fix is to reset
  or clamp the clocks on checkpoint restore — or simply pace at `1/fps`
  whenever the scene is not playing.
- **Parked scenes with updaters stream forever.** The streaming policy
  infers "animating" from `has_updaters()` on any top-level mobject, so
  a scene parked with `always_redraw`/label updaters (typical of course
  scenes) keeps JPEG-encoding visually identical 1080p frames at up to
  45 fps. Measured encode cost on this machine: 20–60 ms per frame at
  quality 90 / 4:4:4 (content-dependent; the synthetic frame above sat
  at ~5 ms, a noise frame at ~62 ms), i.e. most of one core while the
  user just looks at a paused picture. A lossless PNG — forced on every
  checkpoint-state change, so on every navigation keypress — costs
  roughly 100–400 ms of synchronous CPU at 1080p.

The pixel stream was deleted on 2026-09-02 (the browser renders every
frame from geometry, and native capture is skipped while a client
renders), which removed the encode costs above outright; the geometry
stream is delta-cached and cheap at this scene size. The measurements
stay here as the record of what the JPEG path cost.

## The scaling model to aim for

| Operation | Current behavior | Required behavior |
| --- | --- | --- |
| Clean idle scene | Updates and captures at the camera FPS | Sleeps until input, watcher, updater, or timer work exists |
| One object moves | Rebuilds, uploads, serializes, and often sends its whole merged batch | Updates one resource or a bounded chunk plus transform/uniform state |
| Camera-only move | Re-walks and hashes all geometry | Sends camera revision only; reuses all geometry |
| Save checkpoint | Copies the full scene graph and mutable namespace | Records changed state with structural sharing; occasional keyframe |
| Retain history | Unbounded full snapshots | Explicit byte/history budget with eviction or replay fallback |
| Browser cache | Entry-count or unbounded history | Byte budget, active-frame pinning, explicit destruction |
| Transport backlog | Work moves between several implicit queues | Reliable resource channel plus latest-wins timestamped display state |
| Export | Holds all frames in producer and consumer memory | Streams/chunks resources and frame records with direct-seek keyframes |

## Prioritized findings

`P0` items block the large-scene goal or cause unbounded growth. `P1` items are
high-value next work. `P2` items matter in particular workloads or long-running
sessions but should follow the structural changes.

### P0: make render batches non-owning

**Current path:** `Scene.assemble_render_groups()` creates ordinary
`Group`/`VGroup` instances. Ordinary group construction registers the group in
each child's `parents` list. Generic checkpoint copying then follows and copies
these render-only parents. A restored scene creates fresh render groups, while
the copied old groups are no longer present in `scene.render_groups` and cannot
be cleared.

**Evidence:** `maniml/scene/scene.py:assemble_render_groups`,
`maniml/mobject/mobject.py:Mobject.add`, and the 1-to-31 parent-growth
measurement above.

**Required change:** represent render batches as non-owning renderer data, not
semantic mobjects. At minimum, tag render-only parents and exclude them from
snapshotting/restoration, then normalize existing restored graphs. The durable
design is a render-batch object containing weak/non-owning members and GPU
resources. Stale parents also make every later `note_changed_data()` traverse
and dirty obsolete render groups, so this leak slows ordinary animation after
restore—not only subsequent checkpoint copies.

**Acceptance test:** 100 save/restore/replay cycles leave every semantic
mobject's parent count unchanged and do not increase checkpoint time, mutation
time, frame-update time, or RSS.

### P0: replace whole-state checkpoints

**Current path:** `_save_checkpoint()` places `SceneState` in the captured
namespace and deep-copies the namespace and state together. `run_next_animation`
copies the current checkpoint again before executing a unit, and display
navigation copies it again before restoration. `animation_checkpoints` retains
every result without a byte or count limit.

**Evidence:** `maniml/scene/checkpoints.py:_save_checkpoint`,
`run_next_animation`, `_restore_checkpoint_for_display`, and
`deepcopy_namespace`; `maniml/scene/scene.py:SceneState`.

The copy includes mutable globals and unrelated NumPy arrays, not just state
reachable from displayed mobjects. Derived data such as GPU wrappers,
triangulation caches, source images, and immutable module data should not be in
snapshot ownership.

**Required change:**

- Give mutable mobject arrays copy-on-write storage and revision IDs.
- Store a persistent/delta scene snapshot and a small namespace binding map.
- Share immutable globals, assets, and module objects explicitly.
- Define a conservative namespace contract. Unknown mutable values must still
  be copied unless a type explicitly supports snapshots or is registered as
  immutable; preserve aliases, cycles, custom objects, and NumPy view/base
  relationships exactly.
- Use periodic full keyframes so old deltas remain replayable.
- Add configurable checkpoint byte/count budgets and report current usage.
- In movie/export mode, retain only the state required to continue unless
  navigable checkpoint history was explicitly requested.
- Avoid pre-running and retaining a complete independent history merely to
  prepare presentation mode. Preserve navigable live state through structural
  sharing/deltas and periodic replayable live-state keyframes; rendered images
  can be incremental optional thumbnails, not a replacement for live state.

**Acceptance test:** adding one small mobject to a large static scene produces a
small checkpoint delta; 500 checkpoints remain within a configured memory cap;
forward/back/reload identity tests still pass.

### P0: introduce stable revisions and incremental geometry resources

**Current path:** `maniml/web/geometry.py:serialize_scene` walks every drawable
family member, calls `get_shader_data`, builds uniform dictionaries, merges
records, concatenates arrays, converts them to bytes, and hashes the bytes on
every emitted frame. The hash cache suppresses unchanged payload bytes only
after all of that work.

The native path has the same granularity problem. `note_changed_data()` marks
all parents dirty. `Mobject.render()` then gathers and concatenates the whole
render group's shader data, and `ShaderWrapper.read_in()` rewrites its full VBO.

**Required change:** create a shared scene-resource model with:

- Stable object and geometry-resource IDs.
- Monotonic `geometry_revision`, `transform_revision`, `uniform_revision`,
  `order_revision`, `camera_revision`, and texture revisions.
- Immutable geometry resources plus small per-object transform/material data.
- Bounded-size chunks or dirty VBO ranges, so batching remains efficient
  without making invalidation all-or-nothing.
- A frame/display-list message that orders resource IDs and carries only
  revisions changed since the client's acknowledged state.
- Cached serialized bytes for a clean revision; no byte hashing on the hot path.
- A full snapshot/keyframe path for reconnect and cache recovery.

This requires an invalidation audit before hashes are removed. `get_points()`
currently exposes writable NumPy data, and internal, custom, or user code can
mutate `data` or a view without calling `note_changed_data()`. Encapsulate
mutation or provide tracked writable access, retain full-hash validation in a
debug/test mode during migration, and conservatively fall back for custom
mobjects whose mutation behavior is unknown.

Do not optimize this by merely selecting a faster hash or by making thousands
of tiny draw calls. The protocol and GPU representation need separate resource
lifetime from draw ordering.

Also fix the adjacent cache-integrity issue in
`maniml/web/geometry.py`: the triangulated batch hash includes vertex bytes but
not index bytes.

**Acceptance tests:**

- An unchanged 5,000-object frame calls no clean object's `get_shader_data` and
  sends constant-size frame metadata.
- Moving one object does not copy, upload, hash, or send its static siblings.
- Camera-only movement sends no geometry.
- Direct slice writes, writable views, texture replacement, uniform edits,
  submobject reordering, and custom mobjects all advance the correct revision
  or take a safe fallback path.
- Reconnect, cache eviction, and backward seek recover from an explicit
  keyframe without missing geometry.

### P0: stop rendering clean or browser-only frames natively

**Current path:** the interactive loop calls `update_frame(1 / fps)` even when
paused. Because `dt` is nonzero, the idle shortcut does not apply and
`camera.capture()` runs. `should_update_mobjects()` exists but is unused. The
viewer callback comes after capture, so WebGPU-solo and geometry export still
rasterize the complete scene through native OpenGL before the browser or
recorder processes geometry.

**Evidence:** `maniml/scene/scene.py:interact`, `update_frame`, and
`should_update_mobjects`; `maniml/web/viewer.py:on_frame_rendered`.

**Required change:** maintain explicit visual, camera, updater, input, and
watcher dirty generations. Pump events independently of capture and sleep while
clean. Updater-driven scenes retain a clock. In geometry-only mode, serialize
logical scene state without native rasterization. A static `wait()` should be a
duration/hold, not repeated identical renders; the measured live path currently
re-encoded about twelve identical 1080p frames per static wait.

**Acceptance test:** a clean paused scene records zero captures and near-zero
serialization work after its final frame; geometry-only animation performs no
native framebuffer draw or readback.

### P0: bound transport work and resource lifetime

**Current path:** `WebServer.broadcast()` schedules send coroutines without a
hard per-client outbound bound. `_busy` approximates one in-flight droppable
frame but is not a serialized writer queue; non-droppable geometry can continue
to accumulate. The relay's `max_queue=1` bounds only one receive queue.

In the browser, the visible geometry queue is limited, but catch-up calls
`handleGeometry()` for every old state and appends them to an unbounded promise
chain. This can retain every `ArrayBuffer`, submit many GPU frames before one
paint, and move the backlog rather than eliminate it.

**Required change:**

- One serialized writer task and explicit byte/message budget per client.
- Per-client renderer subscription, acknowledged resource revisions, and cache
  state. The current viewer-global geometry mode and `sent` cache cannot
  describe two clients with different capabilities or cache contents.
- Reliable, deduplicated resource updates separate from a latest-wins display
  state.
- Sequence numbers, capture timestamps, presentation timestamps, queue-age
  telemetry, and acknowledgement of resource revisions.
- Ingest necessary deltas without drawing intermediate frames; present one
  timestamp-selected state per refresh.
- A small bounded frames-in-flight budget for WebGPU.
- Coalesce wheel/pointer input on both client and server.

Increasing queue sizes or dropping arbitrary delta messages will hide the
symptom and break resource consistency; the two message classes must be
separated first.

### P0: replace history caches with byte-bounded resource caches

**Current path:** both browser renderers keep up to 512 batch hashes. A single
3.26 MB evolving batch has a theoretical retained-buffer upper estimate of
about 1.67 GB before allocator/metadata overhead; this is not a measured GPU
allocation. The count also thrashes when one active frame legitimately
references more than 512 batches. Browser texture caches, Python texture
tables, geometry `sent` history, SVG/path caches, and several native GL caches
are unbounded.

**Required change:** use byte-accounted LRUs with active-frame pinning and
explicit GPU destruction. Classify resources as immutable/cacheable or
ephemeral/mutable. Update an evolving batch in a reusable capacity-managed GPU
slot instead of caching every prior version. Align server and client retention
so a server never assumes a client still owns an evicted resource.

**Acceptance test:** a 30-minute continuously animated scene reaches a stable
RSS/GPU-memory plateau and recovers correctly after forced cache eviction.

### P0: make export memory proportional to a working set

**Current path:** `GeometryRecorder.frames` retains every complete geometry
message until recording finishes. The player downloads and decompresses the
whole archive, then `ArrayBuffer.slice()` copies every frame while retaining the
original container. Delta frames require replaying all predecessors before a
forward seek, while resources can be evicted without a player cache-miss reset.

**Evidence:** `maniml/web/export.py:GeometryRecorder` and `_write_export`;
`maniml/web/static/player.js` initial load and `show`.

**Required change:** spool/stream frame records during generation. Store an
explicit resource table plus compact frame references, independently compressed
segments, periodic keyframes, and an index. Load the active segment lazily and
use zero-copy views where possible. Run-length encode static holds.

Player pacing must use a `requestAnimationFrame` media clock with one render in
flight; `setInterval(async ...)` can overlap callbacks and is not display
synchronized. Build timeline chips once and update only old/new active state.

**Acceptance test:** 100,000-frame export generation, initial load, direct late
seek, backward seek, and playback stay within explicit memory and latency
budgets without preprocessing every frame.

## P1: high-value engine and renderer work

### Separate geometry from rigid transforms

Animations currently copy starting mobjects and mutate point arrays each frame.
`Animation.interpolate` walks submobject families in Python; rigid shifts,
scales, and rotations therefore invalidate geometry just like nonlinear
deformations.

Keep local immutable geometry plus a transform matrix wherever semantics allow.
Animate the matrix through uniforms and bake points only for nonlinear edits or
an operation that requires world-space geometry. This unlocks static geometry
reuse in native GL, the wire protocol, browser GPU buffers, triangulation, and
checkpoints. Add instancing for repeated glyphs/markers/shapes after stable
resources exist.

### Avoid quadratic scene-list rebatching

`Scene.add()` is decorated to rebuild all render groups but calls decorated
`remove()`, causing two rebuilds. Animation setup and cleanup can call add/remove
once per animated object. Each rebuild sorts all top-level objects and creates
new groups, making large `play(*animations)` setup approach quadratic work.

Add undecorated internal mutations plus a transaction/dirty flag and rebatch
once after bulk setup or cleanup. Cache draw order until membership, `z_index`,
fixed-in-frame status, or shader compatibility changes. Broaden the batch key
from exact Python type to actual compatible layout/shader state.

### Remove avoidable vector-fill work

Native GL and both browser renderers allocate a winding-fill target at twice the
configured width and height. At 1920×1080, the native RGBA16F fill plus float
depth attachments are about 100 MB. WebGPU's fill attachment alone is about
66 MB, and the 4× MSAA output/resolve/depth/fill estimate is roughly 140 MB
before swapchain and geometry resources. Actual depth allocation is
implementation-dependent. At 4K, the fill attachment alone is about 265 MB.

Stroke-only batches still enter fill/border/composite work. Add `has_fill`,
`has_fill_border`, and `has_stroke` metadata; allocate fill targets lazily; skip
empty passes; scissor to conservative batch bounds; and combine compatible
draws so MSAA resolves once. Render at the actual displayed pixel size during
interaction rather than unconditionally at export resolution.

The vector stroke draw count is currently the maximum subdivision required by
any curve in the batch; one curved segment can force every straight segment to
execute the high subdivision count. Bucket by subdivision range or move to the
planned compute-tessellation/indirect-draw path.

### Persist 3D triangulation and GPU buffers

`VShaderWrapper._get_triangulation()` hashes all point bytes and builds a dense
resolution-240 triangulation when invalid. Even on a triangulation cache hit,
`render_triangulated_fill()` concatenates vertices/indices/colors, builds a
structured array, creates VBO/IBO/VAO objects, renders, and releases them every
frame.

Cache topology separately from positions, preserve topology under affine
transforms, and retain capacity-managed GPU buffers. Update only dirty
attributes. Replace byte hashing with geometry revisions and use adaptive
tessellation/error tolerance rather than a universal dense resolution.

### Reuse uniforms and GPU objects

Native `ShaderWrapper.update_program_uniforms()` iterates, normalizes, and
compares all mobject, camera, and texture uniforms for every program on every
draw. `set_program_uniform()` already mirrors values and suppresses unchanged
GL writes; the remaining work needs dirty-uniform revisions, shared camera
uniform blocks, and revisioned material data so clean sets are not revisited.

WebGPU allocates a mapped uniform buffer and bind group for each draw/pass, then
destroys all per-frame buffers immediately after `queue.submit()`. Replace this
with an aligned dynamic-uniform ring buffer, `queue.writeBuffer`, dynamic
offsets, persistent texture views, and cached bind groups. WebGL should cache
uniform and attribute locations while it remains supported.

Move geometry parsing and command construction to an `OffscreenCanvas` worker
when browser profiles show main-thread contention. Benchmark direct
`ArrayBuffer` delivery for geometry or logically split pixel and geometry
handling: globally changing WebSocket `binaryType` removes today's geometry
Blob conversion but may add a conversion for JPEG/PNG, whose decode path wants
a Blob. Replace large per-frame JSON batch lists with compact binary
resource/frame records after the protocol redesign.

### Fix the native double swap and duplicate state work

The native camera renders to an offscreen FBO, calls `swap_buffers()`, then
letterboxes/blits and calls `swap_buffers()` again. With vsync, the first swap
can block and presents before the actual blit. Render offscreen, blit, and swap
exactly once. Confirm with a real-window trace because driver behavior is
platform-dependent.

The vector wrapper also performs duplicate `pre_render()` work and a synchronous
driver state query after setting that state itself. Remove duplicate state
setup/queries and cache the render-group sort until its fixed-in-frame status
changes.

### Optimize staggered animations and updaters

`AnimationGroup.interpolate()` calls every child animation on every frame,
including children whose clipped alpha remains at 0 or 1. Large `LaggedStart`
groups repeatedly rewrite inactive children and invalidate buffers. Track the
active time window for built-in/pure animations, initialize/finalize a child
once at each boundary, and skip stable children. Preserve current behavior for
custom animations until the lifecycle contract is explicit: repeated
`interpolate(0)`/`interpolate(1)` calls can be observably side-effectful.

Cache whether each updater accepts `dt` when it is registered rather than
inspecting `__code__.co_varnames` every invocation. `always_redraw` reconstructs
and `become()`s a complete object each frame; add value-aware/incremental helpers
and document it as inappropriate for large immutable subtrees. The updater
signature micro-optimization remains P2 until updater-heavy profiling shows it
is material.

### Add culling and interactive resolution control

All geometry is currently serialized and drawn even when wholly off-camera.
Maintain conservative bounds and frustum/viewport culling, invalidated by
geometry or transform revision. Size browser/native interactive targets from
actual viewport pixels and device pixel ratio, with a cap and adaptive render
scale based on recent frame time. Restore full configured resolution for pause,
capture, and final render.

Once resources are browser-resident, prefer browser/GPU culling so a camera
move remains a camera-only message. If unloaded geometry must be culled on the
server, query a maintained spatial index/BVH and visibility revisions rather
than reintroducing a full object walk for every camera frame.

## P1: lifecycle, startup, and cache work

### Reduce scene-process startup and baseline memory

`maniml/__init__.py` eagerly imports and re-exports nearly the complete API.
That pulls in Matplotlib pyplot, SciPy, Pyglet/native-window code, Pygments,
Pydub, tqdm, and rendering modules even on headless or lightweight command
paths. Config parsing also reads CLI/YAML state during import.

Lazily import uncommon heavy dependencies and separate lightweight
agent/app/help bootstrap from scene API initialization. Preserve `from maniml
import *` compatibility with an explicit export map and lazy attribute
resolution, while recognizing that star import resolves every name in
`__all__` and may still load the full public scene surface. The first guaranteed
win is keeping agent/app/help and non-star lightweight paths out of it. In
particular, avoid importing `matplotlib.pyplot` merely for occasional colormap
lookup and defer SciPy string-matching machinery until used.

Measure cold/warm import time, RSS, scene spawn, GL context creation, checkpoint
zero, first geometry sent, and first browser-presented frame separately.

### Evict idle scene processes and release GL resources

The app retains every distinct opened `(path, scene)` process until app
shutdown. Each child retains the roughly 150 MiB import baseline, its scene and
checkpoint graphs, GL context, server, pipe, and thread. Add a small idle LRU or
memory-budgeted process pool plus explicit close semantics.

Scene teardown does not explicitly release the camera/context, and global
context-keyed `lru_cache`s strongly retain shader programs, textures, uniform
resources, and the large fill canvas. Reuse a viewer context where safe or make
caches context-owned and provide deterministic teardown. A weak key alone is
not sufficient when its cached value refers back to the context. The global
uniform-mirror table stores only program IDs and values, so it does not retain
contexts, but it still needs lifecycle cleanup to avoid growth and reused-ID
staleness.

`id_to_mobject_map` is populated on add but not pruned on remove/clear, so hot
reload and replay can retain every formerly displayed object. Rebuild it from
active families or use weak values.

### Bound text, SVG, TeX, asset, and log storage

- Replace `SafeTextCache`'s scan/stat/sort on every insertion with a maintained
  byte-count/index and high-water/low-water batch pruning. Avoid `os.utime` on
  every hit and shard large directories.
- Put byte limits on in-process SVG/path template caches and downloaded assets;
  key mutable files by content or `(path, mtime)`.
- Exclude cosmetic progress text from TeX cache identity, add per-key
  cross-process compilation locks, and measure cached/uncached formula batches.
- Treat carriage returns as log update delimiters. TeX progress emits `\r`
  without `\n`, while `OutputTap` buffers until newline and can repeatedly
  concatenate an unbounded partial string.
- Bound `LogBuffer._pending`; when no client is connected, retain only bounded
  history rather than an unlimited pending copy.

### Vectorize surface construction

`Surface.init_points()` calls a Python function once per sample across three UV
grids. A 501×501 surface approaches 750,000 Python calls during construction.
Accept vectorized functions over mesh arrays and retain scalar fallback for API
compatibility.

## P1: movie output

(The pixel-stream readback/encoding item that used to lead this section
is moot: the stream was deleted on 2026-09-02.)

### Pipeline offline movie writes

Every movie frame performs synchronous framebuffer readback and a blocking raw
write to ffmpeg. A 1080p RGBA stream moves about 249 MB/s at 30 fps before
encoder copies. Use double/triple-buffered PBO readback, read directly from an
appropriate single-sample target, and feed ffmpeg through a bounded worker while
preserving frame order. Expose explicit fast-preview/hardware-encode presets.

Checkpoint PNG generation during render mode should be optional and should
release old full snapshots once their durable output is written. Presentation
mode still needs live navigable state, handled by the checkpoint design above.

## P2: smaller or workload-specific issues

- `_current_state()` builds arrays for every checkpoint and future unit, is
  called once for comparison and again for broadcast, and the browser rebuilds
  the entire rail DOM. Track a checkpoint/source revision and virtualize large
  timelines.
- `get_top_level_mobjects()` performs family membership counting with quadratic
  behavior. Replace it with a parent/identity set when it appears in a measured
  hot path.
- Repeated scene switches should not recreate or retain all textures, shader
  programs, and fill targets.
- File watching reads/splits/compares source repeatedly and performs debug diff
  work even when debug logging is disabled. Compute once and debounce/coalesce
  editor saves.
- Many sound additions repeatedly extend and overlay the complete accumulated
  `AudioSegment`. Store timestamped sound events and mix once at finalization.
- Export currently copies an existing destination tree into staging on every
  run. Avoid carrying large unrelated deployments through the hot export path.
- Build player timeline nodes once; do not recreate all segment nodes each
  frame.
- Cache source-derived presentation state and coalesce browser wheel events once
  per refresh.

## Instrumentation and regression plan

Optimization should start by making every stage visible. Add counters and
timers that can be enabled without a profiler:

- Python: event/update, animation interpolation, checkpoint save/restore,
  rebatch, shader-data collection, merge, byte conversion, hash, native capture,
  readback, image encode, socket enqueue, and ffmpeg write.
- Resource counts: mobjects, semantic parents, render groups, vertices, dirty
  objects/chunks, uploaded bytes, serialized bytes, checkpoint bytes, cache
  bytes/hits/evictions, scene subprocesses, and GL objects.
- Queue/timing: captured, enqueued, received, ingested, GPU-submitted, and
  browser-presented sequence/timestamps; queue depth, oldest age, dropped or
  coalesced states, and frames in flight.
- Process: cold/warm import, RSS, peak RSS, CPU time, GPU memory if available,
  context count, TeX subprocess count, and first-present latency.

The cadence investigation already produced working scratch prototypes:
`relaycheck.mjs` (arrival pacing through the app), `ab.mjs` (relay/direct live
comparison), `appshot.mjs` (CDP capture of the WebGPU canvas), `timeline.py`
(engine frame timeline), and `refmp4.py` (export/reference comparison). Promote
maintained versions into a repository benchmark/tooling directory, document
their invocation, and make installed-app provenance part of every result rather
than reimplementing the same probes ad hoc.

Timing labels must describe what they actually measure. Python
`time.monotonic()` and browser `performance.now()` do not share an epoch, so
end-to-end latency needs clock-offset estimation. A `requestAnimationFrame`
callback precedes paint rather than proving physical presentation, and WebGPU
`queue.submit()` is not GPU completion. Use browser tracing where possible and
sample `queue.onSubmittedWorkDone()` when completed GPU work matters.

Every performance gate also needs an output-correctness gate: reference final
and selected intermediate images, scene/object state, forward/back navigation,
reconnect recovery, protocol resources, and exports within defined tolerances.
Omitting work must not count as an optimization.

### Benchmark corpus

Keep fixtures representative rather than relying on one FPS number:

| Dimension | Cases |
| --- | --- |
| Scene size | 10, 100, 500, 2,000, and 5,000 mobjects |
| Scene complexity | Total vertices/curves; mergeable vs unique uniforms; batch count; texture count/bytes |
| Change pattern | Static, camera only, one object, one bounded chunk, all morphing |
| Geometry | Squares/circles, long text, images, surfaces, filled 3D vectors |
| Animation | 0.1 s and longer transforms; updater; `always_redraw`; large `AnimationGroup`/`LaggedStart` |
| Checkpoints | 10, 100, 500; small and large NumPy namespaces; repeated restore/reload |
| Text/TeX | 10, 100, 1,000; cold, warm, repeated, concurrent scene processes |
| Resolution | 720p, 1080p, 4K; device-pixel ratios; MSAA off/4× |
| Renderer | WebGPU, pixel, and mixed/fallback; 30/60 Hz; adapter/backend recorded |
| Process origin | Same direct route from shell vs launchd; verify scheduling policy independently |
| Network route | Same app-spawned process via direct port vs relay; then complete installed-app path |
| Client health | Normal, deliberately slow, background/foreground, disconnect/reconnect |
| Lifecycle | 5/20 scene opens and a 30-minute active/idle soak |
| Export | 1,000, 10,000, and 100,000 frames; direct and backward seek |
| Startup API | Lightweight CLI/app path and canonical `from maniml import *` scene import |
| Real project | The original `ECON_0100` jitter scene plus at least one geometry-heavy course scene |

Track median and p95 stage times, missed presentation deadlines, bytes per
frame, peak/steady RSS, GPU memory, queue age, and cache growth. Keep wall-clock
benchmarks in a separate suite and trend them on a stable scheduled macOS
runner before making tight timing thresholds merge-blocking. Deterministic
structural assertions can run in normal CI immediately.

### Characterization and regression tests to add now

1. Assert that generated/installed launchd plists contain
   `ProcessType=Interactive`; this prevents scheduling policy from being
   misdiagnosed as relay overhead again.
2. Commit representative small/large fixtures and record current stage counts,
   bytes, images, and state transitions without making noisy wall time a normal
   CI gate.
3. Lock down forward/back/reload behavior for aliased and cyclic namespaces,
   NumPy arrays/views, direct data mutation, custom objects, textures, uniform
   edits, and submobject reordering before changing snapshot/invalidation rules.
4. Add image/protocol parity checks for the original `ECON_0100` scene and the
   synthetic scale fixtures at selected intermediate and final frames.
5. In a browser lane, fail rather than silently pass if WebGPU does not
   initialize; record the adapter and selected backend. Keep a separate
   intentional fallback test.

### Acceptance tests to land with the corresponding change

1. Render-only parents never appear in checkpoints; parent count and mutation
   cost remain bounded through 100 restores.
2. A clean idle scene does not call `camera.capture`.
3. WebGPU-only mode does not call native capture/readback for scenes whose
   geometry is fully supported.
4. Moving one member of a large group uploads/serializes only its resource or
   bounded chunk.
5. Bulk add/remove causes one render-group rebuild.
6. Checkpoint and cache byte budgets are enforced without corrupting aliases or
   navigation.
7. A slow client cannot produce unbounded Python, relay, JS, or GPU queues.
8. Resource eviction, reconnect, and late/backward export seeks recover from a
   keyframe.
9. Scene switching releases processes, Python references, contexts, and GPU
   resources.
10. Built-in/pure `LaggedStart` children do no repeated work outside their
    active interval, while custom animation behavior remains compatible.
11. Long TeX progress output and disconnected logs remain bounded.

Run slow-client/relay/browser presentation, GPU completion, process-lifecycle,
and 30-minute memory tests in scheduled integration/soak jobs rather than
pretending they are deterministic unit tests.

The current CI is principally a correctness suite, manually selects tests, and
does not exercise the intended browser WebGPU path as a required capability.
Add structural coverage first, then a browser integration lane and scheduled
performance trend job.

## Proposed delivery order

The sequence below minimizes throwaway optimization:

1. **Measure, stop leaks, and reduce checkpoint damage:** add stage/resource
   counters; make render batches non-owning; exclude immutable/derived assets
   and redundant state from snapshots; disable full history where it is not
   needed; add checkpoint byte accounting with replay-backed limits; cap logs;
   prune dead `id_to_mobject_map` entries; and add lifecycle teardown tests.
2. **Stop avoidable work:** event-driven idle loop, geometry-only native bypass,
   single native swap, bulk scene mutations, empty fill/stroke pass skipping,
   cached state/uniform locations, and actual-viewport preview resolution.
3. **Build the resource/revision layer:** stable IDs, revisions, transforms,
   bounded chunks, dirty ranges, byte-budgeted caches, and keyframes. Use it for
   both native and browser paths.
4. **Complete the checkpoint redesign on that foundation:** structural
   sharing/COW, delta state, namespace policy, and periodic live-state
   keyframes.
5. **Harden browser delivery:** reliable resources plus latest-wins timestamped
   display state, one bounded writer per client, GPU uniform/resource reuse,
   worker parsing, and presentation telemetry.
6. **Scale offline paths:** streaming geometry export, indexed player chunks,
   media-clock playback, pipelined framebuffer readback, and bounded encoding.
7. **Reduce startup and specialist costs:** lazy imports, scene-process LRU,
   bounded text/SVG/TeX caches, vectorized surfaces, and updater ergonomics.

After steps 1–4, a one-object animation in a large scene should finally be a
small operation throughout the complete pipeline. That is the key milestone;
later GPU and transport tuning will then compound instead of masking
whole-scene work.

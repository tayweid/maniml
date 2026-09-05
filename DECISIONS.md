# Decisions

The record of what was decided, what shipped, and what was tried and
deleted — with the reasoning, so none of it gets re-litigated by
accident. The forward roadmap lives in `TODO.md`; the architecture as
it stands lives in `CLAUDE.md`. Commit messages carry the finer grain.

## The browser is the viewer (decided 2026-08-12)

The pyglet window is the most alien inherited layer and the part of the
stack that feels wrong; the browser is the UI toolkit we're fluent in
(Plass). Move the VIEWER, not the renderer — staged so the UI
investment carries over completely and the shader port never happens at
the same time as a UI rebuild.

## Stage 1 — browser viewer, native renderer (shipped 2026-08-13)

Shipped as an additive `--web` flag (`maniml scene.py Name --web`,
combines with `--present`; `--no-browser` suppresses the auto-opened
tab). Built in `maniml/web/`: server (WebSocket + HTTP on one daemon
thread), WebViewer duck-typing the Window interface with the camera
running windowless on the standalone GL context (the `--render` path),
and a vanilla-JS client. Protocol as sketched: JPEG while animating or
input arriving, one lossless PNG at quiet; state JSON on change;
picking server-side. End-to-end tested headlessly in
`tests/test_web_viewer.py`. Measured streaming tax ~3.7ms/frame at
1080p (readback 1.4 + PIL JPEG 2.4).

Deliberately not done at the time, as risk containment — the pyglet
path stays untouched until `--web` earns trust in daily use. Those
holds are now roadmap items in `TODO.md`: deleting
`rendering/window.py` and the pyglet dependency, moving the `--present`
timeline from the GL overlay to DOM, porting `tests/test_interactive`
to a browser-driven harness.

## Stage 2 — the client learns to render (2026-08-13/14)

The portability payoff: the viewer requests a geometry snapshot
(message 0x03: camera/mobject uniforms plus the raw interleaved
VMobject vertex structs) and renders it with its own GPU next to the
pixel stream.

A correction that shaped the port: the pipeline is NOT
geometry-shader-free — maniml and current 3b1b/manim both have four
geometry shaders (quadratic_bezier fill/stroke/depth, true_dot), and
the stroke one carries the adaptive polyline + joints. The port
therefore re-expresses them as *instanced vertex shaders* (one instance
per bezier triple, `gl_VertexID` enumerating the emitted strip) rather
than transliterating. Shader sources are shared between the browser
(`static/glsl/`, `static/gl.js`) and `web/reference_renderer.py`, a
desktop-GL mirror that `tests/test_gl_port.py` pixel-diffs against the
native renderer (mean |diff| 4e-5/255 on a fill+stroke+winding+Text
scene).

The parity ledger closed 2026-08-13/14, in order: 3D VMobjects
(triangulated fill serialized as vertices+indices+flat color, depth
test, MSAA via multisampled renderbuffer + resolve; 3D fidelity mean
|diff| 0.003/255); DotCloud (billboard geometry shader as a 4-vertex
instanced strip; bit-perfect); ImageMobject (raw file bytes by content
hash, browser decodes natively; bit-perfect); Surface and
TexturedSurface (bit-perfect); clip planes (v_clip varying + fragment
discard, the pixel-resolution equivalent of gl_ClipDistance). The
winding-fill depth pre-pass is a FALLBACK BY DESIGN: unreachable
through the public API, since `ThreeDScene.add` / `apply_depth_test`
always switch fills to triangulated — declared `unsupported`, revisit
only if dogfooding ever surfaces it. `set_color_by_code` and the
fractal shaders are niche and likely permanent pixel-stream fallbacks.
Anything unsupported stays honestly declared in the payload's
`unsupported` list, with the pixel stream as the fallback throughout.

Delta encoding (2026-08-14): batches carry a blake2b content hash;
unchanged batches ship as `"cached": true` references (zero bytes)
while metadata stays fresh so zoom changes need no re-upload. Client
and reference renderer cache GPU buffers/VAOs by hash (LRU 512); a
client cache miss requests `geometry_reset`; the server-side sent-set
resets on connect and on mode-on. The remaining serialize CPU per frame
is the numpy get_shader_data walk — optimize via `_data_has_changed`
only if profiling ever demands.

Solo-GL view (2026-08-14): the renderer buttons cycle off →
side-by-side compare → solo. In solo the pixel stream stops entirely
(no per-frame readback/encode server-side) and the client canvas is the
viewer, fully interactive; unsupported content is surfaced loudly since
there is no pixel safety net. This is the Stage-2 burn-in state —
dogfood real course scenes here.

The baked player shipped 2026-08-14: `--export` records the geometry
stream headlessly (`web/export.py`, the same viewer hooks, unpaced)
into `./media/SceneName_web/` — a self-contained static folder (player
page + renderers + gzipped stream, ~7x compression; the dogfood Demo
bakes to 1.7MB) for sharing: scrub/play per animation segment, no
Python anywhere. Known cost: delta granularity is per merged batch, so
an animating batch re-ships whole frames — fine for hold-heavy
lectures, ~video-sized for animation-dense scenes; per-submobject
deltas if it ever matters.

## WebGPU is the endgame renderer (decided 2026-08-14)

One canonical renderer everywhere. Sequencing: finish parity on WebGL2
first — the payload format, protocol, serializer, and fidelity harness
are backend-agnostic and survive — THEN stand up a WebGPU backend
beside WebGL2 against the same payload and tests, migrate, and make it
canonical. wgpu runs the same code in-browser and natively (wgpu-py),
so at that point the reference renderer and the browser renderer become
literally the same code, `--render` moves onto it, and the
geometry-shader pipeline (and eventually pyglet) retires: one renderer
everywhere, no dual maintenance. WebGPU also restores GPU-side adaptive
tessellation via compute shaders — the elegant replacement for the
fixed-strip instancing compromise. Chrome is the app; browser support
is a non-issue.

Built 2026-08-14 in three passes: `static/wgsl/` +
`web/wgpu_renderer.py` render the full parity ledger from the same
payload — 3D/depth/MSAA, triangulated fill, dots, images, surfaces,
textured surfaces, clip planes — via a lazy pipeline cache keyed
(name, sample_count). WebGPU-specific handling: clip-space depth remap
in emit_gl_position (GL [-w,w] → WebGPU [0,w]), per-pipeline blend and
depth state, one packed 176-byte uniform struct (keep UNIFORM_FIELDS
and struct Uniforms in sync), top-down readback, and in the browser a
blit pass to present, since the canvas swapchain format is
platform-preferred. `static/webgpu.js` is the navigator.gpu mirror of
wgpu_renderer.py — same specs, layouts, uniform packing, pass structure;
**keep wgpu_renderer.py, webgpu.js, and wgsl/ in sync**.
`tests/test_wgpu_port.py` runs six fidelity scenes: 2D/clip/dots
bit-perfect (max 1/255); image/3D/surfaces differ on ~0.04% of pixels
at silhouette edges (implementation-defined MSAA sample positions and
texture-filtering precision, Metal vs GL — legitimate cross-API
variance). The live viewer starts on WebGPU and falls back visibly to
Pixel when WebGPU is unavailable.

Retiring `gl.js` + `glsl/` once WebGPU is canonical was **confirmed
2026-08-18**, with the trigger unchanged: burn-in on real course
scenes. The retirement steps live in `TODO.md`.

The retirement implementation was prepared on `review/retire-webgl2`
2026-08-26, but remains merge-gated on the A-series WebGPU fidelity bugs.
Until those close, the restored three-way live control keeps WebGL2 as a
differential diagnostic: a defect shared by WebGL2 and WebGPU implicates the
serializer, while a WebGPU-only defect localizes to the WGSL port. Once the
gate closes, the live product has one client renderer (WebGPU), Pixel remains
its complete-frame fallback, and the WebGL2 browser backend, shader tree,
desktop mirror, and dedicated fidelity module leave together. Backend-neutral
payload and z-order assertions move into the WebGPU suite rather than being
discarded with that harness.

The baked geometry player follows the same retirement: `--export` is
WebGPU-only and displays a clear unsupported-browser message rather than
shipping WebGL2 solely as an export fallback. This is acceptable because the
MP4 student bundle (`--export-present`) is the primary distribution artifact
and needs no GPU renderer; retaining an export-only backend would preserve the
maintenance burden after removing it from the live product.

Geometry exports are explicitly versioned from this retirement onward.
`GEOMETRY_FORMAT_VERSION` is written into both the binary geometry headers
and `scene.json`; the standalone player refuses a different or missing
version with a "Re-export this scene" message before it downloads or renders
the frame stream. Future resource/chunk formats increment that constant
rather than letting an old export fail as malformed GPU input.

## Stage 3 — the app (2026-08-14 onward)

`maniml app [dir]` (`web/app.py`, since split — see 2026-08-18 below):
a persistent local server; opening a scene spawns `maniml file.py Scene
--web` as its own subprocess (crash isolation — scene files are
arbitrary code; process reused for repeat opens; children terminated on
app exit). The viewer and landing shell were redesigned on 2026-08-16
in the shared Plass/Knuth visual language: warm graphite canvas, quiet
floating glass slugs, file-action and renderer flyovers, explicit
reverse/forward transport, a separate DOM pausepoint rail. The export
flyover saves the current frame or starts an isolated, one-at-a-time
video render / baked-web export, leaving the live scene and its
checkpoints intact.

The landing page became an Open action plus your recent files
(2026-08-18) — deliberately not a directory listing: the app is not a
file browser, and a listing of every scene class under a course tree
was noise in front of the one file you actually wanted. Opening no
longer auto-runs; a file opens at its first scene. The background
engine (`maniml agent`) is offered once, on first run — the only moment
worth asking — and `maniml app` hands off to an engine already on the
port rather than binding a second one, restarting an agent still
serving pre-upgrade code. The console panel shipped 2026-08-18:
toggle-only, never automatic, the only place a scene's output is
visible in app mode at all.

## Stage 3b — the hosted PWA: tried, then deleted (2026-08-17)

The frontend deployed to GitHub Pages and talked *across* origins to
the local engine. Everything that seam needed — a service worker and
manifest, a versioned wire handshake, URL-fragment pairing per daemon
session, an AppleScript launcher, a `maniml://` URL scheme, Launch
Services registration, Chrome PWA shim discovery, a public-origin
allowlist — cost roughly 1,400 lines and produced essentially every
delivery bug this project has had. "Collapse to a local, pip-only app"
removed all of it, along with the macOS desktop launch bridge built on
top of it (`install-desktop`, `maniml open FILE`, the `.py` Finder
association) and its public-release gates. The engine that runs the
scenes now serves the interface, from the same pip install, so they
cannot drift. **Do not reintroduce a public origin that talks to
loopback.**

Knuth (github.com/tayweid/knuth) spent 2026-08-17 arriving at the same
architecture from the same starting point, after a day of debugging its
own cross-origin pairing. Its inbound notes lived in
`SAME_ORIGIN_NOTES.md` (deleted 2026-08-18, absorbed here and in
`SECURITY.md`); two findings landed:

- **One port, not two.** The page was served on N and its socket lived
  on N+1, so "same-origin" was two origins bridged by an allowlist —
  paying for a port-pair search, a `?ws=` parameter, a `#control=`
  fragment, and a parent origin threaded into every scene subprocess.
  Both servers now answer plain GETs on their WebSocket port
  (`web/assets.py` via `process_request`), the client says
  `ws://${location.host}/`, and `connect-src 'self'` became a real
  restriction. The app's `/api/*` endpoints went with it.
- **No capability token.** It defended only against another program
  running as you, which can forge any header and can equally run
  `python` itself; keeping it meaningful meant delivering it out of
  band, which made launching a delivery problem and left a refused page
  needing a terminal to recover. The Origin check is now the whole
  boundary, and `http://localhost:8685/` is an address worth
  bookmarking. The attacker table is in `SECURITY.md`. The trap to
  remember: *embedding a token and keeping a token are different
  decisions* — doing the first without noticing turns the second into
  decoration.

Knuth's measurements that still matter here (Chrome 151, macOS 26):

- A PWA installed from a loopback origin **can** register OS file
  handlers, and a double-click delivers the file through `launchQueue`
  — even with the server stopped, since the service worker serves the
  shell and the file handle comes from the OS. This is what makes the
  `.py` double-click question in `TODO.md` answerable at all.
- `connect-src 'self'` **does** cover a WebSocket back to the same
  origin, verified on a non-default port.
- `open -a <App> <url>` cannot hand a URL to a Chromium PWA — the app
  shim silently discards it and loads the manifest `start_url`. Any
  future launcher that needs to deliver state through a URL will hit
  this.
- Do not let a client delete its own stored credential because one
  connection was refused; a refusal is not proof the credential is
  dead. (Moot while there is no credential; recorded because it was
  the single most expensive lesson.)

**The shape it settled into**, matching Knuth's first run:

1. `maniml.tayweid.io` is a preview (`site/`) — shows what this is,
   gives the install command, reaches nothing, cannot be installed.
   `site/sw.js` must keep existing as a kill switch: the pre-collapse
   hosted build registered a caching service worker, and a browser that
   has it keeps running it until a replacement at the same URL
   unregisters it. `site/app.html` redirects for the same reason.
2. `pip install` → `maniml app` starts the engine and opens
   `http://localhost:8685`.
3. The app offers **Install** for an icon and a tab-less window.
   Installing belongs to this origin alone, because only one installed
   app can own a `.py` and it should be the one with a Python process
   behind it. Scenes are relayed through the app's port rather than
   opened on their own, because the port is the installed app's
   identity — see `CLAUDE.md`.

## Removed: the IPython embed (2026-07)

ManimGL's embed mode (`scene_embed.py`, comment-keyed
`checkpoint_paste`) was removed — the checkpoint system is its
replacement. `self.embed()` remains as a stub that logs a warning. If a
live REPL is ever wanted again, build it on the arrow-key checkpoint
history rather than reviving the old module.

## The cleanup pass (2026-08-18)

After the 19-commit collapse arc, a systematic review (four scoped
subagent audits: dead code, docs-vs-code, test health, web-layer
structure) drove: deleting the transient-session path the desktop
bridge left behind; splitting `web/app.py` into `library.py` (file
knowledge) + `app.py` (the server) + `cli.py` (the command);
extracting `shell.css` after the two pages' "shared" palettes were
found drifting; retargeting CONTRIBUTING/SECURITY at the audience that
actually exists; and splitting the old TODO.md into this file and the
roadmap. `viewer.html` stays deliberately single-file: the transport
seam (wsUrl, send(), the message pump — verified still airtight) exists
so a future in-page engine can replace exactly those three things, and
the source-shape contract tests in `tests/test_static_assets.py` pin
its text. A shared websocket-bootstrap helper between `server.py` and
`app.py` was considered and deferred: real duplication, but the
abstraction only pays if that code is being touched anyway.

## Pausepoints are authored, not implied by play() (decided 2026-08-21)

Dogfooding surfaced the mismatch: a pause after every play makes live
presenting feel like clicking through bullets, and deriving
presentation structure from source structure (which plays live where —
helpers, loops) kept demanding smarter AST inference. The resolution
separates the two granularities the checkpoint had been serving at
once. A file that calls `self.pause()` (or CE's `next_section`)
anywhere becomes **pause-anchored**: pauses are the only checkpoint
savers and the only unit boundaries, plays between them run as one
stretch, and a pause works from a helper or a loop body because it
saves at call time — no call-graph inference needed. Files with no
pauses keep the per-play anchoring, which is what lets an unmodified CE
file be opened and stepped; that legacy path is one clearly-marked
branch, kept for CE compatibility and deletable later if the superset
argument wins. History note: the pre-repo prototype (preserved in the
early trees' `scene_backup.py`) checkpointed at *both* play and wait;
the 2025-07-14 rewrite cut wait when checkpoints grew namespaces.
Wait-as-pause stays rejected — `wait(0.5)` is rhythm inside a stretch,
not a hold. The `# %%` cell-marker idea in `TODO.md` is complementary,
not competing: cells would restructure *execution* units; `pause()`
decides where playback *holds*, and reaches the loop bodies and
helpers that comments cannot.

## Live sound is the system player; browser audio is deferred (decided 2026-08-22)

Audio arrived in two halves. The render half was inherited working:
`add_sound()` mixes pydub segments on the file writer's timeline (per-sound
gain, timestamp overlay) and ffmpeg muxes them into the mp4; pydub and
audioop-lts are packaged dependencies. The live half was a stub —
`utils/sounds.py`'s `play_sound()` (afplay/SoundPlayer/aplay) existed with
no call site, and the viewer had no audio at all.

**Tier 1 (shipped):** `add_sound()` now also plays the file immediately
through the system player whenever there is a live audience — a pyglet
window, or a web viewer with a client attached. The correctness of this
rests on the delivery decision above: *the viewer is loopback-only, so the
engine and the browser always share a machine*, and engine-side audio is
indistinguishable from browser audio to the person sitting there. The
`skip_animations` guard keeps fast-forwards (present prep, watcher
replays) silent; real-speed replays — `pause(loop=True)` laps included —
re-trigger the sound, which is the honest semantic. `time_offset` and
`gain` shape only the rendered mix; live playback is immediate and at
file volume. Render and headless runs have no window and stay silent;
export's `GeometryRecorder` stands in as `_web_viewer` without
`has_clients`, so it stays silent too — the audience predicate needs no
mode flags.

**Tier 2 (deferred, design recorded so it need not be rediscovered):**
browser-native audio, needed only when one of two things becomes real —
remote viewing (engine and speaker no longer share a machine) or sound in
the *baked player*, which has no engine at all and for which Tier 2 is
the only possible mechanism. The shape, respecting existing invariants:

- a `{"type": "sound", ...}` protocol message from `WebViewer`, kept
  inside the transport seam (`wsUrl`, `send()`, the message pump) so a
  future in-page Pyodide engine inherits it;
- the audio file served over the same one-port origin, confined by
  `security.py`'s scene-root machinery — no second origin, per the
  delivery rule;
- client-side `new Audio(url).play()` plus a mute control in the bar;
  browsers require a prior user gesture, so a sound fired before first
  interaction is swallowed — acceptable in the live viewer, but the baked
  player would need a start gesture anyway;
- the baked player additionally needs the sound files copied into the
  export folder and timeline-synced playback in `player.js`.

## Pausepoints are marks on play-checkpoints, not the checkpoints themselves (decided 2026-08-23)

One day of dogfooding overturned the previous entry's core mechanism
while keeping its purpose. Pause-only checkpointing quietly deleted the thing
that made LEFT feel like true reversal: with a checkpoint at every play,
a backward step crossed one small delta and the name-paired morph
retraced it faithfully; with checkpoints only at pauses, LEFT crossed a
whole stretch whose target predates everything built inside it, so
nothing paired and the scene crossfaded wholesale (first seen on
0_Welcome's unemployment timeseries).

Alternatives considered and rejected: state-only "breadcrumbs" stored
per play (memory lifecycle for something derivable); re-deriving
breadcrumbs at LEFT-time by fast-forward re-execution (rejected as
architecture smell — navigation shouldn't re-run code); recording the
render/geometry stream and playing it backward (correct and additive —
converges the live viewer with the baked player — but it is a *playback
layer* on top of the computation layer, not a substitute; deliberately
deferred, see the shape in the discussion of segment caches).

So the resolution is the simple hybrid: **every play saves a full
checkpoint again, exactly as before pause() existed; pause() saves one
more, flagged `stop`.** What pause() buys is purely the authored rest:
RIGHT runs play-to-play until the next flag, LEFT morphs back hop by
hop to the previous one (the pause-hop lands instantly — its checkpoint
duplicates the play before it), UP/DOWN keep per-play fine navigation,
and pause(loop=True) laps the stretch from the previous flag. Memory
returns to pre-pause levels, which a day of use had already shown was
acceptable — and cheaper navigation was never worth the reverse.
The rail keeps its wire protocol: the viewer maps each checkpoint to
its pausepoint chip server-side (`_chip_unit`), so interior play
checkpoints collapse into the pause chip and the client is untouched.

## Backward navigation is a jump (decided 2026-08-23, ~3am)

The reverse *morph* is gone. It was never a true reversal — from the
first prototype on, LEFT was a name-paired whole-scene morph between two
stored states, and states are photographs: nothing in them says how a
line was drawn, so a Create could only ever fade, and one night of
pausepoint dogfooding surfaced three separate failure modes (whole-
stretch crossfades, updater fights, trackers unpaired because they join
the scene only when first animated). Each was fixable — the last fix
proved a frame-exact tracker rewind — but the mechanism misleads
precisely when reverse matters most, and a presenter has to be able to
trust the key.

So LEFT now jumps: instant restore of the previous pausepoint's exact
state, the same trusted path UP/DOWN use. What was deleted:
`_play_reverse_to` (pairing, updater discipline, the ValueTracker
special case) and `_reverse_run_time` with its constants. What stays:
per-play checkpoints, `run_time` recorded on each (the playback layer
needs the spans), and the protocol's `back` field (a reverse *playback*
will light the rail the same way).

True reversal is a playback problem, not a state problem: it arrives
with the recorded render-stream layer (TODO.md, "Recorded playback"),
which replays what the GPU was actually sent, in reverse — exact for
any content, no heuristics. Until then the honest options were a jump
or a sometimes-beautiful, sometimes-lying morph; the jump won.

## The presentation cache is the mp4 (decided 2026-08-22)

The plan was to present from the baked geometry stream; a byte-level audit
killed it. Episode0 (~4 min) baked to 772 MB: the whole 2D scene merges
into one delta batch (`_MERGE_KEYS` carries no per-mobject identity), so
any motion re-ships every visible vertex; 99.5% of shipped bytes repeat
between consecutive frames but gzip's 32 KB window cannot see across
150-800 KB frames (measured: zstd 327x, XOR-delta+gzip 35x, shipped gzip
7.2x); 52 of 68 bytes per vertex are replicated constants; a 1.5x index
expansion on top. The best dependency-free re-format lands near 20 MB.
**The H.264 mp4 of the same scene is 7.7 MB.** A codec team has spent
twenty years on temporal compression; presenting is exactly its use case.

So Present runs off the video. The model is Taylor's own t1-web
(`t1-web/js/Present.js`): a <video>, an array of pausepoint timestamps,
and stepped scrubbing toward a target time — which plays **both
directions** with one file, no reversed encode. maniml generates the
inputs that t1-web hand-marked: every checkpoint already stores its
timestamp (`SceneState.time`), pause() supplies stop/loop flags and
names, and `chip_unit_for` (extracted to source_map.py) keeps the
presenter's rail identical to the live one. `--render` now always writes
`media/<Scene>_present/` — scene.mp4 (encoded with `-g fps`, a keyframe
per second, so every scrub seek lands instantly), present.json for the
viewer, present_meta.js + index.html + presentation.js for a standalone
page that opens from disk (fetch() does not exist under file://, which is
why the meta ships as a script — the same reason t1-web used a .js data
file). The viewer's Present button enters playback on the bundle, tells
the engine to send nothing ({"type":"mode", geometry:false, pixels:false}),
and shows a "stale" badge with one-click re-render when the source hash
no longer matches; a missing bundle renders first. Reverse is finally
honest: LEFT scrubs the recording backward, exactly.

The geometry-stream export stays for what only it can do — vector-crisp
zoom, the WebGPU endgame, Pyodide — and its size problem stays documented
in TODO.md with the audit numbers; revisit after the performance track's
per-submobject chunking changes the math.

**Follow-up (2026-08-26): the standalone page returns, as a different
artifact.** The 2026-08-22 slimming deleted `present.html` because the
*presentation cache* — what the viewer's Present button plays — needed
no page: mp4 + pausepoints.json, the no-engine fallback being the mp4 in
any video player. That decision stands. What returned is a *student
bundle*, `--export-present` → `media/<Scene>_present/` (index.html +
presentation.js + present_meta.js + scene.mp4): a self-contained folder
a course site hosts so students can click through an episode's
pausepoints with no engine anywhere — the replacement-for-slides use
case, where "the mp4 in any video player" loses exactly the thing that
matters (parking on beats, honest backward). It is opt-in, never written
by plain `--render`, and the cache the viewer plays is unchanged. The
table ships as `present_meta.js` because the page must open from
file://, where fetch() does not exist. Episode-sized reality check: all
of EpisodeA1 is a 4.3 MB folder.

**Follow-up (2026-08-26): recorded playback starts only after live endpoint
prebuild.** The viewer used to enter the movie immediately, even when the live
engine had built only a prefix of the movie's checkpoints. Exiting playback at
a later point could therefore fail to park the engine at the visible endpoint.
Present now has an explicit readiness handshake: prebuild every live endpoint,
rewind, advertise `presentation_ready`, require a fresh recording with the
same checkpoint count, then let the movie own motion. Exiting first restores
the corresponding live checkpoint and then leaves present mode. `--present`
uses the same path. A missing or stale movie is rendered only after the user
explicitly enters Present; ordinary live WebGPU still writes no media.

## Family draw order is CE's (decided 2026-09-02)

The symptom, reported from course production as "VGroup children render
in reverse order": a fill-only Dot placed last in a VGroup still drew
under an earlier DashedLine's dashes, and no reordering of children
changed anything. The A3 episode grew a workaround culture around it —
"bring_to_front the dots; z_index alone isn't honored across plays".

The diagnosis was not reversal. Same-kind children always drew in
order; the inversion was the batch pass sequence. The renderer merges
same-state family members into one batch, and a batch draws ALL its
fills before ANY of its strokes (the winding-number fill accumulates in
the float texture and composites once — that part is load-bearing, not
an optimization). So within a batch, any stroke beat any fill, whatever
the family order said. CE paints each member completely, in family
order, with the family stably sorted by z_index first.

Decision: match CE, and keep the batching. `assemble_draw_batches`
(utils/family_ops.py) is now the one place that turns a render group's
family into draw batches, used by both the native flatten
(Mobject.get_shader_wrapper_list) and the web serializer
(web/geometry.py) so the pipelines cannot disagree (pixel-diffed in
tests/test_wgpu_port.py). It stably sorts by z_index, merges same-key
neighbors, and starts a new batch when a member's early-pass content
(fill; stroke when stroke_behind) overlaps late-pass content already in
the batch — the only case where merging inverts CE's paint order. The
overlap test is a stroke-padded bounding box per late-pass member (not
a running union, which reads a wrapped grid row as covering everything
and splits members that overlap nothing painted), so text glyphs, bar
charts, and dense grids still merge into one draw: 500 packed
filled+stroked squares stay one batch, ~6ms to rebatch against ~2.5ms
before. A child's z_index change dirties the render caches up the
parent chain and takes effect next frame.

Not done, documented in TODO.md's quality tier: CE sorts one flattened
scene-wide list, so a high-z child of one top-level group cannot draw
over a later top-level group here. The 3D path is untouched — depth
test resolves occlusion per pixel, so batches there never split.

The course workarounds survive unchanged but are now mostly redundant:
z_index on a marker dot inside its VGroup is honored, so the
"first-child-on-top" child ordering (which never actually did anything)
and most of the bring_to_front calls can go when those files are next
touched.

**Follow-up (same day): the split has to trust bounding boxes, and
interpolate was poisoning them.** After the fix above, the A3 markers
still drew dashes-over-dot in the live viewer — but only after a play;
a plain add() rendered correctly. The cause was
`Mobject.interpolate`, which lerped the endpoints' RAW `bounding_box`
cache arrays: an animation-endpoint copy that never computed its box
still holds init-time zeros (with its dirty flag set), and lerping
that writes an origin box into the live mobject while the live flag
stays clean — real points, poisoned cache. The hazard split then saw
every dash "at the origin" and stopped splitting. Fixed by
interpolating `get_bounding_box()` (computes-if-dirty; the endpoints
are static, so it computes once per animation and caches). The
poisoning predates the draw-order work — click-to-inspect hit-testing
reads the same boxes — but rendering never consulted bounding boxes
until the hazard split did. Regression-tested in
tests/test_wgpu_port.py::FamilyDrawOrder.test_family_draw_order_survives_animation.

## One renderer: the beeline (decided 2026-09-02)

Taylor's call after the 2026-09-02 status review: everything goes
except native GL, which stays until after pyglet, with a pause before
it is removed. Concretely:

- **WebGL2 is retired** (`review/retire-webgl2`, merged 2026-09-02):
  `gl.js`, `glsl/`, the GL half of the reference renderer and the
  WebGL2 fidelity module are gone (-1,600 lines). The geometry player
  is WebGPU-only with an unsupported-browser message; exports carry a
  versioned format header. The burn-in hold was lifted because the
  z-order bug the WebGL2 comparator was kept to triage is fixed, and
  remaining triage compares against native render frames or CE.
- **CE is the arbiter.** When native GL and WebGPU disagree, the
  reference is what manim CE draws (the `manimce/` clone and the
  conformance suite), not the native pipeline. The draw-order bug was
  wrong in native GL too; "match native" would have enshrined it.
- **The Pixel stream goes next, then pyglet, then a pause, then
  `--render` on wgpu-py and native GL deleted.** Sequence and reasons
  in TODO.md's milestone section. The pyglet window is the last live
  consumer of the native pipeline; once it is gone native GL serves
  only headless `--render`, which is the one place a wrong-but-stable
  renderer costs least while the wgpu render is built beside it.
- **The shadow-mode gate is closed.** The 2026-08-26 gate review
  (PERFORMANCE_GATE_REPORT and the PROBLEM / ARCHITECTURE / MIGRATION
  proposals, then in the workspace root) approved two background
  investigations — a structural-sharing revision store with stable
  semantic identity, and bounded per-resource geometry chunks for
  large scenes — conditioned on beating a keyframe + skip-replay
  comparator and never taking priority over the WebGPU strip. Its
  measured evidence stands and is summarised here so the documents
  can go: on the course scene (`dogfood/03_Code.py`), solo WebGPU
  after the stabilisation layer reached 64.5 ms input-to-first-motion
  and 62 ms p50 retained-history endpoints against 79/86 ms on Pixel,
  with 238 of 240 native captures bypassed; checkpoint save/restore
  copies were 22/37 ms p50 and the visible navigation-boundary cost;
  a one-object change in a 2,000-square scene still shipped the whole
  merged batch (130 ms p50 to endpoint). Those large-scene numbers are
  real, but no course scene is near them; the decision is to finish
  the one-renderer strip first and re-open scale work only when a
  real scene demands it. The Phase-1 code (`revisions.py`, mobject
  hooks, the shadow Present work) is preserved as tag
  `archive/perf-systematic-viewer`; the priority-decision branch as
  `archive/performance-priority-decision`.

## Recorded video is tagged BT.709 (fixed 2026-09-02)

Taylor's one remaining fidelity report was "the background grey is a
slightly different grey between the web viewer and the rendered
video". Measured in the app's Chromium by drawing the decoded `<video>`
to a canvas beside a CSS swatch: the grey itself matched (26,26,26),
but a maniml BLUE square that is (89,197,223) live decoded as
(80,188,225) — the movie pipe wrote untagged yuv420p, swscale converted
RGB->YUV with its BT.601 default, and browsers decode untagged HD as
BT.709. The pipe now converts with `scale=out_color_matrix=bt709` and
tags the stream (`-colorspace/-color_primaries/-color_trc bt709`,
`-color_range tv`); the square decodes as (90,197,222). The always-on
`eq=saturation=1:gamma=1` filter was also dropped unless asked for: eq
works in YUV, so with RGBA input ffmpeg inserted an extra RGB->YUV pass
whose rounding tinted the grey to (24,26,26). Regression test:
`tests/test_external_processes.py::test_movie_pipe_tags_bt709`.

## The full-suite fidelity flake was a uniform mirror keyed by id() (fixed 2026-09-02)

For about a week the full `unittest discover` run failed one or two
native-vs-wgpu fidelity cases per run — a different case each time,
never in isolation, never with any single other module paired in, and
never in a six-iteration repeat inside one process. Dumping the failing
frames (`MANIML_FIDELITY_DUMP`) showed the NATIVE side was the wrong
one: a z_index case's native frame had lost its dot.

`set_program_uniform` skips a GL write when its mirror says the value
is already set, and the mirror lived in a module dict keyed by
`id(program)`. `get_shader_program` is an `lru_cache` of 128 entries,
so once a run has created enough scenes, programs are evicted and
freed, a new program lands on a freed address, inherits the stale
mirror, and silently skips its first uniform writes. Nothing short of
the whole suite allocates enough programs to reach eviction, which is
why every bisection came back clean. The mirror now lives in the
program's own `extra` slot and dies with it;
`tests/test_shader_uniforms.py` fails unfixed at the second iteration.
The same defect would have hit a long live session in the native
window, which is one more reason the native pipeline is on its way out.

## The browser is the only live viewer (decided 2026-09-02)

Milestone step 1 of the one-renderer beeline: the Pixel stream is
deleted. Until now `--web` kept two pictures — the browser's WebGPU
render of the geometry stream and, behind it, JPEG/PNG frames of the
native GL framebuffer streamed as a fallback and a comparison ("split")
— with a renderer switcher in the bar, a `renderer_fallback` protocol
that flipped a client back to Pixel when a scene held content the
serializer could not express, and a per-frame support preflight that
decided whether native capture could be skipped.

All of that is gone. The client reports `{"type": "mode", "geometry":
true}` once its WebGPU is up; from then on every frame is a geometry
payload and `Scene.update_frame` skips `camera.capture` outright. A
browser without WebGPU gets a notice on the stage (state and console
still flow, so the engine is not lost). Content the serializer cannot
express is declared in the payload's `unsupported` header, left out of
the picture, and named in the bar — there is no native frame behind it
to fall back to, and pretending otherwise is what the split view was
for. `--render`, `--export-checkpoints`, and the pyglet window still
use native GL; they are the next steps.

Why now rather than after pyglet: the stream was the only consumer of
the JPEG encoder, the readback, the `droppable` frame queue in the
server, and the updater-inference streaming costs that the performance
audit measured (20–60 ms per encode, most of a core on a parked scene
with updaters). Deleting it removes those costs rather than optimising
them, and it removes the last reason the viewer had to know whether the
native pipeline agreed with the browser.

## The pyglet window is retired (decided 2026-09-02)

Milestone step 2 of the one-renderer beeline. The browser viewer is
now the default and only live surface: `maniml scene.py Scene` opens
the browser (`--web` is accepted and means the same), and the pyglet
window, `rendering/window.py`, the `pyglet` and `moderngl-window`
dependencies, the window section of the config, and the `-f` full
screen flag are gone. `Scene.window` keeps its name because
`WebViewer` implements the interface the scene loop was built around;
the camera is always a standalone GL context now, which deleted the
window framebuffer, the letterboxed blit, and the `use_window_fbo`
toggling around offline capture.

The `--present` timeline overlay — rings drawn as scene mobjects near
the bottom edge, revealed by the mouse — went with it. It existed for
the window; the browser has had its own rail since 2026-08-16, in
live and Present alike, so the overlay was a second scrubber with its
own checkpoint-ignore plumbing (`get_state`/`restore_state` had to
exclude and re-attach it) and its own crowding bug past ~50
checkpoints. Both are deleted rather than fixed. In present mode a
click on the stage no longer grabs anything: navigation is the rail.

The key and mouse constants in `event_constants.py` are maniml's own.
Their values are still the ones pyglet delivered, so scene code and
`mobject/interactive.py` compare against the same numbers; nothing
imports pyglet, and `tests/test_headless_import.py` asserts that a
star import touches neither pyglet nor moderngl-window.

The windowed scenario suite (`tests/interactive/`, opt-in through
`MANIML_WINDOW_TESTS`) is deleted. Its ghost-mobject regression is
ported to `tests/test_checkpoint_reload.py::TestGhostMobjects`, driven
headlessly the way the rest of that file drives a scene; dev-mode
navigation and present-mode prebuild are covered by the headless
checkpoint and mode tests and by the end-to-end web viewer suite; the
3D depth/MSAA scenario is covered by the wgpu fidelity cases. The
MSAA letterbox blit it also checked no longer exists.

## The roadmap is pruned to the pause, the held step, and the instruction stream (2026-09-04)

`TODO.md` had grown into a record of every idea since August, most of
it written before the one-renderer strip and the instruction-stream
design (`../simlab/ARCHITECTURE.md`, 2026-09-03). On 2026-09-04 it was
cut to what is actually planned. Nothing removed was implemented —
this entry exists so that no one reads the removal as "done":

- **Superseded by the instruction stream** and removed: the
  `PERFORMANCE.md` delivery order (revision store, copy-on-write /
  delta checkpoints, bounded geometry chunks, transform deltas,
  keyframed exports — the engine core in the plan is all of these at
  once), the geometry-stream recorded-playback layer (the clock running
  backward over immutable buffers is the same thing), the parked-scene
  streaming rewrite and the "should idle frames be client-rendered"
  question (the GPU clock owns updaters), and the end-to-end
  presentation clock (the plan's clock). `PERFORMANCE.md` stays as the
  measurement record; its "Proposed delivery order" is no longer the
  plan.
- **Closed by deletion**: the 2026-08-18 duplicate-mobject bug entry.
  Its suspect, the display-only reverse morph, was deleted on
  2026-08-23, and the headless ghost regression that drives the same
  back-and-forward path passes. If it is seen again it is a new bug.
- **No longer planned**: promoting the installed-app measurement
  scratch harnesses (the files are not in the repo and the throttle
  they measured is fixed), checkpoint byte accounting on the current
  engine, `.py` double-click and the PWA install confirmation, process
  controls and multi-scene tabs on the landing page, splitting the
  fragile static-asset pins into their own file.
- **Kept, compactly**: the small fidelity gaps (cross-group z_index, 3D
  gradient fills, re-triangulation, MathTex join drift,
  `AddTextWordByWord`), the 2026-08-18 test debt (verified still
  untested), and two design questions that are not scheduled: cell
  markers (the one item that fixes whole-unit stepping and the blank
  opening frame) and the Typst text backend. Dropped from that list
  the same day, on Taylor's call: the function-rebinding redesign
  (the instruction stream removes copy-on-execute, so it lands
  there), the student-bundle notes track (authoring cost; re-add when
  a course page needs it), and the baked geometry player's restyle
  and site demo (no user; the mp4 bundle is the distribution format).
  The preamble split is not listed separately because it is the
  half-measure of cell markers, and 2x supersampling is one clause of
  the held wgpu-py render step.

Native GL removal (beeline step 4) is explicitly **held** by Taylor as
of the same day: it stays the next structural step and the
instruction-stream plan's prerequisite, but it waits for the dogfood
pause to produce confidence.

## Checkpoints are a ledger (2026-09-05)

The stall at every play boundary — TODO "Now" item 1, the thing dogfood
kept reporting — was the checkpoint copy, and on a real course episode
it was an order of magnitude worse than the August audit had measured
on the benchmark scene: 192 ms at the median and 2.9 s at worst for
the save after each play on EpisodeA3, plus the same again for the
thaw before each unit. Three measurements decided the shape of the
fix, all recorded in `docs_checkpoint_ledger_plan.md`:

- `copy.deepcopy` costs about 27 µs per mobject and nothing per byte
  (a 13 MB circle in 0.4 ms, a thousand squares in 27 ms). The cost is
  the traversal, so the only fix is to not visit unchanged mobjects.
- The namespace keeps every mobject ever made — 31 to 122 variables
  over the episode, all off screen by the end — and every one was
  copied at every play. Two thirds of the objects visited were the
  svgelements path caches every Tex glyph keeps from construction.
- Every unit paid twice: the thaw before exec, the save after.

What shipped, in order of payoff:

1. **Glyphs share their parsed svg path across copies**
   (`Mobject.__deepcopy__` with a per-class `_copy_by_reference`;
   `VMobjectFromSVGPath` names `path_obj`). Four-fold on its own.
2. **The ledger.** `Mobject.revision` is bumped by every mutation a
   checkpoint must see: the existing `note_changed_data` and
   `note_changed_family` choke points (both recurse up the parents,
   so a child change bumps every ancestor) and a new
   `note_changed_state` for uniforms, updaters, locks, targets, the
   `z_index` setter, tracker values, camera orientation. A save
   pre-seeds the deep copy's memo so a mobject whose revision is
   unchanged — and whose submobjects and referenced mobjects
   (`target`, `saved_state`, a `SurroundingRectangle.mobject`, any
   attribute holding one) are unchanged too — hands back the frozen
   copy it got last time. A mobject with updaters is never shared:
   its closures hold mobjects the walk cannot see. The per-play cost
   becomes what moved; history holds objects + changes instead of
   objects × checkpoints.
3. **Frozen graphs carry no parent links and read-only arrays.**
   Parent links would reach every dead group that ever held a
   mobject (the course's `VGroup(*scene.mobjects)` stage grabs), and a
   copy shared between checkpoints could not point at each one's
   parent. A thaw rebuilds the links from the submobject side. The
   read-only flag turns "someone mutated history" into an immediate
   error; the two paths that used to put a stored checkpoint's state
   on screen directly (edit re-anchor, exec-error rollback) go through
   a thaw now.
4. **No thaw at the frontier.** After a save, the live scene and
   namespace are exactly what the checkpoint was frozen from, and the
   checkpoint holds its own copies; the next unit runs against the
   live graph. Any restore clears that, so navigation still thaws.

Why the August revision store failed and this does not: it tried to
*detect* change after the fact (partial hooks, blake2b hashes of the
arrays, derived columns excluded by name) and every miss was silent.
Here the signal is an integer per mobject at the sites that already
mark data as changed, derived columns never pass those sites so they
cannot false-positive, and a miss is loud: `MANIML_VERIFY_LEDGER=1`
compares every reuse against the live object and raises naming the
attribute. The whole suite runs clean under it, and its first run on
the real episode caught one real miss — a `Table` keeps `mob_table`, a
list of lists of its entries, and the reference walk only looked one
container deep, so an entry that changed after leaving the table's
family would have left a stale table in history; the walk now follows
nested containers. Two writes it cannot see are recorded as such: a plain attribute reassigned to a different
mobject (an added or removed attribute is caught by an attribute
count on the entry), and a numpy view taken before a freeze — the
optional live-array freeze in the plan's Phase 4 would close the
second if dogfood ever finds it.

Measured on the same EpisodeA3 render, checkpoint copy per play:

| Run | Save p50 | Save max | Thaw p50 | Copy time over the episode |
| --- | ---: | ---: | ---: | ---: |
| Before | 192 ms | 2,898 ms | 188 ms | 64.5 s |
| Shared svg path | 46 ms | 1,010 ms | 48 ms | 18.6 s |
| + the ledger | 9 ms | 135 ms | 80 ms | 12.5 s |
| + no thaw at the frontier | 10 ms | 111 ms | skipped (92 of 93 units) | 1.3 s |

The thaw got slower under the ledger alone (each thaw enters a whole
new live generation in the ledger) and then vanished from forward
stepping. What is left is the save at 10 ms median, which is the
mobjects that actually moved in each play, and one thaw per
navigation.

Explicitly not done, on purpose: copy-on-write on the live objects
(the instruction-stream architecture makes checkpoints free by
construction), and reuse on thaw for backward navigation (the same
trick reversed; queued in the plan as Phase 2b's remainder).

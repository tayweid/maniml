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

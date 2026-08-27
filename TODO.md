# TODO

The forward roadmap. What was decided, shipped, or tried-and-deleted —
and why — lives in `DECISIONS.md`; the architecture as it stands lives
in `CLAUDE.md`. The large-scene performance audit, measurements, and
implementation order live in `PERFORMANCE.md`.

## The milestone: WebGPU as the one canonical renderer

Decided 2026-08-14; sequencing updated by reviewer decision 2026-08-26. The wgpu backend
already covers the full parity ledger in both the browser
(`static/webgpu.js` + `static/wgsl/`) and natively
(`web/wgpu_renderer.py`), the live viewer starts on WebGPU with a
visible Pixel fallback, and the fidelity suite passes. What remains is
sequence, each step gated on the one before it:

1. **Land and burn in the contained stabilization layer in A2 solo
   WebGPU.** Fidelity reports are foreground work: z-index ordering,
   axis labels, color, text/image, and 3D differences preempt the
   background performance architecture.
2. **Land the supported native-capture bypass.** The profiler and
   bounded-input reviews may land alongside it, but solo WebGPU is the
   daily path and gets wall-clock priority.
3. **Retire `gl.js` + `glsl/`** (and the WebGL2 half of
   `reference_renderer.py` / `tests/test_gl_port.py`). Decided; only
   the active A2 burn-in holds it.
4. **Move default `--render` onto wgpu-py and add 2× supersampling.**
   Browser and offline output then share the WebGPU renderer contract.
   Keep the current native GL renderer permanently behind
   `--renderer=native` as the independent pixel-diff and final-render
   reference; it is not a deprecation stub.
5. **Retire the pyglet window** (`rendering/window.py`), not the native
   renderer. Inline the key/mouse constants `viewer.py` imports and
   move the `--present` timeline from the GL overlay to DOM, deleting
   the checkpoint-ignore/reattachment plumbing.
6. After the transition: Windows/Linux CI matrices and cross-platform
   packaging return (scoped out during the macOS developer preview).

## Performance: near-term work and the large-scene gate

The installed small-scene path is healthy after the launchd, relay,
client-queue, and short-animation fixes: the installed app measured
33.5 ms median / 45.5 ms p95 frame spacing with no observed bunching or
queue backup. Do **not** begin a wholesale renderer rewrite merely to
improve that path. The measurements, evidence, correctness constraints,
and full implementation sequence live in `PERFORMANCE.md`.

**Start Gate S decision, 2026-08-26:** approved with conditions because large
agent-based simulation scenes are a real target. Stable semantic identity plus
structural-sharing history, and bounded renderer resources/chunks, may continue
in shadow mode at background pace. They never take wall-clock priority over
the WebGPU strip above. Before either becomes authoritative, the repeat gate
must prove endpoint/image parity, acceptable shadow overhead, and measured
speedup. Structural-sharing history must also beat a keyframe + skip-replay
prototype at equal correctness: keep every configurable Nth full checkpoint,
evict interior snapshots under a byte budget, and reconstruct an evicted
endpoint with `temp_skip` from the nearest retained keyframe.

Phase 5 video-first Present motion is approved independently and belongs on
its own review branch. Legacy checkpoints and geometry delivery remain
authoritative until their separate repeat gates pass.

Contained/background backlog, in dependency order when it does not compete
with the foreground WebGPU strip:

1. **Preserve the installed-app measurement path.** Promote the working
   scratch harnesses (`relaycheck.mjs`, `ab.mjs`, `appshot.mjs`,
   `timeline.py`, `refmp4.py`) into maintained tooling and add a regression
   assertion for `ProcessType=Interactive`. Keep process origin
   (shell/launchd) independent from network route (direct/relay); a
   hand-started process was structurally unable to reproduce the original
   throttle.
2. **Make render batches non-owning.** `assemble_render_groups()` currently
   creates normal semantic parents. Checkpoint/restore can copy those
   ephemeral parents, after which later mutations traverse and dirty stale
   groups. The synthetic audit grew one mobject from 1 to 31 parents over
   30 restores. Fix this before deeper checkpoint optimization and add a
   100-restore parent-count/mutation-cost regression.
3. **Fix the idle-loop pacing clocks after backward navigation.** The
   interact loop paces with `sleep(max(vt - rt, 0))` where `vt` derives
   from `scene.time` — and LEFT/UP/DOWN restore `scene.time` from the
   checkpoint, rewinding it behind the pacing clock, so the sleep term
   goes permanently negative and the loop free-spins until the next real
   play resets the clocks. Measured 2026-08-26 on a trivial 3-mobject
   scene: 24 passes/s at 15% CPU parked normally, 103 passes/s at 43%
   CPU parked after one backward jump (the "~105 fps" the streaming
   throttle comment guards against). Reset or clamp the clocks on
   checkpoint restore; when not playing, pace at `1/fps` outright.
   Small and self-contained — do this first.
4. **Stop rendering and encoding identical waits/idle frames.** The measured
   viewer encoded roughly twelve identical 1080p frames per static `wait()`.
   Pump events separately, retain clocks for real updaters, and send a hold
   duration/state change rather than repeatedly rendering a clean scene.
   Two further measured costs belong to this item (2026-08-26):
   - The idle loop runs `camera.capture` every pass with a client
     connected even when nothing changed — `update_frame`'s early-out
     only applies to `dt == 0` calls, and the interact loop always
     passes `1/fps`. A parked static scene renders at 30fps forever.
   - The streaming policy treats "any mobject has updaters" as
     animating, so a scene parked with `always_redraw`/label updaters
     (most course scenes) JPEG-encodes visually identical 1080p frames
     at up to 45fps indefinitely — measured 20–60 ms per encode, most
     of a core by itself. Replace the updater inference with a real
     did-the-picture-change test, or freeze streaming when parked and
     tracker values are unchanged. Also note every state change forces
     a lossless PNG (~100–400 ms CPU at 1080p) — per-keypress latency
     on navigation. (Solo WebGL2/WebGPU already turns `_pixel_mode`
     off, so these costs are Pixel/split-mode only; the geometry
     stream is delta-cached and cheap.)
5. **Reduce checkpoint damage before redesigning checkpoints.** Add copy-time
   and byte accounting; exclude render-only/immutable/derived state; avoid
   retaining full history in modes that do not need navigation; and enforce a
   replay-backed budget. `_save_checkpoint()` already contributed about
   19 ms around the measured `play()`. Full copy-on-write/delta checkpoints
   remain a later architecture project.
6. **Fix `AddTextWordByWord` if course scenes use it.** This is a semantic
   bug, not transport pacing: it groups label/isolate spans rather than words,
   so ordinary text becomes one 0.2-second chunk before rendering. Add a
   dedicated word-group path without changing generic `build_groups()`, and
   cover the separate `MarkupText.isolate` forwarding bug. See the focused
   diagnosis and tests in `PERFORMANCE.md`.

Then take the contained next milestone:

- Skip native OpenGL capture when WebGPU is the sole renderer and the scene is
  fully supported.
- Batch scene-list mutations so a large `play(*animations)` rebuilds render
  groups once, not repeatedly.
- Put explicit byte limits and lifecycle cleanup on browser, texture, GL, and
  scene-process caches.
- Add stage timers/counters for update, animation setup, checkpointing,
  serialization, native capture, encoding, queue age, and browser presentation.
- Re-run the same installed-app fixtures and preserve image/state/navigation
  correctness alongside the timing result.

Before making shadow history or resources authoritative for genuinely large
scenes, pass the repeat gate from `PERFORMANCE.md`: stable resource/revision
IDs, bounded geometry chunks and dirty uploads, transform/uniform deltas,
checkpoint parity, accepted shadow overhead, measured speedup, and a win over
keyframe + skip-replay. This evidence is mandatory at that scale:
serializing an unchanged 5,000-object scene already took about 45 ms, and moving
one object resent the full 4.08 MB merged batch.

An end-to-end timestamped presentation clock belongs in that scale/robustness
phase, not at the front of the current queue. The shallow relay and rAF-aligned
client are behaving now, but they still present on arrival and cannot absorb
future OS/network jitter. Build the clock before remote or variable-latency
viewing becomes a product promise.

## Known bugs

- **BUG: navigation can leave two copies of a moved mobject on screen**
  (seen 2026-08-18). In `ECON_0100/F26/blocks/A0_The_Landscape/03_Code.py`,
  `Animation0`, the live viewer showed the `MICROECONOMICS` block
  letters twice — once at the pre-move position and once where
  `Squares.animate.to_edge(UP, buff=1)` puts them — after arrowing
  around and landing on the last pausepoint.

  Already ruled out, so nobody re-does it: **not the client renderers**
  (the viewer was on Pixel, i.e. the native GL render), **not the
  scene** (it adds one `Squares` and moves it), and **not a regression
  from the same-origin work** (that touched no code under `rendering/`,
  `mobject/`, `scene/`, `camera/`, `animation/`). A forward-only
  `--render` of the same scene on the same build is correct —
  checkpoint 032 shows one title — so it is reachable only through
  interactive navigation.

  Where to look: `_play_reverse_to` in `scene/interaction.py` pairs
  mobjects by variable name, Transforms matched pairs and fades
  unmatched ones, and is meant to be display-only
  (`_no_checkpoints()`); and `_restore_checkpoint_for_display` in
  `scene/checkpoints.py`. The suspicion is that a display-only morph
  leaves a mobject in `self.mobjects` that the next restore does not
  clear, so the restored copy joins it rather than replacing it.
  Reproduce headlessly the way `tests/test_web_viewer.py` drives the
  viewer: RIGHT to the end, LEFT/UP back a few, RIGHT forward again,
  then count top-level mobjects rather than eyeballing a frame.

- **Stepping forward runs a whole unit, not a whole pausepoint.** A
  unit ends at the statement containing a `play()`, so a `for` loop of
  plays is one unit: a single forward press fires all of them. Opening
  no longer auto-runs (2026-08-18), which removed the worst of it, and
  the rail no longer misrepresents it (2026-08-19): such a unit is drawn
  as a stack of chips rather than one, because `AnimationUnit` now
  reports `plays`/`loops` and the viewer sends `many` with each future
  unit. That is an honest label, not a fix — per-play stepping
  inside a loop would mean running a unit as something suspendable — a
  coroutine or a thread that parks at each `play()`. Related: a scene's
  `self.add(...)` preamble lives in the same unit as its first play, so
  a scene now opens on an empty frame. Rendering the preamble needs
  `source_map` to split a unit at its play statement, and checkpoint 0
  re-baked to match — doable, but it must not let the preamble run
  twice, or it reproduces the duplicate-mobject bug above. See
  "Cell-marked scene files" below for the version of this that stops
  being a bug rather than getting fixed.

- **Presentation timeline: window the scrubber for large scenes.** The
  bar packs all N rings into a fixed 60% span, so past ~50 checkpoints
  the rings crowd, and past ~78 they overlap and the connecting-line
  stubs invert (`_show_timeline` in `maniml/scene/presentation.py`).
  Plan: show every k-th ring plus the neighborhood around the current
  checkpoint, rather than all of them. (Simpler fallback if windowing
  proves fiddly: adaptive marker radius
  `r = min(0.055 * scale, 0.35 * spacing)`, dropping the connecting
  line when gaps get tiny.) Superseded entirely if the timeline moves
  to DOM (milestone step 4).

## App and viewer

- **`.py` double-click.** Blocked on a real problem, not effort:
  `launchQueue` delivers a browser file handle with no filesystem path,
  and the watcher and the scene's `__file__`-relative imports both need
  one. Knuth measured the machinery itself working from a loopback PWA
  (see `DECISIONS.md`). Options if it matters: resolve the handle's
  name against the app root and recents (ambiguous for duplicate
  basenames), or keep the native dialog as the only path in.
- **Confirm the install in a real browser.** Chrome's installability
  criteria and the offline shell have not been exercised here — Knuth
  got file handlers, `launchQueue`, and an offline shell all working
  from a loopback origin on Chrome 151/macOS 26.
- **A live demo on the preview.** `--export` already bakes a scene into
  a self-contained page that runs with no Python at all, which would
  let a visitor to `maniml.tayweid.io` actually scrub through a real
  scene instead of reading about one.
- **Bring the baked player into the visual language.**
  `static/player.html`/`player.js` predate the 2026-08-16 redesign and
  share no styling with the viewer. They deliberately do not link
  `shell.css` (an export must stay self-contained), so this is a
  restyle in place: warm graphite, glass slugs, the viewer's transport
  idiom. Now the only part of the frontend still off the shared
  language — the viewer and the landing page moved onto Plass's pod run
  on 2026-08-19, and the player's bottom bar is the same shape as the
  viewer's new presenter bar, so it is a copy job with the pod styles
  inlined.
- **Notes track for the student bundle** (not urgent; scoped
  2026-08-26). Per-pausepoint text beside the `--export-present`
  player, switching as students step — the lecture narration a course
  page can't get from a silent recording. The page work is small (a
  panel driven from `onRest`; the writer folds a notes file into
  `present_meta.js`, backward-compatibly — old bundles just have no
  `notes` field). The real design problem is KEYING: which beat a note
  belongs to. Indices silently shift whenever a `pause()` is added or
  removed mid-scene; names (`pause(name=...)`) are stable but must be
  authored for every beat before notes can attach. Decide the key
  before building anything — a likely shape is names for anchors plus
  index-order fill between them, with the export warning on notes it
  could not place. The authoring itself is lecture-prep work and the
  larger ongoing cost; the tooling should not pretend otherwise.
- Later: process controls on the landing page, multi-scene tabs.

## Test debt (from the 2026-08-18 review)

Coverage gaps around the newest features, in risk order:

1. `hand_off_to_a_running_engine` (`web/cli.py`) — the
   version-mismatch restart and reuse branches are untested.
2. `agent` subcommands beyond install/offer — `status`, `restart`,
   `uninstall`, `serve` have no tests against the mocked launchctl.
3. Relay failure paths (`web/app.py`) — a scene dying mid-relay, the
   upstream connect failing; only the happy path and unknown-id are
   covered.
4. The recents/choose control ops are tested at the Python level but
   never over the actual control WebSocket the landing page uses.
5. Log messages are tested through a standalone `--web` process but not
   through the app relay — the one place the console panel matters
   most.

Also noted: `tests/test_static_assets.py` mixes stable content
contracts with deliberately fragile source-shape pins (index-slicing,
call counts). Splitting the fragile half into its own file would make
the refactor risk visible in the file list. And the daemon-thread
websocket bootstrap is duplicated between `server.py` and `app.py`
(bind → serve → ready event → closing event); worth a shared helper
only when that code is being touched anyway.

## Quality tier (polish; none block course production)

- **Supersampled `--render` output (~1 hour).** macOS caps live-window
  MSAA at 4 samples, but offline rendering has no cap: render each
  frame at 2x and downscale before writing — effectively unlimited edge
  AA for published videos. The live-preview cap is then irrelevant.
- **3D fills flatten gradients.** `render_triangulated_fill` samples
  one flat fill color per family member; a gradient-filled shape in a
  ThreeDScene loses its gradient. Fix: carry per-vertex colors through
  the triangulation.
- **Re-triangulation cost for animated 3D fills.** Under depth test, a
  mobject whose points change re-runs earclip every frame. Fine for
  shapes; measurable when morphing large Text in 3D. Fix:
  transform-aware cache so rigid motions reuse the mesh.
- **z_index sorts top-level mobjects only.** CE also sorts within
  families; maniml preserves family draw order. Rarely matters — noted
  so it doesn't surprise.
- **Minor typography drift vs CE.** Multi-part `MathTex(...)` parts
  join with TeX's natural math spacing, slightly tighter than CE's
  joining. Cosmetic.

(LEFT-arrow reverse being an approximate morph rather than true
reversal is a design property, documented in CLAUDE.md's weak spots.)

## Cell-marked scene files (a format question, not a viewer one)

Raised 2026-08-19, from writing scenes rather than reading code: every
scene here is one `class X(Scene)` with one `construct()` and the whole
animation inside it, so what is the class doing? In CE it earns its
keep three ways — the body must not run at import (flags are read and
the camera and file writer are built before `construct()` is called),
the class name is how `manim file.py SceneName` addresses one render
out of a file, and subclassing is how `ThreeDScene` and friends swap
the environment underneath you. Only the third applies to a plain
`Scene`, where the class is a container for a single method and `self`
is a handle to the renderer.

**In maniml it is already vestigial.** The engine never calls
`construct()`. Checkpoint 0 is built from `vars(module)` — the module
namespace, not a method's locals (`_create_checkpoint_zero`,
`checkpoints.py`) — and each unit is `exec`'d flat against that
namespace with `self` planted as an ordinary variable, from source
`_unit_source` produced by taking the raw lines and wrapping them in
`if True:`. No class, no method, no frame. `_find_construct` exists to
see *through* the wrapper to the statements inside it.

So the interesting move is not "drop the class" but **`# %%` cell
markers**, which is Knuth's percent format — the two suites would share
one file format, and Plass's convergence argument for Typst applies
here for the same reason. What makes it worth more than tidiness:
**it dissolves the whole-unit stepping bug above rather than fixing
it.** Animation units stop being an AST heuristic that guesses
boundaries from where `.play()` appears and cannot see inside a `for`
loop; the author marks where each pausepoint is. The `many` stacked
chip on the rail becomes unnecessary, because the count stops being
unknowable. It also gives the preamble somewhere to live — its own
cell before the first play — which is the other half of that bug.

What blocks it, specifically:

- **A script-style file runs itself on import.** `load_scene_module`
  gets checkpoint 0 by importing the file; for a class-based file that
  merely defines a class, but a file whose animation is at module level
  would play the whole scene during the import. The fix is contained
  but real: exec only the preamble (up to the first play or the first
  cell marker) and hand the rest to the unit machinery.
- **CE compatibility is the spine.** Unmodified CE files working is
  what `_CEAliasFinder` and the conformance suite are for, so this can
  only ever be a *second* front door — never a replacement, and never a
  reason to make the class path second-class.
- **One file would be one scene**, which costs the viewer's scene
  picker and `library.py`'s AST scan. Unless a cell marker can also
  name a scene, in which case it does not — worth deciding early,
  because it changes the format.

Not now: course production is running on the checkpoint engine, which
is the riskiest code here. But this is a better milestone than the
per-play stepping item under "Known bugs", because it subsumes it.

## Typst text backend (independent of the viewer; do whenever)

Replace LaTeX/dvisvgm with Typst for Tex/MathTex: mitex accepts LaTeX
math syntax, so `MathTex(r"\frac{a}{b}")` keeps its API while Typst
renders → SVG → mobject paths. Kills the texlive install burden (the
single worst student-install pain), much faster text builds, same
engine as Plass (suite convergence), and a prerequisite for any future
in-browser authoring. Watch: Typst-rendered math will drift differently
from the CE typography drift already noted above — keep the conformance
eye on it.

## Open questions

- Frame pacing/backpressure in the pixel stream.
- Multi-client (presenter + audience views?).
- Baked-format size for long, animation-dense scenes (per-submobject
  deltas if it ever matters).
- Whether idle frames should be the client's own render or stay
  server-authoritative once WebGPU is canonical.
- Idle-loop updater scenes stream via a per-tick `has_updaters()` scan
  of top-level mobjects; nested-family-only updaters would be missed.

### Snapshots copy objects, not the functions that read them (fixed by a corrective pass; wants a real design)

The checkpoint snapshot deep-copies mobjects and trackers, but a function
written in a unit keeps reading the *originals*: its `__globals__` is the old
exec dict, and closures / default args / bound methods hold the old objects.
So `t = ValueTracker(); dot = always_redraw(lambda: ...t...)` then
`self.play(t.animate...)` in a later unit animated a copy the drawing never
read (Episode 0's unemployment scroll froze). The standard tracker idiom,
so it had to work.

What's in place (`checkpoints._rebind_functions`, 2026-08-22): after every
deepcopy, walk the functions reachable from the namespace and from copied
mobjects' updaters, and re-create each as code + new environment --
`__globals__` -> the new namespace (recognised by the `SCENE_NS_MARKER` key
planted at checkpoint zero), cells / defaults / `__self__` -> the copy in
the deepcopy memo. It chains across generations and is covered by
`TestTrackerAcrossUnits`. Known gaps: functions buried in arbitrary
containers aren't walked; a self-referential closure keeps the old function
in its own cell.

Why it's ugly: it is a *repair* of the copy, done after the fact, reaching
into function internals. It exists because execution happens on copies of
the world. Ideas for an elegant replacement, not pursued yet:
- execute forward on the live objects and keep copies only for looking back
  (rewind + continue = fast-forward replay from source; removes the
  copy-on-the-execution-path entirely, but makes rewind O(units) and re-rolls
  nondeterminism);
- make the snapshot itself identity-preserving (restore *into* the existing
  objects rather than replacing them), so references never go stale -- the
  same mapping problem, moved to restore;
- treat a function as a *pointer to source* and re-evaluate its definition in
  the new namespace (Taylor's instinct) -- covers globals cleanly; cells and
  defaults still need the memo.
Decide when `pause()`-anchored units have settled; the rebinding pass is
independent of where boundaries fall.

## Recorded playback

**Shipped 2026-08-22 as present-from-video** (see DECISIONS.md, "The
presentation cache is the mp4"): `--render` writes
`media/<Scene>_present/` — the mp4 plus the generated pausepoint table —
and the viewer's Present button plays it with stepped scrubbing both
directions (t1-web's model), the engine fully silent. True reverse in the
presenter is done. What remains below is the *geometry-stream* variant of
the same idea, kept for what only it can do (vector-crisp zoom, Pyodide,
navigation-as-playback in the live dev viewer) — but its export format
must first shrink: the 2026-08-22 audit measured Episode0 at 772 MB vs a
7.7 MB mp4 (one merged batch re-ships the scene on any motion; 99.5%
inter-frame redundancy invisible to gzip's 32 KB window — zstd measured
327x, XOR-delta+gzip 35x; 52/68 B/vertex replicated constants; 1.5x index
expansion; no keyframes, so seeks replay from frame 0; the player buffers
the stream twice). Revisit after the performance track's per-submobject
chunking changes that math.

The original sketch — **record what the
renderer is sent** and treat navigation over visited ground as *playback*:

- During a real forward run, cache the per-frame render payload for each
  pausepoint stretch — the geometry stream already exists as message 0x03,
  and `--export`'s `GeometryRecorder` + the baked player already record and
  replay exactly this format. Segment boundaries are already on the wire as
  `move` messages.
- LEFT plays the stretch's frames backward: exact reversal of anything —
  Creates undraw, tracker sweeps rewind — because it is literally the
  forward render in reverse. RIGHT over visited ground replays forward
  without re-executing code; `pause(loop=True)` laps a recording instead of
  re-running the stretch. Code executes only at the frontier and after
  edits (restore the pause before the edit, re-run, re-record from there).
- Prefer the **client-side cache**: the viewer already receives every frame
  (pixels or geometry); caching per segment in the browser makes playback
  local, keeps the server out of navigation, and is the shape a Pyodide
  build and remote viewing both need. It also converges the live viewer
  with the baked player — export becomes "save the cache".
- Landing on a pausepoint restores the real checkpoint state, so parked is
  live (inspectable, updaters running) and motion is film. Sound cues and
  a memory/disk bound (the export folder is the on-disk format) ride along.

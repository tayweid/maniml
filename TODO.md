# TODO

The forward roadmap. What was decided, shipped, or tried-and-deleted —
and why — lives in `DECISIONS.md`; the architecture as it stands lives
in `CLAUDE.md`.

## The milestone: WebGPU as the one canonical renderer

Decided 2026-08-14, sequencing confirmed 2026-08-18. The wgpu backend
already covers the full parity ledger in both the browser
(`static/webgpu.js` + `static/wgsl/`) and natively
(`web/wgpu_renderer.py`), the live viewer starts on WebGPU with a
visible Pixel fallback, and the fidelity suite passes. What remains is
sequence, each step gated on the one before it:

1. **Dogfood real course scenes in WebGPU solo mode.** The burn-in
   state: the pixel stream off, the client canvas the only viewer,
   unsupported content surfaced loudly. This is the gate everything
   below waits on.
2. **Retire `gl.js` + `glsl/`** (and the WebGL2 half of
   `reference_renderer.py` / `tests/test_gl_port.py`). Decided; only
   the burn-in holds it.
3. **Retire the native geometry-shader pipeline**: `--render` and the
   reference renderer move onto wgpu-py, making the browser renderer
   and the reference renderer literally the same code. WebGPU compute
   can then restore GPU-side adaptive tessellation, replacing the
   fixed-strip instancing compromise.
4. **Retire pyglet** (`rendering/window.py`): blocked on trusting
   `--web` for daily use, and on inlining the pyglet key/mouse
   constants `viewer.py` imports for the InteractionMixin mapping.
   Moving the `--present` timeline from the GL overlay to DOM belongs
   here too — it absorbs the scrubber-crowding item below and deletes
   the checkpoint-ignore plumbing.
5. After the transition: Windows/Linux CI matrices and cross-platform
   packaging return (scoped out during the macOS developer preview).

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
  plays is one unit: the rail may show 16 pausepoints while a single
  forward press fires all of them. Opening no longer auto-runs
  (2026-08-18), which removed the worst of it, but per-play stepping
  inside a loop would mean running a unit as something suspendable — a
  coroutine or a thread that parks at each `play()`. Related: a scene's
  `self.add(...)` preamble lives in the same unit as its first play, so
  a scene now opens on an empty frame. Rendering the preamble needs
  `source_map` to split a unit at its play statement, and checkpoint 0
  re-baked to match — doable, but it must not let the preamble run
  twice, or it reproduces the duplicate-mobject bug above.

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
  idiom.
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

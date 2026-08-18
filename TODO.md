# TODO

## Browser viewer (the direction — decided 2026-08-12)

The pyglet window is the most alien inherited layer and the part of the
stack that feels wrong; the browser is now the UI toolkit we're fluent in
(Plass). Move the VIEWER, not the renderer. Two stages, staged so the UI
investment carries over completely and the shader port never happens at
the same time as a UI rebuild.

**Stage 1 — browser viewer, native renderer. SHIPPED 2026-08-13 as an
additive `--web` flag** (`maniml scene.py Name --web`, combines with
`--present`; `--no-browser` suppresses the auto-opened tab). Built in
`maniml/web/` — server.py (WebSocket + HTTP daemons), viewer.py
(WebViewer duck-types the Window interface; camera runs windowless on
the standalone GL context, the `--render` path), static/index.html
(vanilla-JS client: canvas, keyboard/pointer forwarding, checkpoint
chips). Protocol as sketched: JPEG while animating / input arriving,
one lossless PNG at quiet; state JSON on change; picking server-side.
End-to-end tested headlessly in `tests/test_web_viewer.py`. Measured
streaming tax ~3.7ms/frame at 1080p (readback 1.4 + PIL JPEG 2.4).

Deliberately NOT done yet (risk containment — pyglet path untouched
until `--web` earns trust in daily use):
- Deleting `rendering/window.py` + the pyglet dependency. Also blocked
  on: viewer.py imports pyglet's key/mouse constants for the
  InteractionMixin mapping — inline them when pyglet goes.
- `--present` timeline is still the GL overlay (works over --web since
  it renders into the FBO); moving it to DOM absorbs the
  scrubber-crowding item below and deletes the checkpoint-ignore
  plumbing.
- Porting `tests/test_interactive` to Playwright against a headless-GL
  server (kills the xvfb job in the CI plan below).
- Idle-loop updater scenes stream via a per-tick `has_updaters()` scan
  of top-level mobjects; nested-family-only updaters would be missed.

**Stage 2 — the client learns to render (the portability payoff).
STARTED 2026-08-13; snapshot path shipped, streaming not yet.**
- CORRECTION to the note below from 2026-08-12: the pipeline is NOT
  geometry-shader-free — maniml and current 3b1b/manim both have
  4 geometry shaders (quadratic_bezier fill/stroke/depth, true_dot),
  and the stroke one carries the adaptive polyline + joints. The port
  therefore re-expresses them as *instanced vertex shaders* (one
  instance per bezier triple, gl_VertexID enumerating the emitted
  strip) rather than transliterating.
- Done: `web/geometry.py` (0x03 snapshot message: camera uniforms +
  per-batch mobject uniforms + the raw 68-byte-stride vertex structs in
  draw order); `web/static/glsl/` (fill winding pass, stroke, border,
  composite, written in the common GLSL 330 / 300 es subset);
  `web/static/gl.js` (WebGL2 renderer behind the client's "GL" toggle,
  side-by-side with the pixel stream, re-snapshots on state change);
  `web/reference_renderer.py` (SAME shaders compiled on desktop GL —
  keep it in sync with gl.js) with `tests/test_gl_port.py` pixel-diffing
  it against the native renderer: mean |diff| 4e-5/255, 0.0005% of
  pixels off by >2 (AA edge pixels) on a fill+stroke+winding+Text scene.
- Done 2026-08-13 (second pass): geometry streams during play() —
  every pixel frame is mirrored with a payload while the GL toggle is
  on — and the GL panel accepts pointer input.

**Stage 2 parity ledger** (gaps between the GL client render and the
native renderer, in priority order; checked = done):
1. [x] 3D VMobjects (2026-08-13): triangulated fill serialized as
   vertices+indices+flat color (`tri` in the batch), depth test on
   stroke/fill, MSAA via multisampled renderbuffer + resolve blit,
   samples in the header. 3D fidelity test: mean |diff| 0.003/255.
   Still excluded: depth-tested winding fill (item 6).
2. [x] DotCloud (2026-08-13): point→billboard-quad geometry shader
   re-expressed as 4-vertex instanced strip (`vdot.*`); glow + sphere
   shading ported. Fidelity test: 0.0 diff (bit-perfect).
3. [x] ImageMobject (2026-08-14): raw file bytes ship in the payload
   by content hash (once — textures ride the delta system), browser
   decodes natively. Bit-perfect vs native.
4. [x] Surface (2026-08-14): already-CPU-expanded triangles, existing
   surface program. Bit-perfect (Sphere with shading).
5. [x] TexturedSurface (2026-08-14): day/night texture pair + the
   textured-surface frag ported. Bit-perfect.
6. [x] Winding-fill depth pre-pass: FALLBACK BY DESIGN (2026-08-14).
   Unreachable through the public API — ThreeDScene.add /
   apply_depth_test always switch fills to triangulated; hitting this
   path requires manually unsetting use_triangulated_fill. Declared
   `unsupported`; revisit only if dogfooding ever surfaces it.
7. [x] Clip planes (2026-08-14): v_clip varying + fragment discard in
   every program (pixel-resolution equivalent of gl_ClipDistance).
   Fidelity test with set_clip_plane passes.
8. [ ] `set_color_by_code` (arbitrary GLSL injection) and the fractal
   shaders: niche; likely permanent pixel-stream fallbacks.
9. [x] Delta encoding (2026-08-14): batches carry a blake2b content
   hash; unchanged batches ship as `"cached": true` references (zero
   bytes) while metadata (uniforms, stroke_verts) stays fresh so zoom
   changes need no re-upload. Client + reference renderer cache GPU
   buffers/VAOs by hash (LRU 512); a client cache miss requests
   `geometry_reset` for a full resend; the server-side sent-set resets
   on connect and on mode-on. Remaining serialize CPU per frame is the
   numpy get_shader_data walk — optimize via _data_has_changed only if
   profiling ever demands.
10. [x] Solo-GL view (2026-08-14): the GL button cycles off →
   side-by-side compare → solo. In solo the pixel stream stops
   entirely (no per-frame readback/encode server-side) and the GL
   canvas is the viewer, fully interactive; unsupported content is
   surfaced loudly in the bar since there is no pixel safety net.
   THE STAGE-2 BURN-IN STATE — dogfood real course scenes here.
   → The baked player SHIPPED 2026-08-14: `--export` records the
   geometry stream headlessly (web/export.py, the same _web_viewer
   hooks, unpaced) into ./media/SceneName_web/ — a self-contained
   static folder (player page + both renderers + gzipped stream, ~7x
   compression; the dogfood Demo bakes to 1.7MB) for GitHub Pages
   sharing: scrub/play per animation segment, no Python anywhere.
   Known cost: delta granularity is per merged batch, so an animating
   batch re-ships whole frames — fine for hold-heavy lectures, ~video-
   sized for animation-dense scenes; per-submobject deltas if it ever
   matters.
- Anything unsupported stays honestly declared in the payload's
  `unsupported` list; the pixel stream remains the fallback throughout.
- **The endgame (decided 2026-08-14): WebGPU as the one canonical
  renderer.** Sequencing: finish parity on WebGL2 first (ledger items
  below — the payload format, protocol, serializer, and fidelity
  harness are backend-agnostic and survive), THEN stand up a WebGPU
  backend beside WebGL2 against the same payload and tests, migrate,
  and make it canonical. wgpu runs the same code in-browser and
  natively (wgpu-py), so at that point the reference renderer and the
  browser renderer become literally the same code, `--render` moves
  onto it, and the geometry-shader pipeline (and eventually pyglet)
  retires: one renderer everywhere, no dual maintenance. WebGPU also
  restores GPU-side adaptive tessellation via compute shaders (the
  elegant replacement for the fixed-strip instancing compromise).
  Chrome is the app; browser support is a non-issue.
  STARTED 2026-08-14: `web/wgsl/` (common/fill/stroke/composite in
  WGSL) + `web/wgpu_renderer.py` (wgpu-py) render the 2D VMobject path
  from the same payload — fidelity vs native: max diff 1/255, zero
  pixels off by >2 (tests/test_wgpu_port.py). WebGPU-specific handling:
  clip-space depth remap in emit_gl_position (GL [-w,w] → WebGPU
  [0,w]), per-pipeline blend state, one packed 176-byte uniform struct
  (keep UNIFORM_FIELDS and struct Uniforms in sync), top-down readback.
  FULL SCOPE 2026-08-14 (second pass): the wgpu backend now covers the
  entire parity ledger — 3D/depth/MSAA (per-pipeline depth state,
  multisampled target + resolve), triangulated fill (indexed draw),
  dots, images, surfaces, textured surfaces, clip planes — via a lazy
  pipeline cache keyed (name, sample_count). tests/test_wgpu_port.py
  runs all six fidelity scenes: 2D/clip/dots bit-perfect (max 1/255);
  image/3D/surfaces differ on ~0.04% of pixels at silhouette edges
  (implementation-defined MSAA sample positions + texture-filtering
  precision, Metal vs GL — legitimate cross-API variance).
  Batch caching + browser driver DONE 2026-08-14 (third pass): wgsl/
  moved under static/ so the page can fetch it; `static/webgpu.js` is
  the navigator.gpu mirror of wgpu_renderer.py (same specs/layouts/
  uniform packing/pass structure — keep all three in sync), presenting
  via a blit pass since the canvas swapchain format is
  platform-preferred. The client now has TWO backend buttons, GL
  (WebGL2) and WGPU, each cycling off → compare → solo, mutually
  exclusive. Browser dogfooding now covers the live ManimCE compatibility
  path, reverse/forward pausepoint playback, and visible WebGPU output. The
  live viewer starts on WebGPU and falls back visibly to Pixel when WebGPU is
  unavailable. Remaining: broaden course-scene dogfooding, then retire
  gl.js/glsl, followed by the geometry-shader pipeline and pyglet.

**Stage 3b — the hosted PWA. TRIED, THEN DELETED (2026-08-17).** The
frontend deployed to GitHub Pages and talked *across* origins to the local
engine. Everything that seam needed — a service worker and manifest, a
versioned wire handshake, URL-fragment pairing per daemon session, an
AppleScript launcher, a `maniml://` URL scheme, Launch Services
registration, Chrome PWA shim discovery, a public-origin allowlist — cost
roughly 1,400 lines and produced essentially every delivery bug this
project has had. "Collapse to a local, pip-only app" removed all of it,
along with the macOS desktop launch bridge built on top of it
(`install-desktop`, `maniml open FILE`, the `.py` Finder association) and
its public-release gates. The engine that runs the scenes now serves the
interface, from the same pip install, so they cannot drift. **Do not
reintroduce a public origin that talks to loopback.**

Knuth spent 2026-08-17 arriving at the same architecture from the same
starting point; its findings are recorded in `SAME_ORIGIN_NOTES.md` and two
of them landed here:

- **One port, not two (2026-08-17).** The page was served on N and its
  socket lived on N+1, so "same-origin" was two origins bridged by an
  allowlist — paying for a port-pair search, a `?ws=` parameter, a
  `#control=` fragment, and a parent origin threaded into every scene
  subprocess. Both servers now answer plain GETs on their WebSocket port
  (`web/assets.py` via `process_request`), the client says
  `ws://${location.host}/`, and `connect-src 'self'` became a real
  restriction. The app's `/api/*` endpoints went with it — the page had
  spoken only over the control socket since the hosted UI died.
- **No capability token (2026-08-17).** It defended only against another
  program running as you, which can forge any header and can equally run
  `python` itself; keeping it meaningful meant delivering it out of band,
  which made launching a delivery problem and left a refused page needing a
  terminal to recover. The Origin check is now the whole boundary, and
  `http://localhost:8685/` is an address worth bookmarking. The attacker
  table is in `SECURITY.md`. Note the trap named in the notes: *embedding a
  token and keeping a token are different decisions.*

**The shape it settled into (2026-08-17), matching Knuth's first run:**

1. `maniml.tayweid.io` is a preview (`site/`) — shows what this is, gives the
   install command, reaches nothing, cannot be installed.
2. `pip install` → `maniml app` starts the engine and opens
   `http://localhost:8685`.
3. The app offers **Install** for an icon and a tab-less window. Installing
   belongs to this origin alone, because only one installed app can own a
   `.py` and it should be the one with a Python process behind it.

Scenes are relayed through the app's port rather than opened on their own,
because the port is the installed app's identity — see CLAUDE.md.

Still open on this path:
- **`.py` double-click.** Blocked on a real problem, not effort: `launchQueue`
  delivers a browser file handle with no filesystem path, and the watcher and
  the scene's `__file__`-relative imports both need one. Options if it matters:
  resolve the handle's name against the app root and recents (ambiguous for
  duplicate basenames), or keep the native dialog as the only path in.
- **Fold `agent install` into first run.** Knuth asks once, at the only moment
  it makes sense, rather than leaving a documented command to discover. maniml
  still expects you to know `maniml agent install`.
- **Confirm the install in a real browser.** Chrome's installability criteria
  and the offline shell have not been exercised here — Knuth measured its own
  spike on Chrome 151/macOS 26 and got file handlers, `launchQueue`, and an
  offline shell all working from a loopback origin.
- **A live demo on the preview.** `--export` already bakes a scene into a
  self-contained page that runs with no Python at all, which would let a
  visitor actually scrub through a real scene instead of reading about one.

**Stage 3 — the app (started 2026-08-14).** `maniml app [dir]`
(`web/app.py` + `static/app.html`): persistent local server, landing
page listing scene files under the dir (AST scan for *Scene classes,
no import) plus recents (~/.maniml_recents.json); opening a scene
spawns `maniml file.py Scene --web` as its own subprocess (crash
isolation; process reused for repeat opens; children terminated on app
exit; stdout tail kept per process — the future console panel's feed).
The viewer and landing shell were redesigned again on 2026-08-16 in the
shared Plass/Knuth visual language: warm graphite canvas, quiet floating
glass slugs, file-action and renderer flyovers, explicit reverse/forward
transport, and a separate DOM pausepoint rail at the bottom. The export
flyover saves the current frame or starts an isolated, one-at-a-time video
render / baked-web export, leaving the live scene and its checkpoints intact.
The three-way renderer control (Pixel / WebGL2 / WebGPU) and comparison mode
remain available in a compact flyover. Later: console panel in the viewer
(stdout is already captured), process controls on the landing page, and
multi-scene tabs.

Security baseline (2026-08-17): each server binds one loopback port, serves
its page there, and completes a WebSocket handshake only for its own exact
origin — no tokens, no pairing, nothing carried in a URL. Pages are served
with `default-src 'self'; connect-src 'self'`. Scene paths stay confined to
the selected app root by default; `--allow-outside-root` is the explicit
compatibility escape hatch, and a file chosen in the native dialog grants
that one file. See `SECURITY.md` and `web/security.py`.
- The baked-scene web player then falls out for free: the same client
  rendering live WS data renders saved data from a file → `--render`
  grows a `--web` sibling, a self-contained page where students scrub
  through a lecture's animations with no Python anywhere.
- This is also the dry run for an eventual wgpu-py native backend, which
  otherwise waits for a forcing event (Apple actually removing GL).
- Open questions: frame pacing/backpressure in Stage 1; multi-client
  (presenter + audience views?); baked-format size for long scenes;
  whether idle frames should be the client's own render in Stage 2 or
  stay server-authoritative.

**Typst text backend (independent of the viewer; do whenever).** Replace
LaTeX/dvisvgm with Typst for Tex/MathTex: mitex accepts LaTeX math
syntax, so `MathTex(r"\frac{a}{b}")` keeps its API while Typst renders →
SVG → mobject paths. Kills the texlive install burden (the single worst
student-install pain), much faster text builds, same engine as Plass
(suite convergence), and a prerequisite for any future in-browser
authoring. Watch: typography drift vs CE is already noted in Quality
tier; Typst-rendered math will drift differently — keep the conformance
eye on it.

- **CI and release safety. SHIPPED 2026-08-16.** During the macOS developer
  preview, locked syntax/package and headless integration jobs cover macOS 14
  on Python 3.11 and 3.14. Windows and Linux application matrices return after
  WebGPU is canonical and cross-platform packaging resumes. CodeQL scans
  `maniml/`; a weekly AST-only job detects ManimCE public-API drift; the release
  workflow can build and inspect a candidate but cannot publish it. The full
  windowed interactive suite on macOS remains a manual public-release gate.


- **BUG: navigation can leave two copies of a moved mobject on screen**
  (seen 2026-08-18). In `ECON_0100/F26/blocks/A0_The_Landscape/03_Code.py`,
  `Animation0`, the live viewer showed the `MICROECONOMICS` block letters
  twice — once at the pre-move position and once where
  `Squares.animate.to_edge(UP, buff=1)` puts them — after arrowing around and
  landing on the last pausepoint.

  Already ruled out, so nobody re-does it: **not the client renderers** (the
  viewer was on Pixel, i.e. the native GL render), **not the scene** (it adds
  one `Squares` and moves it), and **not a regression from the same-origin
  work** (that touched no code under `rendering/`, `mobject/`, `scene/`,
  `camera/`, `animation/`). A forward-only `--render` of the same scene on the
  same build is correct — checkpoint 032 shows one title — so it is reachable
  only through interactive navigation.

  Where to look: `_play_reverse_to` in `scene/interaction.py` pairs mobjects by
  variable name, Transforms matched pairs and fades unmatched ones, and is
  meant to be display-only (`_no_checkpoints()`); and
  `_restore_checkpoint_for_display` in `scene/checkpoints.py`. The suspicion is
  that a display-only morph leaves a mobject in `self.mobjects` that the next
  restore does not clear, so the restored copy joins it rather than replacing
  it. Reproduce headlessly the way `tests/test_web_viewer.py` drives the
  viewer: RIGHT to the end, LEFT/UP back a few, RIGHT forward again, then
  count top-level mobjects rather than eyeballing a frame.

- **Presentation timeline: window the scrubber for large scenes.** The bar
  packs all N rings into a fixed 60% span, so past ~50 checkpoints the rings
  crowd, and past ~78 they overlap and the connecting-line stubs invert
  (`_show_timeline` in `maniml/maniml/scene/presentation.py`). Plan: show
  every k-th ring plus the neighborhood around the current checkpoint,
  rather than all of them. (Simpler fallback if windowing proves fiddly:
  adaptive marker radius `r = min(0.055 * scale, 0.35 * spacing)`, dropping
  the connecting line when gaps get tiny.)

## Quality tier (correctness is done; these are polish, none block course production)

- **Supersampled `--render` output (~1 hour).** macOS caps live-window MSAA
  at 4 samples, but offline rendering has no cap: add a flag that renders
  each frame at 2x resolution and downscales before writing — effectively
  unlimited edge AA for published videos, on everything (fills, strokes,
  text). The live-preview cap is then irrelevant.
- **3D fills flatten gradients.** The triangulated depth-correct fill path
  (`render_triangulated_fill`) samples one flat fill color per family
  member. Multicolor text is fine (per-glyph colors survive); a
  gradient-filled shape in a ThreeDScene loses its gradient. Fix: carry
  per-vertex colors through the triangulation.
- **Re-triangulation cost for animated 3D fills.** Under depth test, a
  mobject whose points change re-runs earclip every frame (cache keys on a
  points hash). Fine for shapes; measurable when morphing large Text in 3D.
  Fix: transform-aware cache so rigid motions reuse the mesh.
- **z_index sorts top-level mobjects only.** CE also sorts within families;
  maniml preserves family draw order. Rarely matters — noted so it doesn't
  surprise.
- **Minor typography drift vs CE.** Multi-part `MathTex(...)` parts join
  with TeX's natural math spacing, slightly tighter than CE's joining.
  Cosmetic.

(LEFT-arrow reverse being an approximate morph rather than true reversal is
a design property, documented in CLAUDE.md's weak spots.)

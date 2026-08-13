# TODO

## Browser viewer (the direction — decided 2026-08-12)

The pyglet window is the most alien inherited layer and the part of the
stack that feels wrong; the browser is now the UI toolkit we're fluent in
(Plass). Move the VIEWER, not the renderer. Two stages, staged so the UI
investment carries over completely and the shader port never happens at
the same time as a UI rebuild.

**Stage 1 — browser viewer, native renderer (days, not weeks).**
- Keep unchanged: scene execution, checkpoints, watcher, and OpenGL
  rendering — render offscreen into the FBO (camera already renders to an
  fbo; only the window blit goes away).
- Delete: `rendering/window.py` and the pyglet dependency. The
  `InteractionMixin` handlers stay; they're fed by protocol messages
  instead of pyglet events.
- Add: a localhost WebSocket server + a small Vite/TS client page:
  `<canvas>` showing streamed frames, checkpoint-chip timeline, keyboard
  forwarding, pointer events.
- Protocol sketch — server→client: binary frame (JPEG during `play()`,
  one lossless PNG when idle — scenes are static between animations, so
  stream only while animating); state `{checkpoint index/count, unit
  line numbers}`. client→server: key events, pointer down/move/up,
  timeline clicks. Picking stays server-side (`point_to_mobject` owns
  the geometry) — the click-prints-name / drag-prints-`move_to` flow
  survives unchanged; client sends canvas px, server maps to scene
  coords via camera.
- JPEG over localhost WS comfortably does 30–60fps; WebRTC/H.264 only if
  streaming ever leaves localhost (remote/iPad second-screen viewing is
  a free unlock).
- `--present` becomes a URL: fullscreen API on the projector. The
  timeline-scrubber crowding item below is ABSORBED by this — the
  overlay becomes DOM, where windowing every k-th chip is trivial (and
  the GL overlay + its checkpoint-ignore plumbing gets deleted).
- CI interplay: the windowed `tests/test_interactive` suite becomes
  Playwright driving the real client against a headless-GL server — no
  xvfb window needed anywhere; GL is offscreen-only everywhere.

**Stage 2 — the client learns to render (the portability payoff).**
- Same client UI shell, same protocol shape; payload becomes the shader
  data arrays instead of pixels, rendered client-side in WebGL2 first —
  the GLSL 330 shaders port nearly verbatim to 300 es since the
  pipeline is geometry-shader-free (verified: no .geom in maniml or
  current manimgl; post-2023 vertex+fragment bezier pipeline). WebGPU
  later only if it earns it.
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

- **CI workflow (after the GitHub migration).** One GitHub Actions file,
  three jobs: (1) pure-logic tests (`test_source_map`,
  `test_ce_conformance`) on Ubuntu + macOS, Python 3.10–3.12 — trivial;
  (2) GL headless tests (`test_checkpoint_reload`, `test_modes`) on
  Ubuntu via Mesa software rendering (`apt install libegl1 xvfb`, run
  under `xvfb-run`, may need `MESA_GL_VERSION_OVERRIDE`), plus a macOS
  job as the trustworthy-GL hedge; (3) stretch: the windowed
  `tests/test_interactive` suite under xvfb — the harness drives the real
  pyglet window programmatically, so a virtual display suffices. Needs
  ffmpeg on runners; keep Tex out of CI fixtures to avoid texlive.
  Prerequisite: maniml pushed to github.com/tayweid/maniml.


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

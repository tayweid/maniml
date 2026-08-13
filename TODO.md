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

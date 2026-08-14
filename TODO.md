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
3. [ ] ImageMobject: image program + shipping the texture over the WS
   (PNG bytes in the payload, texture cache keyed by hash).
4. [ ] Surface / ParametricSurface: surface program (ported for #1)
   + CPU-side indices from `get_shader_vert_indices`; shading uniforms
   already ported.
5. [ ] TexturedSurface: #3's texture transport + day/night pair.
6. [ ] Winding-fill depth pre-pass (depth-tested fill WITHOUT
   use_triangulated_fill — rare in maniml since ThreeDScene.add forces
   triangulated; needs R32F target + MIN blend + gl_FragDepth
   composite, EXT_float_blend in WebGL2).
7. [ ] Clip planes: gl_ClipDistance has no WebGL2 equivalent; emulate
   with a varying + discard in every frag.
8. [ ] `set_color_by_code` (arbitrary GLSL injection) and the fractal
   shaders: niche; likely permanent pixel-stream fallbacks.
9. [ ] Delta encoding: full geometry is resent every frame (fine on
   localhost, wrong for the baked player) — resend only changed
   mobjects, keyed per batch.
10. [ ] Solo-GL view: once parity holds, let the GL panel BE the
   viewer (pixel stream off) — the actual Stage 2 end state; then the
   baked player = record the 0x03 stream to a file.
- Anything unsupported stays honestly declared in the payload's
  `unsupported` list; the pixel stream remains the fallback throughout.
- WebGPU later only if it earns it.
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

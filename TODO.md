# TODO

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

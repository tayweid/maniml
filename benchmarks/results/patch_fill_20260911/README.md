# The B1 patch fill prototype (2026-09-11)

`python -m benchmarks.gpu_borders --samples 12 --warmups 3 --cases tex_static
tex_pan tex_zoom5 tex_zoom4_cycle changing_paths --variants patch_fill
original_2d`, then the same with `--variants gpu_border original_2d`, Apple
M3, Python 3.13, Metal. The reading is in `docs/phase_b1_plan.md`,
"Prototype results".

Two builds were measured the same day. `summary_first_build.json` is the
first (strips on the surface pipeline, instanced groups). `summary.json` and
`patch_fill_report.json` are the second, after two changes Taylor asked for:
the cover no longer evaluates the curve test (the stencil count already holds
the answer per sample) and runs at pixel rate, and the mark draws its fan
triangles at pixel rate with only the patch triangles shaded per sample. Both
summaries carry each run's source hashes.

Warmed complete-frame medians / minima (ms), second build:

| Control | Patch fill | Phase A (GPU border) | Original 2D |
| --- | ---: | ---: | ---: |
| Static 101-glyph text | 5.11 / 4.83 | 5.28 / 3.99 | 5.41 / 5.14 |
| Text pan | 5.24 / 4.76 | 5.59 / 4.87 | 5.33 / 5.04 |
| Repeated 5% zoom | 5.42 / 4.91 | 5.73 / 5.42 | 5.30 / 5.12 |
| Text 1→4→1 zoom | 5.32 / 4.81 | 6.06 / 4.88 | 5.42 / 5.05 |
| Concave quad morph + circle | 4.58 / 2.71 | 5.19 / 2.90 | 2.84 / 2.62 |

First build, for the difference: patch fill 5.71 / 5.43, 5.87 / 5.46,
5.86 / 5.61, 5.92 / 5.44, 3.82 / 3.16 on the same rows; Phase A that run
4.14 / 3.94, 4.68 / 4.40, 6.26 / 3.94, 6.40 / 3.94, 4.19 / 3.01.

Pixels: unchanged between builds; patch fill against Original 2D, worst
fraction of pixels over 24 of 255 per control, 0.21% / 0.24% / 0.29% /
0.62% / 0.07%, identical to Phase A's own fractions on the same frames.
Draws per text frame: 5 (one instanced group of 101 glyphs) against Phase
A's 1. Phase A's medians move between runs with the alternation effect
recorded in `../triangle_followup_20260910/zoom_step_leftover/README.md`;
its minima are the stable figure.

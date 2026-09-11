# The B1 patch fill prototype (2026-09-11)

`python -m benchmarks.gpu_borders --samples 12 --warmups 3 --cases tex_static
tex_pan tex_zoom5 tex_zoom4_cycle changing_paths --variants patch_fill
original_2d`, then the same with `--variants gpu_border original_2d`, Apple
M3, Python 3.13, Metal, both on the tree this archive was committed with
(`summary.json` carries the source hashes of each run and the key numbers;
`patch_fill_report.json` is the complete patch run). The reading is in
`docs/phase_b1_plan.md`, "Prototype results".

Warmed complete-frame medians / minima (ms):

| Control | Patch fill | Phase A (GPU border) | Original 2D |
| --- | ---: | ---: | ---: |
| Static 101-glyph text | 5.71 / 5.43 | 4.14 / 3.94 | 5.84 / 5.43 |
| Text pan | 5.87 / 5.46 | 4.68 / 4.40 | 5.78 / 5.47 |
| Repeated 5% zoom | 5.86 / 5.61 | 6.26 / 3.94 | 5.81 / 5.35 |
| Text 1→4→1 zoom | 5.92 / 5.44 | 6.40 / 3.94 | 5.81 / 5.45 |
| Concave quad morph + circle | 3.82 / 3.16 | 4.19 / 3.01 | 3.34 / 2.81 |

Pixels: patch fill against Original 2D, worst fraction of pixels over 24 of
255 per control, 0.21% / 0.24% / 0.29% / 0.62% / 0.07%, identical to Phase
A's own fractions against Original 2D on the same frames (the two fills
agree; the 4× zoom figure is Phase A's pre-existing gap). Draws per text
frame: 4 (one instanced group of 101 glyphs) against Phase A's 1.

An earlier Phase A run the same day (`earlier_gpu_border_run_same_day` in
the summary) put its still frame at 6.75 ms median with a 4.24 minimum:
the alternation effect recorded in
`../triangle_followup_20260910/zoom_step_leftover/README.md`, which the
rerun did not show on the still frame but did on the zooms.

# The zoom-step leftover (2026-09-10)

`python -m benchmarks.gpu_borders --samples 12 --warmups 3 --cases tex_static
tex_pan tex_zoom5 tex_zoom4_cycle`, Apple M3, Python 3.13.9, Metal. "Before"
is the revision-cache run archived beside this one (`../render_cache_revision`,
its "after"). Two "after" runs: all four renderers in rotation as before, and
the new `--variants gpu_border original_2d` mode. `summary.json` holds the
key numbers, source hashes and readback distributions.

Warmed complete-frame medians (ms), before → after (four in rotation) / after (two):

| Control | GPU-border Phase A | Original 2D |
| --- | ---: | ---: |
| Static 101-glyph text | 5.26 → 5.33 / 5.31 | 5.58 → 5.57 / 5.59 |
| Text pan | 7.30 → 5.75 / 5.87 | 5.53 → 5.51 / 5.61 |
| Repeated 5% zoom | 8.89 → 5.89 / 5.89 | 5.75 → 5.73 / 5.57 |
| Text 1→4→1 zoom | 9.28 → 6.04 / 6.04 | 5.76 → 5.79 / 5.71 |

Phase A preparation on a zoom step: 4.77 → 1.90 ms (5%), 5.13 → 2.02 ms
(4× cycle); the unchanged frame stays at 1.4 ms. GPU-versus-CPU border
pixels exact on all four controls.

The GPU column did not move and is not explained by rotation alone: with
only two renderers alternating, Phase A's submit-through-readback stays
near 3.0 ms with a 2.9 ms minimum on the zoom controls, while Phase A alone
(the AA experiment in `../render_cache_revision`) completes the same frame
in about 1.6 ms. Alternating with any other renderer on this machine costs
Phase A about 1.3 ms of completion time; a live viewer runs one renderer,
so the isolated figure is the relevant one. Original 2D's readbacks are
unaffected by alternation. This remains a harness property, not a Phase A
cost, and is recorded rather than resolved.

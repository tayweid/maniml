# Revision-keyed renderer cache (2026-09-10)

`python -m benchmarks.gpu_borders --samples 12 --warmups 3 --cases tex_static
tex_pan tex_zoom5 tex_zoom4_cycle`, Apple M3, Python 3.13.9, Metal. "Before"
is the format 6 run archived beside this one (`../gpu_border_capacity`);
"after" is the same harness with `MANIML_RENDER_CACHE=revision` (the default)
and no verify mode. An earlier run of this benchmark inside a
`MANIML_VERIFY_LEDGER=1` shell showed no change: verification compares
bytes on every trusted reuse, by design.

Warmed complete-frame medians (ms), before → after:

| Control | GPU-border Phase A | CPU-border Phase A | Original 2D | Native GL |
| --- | ---: | ---: | ---: | ---: |
| Static 101-glyph text | 6.17 → 5.26 | 6.98 → 6.41 | 5.80 → 5.58 | 7.93 → 7.91 |
| Text pan | 8.36 → 7.30 | 8.85 → 8.32 | 6.01 → 5.53 | 7.92 → 8.06 |
| Repeated 5% zoom | 11.33 → 8.89 | 13.51 → 12.96 | 5.77 → 5.75 | 7.98 → 7.99 |
| Text 1→4→1 zoom | 11.59 → 9.28 | 17.90 → 15.91 | 5.92 → 5.76 | 8.06 → 8.12 |

Preparation stage medians (ms), GPU-border Phase A: static 3.35 → 1.49, pan
5.31 → 3.42, 5% zoom 6.80 → 4.77, 4× cycle 7.00 → 5.13. Outside the harness,
an unchanged 101-glyph frame prepares in 1.3 ms (was 3.1). GPU-versus-CPU
border pixels are exact on all four controls; idle and 5% zoom packets are
unchanged at 1.1 KB.

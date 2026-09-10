# GPU border capacity from step counts, indices off the wire (2026-09-10)

`python -m benchmarks.gpu_borders --samples 12 --warmups 3`, Apple M3, Python
3.13.9, Metal, run once against main at `d639d489` (before, fixed 64-vertex
capacity and the strip pattern on the wire) and once against the change
(after). `summary.json` holds both runs' key numbers and source hashes;
`after_report.json` is the complete after report. Per-frame images are not
archived; `gpu_vs_cpu` diagnostics are identical before and after.

Warmed complete-frame medians (ms):

| Control | GPU-border Phase A | CPU-border Phase A | Original 2D | Native GL |
| --- | ---: | ---: | ---: | ---: |
| B0, 211 squares | 24.18 → 24.32 | 24.68 → 24.07 | 63.98 → 64.19 | 252.13 → 252.31 |
| Static 101-glyph text | 7.26 → 6.17 | 6.79 → 6.98 | 5.74 → 5.80 | 7.95 → 7.93 |
| Text pan | 9.33 → 8.36 | 8.69 → 8.85 | 6.02 → 6.01 | 7.76 → 7.92 |
| Repeated 5% zoom | 11.23 → 11.33 | 14.59 → 13.51 | 5.74 → 5.77 | 7.95 → 7.98 |
| Text 1→4→1 zoom | 11.10 → 11.59 | 17.36 → 17.90 | 5.90 → 5.92 | 7.92 → 8.06 |
| Tilt | 9.16 → 8.25 | 8.89 → 8.76 | 5.72 → 5.82 | 8.00 → 7.88 |
| Resize | 10.92 → 11.41 | 11.42 → 12.01 | 5.95 → 7.18 | 7.99 → 8.30 |
| Changing paths | 4.01 → 3.92 | 3.62 → 3.80 | 3.19 → 3.21 | 3.68 → 3.74 |

GPU-border Phase A bytes, 101-glyph text unless noted:

| Metric | Before | After |
| --- | ---: | ---: |
| First frame packet | 3,170,379 | 791,079 |
| Fill-refinement packet, 1→4 zoom (largest) | 2,671,229 | 291,941 |
| Unchanged frame / 5% zoom step packet | 1,077 / 1,138 | 1,091 / 1,152 |
| Retained GPU geometry, static text (vertex + index + output + source) | 11,535,848 | 4,879,848 |
| of which index buffer | 2,431,368 | 895,368 |
| Retained GPU geometry at 4× zoom | 11,649,192 | 10,317,992 |
| Changing paths, first frame packet | 23,648 | 8,840 |

Pixels: GPU borders remain exact against the CPU emitter on six controls and
within 15/255 in one channel on the 4× zoom and tilt controls, exactly as
before. The text reserves 24 vertices per curve at the default zoom (need 12
with 2× headroom) and reaches the 64 maximum during the 4× zoom, so retained
memory at that zoom is close to the old fixed reservation.

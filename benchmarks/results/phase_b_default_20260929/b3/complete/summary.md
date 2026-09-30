| format | class | frames | phase_a complete = serialize + page + gpu (gpu min) | phase_b_forced complete = serialize + page + gpu (gpu min) | ratio (gpu min) | ≤ 1.25 | ratio, GPU part the wait for the device (no stamps) |
|---|---|---|---|---|---|---|---|
| 7 | pausepoint | 1 (1) | 2.57 = 0.53 + 0.15 + 1.89 (1.59) | 2.98 = 0.58 + 0.19 + 2.21 (1.92) | 1.158 (1.181) | yes | 1.110 |
| 7 | ticked | 11 (11) | 5.68 = 1.98 + 0.10 + 2.47 (1.68) | 6.31 = 2.79 + 0.11 + 2.47 (1.81) | 1.111 (1.205) | yes | 1.135 |
| 7 | camera | 12 (12) | 5.27 = 1.45 + 0.50 + 3.29 (2.03) | 4.60 = 1.21 + 0.62 + 2.68 (2.15) | 0.873 (0.996) | yes | 1.022 |
| 7 | play | 72 (12) | 11.63 = 6.58 + 0.94 + 4.54 (4.08) | 8.71 = 2.92 + 0.69 + 4.66 (3.38) | 0.749 (0.653) | yes | 0.754 |
| 7 | navigation | 11 (11) | 17.96 = 12.68 + 1.10 + 4.59 (3.82) | 18.18 = 9.56 + 2.02 + 6.05 (5.44) | 1.013 (1.080) | yes | 1.007 |
| 8 | pausepoint | 1 (1) | 0.53 = 0.53 + 0.00 + 0.00 (0.00) | 0.58 = 0.58 + 0.00 + 0.00 (0.00) | 1.105 (1.105) | yes | 1.105 |
| 8 | ticked | 11 (11) | 2.00 = 2.00 + 0.00 + 0.00 (0.00) | 2.76 = 2.76 + 0.00 + 0.00 (0.00) | 1.380 (1.380) | **no** | 1.380 |
| 8 | camera | 12 (12) | 4.44 = 1.47 + 0.25 + 2.60 (1.82) | 4.83 = 1.21 + 0.27 + 3.34 (2.04) | 1.087 (0.957) | yes | 1.043 |
| 8 | play | 72 (12) | 10.98 = 6.73 + 0.64 + 3.98 (2.88) | 7.19 = 3.09 + 0.37 + 3.88 (2.79) | 0.655 (0.577) | yes | 0.701 |
| 8 | navigation | 11 (11) | 17.37 = 12.46 + 1.03 + 4.26 (3.50) | 17.18 = 9.52 + 2.00 + 4.55 (3.01) | 0.989 (0.912) | yes | 1.112 |

Check, format 7 navigation first (not judged): 22.56 → 25.38 ms, 1.125

Check, format 8 navigation first (not judged): 22.24 → 21.10 ms, 0.948

Pixels, phase_b_vs_nets over 105 frames (12 pausepoints, 93 inside plays): worst 0.0002% over 24/255 (checkpoint 1344, pausepoint, largest channel 28); ≤ 0.5%: yes

Pixels, phase_b_vs_gpu_border over 105 frames (12 pausepoints, 93 inside plays): worst 0.0260% over 24/255 (checkpoint 996, pausepoint, largest channel 144); ≤ 0.5%: yes

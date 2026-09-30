| format | class | frames | phase_a complete = serialize + page + gpu (gpu min) | phase_b_forced complete = serialize + page + gpu (gpu min) | ratio (gpu min) | ≤ 1.25 | ratio, GPU part the wait for the device (no stamps) |
|---|---|---|---|---|---|---|---|
| 7 | pausepoint | 3 (3) | 2.08 = 0.54 + 0.01 + 1.52 (1.39) | 2.97 = 0.64 + 0.03 + 2.31 (2.12) | 1.432 (1.436) | **no** | 1.145 |
| 7 | camera | 3 (3) | 2.18 = 0.73 + 0.02 + 1.43 (1.37) | 3.43 = 1.17 + 0.20 + 2.06 (1.81) | 1.572 (1.499) | **no** | 1.300 |
| 7 | play | 36 (3) | 50.26 = 48.07 + 0.43 + 1.74 (1.33) | 23.46 = 13.30 + 1.85 + 8.30 (7.54) | 0.467 (0.455) | yes | 0.475 |
| 7 | navigation | 2 (2) | 18.93 = 16.94 + 0.42 + 1.57 (1.32) | 29.14 = 17.42 + 3.27 + 8.45 (8.01) | 1.539 (1.536) | **no** | 1.669 |
| 8 | pausepoint | 3 (3) | 0.53 = 0.53 + 0.00 + 0.00 (0.00) | 0.64 = 0.64 + 0.00 + 0.00 (0.00) | 1.198 (1.198) | yes | 1.198 |
| 8 | camera | 3 (3) | 2.19 = 0.74 + 0.02 + 1.43 (1.37) | 3.57 = 1.18 + 0.07 + 2.38 (2.06) | 1.631 (1.537) | **no** | 1.384 |
| 8 | play | 36 (3) | 50.18 = 48.02 + 0.43 + 1.40 (1.33) | 26.29 = 16.74 + 1.24 + 8.29 (6.94) | 0.524 (0.500) | yes | 0.543 |
| 8 | navigation | 2 (2) | 18.52 = 16.74 + 0.41 + 1.37 (1.32) | 28.64 = 17.36 + 3.27 + 8.00 (6.11) | 1.546 (1.447) | **no** | 1.646 |

Check, format 7 navigation first (not judged): 34.18 → 31.14 ms, 0.911

Check, format 8 navigation first (not judged): 33.63 → 29.59 ms, 0.880

Pixels, phase_b_vs_nets over 48 frames (3 pausepoints, 45 inside plays): worst 0.0000% over 24/255 (checkpoint 1, pausepoint, largest channel 0); ≤ 0.5%: yes

Pixels, phase_b_vs_gpu_border over 48 frames (3 pausepoints, 45 inside plays): worst 0.9789% over 24/255 (checkpoint 1, pausepoint, largest channel 177); ≤ 0.5%: **no**

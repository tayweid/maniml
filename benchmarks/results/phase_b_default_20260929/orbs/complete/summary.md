| format | class | frames | phase_a complete = serialize + page + gpu (gpu min) | phase_b_forced complete = serialize + page + gpu (gpu min) | ratio (gpu min) | ≤ 1.25 | ratio, GPU part the wait for the device (no stamps) |
|---|---|---|---|---|---|---|---|
| 7 | pausepoint | 3 (3) | 1.31 = 0.14 + 0.01 + 1.16 (1.09) | 2.62 = 0.15 + 0.03 + 2.43 (1.73) | 1.992 (1.541) | **no** | 1.716 |
| 7 | camera | 3 (3) | 1.32 = 0.19 + 0.02 + 1.11 (1.03) | 3.84 = 0.26 + 0.31 + 3.27 (1.87) | 2.913 (1.965) | **no** | 2.332 |
| 7 | play | 36 (3) | 10.04 = 8.86 + 0.09 + 1.08 (1.02) | 6.06 = 1.81 + 0.60 + 3.64 (2.24) | 0.604 (0.467) | yes | 0.685 |
| 7 | navigation | 2 (2) | 4.51 = 3.32 + 0.09 + 1.11 (1.03) | 6.71 = 2.65 + 0.85 + 3.20 (2.38) | 1.486 (1.327) | **no** | 1.593 |
| 8 | pausepoint | 3 (3) | 0.14 = 0.14 + 0.00 + 0.00 (0.00) | 0.15 = 0.15 + 0.00 + 0.00 (0.00) | 1.117 (1.117) | yes | 1.117 |
| 8 | camera | 3 (3) | 1.31 = 0.20 + 0.02 + 1.09 (1.03) | 3.60 = 0.26 + 0.23 + 3.09 (1.75) | 2.741 (1.791) | **no** | 2.074 |
| 8 | play | 36 (3) | 10.00 = 8.81 + 0.09 + 1.09 (1.02) | 6.45 = 2.25 + 0.49 + 3.68 (2.36) | 0.645 (0.513) | yes | 0.804 |
| 8 | navigation | 2 (2) | 4.36 = 3.19 + 0.09 + 1.09 (1.04) | 7.60 = 2.68 + 0.92 + 4.00 (2.68) | 1.744 (1.458) | **no** | 1.970 |

Check, format 7 navigation first (not judged): 7.10 → 6.64 ms, 0.935

Check, format 8 navigation first (not judged): 6.97 → 7.27 ms, 1.042

Pixels, phase_b_vs_nets over 48 frames (3 pausepoints, 45 inside plays): worst 0.0000% over 24/255 (checkpoint 1, pausepoint, largest channel 0); ≤ 0.5%: yes

Pixels, phase_b_vs_gpu_border over 48 frames (3 pausepoints, 45 inside plays): worst 0.3560% over 24/255 (checkpoint 1, play frame 14, largest channel 199); ≤ 0.5%: yes

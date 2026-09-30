| format | class | frames | phase_a complete = serialize + page + gpu (gpu min) | phase_b_forced complete = serialize + page + gpu (gpu min) | ratio (gpu min) | ≤ 1.25 | ratio, GPU part the wait for the device (no stamps) |
|---|---|---|---|---|---|---|---|
| 7 | pausepoint | 1 (1) | 2.30 = 0.45 + 0.04 + 1.81 (1.62) | 2.92 = 0.44 + 0.07 + 2.41 (1.92) | 1.266 (1.144) | **no** | 1.177 |
| 7 | ticked | 11 (11) | 3.88 = 0.70 + 0.22 + 3.20 (1.71) | 3.33 = 0.73 + 0.12 + 2.37 (1.87) | 0.857 (1.009) | yes | 0.911 |
| 7 | camera | 12 (12) | 5.70 = 1.51 + 0.49 + 3.37 (1.94) | 4.97 = 1.18 + 0.64 + 3.15 (2.29) | 0.872 (0.970) | yes | 1.002 |
| 7 | play | 100 (12) | 8.41 = 3.46 + 0.67 + 4.05 (3.10) | 7.77 = 2.59 + 0.65 + 4.75 (3.14) | 0.924 (0.876) | yes | 0.918 |
| 7 | navigation | 11 (11) | 13.74 = 7.18 + 1.00 + 4.59 (3.21) | 12.47 = 6.88 + 1.64 + 4.30 (2.75) | 0.908 (0.831) | yes | 0.797 |
| 8 | pausepoint | 1 (1) | 0.45 = 0.45 + 0.00 + 0.00 (0.00) | 0.43 = 0.43 + 0.00 + 0.00 (0.00) | 0.959 (0.959) | yes | 0.959 |
| 8 | ticked | 11 (11) | 0.70 = 0.70 + 0.00 + 0.00 (0.00) | 0.73 = 0.73 + 0.00 + 0.00 (0.00) | 1.037 (1.037) | yes | 1.037 |
| 8 | camera | 12 (12) | 4.75 = 1.53 + 0.29 + 2.90 (1.90) | 4.63 = 1.20 + 0.26 + 3.19 (2.16) | 0.974 (0.951) | yes | 0.910 |
| 8 | play | 100 (12) | 7.58 = 3.44 + 0.51 + 3.50 (2.03) | 8.09 = 2.99 + 0.37 + 4.32 (2.74) | 1.066 (1.191) | yes | 0.968 |
| 8 | navigation | 11 (11) | 12.37 = 7.18 + 1.13 + 3.92 (2.53) | 11.38 = 6.81 + 1.37 + 3.94 (2.62) | 0.920 (0.974) | yes | 0.886 |

Check, format 7 navigation first (not judged): 34.81 → 19.95 ms, 0.573

Check, format 8 navigation first (not judged): 33.15 → 19.29 ms, 0.582

Pixels, phase_b_vs_nets over 136 frames (12 pausepoints, 124 inside plays): worst 0.0000% over 24/255 (checkpoint 130, pausepoint, largest channel 27); ≤ 0.5%: yes

Pixels, phase_b_vs_gpu_border over 136 frames (12 pausepoints, 124 inside plays): worst 0.0412% over 24/255 (checkpoint 9, pausepoint, largest channel 142); ≤ 0.5%: yes

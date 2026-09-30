| format | class | frames | phase_a complete = serialize + page + gpu (gpu min) | phase_b_forced complete = serialize + page + gpu (gpu min) | ratio (gpu min) | ≤ 1.25 | ratio, GPU part the wait for the device (no stamps) |
|---|---|---|---|---|---|---|---|
| 7 | pausepoint | 10 (10) | 3.16 = 0.44 + 0.12 + 2.50 (1.78) | 3.62 = 0.44 + 0.15 + 3.03 (1.98) | 1.147 (1.044) | yes | 1.209 |
| 7 | ticked | 2 (2) | 4.59 = 2.12 + 0.12 + 2.35 (1.79) | 5.58 = 2.29 + 0.27 + 3.01 (2.37) | 1.215 (1.225) | yes | 1.310 |
| 7 | camera | 12 (12) | 5.54 = 2.00 + 0.51 + 3.81 (2.20) | 7.01 = 1.44 + 0.82 + 4.39 (2.70) | 1.266 (1.068) | **no** | 1.231 |
| 7 | play | 114 (12) | 14.10 = 7.20 + 1.47 + 5.06 (3.87) | 10.60 = 2.51 + 1.13 + 6.19 (4.43) | 0.752 (0.675) | yes | 0.807 |
| 7 | navigation | 11 (11) | 12.92 = 4.89 + 2.05 + 4.73 (3.69) | 15.17 = 6.82 + 2.28 + 5.04 (3.34) | 1.174 (1.115) | yes | 1.062 |
| 8 | pausepoint | 10 (10) | 0.44 = 0.44 + 0.00 + 0.00 (0.00) | 0.44 = 0.44 + 0.00 + 0.00 (0.00) | 1.007 (1.007) | yes | 1.007 |
| 8 | ticked | 2 (2) | 2.12 = 2.12 + 0.00 + 0.00 (0.00) | 2.30 = 2.30 + 0.00 + 0.00 (0.00) | 1.087 (1.087) | yes | 1.087 |
| 8 | camera | 12 (12) | 4.75 = 2.02 + 0.15 + 3.10 (1.87) | 5.00 = 1.44 + 0.28 + 3.43 (2.53) | 1.053 (1.086) | yes | 1.174 |
| 8 | play | 114 (12) | 12.37 = 7.23 + 1.08 + 4.07 (3.50) | 7.97 = 2.69 + 0.45 + 4.76 (3.92) | 0.644 (0.596) | yes | 0.690 |
| 8 | navigation | 11 (11) | 14.47 = 6.56 + 2.00 + 5.04 (4.30) | 14.33 = 6.84 + 2.36 + 5.13 (4.04) | 0.990 (0.898) | yes | 0.981 |

Check, format 7 navigation first (not judged): 33.32 → 22.05 ms, 0.662

Check, format 8 navigation first (not judged): 31.91 → 20.80 ms, 0.652

Pixels, phase_b_vs_nets over 151 frames (12 pausepoints, 139 inside plays): worst 0.0000% over 24/255 (checkpoint 307, play frame 4, largest channel 30); ≤ 0.5%: yes

Pixels, phase_b_vs_gpu_border over 151 frames (12 pausepoints, 139 inside plays): worst 0.0000% over 24/255 (checkpoint 307, play frame 4, largest channel 30); ≤ 0.5%: yes

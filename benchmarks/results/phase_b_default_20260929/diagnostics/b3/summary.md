| format | class | frames | phase_a complete = serialize + page + gpu (gpu min) | phase_b_forced complete = serialize + page + gpu (gpu min) | ratio (gpu min) | ≤ 1.25 | ratio, GPU part the wait for the device (no stamps) |
|---|---|---|---|---|---|---|---|
| 7 | pausepoint | 1 (1) | 2.75 = 0.54 + 0.15 + 2.06 (1.56) | 2.93 = 0.59 + 0.18 + 2.16 (1.90) | 1.065 (1.188) | yes | 1.158 |
| 7 | ticked | 11 (11) | 5.59 = 2.08 + 0.10 + 2.47 (1.65) | 6.79 = 2.89 + 0.11 + 2.50 (1.84) | 1.216 (1.176) | yes | 1.152 |
| 7 | camera | 12 (12) | 5.72 = 1.56 + 0.57 + 3.34 (2.04) | 5.45 = 1.33 + 0.63 + 3.01 (2.15) | 0.952 (0.973) | yes | 0.965 |
| 7 | play | 72 (12) | 11.78 = 6.60 + 1.02 + 4.64 (3.78) | 8.49 = 2.85 + 0.69 + 4.48 (3.01) | 0.721 (0.592) | yes | 0.727 |
| 7 | navigation | 11 (11) | 17.29 = 10.33 + 1.17 + 4.64 (3.58) | 17.60 = 9.61 + 2.10 + 5.52 (3.52) | 1.018 (0.994) | yes | 1.056 |
| 8 | pausepoint | 1 (1) | 0.52 = 0.52 + 0.00 + 0.00 (0.00) | 0.58 = 0.58 + 0.00 + 0.00 (0.00) | 1.113 (1.113) | yes | 1.113 |
| 8 | ticked | 11 (11) | 2.06 = 2.06 + 0.00 + 0.00 (0.00) | 2.90 = 2.90 + 0.00 + 0.00 (0.00) | 1.407 (1.407) | **no** | 1.407 |
| 8 | camera | 12 (12) | 4.48 = 1.57 + 0.24 + 2.68 (1.86) | 4.88 = 1.32 + 0.28 + 3.18 (2.05) | 1.092 (0.940) | yes | 1.056 |
| 8 | play | 72 (12) | 11.04 = 6.65 + 0.72 + 3.98 (2.81) | 7.09 = 3.06 + 0.36 + 3.92 (2.92) | 0.642 (0.585) | yes | 0.677 |
| 8 | navigation | 11 (11) | 17.43 = 10.36 + 1.10 + 4.18 (2.84) | 16.81 = 9.63 + 2.00 + 4.26 (2.97) | 0.964 (0.949) | yes | 1.088 |

Check, format 7 navigation first (not judged): 22.61 → 22.42 ms, 0.991

Check, format 8 navigation first (not judged): 25.17 → 21.75 ms, 0.864

Diagnostic, format 7 (not judged), phase_b_forced / phase_a_nets; phase_a_nets / phase_a: pausepoint 1.174; 0.907, ticked 1.190; 1.022, camera 0.914; 1.042, play 0.711; 1.015, navigation 0.962; 1.058, navigation first 0.926; 1.070

Diagnostic, format 8 (not judged), phase_b_forced / phase_a_nets; phase_a_nets / phase_a: pausepoint 1.091; 1.020, ticked 1.374; 1.025, camera 1.052; 1.038, play 0.637; 1.008, navigation 1.034; 0.932, navigation first 1.006; 0.859

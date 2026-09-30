| format | class | frames | phase_a complete = serialize + page + gpu (gpu min) | phase_b_forced complete = serialize + page + gpu (gpu min) | ratio (gpu min) | ≤ 1.25 | ratio, GPU part the wait for the device (no stamps) |
|---|---|---|---|---|---|---|---|
| 7 | pausepoint | 10 (10) | 3.38 = 0.65 + 0.12 + 2.45 (1.79) | 3.67 = 0.76 + 0.15 + 2.99 (2.15) | 1.085 (1.105) | yes | 1.212 |
| 7 | ticked | 2 (2) | 5.40 = 2.82 + 0.12 + 2.46 (1.84) | 7.42 = 4.15 + 0.27 + 3.00 (2.48) | 1.375 (1.445) | **no** | 1.478 |
| 7 | camera | 12 (12) | 5.61 = 2.09 + 0.53 + 3.23 (2.09) | 6.07 = 1.55 + 0.78 + 3.92 (2.64) | 1.081 (1.102) | yes | 1.206 |
| 7 | play | 114 (12) | 14.01 = 7.17 + 1.35 + 4.86 (4.33) | 10.29 = 2.49 + 1.14 + 6.41 (4.44) | 0.735 (0.663) | yes | 0.742 |
| 7 | navigation | 11 (11) | 13.25 = 5.30 + 2.06 + 4.81 (3.91) | 15.15 = 7.36 + 2.24 + 4.49 (2.80) | 1.143 (0.975) | yes | 1.012 |
| 8 | pausepoint | 10 (10) | 0.67 = 0.67 + 0.00 + 0.00 (0.00) | 0.76 = 0.76 + 0.00 + 0.00 (0.00) | 1.139 (1.139) | yes | 1.139 |
| 8 | ticked | 2 (2) | 2.81 = 2.81 + 0.00 + 0.00 (0.00) | 3.81 = 3.81 + 0.00 + 0.00 (0.00) | 1.354 (1.354) | **no** | 1.354 |
| 8 | camera | 12 (12) | 4.96 = 2.12 + 0.17 + 3.03 (1.91) | 5.31 = 1.52 + 0.25 + 3.57 (2.54) | 1.069 (1.119) | yes | 1.082 |
| 8 | play | 114 (12) | 12.49 = 7.28 + 1.10 + 4.22 (3.58) | 8.41 = 2.68 + 0.47 + 4.78 (3.99) | 0.673 (0.609) | yes | 0.709 |
| 8 | navigation | 11 (11) | 12.47 = 5.26 + 1.96 + 4.81 (3.60) | 13.13 = 6.98 + 2.33 + 4.85 (2.91) | 1.053 (1.102) | yes | 1.109 |

Check, format 7 navigation first (not judged): 34.74 → 20.97 ms, 0.604

Check, format 8 navigation first (not judged): 31.42 → 20.65 ms, 0.657

Diagnostic, format 7 (not judged), phase_b_forced / phase_a_nets; phase_a_nets / phase_a: pausepoint 1.122; 0.967, ticked 1.404; 0.979, camera 1.092; 0.990, play 0.732; 1.005, navigation 1.126; 1.015, navigation first 0.584; 1.035

Diagnostic, format 8 (not judged), phase_b_forced / phase_a_nets; phase_a_nets / phase_a: pausepoint 1.143; 0.996, ticked 1.122; 1.206, camera 1.070; 0.999, play 0.675; 0.998, navigation 0.903; 1.166, navigation first 0.654; 1.005

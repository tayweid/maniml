| format | class | frames | phase_a complete = serialize + page + gpu (gpu min) | phase_b_forced complete = serialize + page + gpu (gpu min) | ratio (gpu min) | ≤ 1.25 | ratio, GPU part the wait for the device (no stamps) |
|---|---|---|---|---|---|---|---|
| 7 | pausepoint | 1 (1) | 2.47 = 0.62 + 0.04 + 1.82 (1.61) | 3.94 = 0.70 + 0.06 + 3.19 (2.06) | 1.596 (1.243) | **no** | 1.341 |
| 7 | ticked | 11 (11) | 4.46 = 0.93 + 0.26 + 3.00 (1.67) | 3.83 = 1.15 + 0.13 + 2.56 (1.93) | 0.858 (1.138) | yes | 0.816 |
| 7 | camera | 12 (12) | 5.83 = 1.57 + 0.56 + 3.36 (1.95) | 5.88 = 1.24 + 0.69 + 3.91 (2.42) | 1.008 (1.037) | yes | 0.982 |
| 7 | play | 100 (12) | 8.61 = 3.44 + 0.80 + 4.13 (2.91) | 8.00 = 2.49 + 0.67 + 4.27 (2.79) | 0.929 (0.802) | yes | 0.842 |
| 7 | navigation | 11 (11) | 13.46 = 8.20 + 1.00 + 4.67 (3.21) | 11.98 = 6.69 + 1.70 + 3.96 (2.69) | 0.890 (0.842) | yes | 0.844 |
| 8 | pausepoint | 1 (1) | 0.61 = 0.61 + 0.00 + 0.00 (0.00) | 0.69 = 0.69 + 0.00 + 0.00 (0.00) | 1.134 (1.134) | yes | 1.134 |
| 8 | ticked | 11 (11) | 0.93 = 0.93 + 0.00 + 0.00 (0.00) | 1.12 = 1.12 + 0.00 + 0.00 (0.00) | 1.208 (1.208) | yes | 1.208 |
| 8 | camera | 12 (12) | 5.07 = 1.59 + 0.34 + 2.84 (1.82) | 4.74 = 1.25 + 0.30 + 3.16 (2.25) | 0.935 (1.036) | yes | 0.860 |
| 8 | play | 100 (12) | 8.47 = 3.41 + 0.65 + 4.18 (3.15) | 7.69 = 2.92 + 0.37 + 4.16 (2.74) | 0.909 (0.830) | yes | 0.903 |
| 8 | navigation | 11 (11) | 13.30 = 7.37 + 1.12 + 4.44 (3.41) | 11.54 = 6.83 + 1.47 + 3.47 (2.69) | 0.868 (0.868) | yes | 0.869 |

Check, format 7 navigation first (not judged): 32.89 → 21.51 ms, 0.654

Check, format 8 navigation first (not judged): 33.85 → 18.23 ms, 0.539

Diagnostic, format 7 (not judged), phase_b_forced / phase_a_nets; phase_a_nets / phase_a: pausepoint 1.588; 1.005, ticked 0.873; 0.983, camera 1.073; 0.940, play 0.939; 0.989, navigation 0.854; 1.042, navigation first 0.662; 0.988

Diagnostic, format 8 (not judged), phase_b_forced / phase_a_nets; phase_a_nets / phase_a: pausepoint 1.111; 1.020, ticked 1.183; 1.021, camera 0.919; 1.017, play 0.943; 0.963, navigation 0.855; 1.015, navigation first 0.594; 0.907

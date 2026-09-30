| format | class | frames | phase_a complete = serialize + page + gpu (gpu min) | phase_b_forced complete = serialize + page + gpu (gpu min) | ratio (gpu min) | ≤ 1.25 | ratio, GPU part the wait for the device (no stamps) |
|---|---|---|---|---|---|---|---|
| 7 | pausepoint | 3 (3) | 1.27 = 0.14 + 0.01 + 1.12 (1.05) | 1.97 = 0.16 + 0.06 + 1.76 (1.56) | 1.553 (1.474) | **no** | 1.523 |
| 7 | camera | 3 (3) | 1.32 = 0.19 + 0.02 + 1.11 (1.04) | 2.46 = 0.26 + 0.32 + 1.87 (1.62) | 1.860 (1.758) | **no** | 2.246 |
| 7 | play | 36 (3) | 10.03 = 8.85 + 0.09 + 1.08 (1.02) | 5.91 = 1.84 + 0.65 + 3.32 (1.90) | 0.590 (0.450) | yes | 0.828 |
| 7 | navigation | 2 (2) | 4.37 = 3.20 + 0.10 + 1.07 (0.99) | 7.53 = 2.64 + 1.00 + 3.89 (2.48) | 1.721 (1.425) | **no** | 1.533 |
| 8 | pausepoint | 3 (3) | 0.14 = 0.14 + 0.00 + 0.00 (0.00) | 0.15 = 0.15 + 0.00 + 0.00 (0.00) | 1.109 (1.109) | yes | 1.109 |
| 8 | camera | 3 (3) | 1.33 = 0.20 + 0.02 + 1.11 (1.04) | 3.21 = 0.27 + 0.21 + 2.74 (1.71) | 2.424 (1.734) | **no** | 1.976 |
| 8 | play | 36 (3) | 10.00 = 8.82 + 0.09 + 1.08 (1.02) | 6.92 = 2.27 + 0.47 + 4.21 (2.39) | 0.691 (0.514) | yes | 0.657 |
| 8 | navigation | 2 (2) | 4.28 = 3.13 + 0.09 + 1.06 (0.99) | 6.95 = 2.63 + 0.97 + 3.35 (2.37) | 1.624 (1.418) | **no** | 1.714 |

Check, format 7 navigation first (not judged): 7.16 → 7.57 ms, 1.057

Check, format 8 navigation first (not judged): 7.32 → 7.21 ms, 0.985

Diagnostic, format 7 (not judged), phase_b_forced / phase_a_nets; phase_a_nets / phase_a: pausepoint 1.002; 1.551, camera 1.237; 1.504, play 1.107; 0.533, navigation 1.331; 1.293, navigation first 1.326; 0.797

Diagnostic, format 8 (not judged), phase_b_forced / phase_a_nets; phase_a_nets / phase_a: pausepoint 1.005; 1.103, camera 1.681; 1.442, play 1.074; 0.644, navigation 1.054; 1.541, navigation first 1.107; 0.890

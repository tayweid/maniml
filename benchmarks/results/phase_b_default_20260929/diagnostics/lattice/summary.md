| format | class | frames | phase_a complete = serialize + page + gpu (gpu min) | phase_b_forced complete = serialize + page + gpu (gpu min) | ratio (gpu min) | ≤ 1.25 | ratio, GPU part the wait for the device (no stamps) |
|---|---|---|---|---|---|---|---|
| 7 | pausepoint | 3 (3) | 2.01 = 0.54 + 0.01 + 1.45 (1.40) | 2.89 = 0.65 + 0.04 + 2.21 (1.86) | 1.438 (1.300) | **no** | 1.365 |
| 7 | camera | 3 (3) | 2.30 = 0.75 + 0.02 + 1.56 (1.38) | 3.58 = 1.22 + 0.20 + 2.13 (1.56) | 1.554 (1.405) | **no** | 1.529 |
| 7 | play | 36 (3) | 49.80 = 47.71 + 0.47 + 1.44 (1.33) | 23.65 = 13.24 + 1.93 + 8.44 (6.99) | 0.475 (0.444) | yes | 0.514 |
| 7 | navigation | 2 (2) | 18.88 = 17.04 + 0.46 + 1.38 (1.32) | 29.53 = 18.06 + 3.22 + 8.26 (7.98) | 1.564 (1.555) | **no** | 1.674 |
| 8 | pausepoint | 3 (3) | 0.54 = 0.54 + 0.00 + 0.00 (0.00) | 0.65 = 0.65 + 0.00 + 0.00 (0.00) | 1.192 (1.192) | yes | 1.192 |
| 8 | camera | 3 (3) | 2.24 = 0.76 + 0.02 + 1.46 (1.37) | 3.77 = 1.23 + 0.08 + 2.56 (2.02) | 1.686 (1.517) | **no** | 1.271 |
| 8 | play | 36 (3) | 49.94 = 47.91 + 0.48 + 1.42 (1.33) | 26.71 = 16.82 + 1.23 + 8.69 (6.73) | 0.535 (0.492) | yes | 0.530 |
| 8 | navigation | 2 (2) | 18.23 = 16.36 + 0.46 + 1.40 (1.32) | 29.06 = 18.11 + 3.36 + 7.59 (6.13) | 1.594 (1.521) | **no** | 1.711 |

Check, format 7 navigation first (not judged): 33.94 → 29.34 ms, 0.865

Check, format 8 navigation first (not judged): 33.80 → 28.52 ms, 0.844

Diagnostic, format 7 (not judged), phase_b_forced / phase_a_nets; phase_a_nets / phase_a: pausepoint 0.965; 1.490, camera 1.051; 1.479, play 0.860; 0.552, navigation 1.037; 1.509, navigation first 1.050; 0.824

Diagnostic, format 8 (not judged), phase_b_forced / phase_a_nets; phase_a_nets / phase_a: pausepoint 1.007; 1.184, camera 1.066; 1.581, play 0.968; 0.553, navigation 1.019; 1.564, navigation first 1.008; 0.838

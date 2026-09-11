# Reuse on thaw, 2026-09-11

`python benchmarks/live_profile.py 03_Code.py EpisodeA3 --renderer gpu --right-steps 8 --back-steps 4`
on a scratch copy of `econ-0100/Blocks/A3_Trade`, Apple M3, Python 3.13.9,
Phase A renderer. `before_a0a64f7a.json` is main before the change;
`after.json` is the commit that landed it (`DECISIONS.md`, "A step back
copies what changed").

| stage (ms) | before p50 | before max | after p50 | after max |
|---|---:|---:|---:|---:|
| checkpoint.restore_copy (DOWN, 5) | 58.9 | 146.6 | 8.5 | 22.8 |
| checkpoint.execution_copy (RIGHT after a step back, 3) | 36.2 | 65.4 | 7.0 | 22.7 |
| checkpoint.save_copy (49) | 6.4 | 77.4 | 6.3 | 78.9 |

The thaw counters after: 8,903 mobjects reused, 344 copied.

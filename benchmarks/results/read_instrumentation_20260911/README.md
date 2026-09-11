# Point-read profiles, 2026-09-11

Engine profiles (`MANIML_PERF_PATH`) behind
`docs/read_instrumentation_2026-09-11.md`. Machine: Apple M3, macOS 25.6,
Python 3.13.9; maniml at the commit that added the counters
(`DECISIONS.md`, "Point reads are counted by kind and phase"), scenes from
scratch copies of `econ-0100/Blocks/{B0_Markets,A2_Advantage,A3_Trade}` and
`ManimLive/dogfood/scene.py`.

- `reads_<scene>.json`: `python -m maniml 03_Code.py <Scene> --render`.
- `parked_B0_{3,13}s.json`: `python benchmarks/live_profile.py 03_Code.py EpisodeB0 --renderer gpu --right-steps 3 --continuous-seconds {3,13}`;
  the difference is 30 s parked on B02b with the PPF `always_redraw` live.

Tabulate with `python -m benchmarks.read_report <file>...`.

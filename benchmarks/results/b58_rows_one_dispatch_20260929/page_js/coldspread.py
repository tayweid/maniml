"""B5.8: a navigation's page JavaScript, the cold messages of recorded
browser_frames streams replayed by coldfresh.cjs (the driver behind
renderer_selection.js, one pass a fresh Node process, as browser_frames.cjs
plays a round, without its per-frame bookkeeping or a profiler), the
streams taking turns run by run. Prints each cold message's quartiles, the
p50 over the twelve of each run (as browser_frames reduces a round), and
the p50 and total of the per-message medians.

    python coldspread.py <tests/webgpu_fake_device.cjs> <runs> <stream dir>,<stream dir> [stderr]

stderr: "pipe" (the default, as browser_frames.py runs its harness: Node's
stderr a pipe) or "null" (/dev/null). The fix pass found PriceDiscovery's
checkpoint 130 reads 2.6 ms under rows in format 8 with a pipe and 1.0
with /dev/null, nothing being written to it (`pd_replay_stderr.txt`).
"""
import json
import os
import statistics
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
fake, n, streams = os.path.abspath(sys.argv[1]), int(sys.argv[2]), sys.argv[3].split(",")
stderr = {"pipe": subprocess.PIPE, "null": subprocess.DEVNULL}[sys.argv[4] if len(sys.argv) > 4 else "pipe"]
runs = {stream: [] for stream in streams}
for r in range(n):
    for stream in (streams if r % 2 == 0 else streams[::-1]):
        out = subprocess.run(["node", os.path.join(HERE, "coldfresh.cjs"), stream], stdout=subprocess.PIPE,
                             stderr=stderr, text=True, env={**os.environ, "FAKE": fake, "NOPROF": "1"},
                             check=True).stdout
        runs[stream].append(json.loads(out)["walls"])
quartiles = lambda xs: statistics.quantiles(xs, n=4)
for stream in streams:
    rs = runs[stream]
    checkpoints = sorted(rs[0], key=int)
    print(f"== {stream}")
    for c in checkpoints:
        xs = [r[c] for r in rs]
        a, m, b = quartiles(xs)
        print(f"   {c:>4}: q1 {a:6.2f}  median {m:6.2f}  q3 {b:6.2f}  min {min(xs):6.2f}")
    p50s = [statistics.median(r.values()) for r in rs]
    q = quartiles(p50s)
    print(f"   p50 over the 12, per run: median {statistics.median(p50s):.2f}  q1 {q[0]:.2f}  q3 {q[2]:.2f}")
    medians = [statistics.median([r[c] for r in rs]) for c in checkpoints]
    print(f"   p50 of the per-message medians {statistics.median(medians):.2f}; total of them {sum(medians):.2f}")

"""Tabulate point-read counters from MANIML_PERF_PATH profiles.

    python -m benchmarks.read_report profile_B0.json profile_A3.json ...

Prints, per profile, reads by kind (raw = the point array itself;
reduce = bounding box, centre, endpoint or tracker value) and phase
(play, updater, idle), then the calling sites that dominate each kind.
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

KINDS = ("raw", "reduce")
PHASES = ("play", "updater", "idle")


def report(path: Path, top: int = 8) -> str:
    counters = json.loads(path.read_text())["counters"]
    lines = [f"### {path.name}", "",
             "| reads | " + " | ".join(PHASES) + " | total |",
             "|---|" + "---:|" * (len(PHASES) + 1)]
    for kind in KINDS:
        row = [int(counters.get(f"reads.{kind}.{phase}", 0)) for phase in PHASES]
        lines.append(f"| {kind} | " + " | ".join(f"{n:,}" for n in row) + f" | {sum(row):,} |")
    lines.append("")
    for kind in KINDS:
        by_site = defaultdict(lambda: defaultdict(int))
        prefix = f"reads.site.{kind}."
        for key, value in counters.items():
            if key.startswith(prefix):
                phase, site = key[len(prefix):].split(".", 1)
                by_site[site][phase] += int(value)
        ranked = sorted(by_site.items(), key=lambda item: -sum(item[1].values()))[:top]
        if not ranked:
            continue
        lines.append(f"Top {kind} sites (play / updater / idle):")
        lines.append("")
        for site, phases in ranked:
            lines.append(f"- `{site}`: " + " / ".join(f"{phases.get(p, 0):,}" for p in PHASES))
        lines.append("")
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    for arg in argv:
        print(report(Path(arg)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

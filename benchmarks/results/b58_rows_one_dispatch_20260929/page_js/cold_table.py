"""Per-checkpoint cold page_ms of a browser_frames report, rows against records, both formats."""
import json, sys
r = json.load(open(sys.argv[1]))["variants"]
for suffix in ("", "_delta"):
    a = {x["checkpoint"]: x for x in r["phase_b_forced" + suffix]["rows"] if x.get("cold")}
    b = {x["checkpoint"]: x for x in r["phase_b_forced_records" + suffix]["rows"] if x.get("cold")}
    print("format", 8 if suffix else 7, "cp rows/records:", " ".join(f"{cp}:{a[cp]['page_ms']:.2f}/{b[cp]['page_ms']:.2f}" for cp in sorted(a)))
    print("   total", f"{sum(x['page_ms'] for x in a.values()):.2f}", f"{sum(x['page_ms'] for x in b.values()):.2f}")

"""test_point table report.json -> Phase B (rows, the selection) against
phase_b_records per class, format and measured checkpoint: each part's
median over the checkpoint's frames. argv: <table>/report.json."""
import json, sys
from collections import defaultdict
import numpy as np
r = json.load(open(sys.argv[1]))
st = r["stacks"]
cols = ("serialize_ms", "page_ms", "gpu_ms", "complete_ms", "wire_bytes")
for cls in ("pausepoint", "ticked", "play"):
    print("==", cls)
    for fmt in (7, 8):
        a = st.get(f"phase_b_f{fmt}", {}).get("classes", {}).get(cls)
        b = st.get(f"phase_b_records_f{fmt}", {}).get("classes", {}).get(cls)
        if not a: continue
        by = defaultdict(lambda: defaultdict(list))
        for name, entry in (("rows", a), ("records", b)):
            for f in entry["per_frame"]:
                for c in cols:
                    by[f["checkpoint"]][(name, c)].append(f[c])
        print(f"format {fmt}: checkpoint: records -> rows complete (serialize, page, gpu) wire KB")
        for cp in sorted(by):
            d = by[cp]
            m = {k: float(np.median(v)) for k, v in d.items()}
            print(f"  {cp:4d} n={len(d[('rows','complete_ms')]):3d} {m[('records','complete_ms')]:7.2f} -> {m[('rows','complete_ms')]:7.2f}"
                  f"  ser {m[('records','serialize_ms')]:6.2f}->{m[('rows','serialize_ms')]:6.2f}"
                  f"  page {m[('records','page_ms')]:5.2f}->{m[('rows','page_ms')]:5.2f}"
                  f"  gpu {m[('records','gpu_ms')]:5.2f}->{m[('rows','gpu_ms')]:5.2f}"
                  f"  wire {m[('records','wire_bytes')]/1024:7.1f}->{m[('rows','wire_bytes')]/1024:7.1f}")

"""browser_frames summary.json -> phase_b_forced (rows) against
phase_b_forced_records per class and format: the page's JavaScript, the
recording's serialize, the wire, the uploads and what the page created.
argv: <browser>/summary.json."""
import json, sys
s = json.load(open(sys.argv[1]))
keys = ("page_ms", "serialize_ms", "wire_bytes", "bytes_uploaded", "compute_dispatches", "bind_groups_created", "buffers_created")
for cls in ("pausepoint", "ticked", "play", "cold"):
    for base in ("phase_b_forced", "phase_b_forced_delta"):
        rec = s["variants"].get(base.replace("phase_b_forced", "phase_b_forced_records"), {}).get("classes", {}).get(cls)
        row = s["variants"].get(base, {}).get("classes", {}).get(cls)
        if not rec or not row:
            continue
        out = []
        for k in keys:
            if k in row and k in rec:
                a, b = rec[k]["p50"], row[k]["p50"]
                if k in ("wire_bytes", "bytes_uploaded"):
                    out.append(f"{k} {a/1024:.0f}->{b/1024:.0f}KB")
                elif k in ("page_ms", "serialize_ms"):
                    out.append(f"{k} {a:.2f}->{b:.2f} (n {row[k]['n']})")
                else:
                    out.append(f"{k} {a:.0f}->{b:.0f}")
        print(cls, base, "records->rows:", "; ".join(out))

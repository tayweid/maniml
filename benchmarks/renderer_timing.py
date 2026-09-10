"""Report readback-completion distributions without calling them GPU time."""

import numpy as np


COMPLETION_SCOPE = (
    "Submission through one-pixel readback includes GPU work, host waiting and "
    "mapping/polling latency; it is not a GPU timestamp. Minimum and fractions "
    "below 3 ms / above 10 ms expose possible timing modes without discarding "
    "slow samples or asserting their cause. Neither minimum nor median alone "
    "isolates GPU execution."
)


def completion_distribution(values):
    values = np.asarray(values, dtype=float)
    if not len(values):
        return {"samples": 0, "min_ms": None, "fraction_under_3_ms": None,
                "fraction_over_10_ms": None}
    return {"samples": len(values), "min_ms": float(values.min()),
            "fraction_under_3_ms": float((values < 3).mean()),
            "fraction_over_10_ms": float((values > 10).mean())}

"""CE API conformance: guards maniml's ManimCE-compatible surface.

ce_api_names.txt is the full CE public API (harvested from a CE
checkout by tests/ce_conformance/extract_ce_names.py); this test
asserts that every name in supported_names.txt — the subset maniml has
committed to providing — still exists, and reports overall coverage.

When compat is deliberately added or removed, regenerate the baseline:
    python -m tests.ce_conformance.update_baseline
"""
import unittest

from tests.ce_conformance.update_baseline import (
    compute_supported,
    load_ce_names,
)

from tests.ce_conformance import update_baseline as _baseline_module
import os

BASELINE_PATH = os.path.join(
    os.path.dirname(_baseline_module.__file__), "supported_names.txt")


def load_baseline() -> list[str]:
    with open(BASELINE_PATH) as f:
        return [line.strip() for line in f
                if line.strip() and not line.startswith("#")]


class TestCEConformance(unittest.TestCase):
    def test_no_supported_name_regressed(self):
        supported_now = set(compute_supported())
        baseline = load_baseline()
        missing = [n for n in baseline if n not in supported_now]
        self.assertEqual(
            missing, [],
            f"CE API names regressed (were supported, now missing): {missing}",
        )

    def test_report_coverage_and_baseline_freshness(self):
        supported_now = set(compute_supported())
        baseline = set(load_baseline())
        total = len(load_ce_names())
        print(f"\n[ce-conformance] {len(supported_now)}/{total} CE names "
              f"supported ({100 * len(supported_now) / total:.0f}%)")
        newly = sorted(supported_now - baseline)
        if newly:
            self.fail(
                "New CE names are now supported but not in the baseline "
                f"({newly[:10]}{'...' if len(newly) > 10 else ''}). Run: "
                "python -m tests.ce_conformance.update_baseline"
            )


if __name__ == "__main__":
    unittest.main()

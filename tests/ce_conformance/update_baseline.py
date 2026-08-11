"""Regenerate supported_names.txt: the subset of the CE API that maniml
currently provides. Run after deliberately adding or removing CE compat:

    python -m tests.ce_conformance.update_baseline
"""
import os
import sys

HERE = os.path.dirname(__file__)


def load_ce_names() -> list[str]:
    path = os.path.join(HERE, "ce_api_names.txt")
    with open(path) as f:
        return [line.strip() for line in f
                if line.strip() and not line.startswith("#")]


def compute_supported() -> list[str]:
    import manim
    return [name for name in load_ce_names() if hasattr(manim, name)]


def main() -> int:
    supported = compute_supported()
    total = len(load_ce_names())
    path = os.path.join(HERE, "supported_names.txt")
    with open(path, "w") as f:
        f.write("# CE API names maniml currently provides — the\n")
        f.write("# conformance test guards this set against regression.\n")
        f.write("# Regenerate with: python -m tests.ce_conformance.update_baseline\n")
        for name in supported:
            f.write(name + "\n")
    print(f"Wrote {len(supported)} supported names to {path} "
          f"({len(supported)}/{total} = {100 * len(supported) / total:.0f}% of the CE API)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

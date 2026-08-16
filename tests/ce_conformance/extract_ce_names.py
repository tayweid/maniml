"""Regenerate ce_api_names.txt from a ManimCE checkout.

Harvests every module-level `__all__` in CE's manim/ package via AST
(CE cannot be imported alongside maniml — both are named `manim`), and
writes the union as the reference API surface.

Usage:
    python -m tests.ce_conformance.extract_ce_names /path/to/manimce
"""

import argparse
import ast
import subprocess
import sys
from pathlib import Path

OUT = Path(__file__).with_name("ce_api_names.txt")


def extract_all_names(ce_root: str) -> set[str]:
    package_root = Path(ce_root) / "manim"
    names: set[str] = set()
    for path in package_root.rglob("*.py"):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError, UnicodeError):
            continue
        for node in tree.body:
            if not isinstance(node, ast.Assign):
                continue
            targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
            if "__all__" not in targets:
                continue
            if isinstance(node.value, (ast.List, ast.Tuple)):
                for element in node.value.elts:
                    if isinstance(element, ast.Constant) and isinstance(
                        element.value, str
                    ):
                        names.add(element.value)
    return names


def load_names(path: Path = OUT) -> set[str]:
    return {
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    }


def source_revision(ce_root: str) -> str:
    process = subprocess.run(
        ["git", "-C", ce_root, "rev-parse", "HEAD"],
        capture_output=True,
        check=False,
        text=True,
    )
    return process.stdout.strip() if process.returncode == 0 else "unknown"


def write_names(names: set[str], ce_root: str, path: Path = OUT) -> None:
    with path.open("w", encoding="utf-8") as stream:
        stream.write("# ManimCE public API names, harvested from per-module\n")
        stream.write("# __all__ declarations by extract_ce_names.py.\n")
        stream.write(f"# Source commit: {source_revision(ce_root)}\n")
        for name in sorted(names):
            stream.write(name + "\n")


def check_names(names: set[str], path: Path = OUT) -> bool:
    reference = load_names(path)
    added = sorted(names - reference)
    removed = sorted(reference - names)
    if not added and not removed:
        return True
    if added:
        print(f"ManimCE names added upstream: {added}")
    if removed:
        print(f"ManimCE names removed upstream: {removed}")
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ce_root", help="path to a ManimCE checkout")
    parser.add_argument(
        "--check",
        action="store_true",
        help="compare with the checked-in reference without writing it",
    )
    args = parser.parse_args()

    names = extract_all_names(args.ce_root)
    if not names:
        print(f"No __all__ entries found under {args.ce_root}/manim")
        return 1
    if args.check:
        if not check_names(names):
            return 1
        print(f"ManimCE API reference is current ({len(names)} names)")
        return 0

    write_names(names, args.ce_root)
    print(f"Wrote {len(names)} names to {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

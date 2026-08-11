"""Regenerate ce_api_names.txt from a ManimCE checkout.

Harvests every module-level `__all__` in CE's manim/ package via AST
(CE cannot be imported alongside maniml — both are named `manim`), and
writes the union as the reference API surface.

Usage:
    python -m tests.ce_conformance.extract_ce_names /path/to/manimce
"""
import ast
import os
import sys

OUT = os.path.join(os.path.dirname(__file__), "ce_api_names.txt")


def extract_all_names(ce_root: str) -> set[str]:
    package_root = os.path.join(ce_root, "manim")
    names: set[str] = set()
    for dirpath, _dirnames, filenames in os.walk(package_root):
        for filename in filenames:
            if not filename.endswith(".py"):
                continue
            path = os.path.join(dirpath, filename)
            try:
                tree = ast.parse(open(path, encoding="utf-8").read())
            except SyntaxError:
                continue
            for node in tree.body:
                if not isinstance(node, ast.Assign):
                    continue
                targets = [
                    t.id for t in node.targets if isinstance(t, ast.Name)
                ]
                if "__all__" not in targets:
                    continue
                if isinstance(node.value, (ast.List, ast.Tuple)):
                    for element in node.value.elts:
                        if isinstance(element, ast.Constant) and isinstance(element.value, str):
                            names.add(element.value)
    return names


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 1
    names = extract_all_names(sys.argv[1])
    if not names:
        print(f"No __all__ entries found under {sys.argv[1]}/manim")
        return 1
    with open(OUT, "w") as f:
        f.write("# ManimCE public API names, harvested from per-module\n")
        f.write("# __all__ declarations. Regenerate with extract_ce_names.py.\n")
        for name in sorted(names):
            f.write(name + "\n")
    print(f"Wrote {len(names)} names to {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

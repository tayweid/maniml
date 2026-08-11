"""AST-based mapping of a scene file's construct() body into animation units.

An *animation unit* is a run of consecutive top-level statements in
construct() ending with a statement that contains a ``.play(...)`` call.
Statements after the last play call form a trailing unit with
``has_play=False`` (e.g. a final ``self.wait()``).

The checkpoint system executes one unit at a time, so a play call inside
a for-loop or if-block re-executes with its full enclosing statement
instead of a truncated text snippet.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass


class SourceMapError(Exception):
    """Raised when a scene file cannot be mapped into animation units."""


@dataclass
class AnimationUnit:
    index: int        # 0-based position within construct()
    start_line: int   # 1-based first line of the unit's first statement
    end_line: int     # 1-based last line of the unit's last statement
    has_play: bool    # False only for a trailing unit with no play call
    source: str       # exec-ready source for this unit


def _contains_play(node: ast.AST) -> bool:
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute):
            if sub.func.attr == 'play':
                return True
    return False


def _find_construct(tree: ast.Module, scene_name: str | None) -> ast.FunctionDef:
    candidates = []
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        for item in node.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if item.name == 'construct':
                    candidates.append((node.name, item))
    for class_name, fn in candidates:
        if class_name == scene_name:
            return fn
    if scene_name is None and candidates:
        return candidates[0][1]
    if candidates:
        available = ', '.join(name for name, _ in candidates)
        raise SourceMapError(
            f"No construct() found for scene '{scene_name}' "
            f"(classes with construct: {available})"
        )
    raise SourceMapError("No class with a construct() method found")


def _unit_source(lines: list[str], start_line: int, end_line: int) -> str:
    """Build exec-ready source for a line range of construct()'s body.

    The block keeps its original indentation and is wrapped in
    ``if True:`` so it compiles at column zero. This avoids dedent
    pitfalls with multi-line strings that are indented less than the
    surrounding code.
    """
    block = '\n'.join(lines[start_line - 1:end_line])
    return 'if True:\n' + block


def build_units(source: str, scene_name: str | None = None) -> list[AnimationUnit]:
    """Map a scene file's construct() body into animation units.

    Raises SourceMapError if the file has no matching construct(), and
    propagates SyntaxError if the file doesn't parse.
    """
    tree = ast.parse(source)
    construct = _find_construct(tree, scene_name)
    lines = source.splitlines()

    units: list[AnimationUnit] = []
    pending_start: int | None = None
    for stmt in construct.body:
        if pending_start is None:
            pending_start = stmt.lineno
        if _contains_play(stmt):
            units.append(AnimationUnit(
                index=len(units),
                start_line=pending_start,
                end_line=stmt.end_lineno,
                has_play=True,
                source=_unit_source(lines, pending_start, stmt.end_lineno),
            ))
            pending_start = None

    if pending_start is not None:
        end = construct.body[-1].end_lineno
        units.append(AnimationUnit(
            index=len(units),
            start_line=pending_start,
            end_line=end,
            has_play=False,
            source=_unit_source(lines, pending_start, end),
        ))
    return units


def next_play_unit(
    units: list[AnimationUnit],
    after_unit_index: int | None = None,
    after_line: int | None = None,
) -> AnimationUnit | None:
    """Find the next unit containing a play call.

    Prefers unit-index anchoring (robust to line shifts); falls back to
    line-number anchoring for checkpoints created before a source map
    existed.
    """
    for unit in units:
        if not unit.has_play:
            continue
        if after_unit_index is not None:
            if unit.index > after_unit_index:
                return unit
        elif after_line is None or unit.end_line > after_line:
            return unit
    return None


def unit_for_line(units: list[AnimationUnit], line: int) -> AnimationUnit | None:
    """Return the unit whose line range contains the given line."""
    for unit in units:
        if unit.start_line <= line <= unit.end_line:
            return unit
    return None

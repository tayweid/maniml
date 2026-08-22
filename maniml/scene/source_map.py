"""AST-based mapping of a scene file's construct() body into animation units.

An *animation unit* is a run of consecutive top-level statements in
construct() ending with a *boundary statement*: one containing a call
that saves a checkpoint. Every ``.play(...)`` is a boundary — each play
saves a full checkpoint, which is what makes per-play navigation and
reverse morphing work. In a *pause-anchored* file (one that calls
``self.pause()`` or CE's ``self.next_section()`` anywhere — see
``pause_anchored``) pause statements are boundaries too, and their units
carry ``is_pause=True``: a pause's checkpoint is a *pausepoint*, the
authored stop that RIGHT/LEFT and a presentation move between, while the
play checkpoints between pauses are interior states that run through.
Statements after the last boundary form a trailing unit with
``has_stop=False`` (e.g. a final ``self.wait()``).

The checkpoint system executes one unit at a time, so a boundary call
inside a for-loop or if-block re-executes with its full enclosing
statement instead of a truncated text snippet.
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
    has_stop: bool    # False only for a trailing unit with no boundary call
    source: str       # exec-ready source for this unit
    stops: int = 1    # boundary calls written in the unit's source
    loops: bool = False   # at least one of them sits inside a loop
    is_pause: bool = False  # the boundary is a pause: its checkpoint is a pausepoint

    @property
    def indeterminate(self) -> bool:
        """Whether the unit's pausepoint count is knowable before it runs.

        A loop's trip count usually isn't known statically, and only one arm
        of an if/else runs, so in both cases the written stop calls are not a
        count of the checkpoints the unit will produce. A viewer's timeline
        can say so instead of drawing a number it made up.
        """
        return self.loops or self.stops > 1


def _is_pause_call(node: ast.AST) -> bool:
    """Whether this node is a ``self.pause()`` / ``self.next_section()`` call.

    Pauses must be spelled on ``self`` so that a scene about, say, a media
    player calling ``player.pause()`` cannot silently flip the whole file
    into pause-anchored mode.
    """
    if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
        return False
    func = node.func
    return (func.attr in ('pause', 'next_section')
            and isinstance(func.value, ast.Name) and func.value.id == 'self')


def _is_stop_call(node: ast.AST, pause_mode: bool) -> bool:
    """Whether this node is a call that saves a checkpoint.

    Every ``.play(...)`` is one — the loose attribute match it has always
    had; a false positive costs one extra unit boundary, nothing more. In
    pause-anchored mode pauses are checkpoint boundaries too.
    """
    if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
        return False
    if node.func.attr == 'play':
        return True
    return pause_mode and _is_pause_call(node)


def _count_stops(node: ast.AST, pause_mode: bool) -> int:
    """Stop calls that *run* when this statement executes.

    A stop written inside a nested ``def``/``lambda`` does not fire at
    definition time -- it fires wherever the helper is later called -- so it
    must not make the ``def`` statement a unit boundary. (Otherwise the def
    becomes a unit that saves no checkpoint, and the stepper stalls.)
    """
    count = 0
    stack = [node]
    while stack:
        sub = stack.pop()
        if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue   # the statement itself may be the def: nothing in it runs now
        if _is_stop_call(sub, pause_mode):
            count += 1
        stack.extend(ast.iter_child_nodes(sub))
    return count


def _stop_in_loop(node: ast.AST, pause_mode: bool) -> bool:
    """Whether any stop call in this statement sits inside a loop.

    ``ast.walk`` yields the statement itself, so a ``for`` loop that is the
    unit's whole statement is caught along with nested ones.
    """
    return any(
        isinstance(sub, (ast.For, ast.AsyncFor, ast.While))
        and _count_stops(sub, pause_mode) > 0
        for sub in ast.walk(node)
    )


def _tree_uses_pauses(tree: ast.Module) -> bool:
    """Whether the file calls self.pause()/self.next_section() anywhere.

    The whole module is scanned, not just construct(): a pause inside a
    helper fires at runtime all the same, and must put the file in
    pause-anchored mode even though it adds no unit boundary.
    """
    return any(_is_pause_call(node) for node in ast.walk(tree))


def _count_pauses(node: ast.AST) -> int:
    """Pause calls that run when this statement executes (def/lambda
    bodies excluded, same as _count_stops)."""
    count = 0
    stack = [node]
    while stack:
        sub = stack.pop()
        if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue
        if _is_pause_call(sub):
            count += 1
        stack.extend(ast.iter_child_nodes(sub))
    return count


def pause_anchored(source: str) -> bool:
    """Whether this scene source authors its own pausepoints.

    Propagates SyntaxError if the file doesn't parse, the same way
    build_units does.
    """
    return _tree_uses_pauses(ast.parse(source))


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

    Blank lines above the wrapper put the block back at the line number it
    has in the file. The unit is compiled with the real filename, so without
    them a traceback reports a line counted from the top of the *unit* while
    Python reads the source at that line from the *file* — and blames some
    unrelated statement near the top of it, usually an import.
    """
    block = '\n'.join(lines[start_line - 1:end_line])
    # The wrapper takes the line above the block; the padding takes the rest.
    lead = '\n' * (start_line - 2) if start_line >= 2 else ''
    return lead + 'if True:\n' + block


def build_units(source: str, scene_name: str | None = None) -> list[AnimationUnit]:
    """Map a scene file's construct() body into animation units.

    Raises SourceMapError if the file has no matching construct(), and
    propagates SyntaxError if the file doesn't parse.
    """
    tree = ast.parse(source)
    pause_mode = _tree_uses_pauses(tree)
    construct = _find_construct(tree, scene_name)
    lines = source.splitlines()

    units: list[AnimationUnit] = []
    pending_start: int | None = None
    for stmt in construct.body:
        if pending_start is None:
            pending_start = stmt.lineno
        stops = _count_stops(stmt, pause_mode)
        if stops:
            units.append(AnimationUnit(
                index=len(units),
                start_line=pending_start,
                end_line=stmt.end_lineno,
                has_stop=True,
                source=_unit_source(lines, pending_start, stmt.end_lineno),
                stops=stops,
                loops=_stop_in_loop(stmt, pause_mode),
                is_pause=pause_mode and _count_pauses(stmt) > 0,
            ))
            pending_start = None

    if pending_start is not None:
        end = construct.body[-1].end_lineno
        units.append(AnimationUnit(
            index=len(units),
            start_line=pending_start,
            end_line=end,
            has_stop=False,
            source=_unit_source(lines, pending_start, end),
            stops=0,
        ))
    return units


def chip_unit_for(unit_index, units, pause_anchored_mode) -> int | None:
    """Map a checkpoint's source unit to the chip that stands for it.

    Plain files: the unit itself (every checkpoint is a stop). In a
    pause-anchored file a chip is a *pausepoint*, so a play checkpoint maps
    forward to the pause unit that ends its stretch; plays after the last
    pause keep their own unit. Checkpoint 0 (unit -1) is always its own
    Start chip. Shared by the live rail (WebViewer) and the present bundle
    so the two always agree.
    """
    if unit_index is None or unit_index < 0:
        return unit_index
    if not pause_anchored_mode:
        return unit_index
    for unit in units or []:
        if unit.index >= unit_index and unit.is_pause:
            return unit.index
    return unit_index


def next_stop_unit(
    units: list[AnimationUnit],
    after_unit_index: int | None = None,
    after_line: int | None = None,
) -> AnimationUnit | None:
    """Find the next unit containing a stop call.

    Prefers unit-index anchoring (robust to line shifts); falls back to
    line-number anchoring for checkpoints created before a source map
    existed.
    """
    for unit in units:
        if not unit.has_stop:
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

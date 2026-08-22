# Plan: inlining `self.helper()` calls in the source map (not implemented)

Status: reference only, 2026-08-22. Decided against for now — maniml's target
is the flat `construct()` most manim is written in, and the flat form works
(with the two small fixes in `5c136fc2`'s successor commit: nested-def plays
don't cut units; a unit that saves no checkpoint gets one anyway). This note
records how delegation-style scenes could be supported if wanted later.

## Problem

A scene written as

```python
def construct(self):
    self.b01_title()
    self.b02_unemployment()
    ...
def b01_title(self): ...self.play(...)
```

maps to ONE unit: `build_units` cuts units at top-level statements of
`construct()` containing `.play(`, and `self.b01_title()` contains none. The
plays inside the methods still save checkpoints (UP/DOWN work), but RIGHT
re-executes "the next unit" = the whole scene, and an edit inside a helper is
"outside construct()" → full rebuild instead of replay.

## Design

1. **Inline argument-less helper calls.** In `build_units`, when a construct
   statement is `ast.Expr(ast.Call(func=Attribute(Name('self'), name)))` with
   no args/kwargs, `name` is a method of the same class taking only `self`,
   and its body contains a play: descend into the method body and map its
   statements as if written in construct (recursive, cycle guard via a
   name stack, depth cap ~8). Other calls stay opaque.

2. **Segments.** A unit may now span two line ranges (the tail statements
   after a helper's last play + the next helper's opening statements). Add
   `Segment(start, end, owner, owner_start, owner_end)` and
   `AnimationUnit.segments`. Statements from the same body extend the last
   segment; a body change starts a new one.

3. **Source.** `_unit_source(lines, segments)` emits one `if True:` block per
   segment. Pad with blank lines so each segment lands at its file line
   numbers where possible (tracebacks stay honest); a segment above the
   previous one in the file (helper defined before its caller) cannot be
   padded and follows directly.

4. **Exec semantics.** Units already exec at namespace level with `self`
   injected, so helper locals become namespace entries exactly as construct
   locals do, and `self.attr` state carries over. `_capture_caller_namespace`
   needs no change (it walks up to the frame with `__animation_line_number__`).

5. **Watcher.** Replace the contiguous-range check
   (`units[0].start_line <= line <= units[-1].end_line`) and
   `next(u for u in units if u.end_line >= line)` with a segment-aware
   `affected_unit(units, line)`: containment first; else, if the line lies in
   a def that owns segments, the first unit with a segment of that owner at
   or after the line; else None → rebuild (edits to construct's dispatcher
   lines, reordering calls, count as rebuild — the safe answer).
   `unit_for_line` → `unit.contains_line(line)`.

6. **Viewer.** Timeline entries use `u.start_line`; unchanged.

## Sketch

```python
def _inlinable_call(stmt, methods, stack):
    if not (isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call)): return None
    call = stmt.value
    if call.args or call.keywords: return None
    fn = call.func
    if not (isinstance(fn, ast.Attribute) and isinstance(fn.value, ast.Name) and fn.value.id == 'self'): return None
    m = methods.get(fn.attr)
    if m is None or fn.attr in stack or fn.attr == 'construct': return None
    a = m.args
    if len(a.args) != 1 or a.vararg or a.kwonlyargs or a.kwarg or a.posonlyargs: return None
    return m if _contains_play(m) else None

def _flatten(body, owner, methods, stack, depth=0):
    for stmt in body:
        m = _inlinable_call(stmt, methods, stack) if depth < 8 else None
        if m: yield from _flatten(m.body, m, methods, stack + (m.name,), depth + 1)
        else: yield stmt, owner
```

`build_units` then iterates `_flatten(construct.body, construct, methods, ('construct',))`,
growing `pending: list[Segment]` and flushing a unit at each statement whose
`_count_plays` > 0; trailing pending becomes the `has_play=False` tail.

## Caveats

- Helper locals leak into the shared namespace (same as construct locals);
  two helpers both naming `V` share it. Fine for scenes, a semantics change
  from real calls.
- Helpers with parameters are not inlined; they stay opaque calls inside a
  unit — the plays inside them fire from the call site like any closure.
- Tests: add a delegation scene to `tests/test_source_map.py` (units == plays;
  multi-segment unit between helpers; helper defined before construct).

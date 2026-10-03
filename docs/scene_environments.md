# Scene environments: the header, uv, and the layer

Shipped 2026-10-02. Taylor, from a screenshot of ManimLive.app refusing
`dogfood/scene.py` for want of seaborn, with the engine's old hint pointing
at a pip the app's environment does not have: "id like it to create a uv
environment for these with version pins like knuth and then to install
these things with uv if not available." Knuth's model (its
`ENVIRONMENT.md`) is the one followed, so a scene file and a Knuth document
carry their environment the same way, and one rule governs installs in
both apps.

## What a scene file carries

A PEP 723 inline-metadata header, the format `uv init --script` writes:

```python
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "seaborn==0.13.2",
# ]
#
# [tool.uv]
# exclude-newer = "2026-10-02T15:41:07Z"
# ///

from manim import *
```

The packages the scene imports are pinned exactly (`uv add --script
--bounds exact`); everything underneath is held by the date stamp, which
the resolver treats as the end of time. No lock file, nothing beside the
file. It is comments, so ManimCE, bare Python and `maniml scene.py` on a
machine without uv read past it. A file without a header is a file as
before; nothing is written until a package is added. The floor is
maniml's own (`environment.REQUIRES_PYTHON`, held to `pyproject.toml` by
`tests/test_environment.py`), not the engine's minor version as Knuth
writes: the scene runs on the engine's interpreter whatever the header
says, and a header written beside a 3.14 checkout must still build for the
app's 3.13.

## How a scene runs with it

`maniml/environment.py`, standard library only. The scene loader
(`__main__.load_scene_module`, which every load and reload goes through)
calls `activate(path)` before the file's imports run: when the file has a
header, `uv sync --script <file> --python <the engine's interpreter>`
builds the environment in uv's store (`~/.cache/uv/environments-v2/`),
`uv python find --script` names it, and its site-packages goes first on
`sys.path`. The header's packages come from there; maniml and its own
dependencies come from the engine as before. A reload with the same header
costs one file read; a changed header syncs again; a removed header drops
the path.

**Layered, not run inside.** Knuth starts its kernel *on* the document's
interpreter, with a shim exposing only the `knuth` package, because the
kernel is standard library. maniml is not: numpy, wgpu, manimpango and
the compiled Lyon helper would have to be in every scene's environment,
built for its Python, and a scene file could not then be opened by an
app without rebuilding them. Layering keeps one maniml per machine, and a
file without a header costs nothing. The cost is that a header's
packages win over the engine's on a conflict (a header pinning an older
numpy runs maniml on it); by design, the header is the truth, and the
engine's pins are a range.

The app (`web/app.py`, `_start`) syncs the environment itself before it
starts the scene process, with uv's steps shown on the landing page:
a first build can take minutes, and a scene's start-up wait is 25
seconds. The scene process's own sync is then an audit.

## A missing import

A scene that dies on `ModuleNotFoundError` (the app reads the scene's
output; `environment.missing_module`) gets the import's distribution
(`DISTRIBUTIONS` maps the names that differ: `cv2` is opencv-python)
added to its header and environment, and is started again in the same
request. Knuth's rule (Taylor, 2026-09-27): **a package uv already has
on this Mac goes in at once, with no question; only a download asks.**
`uv add --offline` is the first try; when its failure is "not found in
the cache", the landing page shows a Download button, whose click is the
`install` op: the same add with the network, then the scene. The header's
date moves to now before an add, so the new package comes at its newest;
everything already listed is pinned, so nothing else moves. A failure
leaves the file as it was, header and date included. A package added and
still not importable (`import pillow`) stops with the import name the
hint knows (`import_name_hint`), rather than looping; at most five
packages are added per open.

In a terminal, the traceback is followed by the one command that does the
same: `uv add --script scene.py --bounds exact seaborn`.

## A missing import on a reload

The same rule inside a running scene. An `import` added to an open file
is an edit outside `construct()`, so the watcher's reload rebuilds from
the module (`checkpoints._restart_from_source`); its loader call is now
`_reload_module`, which on a `ModuleNotFoundError` adds the package from
uv's cache, tells the watcher of the header write (`FileWatcher.sync`, so
the add is not also an edit to reload for), and loads again, with the
checkpoints rebuilt and the scene back on the unit it was on. When the
package would have to be downloaded, the failure is left in
`scene._load_error` (message, hint, module, distribution, `download`),
which the viewer's state carries as `load_error`; the page shows it in a
box like the render-error box, with a Download button when the engine
declares the `install` capability. The click sends `install` over the
scene's own socket (the app's relay passes it through); the engine runs
the add with the network, broadcasting uv's steps as `install_progress`,
and reloads; the state after clears the box or rewrites it with why not.
Only the offered name is accepted (`install_missing` checks it against
`_load_error`). In a terminal the same reload prints the `uv add
--script` line. Not covered: a scene switch or a bare-process Restart
that fails on the import (`__main__._run_web_scenes`) keeps the code that
last loaded and says so on the console only, until the window closes:
closing ends the session (DECISIONS.md, "A scene's session ends with its
windows"), and the next open starts fresh.

## Not done

- Packages that arrive with others (`import pandas` beside seaborn) are
  not declared in the header after a clean run, as Knuth's
  `declare_imports` does. They are held by the date stamp, not pinned.
- Nothing constrains the header's resolution to the engine's pins (see
  "Layered, not run inside").

## Tests

`tests/test_environment.py`: the header (creation, parsing, pins, the
floor held to pyproject), the missing-import reading, and, with uv on
the machine, a header with no packages built on this interpreter and
layered on `sys.path`, an offline add of an unknown package offering a
download, and the refusal of anything but a package name.
`tests/test_app.py`: the download offer end to end (and the `install`
op's refusal of a package that is nowhere), and a package uv holds
(colorama, put in the cache by `tests/uv_fixtures.py`) added to a scene's
header and the scene started in the same request, its process importing
the package from the layered environment; then the same two through a
running scene, the import written into the open file and the page's
state showing the rebuilt checkpoints, or the offer and the answer to
its `install` message. `tests/test_checkpoint_reload.py`: the reload's
recovery and its refusal headlessly, with the scene's state untouched.

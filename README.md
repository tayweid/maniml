# ManimLive

ManimLive speeds up Manim's animation workflow by bringing hot reloading and interactive navigation on top of ManimGL's OpenGL renderer, targeting compatibility with the current ManimCE API.

## Features

- **ManimCE API compatibility (growing)**: *targets the current ManimCE API; coverage is tracked by a conformance test (`tests/ce_conformance/`) and unsupported settings warn rather than fail silently*
- **Live preview:** *real-time rendering in a native window (`maniml scene.py`) or the browser (`--web`)*
- **The app:** *`maniml app` serves a local page listing your scene files; each opens in the browser viewer*
- **Keyboard navigation:** *arrow keys navigate through the animations, built on dynamic checkpointing; a clickable checkpoint timeline in the browser*
- **Hot reloading:** *the preview automatically plays edited animations*
- **Client-side rendering (experimental):** *the browser viewer can render scenes with its own GPU via WebGL2 or WebGPU, pixel-faithful to the native renderer*

## Installation

ManimLive supports Python 3.11 through 3.14, matching current ManimCE's
supported range. The current developer preview supports macOS. Windows and
Linux support is intentionally deferred until the WebGPU renderer transition
and cross-platform desktop packaging are complete.

```bash
python -m pip install --upgrade --force-reinstall --no-cache-dir "maniml @ git+https://github.com/tayweid/maniml.git"
```

Or install from source, for development:

```bash
git clone https://github.com/tayweid/maniml.git
cd maniml
pip install -e .
```

An editable install makes the `maniml` command run your working tree, so an
edit takes effect the next time you run a scene. Note that the install command
above is **not** idempotent with it: `--force-reinstall` replaces the editable
link with a copy under `site-packages`, and from then on your edits are
silently ignored until you push and reinstall. If you develop ManimLive, run
that command only when you mean to test the end-user setup path, and restore
the editable install afterwards with `pip install -e . --no-deps`.

## Usage

Use exactly like ManimCE:

```python
from maniml import *

class Example(Scene):
    def construct(self):
        circle = Circle()
        self.play(Create(circle))
        self.wait()
```

Run with:
```bash
maniml example.py Example
```

Existing ManimCE scene files run unmodified: under the `maniml`
command, `from manim import *` resolves to maniml (the alias is local
to the maniml process, so a real ManimCE install on the same machine
is unaffected).

## The app

`maniml app [dir]` starts a local server and opens a page listing the scene
files under `dir`. Clicking a scene runs it as its own subprocess and opens the
browser viewer; **Open…** asks the engine for the platform's native file dialog,
so a scene anywhere on disk opens by its real path.

Interface and engine ship together in this package and are served from the same
local origin — one port for the page and its socket alike — so there is nothing
to deploy, nothing to pair, no address to configure, and no way for the page to
be out of step with the engine that answers it.

### Background engine (macOS)

Registering the engine as a login agent keeps `http://localhost:8685` up without
a terminal:

```bash
python -m maniml agent install ~/Projects   # scenes live under this directory
python -m maniml agent open                 # open the app
```

`maniml agent status`, `restart`, `uninstall` manage the job; the log is
`~/Library/Logs/maniml-agent.log`. The address carries nothing secret, so it
is worth bookmarking: it keeps working across restarts and logins.

The agent holds the default port for the whole login session. A foreground
`maniml app` started alongside it binds an OS-assigned port instead and opens
the page on *that* address, so both remain usable.

## Interactive controls

In the preview window:

- **RIGHT arrow** — run the next animation (re-executed from source)
- **LEFT arrow** — reverse to the previous checkpoint (animated)
- **UP / DOWN arrows** — jump between checkpoints instantly
- **Save the scene file** — the watcher replays only the edited animations
- **Click a mobject** — prints its variable name; drag to move it, and a
  paste-ready `name.move_to([x, y, z])` prints on release
- `--present` — pre-runs the whole scene and adds a clickable checkpoint
  timeline at the bottom edge of the window
- `--render` — headless: writes an MP4 plus a PNG per checkpoint

The browser viewer exposes the same reverse/forward behavior in its top
transport slug and shows the whole scene as a clickable pausepoint timeline
along the bottom. Its export menu can save the current frame, render the scene
to video, or bake the self-contained web player; video and web exports run in
a separate process so the live preview does not lose its current state.

## How it works

The scene file is parsed into **animation units** (runs of statements
ending in a `play()` call). Each `play()` saves a checkpoint holding a
deep copy of the scene state *and* the construct namespace together, so
variable-to-mobject references survive navigation. RIGHT re-executes the
next unit's source in the restored namespace; UP/DOWN restore stored
checkpoints; the file watcher re-anchors checkpoints against the edited
source and replays only what changed.

## OpenGL Backend and 3D Scenes

All mobjects live in 3D; 2D scenes are simply viewed with a flat camera
at z=0, and `z_index` (CE-compatible) orders overlapping draws. In
`ThreeDScene`, filled shapes render as triangulated meshes with real
depth, so intersections between filled mobjects and surfaces are
per-pixel correct.

## Status

Work in progress but tested: the checkpoint system, the CE
compatibility surface (tracked by `tests/ce_conformance/`), and the
interactive loop (windowed tests in `tests/interactive/`) all have
regression suites.

## Security

Scene files are Python programs and run with your user account's privileges.
Only run scenes you trust. Everything ManimLive serves is bound to loopback,
and each server serves its page and accepts its WebSocket on one port, so it
can require its own exact browser Origin — which a website cannot forge, at any
port it might guess. It does not defend against another program running as you,
which could equally well run Python itself. By default, `maniml app DIR`
launches scenes only from `DIR`; a file chosen through the native dialog grants
access to that file alone. See [SECURITY.md](SECURITY.md) for the trust model
and vulnerability reporting guidance.

Contributions are welcome; see [CONTRIBUTING.md](CONTRIBUTING.md) for the
development setup and ManimCE compatibility process.

## Project lineage

ManimLive is an independent project built from 3Blue1Brown's ManimGL lineage
and code adapted from ManimCommunity's Manim. It is not an official
ManimCommunity project. Both upstream MIT notices are retained in `LICENSE` and
`LICENSE.community` and are included in release artifacts.

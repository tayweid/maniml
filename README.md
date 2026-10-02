# ManimLive

ManimLive speeds up Manim's animation workflow by bringing hot reloading and interactive navigation with a shared WebGPU renderer, targeting compatibility with the current ManimCE API.

## Features

- **ManimCE API compatibility (growing)**: *targets the current ManimCE API; coverage is tracked by a conformance test (`tests/ce_conformance/`) and unsupported settings warn rather than fail silently*
- **Live preview:** *real-time rendering in the browser (`maniml scene.py`), drawn by your GPU with WebGPU*
- **The app:** *`maniml app` serves a local page listing your scene files; each opens in the browser viewer*
- **Keyboard navigation:** *arrow keys navigate through the animations, built on dynamic checkpointing; a clickable checkpoint timeline in the browser*
- **Hot reloading:** *the preview automatically plays edited animations*
- **Client-side rendering:** *the browser viewer renders scenes with its own GPU via WebGPU, pixel-faithful to the native renderer*

## Installation

ManimLive supports Python 3.11 through 3.14, matching current ManimCE's
supported range. The current developer preview supports macOS. Windows and
Linux support is intentionally deferred until the WebGPU renderer transition
and cross-platform desktop packaging are complete.

ManimLive is used through its app (below): on a Mac with Apple silicon, one
line in Terminal installs ManimLive.app into Applications, and running it
again updates it (the app also updates itself from the site):

```bash
curl -fsSL https://maniml.tayweid.io/install | bash
```

or the download at [maniml.tayweid.io](https://maniml.tayweid.io). The app
installs a Python of its own with [uv](https://docs.astral.sh/uv/) on first
launch and never touches a Python already on the machine. Everything here
goes through uv; there is no pip step and nothing from Homebrew.

Installing from source builds a small Rust helper for vector-fill meshes.
Install the Rust toolchain through [rustup](https://rustup.rs/) and Apple's
Command Line Tools (`xcode-select --install`) first. The tested toolchain is
Rust 1.97.0; `cargo` must be on your `PATH`. The build uses the checked-in
Cargo lockfile and may download its pinned dependencies. The app's bundle
carries this helper prebuilt, so the app needs no Rust toolchain; importing
ManimLive or rendering a scene never compiles it.

Phase A is the default for the browser, movie rendering and checkpoint
images. The viewer's **Scene renderer** menu also offers **Original 2D**, so
you can compare the old winding renderer at the same checkpoint while
dogfooding. This choice affects the live viewer; exports use Phase A.
See the [renderer contract and validation](docs/unified_triangle_renderer_phase_a.md).

From a checkout, for development:

```bash
git clone https://github.com/tayweid/maniml.git
cd maniml
uv sync --extra gl
```

`uv sync` creates `.venv` with a Python uv manages, builds the helper, and
installs ManimLive editable with its development group, so an edit takes
effect the next time you run a scene (`uv run python -m maniml scene.py
Demo`). The `gl` extra adds moderngl and PyOpenGL for the reference GL
camera and the frozen GL references under `tests/`; the app never needs
them. To try ManimLive in some other environment, `uv pip install
"maniml @ git+https://github.com/tayweid/maniml.git"` into it.

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

### ManimLive.app (macOS)

The app is how to use ManimLive without a terminal: the landing page and the
viewer in a window of their own, on the Claerbout shell (Electron; one shell
for Knuth, Plass and ManimLive, built from `app/maniml.json`). On its first
launch the app installs a Python of its own with uv and the engine's packages
at the versions `app/engine-requirements.txt` pins; nothing already on the
machine is used or changed. The engine runs as the app's child, on a port of
its own, and stops with the app; its output goes to
`~/Library/Logs/ManimLive.log`. A scene double-clicked in Finder, or chosen
with Open…, opens in its own window. Scenes needing LaTeX or ffmpeg use the
ones installed on the computer. From a checkout:

```bash
npm install && npm run app:build
```

puts `ManimLive.app` in Applications; `npm run app` runs the shell on the
checkout instead, and `npm run app:smoke` launches it on a scene in a
throwaway folder and checks it. An installed app updates itself: it
checks its site after launch, and the landing page's Update button (or
ManimLive menu → Check for Updates…) downloads the new build, swaps it in
and relaunches. How the port was made is in
`docs/claerbout_experiment.md`.

## Interactive controls

In the browser viewer:

- **RIGHT arrow** — run the next animation (re-executed from source)
- **LEFT arrow** — jump to the previous checkpoint
- **UP / DOWN arrows** — jump between checkpoints instantly
- **Home** (or Start, first on the bottom bar) — jump to the start, the
  timeline kept: RIGHT then replays what was built
- **Restart** (toolbar) — the scene as if just opened: a new scene process
  under ManimLive.app, a fresh instance of the scene from a terminal, at
  the start with no history
- **Save the scene file** — the watcher replays only the edited animations
- **Click a mobject** — prints its variable name; drag to move it, and a
  paste-ready `name.move_to([x, y, z])` prints on release. In a
  `ThreeDScene` a plain drag orbits the camera instead (shift-drag pans,
  alt-press grabs)
- **`mobject.set_draggable()`** — a handle the pointer may move in a
  presentation too, named in a chip on hover; `along=` keeps it on a
  curve or a line, `on_drag=` reports each move (set a `ValueTracker`
  there). Updaters that read the handle follow it. Drags are never saved
- `--present` — pre-runs the whole scene; the rail at the bottom of the
  viewer is the clickable checkpoint timeline. Present then
  uses a fresh MP4 for smooth forward and reverse motion and restores the
  live engine at the recorded endpoint on exit. Entering Present explicitly
  renders the cache if it is missing or stale; ordinary live viewing does
  not write video or image files.
- `--render` — headless: writes an MP4
- `--export-checkpoints` — headless: writes a PNG per checkpoint, and
  nothing else. Its own export (and its own button beside Download in
  the viewer) because the stills outweigh everything else a render
  writes — render them when you want them, don't carry them in a repo
- `--export` — headless: bakes the scene into a self-contained web player
  (a static folder that scrubs and plays with no Python anywhere)

The viewer's **Console** button (or `C`) opens a panel showing everything the
scene prints, including tracebacks — the only place that output is visible when
a scene runs under `maniml app`. It never opens by itself, and full screen (`F`)
hides it along with the rest of the chrome.

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

## Shared renderer and 3D scenes

Source mobjects live in 3D. Ordinary scenes use painter order; `ThreeDScene`
uses depth-tested triangles. Both use the same WebGPU shaders, with 4× MSAA
at twice the final resolution and a shared downsample. Python still updates
points and generates fill meshes on the CPU; moving that work onto the GPU
is Phase B. A nonplanar filled outline needs a defined `Surface` or
`VMobject3D`, since a closed 3D contour alone has no unique interior.

## Status

Work in progress but tested: the checkpoint system, the CE
compatibility surface (tracked by `tests/ce_conformance/`), and the
interactive loop (driven headlessly in `tests/test_checkpoint_reload.py`
and end-to-end in `tests/test_web_viewer.py`) all have regression suites.

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

Development setup and the ManimCE compatibility process are in
[CONTRIBUTING.md](CONTRIBUTING.md).

## Project lineage

ManimLive is an independent project built from 3Blue1Brown's ManimGL lineage
and code adapted from ManimCommunity's Manim. It is not an official
ManimCommunity project. Both upstream MIT notices are retained in `LICENSE` and
`LICENSE.community` and are included in release artifacts.

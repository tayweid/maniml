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

```bash
pip install git+https://github.com/tayweid/maniml.git
```

Or install from source:

```bash
git clone https://github.com/tayweid/maniml.git
cd maniml
pip install -e .
```

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
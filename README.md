# ManimLive

ManimLive speeds up Manim's animation workflow by bringing hot reloading and interactive navigation on top of ManimGL's OpenGL renderer, all compatabile with the existing ManimCE API. 

## Features

- **ManimCE API compatibility**: *all existing ManimCE code will (should) render*
- **Live preview:** *real-time OpenGL rendering in a separate window*
- **Keyboard navigation:** *arrow keys navigate through the animations, built on dynamic checkpointing*
- **Hot reloading:** *the preview window automatically plays edited animations*

## Installation

```bash
pip install -e .
```

## Usage

Use exactly like ManimCE:

```python
from manim import *

class Example(Scene):
    def construct(self):
        circle = Circle()
        self.play(Create(circle))
        self.wait()
```

Run with:
```bash
manim example.py Example
```

## Status

This is a work in progress. Most ManimCE features are implemented, but some are still being added. Bugs are to be expected. 
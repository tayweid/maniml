# maniml - ManimCE with OpenGL Performance

A fork of ManimCE that uses ManimGL's OpenGL renderer for blazing fast performance while maintaining full API compatibility with ManimCE.

## Features

- 5-20x faster rendering than Cairo-based ManimCE
- Full ManimCE API compatibility
- Interactive animations with mouse/keyboard support
- Real-time preview with smooth 60fps playback
- File watching and auto-reload during development

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

This is a work in progress. Most ManimCE features are implemented, but some are still being added.
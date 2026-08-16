"""Display-independent input constants used by ManimLive.

The native window backend forwards Pyglet's integer event values directly to
scenes. Keeping the small subset used by the scene and browser paths here
lets those paths work without importing ``pyglet.window``, which otherwise
tries to create an OpenGL shadow window at import time.

These values are part of Pyglet 2's public ``window.key`` and
``window.mouse`` APIs. A regression test checks them against the installed
Pyglet version so a future dependency change cannot silently break input.
"""


class WindowKeys:
    """Pyglet-compatible key symbols and modifier masks ManimLive uses."""

    MOD_SHIFT = 1 << 0
    MOD_CTRL = 1 << 1
    MOD_ALT = 1 << 2
    MOD_CAPSLOCK = 1 << 3
    MOD_COMMAND = 1 << 6

    BACKSPACE = 0xFF08
    TAB = 0xFF09
    ENTER = 0xFF0D
    ESCAPE = 0xFF1B
    LEFT = 0xFF51
    UP = 0xFF52
    RIGHT = 0xFF53
    DOWN = 0xFF54
    SPACE = 0x020


class MouseButtons:
    """Pyglet-compatible mouse button masks ManimLive uses."""

    LEFT = 1 << 0
    MIDDLE = 1 << 1
    RIGHT = 1 << 2

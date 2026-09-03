"""Key symbols, modifier masks, and mouse button masks for scene input.

These are maniml's own constants. Their integer values are the ones the
retired pyglet window used to deliver (pyglet 2's ``window.key`` and
``window.mouse``), kept so scene code, ``mobject/interactive.py``, and
recorded checkpoints that compare against them keep working; nothing
imports pyglet any more. The browser viewer maps DOM key names and
button indices onto them (``web/viewer.py``).
"""


class WindowKeys:
    """Key symbols and modifier masks the scene handlers compare against."""

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
    """Mouse button masks the scene handlers compare against."""

    LEFT = 1 << 0
    MIDDLE = 1 << 1
    RIGHT = 1 << 2

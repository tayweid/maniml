"""
maniml Utilities - CE-compatible utilities.
"""

from .config import config
from .rate_functions import *
from .tex_templates import TexTemplate, TexTemplateLibrary
from .window_utils import fix_spinning_cursor, WindowEventHandler

# Import color utilities from GL
from manim.utils.color import (
    interpolate_color,
    color_gradient,
    invert_color,
    color_to_rgb,
    rgb_to_color,
    color_to_rgba,
    rgba_to_color,
    rgb_to_hex,
    hex_to_rgb,
)

# Import updater utilities
from manim.mobject.mobject_update_utils import always_redraw, turn_animation_into_updater

__all__ = [
    "config", 
    "TexTemplate", 
    "TexTemplateLibrary",
    "interpolate_color",
    "color_gradient",
    "invert_color",
    "color_to_rgb",
    "rgb_to_color", 
    "color_to_rgba",
    "rgba_to_color",
    "rgb_to_hex",
    "hex_to_rgb",
    "always_redraw",
    "turn_animation_into_updater",
    "fix_spinning_cursor",
    "WindowEventHandler",
]
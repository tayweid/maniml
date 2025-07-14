"""
maniml - Manim Simple Edition

A streamlined version combining ManimCE's API with ManimGL's performance.
"""

__version__ = "0.1.0"
__author__ = "maniml Contributors"

# Fix spinning cursor issue - disable debug GL in pyglet
# This must be set before pyglet is imported by ManimGL
try:
    import pyglet
    pyglet.options['debug_gl'] = False
except ImportError:
    pass

# Core imports
from .constants import *
from .mobject import *
from .animation import *
from .scene import *
from .camera import *
from .utils import *

# Additional imports for convenience
from manim.mobject.shape_matchers import SurroundingRectangle

# Version info
def get_version():
    return __version__

# Print welcome message when imported interactively
if hasattr(__builtins__, '__IPYTHON__'):
    print(f"maniml v{__version__} - Simple, Fast, Beautiful")
    print("Using ManimGL backend for blazing performance!")
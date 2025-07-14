"""
Mobject module for maniml - Mathematical objects for animation

This __init__.py makes commonly used mobjects easily accessible.
Note: Not all mobjects are imported here to avoid circular imports.
Users can still import specific mobjects directly from their modules.
"""

# The most essential imports that are safe from circular dependencies
from .mobject import Mobject, Group, Point
from .types.vectorized_mobject import VMobject, VGroup

# We intentionally don't import everything here because:
# 1. It would create circular import issues (e.g., geometry imports from types)
# 2. It would slow down initial import time
# 3. Users typically use "from manim import *" which imports from the main __init__.py

# For other mobjects, users should import them as needed:
# from manim.mobject.geometry import Circle, Square, Arrow
# from manim.mobject.svg.tex_mobject import Tex
# from manim.mobject.svg.text_mobject import Text
# etc.

__all__ = ['Mobject', 'Group', 'Point', 'VMobject', 'VGroup']
"""
ValueTracker with CE compatibility.
"""

from manim.renderer.opengl.mobject.value_tracker import ValueTracker as GLValueTracker
from manim.renderer.opengl.mobject.value_tracker import ComplexValueTracker as GLComplexValueTracker


class ValueTracker(GLValueTracker):
    """CE-compatible ValueTracker - identical to GL version."""
    pass


class ComplexValueTracker(GLComplexValueTracker):
    """CE-compatible ComplexValueTracker - identical to GL version."""
    pass
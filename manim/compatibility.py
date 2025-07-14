"""
ManimCE Compatibility Layer for Maniml

This module provides mappings from ManimCE API to ManimGL implementation,
allowing CE code to run on the GL backend with minimal changes.
"""

from .animation.transform import Transform as _Transform
from .animation.creation import ShowCreation
from .animation.animation import Animation


# Animation Aliases
def Create(mobject, **kwargs):
    """CE-compatible alias for ShowCreation."""
    return ShowCreation(mobject, **kwargs)


def Uncreate(mobject, **kwargs):
    """CE-compatible reverse of Create."""
    return ShowCreation(mobject, rate_func=lambda t: 1-t, **kwargs)


def Write(mobject, **kwargs):
    """CE-compatible alias for ShowCreation (for text)."""
    return ShowCreation(mobject, **kwargs)


def Unwrite(mobject, **kwargs):
    """CE-compatible reverse of Write."""
    return ShowCreation(mobject, rate_func=lambda t: 1-t, **kwargs)


# Movement Animations
class Shift(_Transform):
    """Shift animation - moves mobject by a vector."""
    def __init__(self, mobject, direction, **kwargs):
        target = mobject.copy().shift(direction)
        super().__init__(mobject, target, **kwargs)


class MoveTo(_Transform):
    """MoveTo animation - moves mobject to a point or another mobject's position."""
    def __init__(self, mobject, point_or_mobject, **kwargs):
        target = mobject.copy()
        if hasattr(point_or_mobject, "get_center"):
            target.move_to(point_or_mobject.get_center())
        else:
            target.move_to(point_or_mobject)
        super().__init__(mobject, target, **kwargs)


class Scale(_Transform):
    """Scale animation - scales mobject by a factor."""
    def __init__(self, mobject, scale_factor, **kwargs):
        target = mobject.copy().scale(scale_factor)
        super().__init__(mobject, target, **kwargs)


class Rotate(_Transform):
    """Rotate animation - rotates mobject by an angle."""
    def __init__(self, mobject, angle, **kwargs):
        target = mobject.copy().rotate(angle)
        super().__init__(mobject, target, **kwargs)


# Special Animations
class Wait(Animation):
    """Wait animation - pauses for a duration."""
    def __init__(self, duration=1.0, **kwargs):
        super().__init__(None, run_time=duration, **kwargs)


# Text/Math Aliases
def MathTex(*args, **kwargs):
    """CE-compatible alias for Tex."""
    from .mobject.svg.tex_mobject import Tex
    return Tex(*args, **kwargs)


def Tex(*args, **kwargs):
    """Import Tex from the correct location."""
    from .mobject.svg.tex_mobject import Tex as _Tex
    return _Tex(*args, **kwargs)


def Text(*args, **kwargs):
    """Import Text from the correct location."""
    from .mobject.svg.text_mobject import Text as _Text
    return _Text(*args, **kwargs)


# Shape Aliases
def Circle(**kwargs):
    """Import Circle from the correct location."""
    from .mobject.geometry import Circle as _Circle
    return _Circle(**kwargs)


def Square(**kwargs):
    """Import Square from the correct location."""
    from .mobject.geometry import Square as _Square
    return _Square(**kwargs)


def Rectangle(**kwargs):
    """Import Rectangle from the correct location."""
    from .mobject.geometry import Rectangle as _Rectangle
    return _Rectangle(**kwargs)


def Dot(**kwargs):
    """Import Dot from the correct location."""
    from .mobject.geometry import Dot as _Dot
    return _Dot(**kwargs)


def Line(*args, **kwargs):
    """Import Line from the correct location."""
    from .mobject.geometry import Line as _Line
    return _Line(*args, **kwargs)


def Arrow(*args, **kwargs):
    """Import Arrow from the correct location."""
    from .mobject.geometry import Arrow as _Arrow
    return _Arrow(*args, **kwargs)


def Vector(*args, **kwargs):
    """Import Vector from the correct location."""
    from .mobject.geometry import Vector as _Vector
    return _Vector(*args, **kwargs)


# Group Aliases
def VGroup(*mobjects, **kwargs):
    """Import VGroup from the correct location."""
    from .mobject.types.vectorized_mobject import VGroup as _VGroup
    return _VGroup(*mobjects, **kwargs)


def Group(*mobjects, **kwargs):
    """Import Group from the correct location."""
    from .mobject.mobject import Group as _Group
    return _Group(*mobjects, **kwargs)


# Animation Imports
def FadeIn(*args, **kwargs):
    """Import FadeIn from the correct location."""
    from .animation.fading import FadeIn as _FadeIn
    return _FadeIn(*args, **kwargs)


def FadeOut(*args, **kwargs):
    """Import FadeOut from the correct location."""
    from .animation.fading import FadeOut as _FadeOut
    return _FadeOut(*args, **kwargs)


def Transform(*args, **kwargs):
    """Import Transform from the correct location."""
    from .animation.transform import Transform as _Transform
    return _Transform(*args, **kwargs)


def ReplacementTransform(*args, **kwargs):
    """Import ReplacementTransform from the correct location."""
    from .animation.transform import ReplacementTransform as _ReplacementTransform
    return _ReplacementTransform(*args, **kwargs)


# Composition Animations
def AnimationGroup(*animations, **kwargs):
    """Import AnimationGroup from the correct location."""
    from .animation.composition import AnimationGroup as _AnimationGroup
    return _AnimationGroup(*animations, **kwargs)


def Succession(*animations, **kwargs):
    """Import Succession from the correct location."""
    from .animation.composition import Succession as _Succession
    return _Succession(*animations, **kwargs)


def LaggedStart(*animations, **kwargs):
    """Import LaggedStart from the correct location."""
    from .animation.composition import LaggedStart as _LaggedStart
    return _LaggedStart(*animations, **kwargs)


# All CE-compatible exports
__all__ = [
    # Creation
    'Create', 'Uncreate', 'Write', 'Unwrite',
    # Movement
    'Shift', 'MoveTo', 'Scale', 'Rotate',
    # Special
    'Wait',
    # Text/Math
    'MathTex', 'Tex', 'Text',
    # Shapes
    'Circle', 'Square', 'Rectangle', 'Dot', 'Line', 'Arrow', 'Vector',
    # Groups
    'VGroup', 'Group',
    # Animations
    'FadeIn', 'FadeOut', 'Transform', 'ReplacementTransform',
    # Composition
    'AnimationGroup', 'Succession', 'LaggedStart',
]